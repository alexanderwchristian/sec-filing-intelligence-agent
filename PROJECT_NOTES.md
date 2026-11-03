> **Historical MVP decision log.** The v2 requirements, architecture, schema and implementation plan live in [`docs/PRODUCT_REQUIREMENTS.md`](docs/PRODUCT_REQUIREMENTS.md) and the other documents linked from the README. This file describes only the original 10-K Item 1A prototype.

# Product decision log

## Who is it for?
Financial research analysts who compare annual 10-K risk-factor language across reporting periods.

## First problem to solve
Identify candidate disclosure wording changes and make source verification faster without implying every wording change is economically material.

## Why the initial scope is narrow
Form 10-K Item 1A is a coherent, repeatable starting point. Adding prospectus fee tables, portfolio managers, and other filing types before measuring baseline quality would make evaluation harder.

## Primary workflow
Select issuer (ticker or CIK) -> retrieve two 10-Ks -> extract Item 1A -> align passages -> return verbatim before-and-after evidence -> human review.

## MVP success criteria
- Every evidence quote is an exact substring of its source text.
- No live report if section extraction fails.
- UI exposes the original document URL for every candidate.
- Evaluation distinguishes exact synthetic regression checks from real-world accuracy.
- API key is not needed to run deterministic detection.

## Planned evaluation
Create a human-labeled set of public SEC filing pairs across industries. Report event-level precision/recall, disagreement patterns, segmentation failure rate, and median review time. Hold out issuers and years before making performance claims.

## Tradeoffs
- Deterministic alignment is easier to audit but less robust to paraphrases.
- LLM commentary is optional to avoid mixing model interpretation with sourced facts.
- The prototype has no scheduler, alerting, persistent storage, or authentication.
- Keyword priority labels are a triage tool rather than an assessment of materiality.