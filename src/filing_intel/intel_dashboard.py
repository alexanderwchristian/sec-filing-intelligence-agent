"""Live Streamlit control room for both SEC fund and stock filing tracks."""
from __future__ import annotations

from datetime import date, timedelta
import json
import os

from .intel_store import IntelStore
from .intel_monitor import scan_intelligence
from .intel_research import investigate_event
from .intel_digest import prepare_digest, send_digest
from .sec import SecClient


def _db_path() -> str:
    return os.getenv("INTEL_DB_PATH",".filing-intel/intelligence.sqlite3")


def render() -> None:
    import streamlit as st

    st.title("SEC Filing Intelligence")
    st.caption("US mutual funds, ETFs and public-company stocks | Live research workspace")
    with st.sidebar:
        st.markdown("**Intelligence workspace**")
        st.caption("Source: SEC EDGAR. Detector outputs are candidates for human review, not confirmed material events.")
        st.caption("Database: " + _db_path())
        st.caption("SEC_USER_AGENT, OPENAI_API_KEY and email configuration are server-side environment variables.")
    tabs=st.tabs(["Overview","Watchlist","Findings","Investigations",
                  "Daily Briefings","Run Health","Evaluation"])
    with IntelStore(_db_path()) as store:
        watches=store.watches()
        active=[w for w in watches if w["enabled"]]
        runs=store.runs()
        latest=runs[0] if runs else None
        all_events=store.events(limit=6000)
        with tabs[0]:
            st.subheader("Monitoring overview")
            c1,c2,c3,c4=st.columns(4)
            c1.metric("Funds watched",sum(w["kind"]=="fund" for w in active))
            c2.metric("Stocks watched",sum(w["kind"]=="stock" for w in active))
            c3.metric("Detected candidates",len(all_events))
            c4.metric("Last scan",latest["status"] if latest else "Not run")
            if not latest:
                st.info("Add a US fund or stock to your watchlist, then run a scan. No monitor results exist yet.")
            elif latest["status"]!="completed":
                st.error("Latest scan is "+latest["status"]+". Monitoring is incomplete; do not assume no changes.")
                for error in latest["errors"][:6]:
                    st.caption(error)
            else:
                st.success("Latest scan completed for its configured coverage window.")
            st.markdown("**Latest evidence-linked findings**")
            for e in all_events[:6]:
                st.write(e["name"]+" | "+e["category"].replace("_"," ")+" | "+e["form"]+
                         " | "+e["change_type"])
            st.caption("A finding is a change candidate, not a validated investment conclusion. Fund class attribution may require review.")

        with tabs[1]:
            st.subheader("Watchlist")
            with st.form("watch_add"):
                kind=st.selectbox("Type",["fund","stock"],help="Fund includes mutual funds and ETFs.")
                name=st.text_input("Fund or company name",placeholder="Official entity name")
                cik=st.text_input("SEC registrant CIK (digits)",placeholder="320193")
                ticker=st.text_input("Ticker (optional)")
                series_id=st.text_input("Fund series ID, e.g. S000... (optional)")
                class_id=st.text_input("Fund class ID, e.g. C000... (optional)")
                add=st.form_submit_button("Add watch",type="primary")
            if add:
                try:
                    if not cik.isdigit():
                        raise ValueError("Enter numeric CIK from the SEC. A ticker alone may not uniquely identify a fund.")
                    wid=store.add_watch(kind,int(cik),name,ticker=ticker or None,
                                series_id=series_id or None,class_id=class_id or None)
                    st.success("Watch added. ID: "+wid[:12])
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
            st.dataframe([{k:w[k] for k in ("kind","name","cik","ticker","series_id",
                                          "class_id","identity_source","enabled")}
                          for w in watches],use_container_width=True,hide_index=True)
            if active:
                selected=st.selectbox("Disable an existing watch",
                                      options=[w["watch_id"] for w in active],
                                      format_func=lambda wid: next(w["name"]+" ("+w["kind"]+")"
                                                                    for w in active if w["watch_id"]==wid))
                if st.button("Disable selected watch"):
                    store.disable_watch(selected)
                    st.rerun()
            st.divider()
            st.subheader("Manual monitoring")
            c1,c2=st.columns(2)
            with c1:
                since=st.date_input("From filing date",date.today()-timedelta(days=90),key="scan_since")
            with c2:
                until=st.date_input("Through filing date",date.today(),key="scan_until")
            batch_watch_ids=None
            if len(active)>25:
                st.info("Large watchlist: run bounded batches of at most 25 watches. "
                        "One completed batch does NOT mean all watches were scanned.")
                batch_size=st.selectbox("Watches per batch",[5,10,20,25],index=1)
                n_batches=(len(active)+batch_size-1)//batch_size
                batch_number=st.number_input("Batch number (1-based)",min_value=1,
                                              max_value=n_batches,value=1)
                selected=active[(batch_number-1)*batch_size:batch_number*batch_size]
                batch_watch_ids=[w["watch_id"] for w in selected]
                st.caption(str(len(selected))+" of "+str(len(active))+
                           " enabled watches in selected batch "+str(batch_number)+
                           " of "+str(n_batches)+". Run all batches for full coverage.")
            if st.button("Scan selected batch" if batch_watch_ids else "Scan watchlist now",
                         type="primary",disabled=not active):
                try:
                    with st.spinner("Discovering, retrieving and analyzing official SEC filings..."):
                        result=scan_intelligence(store,SecClient(),
                                  since=since.isoformat(),until=until.isoformat(),
                                  mode="on_demand",watch_ids=batch_watch_ids)
                    if result["status"]=="completed":
                        st.success("Selected scan scope completed. Check coverage before "
                                   "claiming the full watchlist was analyzed.")
                    else:
                        st.error("Scan partially completed. Inspect Run Health.")
                    st.json(result)
                except Exception as exc:
                    st.error("Scan could not complete: "+str(exc))

        with tabs[2]:
            st.subheader("Findings and source evidence")
            c1,c2=st.columns(2)
            with c1:
                kind_filter=st.selectbox("Asset type",["All","Fund","Stock"])
            with c2:
                cats=sorted(set(x["category"] for x in all_events))
                category_filter=st.selectbox("Category",["All"]+cats)
            filtered=[e for e in all_events if
                      (kind_filter=="All" or e["kind"]==kind_filter.lower()) and
                      (category_filter=="All" or e["category"]==category_filter)]
            st.caption(str(len(filtered))+" finding(s) shown from the latest 6,000 records. "
                       "All historical records remain queryable through the database.")
            if not filtered:
                st.info("No findings match the filters. Run a scan or broaden the filters.")
            page_size=12
            max_page=max(1,(len(filtered)+page_size-1)//page_size)
            page=st.number_input("Page",min_value=1,max_value=max_page,value=1)
            for e in filtered[(page-1)*page_size:page*page_size]:
                title=(e["name"]+" | "+e["category"].replace("_"," ")+
                       " | "+e["change_type"]+" | "+e["filing_date"])
                with st.expander(title):
                    st.caption("Form "+e["form"]+" | Accession "+e["accession"]+
                               " | "+e["status"]+" | priority "+e["priority"])
                    st.caption("Identity: "+e.get("identity_status","unknown")+
                               " | Effective: "+str(e.get("effective_date") or "unknown"))
                    for label,slot in (("Before",e.get("old_evidence")),
                                       ("After",e.get("new_evidence"))):
                        if slot:
                            st.markdown("**"+label+" (source excerpt)**")
                            st.code(slot.get("quote",""),language=None,wrap_lines=True)
                            if slot.get("source_url","").startswith("https://"):
                                st.link_button("Open "+label.lower()+" SEC filing",
                                               slot["source_url"])
                    st.caption(" | ".join(e.get("uncertainties",[])))
                    st.code(e["event_id"],language=None)
                    if st.button("Investigate this finding",key="res_"+e["event_id"]):
                        with st.spinner("Researching verified filing context..."):
                            try:
                                result=investigate_event(store,e["event_id"])
                                st.json(result)
                            except Exception as exc:
                                st.error(str(exc))
            st.download_button("Export displayed findings as JSON",
                               json.dumps(filtered,indent=2),
                               "sec_intelligence_findings.json","application/json")

        with tabs[3]:
            st.subheader("Evidence-backed investigations")
            st.caption("With OPENAI_API_KEY, the bounded research agent uses read-only filing-history tools. "
                       "Without a key, it returns an explicit human-review checklist.")
            if not all_events:
                st.info("No events to investigate. Scan the watchlist first.")
            else:
                sample=all_events[:2000]
                selected=st.selectbox("Finding to investigate",
                    options=[e["event_id"] for e in sample],
                    format_func=lambda i: next(e["name"]+" | "+e["category"]+" | "+e["filing_date"]
                         for e in sample if e["event_id"]==i))
                prior=store.investigation(selected)
                if prior:
                    st.json(prior)
                if st.button("Run research",type="primary"):
                    with st.spinner("Bounded research in progress..."):
                        result=investigate_event(store,selected,force=True)
                        st.json(result)
                st.caption("AI interpretation requires human review; quoted observations must exactly match stored SEC documents.")

        with tabs[4]:
            st.subheader("Daily research briefings")
            day=st.date_input("Reporting day",date.today(),key="daily_day").isoformat()
            digest=store.digest(day)
            if st.button("Prepare daily briefing",disabled=bool(digest)):
                try:
                    digest=prepare_digest(store,day)
                except Exception as exc:
                    st.error(str(exc))
            if digest:
                st.caption("Status: "+digest["status"]+" | "+digest["digest_id"][:12])
                st.markdown(digest["markdown"])
                st.download_button("Download briefing",digest["markdown"],
                                   "sec-briefing-"+day+".md","text/markdown")
                if digest["status"]=="prepared":
                    if st.button("Email this briefing"):
                        try:
                            st.json(send_digest(store,day))
                        except Exception as exc:
                            st.error(str(exc))
                elif digest["status"]=="unknown":
                    st.error("SMTP outcome unknown. Reconcile with provider logs before a manual retry.")
            else:
                st.info("No briefing for this date. Prepare a report after a completed scan.")
            history=store.digests(30)
            if history:
                st.dataframe([{k:x[k] for k in ("period_day","status","attempt_count",
                                                "run_id","provider_id")} for x in history],
                             hide_index=True,use_container_width=True)

        with tabs[5]:
            st.subheader("Run completeness and recovery")
            if not runs:
                st.info("There are no completed or failed monitoring runs.")
            for r in runs[:25]:
                with st.expander(r["started_at"][:19]+" | "+r["mode"]+" | "+r["status"]):
                    st.write("Window: "+r["since_date"]+" through "+r["until_date"])
                    st.json(r["stats"])
                    for error in r["errors"]:
                        st.error(error)
            st.markdown("**Durable per-watch checkpoints**")
            st.dataframe(store.checkpoints(),hide_index=True,use_container_width=True)
            st.caption("A failed or partially completed scan never advances the affected watch checkpoint.")

        with tabs[6]:
            from .intel_evaluation import evaluate_labeled, verify_grounding
            st.subheader("Evaluation and source grounding")
            st.warning("The original 5-case synthetic benchmark is not real-world fund/stock accuracy. No accuracy claim is made without manually labeled public SEC data.")
            ground=verify_grounding(store,all_events)
            a,b,c=st.columns(3)
            a.metric("Evidence excerpts checked",ground["checked"])
            b.metric("Verified exact excerpts",ground["verified"])
            c.metric("Groundedness",f"{ground['groundedness']:.1%}" if ground["groundedness"] is not None else "Not measured")
            if ground["failures"]:
                st.error("Evidence-source inconsistencies detected:")
                st.json(ground["failures"][:25])
            st.markdown("**Evaluate a public-file gold dataset**")
            st.caption("Upload JSON as an array of labeled events, or an object containing a labels array. Use only independently labeled public SEC filing examples.")
            uploaded=st.file_uploader("Manually labeled public-event JSON",type=["json"],key="intel_labels")
            if uploaded:
                try:
                    parsed=json.load(uploaded)
                    gold=parsed.get("labels",[]) if isinstance(parsed,dict) else parsed
                    if not isinstance(gold,list) or any(not isinstance(e,dict) for e in gold):
                        raise ValueError("Expected a list of labeled event objects")
                    scores=evaluate_labeled(gold,all_events)
                    if scores["status"]=="not_measured":
                        st.info(scores["reason"])
                    else:
                        st.json(scores)
                        st.caption("Scores apply ONLY to the uploaded labels and current database, not general SEC accuracy.")
                except Exception as exc:
                    st.error("Could not evaluate labels: "+str(exc))
            st.markdown("**Limits:** Source-normalized offsets do not guarantee precise original HTML anchors. Fund share-class attribution and effective dates remain subject to validation.")
