"""No network/API calls in these regression tests."""
import json
import pytest

from filing_intel.intel_trace_eval import evaluate_pinned, PINNED_FILINGS
from filing_intel.intel_tracing import enabled, step_span, workflow, capture_response, flush


class FakeSec:
    def fetch_document(self, cik, record):
        if cik == 320193:
            text = ("Apple Inc. announced that its chief financial officer was "
                    "appointed to a new leadership position. "
                    "The board of directors oversees the governance process.")
        else:
            text = ("Vanguard 500 Index Fund, S000002839 C000092055, "
                    "has an investment objective to track a broad market index. "
                    "The annual fund operating expenses include a management fee.")
        html = "<html><body><p>" + text + "</p></body></html>"
        return html.encode("utf-8"), html


def test_pinned_real_sec_smoke_has_two_tracks_and_exact_source_grounding(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ENABLE_OPENAI_TRACING", raising=False)
    report = evaluate_pinned(db=str(tmp_path / "test.sqlite3"), client=FakeSec())
    assert report["status"] == "passed"
    assert len(report["filings"]) == 2
    assert set(report["candidate_counts"]) == {"fund", "stock"}
    assert all(row["candidate_count"] > 0 for row in report["filings"])
    assert report["source_grounding"]["groundedness"] == 1.0
    assert report["labeled_event_evaluation"]["status"] == "not_measured"
    assert report["ai_investigation"]["status"] == "not_requested"
    assert all(row["source_url"].startswith("https://www.sec.gov/Archives/")
               for row in report["filings"])


def test_ai_never_runs_without_explicit_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        evaluate_pinned(db=str(tmp_path / "ai.sqlite3"), client=FakeSec(), ai=True)


def test_invalid_gold_is_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("ENABLE_OPENAI_TRACING", raising=False)
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({"labels": {"invalid": "not list"}}))
    with pytest.raises(ValueError, match="Gold file"):
        evaluate_pinned(db=str(tmp_path / "gold.sqlite3"), client=FakeSec(),
                        gold_path=str(gold))


def test_disabled_tracing_needs_no_sdk(monkeypatch):
    monkeypatch.delenv("ENABLE_OPENAI_TRACING", raising=False)
    assert not enabled()
    with workflow("offline"), step_span("offline"):
        capture_response(object())
    flush()


def test_pinned_sources_are_hard_bounded():
    assert len(PINNED_FILINGS) == 2
    assert {row["kind"] for row in PINNED_FILINGS} == {"fund", "stock"}
    assert all(row["record"].accession for row in PINNED_FILINGS)
