"""Optional LLM interpretation, deliberately fenced by exact document evidence.

The deterministic detector works without an LLM or API key. LLM output is
presented as interpretation, NEVER as extracted evidence or a verified fact.
"""

from __future__ import annotations

import json
import os

from .models import Change, Report


def interpret_changes(report: Report, *, api_key: str | None = None,
                      model: str | None = None, max_items: int = 5) -> None:
    """Annotate a bounded number of findings via OpenAI Responses API.

    Mutates report only after exact evidence validation; errors are made visible.
    """
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("Set OPENAI_API_KEY to enable optional LLM interpretation")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install AI support using: pip install -e '.[ai]'") from exc

    client = OpenAI(api_key=key, timeout=25.0, max_retries=1)
    model = model or os.getenv("OPENAI_MODEL", "gpt-5-mini")
    for change in report.changes[:max_items]:
        prompt = {
            "change_type": change.change_type,
            "old_excerpt": change.old_quote[:900],
            "new_excerpt": change.new_quote[:900],
            "old_filing": report.old_date,
            "new_filing": report.new_date,
        }
        try:
            response = client.responses.create(
                model=model,
                instructions=(
                    "You are a financial disclosure analyst. Describe the text change "
                    "in at most 2 sentences. Do not speculate on actual financial impact, "
                    "severity or investment decisions. Output a JSON object with keys "
                    "interpretation, old_evidence, new_evidence. Evidence must be an "
                    "exact verbatim substring of the matching input excerpt, or empty "
                    "when absent. Avoid anything not supported by input excerpts."
                ),
                input=json.dumps(prompt),
            )
            body = response.output_text.strip()
            if body.startswith("```"):
                body = body.strip("`").removeprefix("json").strip()
            data = json.loads(body)
            old_evidence = str(data.get("old_evidence", ""))
            new_evidence = str(data.get("new_evidence", ""))
            interpretation = str(data.get("interpretation", "")).strip()
            if (old_evidence and old_evidence not in change.old_quote) or (
                    new_evidence and new_evidence not in change.new_quote):
                report.warnings.append("Discarded an AI annotation with an unverified evidence quote")
                continue
            if not (old_evidence or new_evidence) or not interpretation:
                report.warnings.append("Discarded an AI annotation without verifiable evidence")
                continue
            change.ai_interpretation = interpretation[:500]
            change.ai_evidence_verified = True
        except Exception as exc:
            report.warnings.append(f"AI interpretation unavailable: {type(exc).__name__}")
            break
