"""Shared scheduled/on-demand SEC monitor for US investment funds and stocks."""
from __future__ import annotations

from datetime import date, timedelta, datetime, timezone
import os
from typing import Any

from .categories import (FUND_FORMS, STOCK_FORMS, FORM_FAMILIES,
                         canonical_text, detect_events, identity_status)
from .intel_store import IntelStore
from .sec import SecClient, archive_url
from .intel_semantic import review_candidates


def _date(value: str | None, default: date) -> date:
    parsed = date.fromisoformat(value) if value else default
    if value and value != parsed.isoformat():
        raise ValueError("Dates must use ISO YYYY-MM-DD")
    return parsed


def _family(form: str) -> str:
    return FORM_FAMILIES[form].replace("_amendment", "")


def choose_baseline(current, records, kind: str):
    """Choose an explainable baseline, never compare unrelated form families."""
    older = [r for r in records if r.filed < current.filed
             and r.accession != current.accession]
    if current.form in {"8-K","N-14"}:
        return None, "event-first filing; no assumed earlier baseline"
    if current.form in {"8-K/A"}:
        return None, "amended event filing; amendment relation requires review"
    if current.form.endswith("/A"):
        originals=[r for r in older if r.form==current.form[:-2]
                   and r.period_end and r.period_end==current.period_end]
        if originals:
            return max(originals,key=lambda r:(r.filed,r.accession)), "amendment to original period/form"
        return None, "original amendment parent not deterministically resolved"
    if current.form=="10-K":
        options=[r for r in older if r.form=="10-K" and
                 (not r.period_end or not current.period_end or r.period_end<current.period_end)]
        if not options:
            return None,"first annual report without comparable baseline"
        return max(options,key=lambda r:(r.period_end or "",r.filed,r.accession)), "preceding annual 10-K"
    if current.form=="10-Q":
        options=[r for r in older if r.form=="10-Q" and r.period_end
                 and current.period_end and r.period_end<current.period_end]
        if current.period_end and options:
            try:
                d=date.fromisoformat(current.period_end)
                yoy=[r for r in options if (date.fromisoformat(r.period_end).month,
                      date.fromisoformat(r.period_end).day)==(d.month,d.day)
                     and date.fromisoformat(r.period_end).year==d.year-1]
            except ValueError:
                yoy=[]
            if yoy:
                return max(yoy,key=lambda r:(r.filed,r.accession)), "year-over-year comparable quarter"
        # A quarter-over-quarter comparison is useful but NOT falsely called YoY.
        if options:
            return max(options,key=lambda r:(r.period_end or "",r.filed)), "prior quarter; not YoY comparable"
        return None,"no comparable previous quarterly filing"
    if kind=="fund":
        # Prospectuses and post-effective supplements are not interchangeable.
        if current.form in {"485APOS","485BPOS"}:
            options=[r for r in older if r.form in {"485APOS","485BPOS"}]
        else:
            options=[r for r in older if r.form==current.form]
        if options:
            return max(options,key=lambda r:(r.filed,r.accession)), "same registrant and fund watch; fund identity validation required"
    return None,"no safely comparable prior document in current supported family"


def _load(store: IntelStore, client: SecClient, watch: dict, record: Any,
          cache: dict[tuple[int,str],tuple[bytes,str]]) -> dict:
    existing=store.filing(watch["watch_id"],record.accession)
    if existing:
        return existing
    key=(watch["cik"],record.accession)
    if key not in cache:
        raw,decoded=client.fetch_document(watch["cik"],record)
        cache[key]=(raw,decoded)
    raw,decoded=cache[key]
    text=canonical_text(decoded)
    if len(text)<60:
        raise ValueError("SEC document empty or could not be normalized")
    status=identity_status(watch,text)
    store.put_filing(watch["watch_id"],record,archive_url(watch["cik"],record),
                     raw,text,status)
    return store.filing(watch["watch_id"],record.accession)


def scan_intelligence(store: IntelStore, client: SecClient, *,
                      since: str | None = None, until: str | None = None,
                      mode: str = "scan") -> dict:
    today=datetime.now(timezone.utc).date()
    end=_date(until,today)
    beginning=_date(since,end-timedelta(days=90))
    if beginning>end:
        raise ValueError("Scan start date must precede end date")
    if mode not in {"scan","backfill","on_demand","scheduled"}:
        raise ValueError("Unsupported scan mode")
    with store.scan_lock():
        watches=store.watches(enabled_only=True)
        run_id=store.begin_run(mode,beginning.isoformat(),end.isoformat())
        stats={"watches":len(watches),"eligible_filings":0,"new_documents":0,
               "new_events":0,"replayed_events":0,"unsupported_forms":0,
               "filing_errors":0,"watch_errors":0}
        errors=[]
        cache={}
        for watch in watches:
            wid=watch["watch_id"]
            allowed=FUND_FORMS if watch["kind"]=="fund" else STOCK_FORMS
            watch_failed=False
            try:
                records=client.discover_filings(watch["cik"])
                stats["unsupported_forms"]+=sum(1 for r in records
                   if beginning.isoformat()<=r.filed<=end.isoformat() and r.form not in allowed)
                relevant=sorted((r for r in records if r.form in allowed),
                                key=lambda r:(r.filed,r.accession))
                targets=[r for r in relevant if beginning.isoformat()<=r.filed<=end.isoformat()]
                for record in targets:
                    stats["eligible_filings"]+=1
                    try:
                        prior,baseline_reason=choose_baseline(record,relevant,watch["kind"])
                        already=store.filing(wid,record.accession)
                        current=_load(store,client,watch,record,cache)
                        if not already:
                            stats["new_documents"]+=1
                        baseline=_load(store,client,watch,prior,cache) if prior else None
                        # A prospectus for a multi-fund registrant is still review-only.
                        # The classifier does not claim verified fund/class attribution.
                        events=detect_events(watch,current,baseline)
                        if os.getenv("USE_SEMANTIC_DETECTORS","0")=="1":
                            events,semantic_warnings=review_candidates(events)
                            if semantic_warnings:
                                watch_failed=True
                                errors.extend(watch["name"]+" "+record.accession+": "+warning
                                              for warning in semantic_warnings)
                        else:
                            for event in events:
                                event["semantic_review"]={"status":"disabled"}
                        for event in events:
                            event["baseline_reason"]=baseline_reason
                            if store.put_event(event):
                                stats["new_events"]+=1
                            else:
                                stats["replayed_events"]+=1
                    except Exception as exc:
                        watch_failed=True
                        stats["filing_errors"]+=1
                        errors.append(f"{watch['name']} {record.accession} ({record.form}): {type(exc).__name__}: {exc}")
                store.complete_watch(run_id,wid,"partial" if watch_failed else "completed",
                                     "One or more filings failed" if watch_failed else None,
                                     None if watch_failed else end.isoformat())
            except Exception as exc:
                stats["watch_errors"]+=1
                errors.append(f"{watch['name']} discovery: {type(exc).__name__}: {exc}")
                store.complete_watch(run_id,wid,"failed",str(exc))
        status=store.finish_run(run_id,stats,errors)
    return {"run_id":run_id,"status":status,"from":beginning.isoformat(),
            "to":end.isoformat(),"stats":stats,"errors":errors}
