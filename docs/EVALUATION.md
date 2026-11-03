# Evaluation plan and release gates

**Status:** planned v2 evaluation. The existing `examples/evaluation_cases.json` includes 5 synthetic detector regressions, not a real-world accuracy estimate.

[PR1 verification](PR1_MONITORING.md) records 30 passing deterministic tests and an offline end-to-end CLI replay with fictional sources. This verifies durability/failure invariants; it does not satisfy the real-public-filing gate or measure general event accuracy.

## Evaluation units
1. **Filing discovery:** true new/eligible accessions within the watched universe and interval; amendment capture, timeliness, duplicate rate and missed-window recovery.
2. **Parsing/identity:** correct fund, share-class, issuer, section and original source span; count failures, ambiguous identities and wrong baselines.
3. **Event detection:** category, event type, affected entity, old/new values and effective date. Align predictions and labels one-to-one per distinct event.
4. **Research grounding:** each factual claim supported by cited primary-source excerpt, correct accession and date. Missing source, unsupported extrapolation and inaccurate effective dates are failures.
5. **Digest quality:** complete event inclusion, prioritization usefulness, actionable next steps, duplicate suppression, and honest reporting of failures.

## Strict and relaxed F1
**Strict match:** canonical affected entity/share class + category/subtype + event type + substantive old/new change + effective date when available in gold labels; compare dates exactly or under an explicitly documented permitted tolerance. `unknown` is not a match to a labeled known date.

**Relaxed match:** correct entity, category and change meaning/type; do not require effective date, but still score date extraction separately. Both are scored by one-to-one matching with TP/FP/FN and micro/macro P/R/F1. Label ambiguity and adjudication rules are written before scoring. Define cross-filing duplicate counting and partial event matches clearly.

## Groundedness and coverage
- **Groundedness:** proportion of factual event attributes, excerpts, summaries and research claims that independently map to source evidence; unsupported attributes counted and reported. Use deterministic quote checks for exact evidence, plus human adjudication for paraphrases and research conclusions. An LLM judge may assist but is not a sole ground-truth source.
- **Coverage:** discovered eligible filings / expected eligible filings; successfully parsed / discovered; events recovered / labeled events; supported forms / watchlist-targeted forms. Publish denominators and exclusions, not a single misleading percent.
- **Operational:** time from SEC publication to detection, median/p95 run time, late/missed filing recovery, error rate by stage, requests/filing, token/cost per processed document and per verified event, daily-send success.

## Dataset design
Build a legally shareable public-SEC dataset of at least 30 paired filings initially across 10+ issuers/funds and multiple form families, then grow it before strong performance claims. Include non-events, amendments, changed entity names, effective-date ambiguity, fee tables, structural reordering, paraphrases, ticker changes, near-duplicates, missing documents, wrong lookback and sparse filings. Human reviewers label exact quote offsets, source accession, entity, event and effective date; second-review a subset and track disagreement. Split by entity and filing period, not randomly by paragraphs, to prevent leakage.

## Adversarial and negative tests
- Old disclosure repeated in a new layout: no false semantic change.
- Same fee changed for two distinct classes: two distinct affected entities.
- Manager rename vs new manager: distinct classification or explicit ambiguity.
- Amended filing corrects an event: corrected/superseded rather than duplicate or silent overwrite.
- A retrieved page contains adversarial instructions: no tool execution or instruction following.
- Filing missing/malformed/SEC 429: run partial, not 'no changes'.
- More than 20 changes: all persisted even if digest displays only ranked subset.
- Missing effective date: nullable with reason, not fabricated.
- Batch workload throttling scenario: bounded concurrency and retry budget (no actual private infrastructure required).

## Reporting protocol
For each version, publish dataset revision, pipeline/model versions, sample size, class distribution, strict and relaxed P/R/F1, groundedness failure counts, discovery/parse coverage, latency percentiles, token/cost sample, failed/abstained counts, representative failure examples, and confidence intervals when sample size permits. Keep synthetic-only results explicitly labeled as regression checks.

## Initial acceptance gates (targets, not achieved metrics)
- 100% of displayed verbatim quotes resolve to stored cited source spans in test fixtures.
- Zero duplicate email sends on rerun/retry in deterministic integration tests.
- Every partial run exposes failure counts and never emits a definitive 'no change' conclusion.
- All labeled supported-form documents in integration fixture inventory are accounted for as processed, intentionally excluded or failed.
- Establish baseline precision/recall on the public labeled set before setting numeric performance gates. Do not invent an F1 target as an achieved result.
