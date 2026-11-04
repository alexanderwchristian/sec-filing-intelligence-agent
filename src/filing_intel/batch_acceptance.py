"""Manual first-batch operational acceptance. No model or trace export calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import time

import requests

from .intel_evaluation import verify_grounding
from .intel_monitor import scan_intelligence
from .intel_store import IntelStore
from .sec import SecClient
from .universe import load_snapshots, resolve_universe, apply_universe
from .universe_scan import batch_plan


class BoundedSession(requests.Session):
    """Count actual attempts, including retries; stop this run on SEC denial.

    SecClient owns the serial 0.55-second spacing and bounded retry policy.
    Redirects are refused so they cannot escape the host or request budget.
    Audit contains no headers, contact identity, response body or credentials.
    """
    def __init__(self, max_requests=120):
        super().__init__()
        if not 1 <= max_requests <= 200:
            raise ValueError("Request budget must be from 1 to 200")
        self.max_requests = max_requests
        self.attempts = 0
        self.statuses = Counter()
        self.started = time.monotonic()
        self.stopped = None

    def get(self, url, **kwargs):
        if self.stopped:
            raise RuntimeError("SEC session stopped: " + self.stopped)
        if self.attempts >= self.max_requests:
            self.stopped = "request budget exhausted"
            raise RuntimeError(self.stopped)
        if not url.startswith(("https://www.sec.gov/", "https://data.sec.gov/")):
            raise ValueError("Only official SEC HTTPS URLs are permitted")
        self.attempts += 1
        response = super().get(url, allow_redirects=False, **kwargs)
        self.statuses[str(response.status_code)] += 1
        if response.status_code in (401, 403, 429) or 300 <= response.status_code < 400:
            self.stopped = f"HTTP {response.status_code}; operator review required"
            raise RuntimeError(self.stopped)
        return response

    def audit(self):
        return {"attempts": self.attempts, "max_requests": self.max_requests,
                "http_status_counts": dict(self.statuses), "stop_reason": self.stopped,
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
                "minimum_request_interval_seconds": 0.55}


def assess_batch(store, watch_ids, since, until):
    events = [e for e in store.events() if e["watch_id"] in watch_ids]
    grounding = verify_grounding(store, events)
    inventory, failures = [], []
    for wid in watch_ids:
        docs = store.filings(wid, limit=None)
        candidates = [e for e in events if e["watch_id"] == wid]
        paired = [e for e in candidates if e.get("baseline_accession")
                  and e["change_type"] in {"added", "revised", "removed"}]
        in_window = [d for d in docs if since <= d["filed"] <= until]
        inventory.append({"watch_id": wid, "documents": docs,
                          "in_window_documents": len(in_window),
                          "candidate_count": len(candidates),
                          "paired_candidate_count": len(paired)})
        if not in_window:
            failures.append(wid + ": no supported in-window document")
        if not paired:
            failures.append(wid + ": no before/after candidate; manual baseline review required")
    if not grounding["checked"] or grounding["failures"]:
        failures.append("Source quote grounding absent or failed")
    return {"inventory": inventory, "complete_candidate_evidence": events,
            "source_grounding": grounding, "failures": failures,
            "accuracy": {"status": "not_measured", "reason": "No independently labeled real filing benchmark"}}


def run_first_batch(db, since, until, client, identity_report):
    if any(os.getenv(flag, "0") != "0" for flag in
           ("USE_SEMANTIC_DETECTORS", "ENABLE_OPENAI_TRACING", "ENABLE_DAILY_AI_RESEARCH")):
        raise ValueError("First batch requires all model/research/tracing switches off")
    if date.fromisoformat(since) > date.fromisoformat(until):
        raise ValueError("Start date must precede end date")
    if Path(db).exists():
        raise ValueError("First batch requires a fresh database")
    stocks, funds = load_snapshots()
    identity = resolve_universe(stocks, funds, client)
    identity_report.parent.mkdir(parents=True, exist_ok=True)
    identity_report.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    if identity["status"] != "verified":
        return {"status": "failed", "failures": ["Official SEC identity verification failed; no scan attempted"]}
    apply_universe(db, identity)
    with IntelStore(db) as store:
        plan = batch_plan(store, index=0, size=11)
        ids = plan["selected_watch_ids"]
        initial = scan_intelligence(store, client, since=since, until=until,
                                    mode="on_demand", watch_ids=ids)
        result = assess_batch(store, ids, since, until)
        before = {e["event_id"] for e in result["complete_candidate_evidence"]}
        if initial["status"] == "completed":
            replay = scan_intelligence(store, client, since=since, until=until,
                                       mode="on_demand", watch_ids=ids)
            replay["event_ids_unchanged"] = before == {e["event_id"] for e in store.events()}
            if (replay["status"] != "completed" or not replay["event_ids_unchanged"]
                    or replay["stats"]["new_documents"] or replay["stats"]["new_events"]):
                result["failures"].append("Replay failed or changed stored results")
        else:
            result["failures"].append("Initial scan incomplete")
            replay = {"status": "skipped_incomplete_initial_scan"}
    return {**result, "status": "failed" if result["failures"] else "passed",
            "plan": plan, "initial": initial, "replay": replay,
            "note": "Operational acceptance only. Fund passage attribution needs manual review. No permission to scale is implied."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".filing-intel/first-batch.sqlite3")
    parser.add_argument("--since", required=True)
    parser.add_argument("--to", required=True)
    parser.add_argument("--max-requests", type=int, default=120)
    parser.add_argument("--report", type=Path, default=Path("artifacts/first-batch.json"))
    args = parser.parse_args(argv)
    session = BoundedSession(args.max_requests)
    try:
        result = run_first_batch(args.db, args.since, args.to,
                                 SecClient(session=session),
                                 args.report.with_name("first-batch-identities.json"))
    except Exception as exc:
        # Do not serialize exception messages that could include headers/contact data.
        result = {"status": "failed", "failures": [type(exc).__name__ + ": setup or identity request failed"]}
    result["sec_requests"] = session.audit()
    result["execution"] = {"source": "official_sec_http", "model_calls": 0,
                           "trace_export": "disabled", "accuracy_evaluation": "not_measured"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "failures": result["failures"],
                      "sec_requests": result["sec_requests"], "report": str(args.report)}, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
