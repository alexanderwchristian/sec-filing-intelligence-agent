from pathlib import Path

import pytest

from filing_intel.cli import ROOT, sample_pair
from filing_intel.detect import compare
from filing_intel.evaluate import evaluate
from filing_intel.models import Filing
from filing_intel.parser import extract_risk_section, segment


def test_demo_produces_grounded_candidates():
    before, after = sample_pair()
    report = compare(before, after)
    assert report.changes
    assert any("ransomware" in c.new_quote.lower() for c in report.changes)
    assert any(c.change_type == "removed" for c in report.changes)
    assert all(c.old_quote in before.text for c in report.changes if c.old_quote)
    assert all(c.new_quote in after.text for c in report.changes if c.new_quote)
    assert all(c.old_url == before.source_url for c in report.changes)
    assert all(c.new_url == after.source_url for c in report.changes)


def test_no_change_and_reorder_are_ignored():
    before, _ = sample_pair()
    report = compare(before, before)
    assert report.changes == []
    paragraphs = before.text.strip().split("\n\n")
    reordered = Filing(before.company, before.form, "2025", before.source_url,
                       "\n\n".join(reversed(paragraphs)))
    assert compare(before, reordered).changes == []


def test_parser_skips_table_of_contents():
    section = ("Markets and demand may change significantly, affecting our customer retention "
               "and revenue in future periods. " * 5)
    html = ("<html><body><p>CONTENTS Item 1A. Risk Factors 12 Item 1B 30</p>"
            f"<p>Item 1A. Risk Factors</p><p>{section}</p>"
            "<p>Item 1B. Unresolved Staff Comments</p></body></html>")
    assert "Markets and demand" in extract_risk_section(html)
    assert "Unresolved Staff Comments" not in extract_risk_section(html)


def test_missing_risk_section_fails_closed():
    with pytest.raises(ValueError, match="Could not locate"):
        extract_risk_section("Item 1. Business. Item 2. Properties.")


def test_invalid_form_fails():
    before, after = sample_pair()
    wrong = Filing(after.company, "8-K", after.filing_date, after.source_url, after.text)
    with pytest.raises(ValueError, match="same filing form"):
        compare(before, wrong)


def test_synthetic_evaluation_is_explicitly_labeled():
    metrics = evaluate(ROOT / "examples" / "evaluation_cases.json")
    assert metrics["cases"] == 5
    assert "not an estimate" in metrics["warning"]
    assert metrics["f1"] >= 0.75


def test_chunks_preserve_exact_text():
    before, _ = sample_pair()
    chunks = segment(before.text)
    assert len(chunks) == 4
    assert all(c in before.text for c in chunks)
