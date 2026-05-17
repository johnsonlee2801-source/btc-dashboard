# AI Stock SEO MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build five public, indexable AI stock risk-check SEO pages for NVDA, TSLA, PLTR, AMD, and SMCI.

**Architecture:** Keep the current static Vercel site. Add a small Python generator that creates five checked-in HTML pages from one stock config, then route clean URLs to those files with `vercel.json`. Add tests that verify the pages stay indexable, public, non-advisory, and wired into `sitemap.xml`.

**Tech Stack:** Static HTML/CSS/JS, Python 3 standard library, Vercel static rewrites, existing `/api/stock-radar` progressive enhancement.

---

## File Structure

- Create `scripts/build_stock_seo_pages.py`: source-of-truth generator for the five SEO pages.
- Create `stock-nvda-risk.html`, `stock-tsla-risk.html`, `stock-pltr-risk.html`, `stock-amd-risk.html`, `stock-smci-risk.html`: generated static pages committed to the repo.
- Modify `vercel.json`: add clean rewrites such as `/stock/nvda-risk` to `stock-nvda-risk.html`.
- Modify `sitemap.xml`: add the five canonical URLs under `https://stock.flowhunt.net/stock/<ticker>-risk`.
- Create `tests/test_stock_seo_pages.py`: validates generated pages, routes, sitemap, content openness, source/limitation metadata, and no buy/sell recommendation wording.

## Task 1: Add SEO Page Generator

**Files:**
- Create: `scripts/build_stock_seo_pages.py`

- [ ] **Step 1: Create the generator with fixed MVP stock config**

Create `scripts/build_stock_seo_pages.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Evidence:
    title: str
    value: str
    meaning: str
    source: str
    source_url: str
    updated: str
    limitation: str
    next_check: str


@dataclass(frozen=True)
class StockPage:
    ticker: str
    company: str
    category: str
    risk_state: str
    risk_summary: str
    search_question: str
    evidence: tuple[Evidence, Evidence, Evidence]


PAGES = [
    StockPage(
        ticker="NVDA",
        company="NVIDIA",
        category="AI 芯片 / 算力龙头",
        risk_state="偏热观察",
        risk_summary="NVDA 的风险检查重点不是预测涨跌，而是确认涨幅、成交量和 AI 主题宽度是否仍然互相支持。",
        search_question="NVDA 现在风险是否过热？",
        evidence=(
            Evidence("量价结构", "先看放量下跌日是否增加", "龙头股在高位如果开始出现放量下跌，说明风险检查优先级上升。", "Yahoo Finance 日线行情", "https://finance.yahoo.com/quote/NVDA", "页面发布日；动态价格由前端增强", "免费行情可能延迟；单日成交量不能单独说明机构行为。", "查看最近 5-10 个交易日是否跌时放量、涨时缩量。"),
            Evidence("AI 主题宽度", "确认 AI 核心样本是否同步走弱", "如果只有少数大权重维持强势，主题内部承接可能变窄。", "流程猎人 AI 样本宽度快照", "/data/snapshots/market-breadth-latest.json", "GitHub Actions 日更快照", "样本不是完整市场；宽度只能说明结构，不能证明个股方向。", "比较 AMD、AVGO、SMCI、PLTR 与 NVDA 是否同向。"),
            Evidence("披露与微结构", "Form 4 / 13F / FTD 只作交叉验证", "披露数据适合判断风险线索是否共振，不适合做实时买卖判断。", "SEC / FINRA 公开数据", "https://www.sec.gov/edgar/search/", "披露源按官方节奏更新", "Form 4、13F、FTD 都有延迟和口径限制。", "只在量价风险也升温时，把披露异常作为加权证据。"),
        ),
    ),
    StockPage(
        ticker="TSLA",
        company="Tesla",
        category="AI / 自动驾驶 / 高波动龙头",
        risk_state="偏热观察",
        risk_summary="TSLA 的风险检查重点是区分叙事推动、价格波动和真实承接，不把社区热度当作结论。",
        search_question="TSLA 现在风险是否升温？",
        evidence=(
            Evidence("量价结构", "先看大波动日后的承接质量", "TSLA 情绪强、波动大，风险温度需要看跌后是否快速收复。", "Yahoo Finance 日线行情", "https://finance.yahoo.com/quote/TSLA", "页面发布日；动态价格由前端增强", "单日涨跌幅容易被新闻扰动，不能直接推导趋势。", "观察大阴线后 1-3 天是否有放量修复。"),
            Evidence("主题宽度", "自动驾驶与 Mag7 是否同步", "若 TSLA 单独波动而 Mag7/AI 宽度没有配合，搜索用户应降低结论置信度。", "Mag7 / AI 样本宽度快照", "/data/snapshots/market-breadth-latest.json", "GitHub Actions 日更快照", "Mag7 样本很窄，容易被单票消息影响。", "同时看 NVDA、AAPL、MSFT、META 是否支持风险偏好。"),
            Evidence("披露与微结构", "短量、FTD、内部人披露只看共振", "这些证据能提示压力，但不能单独说明 TSLA 该买或该卖。", "SEC / FINRA 公开数据", "https://www.finra.org/finra-data", "披露源按官方节奏更新", "短量不是 short interest，FTD 不是裸卖空证明。", "只有当短量/FTD 与价格破位同时出现时才提高关注。"),
        ),
    ),
    StockPage(
        ticker="PLTR",
        company="Palantir",
        category="AI 软件 / 高估值情绪票",
        risk_state="偏热观察",
        risk_summary="PLTR 的风险检查重点是确认高估值叙事下，价格强势是否仍有成交量和主题宽度支撑。",
        search_question="PLTR 是否已经过热？",
        evidence=(
            Evidence("量价结构", "看高位回撤是否放量", "高关注软件股如果高位回撤放量，说明风险线索正在集中。", "Yahoo Finance 日线行情", "https://finance.yahoo.com/quote/PLTR", "页面发布日；动态价格由前端增强", "量价信号有滞后，不能预测下一天涨跌。", "检查 20 日均线与近期成交量峰值。"),
            Evidence("主题宽度", "软件应用股是否同步扩散", "如果软件应用和 AI 核心股一起转弱，PLTR 的单票风险更值得优先检查。", "流程猎人 AI 股票池", "/data/ai-stock-pool.json", "随仓库数据更新", "股票池是精选样本，不代表全部软件股。", "比较 NOW、CRM、ADBE、APP 等相关标的。"),
            Evidence("披露与微结构", "13F 与 Form 4 只作为慢变量", "PLTR 这类高关注股容易被叙事驱动，披露数据更适合验证而不是领先预测。", "SEC EDGAR", "https://www.sec.gov/edgar/search/", "披露源按官方节奏更新", "13F 最多 45 天延迟，只显示季度末多头持仓。", "把披露变化放在财报和量价之后看。"),
        ),
    ),
    StockPage(
        ticker="AMD",
        company="Advanced Micro Devices",
        category="AI 芯片 / GPU 竞争链",
        risk_state="正常观察",
        risk_summary="AMD 的风险检查重点是比较它与 NVDA、AVGO、SMCI 等算力链股票是否出现分化。",
        search_question="AMD 现在风险热不热？",
        evidence=(
            Evidence("量价结构", "确认相对强弱是否恶化", "AMD 常被放在 AI GPU 竞争链里比较，单看涨跌幅容易漏掉相对走弱。", "Yahoo Finance 日线行情", "https://finance.yahoo.com/quote/AMD", "页面发布日；动态价格由前端增强", "相对强弱需要和同主题股票一起看。", "比较 AMD 对 NVDA、SOXX 或 SMH 的相对走势。"),
            Evidence("主题宽度", "芯片链是否共同承接", "若芯片链多数站上均线，AMD 的风险温度更可能是个股层面；若集体走弱，则是主题层面风险。", "AI 样本宽度快照", "/data/snapshots/market-breadth-latest.json", "GitHub Actions 日更快照", "宽度样本有限，不能代表完整半导体行业。", "同时看 NVDA、AVGO、TSM、ASML、SMCI。"),
            Evidence("披露与微结构", "披露数据用于确认异常", "Form 4、13F、FTD 对 AMD 更适合做风险复核，不适合替代行情判断。", "SEC / FINRA 公开数据", "https://www.sec.gov/data-research/sec-markets-data", "披露源按官方节奏更新", "官方披露有延迟，且不覆盖盘中资金流。", "若量价转弱，再检查披露异常是否同步出现。"),
        ),
    ),
    StockPage(
        ticker="SMCI",
        company="Super Micro Computer",
        category="AI 服务器 / 高波动硬件链",
        risk_state="偏热观察",
        risk_summary="SMCI 的风险检查重点是高波动后的承接质量，以及服务器硬件链是否同步支持。",
        search_question="SMCI 风险是否偏热？",
        evidence=(
            Evidence("量价结构", "优先看剧烈波动后的成交量", "SMCI 波动大，风险温度不能只看一天涨跌，要看波动后是否有稳定承接。", "Yahoo Finance 日线行情", "https://finance.yahoo.com/quote/SMCI", "页面发布日；动态价格由前端增强", "高波动股票容易出现假突破和假跌破。", "检查跳空、长上影、放量下跌是否连续出现。"),
            Evidence("主题宽度", "服务器与算力链是否共振", "如果硬件链和芯片链同时走弱，SMCI 的单票风险更容易放大。", "AI 股票池与宽度快照", "/data/ai-stock-pool.json", "随仓库数据更新", "股票池是精选 AI 主题样本，不是完整行业覆盖。", "比较 VRT、DELL、NVDA、AMD 等硬件与算力链标的。"),
            Evidence("披露与微结构", "结算与短量线索只作辅助", "高波动票容易出现短量和 FTD 噪声，必须和量价一起看。", "FINRA / SEC 公开数据", "https://www.finra.org/finra-data", "披露源按官方节奏更新", "短量、FTD 都不能单独证明裸卖空或机构方向。", "只在价格破位、成交量放大时提高这些证据的权重。"),
        ),
    ),
]
```

- [ ] **Step 2: Add the HTML rendering code**

Append to `scripts/build_stock_seo_pages.py`:

```python
STYLE = """
:root{color-scheme:dark;--bg:#07090d;--panel:#111827;--line:#253241;--text:#eef2f6;--muted:#a0adba;--accent:#67e8f9;--yellow:#fbbf24;--red:#ff5f56;--green:#34d399;--sans:"Avenir Next","PingFang SC","Microsoft YaHei",system-ui,sans-serif;--serif:Georgia,"Songti SC","SimSun",serif}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,rgba(103,232,249,.08),transparent 28%),var(--bg);color:var(--text);font-family:var(--sans);line-height:1.68}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}.wrap{max-width:1080px;margin:0 auto;padding:24px 16px 56px}.nav{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:26px}.brand{font-weight:900}.nav a,.cta{border:1px solid rgba(148,163,184,.22);border-radius:999px;padding:8px 12px;color:var(--text);background:rgba(17,24,39,.6)}.hero{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px;align-items:stretch}.panel{border:1px solid rgba(148,163,184,.16);border-radius:18px;background:rgba(17,24,39,.82);padding:20px}.eyebrow{font-size:12px;color:var(--accent);letter-spacing:.14em;text-transform:uppercase}h1{font-family:var(--serif);font-size:42px;line-height:1.08;margin:10px 0 12px}h2{font-size:20px;margin:0 0 12px}.muted{color:var(--muted)}.badge{display:inline-flex;border:1px solid rgba(251,191,36,.35);border-radius:999px;background:rgba(251,191,36,.11);color:#fde68a;padding:6px 10px;font-weight:800}.answer{font-size:18px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:18px}.evidence{border:1px solid rgba(148,163,184,.15);border-radius:16px;background:rgba(7,9,13,.28);padding:16px}.evidence h3{margin:0 0 8px;font-size:17px}.label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:12px}.value{margin:3px 0 0}.next{border-color:rgba(103,232,249,.28);background:rgba(103,232,249,.08)}.footer{margin-top:26px;color:var(--muted);font-size:13px;border-top:1px solid rgba(148,163,184,.16);padding-top:18px}@media(max-width:820px){.hero,.grid{grid-template-columns:1fr}h1{font-size:32px}.nav{align-items:flex-start;flex-direction:column}}
"""


def html(page: StockPage) -> str:
    ticker_lower = page.ticker.lower()
    title = f"{page.ticker} 风险温度检查 | {page.company} 是否过热 | 流程猎人"
    description = f"{page.ticker} 风险检查：用公开证据查看{page.company}当前风险温度、三条关键证据和下一步该查什么。不构成投资建议。"
    canonical = f"https://stock.flowhunt.net/stock/{ticker_lower}-risk"
    evidence_cards = "\n".join(render_evidence(item, idx) for idx, item in enumerate(page.evidence, 1))
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "inLanguage": "zh-CN",
        "author": {"@type": "Organization", "name": "FlowHunt｜流程猎人"},
        "mainEntityOfPage": canonical,
    }
    import json
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
<style>{STYLE}</style>
</head>
<body>
<main class="wrap">
  <nav class="nav"><div class="brand">FlowHunt｜流程猎人 · AI 股票风险检查</div><div><a href="/stock">返回股票雷达</a> <a href="/pricing">会员说明</a></div></nav>
  <section class="hero">
    <article class="panel">
      <div class="eyebrow">30 秒风险检查 · {escape(page.category)}</div>
      <h1>{escape(page.search_question)}</h1>
      <p class="answer"><strong>当前风险温度：{escape(page.risk_state)}。</strong>{escape(page.risk_summary)}</p>
      <p class="muted">这不是买卖建议，也不是价格预测。它只回答：风险热在哪里、证据是否一致、下一步该查什么。</p>
    </article>
    <aside class="panel">
      <div class="eyebrow">Ticker</div>
      <h2>{page.ticker} · {escape(page.company)}</h2>
      <div class="badge">{escape(page.risk_state)}</div>
      <p class="muted">核心内容公开可索引；动态行情和更多股票可到股票雷达查看。</p>
      <p><a class="cta" href="/stock">打开完整股票雷达</a></p>
    </aside>
  </section>
  <section id="evidence">
    <h2>三条关键证据</h2>
    <div class="grid">{evidence_cards}</div>
  </section>
  <section class="panel next" id="next-checks">
    <h2>下一步该查什么</h2>
    <p>先确认三条证据是否共振：价格和成交量是否同步、AI 主题宽度是否支持、披露或微结构是否只是滞后噪声。若证据不一致，降低结论置信度。</p>
    <p><a class="cta" href="/stock">查看 AI 股票风险雷达</a></p>
  </section>
  <p class="footer">数据来自 Yahoo Finance、SEC、FINRA 与流程猎人公开快照等来源。所有内容仅作研究参考，不构成投资建议。</p>
</main>
<script>
window.addEventListener('load',()=>{{
  if(location.hash==='#evidence') document.getElementById('evidence')?.scrollIntoView();
}});
</script>
</body>
</html>
"""


def render_evidence(item: Evidence, idx: int) -> str:
    return f"""<article class="evidence">
  <h3>{idx}. {escape(item.title)}</h3>
  <p><strong>{escape(item.value)}</strong></p>
  <div class="label">这说明什么</div><p class="value">{escape(item.meaning)}</p>
  <div class="label">来源 / 更新时间</div><p class="value"><a href="{escape(item.source_url)}">{escape(item.source)}</a> · {escape(item.updated)}</p>
  <div class="label">局限</div><p class="value">{escape(item.limitation)}</p>
  <div class="label">下一步检查</div><p class="value">{escape(item.next_check)}</p>
</article>"""


def main() -> None:
    for page in PAGES:
        path = ROOT / f"stock-{page.ticker.lower()}-risk.html"
        path.write_text(html(page), encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the generator**

Run:

```bash
python3 scripts/build_stock_seo_pages.py
```

Expected output:

```text
stock-nvda-risk.html
stock-tsla-risk.html
stock-pltr-risk.html
stock-amd-risk.html
stock-smci-risk.html
```

- [ ] **Step 4: Commit the generator and generated pages**

Run:

```bash
git add scripts/build_stock_seo_pages.py stock-nvda-risk.html stock-tsla-risk.html stock-pltr-risk.html stock-amd-risk.html stock-smci-risk.html
git commit -m "feat: add AI stock SEO page generator"
```

## Task 2: Add Clean Routes and Sitemap Entries

**Files:**
- Modify: `vercel.json`
- Modify: `sitemap.xml`

- [ ] **Step 1: Add Vercel rewrites for the five pages**

In `vercel.json`, add these rewrite entries after the existing `/stock` rewrite:

```json
{
  "source": "/stock/nvda-risk",
  "destination": "/stock-nvda-risk.html"
},
{
  "source": "/stock/tsla-risk",
  "destination": "/stock-tsla-risk.html"
},
{
  "source": "/stock/pltr-risk",
  "destination": "/stock-pltr-risk.html"
},
{
  "source": "/stock/amd-risk",
  "destination": "/stock-amd-risk.html"
},
{
  "source": "/stock/smci-risk",
  "destination": "/stock-smci-risk.html"
}
```

- [ ] **Step 2: Replace `sitemap.xml` with all canonical URLs**

Replace `sitemap.xml` with:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://btc.flowhunt.net/</loc>
    <lastmod>2026-05-17</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://stock.flowhunt.net/stock</loc>
    <lastmod>2026-05-17</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.9</priority>
  </url>
  <url>
    <loc>https://stock.flowhunt.net/stock/nvda-risk</loc>
    <lastmod>2026-05-17</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://stock.flowhunt.net/stock/tsla-risk</loc>
    <lastmod>2026-05-17</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://stock.flowhunt.net/stock/pltr-risk</loc>
    <lastmod>2026-05-17</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://stock.flowhunt.net/stock/amd-risk</loc>
    <lastmod>2026-05-17</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://stock.flowhunt.net/stock/smci-risk</loc>
    <lastmod>2026-05-17</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
```

- [ ] **Step 3: Validate JSON and XML syntax**

Run:

```bash
python3 -m json.tool vercel.json >/tmp/vercel-json-check.txt
python3 -c "import xml.etree.ElementTree as ET; ET.parse('sitemap.xml'); print('sitemap ok')"
```

Expected output from the second command:

```text
sitemap ok
```

- [ ] **Step 4: Commit routing and sitemap**

Run:

```bash
git add vercel.json sitemap.xml
git commit -m "feat: route AI stock SEO pages"
```

## Task 3: Add SEO and Scope Tests

**Files:**
- Create: `tests/test_stock_seo_pages.py`

- [ ] **Step 1: Add regression tests**

Create `tests/test_stock_seo_pages.py`:

```python
import json
import pathlib
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
TICKERS = ["nvda", "tsla", "pltr", "amd", "smci"]


class StockSeoPagesTests(unittest.TestCase):
    def test_pages_exist_and_are_static_html(self):
        for ticker in TICKERS:
            text = (ROOT / f"stock-{ticker}-risk.html").read_text(encoding="utf-8")
            self.assertIn("<h1>", text)
            self.assertIn("三条关键证据", text)
            self.assertIn("下一步该查什么", text)
            self.assertIn("不构成投资建议", text)
            self.assertIn(f"https://stock.flowhunt.net/stock/{ticker}-risk", text)

    def test_pages_expose_sources_updates_and_limitations(self):
        for ticker in TICKERS:
            text = (ROOT / f"stock-{ticker}-risk.html").read_text(encoding="utf-8")
            self.assertGreaterEqual(text.count("来源 / 更新时间"), 3)
            self.assertGreaterEqual(text.count("局限"), 3)
            self.assertGreaterEqual(text.count("下一步检查"), 3)

    def test_pages_do_not_make_buy_sell_recommendations(self):
        banned = ["建议买入", "建议卖出", "可以买", "应该买", "应该卖", "清仓", "满仓"]
        for ticker in TICKERS:
            text = (ROOT / f"stock-{ticker}-risk.html").read_text(encoding="utf-8")
            for phrase in banned:
                self.assertNotIn(phrase, text, f"{ticker} contains banned phrase {phrase}")

    def test_vercel_routes_exist(self):
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        rewrites = {(item["source"], item["destination"]) for item in config["rewrites"]}
        for ticker in TICKERS:
            self.assertIn((f"/stock/{ticker}-risk", f"/stock-{ticker}-risk.html"), rewrites)

    def test_sitemap_contains_stock_urls(self):
        tree = ET.parse(ROOT / "sitemap.xml")
        locs = [node.text for node in tree.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        for ticker in TICKERS:
            self.assertIn(f"https://stock.flowhunt.net/stock/{ticker}-risk", locs)

    def test_no_extra_stock_seo_pages(self):
        pages = sorted(p.name for p in ROOT.glob("stock-*-risk.html"))
        self.assertEqual(
            pages,
            [f"stock-{ticker}-risk.html" for ticker in TICKERS],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test and existing tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all existing tests plus `StockSeoPagesTests` pass.

- [ ] **Step 3: Commit tests**

Run:

```bash
git add tests/test_stock_seo_pages.py
git commit -m "test: cover AI stock SEO pages"
```

## Task 4: Add Engagement Event Hooks

**Files:**
- Modify: generated files via `scripts/build_stock_seo_pages.py`
- Regenerate: `stock-nvda-risk.html`, `stock-tsla-risk.html`, `stock-pltr-risk.html`, `stock-amd-risk.html`, `stock-smci-risk.html`
- Modify: `tests/test_stock_seo_pages.py`

- [ ] **Step 1: Add a tiny event helper to the generated HTML**

In `scripts/build_stock_seo_pages.py`, replace the current final `<script>` block with:

```html
<script>
function track(name, detail){
  window.dispatchEvent(new CustomEvent('stock-seo-engagement',{detail:{name,detail}}));
  if(window.gtag) window.gtag('event', name, detail || {});
}
let evidenceSeen=false;
const evidence=document.getElementById('evidence');
if('IntersectionObserver' in window && evidence){
  new IntersectionObserver((entries,observer)=>{
    if(!evidenceSeen && entries.some(e=>e.isIntersecting)){
      evidenceSeen=true;
      track('stock_seo_evidence_view',{ticker:'{page.ticker}'});
      observer.disconnect();
    }
  },{threshold:.35}).observe(evidence);
}
document.querySelectorAll('a').forEach(a=>{
  a.addEventListener('click',()=>track('stock_seo_link_click',{ticker:'{page.ticker}',href:a.getAttribute('href')||''}));
});
if(location.hash==='#evidence') evidence?.scrollIntoView();
</script>
```

Keep it inside the Python f-string so `{page.ticker}` renders to each ticker.

- [ ] **Step 2: Regenerate pages**

Run:

```bash
python3 scripts/build_stock_seo_pages.py
```

Expected: the same five page filenames print.

- [ ] **Step 3: Extend tests for engagement hooks**

Add this method to `StockSeoPagesTests`:

```python
    def test_pages_emit_engagement_events(self):
        for ticker in TICKERS:
            text = (ROOT / f"stock-{ticker}-risk.html").read_text(encoding="utf-8")
            self.assertIn("stock_seo_evidence_view", text)
            self.assertIn("stock_seo_link_click", text)
            self.assertIn("stock-seo-engagement", text)
```

- [ ] **Step 4: Run tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit engagement hooks**

Run:

```bash
git add scripts/build_stock_seo_pages.py stock-nvda-risk.html stock-tsla-risk.html stock-pltr-risk.html stock-amd-risk.html stock-smci-risk.html tests/test_stock_seo_pages.py
git commit -m "feat: track AI stock SEO engagement"
```

## Task 5: Local Static Verification

**Files:**
- No source edits expected unless verification finds a bug.

- [ ] **Step 1: Serve the static site locally**

Run:

```bash
python3 -m http.server 4173
```

Expected: server listens on `http://localhost:4173`. Keep it running for manual/browser verification.

- [ ] **Step 2: Verify one generated page by HTTP**

In a second terminal, run:

```bash
curl -I http://localhost:4173/stock-nvda-risk.html
curl -s http://localhost:4173/stock-nvda-risk.html | grep -E "NVDA|三条关键证据|不构成投资建议"
```

Expected: first command returns `HTTP/1.0 200 OK`; second command prints matching page lines.

- [ ] **Step 3: Verify all generated files are reachable**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
for ticker in ['nvda','tsla','pltr','amd','smci']:
    path = Path(f'stock-{ticker}-risk.html')
    text = path.read_text(encoding='utf-8')
    assert f'/stock/{ticker}-risk' in text
    assert '三条关键证据' in text
    print(path, 'ok')
PY
```

Expected output:

```text
stock-nvda-risk.html ok
stock-tsla-risk.html ok
stock-pltr-risk.html ok
stock-amd-risk.html ok
stock-smci-risk.html ok
```

- [ ] **Step 4: Stop local server**

Stop the `python3 -m http.server 4173` process with `Ctrl-C`.

## Task 6: Final Diff Review

**Files:**
- Review all changed files.

- [ ] **Step 1: Check status**

Run:

```bash
git status --short
```

Expected: no unexpected files. Expected changed or committed files are the generator, five HTML pages, `vercel.json`, `sitemap.xml`, tests, and docs.

- [ ] **Step 2: Run full tests one more time**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Review diff against spec**

Run:

```bash
git diff --stat HEAD~3..HEAD
```

Expected: diff includes the five stock SEO pages, routing, sitemap, generator, and tests. It must not include BTC/ETH page refactors, login/payment work, or more than five SEO pages.

## Self-Review

- Spec coverage: Tasks cover the five public pages, static indexable content, clean routes, sitemap, lightweight CTA, engagement events, source/update/limitation metadata, no buy/sell recommendations, and no more than five pages.
- Placeholder scan: No task relies on "TBD", "TODO", vague error handling, or undefined later work.
- Type consistency: `PAGES`, `StockPage`, `Evidence`, `render_evidence`, `html`, and `main` are defined before use; tests expect the same five ticker slugs and filenames generated by the script.
