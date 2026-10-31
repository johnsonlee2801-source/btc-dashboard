# Positioning Radar Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. User approved the design and local TDD implementation; no additional execution approval, commits or deployments.

**Goal:** Add a source-attributed multi-asset positioning radar and prominent summaries on BTC/ETH.
**Architecture:** Standard-library Python snapshots, pure JS ranking model, safe DOM renderer; no bundler.
**Tech Stack:** Python unittest, Node test runner, existing Playwright/Chrome.
**Spec:** `docs/superpowers/specs/2026-10-31-positioning-radar-design.md` (approved 2026-10-31).

## Global Constraints
- Preserve existing dirty work and duplicate files; work in this authorized project directory.
- Public unauthenticated GET only; no paid calls, credentials, commits, push, workflow dispatch or deployment.
- Per-field original dates; 3h contract freshness, 48h chain freshness; future values invalid.
- Missing evidence never becomes zero, a high-concentration candidate or an institution claim.

## Review Focus
- Wrong symbols, empty strings and nonfinite numbers cannot pass numerical gates.
- Ratios and OI must use the same hourly observation; deltas need exact 24h earlier data.
- Missing/expired observations cannot create new/exit signals.
- DOM labels and evidence URLs are untrusted; no HTML interpolation of source content.
- Actual venue coverage and data access restrictions are reported separately from offline test success.

### Task 1: Collector and data contract
Files: `scripts/build_positioning_radar.py`, `tests/test_positioning_radar.py`.
Interface: `build_row(info, sources, previous, now)` -> `{symbol, baseAsset, metrics}`;
metric is `{value, asOf, source, url, note}`. `apply_evidence(row, evidence, now)` validates curated source evidence; absent mappings remain unknown.
- [x] Write tests: exact24h deltas (0.60->0.65=5pp), mismatched clocks, valid0, future timestamps, failed source cache retention, OI units vs USD, funding settlement intervals, unknown chain attribution.
- [x] Run `python3 -B -m unittest discover -s tests -p test_positioning_radar.py -q` RED.
- [x] Implement limited-rate public collector, all active crypto USDT perpetuals, bounded30day history and explicit field errors.
- [x] Run same command GREEN; collect public snapshot locally, report actual coverage.

### Task 2: Ranking model and UI
Files: `assets/positioning-radar-model.js`, `assets/positioning-radar.js`, `assets/positioning-radar.css`, `positioning-radar.html`, `tests/positioning-radar.test.cjs`, `tests/qa_positioning_radar.py`.
Interface: `PositioningRadarModel.analyze(snapshot, now)` -> eligible rows, ranked groups, coverage, comparisons; renderer and summary share it.
- [x] Write independent fixtures for opposite directions,50% neutral,OI3m/10m,90/95%,stale/future data, search and coverage-aware crossings; observe RED.
- [x] Implement pure ranking model, all reference sections, searchable/expandable tables, evidence dialog, refresh, empty/stale/offline states.
- [x] Write browser tests before DOM implementation: mobile scrolling, search/filter/expand/detail, XSS, summary agreement, offline recovery; observe RED then GREEN.

### Task 3: Integrate, verify and document
Files: `index.html`, `eth.html`, `vercel.json`, `scripts/preview_observatory.py`, `.github/workflows/update-positioning-radar.yml`, `.github/workflows/deploy-vercel.yml`, `sitemap.xml`, `docs/positioning-radar-data.md`.
- [x] Add homepage summaries/navigation; exact route `/positioning-radar`; prepare hourly snapshot workflow through sole existing deployment path (do not trigger).
- [x] Run all Python and existing+new JS tests, existing observatory acceptance and radar browser acceptance; inspect screenshots and actual snapshot coverage.
- [x] Fresh read-only review, fix material findings with RED/GREEN; report data limitations and local-only state.

## Execution ledger
- Ruling: user approved local implementation in current project, so preserve its existing edits rather than move to a clean worktree that omits unpublished fixes. No commit or branch change.
- Ruling: preserve strict public/free source boundary. Unverified concentration/identity/unlock fields are fully represented in UI and typed evidence interface, but do not gain fake values to fill a table.
- Pre-flight: collector -> JS model -> full page and summaries share `metrics` and timestamps; no BTC scoring dependency.
- Task 1/2 RED evidence: absent collector13 failures; absent JS model15 failures; new route404 browser failure. Initial GREEN: collector13, model15, browser6. Added precision/health/date regressions before fixes, then collector17/model16/browser7 GREEN.
- Fresh read-only reviewer found four P2 issues: failure state publication, newest common window selection, focus/scroll preservation and discarded concentration audit. Each was reproduced before its fix. Source health helper remains separate from publishing a valid degraded snapshot.
- Ruling: publish valid degraded source-state JSON with workflow warnings (rather than fail the whole data-state workflow), so the existing successful-workflow deployment path can convey HTTP451/429 failures to users. `dataStatus` explicitly states unavailable; original observation timestamps and universe date remain unchanged. This changes neither trading conclusions nor the no-deployment constraint of this local run.
- Ruling: preserve focus and horizontal offsets while updating sections; keep a bounded on-page concentration evidence summary with a link to the complete source ledger.

- Completed: full public scan519/519 crypto USDT perpetuals, 0 failed requests. Snapshot generated2026-10-31T02:37:11.048Z; all519 have aligned fresh positions, 24h deltas, OI, ticker and settled funding observations. At validation31 divergence candidates,176 long-crowded and91 short-crowded meet OI gates. Concentration coverage0: high/watch counts intentionally unknown.
- Completed: all four reviewer findings reproduced and fixed. Collector19 tests, model16 tests, radar9 browser methods pass. Complete project110 Python tests and32 Node tests pass; existing67 browser checks and6 observatory contract methods pass.
- Ruling: observatory contract retries initially failed with concrete ERR_SOCKET_NOT_CONNECTED/ERR_CONNECTION_RESET on static JS, not assertion mismatches. Local threaded HTTP accept backlog5 was insufficient after adding assets. Set backlog128 in the preview/test server; affected6-method regression passed. No market logic changed for this transport issue.
- Independent source verification: six dated GET requests validated12 BTC/ETH numerical relationships (top/all-account shares, OI, each exact24h change) against the saved snapshot.
- Real-data acceptance:10 checks across radar/BTC/ETH at1440/390/320px, matching519/519 and31 counts, evidence dialog, no page overflow, zero uncaught JS errors. Viewport screenshots visually inspected. Evidence directory: /var/folders/fm/j1kvmlpj257184665jhtr_rw0000gn/T/radar-real-acceptance-wqzc2mnb.
- Preview: http://127.0.0.1:8766/positioning-radar, loopback-only new process; prior preview was not restarted. No Git commit, fetch, push, workflow dispatch, installation or deployment.
- Remaining product limitations: full verified chain concentration/supply/unlocks/market-maker feeds remain absent; these sections and evidence ingestion contract are implemented, but they are not claimed connected. New hourly workflow is prepared locally only. Existing BTC/ETH snapshots retain their previous dates and may be stale; this task did not refresh their separate research pipeline.
