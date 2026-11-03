# Canonical event, evidence and state contracts

**Status:** target contracts for review. [PR1](PR1_MONITORING.md) ships schema-version-1 issuer lexical candidates and normalized source offsets, with nullable effective dates and immutable comparison occurrences. Investigation, digest, feedback and fund identity contracts remain planned. See `examples/monitor_sample.json` for actual serialization and `store.py` for migration 1.

## Required entities
- **WatchEntity:** `watch_id`, `jurisdiction`, `entity_type` (issuer/registrant/fund/series/class), canonical IDs and aliases, enabled categories/forms, owner, effective configuration revision.
- **FilingDocument:** immutable `doc_id`, `source_system`, `cik`, `series_id?`, `class_id?`, `form`, `accession`, `primary_document`, `source_url`, `filing_date`, `accepted_at?`, `discovered_at`, `period_end?`, `is_amendment`, `content_sha256`, `fetch_status`, `parser_version`, `parsed_status`, `baseline_doc_id?`, `baseline_reason`.
- **SourceSpan:** `span_id`, `doc_id`, `section_path`, `start_offset?`, `end_offset?`, `normalized_text`, `exact_original_excerpt`, `source_locator`, `locator_quality`. If exact document coordinates aren't possible, record that honestly.
- **ChangeEvent:** `event_id`, `entity_ids`, `category`, `subtype`, `change_type` (added/revised/removed/new_event/correction), `old_value?`, `new_value?`, `old_span_ids[]`, `new_span_ids[]`, `effective_date?`, `effective_date_basis`, `event_date?`, `status` (candidate/verified/rejected/superseded), `review_priority`, `comparison_method`, `model_version?`, `uncertainties[]`, `detected_at`, `updated_at`, `fingerprint`, `related_event_ids[]`.
- **Investigation:** `investigation_id`, `event_id`, `question`, `tool_call_trace`, `sources`, `supported_observations`, `hypotheses`, `unknowns`, `recommended_next_steps[]`, `stop_reason`, `model`, `token_cost?`, `human_review_status`.
- **Run:** `run_id`, `mode` (scheduled/on_demand/backfill), `window_start/end`, `watchlist_revision`, `status` (queued/running/completed/partial/failed), `discovered`, `processed`, `parse_failures`, `analysis_failures`, `started_at`, `finished_at`, `checkpoint`, `error_summary`.
- **Digest:** `digest_id`, `run_id`, `recipient_scope`, `window`, `content_hash`, `status` (prepared/sent/failed), `provider_message_id?`, `sent_at?`, `last_attempt_at?`.
- **ReviewLabel:** `label_id`, `event_id`, `reviewer`, `annotation_version`, exact match attributes, groundedness decision, false-positive/failure reason, created time.

## Example finding payload (illustrative only)
```json
{
  "event_id": "synthetic-evt-001",
  "entity": {"cik": "0000000000", "name": "Fictional Fund", "series_id": null, "class_id": null},
  "category": "investment_objective",
  "change_type": "revised",
  "old_value": "Growth of capital",
  "new_value": "Long-term growth of capital and income",
  "effective_date": null,
  "effective_date_basis": "not_disclosed",
  "evidence": {
    "old": {"doc_id": "synthetic-before", "quote": "Growth of capital", "source_url": "synthetic://old"},
    "new": {"doc_id": "synthetic-after", "quote": "Long-term growth of capital and income", "source_url": "synthetic://new"}
  },
  "status": "candidate",
  "review_priority": "medium",
  "uncertainties": ["Effective date not found"],
  "recommended_next_steps": ["Confirm the effective date in the prospectus supplement"]
}
```

## Invariants
1. Raw filing and original source spans are immutable; transformations are versioned. Never invent a source quote or transform a paraphrase into a quoted excerpt.
2. Evidence must resolve to the referenced document; before/after must match the declared baseline comparison.
3. Effective date is nullable, and its provenance must be explicit. Filing date, event date, effective date, and discovery date are separate fields.
4. Event fingerprint must support repeat runs and cross-filing references without collapsing distinct fund share classes. Preserve duplicate and supersession relationships rather than erasing data.
5. An event can be `candidate` without being verified. Prioritization is an analyst-workflow aid, not probability of financial materiality.
6. Run failures and partial results remain first-class data, not silently treated as empty findings.
7. Cross-system and multi-jurisdiction identity relations require source-backed aliases and effective periods.
8. Schema must be migration-safe and API/export serialization stable; fixtures and typed validation required before implementation.

## Proposed fingerprint
Stable combination of jurisdiction, canonical affected entity/fund/class, category/subtype, normalized event attributes/effective date and source event lineage. Do **not** fingerprint solely by wording, ticker or accession; persist a separate detection occurrence ID for each filing reference.
