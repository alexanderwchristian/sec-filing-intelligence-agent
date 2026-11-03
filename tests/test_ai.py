import sys
from types import SimpleNamespace

from filing_intel.ai import interpret_changes
from filing_intel.cli import sample_pair
from filing_intel.detect import compare


def test_rejects_unverifiable_ai_evidence(monkeypatch):
    old, new = sample_pair()
    report = compare(old, new)
    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text='{"interpretation":"Unverified claim",'
                                               '"old_evidence":"",'
                                               '"new_evidence":"Not in source"}')
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs:
                           SimpleNamespace(responses=FakeResponses())))
    interpret_changes(report, api_key="fake", max_items=1)
    assert not report.changes[0].ai_evidence_verified
    assert report.changes[0].ai_interpretation == ""
    assert any("Discarded" in warning for warning in report.warnings)


def test_accepts_exact_ai_evidence(monkeypatch):
    old, new = sample_pair()
    report = compare(old, new)
    quote = report.changes[0].new_quote[:26]
    import json
    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text=json.dumps({"interpretation":"A newly added risk paragraph.",
                                               "old_evidence":"", "new_evidence":quote}))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs:
                           SimpleNamespace(responses=FakeResponses())))
    interpret_changes(report, api_key="fake", max_items=1)
    assert report.changes[0].ai_evidence_verified
    assert report.changes[0].ai_interpretation == "A newly added risk paragraph."
