"""Both US SEC filing tracks: deterministic, offline end-to-end acceptance tests."""
from __future__ import annotations

from datetime import date
import hashlib
import json

import pytest

from filing_intel.categories import detect_events,canonical_text,identity_status
from filing_intel.intel_store import IntelStore
from filing_intel.intel_monitor import scan_intelligence,choose_baseline
from filing_intel.intel_research import investigate_event,_verify_observations,research_tool
from filing_intel.intel_digest import generate_briefing,prepare_digest,send_digest
from filing_intel.sec import FilingRecord
from filing_intel.cli import main


def rec(year,cik,form,number=1):
    return FilingRecord(f"{cik:010d}-{year%100:02d}-{number:06d}",
                        f"{year}-02-10",f"{year}.htm",form,f"{year-1}-12-31")


def stock_doc(revenue,person):
    return (f"<html><body><h2>Item 7. Management Discussion</h2>"
            f"<p>Total revenue for the year was {revenue} million dollars "
            f"because customers adopted our cloud platform and recurring services.</p>"
            f"<p>The chief financial officer {person} supervised the year-end "
            f"controls and completed the comprehensive annual financial review.</p>"
            f"<p>Cybersecurity and associated risk factors may materially affect "
            f"operations and future results across our global infrastructure.</p>"
            f"</body></html>").encode()


def fund_doc(manager,fee,*,class_id=True):
    marker="S000000001 C000000001" if class_id else ""
    return (f"<html><body><h2>Northstar Growth Fund</h2>{marker}"
            f"<p>The portfolio manager {manager} is responsible for day-to-day "
            f"investment decisions across the Northstar Growth Fund portfolio.</p>"
            f"<p>The annual management fee is {fee}% for the specified "
            f"investment advisory services and fund operating expenses.</p>"
            f"<p>The Fund benchmark index is the Northstar Broad Market Index "
            f"for performance comparison during each fiscal year.</p>"
            f"<p>The Fund's investment objective is long-term growth of capital "
            f"through diversified exposure to publicly traded companies.</p>"
            f"</body></html>").encode()


class PublicSecFixture:
    def __init__(self):
        self.records={
            1:[rec(2024,1,"10-K"),rec(2025,1,"10-K")],
            2:[rec(2024,2,"485BPOS"),rec(2025,2,"485BPOS")],
        }
        self.docs={
            self.records[1][0].accession:stock_doc("20","Morgan"),
            self.records[1][1].accession:stock_doc("30","Taylor"),
            self.records[2][0].accession:fund_doc("Alice Smith","0.50"),
            self.records[2][1].accession:fund_doc("Bob Jones","0.65"),
        }
        self.fetched=[]

    def discover_filings(self,cik):
        return list(self.records[cik])

    def fetch_document(self,cik,record):
        self.fetched.append(record.accession)
        doc=self.docs[record.accession]
        if isinstance(doc,Exception):
            raise doc
        return doc,doc.decode()


@pytest.fixture
def store(tmp_path):
    with IntelStore(tmp_path/"intelligence.sqlite3") as s:
        s.add_watch("stock",1,"Synthetic Cloud Inc")
        s.add_watch("fund",2,"Northstar Growth Fund",
                    series_id="S000000001",class_id="C000000001")
        yield s


def test_both_tracks_and_idempotent_replay_with_quoted_evidence(store):
    client=PublicSecFixture()
    first=scan_intelligence(store,client,since="2025-01-01",until="2025-12-31")
    events=store.events(limit=5000)
    assert first["status"]=="completed"
    assert {e["kind"] for e in events}=={"fund","stock"}
    assert {"portfolio_manager","fees_expenses"}<=set(e["category"] for e in events)
    assert any(e["category"]=="financial_performance" for e in events)
    for e in events:
        current=store.filing(e["watch_id"],e["accession"])
        if e["new_evidence"]:
            proof=e["new_evidence"]
            assert current["normalized_text"][proof["offset"]:proof["offset"]+len(proof["quote"])]==proof["quote"]
        if e["old_evidence"]:
            baseline=store.filing(e["watch_id"],e["baseline_accession"])
            proof=e["old_evidence"]
            assert baseline["normalized_text"][proof["offset"]:proof["offset"]+len(proof["quote"])]==proof["quote"]
    fetched=list(client.fetched)
    second=scan_intelligence(store,client,since="2025-01-01",until="2025-12-31")
    assert second["status"]=="completed"
    assert second["stats"]["new_events"]==0
    assert client.fetched==fetched
    assert store.events(limit=5000)==events
    assert all(s["through_date"]=="2025-12-31" for s in store.checkpoints())


def test_fund_identity_needs_review_without_class_proof(store):
    client=PublicSecFixture()
    client.docs[rec(2025,2,"485BPOS").accession]=fund_doc("New Manager","0.65",class_id=False)
    result=scan_intelligence(store,client,since="2025-01-01",until="2025-12-31")
    assert result["status"]=="completed"
    events=store.events(kind="fund")
    assert events
    assert all(e["status"]=="needs_review" for e in events)
    assert all(e["identity_status"]=="unconfirmed_share_class" for e in events)


def test_partial_fund_fetch_does_not_imply_no_changes_or_advance_checkpoint(store):
    client=PublicSecFixture()
    client.docs[rec(2025,2,"485BPOS").accession]=RuntimeError("public SEC outage")
    result=scan_intelligence(store,client,since="2025-01-01",until="2025-12-31")
    assert result["status"]=="partial"
    assert result["stats"]["filing_errors"]==1
    assert len(store.checkpoints())==1
    report,_=generate_briefing(store,"2025-12-31")
    assert "Coverage warning" in report
    assert "No qualifying candidate changes detected" not in report


def test_stock_8k_is_event_first_and_no_wrong_fund_comparison():
    e=rec(2025,1,"8-K")
    stock_baseline,why=choose_baseline(e,[rec(2024,1,"10-K")],"stock")
    assert stock_baseline is None and "event-first" in why
    fund=rec(2025,2,"497K")
    base,why=choose_baseline(fund,[rec(2024,2,"N-1A")],"fund")
    assert base is None


def test_ambiguous_fund_class_identity_never_marked_verified(store):
    watch=[w for w in store.watches() if w["kind"]=="fund"][0]
    text=canonical_text(fund_doc("Alice Smith","0.75",class_id=False).decode())
    assert identity_status(watch,text)=="unconfirmed_share_class"


def test_research_fallback_and_source_verification(store,monkeypatch):
    client=PublicSecFixture()
    scan_intelligence(store,client,since="2025-01-01",until="2025-12-31")
    event=store.events()[0]
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)
    answer=investigate_event(store,event["event_id"])
    assert answer["status"]=="ai_not_enabled"
    assert answer["follow_ups"]
    assert store.investigation(event["event_id"])==answer
    fake=[{"accession":event["accession"],"quote":"fabricated SEC excerpt"},
          {"accession":event["accession"],"quote":(event["new_evidence"] or event["old_evidence"])["quote"]}]
    accepted=_verify_observations(store,event,fake)
    assert len(accepted)==1
    assert accepted[0]["source_url"].startswith("https://www.sec.gov/")
    assert research_tool(store,event["watch_id"],"invalid",{})["status"]=="unknown_tool"


def test_digest_status_and_idempotent_send_ledger(store,monkeypatch):
    # Without a scan, an empty digest must not claim 'all clear'.
    report,_=generate_briefing(store,"2025-12-31")
    assert "Coverage warning" in report
    doc=prepare_digest(store,"2025-12-31")
    assert doc["status"]=="prepared"
    assert prepare_digest(store,"2025-12-31")["digest_id"]==doc["digest_id"]
    with pytest.raises(ValueError,match="SMTP_HOST"):
        send_digest(store,"2025-12-31")
    assert store.digest("2025-12-31")["status"]=="prepared"
    monkeypatch.setenv("SMTP_HOST","smtp.test")
    monkeypatch.setenv("EMAIL_FROM","research@example.org")
    monkeypatch.setenv("EMAIL_TO","analyst@example.org")
    sent=[]
    class FakeSMTP:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def send_message(self,msg):sent.append(msg)
        def login(self,*args):pass
    assert send_digest(store,"2025-12-31",smtp_factory=lambda *_:FakeSMTP())["status"]=="sent"
    assert send_digest(store,"2025-12-31",smtp_factory=lambda *_:FakeSMTP())["status"]=="already_sent"
    assert len(sent)==1


def test_cli_intelligence_add_status_and_disable(tmp_path,capsys):
    db=str(tmp_path/"cli.sqlite3")
    assert main(["intelligence","add","--kind","stock","--cik","320193",
                 "--name","Apple","--db",db])==0
    wid=json.loads(capsys.readouterr().out)["watch_id"]
    assert main(["intelligence","status","--db",db])==0
    assert len(json.loads(capsys.readouterr().out)["watchlist"])==1
    assert main(["intelligence","disable","--watch-id",wid,"--db",db])==0
    capsys.readouterr()
    with IntelStore(db) as s:
        assert s.watches()[0]["enabled"]==0


def test_duplicate_identity_and_invalid_class(store):
    fund=[w for w in store.watches() if w["kind"]=="fund"][0]
    assert store.add_watch("fund",2,"Northstar Growth Fund",
                 series_id="S000000001",class_id="C000000001")==fund["watch_id"]
    assert len(store.watches())==2
    with pytest.raises(ValueError,match="series"):
        store.add_watch("fund",2,"Fund",class_id="C000000001")
