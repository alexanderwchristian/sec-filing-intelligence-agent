"""Versioned SQLite developer store. Documents and parser outputs are append-only."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


MIGRATION_1 = """
BEGIN IMMEDIATE;
CREATE TABLE watches (
 cik INTEGER PRIMARY KEY CHECK(cik>0 AND cik<10000000000), name TEXT NOT NULL,
 provenance TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, checkpoint TEXT
);
CREATE TABLE runs (
 run_id TEXT PRIMARY KEY, mode TEXT NOT NULL, window_start TEXT NOT NULL, window_end TEXT NOT NULL,
 watchlist_revision TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
 summary TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE run_watches (
 run_id TEXT NOT NULL REFERENCES runs, cik INTEGER NOT NULL REFERENCES watches,
 status TEXT NOT NULL, error TEXT, PRIMARY KEY(run_id,cik)
);
CREATE TABLE filings (
 cik INTEGER NOT NULL REFERENCES watches, accession TEXT NOT NULL, form TEXT NOT NULL,
 filed TEXT NOT NULL, document TEXT NOT NULL, period_end TEXT, accepted_at TEXT,
 discovered_at TEXT NOT NULL, source_url TEXT, is_amendment INTEGER NOT NULL,
 selected INTEGER NOT NULL DEFAULT 0, exclusion_reason TEXT,
 PRIMARY KEY(cik,accession)
);
CREATE INDEX filing_order ON filings(cik,form,filed,accession);
CREATE TABLE documents (
 cik INTEGER NOT NULL, accession TEXT NOT NULL, content_sha256 TEXT NOT NULL,
 raw_content BLOB NOT NULL, decoded_text TEXT NOT NULL, acquired_at TEXT NOT NULL,
 PRIMARY KEY(cik,accession), FOREIGN KEY(cik,accession) REFERENCES filings
);
CREATE TABLE parses (
 cik INTEGER NOT NULL, accession TEXT NOT NULL, parser_version TEXT NOT NULL,
 normalized_text TEXT NOT NULL, section_text TEXT NOT NULL, section_start INTEGER NOT NULL,
 parsed_at TEXT NOT NULL, PRIMARY KEY(cik,accession,parser_version),
 FOREIGN KEY(cik,accession) REFERENCES documents
);
CREATE TABLE attempts (
 attempt_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs,
 cik INTEGER NOT NULL, accession TEXT NOT NULL, stage TEXT NOT NULL,
 status TEXT NOT NULL, error TEXT, attempted_at TEXT NOT NULL,
 parser_version TEXT NOT NULL, detector_version TEXT NOT NULL
);
CREATE TABLE comparisons (
 comparison_id TEXT PRIMARY KEY, cik INTEGER NOT NULL, accession TEXT NOT NULL,
 baseline_accession TEXT, baseline_reason TEXT NOT NULL, parser_version TEXT NOT NULL,
 detector_version TEXT NOT NULL, status TEXT NOT NULL, warnings TEXT NOT NULL,
 created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 FOREIGN KEY(cik,accession) REFERENCES filings
);
CREATE TABLE run_results (
 run_id TEXT NOT NULL REFERENCES runs, cik INTEGER NOT NULL, accession TEXT NOT NULL,
 status TEXT NOT NULL, comparison_id TEXT REFERENCES comparisons, error TEXT,
 PRIMARY KEY(run_id,cik,accession)
);
CREATE TABLE events (
 event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
 comparison_id TEXT NOT NULL REFERENCES comparisons, payload TEXT NOT NULL
);
CREATE INDEX event_fingerprint ON events(fingerprint);
CREATE INDEX attempts_run ON attempts(run_id,stage,status);
CREATE TRIGGER immutable_raw_update BEFORE UPDATE ON documents BEGIN
 SELECT RAISE(ABORT, 'raw documents are immutable'); END;
CREATE TRIGGER immutable_raw_delete BEFORE DELETE ON documents BEGIN
 SELECT RAISE(ABORT, 'raw documents are immutable'); END;
CREATE TRIGGER immutable_parse_update BEFORE UPDATE ON parses BEGIN
 SELECT RAISE(ABORT, 'parser results are immutable'); END;
CREATE TRIGGER immutable_parse_delete BEFORE DELETE ON parses BEGIN
 SELECT RAISE(ABORT, 'parser results are immutable'); END;
CREATE TRIGGER immutable_event_update BEFORE UPDATE ON events BEGIN
 SELECT RAISE(ABORT, 'events are immutable'); END;
CREATE TRIGGER immutable_event_delete BEFORE DELETE ON events BEGIN
 SELECT RAISE(ABORT, 'events are immutable'); END;
PRAGMA user_version=1;
COMMIT;
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self.conn.executescript(MIGRATION_1)
        elif version != 1:
            self.conn.close()
            raise ValueError(f"Unsupported database schema {version}; expected 1")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.conn.close()

    @contextmanager
    def scan_lock(self):
        # POSIX local developer deployment. A crashed worker releases flock in the OS.
        import fcntl
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another scan is using this database") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def add_watch(self, cik: int, name: str, provenance: str):
        if not 0 < cik < 10_000_000_000 or not name.strip() or not provenance.strip():
            raise ValueError("Issuer watch requires a positive <=10-digit CIK, name and provenance")
        with self.scan_lock(), self.conn:
            self.conn.execute("""INSERT INTO watches(cik,name,provenance,created_at) VALUES(?,?,?,?)
                ON CONFLICT(cik) DO UPDATE SET name=excluded.name,provenance=excluded.provenance,
                enabled=1,revision=watches.revision+1
                WHERE watches.name<>excluded.name OR watches.provenance<>excluded.provenance OR watches.enabled<>1""",
                              (cik, name.strip(), provenance, now()))

    def disable_watch(self, cik: int):
        with self.scan_lock(), self.conn:
            if not self.conn.execute("UPDATE watches SET enabled=0,revision=revision+1 WHERE cik=?", (cik,)).rowcount:
                raise ValueError("CIK is not on the watchlist")

    def status(self) -> dict:
        runs = []
        for row in self.conn.execute("SELECT * FROM runs ORDER BY started_at DESC"):
            value = dict(row)
            value["summary"] = json.loads(value["summary"])
            value["entities"] = [dict(r) for r in self.conn.execute(
                "SELECT cik,status,error FROM run_watches WHERE run_id=? ORDER BY cik", (row["run_id"],))]
            value["attempts"] = [dict(r) for r in self.conn.execute(
                "SELECT * FROM attempts WHERE run_id=? ORDER BY attempt_id", (row["run_id"],))]
            runs.append(value)
        return {"schema_version": 1, "coverage": "watched issuers; 10-K Item 1A only",
                "watchlist": [dict(r) for r in self.conn.execute("SELECT * FROM watches ORDER BY cik")],
                "runs": runs}

    def results(self, *, run_id: str | None = None, include_superseded: bool = False) -> dict:
        if run_id and not self.conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
            raise ValueError("Unknown run ID")
        sql = "SELECT e.payload,c.active FROM events e JOIN comparisons c USING(comparison_id) WHERE 1=1"
        params = []
        if run_id:
            sql += " AND EXISTS(SELECT 1 FROM run_results r WHERE r.run_id=? AND r.comparison_id=c.comparison_id)"
            params.append(run_id)
        elif not include_superseded:
            sql += " AND c.active=1"
        events = []
        for row in self.conn.execute(sql + " ORDER BY e.event_id", params):
            event = json.loads(row["payload"])
            if not row["active"]:
                event["status"] = "superseded"
            events.append(event)
        outcomes = ("SELECT r.*,c.baseline_accession,c.baseline_reason,c.warnings FROM run_results r "
                    "LEFT JOIN comparisons c USING(comparison_id)" + (" WHERE r.run_id=?" if run_id else ""))
        excluded = "SELECT cik,accession,form,filed,exclusion_reason FROM filings WHERE exclusion_reason IS NOT NULL"
        return {"schema_version": 1, "events": events,
                "outcomes": [dict(r) for r in self.conn.execute(outcomes, (run_id,) if run_id else ())],
                "excluded_inventory": [dict(r) for r in self.conn.execute(excluded + " ORDER BY cik,filed,accession")]}
