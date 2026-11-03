# Stage 1, PR1: durable issuer monitoring

PR1 implements a local, deterministic 10-K Item 1A monitoring slice. Amendments, 10-Q, 8-K, fund identity/detectors, investigation, scheduling and email remain future work. Existing demo, live pair comparison, local comparison and Streamlit interfaces retain their defaults.

## Quick start

Python 3.11+, POSIX filesystem with `flock`, and a persistent local disk are required for the new monitor. SQLite on network shares and concurrent distributed workers are not supported. Install with `pip install -e '.[dev]'`.

```bash
filing-intel watchlist add --company 320193 --name Apple --db /persistent/path/state.sqlite3
filing-intel watchlist list --db /persistent/path/state.sqlite3
# Set SEC_USER_AGENT in your shell to your own name/organization and contact email.
filing-intel scan --since 2024-01-01 --db /persistent/path/state.sqlite3
filing-intel status --db /persistent/path/state.sqlite3
filing-intel results --db /persistent/path/state.sqlite3 > /private/path/results.json
filing-intel backfill --from 2020-01-01 --to 2023-12-31 --db /persistent/path/state.sqlite3
filing-intel watchlist disable --company 320193 --db /persistent/path/state.sqlite3
```

CIK input is an explicit operator assertion of issuer identity; its provenance is stored. Tickers resolve through the official SEC ticker map and are then persisted as CIKs, avoiding ticker drift. This is issuer-only configuration, without ambiguous fund/series/class mapping. `--name` must be a public issuer name. The default state path is ignored `.filing-intel/state.sqlite3`. Keep state and generated watchlist/results exports private. No contact address is stored in the database, samples or event output.

Date bounds are inclusive UTC filing dates; acceptance, report period, discovery, acquisition and detection times remain separate. First scan defaults to 400 days if `--since` is omitted. Subsequent default scans revisit the earliest scan start. Explicit scans add to the selected inventory, and revisit previously selected filings through `--to` to recover failures and re-evaluate late baselines. Backfill processes only its requested interval, plus the baseline documents required for those comparisons. Backfill never advances the scan checkpoint. Adding a watch applies the configured scan interval to that issuer.

Exit codes: 0 successful command/completed scan, 1 configuration or local command error, 2 partial/failed scan with persisted audit details. `status` and `results` work without SEC credentials or network. `results --run-id ID` shows that run's complete comparison outcomes and events, including reuse on replay. `results --include-superseded` includes historical superseded candidates. Results contain all events; no display cap or hidden top-20 filter applies. Run-specific results retain original run comparisons, with superseded status if their baselines were subsequently replaced.

## Independent technical decisions

- **Storage/migration:** stdlib SQLite, WAL, FULL synchronous commits and foreign keys. `Store` applies transactional `MIGRATION_1` on a new database and records `PRAGMA user_version=1`; unknown future schemas are rejected. Migration creates watches, accession inventory, immutable documents, versioned parses, processing attempts, comparisons, events, runs and run/entity/result links. No additional infrastructure or model calls.
- **Incremental discovery:** sweep recent submissions and every published historical shard on every run, then deduplicate accessions transactionally. Only new documents are downloaded; parses and comparisons are reused. Full metadata sweeps deliberately trade extra SEC requests for catching late arrivals older than a timestamp checkpoint. Discovery has no top-N cutoff. Inventoried metadata conflicts and malformed/unavailable shards fail explicitly. A checkpoint is a per-issuer completed-through date, never the sole exclusion filter. Unsupported forms, including 10-K/A, remain inventoried with an exclusion reason and amendment flag. They do not count as eligible 10-K parsing failures or imply supported amendment analysis.
- **Immutable evidence:** first successful raw response bytes, SHA-256, decoded response text and acquired time persist together; database triggers reject document updates/deletes. Successful parses also cannot be overwritten. Parser upgrades must change `PARSER_VERSION`, preserving prior output and attempts. Failed parses retain raw content; each replay records a fresh failure rather than pretending the section was unchanged. Correcting parser code requires a version bump before successful output is cached under a new version.
- **Baseline:** same CIK and 10-K form, strictly earlier filing date, latest earlier annual report period when known. Same-period annual duplicates are not treated as prior years; indistinguishable baseline candidates fail for review. Without current report-period metadata, filing chronology is used with an explicit lower-confidence reason. No eligible baseline is a `first_seen` outcome, with no claim of unchanged text. Required earlier documents are fetched even outside the requested interval. A failed prior document blocks the comparison.
- **Comparison adapter:** retain `compare` and legacy defaults. The monitor explicitly disables its 20-change and 350-unit limits, and checks all quotes against the declared stored baseline/current parses before persisting events. Above 1,000 text units on either side, alignment fails visibly rather than truncating; this bounds the quadratic alignment cost. Events are lexical candidates, not verified semantic changes or materiality conclusions. Effective dates remain null with `not_extracted` provenance.
- **Coordinates:** quote offsets index the entire stored whitespace-normalized document. Evidence includes accession, document/hash identity, source URL, parser version, section and start/end offsets. `locator_quality=normalized_document_offset`; `exact_original_excerpt=null` is intentional because raw HTML coordinates are unavailable. The quoted text is exact in stored normalized text, not a claim that decoded HTML contains the same contiguous substring.
- **Deduplication/lineage:** event fingerprint includes jurisdiction, issuer CIK, category, change type, exact values and annual period/date. Separate occurrence IDs include comparison lineage, both accessions and implementation versions. A late-discovered baseline creates a new comparison/occurrences and deactivates the prior comparison atomically; old candidates remain queryable as superseded. This is within-issuer annual lexical deduplication, without cross-filing semantic consolidation or amendment correction logic.
- **Recovery:** a POSIX per-database advisory lock prevents competing local scans/config writes. Each source, parse and comparison commits independently; events and their comparison commit together. OS lock release after a crash lets the next scan mark abandoned runs partial and resume inventory. Checkpoints advance only for successful issuer scans, independently of other issuers, and never move backwards. Pending processing remains selected in durable inventory. Source, fetch, parse and analysis errors are exposed through run summaries, attempts and per-filing outcomes. Analysis failure counts include target failures caused by fetch/parse; these denominators are not additive.
- **Budgets:** one synchronous SEC client, approximately two requests/second, 25-second request timeout, at most three HTTP attempts, bounded backoff, explicit 403 failure, and 20 MB document limit. No LLM/token/cost budget is consumed. Inventory sweep request count depends on published history; no silent document or event truncation occurs.

## Verification and reproducible sample

```bash
python -m pytest
filing-intel demo --format json
filing-intel compare --old examples/synthetic_before.txt --new examples/synthetic_after.txt --format json
filing-intel evaluate
python examples/monitor_smoke.py
```

The offline smoke uses the real CLI, SEC client and durable pipeline with a mocked transport and fictional source texts. It adds a watch, scans, backfills, reads status/results, and asserts equal evidence events on replay. `examples/monitor_sample.json` is its full example output: 3 candidates and idempotent replay. Its URLs illustrate SEC routing; they are **not actual SEC filings**. Run IDs/timestamps vary on rerun; event occurrence IDs are stable for unchanged fixture inputs and versions.

Measured locally on Python 3.12: 32 tests passed, including all 13 original tests. Synthetic evaluation: 5 cases, TP=3, FP=0, FN=0; these are fixture regression results, not real-world accuracy. Demo, compare and offline monitor CLI smoke commands completed successfully. Tests cover missed intervals, late baselines, duplicate accessions, unsupported amendments, missing/malformed inventory, transient fetch failures, parse failures, raw immutability, interruption/recovery, wrong/ambiguous baselines, local lock contention and more than 350 units/20 findings.

### Live SEC acceptance rehearsal passed

On 2026-11-03, the real CLI scanned Apple (CIK 0000320193) for filing dates 2025-01-01 through 2026-11-03 using the operator's contactable SEC_USER_AGENT. Identification was supplied only to the runtime process and is absent from commits and exported results.

- Discovered 2,272 accession records; 162 unsupported-form records within the requested window were explicitly excluded.
- Compared the one eligible annual filing, accession `0000320193-25-000079` (filed 2025-10-31), against `0000320193-24-000123` (filed 2024-11-01). Both official source URLs and stored SHA-256 values are in `examples/live_acceptance.json`.
- Stored 90 lexical candidates. All 131 nonempty before/after quotes resolved exactly to their stored normalized document offsets, and both raw document hashes were independently recomputed successfully.
- Repeated the scan: both runs completed, all event records were identical, document hashes were unchanged, and replay downloaded zero additional documents. Discovery metadata was still swept normally.
- The first attempt exposed legacy SEC records with empty primary-document names. The fix inventories them with an official filing-index URL; fetching one when selected or required as a baseline still fails explicitly. Two regression tests cover these cases.

This satisfies PR1's real-source discovery/comparison/storage/replay rehearsal for one issuer and one annual pair. The 90 candidates are heuristic text differences, not 90 verified economic events. Span verification establishes internal evidence traceability, not general detection accuracy or exhaustive parser quality across issuers.

Reproduce with your own SEC_USER_AGENT configured in the shell:

```bash
python examples/live_monitor_smoke.py --db /persistent/path/live-acceptance.sqlite3 --since 2025-01-01 --to 2026-11-03 --out /private/path/acceptance.json
```

The script uses the actual CLI and network transport, validates raw hashes and every nonempty event quote, and checks event/document stability and zero additional document fetches on replay. No contact identity is embedded in the script.

## Rollback and remaining work

Stop the worker, back up the SQLite database with SQLite's backup API (or after clean shutdown including any WAL sidecars), and revert the code commit. PR1 makes no changes to legacy CLI input/output defaults. There is no destructive down migration: retain the database as an audit archive; delete it only intentionally because that discards history/checkpoints. Future migrations must preserve raw documents and event lineage.

PR2 owns amendment-parent/correction semantics, additional issuer forms and expanded baseline policies. Later stages own fund identity/detectors, research tools, externally hosted persistence, scheduling/email, broad labeled public evaluation and monitoring UI. Local SQLite history must not be placed on an ephemeral GitHub Actions disk and described as durable unattended monitoring. Current parser heuristics and lexical detector remain limited; diverse real filings, source-specific encoding/layout review and production deployment validation remain required beyond this single-pair rehearsal.
