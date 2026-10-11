#!/usr/bin/env python3
"""
CEX 交易所 BTC / ETH 存量 - 数据抓取脚本
抓取各交易所公开储备地址上的 BTC、ETH 存量，生成近两年每周曲线，写入 data/cex-reserves.json
每日运行一次即可（DefiLlama 按天更新）

数据源（免费）：
- DefiLlama CEX Transparency: https://defillama.com/cexs
  按交易所公开的储备钱包地址统计，每家一个 /protocol/<slug> 接口，带逐日分币种存量。

口径说明：
- 只统计交易所自己公布、被 DefiLlama 收录的地址；Coinbase、Kraken 未公开地址，不在其中。
- DefiLlama 把以太坊主网的原生 ETH 记作 WETH，L2 上记作 ETH；BSC 等链上的锚定币不计入，
  否则会和主网上的抵押 ETH 重复计算。
- DefiLlama 补录或移除地址时，存量会在一天内出现台阶。单日变动超过 STEP_THRESHOLD 的标为
  「单日异常变动」：曲线照原样保留并标记，7D/30D/90D 变化量把这些台阶剔除，免得把补录地址
  说成资金流入。这是启发式判断：真实的重大事件（比如 2025-02 Bybit 被盗）也会被标出来，
  所以前端只说「异常」，不断言就是口径调整。小交易所日常 5%~10% 的进出属于正常流动，不标。
"""

import gzip, json, os, sys, time, urllib.request
from datetime import datetime, timezone, timedelta, date

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(REPO_DIR, "data", "cex-reserves.json")
API = "https://api.llama.fi/protocol/{slug}"

# 候选交易所：DefiLlama CEX 分类里 BTC/ETH 储备量靠前的几家
EXCHANGES = [
    ("binance-cex", "Binance"),
    ("okx", "OKX"),
    ("bitfinex", "Bitfinex"),
    ("bybit", "Bybit"),
    ("robinhood", "Robinhood"),
    ("gate", "Gate"),
    ("bitget", "Bitget"),
    ("gemini", "Gemini"),
    ("mexc", "MEXC"),
    ("bitstamp", "Bitstamp"),
    ("htx", "HTX"),
    ("deribit", "Deribit"),
    ("kucoin", "KuCoin"),
    ("crypto-com", "Crypto.com"),
]

# 每个资产：{链: [该链上计入的 token 名]}
ASSET_CHAINS = {
    "BTC": {"Bitcoin": ["BTC"]},
    "ETH": {
        "Ethereum": ["WETH", "ETH"],
        "Arbitrum": ["ETH"], "Base": ["ETH"], "Optimism": ["ETH"],
        "zkSync Era": ["ETH"], "Scroll": ["ETH"], "Linea": ["ETH"],
        "Starknet": ["ETH"], "Manta": ["ETH"], "Blast": ["ETH"],
    },
}
# 存量低于这个数就不展示，避免一堆零头交易所把图表挤满
MIN_HOLDING = {"BTC": 1000, "ETH": 10000}

WEEKS = 104          # 近两年
STEP_THRESHOLD = 0.20  # 单日变动超过 20% 视为异常（多为地址口径调整）
CHANGE_WINDOWS = {"7d": 7, "30d": 30, "90d": 90}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def http_get_json(url, timeout=180, attempts=3):
    # 单家交易所的响应解压后有几十 MB：请求 gzip 压缩，读到一半断开时重试
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    })
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return json.loads(body.decode("utf-8", errors="replace"))
        except Exception as e:
            log(f"  fetch error {url[:80]} (attempt {i + 1}/{attempts}): {e}")
            time.sleep(5 * (i + 1))
    return None


def to_date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).date()


def extract_daily(protocol, asset, field="tokens"):
    """把 protocol JSON 拆成 {date: 存量}，按 ASSET_CHAINS 指定的链和 token 汇总。"""
    out = {}
    chain_tvls = (protocol or {}).get("chainTvls") or {}
    for chain, keys in ASSET_CHAINS[asset].items():
        # 当天往往有两行（日线 + 实时快照），同一条链同一天只取最后一行，不能相加
        per_day = {}
        for row in (chain_tvls.get(chain) or {}).get(field) or []:
            tokens = row.get("tokens") or {}
            per_day[to_date(row["date"])] = sum(float(tokens.get(k) or 0) for k in keys)
        for d, amount in per_day.items():
            out[d] = out.get(d, 0.0) + amount
    return out


def to_series(daily):
    """{date: v} -> 按日期排好序、去掉零值的 [(date, v)]。"""
    return [(d, v) for d, v in sorted(daily.items()) if v > 0]


def detect_steps(series, threshold=STEP_THRESHOLD):
    """单日相对变动超过阈值的日期（多为地址口径调整）。返回 [(date, delta)]。"""
    steps = []
    for (_, prev), (d, cur) in zip(series, series[1:]):
        if prev > 0 and abs(cur - prev) / prev > threshold:
            steps.append((d, cur - prev))
    return steps


def adjusted_series(series, steps):
    """把异常台阶从序列里扣掉（链式拼接），变化量只反映日常流入流出。"""
    step_delta = dict(steps)
    out, offset = [], 0.0
    for d, v in series:
        offset += step_delta.get(d, 0.0)
        out.append((d, v - offset))
    return out


def value_at(series, target):
    """序列中 target 当天或之前最近的一个值；找不到返回 None。"""
    best = None
    for d, v in series:
        if d > target:
            break
        best = v
    return best


def weekly_points(series, anchor, weeks=WEEKS):
    pts = []
    for k in range(weeks, -1, -1):
        d = anchor - timedelta(days=7 * k)
        v = value_at(series, d)
        if v is not None:
            pts.append([d.isoformat(), round(v)])
    return pts


def changes(adjusted, anchor):
    now = value_at(adjusted, anchor)
    out = {}
    for key, days in CHANGE_WINDOWS.items():
        then = value_at(adjusted, anchor - timedelta(days=days))
        out[key] = round(now - then) if now is not None and then is not None else None
    return out


def build_entry(slug, name, protocol, asset, anchor):
    series = to_series(extract_daily(protocol, asset))
    if not series:
        return None
    usd_series = to_series(extract_daily(protocol, asset, field="tokensInUsd"))
    steps = [(d, delta) for d, delta in detect_steps(series) if d >= anchor - timedelta(days=7 * WEEKS)]
    latest_date, latest = series[-1]
    return {
        "slug": slug,
        "name": name,
        "asOf": latest_date.isoformat(),
        "latest": round(latest),
        "latestUsd": round(usd_series[-1][1]) if usd_series else None,
        "change": changes(adjusted_series(series, steps), anchor),
        "weekly": weekly_points(series, anchor),
        "steps": [{"date": d.isoformat(), "delta": round(delta)} for d, delta in steps],
        "stale": False,
    }


def load_previous():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    previous = load_previous()
    prev_by_slug = {
        asset: {e["slug"]: e for e in (previous.get("assets", {}).get(asset, {}).get("exchanges") or [])}
        for asset in ASSET_CHAINS
    }

    protocols = {}
    for slug, name in EXCHANGES:
        log(f"抓取 {name} ({slug})...")
        protocols[slug] = http_get_json(API.format(slug=slug))

    # 统一锚点：所有交易所最新日期中最晚的一天，周线日期在各交易所之间对齐，前端才能直接相加
    latest_dates = [
        to_date(rows[-1]["date"])
        for p in protocols.values() if p
        for rows in [((p.get("chainTvls") or {}).get("Bitcoin") or {}).get("tokens") or []] if rows
    ]
    if not latest_dates:
        log("所有交易所都抓取失败，保留旧文件不动")
        return 1
    anchor = max(latest_dates)

    assets = {}
    for asset in ASSET_CHAINS:
        entries = []
        for slug, name in EXCHANGES:
            protocol = protocols.get(slug)
            entry = build_entry(slug, name, protocol, asset, anchor) if protocol else None
            if entry is None and slug in prev_by_slug[asset]:
                # 抓取失败时沿用上次的数据，并标记为过期
                entry = {**prev_by_slug[asset][slug], "stale": True}
                log(f"  {name} {asset} 抓取失败，沿用 {entry.get('asOf')} 的旧数据")
            if entry and entry["latest"] >= MIN_HOLDING[asset]:
                entries.append(entry)
        entries.sort(key=lambda e: -e["latest"])
        assets[asset] = {"exchanges": entries}
        log(f"{asset}: {len(entries)} 家交易所，合计 {sum(e['latest'] for e in entries):,}")

    out = {
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "anchor": anchor.isoformat(),
        "source": "DefiLlama CEX Transparency",
        "sourceUrl": "https://defillama.com/cexs",
        "stepThreshold": STEP_THRESHOLD,
        "assets": assets,
    }
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DATA_FILE)
    log(f"写入 {DATA_FILE} ({os.path.getsize(DATA_FILE):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
