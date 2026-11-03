# Large SEC pilot universe: 500 stocks plus 50 funds/ETFs

## Frozen as-of-date membership

The November 3, 2026 snapshot includes:

- 503 S&P 500 securities, representing exactly 500 unique SEC issuer CIKs.
  Alphabet, Fox and News Corp have two listed share classes each, but the
  scanner watches each issuer once. All 11 GICS sectors are covered.
- 50 distinct SEC investment fund series with 50 class IDs: 40 ETFs and 10
  mutual funds, with 10 in each sample category: US equity, international
  equity, fixed income, sector/factor/active ETFs, and mutual funds.
  The 50 funds span 22 registrant CIKs and 11 investment management brands.
- A frozen [public index constituent snapshot](https://github.com/lawcal/sp500-components-history).
  As of November 3 the file includes KVUE and excludes OKTA because the
  [S&P announced replacement](https://press.spglobal.com/2026-10-30-Okta-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600)
  is effective November 4.
- Fund class identifiers were preliminarily cross-referenced against a
  [SEC-derived daily mapping archive](https://github.com/jadchaar/sec-cik-mapper).
  LIVE re-verification against the official SEC map is REQUIRED before
  watchlist loading. See [SOURCES.json](../data/universes/SOURCES.json).

## Monitored categories and actual limitations

**Stocks:** financial performance, risk disclosures, management/governance,
liquidity/financing, guidance/outlook, and corporate events in 10-K, 10-Q
and 8-K (plus supported amendments). The current implementation detects
textual/keyword disclosure candidates. It does NOT reliably extract
financial statement figures, calculate period-over-period variances,
establish event materiality, or measure real-world detection F1.

**Funds:** the user-specified portfolio managers, fees/expenses, benchmarks,
investment objectives, strategies, lifecycle (launch, liquidation, merger
or closure), and share-class language, in supported prospectus/supplement
forms. Multiple fund series may share a registrant CIK. A ticker-to-CIK
mapping does not prove which share class a particular filing passage
describes. The current parser does not provide reliable full per-series
segmentation and may generate noisy review candidates for fund registrants.
Review class identity and every claimed change before trusting results.

## No-cost local setup

Use Python 3.11+ and a persistent local SQLite path:

    python -m pip install -e '.[ui,dev]'
    export SEC_USER_AGENT="Your Real Name your-real-contact-email"
    export INTEL_DB_PATH="$PWD/.filing-intel/intelligence.sqlite3"
    export USE_SEMANTIC_DETECTORS=0
    export ENABLE_DAILY_AI_RESEARCH=0
    unset OPENAI_API_KEY
    filing-intel-universe --mode validate
    filing-intel-universe --mode verify
    filing-intel-universe --mode apply --db "$INTEL_DB_PATH"

Replace SEC_USER_AGENT with your genuine contact identity as required by
SEC fair access. Offline 'validate' checks 503 securities, 500 issuers,
11 sectors, 50 unique series/classes, and five 10-fund sample groups.

The 'verify' mode fetches only two official SEC files:
[issuer tickers](https://www.sec.gov/files/company_tickers.json) and
[fund series/class tickers](https://www.sec.gov/files/company_tickers_mf.json).
It confirms each ticker/CIK and each fund ticker/CIK/series/class tuple,
lists every disagreement, and exits nonzero on ANY mismatch. The SEC
warns these mappings are periodically updated and not guaranteed complete.

The 'apply' mode repeats official verification and writes all 550 watches
to SQLite ONLY if every identity agrees. It deduplicates issuer share
classes and is idempotent. On an unresolved ticker it refuses to write
a partial watchlist. Review the generated artifacts/universe-resolution.json
before amending the frozen snapshot. Never invent missing IDs.

## Explicit bounded batches

After loading the full universe:

    filing-intel-universe-scan --batch-index 0 --batch-size 11 \
      --since 2026-04-01 --to 2026-11-03 \
      --db "$INTEL_DB_PATH" --report "artifacts/batch-000.json"

Batch indexes start at ZERO. Size 11 creates 50 batches of 10 issuer
watches plus one fund. Default size 10 creates 55 batches. Each batch
contains at most 25 watches; the scan reports coverage and NEVER calls
AI models when USE_SEMANTIC_DETECTORS=0. Fund checks need manual attribution
review. Scan serially, obey SEC fair access, and inspect errors, quote
grounding and persistent checkpoints.

The Streamlit dashboard exposes batches for large watchlists. Unbounded
normal scans and the old daily scheduler refuse more than 25 enabled
watches. This intentionally prevents an uncontrolled 550-issuer fetch.
It also means that reliable daily automation for all 550 is NOT YET
IMPLEMENTED: that needs a batch-aware durable worker, full-day completion
ledger, recovery and email acceptance. GitHub Actions ephemeral disks and
a sleeping laptop do not provide durable scheduling.

## What can currently be called validated

Offline CI checks manifest integrity, SEC identity gating on mocked maps,
idempotent 550-watch loading, bounded mixed batches, and honest coverage.
The manual [SEC identity verification Action](../.github/workflows/universe-verify.yml)
can recheck the official SEC maps with the existing repository SEC_USER_AGENT
secret and upload a report without model/API charges. It does not scan
all 550 filings, evaluate agents or deploy a hosted dashboard.

Neither green CI nor a watchlist count demonstrates real filing retrieval,
semantic event accuracy or provenance of fund share-class passages.
The two-track PR #7 acceptance is separate and still needs live execution.
A human-labeled public SEC ground-truth benchmark with negatives is
necessary before reporting real-world precision/recall/F1.

Status at authoring: frozen 500 + 50 universe is prepared; identity mapping
and watchlist scanning on the official SEC service are not yet verified
end-to-end. No paid providers or automatic AI runs are enabled.
