"""Mocked dual-track acceptance regression. No SEC network or OpenAI calls."""
import importlib.util
import json
from pathlib import Path
import pytest
from filing_intel.intel_store import IntelStore
from filing_intel.sec import FilingRecord
from filing_intel.cli import main as cli_main

file = Path(__file__).resolve().parents[1] / "examples" / "live_dual_track_smoke.py"
spec = importlib.util.spec_from_file_location("live_pilot", file)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def rec(cik, year, form):
    return FilingRecord(f"{cik:010d}-{year % 100:02d}-000001",
                        f"{year}-03-20", f"{year-1}.htm", form,
                        f"{year-1}-12-31")


class FakeSEC:
    def __init__(self):
        self.records = {1: [rec(1, 2024, "10-K"), rec(1, 2025, "10-K")],
                        2: [rec(2, 2024, "485BPOS"), rec(2, 2025, "485BPOS")]}
        self.documents = {
            self.records[1][0].accession: b"<p>Total revenue was 20 million from global cloud services and recurring applications.</p>",
            self.records[1][1].accession: b"<p>Total revenue was 30 million from global cloud services and recurring applications.</p>",
            self.records[2][0].accession: b"<h2>Northstar Growth Fund</h2><p>S000000001 C000000001</p><p>The portfolio manager Alice Smith oversees all investments and the annual management fee is 0.50 percent.</p>",
            self.records[2][1].accession: b"<h2>Northstar Growth Fund</h2><p>S000000001 C000000001</p><p>The portfolio manager Bob Jones oversees all investments and the annual management fee is 0.65 percent.</p>",
        }
        self.fetches = []

    def discover_filings(self, cik):
        return list(self.records[cik])

    def fetch_document(self, cik, record):
        self.fetches.append(record.accession)
        content = self.documents[record.accession]
        if isinstance(content, Exception):
            raise content
        return content, content.decode()


def run(tmp_path, client, **kwargs):
    values = dict(stock_cik=1, stock_name="Synthetic Issuer",
                  fund_cik=2, fund_name="Northstar Growth Fund",
                  series_id="S000000001", class_id="C000000001",
                  since="2025-01-01", until="2025-12-31",
                  db=str(tmp_path / "fresh.sqlite3"), client=client)
    values.update(kwargs)
    return pilot.run_acceptance(**values)


def test_two_track_baselines_quotes_and_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_SEMANTIC_DETECTORS", "0")
    result = run(tmp_path, FakeSEC())
    assert result["status"] == "passed", result["failures"]
    assert all(result["paired_baseline_candidates"][k] > 0 for k in ("fund", "stock"))
    assert all(result["inventory"][k]["eligible_in_window"] == 1 for k in ("fund", "stock"))
    assert result["source_grounding"]["groundedness"] == 1
    assert result["replay"]["new_documents"] == 0
    assert result["replay"]["new_events"] == 0
    assert result["replay"]["event_ids_unchanged"]
    assert result["complete_candidate_evidence"]


def test_fresh_db_and_no_in_window_docs_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_SEMANTIC_DETECTORS", "0")
    existing = tmp_path / "prior.sqlite3"
    with IntelStore(existing) as s:
        s.add_watch("stock", 1, "Existing")
    with pytest.raises(ValueError, match="fresh database"):
        run(tmp_path, FakeSEC(), db=str(existing))
    client = FakeSEC()
    client.records = {cik: rows[:1] for cik, rows in client.records.items()}
    report = run(tmp_path, client)
    assert report["status"] == "failed"
    assert any("no supported SEC filing" in f for f in report["failures"])


def test_first_observation_is_not_a_comparison(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_SEMANTIC_DETECTORS", "0")
    client = FakeSEC()
    client.records[2] = client.records[2][1:]
    result = run(tmp_path, client)
    assert result["status"] == "failed"
    assert result["paired_baseline_candidates"]["fund"] == 0


def test_sec_partial_and_paid_semantic_opt_in_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_SEMANTIC_DETECTORS", "0")
    client = FakeSEC()
    client.documents[client.records[2][1].accession] = RuntimeError("SEC outage")
    report = run(tmp_path, client)
    assert report["status"] == "failed"
    assert report["run"]["status"] == "partial"
    assert report["replay"]["status"] == "skipped_incomplete_initial_scan"
    monkeypatch.setenv("USE_SEMANTIC_DETECTORS", "1")
    with pytest.raises(ValueError, match="refuses"):
        run(tmp_path, FakeSEC(), db=str(tmp_path / "other.sqlite3"))


def test_filing_inventory_supports_unbounded_query(tmp_path):
    client = FakeSEC()
    with IntelStore(tmp_path / "inventory.sqlite3") as store:
        wid = store.add_watch("stock", 1, "Test")
        for record in client.records[1]:
            content = client.documents[record.accession]
            store.put_filing(wid, record, "https://www.sec.gov/sample",
                             content, content.decode(), "registrant_only")
        assert len(store.filings(wid, limit=1)) == 1
        assert len(store.filings(wid, limit=None)) == 2


def test_daily_cli_nonzero_on_nested_partial_scan(tmp_path, monkeypatch, capsys):
    import filing_intel.cli as cli
    monkeypatch.setattr(cli, "run_daily",
                        lambda **k: {"status": "prepared", "scan": {"status": "partial"}})
    assert cli_main(["intelligence", "daily", "--no-send"]) == 2
    assert json.loads(capsys.readouterr().out)["scan"]["status"] == "partial"
    monkeypatch.setattr(cli, "run_daily",
                        lambda **k: {"status": "prepared", "scan": {"status": "completed"}})
    assert cli_main(["intelligence", "daily", "--no-send"]) == 0
