# US SEC fund and stock filing coverage

**Product scope:** US SEC EDGAR filings for (1) registered investment funds, including mutual funds and ETFs, and (2) public companies and their publicly traded securities. **Do not implement UK, UCITS, Singapore, non-US regulators, unrelated general news, or a global regulatory crawler.** Scope is a user-configured watchlist, not every EDGAR accession.

**Current reality:** Only 10-K Item 1A issuer comparison and its local durable monitoring are implemented. Everything below marked target is not working until tested with public filings. The existing static GitHub Pages demo is fictional, not a live monitor.

## Stock / public-company filings

| Forms / source family | What to detect | Baseline / treatment | Priority |
|---|---|---|---|
| 10-K, 10-K/A | Financials, annual results, risks, strategy, business changes, liquidity, accounting, controls | Prior comparable annual and amendment-to-original | P0 target; Item 1A 10-K already partially implemented |
| 10-Q, 10-Q/A | Quarterly results, risks, liquidity, financial metrics, revisions | Comparable quarter/year and amendment lineage | P0 target |
| 8-K, 8-K/A, relevant exhibits | Earnings, material agreements, management changes, acquisitions, financings, guidance when disclosed | Event-first, reconcile duplicate exhibits and amended disclosure | P0 target |
| DEF 14A and related proxy statements | Directors, compensation, governance, shareholder proposals | Prior comparable proxy, named entity matching | P1 target |
| SC 13D/13G and amendments; Forms 3/4/5 | Ownership changes and insider transactions | Stakeholder/security identity, amendments and repeated transactions | P1 target |
| S-1/S-3, 424B and related securities offerings | New offerings, dilution, securities terms | Offering terms and amendments, not annual-report comparison | P1 target |

A form is supported only when its parser, applicable sections, category detectors, and baseline policy pass documented public-data tests. Do not count excluded or unparsed forms as no changes.

## Fund filings: mutual funds and ETFs

| Forms / source family | What to detect | Baseline / treatment | Priority |
|---|---|---|---|
| N-1A, 485APOS/485BPOS, 497/497K and applicable supplements | Portfolio managers, benchmarks, objectives, strategies, management fees, expense ratios, waivers, new classes, closures/launches | Same registrant **and** correct fund series/class, previous applicable prospectus and amendment/supplement chronology | P0 target |
| N-CSR, N-CSRS and applicable shareholder reports | Fund performance, material management/strategy disclosures, shareholder-report changes | Same fund/period, preserve reporting and filing dates | P1 target |
| N-PORT, N-CEN where relevant and accessible | Holdings/exposure and fund operational data where the form supports it | Structured period comparisons and data quality checks | P1 target |
| N-14 and relevant merger/liquidation supplements | Fund mergers, reorganizations, wind-down and class impact | Lifecycle/event-specific baseline | P1 target |

Some ETF structures use different filing forms; the discovery layer must check the legal structure before assuming an N-1A prospectus applies. Filing categories and exact applicability are subject to official SEC verification before declaring them supported.

## Two entity tracks, one product

- **Stock identity:** issuer CIK, ticker history, securities/classes where relevant, registrant and filing dates.
- **Fund identity:** registrant CIK, SEC series ID, class ID, fund name, ticker/ISIN if supported, aliases and effective identity periods.
- Never attribute a registrant-level paragraph to a specific fund or share class without source-backed identity resolution. Ambiguity means needs-review, not a verified alert.
- Both tracks share watchlist, discovery checkpoints, raw/normalized evidence store, event feed, investigation tools, Streamlit dashboard, review status and daily email digest.
- Each track has separate **form-specific** parsing, baselines, detectors, and evaluation labels.

## Detection requirements

**Funds:** portfolio-manager changes; benchmark/index changes; investment objective and strategy changes; fees, expenses and waivers; launch, closure, merger, reorganization; share-class implications.

**Stocks:** financial and operating changes; material risk and controls; management/governance; liquidity and financing; guidance and earnings disclosures; significant agreements, acquisitions, ownership/capital structure where supported.

Capture added, revised, removed, corrected and first-observed events. Every claim needs an accession and precise supported quote, including prior and current evidence when applicable. Preserve effective date separately from filing date. Never silently truncate findings, promote lexical text changes into economic conclusions, or fabricate materiality.

## MVP acceptance (both tracks mandatory)

1. Add/remove at least one fund and one public company through the **interactive UI**.
2. Discover and persist real official SEC filings for both, including at least one relevant supported fund prospectus and one public-company filing.
3. Emit structured, non-duplicate, source-linked candidate changes for both, with explicit entity identity and complete/partial run status.
4. Generate a cited AI-assisted summary with uncertainties and concrete, bounded follow-up investigation suggestions; no model-generated source evidence.
5. Render both in the same **live dashboard**, with filters and evidence inspection.
6. Produce a reproducible **daily briefing** for the combined watchlist, with failure/replay/no-change semantics and durable delivery ledger.
7. Test a missed run, amended filing, false positive, ambiguous fund share class, evidence mismatch, and repeated delivery before calling it operational.

Until these tests pass, README/UI must clearly label the specific capability as planned or experimental.

## Sources and compliance

Official SEC EDGAR submissions and filing archives; documented rate limits, contactable SEC user agent and backoff. No proprietary employer source code/prompts/data. No trading automation. Exclude non-US regulator sources from the roadmap unless the owner explicitly reopens that scope.

Official references:
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://www.sec.gov/about/developer-resources
- https://www.sec.gov/edgar/search/
