"""Form-specific, evidence-grounded candidate detectors for US SEC fund and stock filings.

These deterministic detectors produce review candidates, NEVER verified material
events. Semantic LLM investigation is a separate stage. No employer-derived code.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from .intel_store import stable_id, utcnow


# The category registry makes each specialist detector independently testable.
FUND_DETECTORS = {
    "portfolio_manager": r"\b(?:portfolio manager|portfolio management team|co.portfolio manager|managed by)\b",
    "benchmark": r"\b(?:benchmark(?: index)?|performance index|tracking index|underlying index)\b",
    "fees_expenses": r"\b(?:management fee|advisory fee|net expense|gross expense|expense ratio|annual fund operating expenses|fee waiver)\b",
    "investment_objective": r"\b(?:investment objective|seeks to (?:achieve|provide|track)|investment goal)\b",
    "investment_strategy": r"\b(?:principal investment strateg|investment strateg|invests at least|principal risk)\b",
    "fund_lifecycle": r"\b(?:liquidat(?:e|ion|ing)|merg(?:er|e|ed)|reorganiz|closed to new investors|terminate the fund|launch(?:es|ed)? the fund)\b",
    "share_class": r"\b(?:share class|class [A-Z] shares|institutional class|investor class|class-specific expense)\b",
}
STOCK_DETECTORS = {
    "financial_performance": r"\b(?:net sales|net revenue|total revenue|net income|earnings per share|operating income|gross margin|operating cash flow)\b",
    "risk_disclosure": r"\b(?:risk factors?|material risk|cybersecurity|litigation|going concern|material weakness)\b",
    "management_governance": r"\b(?:chief executive officer|chief financial officer|board of directors|director resign|appointed as|executive officer)\b",
    "liquidity_financing": r"\b(?:liquidity|credit facilit|senior notes|debt covenant|convertible notes|equity offering|common stock offering)\b",
    "guidance": r"\b(?:financial guidance|full.year outlook|earnings guidance|revenue outlook|forward.guidance)\b",
    "corporate_event": r"\b(?:merger agreement|acquisition agreement|acquir(?:e|ed|ing) .* company|material definitive agreement|bankruptcy|restructur)\b",
}
FORM_FAMILIES = {
    "10-K": "annual", "10-K/A": "annual_amendment",
    "10-Q": "quarterly", "10-Q/A": "quarterly_amendment",
    "8-K": "current", "8-K/A": "current_amendment",
    "N-1A": "fund_prospectus", "485APOS": "fund_prospectus",
    "485BPOS": "fund_prospectus", "497": "fund_supplement", "497K": "fund_supplement",
    "N-14": "fund_reorganization",
}
STOCK_FORMS = frozenset(k for k in FORM_FAMILIES if k.startswith(("10-","8-")))
FUND_FORMS = frozenset(FORM_FAMILIES) - STOCK_FORMS
HIGH_PRIORITY = frozenset({"fees_expenses","portfolio_manager","fund_lifecycle",
                          "financial_performance","corporate_event","liquidity_financing"})
MAX_MATCHES_PER_CATEGORY = 160
MAX_EVENTS_PER_DOCUMENT = 700


@dataclass(frozen=True)
class EvidenceSlice:
    quote: str
    offset: int


def canonical_text(value: str) -> str:
    """Normalize SEC HTML for stable, inspectable character offsets."""
    from .parser import as_plain_text
    plain = as_plain_text(value)
    plain = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
    return plain.strip()


def _sentences(text: str) -> list[EvidenceSlice]:
    """Bound passage size while preserving exact spans in normalized source."""
    if not text:
        return []
    # Long SEC paragraphs contain many sentences; derive offsets from regex
    # boundaries instead of a lossy normalized rejoin.
    bounds = [0]
    for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z(0-9])", text):
        bounds.append(m.end())
    bounds.append(len(text))
    result = []
    for a,b in zip(bounds,bounds[1:]):
        chunk = text[a:b].strip()
        if len(chunk)<28:
            continue
        if len(chunk)<=1100:
            result.append(EvidenceSlice(chunk,text.find(chunk,a,b)))
        else:
            # A long sentence is split by stable source offsets, not truncated.
            for pos in range(a,b,850):
                part=text[pos:min(pos+850,b)].strip()
                if len(part)>=28:
                    result.append(EvidenceSlice(part,text.find(part,pos,b)))
    return result


def relevant_slices(text: str, category: str, kind: str) -> list[EvidenceSlice]:
    patterns=FUND_DETECTORS if kind=="fund" else STOCK_DETECTORS
    pattern=re.compile(patterns[category],re.IGNORECASE)
    result=[]
    seen=set()
    for s in _sentences(text):
        if pattern.search(s.quote):
            identity=re.sub(r"\W+","",s.quote.lower())
            if identity not in seen:
                result.append(s)
                seen.add(identity)
    if len(result)>MAX_MATCHES_PER_CATEGORY:
        raise ValueError("Detector budget exceeded for "+category+"; results not silently truncated")
    return result


def _match_score(a: str,b: str)->float:
    a_words=set(re.findall(r"[a-z0-9]+",a.lower()))
    b_words=set(re.findall(r"[a-z0-9]+",b.lower()))
    overlap=len(a_words&b_words)/max(1,len(a_words|b_words))
    return 0.6*SequenceMatcher(None,a[:1000],b[:1000]).ratio()+0.4*overlap


def _match_pairs(old:list[EvidenceSlice],new:list[EvidenceSlice]):
    """One-to-one within category; exact matches are ignored."""
    used_old=set()
    pairs=[]
    for new_s in new:
        candidates=[(i,_match_score(old_s.quote,new_s.quote)) for i,old_s in enumerate(old) if i not in used_old]
        best=max(candidates,key=lambda x:x[1],default=(-1,0.0))
        if best[1]>=0.60:
            used_old.add(best[0])
            old_s=old[best[0]]
            if old_s.quote!=new_s.quote:
                pairs.append(("revised",old_s,new_s))
        else:
            pairs.append(("added",None,new_s))
    for i,old_s in enumerate(old):
        if i not in used_old:
            pairs.append(("removed",old_s,None))
    return pairs


def _effective_date(quote:str)->str|None:
    # Only extract an explicit ISO date. Other date formats require contextual
    # normalization and remain deliberately null rather than guessed.
    match=re.search(r"(?:effective|as of|beginning)\s+(?:on\s+)?(20\d{2}-\d\d-\d\d)",quote,re.I)
    if not match:
        return None
    from datetime import date
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


def identity_status(watch:dict,text:str)->str:
    if watch["kind"]=="stock":
        return "registrant_only"
    # For multi-fund registrants, CIK alone never establishes the fund identity.
    # Even an exact name match needs human verification of series/class coverage.
    name=watch["name"].lower().strip()
    if not name or name not in text.lower():
        return "unresolved"
    series=watch.get("series_id")
    class_id=watch.get("class_id")
    if class_id:
        if class_id not in text or (series and series not in text):
            return "unconfirmed_share_class"
        return "source_mentions_class_and_series"
    if series:
        return "source_mentions_series" if series in text else "unconfirmed_series"
    return "name_mentioned_only"


def detect_events(watch:dict,current:dict,previous:dict|None=None)->list[dict]:
    kind=watch["kind"]
    if kind not in {"fund","stock"}:
        raise ValueError("Unsupported watch kind")
    if current["form"] not in (FUND_FORMS if kind=="fund" else STOCK_FORMS):
        raise ValueError("Unsupported SEC form for this watch kind")
    newtext=current["normalized_text"]
    oldtext=previous["normalized_text"] if previous else ""
    status=identity_status(watch,newtext)
    categories=FUND_DETECTORS if kind=="fund" else STOCK_DETECTORS
    results=[]
    for category in categories:
        older=relevant_slices(oldtext,category,kind)
        newer=relevant_slices(newtext,category,kind)
        if not previous:
            pairs=[("first_observed",None,s) for s in newer]
        else:
            pairs=_match_pairs(older,newer)
        for change,old,new in pairs:
            oldquote=old.quote if old else None
            newquote=new.quote if new else None
            # Evidence must be a verbatim span in this normalized document.
            if oldquote and (not previous or oldtext.find(oldquote)!=old.offset):
                raise ValueError("Old evidence source mismatch")
            if newquote and newtext.find(newquote)!=new.offset:
                raise ValueError("New evidence source mismatch")
            event_id=stable_id(kind,watch["watch_id"],current["accession"],
                               previous["accession"] if previous else None,
                               category,change,oldquote,newquote)
            extracted=_effective_date(newquote or oldquote or "")
            results.append({
                "event_id":event_id,"watch_id":watch["watch_id"],
                "kind":kind,"name":watch["name"],"cik":watch["cik"],
                "series_id":watch.get("series_id"),"class_id":watch.get("class_id"),
                "identity_status":status,"accession":current["accession"],
                "baseline_accession":previous["accession"] if previous else None,
                "form":current["form"],"filing_date":current["filed"],
                "source_url":current["source_url"],
                "baseline_url":previous["source_url"] if previous else None,
                "document_hash":current["content_hash"],
                "category":category,"change_type":change,
                "priority":"high" if category in HIGH_PRIORITY else "medium",
                "status":"needs_review" if kind=="fund" and status not in
                         {"source_mentions_class_and_series","source_mentions_series"} else "candidate",
                "effective_date":extracted,"effective_date_basis":
                        "explicit_iso_source_text" if extracted else "not_determined",
                "detected_at":utcnow(),
                "old_evidence":{"quote":oldquote,"offset":old.offset,
                                "source_url":previous["source_url"],
                                "accession":previous["accession"]} if old else None,
                "new_evidence":{"quote":newquote,"offset":new.offset,
                                "source_url":current["source_url"],
                                "accession":current["accession"]} if new else None,
                "uncertainties":[
                    "Lexical change candidate, not verified economic materiality",
                    "Identity attribution requires review" if kind=="fund"
                    else "Regulatory disclosure may not reflect current market impact",
                    "Effective date unknown" if not extracted else "Effective date from source text"
                ],
            })
            if len(results)>MAX_EVENTS_PER_DOCUMENT:
                raise ValueError("Detector event limit exceeded; filing remains incomplete, not truncated")
    return results
