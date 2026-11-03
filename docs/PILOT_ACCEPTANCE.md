# No-cost SEC filings intelligence pilot: operations and acceptance

## What has been verified

Local work previously confirmed Python 3.12.16 startup, all 51 offline tests,
compilation, synthetic CLI evaluation, Streamlit health endpoint, and the seven
dashboard tabs. Those results are not proof of real SEC fund/stock detection.
PR #6 CI also passed, but its pinned Apple 8-K and Vanguard 497K test considers
individual first-observed documents rather than before/after changes.
Real source verification, meaningful accuracy and daily delivery require
separate acceptance.

## Local startup, no API key or paid services

Use Python 3.11 or newer on macOS/Linux:

    python3.12 -m venv .venv
    source .venv/bin/activate
    python -m pip install -e '.[ui,dev]'
    export USE_SEMANTIC_DETECTORS=0
    export ENABLE_OPENAI_TRACING=0
    export ENABLE_DAILY_AI_RESEARCH=0
    unset OPENAI_API_KEY
    export SEC_USER_AGENT="Your Real Name your-real-contact-email"
    export INTEL_DB_PATH="$PWD/.filing-intel/intelligence.sqlite3"
    python -m pytest
    python -m compileall -q app.py src/filing_intel
    filing-intel evaluate
    python -m streamlit run app.py --server.address 127.0.0.1

Replace the SEC_USER_AGENT placeholder with a genuine name and contactable
email as required by SEC fair access. The dashboard opens at
http://127.0.0.1:8501 and is local only. There is no automatic hosted
deployment, and no SECRET from GitHub Actions is available locally by default.

Add two watched public entities from the Watchlist tab or run:

    filing-intel intelligence add --kind stock --cik 320193 --name "Apple Inc."
    filing-intel intelligence add --kind fund --cik 36405 --name "Vanguard 500 Index Fund" --series-id S000002839 --class-id C000092055
    filing-intel intelligence scan --since 2026-04-01 --to 2026-11-03
    filing-intel intelligence status
    filing-intel intelligence events

The fund series/class identifiers are operator-supplied watch scope, not a
guarantee that every document under registrant CIK 36405 pertains to the
same fund or share class.

## Reproducible real-SEC acceptance

Run the full monitored discovery and replay pipeline, unlike PR #6's pinned
single-filing test:

    python examples/live_dual_track_smoke.py \
      --stock-cik 320193 --stock-name "Apple Inc." \
      --fund-cik 36405 --fund-name "Vanguard 500 Index Fund" \
      --series-id S000002839 --class-id C000092055 \
      --since 2026-04-01 --to 2026-11-03 \
      --db ".filing-intel/acceptance-run-001.sqlite3" \
      --report "artifacts/acceptance-run-001.json"

Choose a fresh DB filename each time. The script rejects an existing file so
older cached findings cannot falsely pass. The manual GitHub Actions workflow
**Live fund and stock pilot acceptance** performs the same checks, without
any OpenAI model calls; its optional trace switch exports instrumentation
spans and requires an API key for tracing only.

A PASS requires BOTH tracks to have real in-window supported documents,
source-backed candidates, at least one before/after comparison with an earlier
baseline, exact stored-source quote grounding, a completed scan, and an
identical replay that creates zero new documents/events and leaves event
identifiers unchanged. A partial SEC scan, absent baseline or missing quote
must FAIL. The report includes complete candidate evidence, filing links,
identity states, matched baselines and run errors.

**Scope limitation:** Such a pass validates only a specific live execution and
replay. It does not prove financial materiality, fund-class attribution,
production reliability, or real-event precision/recall. Those metrics require
human-labeled complete SEC filing sets with positive and negative examples.
The Evaluation tab accepts labels but none are supplied as independently
validated real-world ground truth. A model trace proves execution visibility,
not semantic correctness.

## Daily operation without extra paid services

    filing-intel intelligence daily --no-send

This saves an in-process scan and briefing to durable local SQLite. Model
research is disabled by default even when an API key exists; enable only with
ENABLE_DAILY_AI_RESEARCH=1. Partial scans return a nonzero CLI exit status.
The command does not send email. The separate Docker scheduler attempts SMTP
delivery by default and must NOT be enabled without credentials and testing.

For unattended operation, the worker must be awake, running, and sharing a
persistent DB with the dashboard. Single-host SQLite needs backups. Monitor
checkpoint freshness, partial runs, SEC failures, and disk growth. Downtime
triggers a 90-day replay but does not back-send missed daily emails.
GitHub Actions has ephemeral disk, so a scheduled Action alone cannot provide
a durable shared database or 24/7 dashboard. A free hosted architecture still
needs a verified persistence and recovery solution.

## Security

Do not commit or print API keys, SEC user contact identity, SMTP credentials
or real billing information. GitHub Secrets are write-only through the web UI
and cannot be read back as plaintext. Never treat passing offline CI as proof
that a real SEC or OpenAI call occurred. No production deployment, automatic
model evaluation, or paid hosting is enabled by these changes.
