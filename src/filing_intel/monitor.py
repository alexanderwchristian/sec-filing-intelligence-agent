"""Deterministic PR1 monitoring: inventory -> immutable source -> parse -> compare."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

from .detect import compare
from .models import Filing
from .parser import as_plain_text, extract_risk_section, normalize_spaces, segment
from .sec import FilingRecord, archive_url
from .store import Store, digest, now

PARSER_VERSION = "item1a-normalized-v1"
DETECTOR_VERSION = "risk-text-v1-untruncated"
BASELINE_POLICY = "prior annual 10-K with earlier filing date and distinct earlier report period"
MAX_UNITS = 1000  # reject explicitly, never silently truncate quadratic alignment


def iso_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Dates must use YYYY-MM-DD")
    return value


def filing_record(row) -> FilingRecord:
    return FilingRecord(row["accession"], row["filed"], row["document"], row["form"],
                        row["period_end"], row["accepted_at"])


@dataclass(frozen=True)
class SourceSpan:
    doc_id: str
    accession: str
    content_sha256: str
    parser_version: str
    section_path: str
    start_offset: int
    end_offset: int
    quote: str
    source_url: str
    locator_quality: str = "normalized_document_offset"
    exact_original_excerpt: str | None = None


def source_span(store: Store, row, quote: str) -> dict | None:
    if not quote:
        return None
    parsed = store.conn.execute("SELECT * FROM parses WHERE cik=? AND accession=? AND parser_version=?",
                                (row["cik"], row["accession"], PARSER_VERSION)).fetchone()
    offset = parsed["section_text"].find(quote)
    if offset < 0:
        raise ValueError("Evidence quote does not resolve to the declared source section")
    start = parsed["section_start"] + offset
    if parsed["normalized_text"][start:start + len(quote)] != quote:
        raise ValueError("Evidence offsets do not resolve")
    content_hash = store.conn.execute("SELECT content_sha256 FROM documents WHERE cik=? AND accession=?",
                                      (row["cik"], row["accession"])).fetchone()[0]
    return asdict(SourceSpan(f"sec:{row['cik']:010d}:{row['accession']}:{content_hash}",
                             row["accession"], content_hash, PARSER_VERSION, "Item 1A Risk Factors",
                             start, start + len(quote), quote, row["source_url"]))


def attempt(store, run_id, row, stage, status, error=None):
    with store.conn:
        store.conn.execute("""INSERT INTO attempts(run_id,cik,accession,stage,status,error,attempted_at,
                           parser_version,detector_version) VALUES(?,?,?,?,?,?,?,?,?)""",
                           (run_id, row["cik"], row["accession"], stage, status, error, now(),
                            PARSER_VERSION, DETECTOR_VERSION))


def prepare(store, client, run_id, row) -> Filing:
    key = (row["cik"], row["accession"])
    document = store.conn.execute("SELECT * FROM documents WHERE cik=? AND accession=?", key).fetchone()
    if document is None:
        try:
            raw, decoded = client.fetch_document(row["cik"], filing_record(row))
            with store.conn:
                store.conn.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)",
                                   (*key, hashlib.sha256(raw).hexdigest(), raw, decoded, now()))
            attempt(store, run_id, row, "fetch", "completed")
        except Exception as exc:
            attempt(store, run_id, row, "fetch", "failed", str(exc))
            raise
        document = store.conn.execute("SELECT * FROM documents WHERE cik=? AND accession=?", key).fetchone()
    parsed = store.conn.execute("SELECT * FROM parses WHERE cik=? AND accession=? AND parser_version=?",
                                (*key, PARSER_VERSION)).fetchone()
    if parsed is None:
        try:
            normalized = normalize_spaces(as_plain_text(document["decoded_text"]))
            section = extract_risk_section(document["decoded_text"])
            offset = normalized.find(section)
            if offset < 0:
                raise ValueError("Parsed section is not grounded in normalized document")
            with store.conn:
                store.conn.execute("INSERT INTO parses VALUES(?,?,?,?,?,?,?)",
                                   (*key, PARSER_VERSION, normalized, section, offset, now()))
            attempt(store, run_id, row, "parse", "completed")
        except Exception as exc:
            attempt(store, run_id, row, "parse", "failed", str(exc))
            raise
        parsed = store.conn.execute("SELECT * FROM parses WHERE cik=? AND accession=? AND parser_version=?",
                                    (*key, PARSER_VERSION)).fetchone()
    return Filing(str(row["cik"]), "10-K", row["filed"], row["source_url"], parsed["section_text"], row["accession"])


def choose_baseline(rows, current):
    prior = [r for r in rows if r["form"] == "10-K" and r["filed"] < current["filed"]]
    if current["period_end"]:
        # Missing period metadata cannot establish a comparable annual baseline.
        prior = [r for r in prior if r["period_end"] and r["period_end"] < current["period_end"]]
        order = lambda r: (r["period_end"], r["filed"], r["accession"])
        reason = BASELINE_POLICY
    else:
        order = lambda r: (r["filed"], r["accession"])
        reason = "prior annual 10-K by filing date; report period unavailable (lower confidence)"
    if not prior:
        return None, "first_seen: no eligible earlier annual baseline in published inventory"
    selected = max(prior, key=order)
    # Same-date duplicate annual candidates are ambiguous; accession order is not a policy.
    peers = [r for r in prior if r["filed"] == selected["filed"]
             and r["period_end"] == selected["period_end"]]
    if len(peers) > 1:
        raise ValueError("Ambiguous annual baseline; review duplicate reporting periods")
    return selected, reason


def analyze(store, client, run_id, rows, current) -> tuple[str, str]:
    baseline, reason = choose_baseline(rows, current)
    new = prepare(store, client, run_id, current)
    old = prepare(store, client, run_id, baseline) if baseline else None
    comparison_id = digest([current["cik"], current["accession"],
                            baseline["accession"] if baseline else None, PARSER_VERSION, DETECTOR_VERSION])
    existing = store.conn.execute("SELECT status FROM comparisons WHERE comparison_id=?", (comparison_id,)).fetchone()
    if existing:
        # Re-activate a formerly superseded comparison only if the selector chooses it again.
        with store.conn:
            store.conn.execute("UPDATE comparisons SET active=0 WHERE cik=? AND accession=?",
                               (current["cik"], current["accession"]))
            store.conn.execute("UPDATE comparisons SET active=1 WHERE comparison_id=?", (comparison_id,))
        return existing["status"], comparison_id
    report = None
    events = []
    supersedes = [r[0] for r in store.conn.execute(
        "SELECT comparison_id FROM comparisons WHERE cik=? AND accession=? ORDER BY comparison_id",
        (current["cik"], current["accession"]))]
    if old:
        if max(len(segment(old.text)), len(segment(new.text))) > MAX_UNITS:
            raise ValueError(f"Alignment budget exceeded ({MAX_UNITS} units); no section was truncated")
        report = compare(old, new, max_changes=None, max_segments=None)
        for change in report.changes:
            fingerprint = digest(["US", current["cik"], "issuer_risk", change.change_type,
                                  change.old_quote, change.new_quote, current["period_end"] or current["filed"]])
            event_id = digest([comparison_id, fingerprint])
            events.append({"schema_version": 1, "event_id": event_id, "fingerprint": fingerprint,
                           "entity_ids": {"jurisdiction": "US", "cik": f"{current['cik']:010d}",
                                          "entity_type": "issuer", "series_id": None, "class_id": None},
                           "category": "issuer_risk", "subtype": "wording_change",
                           "change_type": change.change_type, "status": "candidate",
                           "accession": current["accession"], "baseline_accession": baseline["accession"],
                           "baseline_reason": reason, "comparison_id": comparison_id,
                           "supersedes_comparison_ids": supersedes,
                           "comparison_method": DETECTOR_VERSION, "model_version": None,
                           "old_value": change.old_quote or None, "new_value": change.new_quote or None,
                           "effective_date": None, "effective_date_basis": "not_extracted",
                           "event_date": None, "filing_date": current["filed"],
                           "review_priority": change.attention, "detected_at": now(),
                           "uncertainties": ["Lexical candidate; economic significance not verified",
                                             "Offsets refer to normalized document, not raw HTML"],
                           "related_event_ids": [],
                           "evidence": {"old": source_span(store, baseline, change.old_quote),
                                        "new": source_span(store, current, change.new_quote)}})
    status = "compared" if old else "first_seen"
    with store.conn:
        store.conn.execute("UPDATE comparisons SET active=0 WHERE cik=? AND accession=?",
                           (current["cik"], current["accession"]))
        store.conn.execute("INSERT INTO comparisons VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                           (comparison_id, current["cik"], current["accession"],
                            baseline["accession"] if baseline else None, reason, PARSER_VERSION,
                            DETECTOR_VERSION, status, json.dumps(report.warnings if report else []), now()))
        for event in events:
            store.conn.execute("INSERT INTO events VALUES(?,?,?,?)",
                               (event["event_id"], event["fingerprint"], comparison_id, json.dumps(event)))
    return status, comparison_id


def inventory(store, watch, records, since, until):
    # Validate the entire feed before committing inventory or treating it as complete.
    unique = {}
    for record in records:
        iso_date(record.filed)
        if record.period_end:
            iso_date(record.period_end)
        if record.accession in unique and unique[record.accession] != record:
            raise ValueError("Conflicting duplicate accession metadata")
        unique[record.accession] = record
    with store.conn:
        for record in unique.values():
            reason = None if record.form == "10-K" else "unsupported_form_pr1"
            # Excluded ownership/XML forms can use nested primary paths. Inventory
            # those verbatim and link their filing index without invoking the 10-K path validator.
            url = archive_url(watch["cik"], record if reason is None and record.document else FilingRecord(
                record.accession, record.filed, record.accession + "-index.html", record.form))
            # Legacy submissions may omit a primary filename. Keep their inventory
            # and fail fetching only when this filing is selected or required as a baseline.
            key = (watch["cik"], record.accession)
            existing = store.conn.execute("SELECT * FROM filings WHERE cik=? AND accession=?", key).fetchone()
            if existing and filing_record(existing) != record:
                raise ValueError("Published accession metadata changed; manual review required")
            selected = record.form == "10-K" and since <= record.filed <= until
            store.conn.execute("""INSERT INTO filings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(cik,accession) DO UPDATE SET selected=MAX(filings.selected,excluded.selected)""",
                               (*key, record.form, record.filed, record.document, record.period_end,
                                record.accepted_at, now(), url, int(record.form.endswith('/A')),
                                int(selected), reason))


def scan(store: Store, client, *, since: str | None = None, until: str | None = None, mode: str = "scan") -> dict:
    until = iso_date(until or datetime.now(timezone.utc).date().isoformat())
    if mode not in ("scan", "backfill"):
        raise ValueError("Unsupported run mode")
    if since:
        since = iso_date(since)
    if mode == "backfill" and not since:
        raise ValueError("Backfill requires --from")
    if since and since > until:
        raise ValueError("Window start must not be after end")
    with store.scan_lock():
        watches = store.conn.execute("SELECT * FROM watches WHERE enabled=1 ORDER BY cik").fetchall()
        if not watches:
            raise ValueError("Watchlist is empty; add an issuer first")
        # Default scans revisit the original requested monitoring interval, including late arrivals.
        earlier = store.conn.execute("SELECT MIN(window_start) FROM runs WHERE mode='scan'").fetchone()[0]
        start = since or earlier or (date.fromisoformat(until) - timedelta(days=400)).isoformat()
        if start > until:
            raise ValueError("Window start must not be after end")
        run_id = str(uuid4())
        summary = {"run_id": run_id, "status": "running", "window_start": start, "window_end": until,
                   "discovered": 0, "eligible": 0, "processed": 0, "first_seen": 0,
                   "excluded": 0, "parse_failures": 0, "fetch_failures": 0,
                   "analysis_failures": 0, "discovery_failures": 0, "errors": []}
        with store.conn:
            store.conn.execute("""UPDATE runs SET status='partial',finished_at=?,
                summary=json_set(summary,'$.status','partial','$.interrupted',1)
                WHERE status='running'""", (now(),))
            store.conn.execute("UPDATE run_watches SET status='partial',error='interrupted worker' WHERE status='running'")
            store.conn.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)",
                               (run_id, mode, start, until,
                                digest([{k: w[k] for k in ("cik", "name", "provenance", "enabled", "revision")}
                                        for w in watches]),
                                "running", now(), None, json.dumps(summary)))
        for watch in watches:
            cik = watch["cik"]
            with store.conn:
                store.conn.execute("INSERT INTO run_watches VALUES(?,?,?,NULL)", (run_id, cik, "running"))
            before = store.conn.execute("SELECT count(*) FROM filings WHERE cik=?", (cik,)).fetchone()[0]
            try:
                inventory(store, watch, client.discover_filings(cik), start, until)
            except Exception as exc:
                summary["discovery_failures"] += 1
                summary["errors"].append({"cik": cik, "stage": "discovery", "error": str(exc)})
                with store.conn:
                    store.conn.execute("UPDATE run_watches SET status='failed',error=? WHERE run_id=? AND cik=?",
                                       (str(exc), run_id, cik))
                continue
            rows = store.conn.execute("SELECT * FROM filings WHERE cik=? ORDER BY filed,accession", (cik,)).fetchall()
            summary["discovered"] += len(rows) - before
            summary["excluded"] += sum(r["exclusion_reason"] is not None and start <= r["filed"] <= until for r in rows)
            targets = [r for r in rows if r["selected"] and r["filed"] <= until
                       and (mode != "backfill" or start <= r["filed"])]
            summary["eligible"] += len(targets)
            failed = False
            for current in targets:
                error = None
                comparison_id = None
                try:
                    outcome, comparison_id = analyze(store, client, run_id, rows, current)
                    summary["processed"] += 1
                    summary["first_seen"] += outcome == "first_seen"
                except Exception as exc:
                    failed = True
                    outcome, error = "failed", str(exc)
                    summary["errors"].append({"cik": cik, "accession": current["accession"], "error": error})
                    attempt(store, run_id, current, "analysis", "failed", error)
                    # A failed new baseline invalidates the old active result, without erasing it.
                    with store.conn:
                        store.conn.execute("UPDATE comparisons SET active=0 WHERE cik=? AND accession=?",
                                           (cik, current["accession"]))
                with store.conn:
                    store.conn.execute("INSERT INTO run_results VALUES(?,?,?,?,?,?)",
                                       (run_id, cik, current["accession"], outcome, comparison_id, error))
                    store.conn.execute("UPDATE runs SET summary=? WHERE run_id=?", (json.dumps(summary), run_id))
            with store.conn:
                store.conn.execute("UPDATE run_watches SET status=? WHERE run_id=? AND cik=?",
                                   ("partial" if failed else "completed", run_id, cik))
                if not failed and mode == "scan":
                    store.conn.execute("UPDATE watches SET checkpoint=MAX(COALESCE(checkpoint,?),?) WHERE cik=?",
                                       (until, until, cik))
        for stage in ("parse", "fetch", "analysis"):
            summary[stage + "_failures"] = store.conn.execute(
                "SELECT count(*) FROM attempts WHERE run_id=? AND stage=? AND status='failed'", (run_id, stage)).fetchone()[0]
        errors = summary["errors"]
        summary["status"] = "partial" if errors else "completed"
        if summary["discovery_failures"] == len(watches):
            summary["status"] = "failed"
        summary["coverage"] = "10-K Item 1A only; amendments and other forms inventoried but excluded"
        with store.conn:
            store.conn.execute("UPDATE runs SET status=?,finished_at=?,summary=? WHERE run_id=?",
                               (summary["status"], now(), json.dumps(summary), run_id))
        return summary
