"""Conservative, explainable risk-factor change candidates.

The model never invents quotes. Changes must quote exact document text.
Not a legal materiality determination or a semantic equivalence model.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import Change, Filing, Report
from .parser import normalize_spaces, segment

_HIGH = ("material weakness", "going concern", "ransomware", "cyberattack", "security breach",
         "default", "liquidity crisis", "bankruptcy", "restatement", "regulatory enforcement")
_MEDIUM = ("cybersecurity", "cyber", "regulatory", "interest rate", "inflation", "supply chain",
           "litigation", "privacy", "concentration", "single regional", "tariff", "competition")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    overlap = len(a & b) / len(a | b)
    # Shortlist on token similarity so SequenceMatcher is bounded in practice.
    if overlap < 0.20:
        return overlap * 0.5
    order = SequenceMatcher(None, normalize_spaces(left).lower(),
                            normalize_spaces(right).lower(), autojunk=False).ratio()
    return 0.40 * overlap + 0.60 * order


def _tier(old: str, new: str) -> str:
    combined = (old + " " + new).lower()
    if any(k in combined for k in _HIGH):
        return "high"
    if any(k in combined for k in _MEDIUM):
        return "medium"
    return "low"


def _explanation(kind: str) -> str:
    if kind == "revised":
        return "Wording changed compared with the prior filing. Review both cited passages."
    if kind == "added":
        return "No close text match was found in the previous filing. Review the new passage."
    return "No close text match was found in the current filing. Review the previous passage."


def compare(old: Filing, new: Filing, *, max_changes: int = 20,
            change_threshold: float = 0.87, match_threshold: float = 0.49) -> Report:
    """Compare extracted sections using one-to-one alignment, without hallucinated evidence.

    Changes are candidate *text changes*, not verified economic event changes.
    """
    if old.form != new.form:
        raise ValueError("Compare documents with the same filing form")
    if not (0 < match_threshold < change_threshold < 1):
        raise ValueError("Similarity thresholds must be between 0 and 1 and ordered")
    if max_changes < 1:
        raise ValueError("max_changes must be positive")

    before = segment(old.text)
    after = segment(new.text)
    if not before or not after:
        raise ValueError("Both filing sections need substantive text to compare")

    report = Report(company=new.company, old_date=old.filing_date,
                    new_date=new.filing_date, old_url=old.source_url, new_url=new.source_url)
    if len(before) > 350 or len(after) > 350:
        report.warnings.append("Large section: only the first 350 text units were compared")
        before, after = before[:350], after[:350]

    # Globally align the strongest pairs first to reduce noisy one-to-many matches.
    candidate_pairs: list[tuple[float, int, int]] = []
    old_sets = [_tokens(value) for value in before]
    new_sets = [_tokens(value) for value in after]
    for i, old_text in enumerate(before):
        for j, new_text in enumerate(after):
            overlap = len(old_sets[i] & new_sets[j])
            union = len(old_sets[i] | new_sets[j])
            jac = overlap / union if union else 0
            if jac >= 0.20:
                value = _similarity(old_text, new_text)
                if value >= match_threshold:
                    candidate_pairs.append((value, i, j))

    candidate_pairs.sort(reverse=True)
    old_matched, new_matched = set(), set()
    events: list[Change] = []
    for similarity, i, j in candidate_pairs:
        if i in old_matched or j in new_matched:
            continue
        old_matched.add(i)
        new_matched.add(j)
        if similarity >= change_threshold:
            continue
        events.append(Change("revised", _tier(before[i], after[j]), before[i], after[j],
                             old.source_url, new.source_url, round(similarity, 3), _explanation("revised")))

    for j, text in enumerate(after):
        if j not in new_matched:
            events.append(Change("added", _tier("", text), "", text, old.source_url,
                                 new.source_url, 0.0, _explanation("added")))
    for i, text in enumerate(before):
        if i not in old_matched:
            events.append(Change("removed", _tier(text, ""), text, "", old.source_url,
                                 new.source_url, 0.0, _explanation("removed")))

    # Attention is a keyword-based triage aid, NOT a probability or materiality assessment.
    priority = {"high": 0, "medium": 1, "low": 2}
    kind_order = {"revised": 0, "added": 1, "removed": 2}
    events.sort(key=lambda event: (priority[event.attention], kind_order[event.change_type],
                                   event.new_quote[:50] or event.old_quote[:50]))
    report.changes = events[:max_changes]
    if len(events) > max_changes:
        report.warnings.append(f"Showing top {max_changes} of {len(events)} candidate changes")
    report.warnings.append("Attention tiers are keyword heuristics; not legal or financial materiality judgments")
    return report
