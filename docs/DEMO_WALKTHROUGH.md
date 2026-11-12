# Three-minute SEC Filing Intelligence walkthrough

## Ready-to-present artifact

Open `docs/index.html` directly in a browser. All four hand-authored synthetic
candidates and their synthetic source documents are embedded, so no server,
SEC access, API key or paid service is required. JSON export is browser-local.
The original detector-output demo is preserved at `docs/legacy-demo.html`.

## Presentation path

Click **Start 3-minute tour** and follow Next:

1. **0:00–0:30 — scope:** 500 S&P issuer and 50 distinct fund-series pilot targets;
   four synthetic candidates across two fictional entities; zero live entities
   verified in this page.
2. **0:30–1:15 — stock:** inspect concentration wording and both synthetic source
   excerpts. Highlight the difference between wording and investment significance.
3. **1:15–2:00 — fund:** inspect the Class A fee change, effective date and exact
   source spans. Explain the need for correct series and class attribution.
4. **2:00–2:30 — pipeline:** click discovery, identity, baseline, grounding,
   investigation and persistence steps. This is architecture illustration,
   not a recorded execution trace.
5. **2:30–3:00 — evaluation:** explain that real SEC F1 is not measured in this
   demo; show the acceptance and evaluation gaps. Finish opens Sample briefing.

Search, track filters, individual candidate selection, source inspection,
JSON export, pipeline steps, briefing evidence links and keyboard tab navigation
are available outside the guided path.

## Hosting status and publication

On November 12, 2026, the proposed public URL returned GitHub Pages 404:
https://alexanderwchristian.github.io/sec-filing-intelligence-agent/
This change does not deploy a site, enable schedules, or call an AI model.
After review/merge and explicit authorization to publish, configure repository
**Settings → Pages → Deploy from a branch → main → /docs → Save**.
Wait for the Pages build and verify the URL before claiming public availability.
No paid service is needed. A merge alone does not enable Pages when it is disabled.

## Validation

- 76 deterministic tests passed, including a new fixture contract test validating
  every embedded source span and synthetic provenance.
- CLI offline demo completed.
- The separate legacy evaluator passed five synthetic regression scenarios
  (TP=3, FP=0, FN=0). This is not a score for the four hand-authored UI cards
  or real SEC accuracy.
- Browser preview returned HTTP 200. Checked stock/fund filters, empty search,
  synthetic source highlighting, all five tour steps, all six pipeline steps,
  sample briefing and JSON download. No browser errors were observed.
- Browser screenshot: `docs/demo-walkthrough-preview.jpg`.

Remaining gaps: real SEC acceptance evidence across both tracks, genuine exported
agent execution traces, broad human-labeled filing evaluation and operational
hosting/delivery acceptance. The page does not claim these are completed.
