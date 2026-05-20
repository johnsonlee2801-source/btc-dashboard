from __future__ import annotations

import json
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
            Evidence(
                "量价结构",
                "先看放量下跌日是否增加",
                "龙头股在高位如果开始出现放量下跌，说明风险检查优先级上升。",
                "Yahoo Finance 日线行情",
                "https://finance.yahoo.com/quote/NVDA",
                "页面发布日；动态价格由前端增强",
                "免费行情可能延迟；单日成交量不能单独说明机构行为。",
                "查看最近 5-10 个交易日是否跌时放量、涨时缩量。",
            ),
            Evidence(
                "AI 主题宽度",
                "确认 AI 核心样本是否同步走弱",
                "如果只有少数大权重维持强势，主题内部承接可能变窄。",
                "流程猎人 AI 样本宽度快照",
                "/data/snapshots/market-breadth-latest.json",
                "GitHub Actions 日更快照",
                "样本不是完整市场；宽度只能说明结构，不能证明个股方向。",
                "比较 AMD、AVGO、SMCI、PLTR 与 NVDA 是否同向。",
            ),
            Evidence(
                "披露与微结构",
                "Form 4 / 13F / FTD 只作交叉验证",
                "披露数据适合判断风险线索是否共振，不适合做实时交易决定。",
                "SEC / FINRA 公开数据",
                "https://www.sec.gov/edgar/search/",
                "披露源按官方节奏更新",
                "Form 4、13F、FTD 都有延迟和口径限制。",
                "只在量价风险也升温时，把披露异常作为加权证据。",
            ),
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
            Evidence(
                "量价结构",
                "先看大波动日后的承接质量",
                "TSLA 情绪强、波动大，风险温度需要看跌后是否快速收复。",
                "Yahoo Finance 日线行情",
                "https://finance.yahoo.com/quote/TSLA",
                "页面发布日；动态价格由前端增强",
                "单日涨跌幅容易被新闻扰动，不能直接推导趋势。",
                "观察大阴线后 1-3 天是否有放量修复。",
            ),
            Evidence(
                "主题宽度",
                "自动驾驶与 Mag7 是否同步",
                "若 TSLA 单独波动而 Mag7/AI 宽度没有配合，搜索用户应降低结论置信度。",
                "Mag7 / AI 样本宽度快照",
                "/data/snapshots/market-breadth-latest.json",
                "GitHub Actions 日更快照",
                "Mag7 样本很窄，容易被单票消息影响。",
                "同时看 NVDA、AAPL、MSFT、META 是否支持风险偏好。",
            ),
            Evidence(
                "披露与微结构",
                "短量、FTD、内部人披露只看共振",
                "这些证据能提示压力，但不能单独说明 TSLA 的操作方向。",
                "SEC / FINRA 公开数据",
                "https://www.finra.org/finra-data",
                "披露源按官方节奏更新",
                "短量不是 short interest，FTD 不是裸卖空证明。",
                "只有当短量/FTD 与价格破位同时出现时才提高关注。",
            ),
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
            Evidence(
                "量价结构",
                "看高位回撤是否放量",
                "高关注软件股如果高位回撤放量，说明风险线索正在集中。",
                "Yahoo Finance 日线行情",
                "https://finance.yahoo.com/quote/PLTR",
                "页面发布日；动态价格由前端增强",
                "量价信号有滞后，不能预测下一天涨跌。",
                "检查 20 日均线与近期成交量峰值。",
            ),
            Evidence(
                "主题宽度",
                "软件应用股是否同步扩散",
                "如果软件应用和 AI 核心股一起转弱，PLTR 的单票风险更值得优先检查。",
                "流程猎人 AI 股票池",
                "/data/ai-stock-pool.json",
                "随仓库数据更新",
                "股票池是精选样本，不代表全部软件股。",
                "比较 NOW、CRM、ADBE、APP 等相关标的。",
            ),
            Evidence(
                "披露与微结构",
                "13F 与 Form 4 只作为慢变量",
                "PLTR 这类高关注股容易被叙事驱动，披露数据更适合验证而不是领先预测。",
                "SEC EDGAR",
                "https://www.sec.gov/edgar/search/",
                "披露源按官方节奏更新",
                "13F 最多 45 天延迟，只显示季度末多头持仓。",
                "把披露变化放在财报和量价之后看。",
            ),
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
            Evidence(
                "量价结构",
                "确认相对强弱是否恶化",
                "AMD 常被放在 AI GPU 竞争链里比较，单看涨跌幅容易漏掉相对走弱。",
                "Yahoo Finance 日线行情",
                "https://finance.yahoo.com/quote/AMD",
                "页面发布日；动态价格由前端增强",
                "相对强弱需要和同主题股票一起看。",
                "比较 AMD 对 NVDA、SOXX 或 SMH 的相对走势。",
            ),
            Evidence(
                "主题宽度",
                "芯片链是否共同承接",
                "若芯片链多数站上均线，AMD 的风险温度更可能是个股层面；若集体走弱，则是主题层面风险。",
                "AI 样本宽度快照",
                "/data/snapshots/market-breadth-latest.json",
                "GitHub Actions 日更快照",
                "宽度样本有限，不能代表完整半导体行业。",
                "同时看 NVDA、AVGO、TSM、ASML、SMCI。",
            ),
            Evidence(
                "披露与微结构",
                "披露数据用于确认异常",
                "Form 4、13F、FTD 对 AMD 更适合做风险复核，不适合替代行情判断。",
                "SEC / FINRA 公开数据",
                "https://www.sec.gov/data-research/sec-markets-data",
                "披露源按官方节奏更新",
                "官方披露有延迟，且不覆盖盘中资金流。",
                "若量价转弱，再检查披露异常是否同步出现。",
            ),
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
            Evidence(
                "量价结构",
                "优先看剧烈波动后的成交量",
                "SMCI 波动大，风险温度不能只看一天涨跌，要看波动后是否有稳定承接。",
                "Yahoo Finance 日线行情",
                "https://finance.yahoo.com/quote/SMCI",
                "页面发布日；动态价格由前端增强",
                "高波动股票容易出现假突破和假跌破。",
                "检查跳空、长上影、放量下跌是否连续出现。",
            ),
            Evidence(
                "主题宽度",
                "服务器与算力链是否共振",
                "如果硬件链和芯片链同时走弱，SMCI 的单票风险更容易放大。",
                "AI 股票池与宽度快照",
                "/data/ai-stock-pool.json",
                "随仓库数据更新",
                "股票池是精选 AI 主题样本，不是完整行业覆盖。",
                "比较 VRT、DELL、NVDA、AMD 等硬件与算力链标的。",
            ),
            Evidence(
                "披露与微结构",
                "结算与短量线索只作辅助",
                "高波动票容易出现短量和 FTD 噪声，必须和量价一起看。",
                "FINRA / SEC 公开数据",
                "https://www.finra.org/finra-data",
                "披露源按官方节奏更新",
                "短量、FTD 都不能单独证明裸卖空或机构方向。",
                "只在价格破位、成交量放大时提高这些证据的权重。",
            ),
        ),
    ),
]


STYLE = """
:root{color-scheme:dark;--bg:#080b12;--bg-soft:#0d121c;--panel:#101722;--panel-2:#121b28;--line:#263241;--line-soft:rgba(148,163,184,.16);--text:#eef2f6;--muted:#8b98a8;--accent:#67e8f9;--accent-soft:rgba(103,232,249,.12);--yellow:#fbbf24;--red:#ff5f56;--green:#34d399;--sans:"Avenir Next","PingFang SC","Microsoft YaHei",system-ui,sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;min-height:100vh;background:radial-gradient(circle at 50% -20%,rgba(103,232,249,.10),transparent 34%),linear-gradient(90deg,rgba(255,95,86,.06),transparent 18%,transparent 82%,rgba(251,191,36,.06)),var(--bg);color:var(--text);font-family:var(--sans);line-height:1.62}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:none}.shell{max-width:1240px;margin:0 auto}.header{position:sticky;top:0;z-index:20;border-bottom:1px solid rgba(148,163,184,.16);background:rgba(7,9,13,.82);backdrop-filter:blur(18px)}.nav{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 18px}.brand{display:flex;align-items:center;gap:12px;min-width:0;color:inherit}.brand:hover{color:inherit}.logo{width:38px;height:38px;border:1px solid rgba(103,232,249,.34);border-radius:11px;display:grid;place-items:center;background:rgba(103,232,249,.08);box-shadow:none;font-size:19px;line-height:1}.brand-title{margin:0;font-size:17px;line-height:1.12;font-weight:900;letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.subtitle{margin-top:3px;color:var(--weak);font-size:12px;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.navlinks{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}.navlink,.cta{display:inline-flex;align-items:center;justify-content:center;min-height:36px;border:1px solid rgba(148,163,184,.18);border-radius:999px;padding:7px 11px;color:var(--muted);background:rgba(17,24,39,.58);font-size:12px;font-weight:400}.navlink:hover,.cta:hover{border-color:rgba(103,232,249,.5);color:var(--text);background:rgba(103,232,249,.10)}.member-pill{border-color:rgba(103,232,249,.38);color:var(--text);background:rgba(103,232,249,.10)}.wrap{max-width:1240px;margin:0 auto;padding:18px 14px 56px}.hero{display:grid;grid-template-columns:minmax(0,1.08fr) 360px;gap:14px;align-items:stretch}.panel,.evidence{border:1px solid var(--line-soft);border-radius:18px;background:linear-gradient(180deg,rgba(18,27,40,.94),rgba(13,18,28,.92));box-shadow:0 22px 70px rgba(0,0,0,.24)}.panel{padding:22px}.hero-main{min-height:330px;display:flex;flex-direction:column;justify-content:space-between;background:linear-gradient(135deg,rgba(103,232,249,.14),rgba(18,27,40,.96) 38%,rgba(13,18,28,.92))}.eyebrow{font-size:12px;color:var(--accent);letter-spacing:.13em;text-transform:uppercase;font-weight:900}.kicker{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:14px}.badge{display:inline-flex;align-items:center;border:1px solid rgba(251,191,36,.38);border-radius:999px;background:rgba(251,191,36,.12);color:#fde68a;padding:6px 10px;font-size:12px;font-weight:900}h1{max-width:760px;font-size:48px;line-height:1.02;margin:0 0 14px;letter-spacing:0}h2{font-size:20px;line-height:1.2;margin:30px 0 12px}.panel h2{margin-top:0}.answer{max-width:760px;font-size:18px;color:#dfe6ee;margin:0 0 10px}.muted{color:var(--muted)}.hero-note{max-width:720px;margin:0;color:var(--muted)}.ticker-card{display:flex;flex-direction:column;gap:14px}.ticker-symbol{font-size:52px;line-height:1;font-weight:950;letter-spacing:0}.company{font-size:17px;font-weight:900}.mini-list{display:grid;gap:10px;margin:4px 0}.mini-row{display:grid;gap:2px;border-top:1px solid rgba(148,163,184,.13);padding-top:10px}.mini-label{font-size:12px;color:var(--muted)}.mini-value{font-weight:900}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:14px}.evidence{padding:18px;background:rgba(13,18,28,.86)}.evidence h3{margin:0 0 8px;font-size:17px;line-height:1.25}.evidence p{margin:7px 0}.label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:13px;font-weight:900}.value{margin:3px 0 0}.next{border-color:rgba(103,232,249,.28);background:linear-gradient(135deg,rgba(103,232,249,.12),rgba(18,27,40,.94));margin-top:24px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.footer{margin-top:26px;color:var(--muted);font-size:13px;border-top:1px solid rgba(148,163,184,.16);padding-top:18px}.footer a{color:var(--muted)}@media(max-width:900px){.nav{align-items:flex-start;flex-direction:column}.navlinks{justify-content:flex-start}.hero,.grid{grid-template-columns:1fr}h1{font-size:36px}.hero-main{min-height:auto}.ticker-symbol{font-size:42px}}@media(max-width:560px){.header{position:static}.brand-title{font-size:16px}.subtitle{font-size:11px;white-space:normal}.navlink,.cta{width:auto;min-height:34px;padding:6px 9px}.wrap{padding:14px 10px 44px}.panel,.evidence{border-radius:14px;padding:16px}h1{font-size:30px}.answer{font-size:16px}}
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


def html(page: StockPage) -> str:
    ticker_lower = page.ticker.lower()
    title = f"{page.ticker} 风险温度检查 | {page.company} 是否过热 | 流程猎人"
    description = f"{page.ticker} 风险检查：用公开证据查看 {page.company} 当前风险温度、三条关键证据和下一步该查什么。不构成投资建议。"
    canonical = f"https://stock.flowhunt.net/stock/{ticker_lower}-risk"
    evidence_cards = "\n".join(
        render_evidence(item, idx) for idx, item in enumerate(page.evidence, 1)
    )
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "inLanguage": "zh-CN",
        "author": {"@type": "Organization", "name": "FlowHunt｜流程猎人"},
        "publisher": {"@type": "Organization", "name": "FlowHunt｜流程猎人"},
        "mainEntityOfPage": canonical,
    }
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
<header class="header">
  <div class="shell nav">
    <a class="brand" href="/stock" aria-label="打开 FlowHunt 股票风险雷达">
      <div class="logo">FH</div>
      <div>
        <p class="brand-title">FlowHunt｜流程猎人 · 热门股风险雷达</p>
        <div class="subtitle">买卖前 30 秒，用公开证据看风险温度</div>
      </div>
    </a>
    <div class="navlinks">
      <a class="navlink" href="/stock">股票雷达</a>
      <a class="navlink" href="/stock-en">English</a>
      <a class="navlink member-pill" href="/stock#screener">生成检查表</a>
    </div>
  </div>
</header>
<main class="wrap">
  <section class="hero">
    <article class="panel hero-main">
      <div>
        <div class="kicker">
          <div class="eyebrow">30 秒风险检查 · {escape(page.category)}</div>
          <span class="badge">{escape(page.risk_state)}</span>
        </div>
      <h1>{escape(page.search_question)}</h1>
      <p class="answer"><strong>当前风险温度：{escape(page.risk_state)}。</strong>{escape(page.risk_summary)}</p>
      </div>
      <p class="hero-note">这不是买卖建议，也不是价格预测。它只回答：风险热在哪里、证据是否一致、下一步该查什么。</p>
    </article>
    <aside class="panel ticker-card">
      <div class="eyebrow">Ticker</div>
      <div>
        <div class="ticker-symbol">{page.ticker}</div>
        <div class="company">{escape(page.company)}</div>
      </div>
      <div class="mini-list">
        <div class="mini-row"><span class="mini-label">当前判断</span><span class="mini-value">{escape(page.risk_state)}</span></div>
        <div class="mini-row"><span class="mini-label">页面类型</span><span class="mini-value">公开可索引风险检查</span></div>
        <div class="mini-row"><span class="mini-label">更多标的</span><span class="mini-value">主雷达页继续查看</span></div>
      </div>
      <p class="muted">核心内容公开可索引；动态行情和更多股票可到股票雷达查看。</p>
      <div class="actions"><a class="cta" href="/stock">打开完整股票雷达</a></div>
    </aside>
  </section>
  <section id="evidence">
    <h2>三条关键证据</h2>
    <div class="grid">{evidence_cards}</div>
  </section>
  <section class="panel next" id="next-checks">
    <h2>下一步该查什么</h2>
    <p>先确认三条证据是否共振：价格和成交量是否同步、AI 主题宽度是否支持、披露或微结构是否只是滞后噪声。若证据不一致，降低结论置信度。</p>
    <div class="actions"><a class="cta" href="/stock">查看 AI 股票风险雷达</a> <a class="cta" href="/stock-en">Open English version</a></div>
  </section>
  <p class="footer">数据来自 Yahoo Finance、SEC、FINRA 与流程猎人公开快照等来源。所有内容仅作研究参考，不构成投资建议。<a href="/stock">返回股票雷达</a></p>
</main>
<script>
const STOCK_SEO_TICKER={json.dumps(page.ticker)};
function track(name, detail){{
  const payload=detail||{{}};
  window.dispatchEvent(new CustomEvent('stock-seo-engagement',{{detail:{{name,detail:payload}}}}));
  if(typeof window.gtag==='function') window.gtag('event',name,payload);
}}
document.querySelectorAll('a[href]').forEach((link)=>{{
  link.addEventListener('click',()=>track('stock_seo_link_click',{{ticker:STOCK_SEO_TICKER,href:link.href}}),{{passive:true}});
}});
const evidence=document.getElementById('evidence');
if(evidence&&'IntersectionObserver' in window){{
  const observer=new IntersectionObserver((entries)=>{{
    if(entries.some((entry)=>entry.isIntersecting)){{
      track('stock_seo_evidence_view',{{ticker:STOCK_SEO_TICKER}});
      observer.disconnect();
    }}
  }},{{threshold:0.25}});
  observer.observe(evidence);
}}
window.addEventListener('load',()=>{{
  if(location.hash==='#evidence') document.getElementById('evidence')?.scrollIntoView();
}});
</script>
</body>
</html>
"""


def filename(page: StockPage) -> str:
    return f"stock-{page.ticker.lower()}-risk.html"


def main() -> None:
    for page in PAGES:
        output = ROOT / filename(page)
        output.write_text(html(page), encoding="utf-8")
        print(output.name)


if __name__ == "__main__":
    main()
