"""Operator-only, no-LLM acceptance for real fund/stock SEC discovery and replay."""
from __future__ import annotations
import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys

from filing_intel.categories import FUND_FORMS, STOCK_FORMS
from filing_intel.intel_evaluation import verify_grounding
from filing_intel.intel_monitor import scan_intelligence
from filing_intel.intel_store import IntelStore
from filing_intel.sec import SecClient
from filing_intel.intel_tracing import flush


def run_acceptance(*, stock_cik: int, fund_cik: int, fund_name: str,
                   since: str, until: str, db: str,
                   stock_name: str = "Public stock issuer",
                   series_id: str | None = None, class_id: str | None = None,
                   client=None) -> dict:
    if os.getenv("USE_SEMANTIC_DETECTORS", "0") == "1":
        raise ValueError("Acceptance refuses USE_SEMANTIC_DETECTORS=1; disable AI")
    if date.fromisoformat(since) > date.fromisoformat(until):
        raise ValueError("The --since date must not be after --to")
    path = Path(db).expanduser().resolve()
    if path.exists():
        raise ValueError("Acceptance requires a fresh database. Choose a new --db path")
    client = client or SecClient()
    failures = []
    with IntelStore(path) as store:
        watches = {
            "stock": store.add_watch("stock", stock_cik, stock_name),
            "fund": store.add_watch("fund", fund_cik, fund_name,
                                    series_id=series_id, class_id=class_id)
        }
        initial = scan_intelligence(store, client, since=since, until=until,
                                    mode="on_demand")
        events = store.events()
        first_ids = {e["event_id"] for e in events}
        grounding = verify_grounding(store, events)
        inventory, candidate_counts, paired_counts, evidence = {}, {}, {}, []
        for kind, wid in watches.items():
            forms = STOCK_FORMS if kind == "stock" else FUND_FORMS
            docs = store.filings(wid, limit=None)
            in_window = [d for d in docs if since <= d["filed"] <= until
                         and d["form"] in forms]
            candidates = [e for e in events if e["watch_id"] == wid
                          and since <= e["filing_date"] <= until]
            paired = [e for e in candidates if e.get("baseline_accession")
                      and e["change_type"] in {"added", "revised", "removed"}]
            inventory[kind] = {
                "stored_documents_including_baselines": len(docs),
                "eligible_in_window": len(in_window),
                "forms": sorted({d["form"] for d in in_window}),
                "source_urls": [d["source_url"] for d in in_window],
                "identity_statuses": sorted({d["identity_status"] for d in docs}),
            }
            candidate_counts[kind], paired_counts[kind] = len(candidates), len(paired)
            if not in_window:
                failures.append(kind + ": no supported SEC filing in requested window")
            if not candidates:
                failures.append(kind + ": no source-backed candidate in requested window")
            if not paired:
                failures.append(kind + ": no candidate compared with an earlier baseline")
            evidence.extend(candidates)
        if initial["status"] != "completed":
            failures.append("initial scan incomplete: " + initial["status"])
        if not grounding["checked"]:
            failures.append("no source excerpts checked")
        if grounding["failures"] or grounding["checked"] != grounding["verified"]:
            failures.append("one or more event quotes did not match persisted SEC text")
        if initial["status"] == "completed":
            second = scan_intelligence(store, client, since=since, until=until,
                                       mode="on_demand")
            replay_ids = {e["event_id"] for e in store.events()}
            replay = {
                "run_id": second["run_id"], "status": second["status"],
                "new_documents": second["stats"]["new_documents"],
                "new_events": second["stats"]["new_events"],
                "event_ids_unchanged": replay_ids == first_ids,
                "errors": second["errors"]
            }
            if second["status"] != "completed":
                failures.append("replay incomplete: " + second["status"])
            if replay["new_documents"] or replay["new_events"]:
                failures.append("replay generated new documents or events")
            if not replay["event_ids_unchanged"]:
                failures.append("replay changed immutable event identifiers")
        else:
            replay = {"status": "skipped_incomplete_initial_scan"}
        return {
            "status": "passed" if not failures else "failed",
            "run": initial, "window": {"since": since, "to": until},
            "inventory": inventory, "candidate_counts": candidate_counts,
            "paired_baseline_candidates": paired_counts,
            "source_grounding": grounding, "replay": replay,
            "complete_candidate_evidence": evidence, "failures": failures,
            "note": ("Operational source-and-replay acceptance only; no labeled "
                     "precision/recall, confirmed economic materiality, or "
                     "verified fund share-class attribution.")
        }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="No-AI dual-track SEC acceptance")
    p.add_argument("--stock-cik", type=int, required=True)
    p.add_argument("--fund-cik", type=int, required=True)
    p.add_argument("--stock-name", default="Public stock issuer")
    p.add_argument("--fund-name", required=True)
    p.add_argument("--series-id")
    p.add_argument("--class-id")
    p.add_argument("--since", default=(date.today()-timedelta(days=365)).isoformat())
    p.add_argument("--to", default=date.today().isoformat())
    p.add_argument("--db", default=".filing-intel/live-dual-acceptance.sqlite3")
    p.add_argument("--report", default="artifacts/live-dual-track-acceptance.json")
    args = p.parse_args(argv)
    try:
        result = run_acceptance(
            stock_cik=args.stock_cik, fund_cik=args.fund_cik,
            stock_name=args.stock_name, fund_name=args.fund_name,
            series_id=args.series_id, class_id=args.class_id,
            since=args.since, until=args.to, db=args.db)
    except Exception as exc:
        result = {"status": "failed", "failures": [
            type(exc).__name__ + ": " + str(exc)[:500]]}
    try:
        flush()
    except Exception as exc:
        result["status"] = "failed"
        result.setdefault("failures", []).append("Trace export error: " + type(exc).__name__)
    output = Path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "report": str(output),
        "candidate_counts": result.get("candidate_counts"),
        "paired_baseline_candidates": result.get("paired_baseline_candidates"),
        "source_grounding": result.get("source_grounding"),
        "replay": result.get("replay"),
        "failures": result.get("failures", [])
    }, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
