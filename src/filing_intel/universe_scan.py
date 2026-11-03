"""Run one bounded batch of the frozen 500-stock + 50-fund watch universe.

All 550 identities must already be added to persistent SQLite with
"filing-intel-universe --mode apply". A successful one-batch scan does not
represent complete universe coverage or real event detection recall.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import sys

from .intel_monitor import scan_intelligence
from .intel_store import IntelStore, stable_id
from .sec import SecClient
from .universe import load_snapshots, _stock_universe, SAMPLE_DATE


MAX_BATCH_SIZE = 25


def ordered_watch_ids(stocks: list[dict], funds: list[dict]) -> list[str]:
    """Spread the 50 funds across 500 stocks for mixed small batches."""
    unique_stocks = _stock_universe(stocks)
    fund_rows = sorted(funds, key=lambda row: (row["category"], row["ticker"]))
    assert len(unique_stocks) == 500 and len(fund_rows) == 50
    ids = []
    for i, fund in enumerate(fund_rows):
        block = unique_stocks[10*i:10*(i+1)]
        ids.extend(stable_id("us-sec", "stock", stock["cik"], "", "")
                   for stock in block)
        ids.append(stable_id("us-sec", "fund", int(fund["cik"]),
                             fund["series_id"], fund["class_id"]))
    if len(ids) != 550 or len(set(ids)) != 550:
        raise ValueError("Expected 550 unique SEC watch IDs")
    return ids


def batch_plan(store: IntelStore, *, index: int = 0,
               size: int = 10) -> dict:
    if not 1 <= size <= MAX_BATCH_SIZE:
        raise ValueError("Batch size must be from 1 to 25")
    if index < 0:
        raise ValueError("Batch index cannot be negative")
    stocks, funds = load_snapshots()
    watch_ids = ordered_watch_ids(stocks, funds)
    live = {r["watch_id"]: r for r in store.watches(enabled_only=True)}
    missing = [wid for wid in watch_ids if wid not in live]
    if missing:
        raise ValueError(
            f"Only {550-len(missing)} of 550 required pilot watches are enabled; "
            "first verify and apply the full SEC universe with filing-intel-universe.")
    total_batches = math.ceil(len(watch_ids)/size)
    if index >= total_batches:
        raise ValueError(f"Batch index out of range: 0 to {total_batches-1}")
    selected = watch_ids[index*size:(index+1)*size]
    return {
        "snapshot_date": SAMPLE_DATE, "batch_index": index,
        "batch_size": size, "batch_count": total_batches,
        "selected_watches": len(selected),
        "total_universe_watches": len(watch_ids),
        "selected_watch_ids": selected,
        "selected": [{"kind": live[wid]["kind"], "name": live[wid]["name"],
                      "ticker": live[wid]["ticker"], "cik": live[wid]["cik"],
                      "series_id": live[wid]["series_id"],
                      "class_id": live[wid]["class_id"]}
                     for wid in selected],
        "complete_universe_coverage": False,
        "note": "One batch only, not all 550 watches. No model research."
    }


def run_batch(db: str, *, index: int = 0, size: int = 10,
              since: str | None = None, until: str | None = None,
              client=None) -> dict:
    if os.getenv("USE_SEMANTIC_DETECTORS", "0") == "1":
        raise ValueError("Pilot batch refuses paid semantic detectors")
    with IntelStore(db) as store:
        plan = batch_plan(store, index=index, size=size)
        sec = client or SecClient()
        scan = scan_intelligence(store, sec, since=since, until=until,
                                 mode="on_demand",
                                 watch_ids=plan["selected_watch_ids"])
    result = {
        "status": scan["status"], "universe": "S&P 500 plus 50 funds/ETFs",
        "plan": plan,
        "scan": scan,
        "sample_scope": "one bounded batch",
        "note": ("This run proves neither full-universe completion nor "
                 "independently measured detection accuracy. Fund events remain "
                 "subject to class/series attribution review.")
    }
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="One bounded no-AI SEC universe scan batch")
    p.add_argument("--db", default=os.getenv("INTEL_DB_PATH",
                                             ".filing-intel/intelligence.sqlite3"))
    p.add_argument("--batch-index", type=int, default=0)
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--since", default=(date.today()-timedelta(days=90)).isoformat())
    p.add_argument("--to", default=date.today().isoformat())
    p.add_argument("--report", type=Path, default=Path("artifacts/universe-batch.json"))
    args = p.parse_args(argv)
    try:
        result = run_batch(args.db, index=args.batch_index, size=args.batch_size,
                           since=args.since, until=args.to)
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__,
                  "message": str(exc)[:700],
                  "note": "Batch failure is never interpreted as no SEC changes"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    summary = {k: v for k, v in result.items() if k != "scan"}
    if "scan" in result:
        summary["scan_stats"] = result["scan"]["stats"]
        summary["scan_coverage"] = result["scan"]["coverage"]
        summary["scan_errors"] = result["scan"]["errors"][:10]
    print(json.dumps(summary, indent=2))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
