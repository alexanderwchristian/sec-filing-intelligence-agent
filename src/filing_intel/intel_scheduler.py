"""Single-host daily operator, compatible with a persistent Docker volume.

Runs the full watchlist through shared detector/investigation/digest components.
At most one attempted digest per local calendar day; recovery scans re-sweep
filings after downtime. Do not run two schedulers on the same database.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import os
import time
from zoneinfo import ZoneInfo

from .intel_store import IntelStore
from .intel_monitor import scan_intelligence
from .intel_research import investigate_event
from .intel_digest import prepare_digest, send_digest
from .sec import SecClient


def run_daily(*,db:str|None=None,day:str|None=None,send:bool=True)->dict:
    zone=ZoneInfo(os.getenv("DIGEST_TIMEZONE","America/New_York"))
    local=datetime.now(zone)
    target=day or local.date().isoformat()
    path=db or os.getenv("INTEL_DB_PATH",".filing-intel/intelligence.sqlite3")
    with IntelStore(path) as store:
        saved=store.digest(target)
        if saved:
            if saved["status"]=="sent":
                return {"status":"already_sent","day":target}
            if saved["status"]=="prepared" and send:
                return send_digest(store,target)
            return {"status":saved["status"],"day":target}
        # A sufficiently broad reread detects late arrivals; immutable document
        # cache and event fingerprints keep repeated scans idempotent.
        since=(datetime.fromisoformat(target).date()-timedelta(days=90)).isoformat()
        result=scan_intelligence(store,SecClient(),since=since,until=target,mode="scheduled")
        events=store.events(since=target,limit=10000)
        # A present key must not automatically spend credits on daily runs.
        # Operator must explicitly enable model-based investigation.
        if os.getenv("ENABLE_DAILY_AI_RESEARCH", "0") == "1":
            for item in [e for e in events if e["priority"]=="high"][:5]:
                investigate_event(store,item["event_id"])
        digest=prepare_digest(store,target)
        outcome={"status":"prepared","day":target,"scan":result,
                 "digest_id":digest["digest_id"]}
        if send:
            outcome["delivery"]=send_digest(store,target)
        return outcome


def main():
    """Poll every minute; a persistent calendar-day ledger prevents repeats."""
    zone=ZoneInfo(os.getenv("DIGEST_TIMEZONE","America/New_York"))
    hour=int(os.getenv("DIGEST_HOUR","8"))
    if not 0<=hour<=23:
        raise ValueError("DIGEST_HOUR must be 0-23")
    while True:
        local=datetime.now(zone)
        if local.weekday()<5 and local.hour>=hour:
            try:
                result=run_daily()
                print(result,flush=True)
            except Exception as exc:
                # Do not forge a successful daily run. Container logs/health
                # monitoring must surface the error for operator recovery.
                print("Scheduled filing intelligence failure:",type(exc).__name__,
                      str(exc),flush=True)
        time.sleep(60)


if __name__=="__main__":
    main()
