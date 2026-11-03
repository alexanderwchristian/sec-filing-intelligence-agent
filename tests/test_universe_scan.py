"""Batching and workload-scope tests, without SEC network or paid model calls."""
import pytest

from filing_intel.intel_store import IntelStore
from filing_intel.intel_monitor import scan_intelligence
from filing_intel.universe import load_snapshots, _stock_universe
from filing_intel.universe_scan import ordered_watch_ids, batch_plan, run_batch


class EmptySec:
    def __init__(self):
        self.discovered = []

    def discover_filings(self, cik):
        self.discovered.append(cik)
        return []

    def fetch_document(self, cik, record):
        raise AssertionError("No documents exist in EmptySec")


def populate(db):
    stocks, funds = load_snapshots()
    with IntelStore(db) as store:
        for row in _stock_universe(stocks):
            store.add_watch("stock", row["cik"], row["name"], ticker=row["ticker"])
        for row in funds:
            store.add_watch("fund", int(row["cik"]), row["name"],
                            ticker=row["ticker"], series_id=row["series_id"],
                            class_id=row["class_id"])
    return stocks, funds


def test_interleaving_500_companies_and_50_distinct_funds():
    stocks, funds = load_snapshots()
    ids = ordered_watch_ids(stocks, funds)
    assert len(ids) == len(set(ids)) == 550
    assert len({x["cik"] for x in _stock_universe(stocks)}) == 500


def test_batch_plan_covers_550_once_and_interleaves_tracks(tmp_path):
    db = tmp_path / "pilot.sqlite3"
    populate(db)
    with IntelStore(db) as store:
        plans = [batch_plan(store, index=i, size=11) for i in range(50)]
    assert all(plan["batch_count"] == 50 for plan in plans)
    assert all(plan["selected_watches"] == 11 for plan in plans)
    assert all(sum(x["kind"] == "fund" for x in p["selected"]) == 1 for p in plans)
    assert all(sum(x["kind"] == "stock" for x in p["selected"]) == 10 for p in plans)
    all_ids = [wid for p in plans for wid in p["selected_watch_ids"]]
    assert len(set(all_ids)) == 550
    with IntelStore(db) as store:
        with pytest.raises(ValueError, match="out of range"):
            batch_plan(store, index=50, size=11)
        with pytest.raises(ValueError, match="size"):
            batch_plan(store, index=0, size=100)


def test_batch_missing_or_disabled_watch_refuses_partial_universe(tmp_path):
    db = tmp_path / "incomplete.sqlite3"
    with IntelStore(db) as store:
        store.add_watch("stock", 320193, "Apple")
        with pytest.raises(ValueError, match="550 required"):
            batch_plan(store)


def test_real_monitor_accepts_selected_batch_without_touching_other_entities(tmp_path):
    db = tmp_path / "monitor.sqlite3"
    client = EmptySec()
    with IntelStore(db) as store:
        a = store.add_watch("stock", 1, "Issuer A")
        b = store.add_watch("stock", 2, "Issuer B")
        result = scan_intelligence(store, client, since="2026-04-01",
                                   until="2026-11-03", watch_ids=[a])
        assert result["status"] == "completed"
        assert result["coverage"] == {
            "selected_watches": 1, "total_watches": 2,
            "complete_watchlist": False
        }
        assert client.discovered == [1]
        assert {x["watch_id"] for x in store.checkpoints()} == {a}
        with pytest.raises(ValueError, match="unknown watch ID"):
            scan_intelligence(store, client, watch_ids=["not-a-watch"])


def test_batch_runner_never_calls_model_and_never_claims_full_coverage(tmp_path, monkeypatch):
    db = tmp_path / "pilot.sqlite3"
    populate(db)
    monkeypatch.setenv("USE_SEMANTIC_DETECTORS", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-secret-not-used")
    client = EmptySec()
    report = run_batch(str(db), index=0, size=11,
                       since="2026-04-01", until="2026-11-03", client=client)
    assert report["status"] == "completed"
    assert report["scan"]["coverage"]["selected_watches"] == 11
    assert report["scan"]["coverage"]["total_watches"] == 550
    assert not report["scan"]["coverage"]["complete_watchlist"]
    assert len(client.discovered) == 11
    assert report["scan"]["stats"]["eligible_filings"] == 0
    monkeypatch.setenv("USE_SEMANTIC_DETECTORS", "1")
    with pytest.raises(ValueError, match="refuses"):
        run_batch(str(db), index=0, size=11, client=EmptySec())


def test_unbounded_scan_with_large_watchlist_fails_closed(tmp_path):
    client = EmptySec()
    with IntelStore(tmp_path / "many.sqlite3") as store:
        for i in range(1, 27):
            store.add_watch("stock", i, f"Company {i}")
        with pytest.raises(ValueError, match="explicit batches"):
            scan_intelligence(store, client)
        assert not store.runs()
        assert not client.discovered
