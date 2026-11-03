# Regulatory filing coverage matrix

**Status:** proposed. The **only currently implemented live parser** is US public-company 10-K Item 1A. Other lines are target/experimental, not shipped support. Scope is watched entities, not the entirety of EDGAR.

| Phase | Geography/entity | Source & form family | Detection focus | Baseline/identity considerations | State |
|---|---|---|---|---|---|
| Existing | US issuer | SEC 10-K Item 1A | Risk wording adds/revisions/removals | Two latest 10-Ks by CIK | Implemented prototype |
| P1 | US issuer | 10-K, 10-K/A | Risks, business, liquidity, governance and financial disclosure changes | Same section prior annual, amendments against original | Proposed |
| P1 | US issuer | 10-Q, 10-Q/A | Risk, operations, liquidity, key facts | Comparable prior quarter/annual section as appropriate, not blindly preceding form | Proposed |
| P1 | US issuer | 8-K, 8-K/A and exhibits as relevant | Discrete events, management, financing, results, material agreements | Event-first classification; amendment chain, duplicate press releases | Proposed |
| P1/P2 | US registered investment company | N-1A, 485APOS/485BPOS, 497/497K and related applicable prospectus supplements | Fees, objectives, benchmarks, managers, share-class updates, closures/launches | CIK + series/class IDs, fund/registrant relationships, prospectus history | Proposed, validate forms |
| P2 | US registered investment company | N-CSR, N-CSRS, N-PORT, N-CEN and related forms where relevant | Financial/shareholder reports, holdings or operational changes | Structured sections, reporting dates, amendments, disclosure timing | Proposed, validate form relevance |
| P3 | UK/UCITS | Official UK regulator and fund/manager disclosure sources | Fund objectives, fees, managers, benchmarks, closures | ISIN/share-class/fund identity, publication and license rules | Research only |
| P3 | Singapore | Official MAS/public scheme disclosure sources | Prospectus and fund status changes | Fund identifiers and access/license rules | Research only |

## Canonical identity
`source_system`, `jurisdiction`, `registrant_cik`, `series_id`, `class_id`, `ticker`, `isin`, `fund_name`, `registrant_name`, aliases, validity dates and confidence/provenance. Not every identifier is present on every SEC form. Do not equate fund/share class with registrant. Ambiguous mappings require review and must not be silently resolved by an LLM.

## Source ingestion rules
- Discover from official submission feeds and filing archives; version by accession and document hash, not ticker alone. Store `filing_date`, `accepted_at` (if available), `discovered_at`, `period_end`, `form`, `is_amendment`, `parent_accession` (if determinable).
- Filter by watchlist and explicitly supported forms; retain an inventory of excluded forms and source failures to measure coverage gaps.
- Select baseline per event family: prior annual vs annual; 10-Q year-over-year/quarter-over-quarter as justified; 8-K event-first vs related disclosures; amended filing vs original *and* latest valid baseline; prospectus changes vs prior same fund and class.
- Parse source-specific HTML, text, XBRL and tables independently. Preserve source spans and table cells; fail closed when necessary sections are not identifiable.
- For fee schedules, capture fee type, unit, value and effective date; for managers/benchmarks capture full names and identifiers; for closure/launch capture fund/class lifecycle and dates. Never represent an absent date as today's date.
- Avoid collapsing separate share classes or investment products; keep an explicit many-to-many issuer/registrant/fund/class mapping.

## Coverage expansion gates
Before marking a form supported, provide: (1) official source documentation; (2) at least 10 diverse public examples including amendments/edge cases where available; (3) baseline-selection test; (4) parser fail-closed tests; (5) category extraction and quote-grounding tests; (6) documented known blind spots; (7) reproducible integration smoke test.

## Known uncertainty
Form applicability and filing terminology vary. The specific fund form taxonomy above is a prioritized research inventory, not a guarantee that any individual form contains every listed change category. Regulator and market datasets outside SEC require separate terms/quality verification.

## Primary references
- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC developer resources: https://www.sec.gov/about/developer-resources
- SEC EDGAR company and fund search: https://www.sec.gov/edgar/search/