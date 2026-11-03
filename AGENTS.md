# Codex repository instructions

This is an independently implemented, public-data research portfolio project. Read `docs/PRODUCT_REQUIREMENTS.md`, `docs/FILING_COVERAGE.md`, `docs/EVENT_SCHEMA.md`, `docs/ARCHITECTURE.md`, `docs/EVALUATION.md`, `docs/OPERATIONS.md`, and `docs/IMPLEMENTATION_PLAN.md` before proposing a scope-changing edit. Use `docs/SOURCE_CONTEXT.md` to distinguish prior reference-system characteristics from independently implemented functionality.

## Non-negotiable rules
- Do not copy or reconstruct any employer-owned source code, prompts, datasets, documents, architecture diagrams, or production credentials. Use public filings, fictional examples, and independent implementation.
- Don't describe planned features as working. The current Python MVP compares two 10-K Item 1A sections and has no persistent daily monitor.
- Preserve existing CLI, tests, and UI unless a reviewed migration replaces them. Change one vertical slice at a time; propose tests before coding.
- Deterministic tools own discovery, retrieval, parsing, identity mapping, versioning, diffing, persistence, delivery and evidence validation. Models may classify, interpret and plan bounded investigation steps, not invent filing facts.
- Every factual finding must trace to an accessible source document, accession, exact quote/span and its comparison baseline. Distinguish text change, semantic change, newly filed event, and investment significance.
- Never silently truncate results or convert retrieval/parse failures to 'no changes'. Keep complete machine-readable results and explicit partial-run status.
- Implement idempotent durable run state and replay/backfill before scheduling email delivery; never rely on the GitHub runner's local disk to persist history.
- Respect SEC fair access; provide contactable SEC_USER_AGENT, bounded rate limits, timeouts, backoff, and source-specific terms. No secrets, .env files, raw user addresses, or private data in commits or generated digests.
- Provide deterministic, mocked tests and manual public-source integration smoke tests. Report measured results only from reproducible runs; never claim general precision/recall from synthetic cases.
- Prefer incremental architecture and clear interfaces over unnecessary multi-agent delegation. Explicitly cap model calls, tokens, tool iterations, cost and retry budgets.
- No automated trading or portfolio decisions. Recommendations are research follow-ups with evidence and uncertainty, requiring human judgment.

## Workflow for Codex
1. Check current repository implementation and compare proposed work with the product specification and acceptance criteria.
2. Create one focused branch or PR per milestone. Don't begin later phases until prior milestone gates pass.
3. Add or adjust tests first, including negative and failure-mode cases. Run `pytest` and a reproducible CLI smoke test.
4. Update relevant docs and current-versus-planned status. Document assumptions, source caveats, and remaining gaps.
5. Request review for schema, detection logic, coverage changes, email delivery, and any new credentials.

## Definition of done
An increment is done only if code, tests, sample output, documentation, failure behavior, and evidence traces agree. See the milestone-specific exit criteria in `docs/IMPLEMENTATION_PLAN.md`.