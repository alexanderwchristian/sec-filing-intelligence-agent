"""Manual, bounded, independently source-grounded SEC evaluation harness.

Uses exactly two pinned, independently checked SEC filing accessions:
Apple Inc. 2026-11-02 Form 8-K and Vanguard 500 Index Fund / VOO 2026-04-28
Form 497K. This is a LIVE operational and quote-grounding test, NOT a
complete labeled detection benchmark. The optional AI phase investigates
only ONE finding with the existing bounded research agent.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .categories import canonical_text, detect_events, identity_status
from .intel_evaluation import evaluate_labeled, verify_grounding
from .intel_research import investigate_event
from .intel_store import IntelStore
from .intel_tracing import flush, step_span, workflow
from .sec import FilingRecord, SecClient, archive_url


# All identifiers, dates, document names, series and class verified on sec.gov.
PINNED_FILINGS = (
    {
        "kind": "stock", "cik": 320193, "name": "Apple Inc.",
        "record": FilingRecord("0000320193-26-000024", "2026-11-02",
                               "aapl-20261102.htm", "8-K", "2026-11-02"),
        "series_id": None, "class_id": None,
    },
    {
        "kind": "fund", "cik": 36405, "name": "Vanguard 500 Index Fund",
        "record": FilingRecord("0000036405-26-000183", "2026-04-28",
                               "f44783d1.htm", "497K"),
        "series_id": "S000002839", "class_id": "C000092055",
    },
)


def _gold_labels(path: str | None) -> list[dict]:
    if not path:
        return []
    with open(path, encoding="utf-8") as source:
        payload = json.load(source)
    labels = payload.get("labels", []) if isinstance(payload, dict) else payload
    if not isinstance(labels, list) or any(not isinstance(e, dict) for e in labels):
        raise ValueError("Gold file must contain a list of manually labeled events")
    # Empty or absent labels mean that event F1 is NOT measured.
    return labels


def evaluate_pinned(*, db: str, client=None, ai: bool = False,
                    gold_path: str | None = None) -> dict:
    if ai and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("AI run requires the OPENAI_API_KEY Actions secret")
    client = client or SecClient()
    report = {
        "test_type": "live_pinned_sec_documents",
        "source": "SEC EDGAR",
        "real_sec_accuracy_claim": False,
        "note": ("Two pinned actual public SEC documents, no inferred fund-class "
                 "identity or exhaustive detection recall. Unlabeled events "
                 "are never reported as precision/recall/F1."),
    }
    with workflow("SEC filings: live source grounding and bounded research",
                  {"suite": "pinned_stock_fund", "ai": str(ai).lower()}):
        with IntelStore(db) as store:
            loaded = []
            for item in PINNED_FILINGS:
                record = item["record"]
                url = archive_url(item["cik"], record)
                with step_span("sec_fetch_document", {
                    "cik": str(item["cik"]), "accession": record.accession,
                    "form": record.form
                }):
                    raw, html = client.fetch_document(item["cik"], record)
                with step_span("sec_normalize_and_detect", {
                    "accession": record.accession, "kind": item["kind"]
                }):
                    text = canonical_text(html)
                    if len(text) < 60:
                        raise ValueError("SEC document text too short: " + record.accession)
                    wid = store.add_watch(item["kind"], item["cik"], item["name"],
                                          series_id=item["series_id"],
                                          class_id=item["class_id"],
                                          identity_source="pinned official SEC index")
                    watch = store.watch(wid)
                    identity = identity_status(watch, text)
                    store.put_filing(wid, record, url, raw, text, identity)
                    doc = store.filing(wid, record.accession)
                    # These isolated first observations are not before/after changes.
                    findings = detect_events(watch, doc)
                    for event in findings:
                        store.put_event(event)
                loaded.append({
                    "kind": item["kind"], "accession": record.accession,
                    "form": record.form, "filed": record.filed,
                    "source_url": url, "bytes": len(raw),
                    "identity_status": identity, "candidate_count": len(findings),
                })
            events = store.events()
            with step_span("verify_exact_sec_quotes", {"event_count": len(events)}):
                grounding = verify_grounding(store, events)
            with step_span("score_independent_gold_labels", {
                "gold_supplied": str(bool(gold_path)).lower()
            }):
                scores = evaluate_labeled(_gold_labels(gold_path), events)
            report["filings"] = loaded
            report["candidate_counts"] = {
                kind: sum(e["kind"] == kind for e in events)
                for kind in ("fund", "stock")
            }
            report["source_grounding"] = grounding
            report["labeled_event_evaluation"] = scores
            report["ai_investigation"] = {"status": "not_requested"}
            # At most one AI research investigation, independently capped at
            # three read-only tool calls and 600 output tokens per model turn.
            if ai:
                candidates = [e for e in events if e["kind"] == "stock"
                              and e.get("new_evidence")]
                if not candidates:
                    raise RuntimeError("No grounded stock candidate available for AI research")
                event = candidates[0]
                with step_span("investigate_one_grounded_finding", {
                    "event_id": event["event_id"], "category": event["category"]
                }):
                    investigation = investigate_event(store, event["event_id"])
                report["ai_investigation"] = {
                    "event_id": event["event_id"],
                    "status": investigation["status"],
                    "model": os.getenv("RESEARCH_MODEL", "gpt-5-mini"),
                    "tool_calls": investigation["tool_calls"],
                    "token_usage": investigation["token_usage"],
                    "verified_observations": len(investigation["observations"]),
                    "uncertainties": investigation["uncertainties"][:3],
                }
            valid = (len(loaded) == 2 and grounding["checked"] > 0
                     and not grounding["failures"])
            if ai and report["ai_investigation"]["status"] in {
                    "ai_not_enabled", "research_unavailable"}:
                valid = False
            report["status"] = "passed" if valid else "failed"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Manual pinned real-SEC smoke, traces, optional AI")
    parser.add_argument("--db", default=".filing-intel/trace-eval.sqlite3")
    parser.add_argument("--report", default="artifacts/sec-trace-eval.json")
    parser.add_argument("--gold", help="Independently labeled complete public SEC event dataset")
    parser.add_argument("--ai", action="store_true", help="Allow ONE bounded API investigation")
    args = parser.parse_args(argv)
    # A failure still produces a redacted JSON artifact for diagnosis.
    try:
        result = evaluate_pinned(db=args.db, gold_path=args.gold, ai=args.ai)
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__,
                  "error": str(exc)[:300], "ai_requested": args.ai}
    try:
        flush()
    except Exception as exc:
        result["tracing_export"] = "failed: " + type(exc).__name__
        result["status"] = "failed"
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
