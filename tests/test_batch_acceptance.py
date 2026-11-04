"""Offline acceptance regression; these are not live SEC accuracy results."""
import pytest
import requests

from filing_intel.batch_acceptance import BoundedSession, assess_batch, run_first_batch
from filing_intel.intel_store import IntelStore
from filing_intel.intel_monitor import scan_intelligence
from test_pilot_acceptance import FakeSEC
from test_pilot_acceptance import rec
from test_universe import FakeSecMaps
from filing_intel.universe import load_snapshots


def test_empty_completed_scan_cannot_pass(tmp_path):
    with IntelStore(tmp_path / "test.sqlite3") as store:
        wid = store.add_watch("stock", 1, "Synthetic")
        report = assess_batch(store, [wid], "2025-01-01", "2025-12-31")
    assert report["failures"]
    assert report["source_grounding"]["checked"] == 0
    assert report["accuracy"]["status"] == "not_measured"


def test_http_budget_counts_attempts_and_stops_on_throttle(monkeypatch):
    calls = []
    def get(self, url, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = 429
        return response
    monkeypatch.setattr(requests.Session, "get", get)
    session = BoundedSession(max_requests=2)
    with pytest.raises(RuntimeError, match="429"):
        session.get("https://www.sec.gov/files/company_tickers.json")
    with pytest.raises(RuntimeError, match="stopped"):
        session.get("https://www.sec.gov/files/company_tickers.json")
    assert len(calls) == session.audit()["attempts"] == 1


def test_http_budget_exhaustion_and_redirects(monkeypatch):
    def get(self, url, **kwargs):
        assert kwargs["allow_redirects"] is False
        response = requests.Response()
        response.status_code = 200
        return response
    monkeypatch.setattr(requests.Session, "get", get)
    session = BoundedSession(max_requests=1)
    session.get("https://data.sec.gov/submissions/CIK0000000001.json")
    with pytest.raises(RuntimeError, match="budget"):
        session.get("https://data.sec.gov/submissions/CIK0000000001.json")
    assert session.audit()["attempts"] == 1


def test_paired_sources_assessed_and_missing_baseline_fails(tmp_path, monkeypatch):
    with IntelStore(tmp_path / "test.sqlite3") as store:
        ids = [store.add_watch("stock", 1, "Synthetic Issuer"),
               store.add_watch("fund", 2, "Northstar Growth Fund",
                               series_id="S000000001", class_id="C000000001")]
        scan_intelligence(store, FakeSEC(), since="2025-01-01", until="2025-12-31")
        result = assess_batch(store, ids, "2025-01-01", "2025-12-31")
        assert not result["failures"]
        assert len(result["inventory"]) == 2
        assert result["source_grounding"]["checked"] == result["source_grounding"]["verified"]
        assert result["complete_candidate_evidence"]
        original = store.filing
        monkeypatch.setattr(store, "filing", lambda wid, accession:
                            None if "-24-" in accession else original(wid, accession))
        assert assess_batch(store, ids, "2025-01-01", "2025-12-31")["failures"]


def test_full_first_batch_gate_and_replay_are_bounded(tmp_path, monkeypatch):
    for flag in ("USE_SEMANTIC_DETECTORS", "ENABLE_OPENAI_TRACING", "ENABLE_DAILY_AI_RESEARCH"):
        monkeypatch.setenv(flag, "0")
    stocks, funds = load_snapshots()
    class Client(FakeSecMaps):
        def __init__(self):
            super().__init__(stocks, funds)
            self.discovered = []
            self.fetches = 0
        def discover_filings(self, cik):
            self.discovered.append(cik)
            kind = "10-K" if cik in {int(s["cik"]) for s in stocks} else "485BPOS"
            return [rec(cik, 2024, kind), rec(cik, 2025, kind)]
        def fetch_document(self, cik, record):
            self.fetches += 1
            text = ("<p>Total revenue was " + ("20" if "-24-" in record.accession else "30")
                    + " million from global cloud services and recurring applications. "
                    + "The annual management fee is "
                    + ("0.50" if "-24-" in record.accession else "0.65") + " percent.</p>")
            return text.encode(), text
    client = Client()
    db = str(tmp_path / "batch.sqlite3")
    report = run_first_batch(db, "2025-01-01", "2025-12-31", client,
                             tmp_path / "identities.json")
    assert report["status"] == "passed", report["failures"]
    assert len(set(client.discovered)) == 11
    assert len(client.discovered) == 22
    assert client.fetches == 22  # replay fetches inventory only, no documents
    assert report["replay"]["stats"]["new_documents"] == 0
    assert report["replay"]["stats"]["new_events"] == 0
    assert report["replay"]["event_ids_unchanged"]
    assert sum(x["kind"] == "fund" for x in report["plan"]["selected"]) == 1
    with pytest.raises(ValueError, match="fresh"):
        run_first_batch(db, "2025-01-01", "2025-12-31", client, tmp_path / "unused.json")


def test_identity_failure_prevents_all_filing_requests(tmp_path):
    stocks, funds = load_snapshots()
    client = FakeSecMaps(stocks, funds)
    client.stock_rows["0"]["cik_str"] = 99999999
    db = tmp_path / "uncreated.sqlite3"
    result = run_first_batch(str(db), "2025-01-01", "2025-12-31", client,
                             tmp_path / "identities.json")
    assert result["status"] == "failed"
    assert not db.exists()
