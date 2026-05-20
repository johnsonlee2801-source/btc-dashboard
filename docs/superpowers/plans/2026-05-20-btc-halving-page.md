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

- [ ] Write `halving.html` as a standalone BTC FlowHunt page.
- [ ] Preserve the useful modules: current cycle status, historical halvings, cycle comparison chart, relative-price calculator, next-cycle observation framework, on-chain indicator guide.
- [ ] Replace risky wording:
  - `预测` → `观察框架` where possible
  - `底部测算器` → `周期位置测算`
  - avoid direct buy/sell advice
- [ ] Replace fixed date `2026-04-21` with `new Date()` normalized to local date.
- [ ] Add disclaimer: `仅作研究参考，不构成投资建议。`

### Task 2: Wire routing and navigation

**Files:**
- Modify: `vercel.json`
- Modify: `index.html`

- [ ] Add Vercel rewrite `/halving` → `/halving.html`.
- [ ] Add a header navigation pill from dashboard to `/halving` named `⏳ 减半周期`.
- [ ] Add a reciprocal navigation pill from `halving.html` back to `/`, `/distribution-radar`, and `/eth`.

### Task 3: SEO and discovery

**Files:**
- Modify: `sitemap.xml`
- Modify: `robots.txt`

- [ ] Add `https://btc.flowhunt.net/halving` to `sitemap.xml` with priority `0.8`.
- [ ] Fix BTC `robots.txt` to point to `https://btc.flowhunt.net/sitemap.xml`, not stock sitemap.

### Task 4: Verification

**Files:**
- Test via local HTTP server and static parsing.

- [ ] Verify `/halving` returns 200 locally.
- [ ] Verify page contains `BTC 减半周期观察器`, `仅作研究参考，不构成投资建议`, and no fixed `TODAY = new Date('2026-04-21')`.
- [ ] Verify `vercel.json` parses as JSON and contains `/halving` rewrite.
- [ ] Verify main dashboard contains `/halving` link.
- [ ] Commit, deploy, alias, and verify live.
