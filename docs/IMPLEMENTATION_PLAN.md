# Implementation plan: reviewable vertical slices

**Status:** Stage 1 issuer 10-K foundation merged; v2 local implementation now includes both US SEC fund/stock candidate paths, dashboard, bounded research, daily digest, SMTP sender and scheduler. Tests are offline; live two-track SEC acceptance, labeled accuracy and deployed delivery remain incomplete. Do not call this production-ready. [Implementation, validation, scope and rollback](PR1_MONITORING.md). Later PRs/stages remain planned. Existing CLI and Streamlit comparison workflows remain functional.

## Stage 0: baseline and specification signoff
- Validate repository vs README; make CI and `.gitignore` actually present in GitHub (they were missing from the inspected remote despite existing in an earlier local package).
- Review coverage and event schema with owner. Pick 5-10 public watchlist examples including fund registrant/series/class and issuer, and source timelines. Choose timezone, email provider and durable database target.
- Run current tests and manual SEC smoke test (with real SEC_USER_AGENT) and record results without calling a static demo a live agent.
**Gate:** approved docs, current functionality evidenced, documented constraints and sample source inventory.

## Stage 1: one end-to-end durable monitoring slice
- Add migrations and models for watchlist, accession inventory, immutable documents, parser results, checkpoints, run and events.
- Extend SEC discovery to incremental monitored-entity filing inventory with historical backfill and amendment detection. Start with 10-K and 10-K/A, then 10-Q and 8-K. No silent truncation; explicit unsupported handling.
- Add immutable raw storage and repeatable baseline selector; preserve existing `compare` function behind an adapter.
- CLI: `filing-intel watchlist`, `scan --since`, `backfill --from --to`, `status` (names tentative). Produce evidence-linked event JSON.
- Unit tests: missed run, duplicate accession, amendment, parser failure, >20 findings, wrong baseline, idempotent replay.
**Gate:** real public filing discovered, compared, stored, and replayed without duplicate events; all failures visible.

## Stage 2: both filing tracks and specialized detector fanout
- Make the two SEC tracks explicit: public-company 10-K/10-Q/8-K (plus amendments) and mutual-fund/ETF prospectuses. Resolve fund registrant to series/class identities; validate fees, objective, portfolio manager, benchmark, lifecycle schemas with public prospectuses.
- Add form/section detectors one at a time, each with fixtures, eligibility rules, clear before/after/effective date, and entity resolution.
- Canonicalization/dedup and category-specific ambiguity handling, preserving every candidate and source.
**Gate:** demonstrate actual detection on BOTH an SEC issuer filing and a fund prospectus, at least two distinct fund categories, a share-class distinction, and amendment lineage. The same persisted event feed powers an initial interactive dashboard.

## Stage 3: research agent, on-demand path and operational UI
- Add typed research tools over persisted public filings and events. Implement one agent with tool limits/stop conditions and model-independent quote validation.
- Produce cited context, uncertainty, hypotheses and 1-3 concrete investigation questions/actions; no unsolicited trade instructions.
- Use shared pipeline for on-demand lookups and scheduled requests. Capture tool trace, budget and errors. Extend Streamlit into a usable combined fund/stock watchlist, findings, investigations and monitoring health dashboard.
**Gate:** an analyst can inspect real fund AND stock findings, source evidence and next steps in the live UI. Integration fixtures demonstrate useful investigation, exact citations, successful abstention, prompt-injection resistance and budget exhaustion fallback.

## Stage 4: combined daily digest and unattended operation
- Add report assembler, configurable schedule, email service with send ledger, run completeness indicators, durable checkpoints and recovery.
- GitHub Actions scheduler or managed job only as trigger, durable database external. Provide incident alert and manual re-run.
**Gate:** 3 consecutive reproducible scheduled runs (in controlled testing), simulated skipped day and email failure without duplicated alerts; public demo transparently distinguishes live and fictional modes.

## Stage 5: robust evaluation and product polish
- Curate labeled public datasets with deliberate negative cases, multiple forms, dates and identity ambiguities.
- Measure strict/relaxed event F1, groundedness, completeness, latency, model cost; use error analysis to improve detectors.
- Update UI for watchlist status, run completeness, exact evidence, feedback, pagination and downloadable daily reports.
**Gate:** reproducible benchmark with provenance, limitations and measured values; a live watchlist run and sample digest demo (not conflated with synthetic static walkthrough).

## Release sequencing / developer workflow
PR1: foundation + state + incremental 10-K scan. PR2: 10-Q/8-K, amendments and baselines. PR3: first fund prospectus detector and identity. PR4: investigation agent. PR5: scheduler/email and replay. PR6: evaluation/UX. Each PR includes migration, tests, sample output, updated limitation claims and a rollback note.

## Design decisions to resolve before coding
1. First fund and stock watchlist examples. Both tracks are required for the end-to-end MVP; initial detector breadth can be phased within each track.
2. Postgres/cloud deployment vs local SQLite-only prototype (daily unattended delivery requires durable hosting).
3. Digest timezone, hour, recipient channel, weekends and no-change email policy.
4. Allowed public research sources beyond EDGAR, token/cost cap and number of events to investigate per run.
5. Required evaluation thresholds once public gold labels exist.

## Portfolio narrative
Demonstrate: input watchlist -> newly discovered public filing -> diff and specialized event -> primary-source evidence -> agent's bounded investigation -> explicit uncertainties and next research step -> daily digest -> labeled evaluation. State clearly which portions are live, which are synthetic, and which are upcoming.
