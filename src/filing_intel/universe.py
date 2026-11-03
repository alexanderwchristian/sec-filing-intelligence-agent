"""Reproducible S&P 500 + 50 fund/ETF pilot universe.

No AI calls. Snapshot validation is offline. SEC verification and watchlist
application are explicit operations using two official SEC ticker-map files.
The S&P list contains 503 securities, collapsed to 500 unique issuer CIKs.
Every sampled fund has a distinct SEC series ID and one tracked share class.
"""
from __future__ import annotations

from collections import Counter
import argparse
import csv
import json
import os
from pathlib import Path
import re
import sys

from .intel_store import IntelStore
from .sec import SecClient

ROOT = Path(__file__).resolve().parents[2]
STOCK_FILE = ROOT / "data" / "universes" / "sp500-2026-11-03.csv"
FUND_FILE = ROOT / "data" / "universes" / "fund50-2026-11-03.csv"
STOCK_SEC_URL = "https://www.sec.gov/files/company_tickers.json"
FUND_SEC_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SAMPLE_DATE = "2026-11-03"

EXPECTED_STOCK_SECURITIES = 503
EXPECTED_STOCK_ISSUERS = 500
EXPECTED_FUNDS = 50
EXPECTED_FUND_CATEGORIES = {
    "us_equity", "international_equity", "fixed_income",
    "sector_factor_active", "mutual_fund",
}


def _ticker(value: str) -> str:
    return value.upper().strip().replace(".", "-")


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"Unexpected CSV columns in {path.name}")
        rows = list(reader)
    if not rows or any(not all(isinstance(row[c], str) and row[c].strip()
                               for c in columns) for row in rows):
        raise ValueError(f"Missing or blank universe fields: {path.name}")
    return rows


def load_snapshots(stock_path: Path = STOCK_FILE,
                   fund_path: Path = FUND_FILE) -> tuple[list[dict], list[dict]]:
    stocks = _read_csv(Path(stock_path), ("symbol", "cik", "name", "sector"))
    funds = _read_csv(Path(fund_path), (
        "ticker", "name", "kind", "category", "provider",
        "cik", "series_id", "class_id"))
    if len(stocks) != EXPECTED_STOCK_SECURITIES:
        raise ValueError(f"Expected 503 S&P securities; got {len(stocks)}")
    if len({row["symbol"] for row in stocks}) != len(stocks):
        raise ValueError("Duplicate S&P security tickers")
    issuer_ids = {row["cik"] for row in stocks}
    if len(issuer_ids) != EXPECTED_STOCK_ISSUERS:
        raise ValueError(f"Expected 500 distinct stock issuer CIKs; got {len(issuer_ids)}")
    if any(not re.fullmatch(r"\d{10}", row["cik"]) or int(row["cik"]) <= 0
           for row in stocks):
        raise ValueError("Invalid S&P issuer CIK")
    sectors = {row["sector"] for row in stocks}
    if len(sectors) != 11:
        raise ValueError("Expected all 11 S&P index sectors")
    if len(funds) != EXPECTED_FUNDS:
        raise ValueError(f"Expected 50 fund/ETF tickers; got {len(funds)}")
    if len({row["ticker"] for row in funds}) != EXPECTED_FUNDS:
        raise ValueError("Fund class tickers must be unique")
    if len({row["series_id"] for row in funds}) != EXPECTED_FUNDS:
        raise ValueError("Fund/ETF sample must represent 50 DISTINCT fund series")
    if len({row["class_id"] for row in funds}) != EXPECTED_FUNDS:
        raise ValueError("Fund class IDs must be unique")
    if {row["category"] for row in funds} != EXPECTED_FUND_CATEGORIES:
        raise ValueError("Missing a required fund/ETF sample category")
    counts = Counter(row["category"] for row in funds)
    if any(counts[key] != 10 for key in EXPECTED_FUND_CATEGORIES):
        raise ValueError("Expected exactly 10 sampled funds in each category")
    if sum(row["kind"] == "etf" for row in funds) != 40:
        raise ValueError("Expected 40 ETF and 10 mutual fund class tickers")
    if any((row["kind"] not in {"etf", "mutual_fund"} or
            not re.fullmatch(r"\d{10}", row["cik"]) or
            not re.fullmatch(r"S\d{9}", row["series_id"]) or
            not re.fullmatch(r"C\d{9}", row["class_id"]))
           for row in funds):
        raise ValueError("Malformed SEC identifiers or fund kind")
    # Preserve the identity/sector snapshot instead of silently replacing
    # historical sample membership with an index's future composition.
    return stocks, funds


def _stock_map(data: dict) -> dict[str, set[int]]:
    if not isinstance(data, dict) or not data:
        raise ValueError("Malformed official SEC company tickers map")
    out: dict[str, set[int]] = {}
    for row in data.values():
        if not isinstance(row, dict):
            raise ValueError("Malformed SEC company ticker row")
        ticker = row.get("ticker")
        cik = row.get("cik_str")
        if not ticker or not str(cik).isdigit():
            continue
        out.setdefault(_ticker(str(ticker)), set()).add(int(cik))
    if len(out) < 500:
        raise ValueError("SEC company tickers map unexpectedly small")
    return out


def _fund_map(data: dict) -> dict[str, set[tuple[int, str, str]]]:
    if not isinstance(data, dict) or not isinstance(data.get("fields"), list):
        raise ValueError("Malformed official SEC fund ticker map")
    fields = [str(f).lower().replace("_", "") for f in data["fields"]]
    required = ("cik", "seriesid", "classid", "ticker")
    if not set(required).issubset(fields):
        raise ValueError("SEC fund ticker map missing CIK, series, class or ticker")
    indexes = {key: fields.index(key) for key in required}
    rows = data.get("data")
    if not isinstance(rows, list) or len(rows) < 50:
        raise ValueError("SEC fund ticker map unexpectedly small")
    out: dict[str, set[tuple[int, str, str]]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < len(fields):
            raise ValueError("Malformed SEC fund ticker row")
        ticker = str(row[indexes["ticker"]] or "").strip()
        cik = str(row[indexes["cik"]] or "")
        series = str(row[indexes["seriesid"]] or "")
        class_id = str(row[indexes["classid"]] or "")
        if not ticker or not cik.isdigit():
            continue
        if re.fullmatch(r"S\d{9}", series) and re.fullmatch(r"C\d{9}", class_id):
            out.setdefault(_ticker(ticker), set()).add((int(cik), series, class_id))
    return out


def _stock_universe(stocks: list[dict]) -> list[dict]:
    by_cik: dict[int, dict] = {}
    for row in stocks:
        cik = int(row["cik"])
        if cik not in by_cik:
            by_cik[cik] = {
                "kind": "stock", "cik": cik, "name": row["name"],
                "ticker": row["symbol"], "tickers": [],
                "sector": row["sector"], "snapshot_date": SAMPLE_DATE,
            }
        by_cik[cik]["tickers"].append(row["symbol"])
    for row in by_cik.values():
        row["tickers"].sort()
    return sorted(by_cik.values(), key=lambda r: (r["sector"], r["name"]))


def resolve_universe(stocks: list[dict], funds: list[dict], client) -> dict:
    """Verify every ticker/CIK/class against the SEC before applying ANY writes."""
    sec_stocks = _stock_map(client._get(STOCK_SEC_URL).json())
    sec_funds = _fund_map(client._get(FUND_SEC_URL).json())
    problems: list[dict] = []
    for row in stocks:
        expected = int(row["cik"])
        current = sec_stocks.get(_ticker(row["symbol"]), set())
        if current != {expected}:
            problems.append({
                "kind": "stock", "ticker": row["symbol"],
                "expected_cik": expected, "sec_ciks": sorted(current),
                "issue": "ticker_CIK_mismatch_or_missing"
            })
    for row in funds:
        expected = (int(row["cik"]), row["series_id"], row["class_id"])
        current = sec_funds.get(_ticker(row["ticker"]), set())
        if current != {expected}:
            problems.append({
                "kind": "fund", "ticker": row["ticker"],
                "expected": {"cik": expected[0], "series": expected[1],
                             "class": expected[2]},
                "sec_matches": [
                    {"cik": cik, "series": series, "class": class_id}
                    for cik, series, class_id in sorted(current)
                ],
                "issue": "fund_class_identity_mismatch_or_missing"
            })
    return {
        "status": "verified" if not problems else "blocked_identity_mismatch",
        "snapshot_date": SAMPLE_DATE,
        "stock_securities": len(stocks),
        "stock_issuer_watches": len({row["cik"] for row in stocks}),
        "fund_class_watches": len(funds),
        "unique_fund_series": len({r["series_id"] for r in funds}),
        "fund_categories": dict(sorted(Counter(r["category"] for r in funds).items())),
        "sec_sources": [STOCK_SEC_URL, FUND_SEC_URL],
        "identity_issues": problems,
        "stocks": _stock_universe(stocks),
        "funds": [{**row, "kind": "fund"} for row in funds],
        "note": ("SEC ticker mappings verify registrant and class identifiers, "
                 "NOT fund text attribution, detector recall, class-level "
                 "evidence, or current S&P index membership.")
    }


def apply_universe(db: str, result: dict) -> dict:
    """Fail atomically on identity mismatches, then add all requested watches."""
    if result["status"] != "verified" or result["identity_issues"]:
        raise ValueError("SEC identity verification failed: no watchlist changes applied")
    if len(result["stocks"]) != 500 or len(result["funds"]) != 50:
        raise ValueError("Expected complete 500+50 verified watch sample")
    with IntelStore(db) as store:
        before = {r["watch_id"] for r in store.watches()}
        for r in result["stocks"]:
            store.add_watch("stock", r["cik"], r["name"], ticker=r["ticker"],
                            identity_source=f"S&P 500 {SAMPLE_DATE} snapshot; SEC ticker verified")
        for r in result["funds"]:
            store.add_watch("fund", int(r["cik"]), r["name"],
                            ticker=r["ticker"], series_id=r["series_id"],
                            class_id=r["class_id"],
                            identity_source=f"SEC mutual fund ticker map; {SAMPLE_DATE} sample")
        now = {r["watch_id"] for r in store.watches()}
        active = store.watches(enabled_only=True)
    return {
        "status": "applied",
        "new_watches": len(now - before),
        "pilot_watch_count": 550,
        "active_watchlist_size": len(active),
        "stock_issuer_watches": 500,
        "fund_class_watches": 50,
        "warning": ("Application only populates the durable watchlist. "
                    "It does NOT fetch 550 entities or validate detected changes.")
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="S&P 500 and 50-fund SEC pilot universe")
    p.add_argument("--mode", choices=["validate", "verify", "apply"], default="validate")
    p.add_argument("--stock-csv", type=Path, default=STOCK_FILE)
    p.add_argument("--fund-csv", type=Path, default=FUND_FILE)
    p.add_argument("--db", default=os.getenv("INTEL_DB_PATH",
                                            ".filing-intel/intelligence.sqlite3"))
    p.add_argument("--report", type=Path, default=Path("artifacts/universe-resolution.json"))
    args = p.parse_args(argv)
    try:
        stocks, funds = load_snapshots(args.stock_csv, args.fund_csv)
        result = {
            "status": "snapshot_validated", "snapshot_date": SAMPLE_DATE,
            "stock_securities": len(stocks), "stock_issuer_watches": 500,
            "fund_class_watches": len(funds),
            "unique_fund_series": len({r["series_id"] for r in funds}),
            "fund_categories": dict(sorted(Counter(r["category"] for r in funds).items())),
            "identity_issues": [],
            "note": "Offline snapshot structure only. SEC identities NOT freshly checked."
        }
        if args.mode != "validate":
            result = resolve_universe(stocks, funds, SecClient())
        if args.mode == "apply" and result["status"] == "verified":
            result["application"] = apply_universe(args.db, result)
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__,
                  "message": str(exc)[:700]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {key: val for key, val in result.items()
               if key not in {"stocks", "funds", "identity_issues"}}
    summary["identity_issue_count"] = len(result.get("identity_issues", []))
    summary["report"] = str(args.report)
    print(json.dumps(summary, indent=2))
    return 0 if result["status"] in {"snapshot_validated", "verified"} else 2


if __name__ == "__main__":
    sys.exit(main())
