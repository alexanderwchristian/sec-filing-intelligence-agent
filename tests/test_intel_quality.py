"""Adversarial and evaluator tests for the v2 filing intelligence workspace."""
import json
import sqlite3

import pytest

from filing_intel.intel_store import IntelStore
from filing_intel.intel_evaluation import evaluate_labeled,verify_grounding
from filing_intel.intel_semantic import review_candidates
from filing_intel.intel_digest import prepare_digest,send_digest


def example_event():
    return {
      "event_id":"evt-a","watch_id":"watch-a","kind":"fund",
      "cik":1,"name":"Example Fund","series_id":"S000000001","class_id":"C000000001",
      "form":"497K","filing_date":"2025-03-01","accession":"0000000001-25-000001",
      "baseline_accession":None,"category":"fees_expenses",
      "change_type":"added","effective_date":None,
      "identity_status":"unconfirmed_share_class",
      "old_evidence":None,
      "new_evidence":{"quote":"The annual management fee is 0.65 percent.",
                      "source_url":"https://www.sec.gov/sample","offset":0},
      "source_url":"https://www.sec.gov/sample"
    }


def test_semantic_evidence_must_be_exact_and_original_candidates_retained():
    item=example_event()
    class FakeReply:
        output_text=json.dumps({"assessments":[{
          "event_id":"evt-a","verdict":"substantive_candidate",
          "reason":"Fees increased","evidence_quote":"Fabricated fee disclosure"
        }]})
    class FakeClient:
        class responses:
            @staticmethod
            def create(**kwargs):
                return FakeReply()
    reviewed,warnings=review_candidates([item],client=FakeClient())
    assert not warnings
    assert len(reviewed)==1
    assert reviewed[0]["semantic_review"]["status"]=="invalid_evidence"
    assert reviewed[0]["new_evidence"]["quote"]=="The annual management fee is 0.65 percent."


def test_semantic_model_unavailable_does_not_drop_candidate(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)
    reviewed,warnings=review_candidates([example_event()])
    assert len(reviewed)==1
    assert warnings
    assert reviewed[0]["semantic_review"]["status"]=="unavailable_no_key"


def test_strict_and_relaxed_f1_differ_on_effective_date():
    gold=[{**example_event(),"effective_date":"2025-04-01"}]
    pred=[{**example_event(),"effective_date":"2025-05-01"}]
    outcome=evaluate_labeled(gold,pred)
    assert outcome["strict"]["f1"]==0.0
    assert outcome["relaxed"]["f1"]==1.0
    assert evaluate_labeled([],pred)["status"]=="not_measured"


def test_immutable_filing_history_and_grounding(tmp_path):
    from filing_intel.sec import FilingRecord
    with IntelStore(tmp_path/"s.sqlite3") as store:
        wid=store.add_watch("stock",1,"Test")
        record=FilingRecord("0000000001-25-000001","2025-03-01","a.htm","10-K")
        store.put_filing(wid,record,"https://www.sec.gov/sample",
                         b"risk disclosure","risk disclosure","registrant_only")
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute("UPDATE intel_filings SET raw_content=x'01'")
        with pytest.raises(ValueError,match="hash mismatch"):
            store.put_filing(wid,record,"https://www.sec.gov/sample",
                             b"changed filing","risk disclosure","registrant_only")
        event={
          **example_event(),"kind":"stock","watch_id":wid,"cik":1,
          "accession":record.accession,
          "new_evidence":{"quote":"risk disclosure",
                          "source_url":"https://www.sec.gov/sample","offset":0}
        }
        assert verify_grounding(store,[event])["groundedness"]==1.0
        event["new_evidence"]["quote"]="not present"
        assert verify_grounding(store,[event])["groundedness"]==0.0


def test_email_unknown_state_blocks_blind_retries(tmp_path,monkeypatch):
    with IntelStore(tmp_path/"s.sqlite3") as store:
        prepare_digest(store,"2025-04-01")
        monkeypatch.setenv("SMTP_HOST","smtp.test")
        monkeypatch.setenv("EMAIL_FROM","research@example.org")
        monkeypatch.setenv("EMAIL_TO","researcher@example.org")
        class BrokenSMTP:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def send_message(self,msg):raise OSError("network dropped after transmission")
        with pytest.raises(RuntimeError,match="outcome uncertain"):
            send_digest(store,"2025-04-01",smtp_factory=lambda *_:BrokenSMTP())
        assert store.digest("2025-04-01")["status"]=="unknown"
        with pytest.raises(RuntimeError,match="already in progress"):
            send_digest(store,"2025-04-01",smtp_factory=lambda *_:BrokenSMTP())
