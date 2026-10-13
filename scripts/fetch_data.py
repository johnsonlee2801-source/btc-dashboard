#!/usr/bin/env python3
"""
BTC Dashboard - 自动数据抓取脚本
每6小时运行一次，抓取链上/宏观数据，写入 data.json，推送到 GitHub
"""

import json, urllib.request, urllib.error, time, subprocess, os, re, math, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
FRED_KEY = os.environ.get("FRED_KEY", "")
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(REPO_DIR, "data.json")

def load_previous_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log(f"  读取旧 data.json 失败: {e}")
    return {}

def carry_forward(previous, current, path, label):
    old = previous
    for key in path:
        if not isinstance(old, dict):
            old = None
            break
        old = old.get(key)
    if current is None and old is not None:
        log(f"  ♻️ {label} 本轮抓取失败，沿用上一版有效值: {old}")
        return old
    return current

def drop_non_finite(node, path="data"):
    """Replace NaN/Infinity with None, in place, anywhere in the payload.

    A single non-finite float makes data.json unparseable by the browser, which
    takes down every metric on the page — not just the bad one.
    """
    items = node.items() if isinstance(node, dict) else enumerate(node)
    for key, value in list(items):
        if isinstance(value, (dict, list)):
            drop_non_finite(value, f"{path}.{key}")
        elif isinstance(value, float) and not math.isfinite(value):
            log(f"  ⚠️ {path}.{key} 是 {value}，无法写入 JSON，置为 null")
            node[key] = None


ONCHAIN_STALE_AFTER_DAYS = 3
# TIPS is a business-day series: a Monday reading is legitimately Friday's.
TIPS_STALE_AFTER_DAYS = 7
FED_STALE_AFTER_DAYS = 3


def age_in_days(as_of):
    """Age of an ISO date in days, or None when it is missing or unparseable."""
    if not isinstance(as_of, str):
        return None
    try:
        return (datetime.now(timezone.utc).date()
                - datetime.strptime(as_of, "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return None


def is_stale(age_days, limit):
    """Unknown ages and future dates both count as stale — neither can be
    trusted to mean 'current'."""
    return age_days is None or age_days < 0 or age_days > limit


def mark_onchain_freshness(previous, onchain):
    """Record how old each on-chain number is, and flag the old ones.

    MVRV feeds the score directly (it can even trigger the veto), so a value
    carried forward for weeks is worse than a missing one: the page renders it
    exactly like a fresh reading. Keep the carried value, but say how old it is.
    """
    prev_onchain = (previous or {}).get("onchain") or {}

    for metric in ("mvrv_zscore", "nupl"):
        as_of_key = f"{metric}_as_of"
        source_key = f"{metric}_source" if metric == "mvrv_zscore" else "nupl_source"
        if not onchain.get(as_of_key):
            # Value came from carry_forward, so its date and source did too.
            onchain[as_of_key] = prev_onchain.get(as_of_key)
            onchain[source_key] = prev_onchain.get(source_key)

        age_days = age_in_days(onchain.get(as_of_key))
        onchain[f"{metric}_age_days"] = age_days
        # Unknown age means the value predates this bookkeeping: treat as stale.
        onchain[f"{metric}_stale"] = is_stale(age_days, ONCHAIN_STALE_AFTER_DAYS)

        if onchain[f"{metric}_stale"] and onchain.get(metric) is not None:
            shown = f"{age_days} 天前" if age_days is not None else "日期未知"
            log(f"  ⚠️ {metric} 使用陈旧数据（{shown}），页面会标注")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def http_get(url, headers=None, timeout=25):
    h = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        log(f"  fetch error {url[:70]}: {e}")
        return None

def ask_deepseek(prompt, content, max_tokens=300):
    if not DEEPSEEK_KEY:
        log("  DeepSeek key 未配置，跳过 AI 解析")
        return None
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是数据解析助手。从给定内容中精确提取数值。只返回JSON，不含任何解释或markdown代码块。"},
            {"role": "user", "content": f"{prompt}\n\n---内容---\n{content[:10000]}"}
        ],
        "max_tokens": max_tokens,
        "temperature": 0
    }).encode()

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            text = result['choices'][0]['message']['content'].strip()
            # 清理可能的 markdown 代码块
            text = re.sub(r'```(?:json)?\s*', '', text).strip()
            text = text.rstrip('`').strip()
            return json.loads(text)
    except Exception as e:
        log(f"  DeepSeek parse error: {e}")
        return None

# ============================================================
# 1. ETF 净流入 - farside.co.uk
# ============================================================
def fetch_farside_etf():
    log("抓取 ETF 流入 (farside.co.uk)...")
    html = http_get("https://farside.co.uk/bitcoin-etf/", headers={"Referer": "https://www.google.com/"})
    if not html:
        log("  ⚠️ ETF 页面抓取失败")
        return None
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        target = None
        for t in tables:
            rows = t.find_all("tr")
            if len(rows) > 10:
                header = [c.get_text(strip=True) for c in rows[0].find_all(["th","td"])]
                if "Date" in header and "Total" in header:
                    target = (t, rows, header)
                    break
        if not target:
            log("  ⚠️ 未找到ETF表格")
            return None
        t, rows, header = target
        total_idx = header.index("Total")

        def parse_val(text):
            text = text.strip().replace(",", "")
            if not text or text in ["-", "—"]: return None
            if text.startswith("(") and text.endswith(")"):
                try: return -float(text[1:-1])
                except: return None
            try: return float(text)
            except: return None

        skip = {"total", "average", "maximum", "minimum", ""}
        valid = []
        for row in rows[1:]:
            cols = row.find_all(["td","th"])
            if len(cols) <= total_idx: continue
            date = cols[0].get_text(strip=True)
            if date.lower() in skip: continue
            val = parse_val(cols[total_idx].get_text(strip=True))
            if val is not None:
                valid.append({"date": date, "value": val})

        recent5 = valid[-5:] if len(valid) >= 5 else valid
        sum5d = round(sum(d["value"] for d in recent5), 1)
        latest = recent5[-1]["date"] if recent5 else ""
        log(f"  ✅ ETF 5日净流入: ${sum5d}M | 最新: {latest} | 明细: {[round(d['value'],1) for d in recent5]}")
        return {"sum5d": sum5d, "days": [d["value"] for d in recent5], "latest_date": latest, "source": "farside_parsed"}
    except Exception as e:
        log(f"  ⚠️ ETF 解析异常: {e}")
        return None

# ============================================================
# 0. BTC 价格 - CoinGecko（服务端抓，绕过浏览器限流）
# ============================================================
def fetch_btc_price():
    log("抓取 BTC 价格 (CoinGecko)...")
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true&include_market_cap=false"
        data = http_get(url)
        if data:
            d = json.loads(data)
            btc = d.get("bitcoin", {})
            price = btc.get("usd")
            change24h = btc.get("usd_24h_change")
            if price:
                log(f"  ✅ BTC 价格: ${price:,.0f} ({change24h:+.2f}%)")
                return {"price": price, "change24h": round(change24h, 2) if change24h else None}
    except Exception as e:
        log(f"  ⚠️ 价格抓取失败: {e}")

    # 备用：Binance API
    try:
        data = http_get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT")
        if data:
            d = json.loads(data)
            price = float(d.get("lastPrice", 0))
            change24h = float(d.get("priceChangePercent", 0))
            if price:
                log(f"  ✅ BTC 价格(Binance): ${price:,.0f} ({change24h:+.2f}%)")
                return {"price": price, "change24h": round(change24h, 2)}
    except Exception as e:
        log(f"  ⚠️ Binance备用也失败: {e}")

    return None

# ============================================================
# 2. 链上指标 - lookintobitcoin.com
# ============================================================
def fetch_bitcoin_data_metric(endpoint, key, label):
    """Read one daily metric from bitcoin-data.com.

    lookintobitcoin only yields these numbers to a scraper, and that scraping
    has been failing from CI since June while the dashboard quietly reused the
    last good value. This public JSON feed is the fallback, and it reports the
    date the value belongs to so staleness stops being invisible.
    """
    raw = http_get(f"https://bitcoin-data.com/v1/{endpoint}/last", timeout=20)
    if not raw:
        return None, None
    try:
        payload = json.loads(raw)
    except Exception as e:
        log(f"  ⚠️ {label} (bitcoin-data.com) 解析失败: {e}")
        return None, None
    value = payload.get(key)
    if not isinstance(value, (int, float)):
        log(f"  ⚠️ {label} (bitcoin-data.com) 响应缺少 {key}")
        return None, None
    as_of = payload.get("d")
    log(f"  ✅ {label} (bitcoin-data.com): {value} (数据日期: {as_of})")
    return float(value), as_of


def fetch_coinmetrics_btc():
    """Coin Metrics 社区版（免费）：用市值和 MVRV 比率算 MVRV Z-Score、NUPL，并给出 200 周均线。

    bitcoin-data.com 免费版只给 7 天前的数据（返回里写明 delayed），Coin Metrics 只晚 1 天。
    - 已实现市值 RC = 市值 / MVRV
    - NUPL = (市值 - RC) / 市值 = 1 - 1/MVRV
    - MVRV Z-Score = (市值 - RC) / 市值从 2010 年至今的标准差（与 LookIntoBitcoin 口径一致）
    - 200 周均线 = 最近 1400 个日收盘价的简单平均
    """
    log("抓取链上指标 (Coin Metrics community)...")
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
           "?assets=btc&metrics=CapMrktCurUSD,CapMVRVCur,PriceUSD&frequency=1d&page_size=10000")
    raw = http_get(url, timeout=60)
    try:
        rows = json.loads(raw)["data"] if raw else []
    except Exception as e:
        log(f"  ⚠️ Coin Metrics 解析失败: {e}")
        return None

    caps, z, nupl, as_of = [], None, None, None
    n = mean = m2 = 0.0  # Welford 累积方差，避免对 5000+ 天反复求标准差
    for r in rows:
        try:
            mc, mvrv = float(r["CapMrktCurUSD"]), float(r["CapMVRVCur"])
        except (KeyError, TypeError, ValueError):
            continue
        if mc <= 0 or mvrv <= 0:
            continue
        n += 1
        delta = mc - mean
        mean += delta / n
        m2 += delta * (mc - mean)
        sd = (m2 / n) ** 0.5
        if sd > 0:
            z = (mc - mc / mvrv) / sd
            nupl = 1 - 1 / mvrv
            as_of = r["time"][:10]

    prices = []
    for r in rows:
        try:
            prices.append(float(r["PriceUSD"]))
        except (KeyError, TypeError, ValueError):
            pass
    ma200w = round(sum(prices[-1400:]) / 1400) if len(prices) >= 1400 else None
    # 首页原本只从浏览器直连 CoinGecko 拿 200 日均线 / 历史高点 / 30 日涨跌；CoinGecko 限流或在国内连不上时，
    # 这几项（其中 200 日均线参与评分）就消失了，同一时刻不同访客看到不同分数。这里给出服务端兜底值。
    market = None
    if len(prices) >= 200:
        market = {
            "ma200d": round(sum(prices[-200:]) / 200, 2),
            "ath_close": round(max(prices), 2),
            "price_30d_ago": round(prices[-31], 2) if len(prices) >= 31 else None,
        }

    if z is None:
        log("  ⚠️ Coin Metrics 没有可用的 MVRV 数据")
        return None
    log(f"  ✅ MVRV Z-Score {z:.4f} / NUPL {nupl:.4f} / 200WMA ${ma200w:,} (数据日期: {as_of})")
    return {"mvrv_zscore": round(z, 4), "nupl": round(nupl, 4), "as_of": as_of, "ma200w": ma200w, "market": market}


def fetch_btc_dominance():
    raw = http_get("https://api.coingecko.com/api/v3/global", timeout=20)
    try:
        dom = json.loads(raw)["data"]["market_cap_percentage"]["btc"] if raw else None
    except Exception:
        dom = None
    if isinstance(dom, (int, float)) and 0 < dom < 100:
        log(f"  ✅ BTC 市占率: {dom:.2f}%")
        return round(dom, 2)
    log("  ⚠️ BTC 市占率获取失败")
    return None


def fetch_lookintobitcoin():
    log("抓取链上指标 (lookintobitcoin.com)...")
    mvrv_val = None
    nupl_val = None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mvrv_source = mvrv_as_of = None
    nupl_source = nupl_as_of = None

    # MVRV Z-Score
    html = http_get("https://www.lookintobitcoin.com/charts/mvrv-zscore/")
    if html:
        patterns = [
            r'current[_\s-]*value["\s:]+([0-9.-]+)',
            r'mvrv["\s:]+([0-9.-]+)',
            r'"value"\s*:\s*([0-9.-]+)',
        ]
        for p in patterns:
            m = re.search(p, html, re.IGNORECASE)
            if m:
                try:
                    mvrv_val = float(m.group(1))
                    if 0 < mvrv_val < 20:
                        log(f"  ✅ MVRV Z-Score (regex): {mvrv_val}")
                        break
                    mvrv_val = None
                except:
                    pass

        if mvrv_val is None:
            result = ask_deepseek(
                """这是 lookintobitcoin.com 的 MVRV Z-Score 页面HTML。
                请找出当前/最新的 MVRV Z-Score 数值（通常在 -2 到 10 之间）。
                返回JSON：{"mvrv_zscore": 数值} 或 {"error": "找不到"}""",
                html
            )
            if result and isinstance(result.get('mvrv_zscore'), (int, float)):
                mvrv_val = result['mvrv_zscore']
                log(f"  ✅ MVRV Z-Score (AI): {mvrv_val}")

    if mvrv_val is not None:
        mvrv_source, mvrv_as_of = "lookintobitcoin", today
    else:
        mvrv_val, mvrv_as_of = fetch_bitcoin_data_metric(
            "mvrv-zscore", "mvrvZscore", "MVRV Z-Score")
        if mvrv_val is not None:
            mvrv_source = "bitcoin-data.com"

    time.sleep(3)

    # NUPL
    html2 = http_get("https://www.lookintobitcoin.com/charts/relative-unrealized-profit--loss/")
    if html2:
        result = ask_deepseek(
            """这是 lookintobitcoin.com 的 NUPL（Net Unrealized Profit/Loss）页面HTML。
            NUPL 数值范围通常在 -1 到 1 之间（或 -100% 到 100%，那就除以100）。
            请找出当前/最新的 NUPL 数值。
            返回JSON：{"nupl": 数值（小数形式，如0.64）} 或 {"error": "找不到"}""",
            html2
        )
        if result and isinstance(result.get('nupl'), (int, float)):
            nupl_val = result['nupl']
            if abs(nupl_val) > 1:
                nupl_val = nupl_val / 100
            log(f"  ✅ NUPL (AI): {nupl_val}")

    if nupl_val is not None:
        nupl_source, nupl_as_of = "lookintobitcoin", today
    else:
        nupl_val, nupl_as_of = fetch_bitcoin_data_metric("nupl", "nupl", "NUPL")
        if nupl_val is not None:
            nupl_source = "bitcoin-data.com"

    return {
        "mvrv_zscore": mvrv_val,
        "nupl": nupl_val,
        "mvrv_zscore_as_of": mvrv_as_of,
        "nupl_as_of": nupl_as_of,
        "mvrv_zscore_source": mvrv_source,
        "nupl_source": nupl_source,
    }

# ============================================================
# 3. 美联储方向 - 多源备用
# ============================================================


def fetch_fed_direction_rateprob():
    """
    优先使用 JSON API 源，避免 CME/财经站点的 403/404。
    来源: https://rateprobability.com/api/latest
    """
    url = "https://rateprobability.com/api/latest"
    data = http_get(url, headers={"Accept": "application/json"})
    if not data:
        return None
    try:
        payload = json.loads(data)
        today = payload.get("today") or {}
        rows = today.get("rows") or []
        midpoint = today.get("midpoint")
        if not rows:
            return None
        next_meeting = rows[0]
        prob = float(next_meeting.get("prob_move_pct", 0) or 0)
        is_cut = bool(next_meeting.get("prob_is_cut"))
        implied = next_meeting.get("implied_rate_post_meeting")
        change_bps = float(next_meeting.get("change_bps", 0) or 0)
        meeting = next_meeting.get("meeting") or next_meeting.get("meeting_iso") or "next meeting"

        if is_cut and prob >= 50:
            direction = "cut2"
            confidence = "high"
        elif (not is_cut) and (change_bps >= 12.5 or (midpoint is not None and implied is not None and float(implied) > float(midpoint) + 0.125)):
            direction = "hike"
            confidence = "high"
        else:
            # 下次会议降息概率不到一半：市场的基准情形是按兵不动，用页面已有的「观望」档（5/10），
            # 不再归入 cut1（7/10，偏鸽）
            direction = "hold"
            confidence = "medium" if prob >= 10 or abs(change_bps) >= 5 else "high"

        reasoning = f"{meeting} 定价：{'降息' if is_cut else '加息/不降息'}概率 {prob:.2f}%，变动 {change_bps:.1f}bps"
        log(f"  ✅ 美联储方向(RateProbability API): {direction} ({reasoning})")
        return {
            "fed_direction": direction,
            "reasoning": reasoning,
            "confidence": confidence,
            "source": "rateprobability_api"
        }
    except Exception as e:
        log(f"  RateProbability API parse error: {e}")
        return None


def parse_oddpool_cut_count_html(html):
    """Parse Oddpool's Fed cut-count page and return probability of >=1 cut this year.

    Oddpool renders the table server-side, so this works without browser/CDP and
    survives CME/Investing 403 blocks. We use the Average column for "Exactly 0
    cuts" and convert it to P(at least one cut) = 100 - P(0 cuts).
    """
    if not html:
        return None
    match = re.search(
        r'Exactly\s+0\s+cuts</td>.*?<td[^>]*>.*?</td>.*?<td[^>]*>.*?</td>.*?<td[^>]*>\s*<span[^>]*>([0-9]+(?:\.[0-9]+)?)%</span>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    zero_cut_probability = float(match.group(1))
    cut_probability = round(max(0.0, min(100.0, 100.0 - zero_cut_probability)), 1)
    title_match = re.search(r'Number\s+of\s+Fed\s+Rate\s+Cuts\s+in\s+(20\d{2})', html, re.IGNORECASE)
    year = title_match.group(1) if title_match else datetime.now(timezone.utc).strftime("%Y")
    return {
        "year": year,
        "zero_cut_probability": zero_cut_probability,
        "cut_probability": cut_probability,
    }


def fetch_fed_direction_oddpool_cut_count():
    """Fallback source for year-end Fed cut probability.

    Source: https://www.oddpool.com/fed-rate-cut-count
    This is not CME Fed Funds futures; it is a cross-venue prediction-market
    average (Kalshi/Polymarket where available). Mark source clearly and keep
    confidence medium unless the page is parsed cleanly.
    """
    url = "https://www.oddpool.com/fed-rate-cut-count"
    html = http_get(url, headers={
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Referer": "https://www.oddpool.com/",
    }, timeout=35)
    parsed = parse_oddpool_cut_count_html(html)
    if not parsed:
        return None

    prob = parsed["cut_probability"]
    zero_prob = parsed["zero_cut_probability"]
    year = parsed["year"]
    # 年内至少降息一次的概率不到一半，就是「维持不变为主」：给观望档，不算偏鸽
    direction = "cut2" if prob >= 60 else "cut1" if prob >= 50 else "hold"
    confidence = "medium"
    reasoning = f"Oddpool {year} 年降息次数市场：至少一次降息概率 {prob:.1f}%（Exactly 0 cuts 平均 {zero_prob:.1f}%）；非 CME 期货源，作为 403 fallback"
    log(f"  ✅ 美联储方向(Oddpool cut-count fallback): {direction} ({reasoning})")
    return {
        "fed_direction": direction,
        "reasoning": reasoning,
        "confidence": confidence,
        "source": "oddpool_fed_rate_cut_count",
        "cut_probability": prob,
        "zero_cut_probability": zero_prob,
        "year": year,
    }


def fetch_fed_direction():
    log("抓取美联储预期 (多源)...")

    api_result = fetch_fed_direction_rateprob()
    if api_result and api_result.get("fed_direction"):
        return api_result

    oddpool_result = fetch_fed_direction_oddpool_cut_count()
    if oddpool_result and oddpool_result.get("fed_direction"):
        return oddpool_result

    sources = [
        "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
        "https://www.investing.com/central-banks/fed-rate-monitor",
    ]

    for url in sources:
        html = http_get(url)
        if html and len(html) > 1000:
            result = ask_deepseek(
                """从这个页面中找出当前美联储下次会议的加息/降息/维持不变的市场预期概率。
                基于概率最高的选项判断方向：
                - "cut2" = 市场主要预期降息（概率>50%，降息≥25bps）
                - "cut1" = 市场主要预期轻微降息（年内约一次）
                - "hold" = 市场主要预期维持不变
                - "hike" = 市场主要预期加息
                只有在页面有明确概率数据时才判断，否则返回 {"error": "无数据"}
                返回JSON：{"fed_direction": "cut2|cut1|hold|hike", "reasoning": "百分比数据说明", "confidence": "high|low"}""",
                html,
                max_tokens=200
            )
            if result and result.get('confidence') == 'high' and 'fed_direction' in result:
                log(f"  ✅ 美联储方向: {result['fed_direction']} ({result.get('reasoning','')})")
                return result
            time.sleep(2)

    html = http_get("https://finance.yahoo.com/news/fed-rate-decision/")
    if html:
        result = ask_deepseek(
            """从这篇文章中判断当前美联储利率政策方向：是在降息、维持不变、还是加息？
            返回JSON：{"fed_direction": "cut2|cut1|hold|hike", "reasoning": "简短依据", "confidence": "high|low"}""",
            html
        )
        if result and 'fed_direction' in result:
            log(f"  ✅ 美联储方向(yahoo): {result['fed_direction']}")
            return result

    # Returning "cut1" here invented a market stance out of a network failure,
    # and the page rendered it exactly like a real reading. Say nothing instead;
    # main() will carry the previous value forward and label it.
    log("  ⚠️ 美联储方向所有来源失败，本轮留空（不编造方向）")
    return {"fed_direction": None, "reasoning": "所有数据源获取失败", "confidence": "none"}

# ============================================================
# 4. 资金费率 - Coinglass / Binance API
# ============================================================
def fetch_funding_rate():
    """Fetch BTC perpetual funding rates from public exchange APIs.

    Return an object instead of a single number so the frontend can show Binance
    and OKX separately. Older data.json files may still contain a scalar; the
    page keeps backward compatibility.
    """
    log("抓取资金费率 (Binance + OKX 公开 API)...")
    result = {"bn": None, "okx": None, "avg": None, "source": "exchange_public"}

    # Binance USD-M perpetual: lastFundingRate is decimal per 8h.
    data = http_get("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT")
    if data:
        try:
            d = json.loads(data)
            result["bn"] = round(float(d.get('lastFundingRate', 0)) * 100, 4)
            log(f"  ✅ Binance 资金费率: {result['bn']:.4f}%/8h")
        except Exception as e:
            log(f"  Binance API parse error: {e}")

    # OKX BTC-USDT swap: fundingRate is decimal per funding interval.
    okx_data = http_get("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
    if okx_data:
        try:
            d = json.loads(okx_data)
            rows = d.get('data') or []
            if rows:
                result["okx"] = round(float(rows[0].get('fundingRate', 0)) * 100, 4)
                log(f"  ✅ OKX 资金费率: {result['okx']:.4f}%/8h")
        except Exception as e:
            log(f"  OKX API parse error: {e}")

    vals = [v for v in (result["bn"], result["okx"]) if isinstance(v, (int, float))]
    if vals:
        result["avg"] = round(sum(vals) / len(vals), 4)
        return result

    # Last resort: Coinglass page + AI parser only if a key is configured.
    if DEEPSEEK_KEY:
        html = http_get("https://www.coinglass.com/FundingRate")
        if html:
            parsed = ask_deepseek(
                """这是 Coinglass 资金费率页面。请找出 BTC 在 Binance 和 OKX 的当前资金费率（%/8h）。
                正常范围 -0.1% 到 +0.1%，正数代表多头付空头。
                返回JSON：{"bn": Binance数值, "okx": OKX数值} 或 {"error": "找不到"}""",
                html
            )
            if parsed:
                for k in ("bn", "okx"):
                    if isinstance(parsed.get(k), (int, float)):
                        result[k] = round(float(parsed[k]), 4)
                vals = [v for v in (result["bn"], result["okx"]) if isinstance(v, (int, float))]
                if vals:
                    result["avg"] = round(sum(vals) / len(vals), 4)
                    result["source"] = "coinglass_ai_fallback"
                    return result

    return None

# ============================================================
# 5. 保证金借贷费率 + 未平仓合约 - Binance 公开 API（无需Key）
# ============================================================
def fetch_margin_lending():
    """
    借贷 BTC 做空的成本指标（Margin Borrow Rate）。
    利率异常上涨 → 有机构/大户在大量借BTC准备做空。
    结合 Open Interest 变化判断操纵意图。
    """
    log("抓取借贷费率 + 未平仓合约 (Binance 公开 API)...")

    result = {
        "btc_daily_rate": None,      # VIP0日利率（小数，如 0.00001116）
        "btc_annual_rate": None,     # 年化利率（%，如 0.407）
        "btc_borrow_limit": None,    # VIP0最大借款量（BTC）
        "open_interest": None,       # 合约未平仓总量（BTC）
        "open_interest_usd": None,   # 合约未平仓总量（美元估算）
        "open_interest_source": None,  # 实际取到数的交易所
        "source": "binance_public"
    }

    # 1. 借贷利率（公开，无需签名）
    try:
        url = "https://www.binance.com/bapi/margin/v1/public/margin/vip/spec/list-all"
        data = http_get(url)
        if data:
            d = json.loads(data)
            for item in d.get('data', []):
                if item.get('assetName') == 'BTC':
                    specs = item.get('specs', [])
                    vip0 = next((s for s in specs if s.get('vipLevel') == '0'), None)
                    if vip0:
                        daily = float(vip0.get('dailyInterestRate', 0))
                        annual = round(daily * 365 * 100, 4)  # 转年化%
                        borrow_limit = float(vip0.get('borrowLimit', 0))
                        result['btc_daily_rate'] = daily
                        result['btc_annual_rate'] = annual
                        result['btc_borrow_limit'] = borrow_limit
                        log(f"  ✅ BTC借贷年化利率: {annual}% | VIP0限额: {borrow_limit} BTC")
                    break
    except Exception as e:
        log(f"  ⚠️ 借贷利率抓取失败: {e}")

    # 2. 合约未平仓量（永续合约，公开API）
    try:
        oi_url = "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"
        oi_data = http_get(oi_url)
        if oi_data:
            oi = json.loads(oi_data)
            oi_btc = float(oi.get('openInterest') or 0)
            # A malformed 200 response would otherwise publish 0 and, being
            # non-None, stop the fallback chain below from ever running.
            if oi_btc > 0:
                result['open_interest'] = round(oi_btc, 0)
                result['open_interest_source'] = 'binance_public'
                log(f"  ✅ BTC未平仓合约 (Binance): {oi_btc:,.0f} BTC")
            else:
                log("  ⚠️ Binance 未平仓合约响应缺少有效数值，转兜底源")
    except Exception as e:
        log(f"  ⚠️ 未平仓合约抓取失败: {e}")

    # Binance (451) and Bybit (403) both refuse GitHub runners, so this value
    # was always empty in production. OKX answers there — the funding-rate call
    # above proves it. Each venue is its own market, hence the source label:
    # the numbers are comparable in shape, not identical in size.
    for label, url, extract in (
        ("OKX",
         "https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP",
         lambda p: float((p.get('data') or [{}])[0].get('oiCcy'))),
        ("Bybit",
         "https://api.bybit.com/v5/market/open-interest"
         "?category=linear&symbol=BTCUSDT&intervalTime=5min&limit=1",
         lambda p: float(((p.get('result') or {}).get('list') or [{}])[0]['openInterest'])),
    ):
        if result['open_interest'] is not None:
            break
        try:
            raw = http_get(url)
            if not raw:
                continue
            oi_btc = extract(json.loads(raw))
            if oi_btc > 0:
                result['open_interest'] = round(oi_btc, 0)
                result['open_interest_source'] = f"{label.lower()}_public"
                log(f"  ✅ BTC未平仓合约 ({label} 兜底): {oi_btc:,.0f} BTC")
        except Exception as e:
            log(f"  ⚠️ 未平仓合约 {label} 兜底失败: {e}")

    if result['open_interest'] is None:
        log("  ⚠️ 未平仓合约全部来源失败，本轮为空")

    return result

# ============================================================
# TIPS 实际利率 - FRED API
# ============================================================
def fetch_tips():
    """Fetch 10-year real yield as ``(value, as_of)``.

    Preferred source is FRED when FRED_KEY is configured. Without a key, fall
    back to the official U.S. Treasury real-yield XML feed so the dashboard does
    not keep carrying stale TIPS values forever.

    The observation date travels with the value: this is a business-day series,
    so "yesterday's number" is normal and "six weeks old" is not, and the page
    cannot tell them apart from the value alone.
    """
    log("抓取 10Y TIPS 实际利率 (FRED / Treasury fallback)...")

    if FRED_KEY:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={FRED_KEY}&sort_order=desc&limit=1&file_type=json"
        data = http_get(url)
        if data:
            try:
                d = json.loads(data)
                obs = d.get('observations', [])
                if obs and obs[0].get('value') not in ('.', ''):
                    val = float(obs[0]['value'])
                    log(f"  ✅ TIPS(FRED): {val}% (日期: {obs[0]['date']})")
                    return val, obs[0]['date']
            except Exception as e:
                log(f"  FRED 解析失败: {e}")
    else:
        log("  FRED_KEY 未配置，改用 U.S. Treasury official XML fallback")

    try:
        year = datetime.now(timezone.utc).strftime("%Y")
        url = f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_real_yield_curve&field_tdr_date_value={year}"
        xml_text = http_get(url, headers={"Accept": "application/xml,text/xml,*/*"}, timeout=45)
        if xml_text:
            root = ET.fromstring(xml_text)
            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'm': 'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata',
                'd': 'http://schemas.microsoft.com/ado/2007/08/dataservices',
            }
            latest = None
            for entry in root.findall('atom:entry', ns):
                props = entry.find('atom:content/m:properties', ns)
                if props is None:
                    continue
                date_el = props.find('d:NEW_DATE', ns)
                val_el = props.find('d:TC_10YEAR', ns)
                if val_el is None:
                    val_el = props.find('d:BC_10YEAR', ns)
                if date_el is None or val_el is None:
                    continue
                val_text = (val_el.text or '').strip()
                if not val_text:
                    continue
                latest = ((date_el.text or '')[:10], float(val_text))
            if latest:
                log(f"  ✅ TIPS(Treasury 10Y real yield): {latest[1]}% (日期: {latest[0]})")
                return latest[1], latest[0]
    except Exception as e:
        log(f"  Treasury fallback 解析失败: {e}")

    log("  ⚠️ TIPS 获取失败")
    return None, None

def fetch_stablecoin():
    log("抓取稳定币市值 (DeFiLlama)...")
    url = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
    data = http_get(url)
    if data:
        try:
            d = json.loads(data)
            pegs = d.get('peggedAssets', [])
            total = sum(
                p.get('circulating', {}).get('peggedUSD', 0)
                for p in pegs if p.get('circulating', {}).get('peggedUSD', 0) > 0
            ) / 1e9
            trend = "expand" if total > 250 else "flat" if total > 190 else "shrink"
            log(f"  ✅ 稳定币总市值: ${total:.1f}B → {trend}")
            return {"total_b": round(total, 1), "trend": trend}
        except Exception as e:
            log(f"  解析失败: {e}")
    return None

# ============================================================
# 主流程
# ============================================================
def main(push=False, dry_run=False):
    """Fetch every metric and write data.json.

    Git is opt-in: this script used to commit and push on every run, so simply
    debugging it locally published to production — twice in one afternoon, once
    causing a rebase conflict against the scheduled job. Publishing is now the
    workflow's job unless --push says otherwise.
    """
    log("=" * 55)
    log("BTC Dashboard 数据抓取 v3（含借贷费率+未平仓合约）")
    log(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 55)

    previous_data = load_previous_data()

    # One instant, two renderings. datetime.now() without a timezone follows the
    # machine clock: on the GitHub runner that is UTC, so the "CN" timestamp the
    # page shows was running eight hours behind Beijing.
    now_utc = datetime.now(timezone.utc)

    data = {
        "timestamp": now_utc.isoformat(),
        "timestamp_cn": now_utc.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M"),
        "price": None,
        "etf": None,
        "onchain": {"mvrv_zscore": None, "nupl": None},
        "fed": None,
        "funding_rate": None,
        "margin_lending": None,
        "stablecoin": None,
        "tips": None
    }

    # 按顺序抓取，加间隔避免频率限制
    etf = fetch_farside_etf()
    if etf:
        data["etf"] = etf
    time.sleep(2)

    btc_price = fetch_btc_price()
    if btc_price:
        data["price"] = btc_price
    cm = fetch_coinmetrics_btc()
    if cm:
        onchain = {
            "mvrv_zscore": cm["mvrv_zscore"], "nupl": cm["nupl"],
            "mvrv_zscore_as_of": cm["as_of"], "nupl_as_of": cm["as_of"],
            "mvrv_zscore_source": "coinmetrics", "nupl_source": "coinmetrics",
        }
        if cm["ma200w"]:
            data["ma200w"] = {"value": cm["ma200w"], "as_of": cm["as_of"], "source": "coinmetrics"}
        if cm.get("market"):
            data["market"] = {**cm["market"], "as_of": cm["as_of"], "source": "coinmetrics"}
    else:
        onchain = fetch_lookintobitcoin()
    dominance = fetch_btc_dominance()
    if dominance is not None:
        data.setdefault("market", {})["btc_dominance"] = dominance
    if "ma200w" not in data and isinstance(previous_data.get("ma200w"), dict):
        data["ma200w"] = previous_data["ma200w"]  # 沿用上次，as_of 会如实显示它有多旧
    onchain["mvrv_zscore"] = carry_forward(previous_data, onchain.get("mvrv_zscore"), ["onchain", "mvrv_zscore"], "MVRV Z-Score")
    onchain["nupl"] = carry_forward(previous_data, onchain.get("nupl"), ["onchain", "nupl"], "NUPL")
    mark_onchain_freshness(previous_data, onchain)
    data["onchain"] = onchain
    time.sleep(2)

    fed = fetch_fed_direction()
    prev_fed = (((previous_data or {}).get("fed") or {}))
    fed_usable = bool(fed and fed.get("fed_direction") and fed.get("confidence") != "low")
    if fed_usable:
        fed["as_of"] = now_utc.strftime("%Y-%m-%d")
        fed["age_days"] = 0
        fed["stale"] = False
        data["fed"] = fed
    elif prev_fed.get("fed_direction"):
        age = age_in_days(prev_fed.get("as_of"))
        data["fed"] = {
            **prev_fed,
            "reasoning": f"沿用上一版有效值；本轮抓取失败。上一版依据：{prev_fed.get('reasoning', '')}".strip(),
            # Never inherit the old "high": this reading is no longer current.
            "confidence": "carried_forward",
            "age_days": age,
            "stale": is_stale(age, FED_STALE_AFTER_DAYS),
        }
        shown = f"{age} 天前" if age is not None else "日期未知"
        log(f"  ♻️ 美联储方向本轮抓取失败，沿用上一版有效值: {prev_fed.get('fed_direction')}（{shown}）")
    elif fed:
        data["fed"] = fed
    time.sleep(2)

    fr = fetch_funding_rate()
    if fr is not None:
        data["funding_rate"] = fr
    time.sleep(1)

    # 新增：借贷费率 + 未平仓合约
    ml = fetch_margin_lending()
    data["margin_lending"] = ml
    time.sleep(1)

    stbl = fetch_stablecoin()
    if stbl:
        data["stablecoin"] = stbl

    time.sleep(1)
    tips, tips_as_of = fetch_tips()
    data["tips"] = carry_forward(previous_data, tips, ["tips"], "TIPS 实际利率")
    if tips is None:
        # Carried forward, so its observation date came from the previous run.
        tips_as_of = (previous_data or {}).get("tips_as_of")
    tips_age = age_in_days(tips_as_of)
    data["tips_as_of"] = tips_as_of
    data["tips_age_days"] = tips_age
    data["tips_stale"] = data["tips"] is not None and is_stale(tips_age, TIPS_STALE_AFTER_DAYS)
    if data["tips_stale"]:
        shown = f"{tips_age} 天前" if tips_age is not None else "日期未知"
        log(f"  ⚠️ TIPS 使用陈旧数据（{shown}），页面会标注")

    # 汇总输出
    log("\n" + "=" * 55)
    log("抓取结果汇总:")
    log(f"  ETF 5日净流入:   {data['etf']['sum5d'] if data['etf'] else 'N/A'}M USD")
    log(f"  MVRV Z-Score:    {data['onchain']['mvrv_zscore']}")
    log(f"  NUPL:            {data['onchain']['nupl']}")
    log(f"  美联储方向:      {data['fed']['fed_direction'] if data['fed'] else 'N/A'}")
    log(f"  资金费率:        {data['funding_rate']}%/8h")
    ml = data.get('margin_lending') or {}
    log(f"  BTC借贷年化利率: {ml.get('btc_annual_rate')}%")
    log(f"  BTC未平仓合约:   {ml.get('open_interest')} BTC")
    log(f"  稳定币趋势:      {data['stablecoin']['trend'] if data['stablecoin'] else 'N/A'} ({data['stablecoin']['total_b'] if data['stablecoin'] else 'N/A'}B)")
    log(f"  TIPS 实际利率:   {data['tips']}%")
    log("=" * 55)

    # 写入文件
    # NaN/Infinity are valid Python floats but not valid JSON. The browser's
    # response.json() rejects them, which would blank the whole dashboard, so
    # drop them to null here and let allow_nan=False catch anything missed.
    drop_non_finite(data)

    if dry_run:
        log("\n🔍 --dry-run：未写入文件，以上为本轮抓取结果")
        return data

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
    log(f"\n✅ 数据已写入: {DATA_FILE}")

    if not push:
        log("  未提交也未推送：git 操作需显式 --push；"
            "定时任务里由 workflow 负责提交。")
        return data

    push_data_file(data)
    return data


def push_data_file(data):
    """Commit and push data.json. Opt-in only — see main()'s --push.

    The scheduled workflow does its own commit with rebase-and-retry, so this
    path exists for manual runs. Two owners of the same commit is why it is not
    the default: if this push loses a race, the workflow then sees a clean tree
    and exits without republishing the data.
    """
    log("推送到 GitHub...")
    try:
        os.chdir(REPO_DIR)
        # --only scopes the commit to this one path. Staging alone does not:
        # a plain `git commit` also sweeps in whatever the user had staged.
        result = subprocess.run(
            ["git", "commit", "--only", "-m",
             f"data: auto-update {data['timestamp_cn']}", "--", "data.json"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            subprocess.run(["git", "push"], check=True, capture_output=True)
            log("  ✅ 推送成功")
        elif "nothing to commit" in result.stdout or "no changes added" in result.stdout:
            log("  无变化，跳过 push")
        else:
            # Never fall through to push on an unexplained failure: that reports
            # success while the new data sits uncommitted.
            log(f"  ⚠️ commit 失败({result.returncode})，未推送: "
                f"{(result.stderr or result.stdout).strip()[:200]}")
    except subprocess.CalledProcessError as e:
        log(f"  Git 操作: {e.stderr if e.stderr else str(e)}")


if __name__ == "__main__":
    main(push="--push" in sys.argv, dry_run="--dry-run" in sys.argv)
