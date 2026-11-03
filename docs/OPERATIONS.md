# Daily monitoring and operations

**Status:** local daily scheduler and SMTP sender implemented in the v2 feature branch, not deployed. Owner must configure persistent host, SEC contact identity, email provider and monitoring. SMTP send ledger is fail-closed on uncertain delivery and requires manual reconciliation. See DEPLOYMENT.md.

## Execution modes
- **Scheduled:** e.g. each US business day with configurable UTC/timezone scheduling. Use a lookback sweep greater than schedule interval plus durable checkpoints, rather than trusting exact scheduler execution time.
- **Manual/backfill:** reprocess a date interval, entity or accession deterministically. A backfill must not resend unchanged previously delivered items.
- **On-demand:** same discovery/parse/detect/investigate functions, scoped to user query; outputs use the same event schema.

## Recommended small-scale deployment
GitHub Actions can trigger on a schedule or manual dispatch. Run the Python worker against externally persisted database state (Postgres or durable equivalent), not a checked-in SQLite file or ephemeral workflow filesystem. Keep SEC_USER_AGENT, OPENAI_API_KEY, database URL and email credentials as encrypted secrets. Avoid exposing them through untrusted pull-request workflows. Prefer a managed scheduled runner once reliability and volume demand it.

## Runbook
1. Start with immutable run ID, watchlist version and interval; register `running` state.
2. Fetch submissions for all watch entities with rate limits and retries; dedupe accession inventory; cross-check prior lookback interval.
3. Fetch/parse new documents; write raw content hash, parser version and failures. Select comparison baselines.
4. Detect and persist all candidates, then verify groundings; investigate the top subset subject to budgets. Persist investigation traces and abstentions.
5. Transactionally finalize the run status and completeness counts; build report from persisted state, not in-memory process state.
6. Prepare digest with unique `(recipient_group, window, content_revision)` key; send once using provider idempotency where supported; store provider message ID/status and retry uncertain delivery safely.
7. Emit run metrics and alert on failure/partial windows, no source data when historically expected, prolonged lag, or repeated detection failures.

## Failure policies
| Failure | Response |
|---|---|
| SEC 429, timeout or transient outage | Exponential backoff and global concurrency cap; mark pending; replay on next run |
| SEC 403/user-agent blocked | Stop requesting that endpoint, surface configuration problem, do not claim no changes |
| Unsupported/ambiguous filing or entity | Store excluded/needs-review status; disclose coverage gap |
| Parser failed, ambiguous baseline | Preserve raw document and failure; do not guess event |
| LLM budget exhausted or unavailable | Send evidence-only findings labeled 'investigation pending' |
| Scheduler delayed or skipped | Recover via durable polling lookback from last successful checkpoint |
| Email failure/uncertain delivery | Use send ledger and provider status; avoid blind retries that could duplicate messages |
| Sensitive/poisoned filing text | Never treat document as execution instruction; tool allowlist, typed schemas and logging |

## Observability
Track run start/end, discovered and eligible filing counts, parser and category failure codes, number of candidate/verified/rejected events, source request rates, SEC error codes, latency p50/p95, model tool calls/tokens, estimated cost, digest generated/sent status and overdue checkpoints. Provide a daily operations summary for the developer without leaking secrets or private recipients.

## Cost and abuse limits
Configurable per-run token, dollar, document and research-depth limits. Cache immutable filings and model-independent normalization. Perform cheap deterministic filtering before LLM fanout. Research only the prioritized top events; preserve other events in the digest/index and disclose investigation coverage. Enforce SEC user-agent and source-specific throttling. Bounded concurrent workers and emergency stop.

## Security/deployment checklist
- Public repository only contains public/fictional data. No internal screenshots, employer code, API keys, contact info or live recipient lists.
- `.gitignore` excludes `.env`, local databases, caches and generated private reports. CI tests cannot require real credentials.
- Schema migrations, secret rotation instructions, dependency scanning and reproducible integration tests exist before unattended operation.
- Permissions for GitHub workflow read-only unless artifact/deployment writes required; minimal email scope; no arbitrary tool shell calls from filing content.

## Recovery rehearsal
Simulate a two-day scheduler outage, late amendment, duplicate accession, 429 response and a failed email. Verify complete replay, no duplicate event, no duplicate email, explicit partial status and preserved original evidence.
