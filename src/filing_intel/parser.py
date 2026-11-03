"""Extract risk-factor sections and stable comparison units from SEC documents."""

from __future__ import annotations

import re
from bs4 import BeautifulSoup


_START = re.compile(r"\bitem\s*1\s*a\s*[.\-:\s]*risk\s+factors?\b", re.I)
_END = re.compile(r"\bitem\s*1\s*[bc]\b|\bitem\s*2\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def as_plain_text(content: str) -> str:
    """Readable text, not a raw HTML or XBRL dump."""
    if "<html" not in content.lower() and "<body" not in content.lower() and "</p>" not in content.lower():
        return content
    soup = BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "head"]):
        node.decompose()
    for node in soup.find_all(attrs={"style": re.compile(r"display\s*:\s*none", re.I)}):
        node.decompose()
    return soup.get_text(separator="\n")


def extract_risk_section(content: str) -> str:
    """Return substantive Item 1A section, avoiding short table-of-contents entries.

    A heuristic by design. If headings cannot be located, fail rather than invent
    a risk-factor section. Some issuers use unusual filing formats.
    """
    text = normalize_spaces(as_plain_text(content))
    starts = list(_START.finditer(text))
    if not starts:
        raise ValueError("Could not locate 'Item 1A. Risk Factors' in filing text")

    candidates: list[str] = []
    for start in starts:
        next_end = _END.search(text, start.end())
        if next_end:
            value = text[start.end():next_end.start()].strip()
            if 400 <= len(value) <= 600_000:
                candidates.append(value)
    if not candidates:
        raise ValueError("Risk-factor headings found, but no substantive section extracted")
    # Table-of-contents entries tend to be short; choose largest bounded span.
    return max(candidates, key=len)


def _split_long_paragraph(value: str, max_chars: int) -> list[str]:
    sentences = _SENTENCE.split(value)
    result: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 > max_chars and current:
            result.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        result.append(current)
    return result


def segment(text: str, max_chars: int = 850) -> list[str]:
    """Chunk by paragraph, then sentence. Keep verbatim evidence in each unit."""
    # Documents often use newlines between short HTML tokens. Prefer blank lines,
    # otherwise group sentences from the normalized text.
    paragraphs = re.split(r"\n\s*\n+", text.strip())
    if len(paragraphs) == 1:
        paragraphs = [text]
    chunks: list[str] = []
    for paragraph in paragraphs:
        value = normalize_spaces(paragraph)
        if not value:
            continue
        for piece in _split_long_paragraph(value, max_chars):
            if len(piece) >= 65 and len(piece.split()) >= 9:
                chunks.append(piece)
    # Preserve order, remove exact repeats that can come from repeated SEC markup.
    seen: set[str] = set()
    result: list[str] = []
    for chunk in chunks:
        key = re.sub(r"[^a-z0-9]", "", chunk.lower())
        if key not in seen:
            result.append(chunk)
            seen.add(key)
    return result
