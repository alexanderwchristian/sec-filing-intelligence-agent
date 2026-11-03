"""Markdown output with traceable evidence and explicit uncertainty."""

from __future__ import annotations

from .models import Report


def to_markdown(report: Report) -> str:
    c = report.counts
    lines = [f"# Filing Change Review: {report.company}", "",
             f"**Comparison:** {report.old_date} vs {report.new_date} (Form 10-K, Item 1A)",
             "", f"**Candidates:** {len(report.changes)}"
             f" ({c['added']} added, {c['revised']} revised, {c['removed']} removed)", "",
             "This report identifies **text-change candidates**, not verified material events.",
             "Review the original filings before drawing conclusions.", "",
             f"[Previous filing]({report.old_url}) | [Current filing]({report.new_url})", ""]
    for idx, change in enumerate(report.changes, start=1):
        lines.extend([f"## {idx}. {change.change_type.title()} | {change.attention.title()} attention",
                      "", change.rationale, ""])
        if change.old_quote:
            lines.extend(["**Before (verbatim):**", "", f"> {change.old_quote}", "",
                          f"Source: {change.old_url}", ""])
        if change.new_quote:
            lines.extend(["**After (verbatim):**", "", f"> {change.new_quote}", "",
                          f"Source: {change.new_url}", ""])
        if change.ai_interpretation:
            lines.extend([f"**AI interpretation (review required):** {change.ai_interpretation}", ""])
    if report.warnings:
        lines.extend(["## Limitations", ""])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines) + "\n"
