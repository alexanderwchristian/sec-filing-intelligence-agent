"""Deterministic end-to-end durability and failure rehearsals; no SEC access."""
import json
import sqlite3

import pytest

from filing_intel.cli import main
from filing_intel.monitor import scan
from filing_intel.sec import FilingRecord
from filing_intel.store import Store


def record(year, *, form="10-K", day="02-01"):
    return FilingRecord(f"0000000001-{year % 100:02d}-000001", f"{year}-{day}",
                        f"{year}.htm", form, f"{year - 1}-12-31")


def document(label):
    theme = ("Ransomware criminals attack confidential networks exposing personal information"
             if label != "0" else "Drought reduces agricultural harvest yields across farmland regions")
    sentences = [f"{theme} risk number {i} could harm our {label} performance and demand in future periods."
                 for i in range(12)]
    return ("<html><body><p>Item 1A. Risk Factors</p><p>" + " ".join(sentences)
            + "</p><p>Item 1B. Comments</p></body></html>")


class Client:
    def __init__(self, records):
        self.records = records
        self.docs = {r.accession: document(str(i)).encode() for i, r in enumerate(records)}
        self.fetched = []

    def discover_filings(self, cik):
        return self.records

    def fetch_document(self, cik, rec):
        self.fetched.append(rec.accession)
        value = self.docs[rec.accession]
        if isinstance(value, BaseException):
            raise value
        return value, value.decode()


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "state.sqlite3") as db:
        db.add_watch(1, "Fictional Issuer", "test fixture")
        yield db


def test_replay_is_idempotent_and_evidence_resolves(store):
    client = Client([record(2023), record(2024)])
    first = scan(store, client, since="2024-01-01", until="2024-12-31")
    events = store.results()["events"]
    assert first["status"] == "completed" and events
    for event in events:
        assert event["baseline_accession"] == record(2023).accession
        assert event["effective_date"] is None
        for side in ("old", "new"):
            span = event["evidence"][side]
            if span:
                parsed = store.conn.execute("SELECT normalized_text FROM parses WHERE accession=?",
                                            (span["accession"],)).fetchone()[0]
                assert parsed[span["start_offset"]:span["end_offset"]] == span["quote"]
                assert span["source_url"].startswith("https://www.sec.gov/Archives/")
    fetched = list(client.fetched)
    second = scan(store, client, since="2024-01-01", until="2024-12-31")
    assert second["status"] == "completed"
    assert client.fetched == fetched
    assert store.results()["events"] == events
    assert store.results(run_id=second["run_id"])["events"] == events
    runs = store.status()["runs"]
    assert runs[0]["watchlist_revision"] == runs[1]["watchlist_revision"]


def test_missed_run_and_late_filing_reselect_baseline(store):
    client = Client([record(2022), record(2024)])
    scan(store, client, since="2024-01-01", until="2024-12-31")
    old_ids = {e["event_id"] for e in store.results()["events"]}
    client.records += [record(2023), record(2025)]
    client.docs[record(2023).accession] = document("0").encode()
    client.docs[record(2025).accession] = document("0").encode()
    result = scan(store, client, until="2025-12-31")
    assert result["status"] == "completed"
    events = store.results()["events"]
    assert any(e["accession"] == record(2025).accession for e in events)
    assert all(e["baseline_accession"] == record(2023).accession
               for e in events if e["accession"] == record(2024).accession)
    assert not old_ids.intersection(e["event_id"] for e in events)
    assert old_ids <= {e["event_id"] for e in store.results(include_superseded=True)["events"]}


def test_duplicate_accession_and_unsupported_amendment_are_visible(store):
    from dataclasses import replace
    amendment = record(2025, form="10-K/A")
    ownership = replace(record(2025, form="4", day="03-01"), accession="0000000001-25-000002",
                        document="xslF345X05/ownership.xml")
    client = Client([record(2023), record(2024), record(2024), amendment, ownership])
    result = scan(store, client, since="2024-01-01", until="2025-12-31")
    assert result["status"] == "completed"
    assert result["excluded"] == 2
    rows = store.conn.execute("SELECT * FROM filings").fetchall()
    assert len(rows) == 4
    assert amendment.accession not in client.fetched


def test_parser_failure_retains_raw_blocks_checkpoint_and_is_retryable(store):
    client = Client([record(2023), record(2024)])
    client.docs[record(2024).accession] = b"<html>No Item 1A section here</html>"
    failed = scan(store, client, since="2024-01-01", until="2024-12-31")
    assert failed["status"] == "partial" and failed["parse_failures"] == 1
    assert store.status()["watchlist"][0]["checkpoint"] is None
    assert store.results()["events"] == []
    assert store.conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    assert "No qualifying changes" not in json.dumps(failed)
    again = scan(store, client, until="2025-01-01")
    assert again["status"] == "partial"  # does not treat a cached parse error as no change
    assert client.fetched.count(record(2024).accession) == 1


def test_incomplete_run_recovered_without_lost_work(store):
    client = Client([record(2023), record(2024), record(2025)])
    client.docs[record(2025).accession] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        scan(store, client, since="2024-01-01", until="2025-12-31")
    assert store.status()["runs"][0]["status"] == "running"
    client.docs[record(2025).accession] = document("recovered").encode()
    result = scan(store, client, until="2025-12-31")
    assert result["status"] == "completed"
    assert store.status()["runs"][1]["status"] == "partial"
    assert len({e["event_id"] for e in store.results()["events"]}) == len(store.results()["events"])
    assert client.fetched.count(record(2024).accession) == 1


def test_backfill_first_seen_and_no_future_or_other_issuer_baseline(store):
    store.add_watch(2, "Another Fictional Issuer", "test fixture")
    client = Client([record(2023), record(2025)])
    result = scan(store, client, since="2023-01-01", until="2023-12-31", mode="backfill")
    assert result["status"] == "completed"
    assert result["first_seen"] == 2
    assert store.results()["events"] == []


def test_raw_documents_are_immutable_and_migration_reopens(store):
    scan(store, Client([record(2023)]), since="2023-01-01", until="2023-12-31")
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("UPDATE documents SET raw_content=x'00'")
    with Store(store.path) as reopened:
        assert reopened.conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert len(reopened.status()["watchlist"]) == 1


def test_status_and_results_cli_without_sec_identity(tmp_path, capsys):
    path = str(tmp_path / "cli.sqlite3")
    assert main(["status", "--db", path]) == 0
    assert json.loads(capsys.readouterr().out)["runs"] == []
    assert main(["results", "--db", path]) == 0
    assert json.loads(capsys.readouterr().out)["events"] == []


def test_more_than_350_units_and_20_findings_are_not_truncated(store):
    client = Client([record(2023), record(2024)])
    extra = " ".join(f"Zebras number {i} " + "unexpected exotic zebra hazards " * 30 + "."
                     for i in range(360))
    client.docs[record(2024).accession] = document("0").replace(
        "</p><p>Item 1B", extra + "</p><p>Item 1B").encode()
    result = scan(store, client, since="2024-01-01", until="2024-12-31")
    assert result["status"] == "completed"
    assert len(store.results()["events"]) > 350


def test_failed_fetch_retries_and_independent_issuer_completes(store):
    store.add_watch(2, "Second Issuer", "fixture")
    client = Client([record(2023), record(2024)])
    original = client.discover_filings
    client.discover_filings = lambda cik: original(cik) if cik == 1 else []
    client.docs[record(2024).accession] = RuntimeError("transient SEC outage")
    result = scan(store, client, since="2024-01-01", until="2024-12-31")
    assert result["status"] == "partial" and result["fetch_failures"] == 1
    assert store.status()["watchlist"][0]["checkpoint"] is None
    assert store.status()["watchlist"][1]["checkpoint"] == "2024-12-31"
    client.docs[record(2024).accession] = document("new").encode()
    assert scan(store, client, until="2024-12-31")["status"] == "completed"
    assert store.results()["events"]


def test_failed_discovery_and_inverted_interval_are_visible(store):
    class Broken(Client):
        def discover_filings(self, cik):
            raise ValueError("historical shard unavailable")
    result = scan(store, Broken([]), since="2024-01-01", until="2024-12-31")
    assert result["status"] == "failed" and result["discovery_failures"] == 1
    assert not store.results()["events"]
    with pytest.raises(ValueError, match="after"):
        scan(store, Client([]), since="2025-01-01", until="2024-01-01")


def test_scan_lock_rejects_concurrent_worker(store):
    with store.scan_lock(), Store(store.path) as other:
        with pytest.raises(RuntimeError, match="Another scan"):
            scan(other, Client([]), since="2024-01-01", until="2024-12-31")


def test_ambiguous_baseline_fails_closed(store):
    from dataclasses import replace
    older = record(2023)
    duplicate_period = replace(older, accession="0000000001-23-000002")
    result = scan(store, Client([older, duplicate_period, record(2024)]),
                  since="2024-01-01", until="2024-12-31")
    assert result["status"] == "partial"
    assert "Ambiguous" in result["errors"][0]["error"]
    assert not store.results()["events"]
