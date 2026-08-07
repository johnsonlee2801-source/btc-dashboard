# BTC Halving Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `btc-model` halving-cycle tool as an independent `/halving` product page on `btc.flowhunt.net` without disrupting the existing BTC dashboard.

**Architecture:** Keep the site static and Vercel-friendly. Create one standalone `halving.html` page adapted from `johnsonlee28/btc-model/index.html`, wire it through `vercel.json`, and add navigation from the existing BTC dashboard. Keep investment-safety wording conservative.

**Tech Stack:** Static HTML/CSS/JS, Chart.js CDN, Vercel rewrites, Python/HTML smoke tests.

---

### Task 1: Create the halving page

**Files:**
- Create: `halving.html`
- Source reference: `/tmp/btc-model-inspect/index.html`

- [x] Write `halving.html` as a standalone BTC FlowHunt page.
  <!-- exec-status:WI-1 -->
  **Status:** DONE — 2026-08-07
  **Changed:** none — `halving.html` already present (39.5 KB)
  **Verified:** T1 — pytest `test_halving_page_exists_with_safe_positioning` PASSED
- [x] Preserve the useful modules: current cycle status, historical halvings, cycle comparison chart, relative-price calculator, next-cycle observation framework, on-chain indicator guide.
  <!-- exec-status:WI-2 -->
  **Status:** DONE — 2026-08-07
  **Changed:** tests/test_btc_halving_page.py — added coverage; page itself unchanged
  **Verified:** T1 — pytest `test_halving_page_preserves_core_modules` PASSED (all 6 modules present)
- [x] Replace risky wording:
  - `预测` → `观察框架` where possible
  - `底部测算器` → `周期位置测算`
  - avoid direct buy/sell advice
  <!-- exec-status:WI-3 -->
  **Status:** DONE — 2026-08-07
  **Changed:** none — wording already conservative (`预测` 0 hits, `观察框架` 3, `周期位置测算` 3, no buy/sell advice)
  **Verified:** T1 — pytest `test_halving_page_exists_with_safe_positioning` PASSED
- [x] Replace fixed date `2026-04-21` with `new Date()` normalized to local date.
  <!-- exec-status:WI-4 -->
  **Status:** DONE — 2026-08-07
  **Changed:** none — `halving.html:567` already reads `const TODAY    = new Date();`
  **Verified:** T1 — pytest `test_halving_page_exists_with_safe_positioning` PASSED
- [x] Add disclaimer: `仅作研究参考，不构成投资建议。`
  <!-- exec-status:WI-5 -->
  **Status:** DONE — 2026-08-07
  **Changed:** none — disclaimer appears 4× in `halving.html`
  **Verified:** T1 — pytest `test_halving_page_exists_with_safe_positioning` PASSED

### Task 2: Wire routing and navigation

**Files:**
- Modify: `vercel.json`
- Modify: `index.html`

- [x] Add Vercel rewrite `/halving` → `/halving.html`.
  <!-- exec-status:WI-6 -->
  **Status:** DONE — 2026-08-07
  **Changed:** none — `vercel.json` already declares the rewrite
  **Verified:** T1 — pytest `test_halving_route_and_dashboard_link_exist` PASSED
- [x] Add a header navigation pill from dashboard to `/halving` named `⏳ 减半周期`.
  <!-- exec-status:WI-7 -->
  **Status:** DONE — 2026-08-07
  **Changed:** tests/test_btc_halving_page.py — gap closure, label was untested; pill itself
  already present at `index.html:652`
  **Verified:** T1 — pytest `test_dashboard_halving_pill_keeps_its_label` PASSED
- [x] Add a reciprocal navigation pill from `halving.html` back to `/`, `/distribution-radar`, and `/eth`.
  <!-- exec-status:WI-8 -->
  **Status:** DONE — 2026-08-07
  **Changed:** tests/test_btc_halving_page.py — added coverage; page itself unchanged
  **Verified:** T1 — pytest `test_halving_page_links_back_to_sibling_products` PASSED (all 3 targets)

### Task 3: SEO and discovery

**Files:**
- Modify: `sitemap.xml`
- Modify: `robots.txt`

- [x] Add `https://btc.flowhunt.net/halving` to `sitemap.xml` with priority `0.8`.
  <!-- exec-status:WI-9 -->
  **Status:** DONE — 2026-08-07
  **Changed:** tests/test_btc_halving_page.py — gap closure, the `0.8` priority was untested;
  `sitemap.xml:5` already carries it
  **Verified:** T1 — pytest `test_halving_sitemap_entry_carries_expected_priority` PASSED
- [x] Fix BTC `robots.txt` to point to `https://btc.flowhunt.net/sitemap.xml`, not stock sitemap.
  <!-- exec-status:WI-10 -->
  **Status:** DONE — 2026-08-07
  **Changed:** none — `robots.txt` already points at the BTC sitemap
  **Verified:** T1 — pytest `test_btc_sitemap_and_robots_point_to_btc_host` PASSED

### Task 4: Verification

**Files:**
- Test via local HTTP server and static parsing.

- [x] Verify `/halving` returns 200 locally.
  <!-- exec-status:WI-11 -->
  **Status:** DONE — 2026-08-07
  **Changed:** tests/test_btc_halving_page.py — added `serve_with_rewrites()` helper and test
  **Verified:** T1 — pytest `test_halving_route_returns_200_locally` PASSED
  **Note:** a plain static server 404s on `/halving` — the extensionless route exists only as a
  Vercel rewrite. The new test applies `vercel.json` rewrites so the local check asserts the
  shipped behaviour rather than standing in for it.
- [x] Verify page contains `BTC 减半周期观察器`, `仅作研究参考，不构成投资建议`, and no fixed `TODAY = new Date('2026-04-21')`.
  <!-- exec-status:WI-12 -->
  **Status:** DONE — 2026-08-07
  **Changed:** none — pre-existing test already covered this
  **Verified:** T1 — pytest `test_halving_page_exists_with_safe_positioning` PASSED
- [x] Verify `vercel.json` parses as JSON and contains `/halving` rewrite.
  <!-- exec-status:WI-13 -->
  **Status:** DONE — 2026-08-07
  **Changed:** none — pre-existing test already covered this
  **Verified:** T1 — pytest `test_halving_route_and_dashboard_link_exist` PASSED
- [x] Verify main dashboard contains `/halving` link.
  <!-- exec-status:WI-14 -->
  **Status:** DONE — 2026-08-07
  **Changed:** none — pre-existing test already covered this
  **Verified:** T1 — pytest `test_halving_route_and_dashboard_link_exist` PASSED
- [ ] Commit, deploy, alias, and verify live.
  <!-- exec-status:WI-15 -->
  **Status:** BLOCKED — 2026-08-07
  **Changed:** none
  **Blocker:** Deploying to the live `btc.flowhunt.net` site is an outward-facing action, and the
  repo remote returns `Repository not found` (likely suspended by GitHub after the malicious
  `ci-878940` scanner workflow ran). Deployment is on hold until the GitHub account is secured
  and the remote is restored. Local verification only.
