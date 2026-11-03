"""Persistent, independently implemented event store for US fund and stock filings.

Coexists with the original Stage 1 issuer 10-K database without changing its schema.
This store is single-host SQLite with a persistent volume, not a cloud distributed DB.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


DDL = """
CREATE TABLE IF NOT EXISTS intel_watchlist (
    watch_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('fund','stock')),
    cik INTEGER NOT NULL CHECK(cik > 0), name TEXT NOT NULL,
    series_id TEXT, class_id TEXT, ticker TEXT, identity_source TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS intel_watch_identity ON intel_watchlist
    (kind,cik,COALESCE(series_id,''),COALESCE(class_id,''));
CREATE TABLE IF NOT EXISTS intel_runs (
    run_id TEXT PRIMARY KEY, mode TEXT NOT NULL, since_date TEXT NOT NULL,
    until_date TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT, stats_json TEXT NOT NULL DEFAULT '{}', errors_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS intel_run_watches (
    run_id TEXT NOT NULL, watch_id TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
    PRIMARY KEY(run_id,watch_id)
);
CREATE TABLE IF NOT EXISTS intel_filings (
    watch_id TEXT NOT NULL, accession TEXT NOT NULL, form TEXT NOT NULL,
    filed TEXT NOT NULL, period_end TEXT, accepted_at TEXT, source_url TEXT NOT NULL,
    content_hash TEXT NOT NULL, raw_content BLOB NOT NULL,
    normalized_text TEXT NOT NULL, identity_status TEXT NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY(watch_id,accession)
);
CREATE INDEX IF NOT EXISTS intel_filings_date ON intel_filings(watch_id,filed,form);
CREATE TABLE IF NOT EXISTS intel_events (
    event_id TEXT PRIMARY KEY, watch_id TEXT NOT NULL, accession TEXT NOT NULL,
    baseline_accession TEXT, category TEXT NOT NULL, change_type TEXT NOT NULL,
    status TEXT NOT NULL, priority TEXT NOT NULL, effective_date TEXT,
    detected_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS intel_events_lookup ON intel_events(watch_id,detected_at);
CREATE TABLE IF NOT EXISTS intel_investigations (
    event_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
    model TEXT, result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intel_digests (
    digest_id TEXT PRIMARY KEY, period_day TEXT NOT NULL UNIQUE,
    run_id TEXT, content_hash TEXT NOT NULL, markdown TEXT NOT NULL,
    status TEXT NOT NULL, provider_id TEXT, attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS intel_checkpoints (
    watch_id TEXT PRIMARY KEY, through_date TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS intel_filing_immutable_update BEFORE UPDATE ON intel_filings
BEGIN SELECT RAISE(ABORT, 'stored SEC filings are immutable'); END;
CREATE TRIGGER IF NOT EXISTS intel_filing_immutable_delete BEFORE DELETE ON intel_filings
BEGIN SELECT RAISE(ABORT, 'stored SEC filings are immutable'); END;
CREATE TRIGGER IF NOT EXISTS intel_event_immutable_update BEFORE UPDATE ON intel_events
BEGIN SELECT RAISE(ABORT, 'detected event history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS intel_event_immutable_delete BEFORE DELETE ON intel_events
BEGIN SELECT RAISE(ABORT, 'detected event history is immutable'); END;
CREATE TABLE IF NOT EXISTS intel_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO intel_meta(key,value) VALUES('schema_version','1');
"""


class IntelStore:
    def __init__(self, path: str | Path = ".filing-intel/intelligence.sqlite3"):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(DDL)
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    @contextmanager
    def scan_lock(self):
        """Single-host cooperative lock: scanners should not race on this file."""
        import fcntl
        with self.path.with_suffix(".scan.lock").open("a") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("A scan is already running on this store") from exc
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def add_watch(self, kind: str, cik: int, name: str, *,
                  ticker: str | None = None, series_id: str | None = None,
                  class_id: str | None = None, identity_source: str = "operator supplied") -> str:
        if kind not in {"fund", "stock"} or not isinstance(cik, int) or cik <= 0:
            raise ValueError("Specify kind fund/stock and a positive SEC registrant CIK")
        if not name or not name.strip():
            raise ValueError("Watch name is required")
        if kind == "stock" and (series_id or class_id):
            raise ValueError("Series and class IDs are for fund watches only")
        if class_id and not series_id:
            raise ValueError("A fund class ID requires the series ID")
        if series_id and (not series_id.startswith("S") or not series_id[1:].isdigit()):
            raise ValueError("Invalid SEC series ID")
        if class_id and (not class_id.startswith("C") or not class_id[1:].isdigit()):
            raise ValueError("Invalid SEC class ID")
        watch_id = stable_id("us-sec", kind, cik, series_id or "", class_id or "")
        with self.conn:
            self.conn.execute("""INSERT INTO intel_watchlist
                (watch_id,kind,cik,name,series_id,class_id,ticker,identity_source,enabled,created_at)
                VALUES (?,?,?,?,?,?,?,?,1,?)
                ON CONFLICT(watch_id) DO UPDATE SET name=excluded.name,
                ticker=excluded.ticker,identity_source=excluded.identity_source,enabled=1""",
                (watch_id, kind, cik, name.strip(), series_id, class_id, ticker,
                 identity_source.strip(), utcnow()))
        return watch_id

    def watches(self, *, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM intel_watchlist"
        if enabled_only:
            sql += " WHERE enabled=1"
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY kind,name")]

    def watch(self, watch_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM intel_watchlist WHERE watch_id=?", (watch_id,)).fetchone()
        return dict(row) if row else None

    def disable_watch(self, watch_id: str) -> None:
        with self.conn:
            if not self.conn.execute("UPDATE intel_watchlist SET enabled=0 WHERE watch_id=?",
                                     (watch_id,)).rowcount:
                raise ValueError("Unknown watch ID")

    def begin_run(self, mode: str, since_date: str, until_date: str) -> str:
        run_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute("""INSERT INTO intel_runs
              (run_id,mode,since_date,until_date,status,started_at) VALUES (?,?,?,?,?,?)""",
              (run_id,mode,since_date,until_date,"running",utcnow()))
        return run_id

    def complete_watch(self, run_id: str, watch_id: str, status: str, error: str | None = None,
                       through_date: str | None = None):
        with self.conn:
            self.conn.execute("""INSERT OR REPLACE INTO intel_run_watches
                (run_id,watch_id,status,error) VALUES (?,?,?,?)""",
                (run_id,watch_id,status,error))
            if through_date and status == "completed":
                self.conn.execute("""INSERT INTO intel_checkpoints(watch_id,through_date,updated_at)
                    VALUES (?,?,?) ON CONFLICT(watch_id) DO UPDATE SET
                    through_date=MAX(intel_checkpoints.through_date,excluded.through_date),
                    updated_at=excluded.updated_at""", (watch_id,through_date,utcnow()))

    def finish_run(self, run_id: str, stats: dict, errors: list[str]):
        status = "partial" if errors else "completed"
        with self.conn:
            self.conn.execute("""UPDATE intel_runs SET status=?,finished_at=?,stats_json=?,
                 errors_json=? WHERE run_id=?""", (status,utcnow(),json.dumps(stats),
                                                   json.dumps(errors),run_id))
        return status

    def runs(self, limit: int = 30) -> list[dict]:
        result = []
        for r in self.conn.execute("SELECT * FROM intel_runs ORDER BY started_at DESC LIMIT ?",(limit,)):
            x = dict(r)
            x["stats"] = json.loads(x.pop("stats_json"))
            x["errors"] = json.loads(x.pop("errors_json"))
            result.append(x)
        return result

    def checkpoints(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM intel_checkpoints ORDER BY watch_id")]

    def put_filing(self, watch_id: str, record: object, url: str, raw: bytes, text: str,
                   identity_status: str) -> None:
        digest = hashlib.sha256(raw).hexdigest()
        with self.conn:
            row = self.conn.execute("""SELECT content_hash FROM intel_filings
                                     WHERE watch_id=? AND accession=?""",
                                    (watch_id,record.accession)).fetchone()
            if row:
                if row["content_hash"] != digest:
                    raise ValueError("Immutable accession content hash mismatch")
                return
            self.conn.execute("""INSERT INTO intel_filings
                (watch_id,accession,form,filed,period_end,accepted_at,source_url,content_hash,
                 raw_content,normalized_text,identity_status,created_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (watch_id,record.accession,record.form,record.filed,
                 record.period_end,record.accepted_at,url,digest,raw,text,
                 identity_status,utcnow()))

    def filing(self, watch_id: str, accession: str) -> dict | None:
        row = self.conn.execute("""SELECT * FROM intel_filings
            WHERE watch_id=? AND accession=?""",(watch_id,accession)).fetchone()
        return dict(row) if row else None

    def filings(self, watch_id: str, *, limit: int | None = 200) -> list[dict]:
        sql = """SELECT watch_id,accession,form,filed,period_end,source_url,
          content_hash,identity_status FROM intel_filings
          WHERE watch_id=? ORDER BY filed DESC,accession DESC"""
        if limit is None:
            return [dict(r) for r in self.conn.execute(sql,(watch_id,))]
        return [dict(r) for r in self.conn.execute(sql+" LIMIT ?",(watch_id,limit))]

    def put_event(self, event: dict) -> bool:
        with self.conn:
            row = self.conn.execute("SELECT 1 FROM intel_events WHERE event_id=?",
                                    (event["event_id"],)).fetchone()
            if row:
                return False
            self.conn.execute("""INSERT INTO intel_events(event_id,watch_id,accession,
                baseline_accession,category,change_type,status,priority,effective_date,
                detected_at,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (event["event_id"],event["watch_id"],event["accession"],
                 event.get("baseline_accession"),event["category"],event["change_type"],
                 event["status"],event["priority"],event.get("effective_date"),
                 event["detected_at"],json.dumps(event,sort_keys=True)))
        return True

    def events(self, *, kind: str | None = None, category: str | None = None,
               since: str | None = None, limit: int | None = None) -> list[dict]:
        q = """SELECT e.payload_json,w.kind,w.name FROM intel_events e
               JOIN intel_watchlist w ON e.watch_id=w.watch_id WHERE 1=1"""
        args: list[object] = []
        if kind:
            q += " AND w.kind=?"
            args.append(kind)
        if category:
            q += " AND e.category=?"
            args.append(category)
        if since:
            q += " AND substr(e.detected_at,1,10)>=?"
            args.append(since)
        q += " ORDER BY e.detected_at DESC,e.event_id"
        if limit is not None:
            q += " LIMIT ?"
            args.append(limit)
        return [{**json.loads(r["payload_json"]),"kind":r["kind"],"watch_name":r["name"]}
                for r in self.conn.execute(q,args)]

    def event(self, event_id: str) -> dict | None:
        row = self.conn.execute("SELECT payload_json FROM intel_events WHERE event_id=?",
                                (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_investigation(self, event_id: str, result: dict, model: str | None = None) -> None:
        with self.conn:
            self.conn.execute("""INSERT OR REPLACE INTO intel_investigations
                (event_id,created_at,status,model,result_json) VALUES (?,?,?,?,?)""",
                (event_id,utcnow(),result.get("status","completed"),model,
                 json.dumps(result,sort_keys=True)))

    def investigation(self, event_id: str) -> dict | None:
        row=self.conn.execute("SELECT result_json FROM intel_investigations WHERE event_id=?",
                              (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_digest(self, day: str, markdown: str, run_id: str | None) -> dict:
        digest_id = stable_id("digest",day)
        hash_value = hashlib.sha256(markdown.encode()).hexdigest()
        with self.conn:
            existing=self.conn.execute("SELECT * FROM intel_digests WHERE period_day=?",
                                       (day,)).fetchone()
            if existing:
                if existing["content_hash"] != hash_value:
                    # Never silently overwrite a prepared/sent briefing.
                    raise ValueError("Daily digest already exists with different content; review required")
                return dict(existing)
            self.conn.execute("""INSERT INTO intel_digests
                (digest_id,period_day,run_id,content_hash,markdown,status,created_at,updated_at)
                VALUES(?,?,?,?,?,'prepared',?,?)""",
                (digest_id,day,run_id,hash_value,markdown,utcnow(),utcnow()))
        return self.digest(day)

    def digest(self, day: str) -> dict | None:
        row=self.conn.execute("SELECT * FROM intel_digests WHERE period_day=?",(day,)).fetchone()
        return dict(row) if row else None

    def digests(self, limit: int = 90) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM intel_digests ORDER BY period_day DESC LIMIT ?",(limit,))]

    def begin_send(self, day: str) -> bool:
        """Fail-closed: never automatically retry an uncertain/attempted delivery."""
        with self.conn:
            result=self.conn.execute("""UPDATE intel_digests SET status='sending',
                   attempt_count=attempt_count+1,updated_at=?
                   WHERE period_day=? AND status='prepared'""",(utcnow(),day))
        return result.rowcount == 1

    def finish_send(self, day: str, provider_id: str | None, error: str | None = None):
        status = "sent" if not error else "unknown"
        with self.conn:
            self.conn.execute("""UPDATE intel_digests SET status=?,provider_id=?,error=?,
               updated_at=? WHERE period_day=? AND status='sending'""",
               (status,provider_id,error,utcnow(),day))

    def latest_successful_run(self, day: str) -> dict | None:
        rows=self.conn.execute("""SELECT * FROM intel_runs
             WHERE until_date=? ORDER BY started_at DESC""",(day,)).fetchall()
        return dict(rows[0]) if rows else None
