# Product requirements: SEC Filing Intelligence Agent

**Status:** proposed v2 specification; **implementation:** pairwise comparison plus [Stage 1, PR1 local durable 10-K monitoring](PR1_MONITORING.md). Broader coverage, unattended operation, investigation and delivery remain planned.

## Product promise
For an analyst's defined watchlist, discover new relevant regulatory disclosures, detect and normalize changes, investigate likely implications using cited public sources, and deliver a trustworthy daily research briefing. Primary job: reduce missed changes and analyst review time without replacing research judgment.

## Users and jobs
1. **Fund research analyst:** track fee, investment objective, portfolio-manager, benchmark, fund status and product changes; find effective dates and affected share classes/series.
2. **Equity / credit analyst:** surface new issuer risk, results, governance, liquidity, legal and material event disclosures; compare with prior periods and trace primary documents.
3. **Research team lead:** set watchlist and relevance policies; review precision, false positives, coverage and operational completeness.

## User journeys and acceptance
**Daily monitoring:** analyst configures watchlist (CIK, ticker, and fund series/class IDs where available); ingestion discovers all relevant new filings since durable checkpoint, including amended filings; baseline comparisons and category detectors produce candidates; agent investigates highest-priority candidates; digest contains summary, links, uncertainties and recommended follow-ups. A successful zero-change run explicitly says 'No qualifying changes detected' and shows coverage; a partial or failed run must never say that.

**On-demand analysis:** user asks for a named issuer/fund, filing, event or lookback period; same retrieval, detection and event contracts run with an explicit request context. Re-running the same query on unchanged sources must be reproducible, not create duplicate events.

**Research follow-up:** user selects a candidate and asks for cause/context. Agent fetches earlier filings and other approved public sources within bounded steps; produces a question, sourced finding, unresolved evidence gaps, and an analyst next step. It must stop and say 'insufficient evidence' when appropriate.

**Human review:** analyst can mark confirmed change, not material, duplicate, false positive, or needs investigation. Decisions feed an evaluation dataset without overwriting original evidence or model output.

## Functional requirements (prioritized)
| ID | Priority | Requirement | Acceptance |
|---|---|---|---|
| FR-01 | P0 | Configurable watchlist and stable identity mapping | Ticker/CIK and series/class identity resolve with provenance; unknown or ambiguous entities block alerting pending review |
| FR-02 | P0 | Incremental new-filing discovery | Discover late-arriving and amended accessions, backfill after missed runs, record discovery vs filing timestamps |
| FR-03 | P0 | Durable raw/normalized versions | Content hash, accession, source URL, parser version, acquired time, prior baseline and document text preserved |
| FR-04 | P0 | Category-specific change extraction | Support changes, unchanged, removal, effective date, ambiguity and document-level comparison; no silent truncation |
| FR-05 | P0 | Evidence trace | Verbatim old/new span with accession, section, source URL and confidence/status; no unsupported factual assertions |
| FR-06 | P0 | Daily digest with explicit completeness | One report per interval; sections: new, changed, follow-up, no changes and coverage failures; no duplicate sends |
| FR-07 | P0 | Run audit/recovery | Durable checkpoints, retry/backfill, source outages represented explicitly |
| FR-08 | P1 | Bounded tool-using investigation | Tool calls and citations captured; next-step suggestions are hypotheses, not investment actions |
| FR-09 | P1 | Feedback and evaluation | Reviewer labels, strict/relaxed event scores, groundedness, coverage, error taxonomy and run cost |
| FR-10 | P1 | Interactive UI | Watchlist management, report review, cited before/after diffs, run status and manual rerun |
| FR-11 | P2 | Multi-jurisdiction connector support | UK/UCITS/Singapore data only after sources and permissions validated |

## Digest contract
Header includes reporting window, timezone, monitored entities, complete/partial/failed status, count of discovered/processed/failed filings, and a run ID. Each finding includes issuer/fund, form/date/accession, event type, change category, effective date (known/unknown), before/after evidence, concise summary, why review, confidence/uncertainty, and 1-3 precise questions/actions for further research. Separate 'newly detected' from 'previously detected but updated/corrected'. Include direct links to primary documents. No recommendations to buy/sell or claims of verified investment materiality.

## Detection and prioritization
- Compare appropriate prior document/period, including amended-vs-original and annual/quarterly comparables; preserve baseline selection rationale.
- Distinguish lexical changes (wording), factual changes (values/entities/dates), and semantic changes (substantive meaning); do not assume lexical differences imply impact.
- Classify by category, affected entity, magnitude (when computable), novelty, and completeness; use a *review priority*, not an unsupported materiality probability.
- Preserve every candidate in storage; digest and UI can paginate or rank, with counts clearly stating what's hidden.

## Quality and safety
- **Factual correctness:** every source claim must be supported by the cited excerpt and document metadata. Unsupported commentary becomes a flagged hypothesis or is omitted.
- **Coverage:** do not misstate 'all SEC filings'. Coverage is explicitly limited to watched entities and supported forms/documents.
- **Privacy/security:** public filings only; secrets never committed; uploaded user watchlists and email addresses kept out of public repo/logs.
- **Accessibility:** HTML digest readable as plain text; CLI and Markdown usable without web UI.
- **Recoverability:** missed schedule, partial failures, repeats and amended filings handled without lost changes or duplicate notifications.

## Explicit out of scope for initial release
Automated trading; price targets; personalized investment advice; unrestricted web browsing; full-text search across every global regulator; fully automated legal conclusions; production SLAs before reliable operation is measured.

## Review decisions
Select initial watchlist (recommend 5-10 entities spanning fund and issuer forms), timezone/digest hour, delivery transport, deployment environment, research budget and first supported form subset before execution. See `FILING_COVERAGE.md` for phased scope, not aspirational promises.
