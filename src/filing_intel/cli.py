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
    for item in (demo, live, compare_files):
        item.add_argument("--format", choices=["markdown", "json"], default="markdown")
        item.add_argument("--out", help="Output path; defaults to stdout")
        item.add_argument("--ai", action="store_true", help="Optional LLM interpretation, requires API key")
    args = parser.parse_args(argv)
    try:
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
