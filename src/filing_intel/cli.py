"""Reproducible CLI for sample analysis, SEC fetches and regression evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ai import interpret_changes
from .detect import compare
from .evaluate import evaluate
from .models import Filing
from .reporting import to_markdown
from .sec import SecClient
from .store import Store
from .monitor import scan

ROOT = Path(__file__).resolve().parents[2]


def sample_pair() -> tuple[Filing, Filing]:
    old = (ROOT / "examples" / "synthetic_before.txt").read_text(encoding="utf-8")
    new = (ROOT / "examples" / "synthetic_after.txt").read_text(encoding="utf-8")
    return (Filing("Northstar Cloud Systems (fictional)", "10-K", "2024-02-20",
                   "synthetic://northstar/2024", old),
            Filing("Northstar Cloud Systems (fictional)", "10-K", "2025-02-20",
                   "synthetic://northstar/2025", new))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="filing-intel", description="Evidence-linked 10-K change detection")
    subs = parser.add_subparsers(dest="command", required=True)
    demo = subs.add_parser("demo", help="Run offline on fully synthetic, labeled example")
    live = subs.add_parser("live", help="Fetch latest two 10-Ks from official SEC EDGAR")
    live.add_argument("--company", required=True, help="Ticker or CIK, e.g., AAPL or 320193")
    evaluation = subs.add_parser("evaluate", help="Score regression fixtures")
    evaluation.add_argument("--fixtures", default=str(ROOT / "examples" / "evaluation_cases.json"))
    compare_files = subs.add_parser("compare", help="Compare local Item 1A sections")
    compare_files.add_argument("--old", required=True)
    compare_files.add_argument("--new", required=True)
    watchlist = subs.add_parser("watchlist", help="Manage durable issuer watchlist")
    watchlist.add_argument("action", choices=["add", "list", "disable"])
    watchlist.add_argument("--company", help="Issuer CIK or ticker")
    watchlist.add_argument("--name", help="Public issuer display name")
    scan_cmd = subs.add_parser("scan", help="Discover and compare watched 10-K filings")
    scan_cmd.add_argument("--since", help="Inclusive filing date; default replays monitoring window")
    scan_cmd.add_argument("--to", help="Inclusive filing date; defaults to today (UTC)")
    backfill = subs.add_parser("backfill", help="Replay an inclusive historical filing interval")
    backfill.add_argument("--from", dest="since", required=True)
    backfill.add_argument("--to", required=True)
    status = subs.add_parser("status", help="Full durable run/checkpoint status as JSON")
    results = subs.add_parser("results", help="Complete evidence-linked event inventory as JSON")
    results.add_argument("--run-id")
    results.add_argument("--include-superseded", action="store_true")
    for item in (watchlist, scan_cmd, backfill, status, results):
        item.add_argument("--db", default=".filing-intel/state.sqlite3", help="Durable SQLite path")
    for item in (demo, live, compare_files):
        item.add_argument("--format", choices=["markdown", "json"], default="markdown")
        item.add_argument("--out", help="Output path; defaults to stdout")
        item.add_argument("--ai", action="store_true", help="Optional LLM interpretation, requires API key")
    args = parser.parse_args(argv)
    try:
        if args.command in ("watchlist", "scan", "backfill", "status", "results"):
            with Store(args.db) as store:
                if args.command == "watchlist":
                    if args.action != "list" and not args.company:
                        raise ValueError("--company is required")
                    if args.action == "add":
                        if not args.name:
                            raise ValueError("--name is required")
                        if args.company.isdigit():
                            cik, provenance = int(args.company), "user-supplied CIK; issuer identity asserted by operator"
                        else:
                            cik = SecClient().resolve_cik(args.company)
                            provenance = "SEC company_tickers.json: " + args.company.upper()
                        store.add_watch(cik, args.name, provenance)
                    elif args.action == "disable":
                        if not args.company.isdigit():
                            raise ValueError("Disable by stored CIK")
                        store.disable_watch(int(args.company))
                    output = store.status()["watchlist"]
                elif args.command == "status":
                    output = store.status()
                elif args.command == "results":
                    output = store.results(run_id=args.run_id, include_superseded=args.include_superseded)
                else:
                    output = scan(store, SecClient(), since=args.since, until=args.to, mode=args.command)
                print(json.dumps(output, indent=2))
                return 0 if not isinstance(output, dict) or output.get("status", "completed") == "completed" else 2
        if args.command == "evaluate":
            print(json.dumps(evaluate(args.fixtures), indent=2))
            return 0
        if args.command == "demo":
            before, after = sample_pair()
        elif args.command == "live":
            before, after = SecClient().fetch_latest_pair(args.company)
        else:
            before = Filing("Local filing comparison", "10-K", "prior", "file://before",
                            Path(args.old).read_text(encoding="utf-8"))
            after = Filing("Local filing comparison", "10-K", "current", "file://after",
                           Path(args.new).read_text(encoding="utf-8"))
        report = compare(before, after)
        if args.ai:
            interpret_changes(report)
        output = json.dumps(report.to_dict(), indent=2) if args.format == "json" else to_markdown(report)
        if args.out:
            Path(args.out).write_text(output + ("\n" if args.format == "json" else ""), encoding="utf-8")
            print(f"Wrote {args.out}")
        else:
            print(output)
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

