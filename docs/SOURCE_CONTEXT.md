# Source context and confidence register

This document avoids confusing a prior employer-system reference with the independent public portfolio implementation.

## A. Verified in this repository (code inspected, November 2026)
- SEC client (`sec.py`) resolves ticker/CIK, fetches two 10-K submissions and parses Item 1A using heuristics. Contactable User-Agent, modest throttling and bounded retries are present.
- Detector (`detect.py`) segments and aligns text by token overlap/sequence similarity; categorizes added/revised/removed candidates and keyword attention. It caps default returned changes at 20 and limits long sections to 350 segments, with warnings.
- `ai.py` optionally adds short model interpretations to at most five findings, requiring returned evidence substrings to match supplied text. It does not provide tools or independent investigation.
- CLI offers synthetic demo, live pairwise analysis, local comparison and a five-scenario synthetic evaluator. The Streamlit UI and static fictional GitHub Pages walkthrough are separate experiences.
- Stage 1, PR1 adds a manual local 10-K monitor and immutable SQLite event/document history, with deterministic mocked recovery tests. See [actual scope and validation](PR1_MONITORING.md); real-source discovery/comparison/storage/replay passed on one Apple annual pair. No daily email, multi-form fund detector or autonomous research loop exists yet.

## B. Product-owner design priorities (high-level, independently specified)
The owner requested an expanded fund research workflow informed by prior professional experience. The following are product *requirements and design inspirations*, not public descriptions of employer systems or their source code:
- Both on-demand requests and scheduled batch monitoring should share a common processing pipeline.
- Use deterministic retrieval/cleaning; specialized category detection; and deterministic verification, historical backfill and deduplication.
- Cover portfolio-manager, benchmark, fund closure, fee, investment objective and product launch changes, with future jurisdiction adapters for UK/UCITS and Singapore.
- Evaluate strict event accuracy (entity, category, effective date), relaxed accuracy, groundedness and coverage using labeled, legally shareable data.
- Design explicitly for lookback gaps, request throttling, entity-name variations, missing forms and limits of model-based judging.

## C. New requirements expressed by the product owner
- Detect *relevant* new disclosure changes across watched entities, summarize them daily, and recommend concrete further investigation steps.
- Build an autonomous, tool-using research workflow with traceable source evidence and explicit limitations. The user has Codex for implementation.

## D. Design proposals, not confirmed original implementation
- Persistent relational store, issue-identity resolution, structured event schema, fixed-cost investigator budget, daily digest email, tracked watchlist and GitHub Actions orchestration.
- Use the OpenAI Agents SDK if it meaningfully simplifies bounded tool calls/tracing. The exact orchestration framework is replaceable.
- First ship US registered funds and public-company SEC coverage; design connectors for UK/Singapore, but don't claim supported before sources, licensing, and test fixtures are validated.

## E. Unknowns requiring explicit review
- Exact production data-source mapping and comprehensive category taxonomy in the prior system (recordings show only portions).
- Rights to any historical source material: assume no public redistribution rights; recreate independently.
- User persona priorities, initial watchlist, digest recipients, time zone, hosting, cloud budget, acceptable timeliness, source coverage and threshold preferences.
- Actual legal and licensing access for UK/Singapore data and amendments to fund disclosure source-selection rules.

## Evidence and provenance policy
These documents are independently authored product plans, not reproductions of employer work. Public deliverables must not include internal URLs, screenshots, names, infrastructure account identifiers or private tickets. Never host source recordings in the public portfolio.
