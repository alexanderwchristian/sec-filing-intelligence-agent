"""Daily fund+stock briefings and fail-closed SMTP delivery with a send ledger."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
import os
import re
import smtplib

from .intel_store import IntelStore


def generate_briefing(store:IntelStore,day:str,*,max_display:int=35)->tuple[str,str|None]:
    date.fromisoformat(day)
    all_runs=[r for r in store.runs(100) if r["until_date"]==day]
    run=next((r for r in all_runs if r["mode"]=="scheduled"),all_runs[0] if all_runs else None)
    last_sent=next((d for d in store.digests(365)
                    if d["period_day"]<day and d["status"]=="sent"),None)
    boundary=last_sent["created_at"] if last_sent else day+"T00:00:00"
    # Include newly detected candidates since the last successful delivery,
    # not just those filed today. Publication and detection dates differ.
    events=[e for e in store.events(since=boundary[:10],limit=50000)
            if e["detected_at"]>=boundary]
    funds=[e for e in events if e["kind"]=="fund"]
    stocks=[e for e in events if e["kind"]=="stock"]
    active=store.watches(enabled_only=True)
    status=run["status"] if run else "not_run"
    lines=[
      "# SEC Fund & Stock Intelligence | "+day,
      "",
      "**Coverage:** US public SEC EDGAR filings for watched funds and stocks.",
      "**Run status:** "+status.upper(),
      "**Watchlist:** "+str(len([w for w in active if w["kind"]=="fund"]))+
         " fund(s), "+str(len([w for w in active if w["kind"]=="stock"]))+" stock(s)",
      "**New candidate findings:** "+str(len(events)),
      "",
      "Candidate changes require human verification. Fund share-class attribution "
      "is not assumed from registrant CIK alone.",
      "",
    ]
    if status!="completed":
        lines += ["## Coverage warning",
                  "Monitoring is incomplete or not confirmed for this reporting day. "
                  "Absence of findings MUST NOT be treated as no changes.",
                  ""]
        if run:
            lines += ["**Failures:** "+str(len(run["errors"])),""]
            for error in run["errors"][:10]:
                lines.append("- "+str(error)[:300])
        else:
            lines += ["No completed scan is recorded for the day.",""]
    elif not events:
        lines += ["## No qualifying candidate changes detected",
                  "The monitored, supported filing coverage completed successfully; "
                  "excluded forms and unsupported categories are not covered.",""]

    displayed=0
    for label,group in (("Fund filing changes",funds),("Stock filing changes",stocks)):
        lines += ["## "+label,""]
        if not group:
            lines += ["No newly detected candidates in this category.",""]
            continue
        lines.append(str(len(group))+" candidate(s) detected.")
        for event in group:
            if displayed>=max_display:
                continue
            displayed+=1
            lines += ["", "### "+event["name"]+" | "+event["category"].replace("_"," "),
                      "- Form: "+event["form"]+"; filed "+event["filing_date"],
                      "- Change: "+event["change_type"]+"; review priority "+event["priority"],
                      "- Event ID: "+event["event_id"]]
            if event.get("identity_status"):
                lines.append("- Identity: "+event["identity_status"])
            if event.get("effective_date"):
                lines.append("- Effective date (source text): "+event["effective_date"])
            else:
                lines.append("- Effective date: unknown")
            evidence=event.get("new_evidence") or event.get("old_evidence")
            if evidence:
                quote=str(evidence.get("quote","")).replace("\n"," ")[:320]
                lines.append("- Source excerpt: "+quote)
                lines.append("- SEC filing: "+evidence["source_url"])
            result=store.investigation(event["event_id"])
            if result:
                lines.append("- Research: "+result.get("summary","")[:330])
                for step in result.get("follow_ups",[])[:2]:
                    lines.append("  - Investigate: "+step[:230])
            else:
                lines.append("- Investigate: Verify the source passage, fund/class attribution and any effective date.")
        lines.append("")
    if len(events)>max_display:
        lines += ["**"+str(len(events)-max_display)+" additional candidate(s) are not shown** "
                  "in this condensed briefing; the complete event inventory remains "
                  "available in the dashboard and database.",""]
    lines += ["## Method and limitations",
              "Filing and detected dates are different. These are source-linked "
              "lexical/category candidates, not confirmed material events or trade advice.",
              "Daily completeness applies to the configured watchlist and supported "
              "forms only. Failed filings and missing fund identity are not silently cleared.",""]
    return "\n".join(lines),run["run_id"] if run else None


def prepare_digest(store:IntelStore,day:str)->dict:
    existing=store.digest(day)
    if existing:
        return existing
    report,run_id=generate_briefing(store,day)
    return store.save_digest(day,report,run_id)


def _addresses(value:str)->list[str]:
    items=[x.strip() for x in value.split(",") if x.strip()]
    if not items or any("\n" in x or "\r" in x or "@" not in x for x in items):
        raise ValueError("Configure valid EMAIL_TO / EMAIL_FROM values")
    return items


def send_digest(store:IntelStore,day:str,*,smtp_factory=None)->dict:
    """At most one automatic attempt per day. Uncertain outcomes require review.

    SMTP cannot guarantee exactly-once remote delivery. The state is moved to
    'sending' before network I/O; an exception becomes 'unknown', NEVER
    automatically retried without provider reconciliation.
    """
    digest=store.digest(day)
    if not digest:
        raise ValueError("Prepare the daily briefing before sending")
    if digest["status"]=="sent":
        return {"status":"already_sent","digest_id":digest["digest_id"]}
    settings={
      "host":os.getenv("SMTP_HOST",""),"port":int(os.getenv("SMTP_PORT","587")),
      "from":os.getenv("EMAIL_FROM",""),"to":os.getenv("EMAIL_TO",""),
      "user":os.getenv("SMTP_USERNAME",""),"password":os.getenv("SMTP_PASSWORD","")
    }
    if not settings["host"] or not settings["from"] or not settings["to"]:
        raise ValueError("Set SMTP_HOST, EMAIL_FROM and EMAIL_TO (and SMTP credentials when required)")
    sender=_addresses(settings["from"])
    recipients=_addresses(settings["to"])
    if len(sender)!=1:
        raise ValueError("EMAIL_FROM must be one address")
    if not store.begin_send(day):
        raise RuntimeError("Delivery is already in progress, sent or uncertain; check ledger")
    msg=EmailMessage()
    msg["From"]=sender[0]
    msg["To"]=", ".join(recipients)
    msg["Subject"]="SEC fund & stock filing intelligence | "+day
    msg.set_content(digest["markdown"])
    try:
        if smtp_factory:
            smtp=smtp_factory(settings["host"],settings["port"])
        elif settings["port"]==465:
            smtp=smtplib.SMTP_SSL(settings["host"],settings["port"],timeout=30)
        else:
            smtp=smtplib.SMTP(settings["host"],settings["port"],timeout=30)
        with smtp as connection:
            if settings["port"]!=465 and not smtp_factory:
                connection.starttls()
            if settings["user"]:
                connection.login(settings["user"],settings["password"])
            connection.send_message(msg)
        store.finish_send(day,"smtp:accepted")
        return {"status":"sent","digest_id":digest["digest_id"]}
    except Exception as exc:
        store.finish_send(day,None,"SMTP outcome uncertain: "+type(exc).__name__)
        raise RuntimeError("SMTP delivery outcome uncertain; check provider logs before manual retry") from exc
