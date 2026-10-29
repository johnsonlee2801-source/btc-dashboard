# BTC / ETH Observatory Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; implement inline. The user asked to proceed directly after confirming BTC/ETH scope and public data with explicit missing values. No stock pages, paid APIs, production deployment, commits, or credential changes.

**Goal:** Replace the BTC and ETH landing pages with a responsive, source-attributed research dashboard based on the supplied indicator references.

**Architecture:** Static HTML, shared CSS/JavaScript, Python standard-library snapshot collector. Preserve existing API and tool URLs. Same-origin JSON snapshots keep visitor requests small; the existing ticker supplies separately timestamped live quotes. No bundler or new application framework.

**Spec:** The latest BTC long-form image supplies the hierarchy: overview, valuation band, historical trend, three signal groups, price ladder, capital flows, cohort flows, sentiment. ETH shares the visual language with separate technical/protocol metrics; BTC mining/STH thresholds and Bitcoin sentiment are not silently applied to ETH.

## Design

- Ink #0c1016, panels #151c26, borders #293442, muted #9aa8bb, amber #ffb547, green #41d69c. Amber indicates price/attention, green a met condition, red negative flow; missing data stays neutral.
- System Chinese sans for text, tabular system numerals for values. Dense and legible: 13–15px supporting text, 28–44px primary values. Reference-like compact panels with consistent 14px radii.
- Desktop: broad price/signal workspace and narrower context column. Mobile: one reading column with 2-column indicator tiles, no clipped controls or horizontal page scrolling.
- Preserve FlowHunt identity; do not impersonate the author/watermark in the reference.

## Global Constraints

- Public unauthenticated data only. Never run the legacy AI parser or output credentials.
- Every value carries source, observation date, and freshness. Missing/future/expired values cannot light signals or be silently scored as zero.
- No screenshot prices, fabricated chart history, backtest win rates, or invented entity cohort flows.
- Missing STH cost means the combined signal/valuation band is indeterminate. Show available price levels separately.
- ETH has its own technical observations, not the BTC 100-point model or a Bitcoin-only sentiment reading.
- Keep /eth, /halving, /distribution-radar and the production workflow as the release path. Local changes only.

## Review Focus

1. Partial/stale/future source data: show unknown and score bounds rather than a confident recommendation.
2. Closed candles and date alignment: no in-progress candle in historical calculations; retain per-series observation dates.
3. Invalid numeric types/NaN/zero denominators: null, not a broken chart or false trigger.
4. Realtime quote versus daily indicators: distinct timestamps, don't silently recompute a historical snapshot.
5. Mobile/keyboard/fetch failures: accessible usable controls and explicit offline state.

## Tasks

- [x] 1. Add failing collector tests for closed candles, weekly RSI, score bounds, missing/future dates and BTC/ETH separation; run red. Implement `scripts/build_observatory.py` and run green. Fetch fresh public data into `data/observatory.json`, preserving dates on source failure.
- [x] 2. Add failing JavaScript tests for client freshness, signal selection, chart ranges, and derived labels. Implement `assets/observatory-model.js`, shared application script/styles, and replace `index.html`/`eth.html`. Use screenshot-inspired structure without trading instructions. Update page-title tests for the intentional new subtitles, retaining tool navigation contracts.
- [x] 3. Add six-hour snapshot workflow with 24h chain-source caching, connect its successful run to the existing deployment workflow, and monitor the new snapshot in health checks. Add source/method documentation and update sitemap dates for changed pages.
- [x] 4. Run full Python/Node tests and browser checks for desktop/mobile, both assets, range/filter/dialog controls, incomplete/stale/offline data. Visually inspect screenshots. Review the final diff and report data limitations and unshipped status.

## Execution record

- Baseline: 58 Python unittest tests passed (local route test requires loopback permission). No source changes existed before starting.
- Ruling: execute in the requested current workspace, preserving the user's direct instruction to proceed; no commits, branch integration, push or deployment.
- Public endpoint preflight: Binance candles, Alternative.me and BGeometrics snapshot responded without keys; Coin Metrics combined metric query returned HTTP 400, so it is not assumed available.
- Image lists seven relative tiles despite its 8-item heading. The eighth item in this implementation is the 90-day 20% drawdown condition explicitly supplied by the user's earlier reference; documented as a site rule rather than a reproduced proprietary score.

- Verification: 75 Python tests, 14 Node tests, 67 browser checks passed. Browser checks cover 320/390/768/1440px, BTC/ETH, filtering, ranges, dialogs, quotes, stale/missing/offline and XSS labels. Desktop/mobile screenshots visually inspected.
- Fresh public collection: BTC 22/31 and ETH 21/22 metric records fresh; both have 365 actual closed daily candles. BTC nine and ETH one absent/expired records are explicit. Both Farside ETF tables parsed with dated rows; no public source request failures in the final run.
- Independent review: fixed optional chain cache loss, per-exchange observation-date validation, below-line BTC position highlighting, and non-finite/reversed candle timestamps. Regression tests passed.
- Local-only release: no commits, fetch, push or deployment. Preview on 127.0.0.1:8765.

- Final additions from the reference: separate CMC sentiment and 25Δ risk reversal slots remain explicitly unavailable; True Mean has its delayed date, LTH cost and BTC/ETH DVOL are sourced independently. No approximation substituted for unavailable 25Δ expiry definitions.

## Release authorization

2026-10-29: User explicitly authorized immediate push and production release after local acceptance. This supersedes the implementation-only release restriction above. Use the existing GitHub Actions deployment entry; integrate latest data updates without overwriting unrelated changes, validate from a clean isolated worktree, and verify production BTC/ETH pages and API/data paths.
