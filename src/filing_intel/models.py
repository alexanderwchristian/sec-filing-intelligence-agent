"""Explicit data contracts for documents, evidence and change results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Filing:
    company: str
    form: str
    filing_date: str
    source_url: str
    text: str
    accession: str = ""


@dataclass
class Change:
    change_type: str  # added, removed, or revised
    attention: str  # high, medium, or low; NOT a materiality determination
    old_quote: str
    new_quote: str
    old_url: str
    new_url: str
    similarity: float
    rationale: str
    ai_interpretation: str = ""
    ai_evidence_verified: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    company: str
    old_date: str
    new_date: str
    old_url: str
    new_url: str
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scope: str = "Item 1A Risk Factors of two 10-K filings"
    method: str = "Heuristic text alignment with verbatim document evidence"

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def counts(self) -> dict[str, int]:
        return {kind: sum(c.change_type == kind for c in self.changes)
                for kind in ("added", "revised", "removed")}
