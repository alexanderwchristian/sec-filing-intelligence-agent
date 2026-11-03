# Run and deploy the US fund + stock intelligence workspace

## Scope and verification

The new Python and Streamlit workspace includes SEC fund/stock watchlists,
deterministic category-based candidate detection, evidence-linked findings,
bounded AI filing research, persistent event history, daily Markdown
briefings, SMTP sending, and a local scheduler. The original Stage 1 issuer
10-K pipeline remains available.

**Not automatically hosted:** The public GitHub Pages site is still a
fictional static walkthrough. Deployment and SMTP credentials must be
provided by the owner. Broad real-world detection accuracy, complete
fund-class identity validation, and source-specific extraction remain
unverified; the tool labels findings as candidates.

## Local setup

Python 3.11+, Linux or macOS (POSIX flock), persistent disk.

1. Create a virtual environment.
2. Install: python -m pip install -e '.[ui,ai,dev]'
3. Set SEC_USER_AGENT to your name and genuine contact email. SEC requires
   this for programmatic fair access.
4. Optionally set OPENAI_API_KEY and RESEARCH_MODEL to activate bounded AI
   investigations. Without the key, the product provides review checklists
   and explicitly labels model research as disabled.
5. Set INTEL_DB_PATH to the full path of the SQLite file on persistent disk,
   otherwise the default is .filing-intel/intelligence.sqlite3.
6. Start: streamlit run app.py
7. Use Watchlist to add fund or stock CIKs. Fund series and class IDs improve
   the identity scope, but the detector NEVER claims a fund class is verified
   merely from the registrant CIK.
8. Run a scan from the Watchlist tab, then inspect Findings, Investigations
   and Daily Briefings. The original 10-K pairwise demo is available by
   disabling the dashboard toggle in the sidebar.

CLI examples:

    filing-intel intelligence add --kind stock --cik 320193 --name Apple
    filing-intel intelligence add --kind fund --cik FUND_CIK --name "Fund Name" --series-id S123 --class-id C123
    filing-intel intelligence scan --since 2025-01-01
    filing-intel intelligence events
    filing-intel intelligence status
    filing-intel intelligence digest --day 2026-11-02
    filing-intel intelligence daily --no-send

Replace FUND_CIK and identity placeholders with official SEC values.

## Single-host Docker deployment

1. Copy .env.example to .env, update placeholders with real values, and
   ensure the .env file remains untracked and private.
2. Create the persistent data folder: mkdir -p runtime
3. Start: docker compose up -d --build
4. Open localhost:8501 (the UI binds to 127.0.0.1, not public internet).
5. The scheduler and UI both use ./runtime/intelligence.sqlite3 by default
   inside Docker. Back up with SQLite's online backup API and monitor disk.
6. Logs: docker compose logs --tail=100 scheduler

For access from another computer, use a secured VPN/SSH tunnel or
authenticated reverse proxy. **Streamlit has no built-in authentication in
this project. Do not expose the dashboard publicly without adding it.**

The scheduler runs on a persistent, single-host Docker volume, not an
ephemeral GitHub Actions runner. It checks weekdays after 8 AM in
America/New_York using zoneinfo, which follows US DST. On recovery it
re-sweeps the last 90 days, deduplicates accessions and events, and
reuses cached filing documents. It does not automatically send missed
calendar-day digests from earlier outages.

## Daily email and replay semantics

SMTP env variables: SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
EMAIL_FROM, EMAIL_TO (comma-separated recipients). Email is optional
for local testing but must be configured for unattended delivery.

The sender records "sending" **before** SMTP network I/O. On apparent
success it records "sent". On network ambiguity it records "unknown"
and will not retry automatically; an operator must reconcile with
the SMTP provider before any manual intervention. SMTP alone cannot
guarantee exact-once inbox delivery.

The digest contains evidence and run completeness, separates fund and
stock changes, includes verified SEC source links, and avoids saying
"no changes" when a scan failed or never ran. It condenses large
finding sets but never removes stored events.

## Evaluation and release limitations

Run: python -m pytest

Use filing_intel.intel_evaluation for strict/relaxed event-level F1 on
manually labeled public SEC filing examples and independent exact quote
grounding checks. A five-case synthetic detector suite still exists;
its F1 must never be presented as real SEC accuracy.

Before calling the product production-ready, collect diverse real
fund and issuer filings with human labels, verify share-class/series
mapping and section baselines, test amendments and repeated disclosures,
run a controlled live SEC smoke test, and test end-to-end SMTP delivery
to a controlled inbox. The integration tests currently run offline
against independent fictional filings; a live v2 SEC acceptance is
not yet established.

## Security and operating limitations

No automated trading or portfolio recommendations. Retrieved filings
are untrusted data, not executable instructions. Model output requires
human review and quote validation. Document storage grows over time;
apply backup and retention controls on the deployment host.


## Optional specialized LLM detector fanout

Set USE_SEMANTIC_DETECTORS=1 and OPENAI_API_KEY to enable the bounded
per-category LLM review after deterministic extraction. Each candidate
retains its source text. At most six category calls and six examples per
category per filing are assessed; additional events remain persisted
with an explicit not_assessed_budget annotation. Quote-grounding and
model-output schema are validated independently. Model errors and
exceeded budgets mark a scan partial instead of becoming no-change
reports. Model calls cost money; default is disabled. A lexical
detector and an LLM verdict still do NOT establish investment
materiality or fund-class attribution.


## Manual, zero-scheduled-charge trace and live SEC quality run

The **Manual live SEC tracing and evaluation** GitHub Actions workflow is
\`workflow_dispatch\` only. It has no cron and never invokes the model unless
an operator explicitly checks \`run_ai\`. It runs offline tests, then fetches
exactly two independently verified public SEC documents: the November 2,
2026 Apple 8-K (CIK 320193, accession 0000320193-26-000024) and April 28,
2026 Vanguard 500 Index Fund / VOO 497K (CIK 36405, series S000002839,
class C000092055, accession 0000036405-26-000183). It computes actual
source-quote groundedness and uploads an evaluation JSON report.

Setup:
1. GitHub repository Settings -> Secrets and variables -> Actions: add
   \`OPENAI_API_KEY\` (already needed for optional model-based research).
2. Add a separate Actions secret \`SEC_USER_AGENT\`: your real name, followed
   by your actual contact email. SEC fair access requires this.
3. Merge the workflow PR. Go to Actions -> Manual live SEC tracing and
   evaluation -> Run workflow. Leave \`run_ai\` **unchecked** to perform a
   completely zero-model-call acceptance first. Check it only when you
   specifically want one traced OpenAI investigation.
4. Download the \`sec-trace-evaluation\` report artifact from the workflow
   run; it includes the SEC source URLs, candidate counts, exact quote
   validation, model call token usage when enabled, and explicit status.

When AI is requested, \`ENABLE_OPENAI_TRACING=1\` uses the official
OpenAI Agents SDK to export workflow, SEC retrieval, detection, research
model, read-only tool and source verification spans. The trace appears
under the linked API project in OpenAI Logs -> Traces. Span metadata uses
only IDs, names and counters, not raw filing text or secrets.
The workflow uses a bounded single investigation with a small model
output cap, not unrestricted batch reasoning. Usage is **not** an account
spend ceiling: keep auto-recharge off and enforce account/project spending
controls if you must guarantee no additional charges.

**Honest metric scope:** This run proves only live retrieval and exact
grounding on two pinned SEC documents. Without an independently and
completely human-labeled gold set, \`labeled_event_evaluation\` remains
\`not_measured\`. A fund registrant CIK alone is not validated class-level
attribution. The original five synthetic cases are not a real-world F1
estimate. Add manually labeled real data via the local CLI's \`--gold\`
argument once a full review set exists. This is not a hosted dashboard,
24/7 scanner, or automatic emailing deployment.
