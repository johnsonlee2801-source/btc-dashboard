# AI Stock SEO MVP Spec

Date: 2026-05-17

## 1. Problem Statement

The target user is a Chinese-speaking US stock investor who follows AI-related stocks, especially `NVDA`, `TSLA`, `PLTR`, `AMD`, and `SMCI`.

The problem: before buying, selling, or researching these stocks, users often check chart tools, brokerage apps, community feeds, group chats, and headlines. They may not have a fixed risk-check workflow. They may search questions such as "NVDA 是否过热", "TSLA 风险", or "AI 股票风险升温".

Evidence status: this is currently an assumption, not externally validated. The strongest evidence is the owner's own investing and research workflow. This MVP exists to test whether the search intent is real and whether users will stay to read a structured risk-check page.

## 2. Proposed Solution

Build five public, indexable stock-specific SEO pages:

- `NVDA`
- `TSLA`
- `PLTR`
- `AMD`
- `SMCI`

Each page must openly answer three questions:

- What is the current risk temperature?
- What are the three key pieces of evidence?
- What should the user check next?

The core page content must be static or semi-static HTML so users and search engines can read the main answer without JavaScript. Existing `/api/stock-radar` data may be used as progressive enhancement, but it must not be required for the core SEO content.

Membership may appear only as a light CTA, such as "view the full stock radar", "subscribe to updates", or "contact to unlock deeper checks". The core answer must not be locked.

## 3. Technical Constraints

Keep the current static-site plus Vercel Edge Functions architecture.

Constraints:

- Do not migrate to Next.js or SSR for this MVP.
- Do not rely on client-side JavaScript as the primary SEO content.
- Do not introduce a CMS, database, login system, payment flow, or subscription system.
- The MVP must be feasible for one person to complete within two weeks.
- The main body of each page must be indexable.
- Each key evidence item must include source, update time, and limitation.
- Page structure must avoid buy/sell recommendations. The page answers risk-check questions only.

## 4. Non-goals

This MVP explicitly does not include:

- Locking core content behind membership.
- Programmatic SEO pages for dozens of stocks.
- Optimizing BTC, ETH, or cross-asset pages as part of this MVP.
- Answering "should I buy or sell now?"
- Long company background essays or broad AI narrative explainers as the main content.
- Migrating to Next.js or SSR.
- Using client-side JavaScript as the SEO-primary content.
- Treating payment, redemption, or membership conversion as the main success metric.
- Automatically generating large numbers of unreviewed SEO pages.
- Building complex login, payment, or subscription systems.
- Refactoring BTC/ETH pages, price alerts, or the BTC distribution radar into this MVP.
- Adding a sixth stock page. Any new stock must replace one of the five MVP tickers.

## 5. Success Criteria

The validation window is 14 days after launch.

The MVP succeeds if all of the following happen:

- All five pages are indexed by Google.
- The five pages receive at least 100 total impressions in Google Search Console.
- The five pages produce at least 10 total on-site engagement events.

On-site engagement events include:

- Scrolling to the evidence section.
- Clicking a "what to check next" link.
- Clicking back to `/stock`.
- Clicking a source link.
- Clicking the light CTA.

The MVP fails if any of the following happen:

- Any of the five pages is not indexed after 14 days.
- Total Google Search Console impressions are below 100.
- Total on-site engagement events are below 10.
- Visitors mostly bounce without scrolling to evidence or clicking sources.

## 6. Top 3 Killer Risks

### 1. Search intent does not exist or is too weak

How it kills the project: if users do not search stock-specific AI risk questions, the pages will not receive organic traffic no matter how good the content is.

How to reduce or validate it now: only ship five pages first. Use Search Console impressions after 14 days as the first hard signal. If total impressions are below 100, do not expand pages; revisit keyword targeting and titles first.

### 2. Users perceive the pages as marketing or pseudo-advice

How it kills the project: if users arrive from search and see aggressive membership prompts or implied trading advice, they will not trust the page. Investment content loses trust quickly when it looks like promotion or prediction.

How to reduce it now: keep all core content public. Keep CTA placement light. The page must answer risk temperature, evidence, and next checks, not whether to buy or sell.

### 3. The evidence chain looks professional but users do not read it

How it kills the project: the target user may want confirmation, not a dense research report. If the page is too complex, it may get indexed but fail to produce engagement.

How to reduce it now: put a 30-second answer near the top, then show exactly three evidence items. Each evidence item should use a fixed structure: what it means, what its limitation is, and what to check next.
