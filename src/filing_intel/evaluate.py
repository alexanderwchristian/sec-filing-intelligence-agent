"""Tiny transparent regression harness, not a production accuracy benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from .detect import compare
from .models import Filing


def evaluate(fixtures: str | Path) -> dict:
    data = json.loads(Path(fixtures).read_text(encoding="utf-8"))
    tp = fp = fn = 0
    details = []
    for case in data["cases"]:
        old = Filing("Synthetic issuer", "10-K", "2024-01-01", "synthetic://before", case["old"])
        new = Filing("Synthetic issuer", "10-K", "2025-01-01", "synthetic://after", case["new"])
        report = compare(old, new, max_changes=1000)
        findings = list(report.changes)
        used = set()
        case_tp = 0
        for expected in case["expected"]:
            quote_part = expected["contains"].lower()
            found = None
            for pos, finding in enumerate(findings):
                evidence = (finding.new_quote or finding.old_quote).lower()
                if (pos not in used and finding.change_type == expected["type"]
                        and quote_part in evidence):
                    found = pos
                    break
            if found is not None:
                used.add(found)
                case_tp += 1
        case_fp = len(findings) - len(used)
        case_fn = len(case["expected"]) - case_tp
        tp += case_tp
        fp += case_fp
        fn += case_fn
        details.append({"id": case["id"], "tp": case_tp, "fp": case_fp,
                        "fn": case_fn, "predicted": len(findings),
                        "expected": len(case["expected"])})
    precision = tp / (tp + fp) if tp + fp else 1.0 if fn == 0 else 0.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"cases": len(data["cases"]), "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3), "details": details,
            "warning": "Small synthetic fixture regression checks only; not an estimate of real-world accuracy"}
