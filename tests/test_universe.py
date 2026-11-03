"""Complete 500+50 pilot manifests and SEC-identity gate tests. All offline."""
import copy
import csv
import json

import pytest

from filing_intel.intel_store import IntelStore
from filing_intel.universe import (
    STOCK_FILE, FUND_FILE, load_snapshots,
    _fund_map, resolve_universe, apply_universe, main
)


class Reply:
    def __init__(self, value):
        self.value = value

    def json(self):
        return self.value


class FakeSecMaps:
    """Construct full mock SEC maps from the checked-in independent snapshots."""
    def __init__(self, stocks, funds):
        self.stock_rows = {
            str(i): {"ticker": stock["symbol"].replace(".", "-"),
                     "cik_str": int(stock["cik"]), "title": stock["name"]}
            for i, stock in enumerate(stocks)
        }
        self.fund_rows = {
            "fields": ["cik", "seriesId", "classId", "ticker"],
            "data": [
                [int(fund["cik"]), fund["series_id"], fund["class_id"], fund["ticker"]]
                for fund in funds
            ]
        }
        self.urls = []

    def _get(self, url):
        self.urls.append(url)
        if url.endswith("company_tickers_mf.json"):
            return Reply(self.fund_rows)
        if url.endswith("company_tickers.json"):
            return Reply(self.stock_rows)
        raise AssertionError("Unexpected request: " + url)


def test_manifest_is_503_securities_500_unique_companies_and_50_distinct_funds():
    stocks, funds = load_snapshots()
    assert len(stocks) == 503
    assert len({row["cik"] for row in stocks}) == 500
    assert len({row["symbol"] for row in stocks}) == 503
    assert len({row["sector"] for row in stocks}) == 11
    assert len(funds) == 50
    assert len({row["series_id"] for row in funds}) == 50
    assert len({row["class_id"] for row in funds}) == 50
    assert sum(fund["kind"] == "etf" for fund in funds) == 40
    assert sum(fund["kind"] == "mutual_fund" for fund in funds) == 10
    assert len({row["provider"] for row in funds}) >= 8


def test_offline_validate_cli_does_not_call_network_or_change_db(tmp_path, monkeypatch, capsys):
    import filing_intel.universe as module
    def fail(*a, **k):
        raise AssertionError("SEC client must not be instantiated in validation mode")
    monkeypatch.setattr(module, "SecClient", fail)
    db = tmp_path / "uncreated.sqlite3"
    output = tmp_path / "report.json"
    assert main(["--mode", "validate", "--db", str(db),
                 "--report", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["status"] == "snapshot_validated"
    assert report["stock_issuer_watches"] == 500
    assert report["fund_class_watches"] == 50
    assert not db.exists()


def test_sec_reverification_resolves_and_applies_all_550_without_duplicates(tmp_path):
    stocks, funds = load_snapshots()
    client = FakeSecMaps(stocks, funds)
    result = resolve_universe(stocks, funds, client)
    assert result["status"] == "verified"
    assert not result["identity_issues"]
    assert len(client.urls) == 2
    assert len(result["stocks"]) == 500
    assert len(result["funds"]) == 50
    db = str(tmp_path / "pilot.sqlite3")
    applied = apply_universe(db, result)
    assert applied["new_watches"] == 550
    again = apply_universe(db, result)
    assert again["new_watches"] == 0
    with IntelStore(db) as store:
        watches = store.watches()
        assert len(watches) == 550
        assert sum(w["kind"] == "stock" for w in watches) == 500
        assert sum(w["kind"] == "fund" for w in watches) == 50
        assert all(w["identity_source"] for w in watches)


def test_sec_identity_mismatch_blocks_all_writes(tmp_path):
    stocks, funds = load_snapshots()
    client = FakeSecMaps(stocks, funds)
    client.stock_rows["0"]["cik_str"] = 99999999
    client.fund_rows["data"][0][2] = "C999999999"
    result = resolve_universe(stocks, funds, client)
    assert result["status"] == "blocked_identity_mismatch"
    assert len(result["identity_issues"]) == 2
    db = str(tmp_path / "should_not_exist.sqlite3")
    with pytest.raises(ValueError, match="SEC identity verification"):
        apply_universe(db, result)
    assert not (tmp_path / "should_not_exist.sqlite3").exists()


def test_fund_map_requires_series_and_class():
    with pytest.raises(ValueError, match="missing"):
        _fund_map({"fields": ["cik", "ticker"],
                   "data": [[123, "VOO"]]})
    with pytest.raises(ValueError, match="small"):
        _fund_map({"fields": ["cik", "seriesId", "classId", "ticker"],
                   "data": []})


def test_duplicate_fund_series_is_rejected_before_network(tmp_path):
    _, funds = load_snapshots()
    with FUND_FILE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0])
    rows[1]["series_id"] = rows[0]["series_id"]
    modified = tmp_path / "duplicates.csv"
    with modified.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="DISTINCT fund series"):
        load_snapshots(STOCK_FILE, modified)
