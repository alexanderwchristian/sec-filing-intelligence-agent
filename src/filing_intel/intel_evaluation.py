"""Strict/relaxed event F1 and independent source-grounding verification."""
from __future__ import annotations

from .intel_store import IntelStore


def _key(event: dict, strict: bool) -> tuple:
    fields = ("kind", "cik", "series_id", "class_id", "category", "change_type")
    core = tuple(str(event.get(k) or "") for k in fields)
    return core + (str(event.get("effective_date") or ""),) if strict else core


def _scores(gold: list[dict], predictions: list[dict], strict: bool) -> dict:
    used = set()
    tp = 0
    for target in gold:
        for index, predicted in enumerate(predictions):
            if index not in used and _key(target, strict) == _key(predicted, strict):
                tp += 1
                used.add(index)
                break
    fp = len(predictions) - tp
    fn = len(gold) - tp
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0}


def evaluate_labeled(gold: list[dict], predictions: list[dict]) -> dict:
    if not gold:
        return {"status": "not_measured",
                "reason": "No manually labeled public SEC ground truth provided"}
    return {"status": "measured_on_supplied_labels",
            "gold_count": len(gold), "prediction_count": len(predictions),
            "strict": _scores(gold, predictions, True),
            "relaxed": _scores(gold, predictions, False),
            "warning": "Validate complete public labels, entity holdouts and negative examples"}


def verify_grounding(store: IntelStore, events: list[dict]) -> dict:
    checked = 0
    verified = 0
    failures = []
    for event in events:
        for label, accession in (("old_evidence", event.get("baseline_accession")),
                                 ("new_evidence", event.get("accession"))):
            ev = event.get(label)
            if not ev:
                continue
            checked += 1
            document = store.filing(event["watch_id"], accession) if accession else None
            quote = ev.get("quote", "")
            offset = ev.get("offset", -1)
            if (document and isinstance(offset, int) and offset >= 0 and quote
                    and document["normalized_text"][offset:offset+len(quote)] == quote
                    and document["source_url"] == ev.get("source_url")):
                verified += 1
            else:
                failures.append({"event_id": event["event_id"], "side": label})
    return {"checked": checked, "verified": verified,
            "groundedness": verified/checked if checked else None,
            "failures": failures}
