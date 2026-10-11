#!/usr/bin/env python3
"""
ETH 链上观察 - 数据抓取脚本
抓取以太坊链上数据，写入 eth-data.json
每日运行一次

数据源（全免费）：
- CoinGecko API: ETH 价格、供应量
- Coin Metrics community API: 持币地址数（余额 > 0）、日活跃地址
- Etherscan 公开页面: 前 100 地址持仓占比
- 以太坊公共节点 (publicnode): 最近 24 小时基础费销毁量
- DefiLlama: 以太坊链上稳定币市值
- 交易所 ETH 存量与 7 日净流量不在这里抓：页面直接读 data/cex-reserves.json，
  和首页「交易所 BTC / ETH 存量」用同一份数据

原则：抓不到就写 null，页面显示「暂无数据」，并把该项移出评分。
以前抓取失败会回退到写死的「估计值」（地址数 17.8 亿、质押集中度 58%、长期持有 62%、
整张持仓分层表、5 家交易所储备……），每天原样发布，看起来像实时数据，还参与了评分。
质押占比、质押集中度、长期持有占比、持仓分层这几项目前没有可用的免费来源，固定为 null。
"""

import json, urllib.request, urllib.error, time, os, re
from datetime import datetime, timezone, timedelta, date

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(REPO_DIR, "eth-data.json")
ETH_RPC = "https://ethereum-rpc.publicnode.com"
# 抓取失败时，上次的值在这么多天内仍可沿用（页面会显示数据日期）
CARRY_FORWARD_DAYS = 3


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def http_get(url, headers=None, timeout=20):
    h = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        log(f"  fetch error {url[:80]}: {e}")
        return None


def safe_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def rpc(method, params, timeout=20):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(ETH_RPC, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("result")
    except Exception as e:
        log(f"  rpc error {method}: {e}")
        return None


# ============================================================
# 1. ETH 基础数据 - CoinGecko
# ============================================================
def fetch_coingecko():
    log("抓取 CoinGecko ETH 基础数据...")
    url = "https://api.coingecko.com/api/v3/coins/ethereum?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false"
    d = safe_json(http_get(url))
    if not d:
        return {}

    md = d.get('market_data', {})
    result = {
        'price_usd': md.get('current_price', {}).get('usd'),
        'price_change_24h': md.get('price_change_percentage_24h'),
        'market_cap': md.get('market_cap', {}).get('usd'),
        'circulating_supply': md.get('circulating_supply'),
    }
    log(f"  ✅ 价格: ${result['price_usd']}, 供应: {result['circulating_supply']}")
    return result


# ============================================================
# 2. 地址数据 - Coin Metrics community
# ============================================================
def fetch_coinmetrics_addresses():
    """持币地址数（余额 > 0 的地址，AdrBalCnt）与近 7 日平均日活跃地址（AdrActCnt）。"""
    log("抓取地址数据 (Coin Metrics)...")
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
           "?assets=eth&metrics=AdrBalCnt,AdrActCnt&frequency=1d&page_size=7&paging_from=end")
    d = safe_json(http_get(url, timeout=30))
    rows = (d or {}).get("data") or []
    if not rows:
        return {}
    out = {"as_of": rows[-1]["time"][:10]}
    try:
        out["holder_count"] = int(float(rows[-1]["AdrBalCnt"]))
    except (KeyError, TypeError, ValueError):
        pass
    active = []
    for r in rows:
        try:
            active.append(float(r["AdrActCnt"]))
        except (KeyError, TypeError, ValueError):
            pass
    if active:
        out["active_addr_7d"] = round(sum(active) / len(active))
    log(f"  ✅ 持币地址 {out.get('holder_count')} / 7日均活跃 {out.get('active_addr_7d')} (数据日期: {out['as_of']})")
    return out


# ============================================================
# 3. Top 100 地址持仓占比 - Etherscan 公开页面
# ============================================================
# 这些地址的余额不是「某个持有者的仓位」：质押存款合约记录的是历年累计存款（单独就占供应的
# 七成以上），WETH 是代币合约，跨链桥里是 L2 用户的钱。算进去前 100 地址占比会高达 90%+，毫无意义
NON_HOLDER_PATTERNS = re.compile(r"Beacon Deposit|Wrapped Ether|Bridge|Portal", re.I)


def parse_top_accounts(html):
    """Etherscan 前 100 地址页 -> [(名称标签, 占比%)]。"""
    out = []
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        cells = [" ".join(re.sub(r"<[^>]+>", " ", c).split()) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        pct = next((c for c in cells if re.fullmatch(r"\d+\.\d+%", c)), None)
        if pct:
            out.append((cells[2] if len(cells) > 2 else "", float(pct[:-1])))
    return out


def fetch_whale_concentration():
    """前 100 地址中，剔除非持有者合约后的持仓占比。"""
    log("抓取鲸鱼地址集中度 (Etherscan)...")
    html = http_get("https://etherscan.io/accounts/1?ps=100")
    accounts = parse_top_accounts(html) if html else []
    if len(accounts) < 100:
        log(f"  ⚠️ 页面解析失败（只找到 {len(accounts)} 行），本项置空")
        return None
    holders = [pct for name, pct in accounts[:100] if not NON_HOLDER_PATTERNS.search(name)]
    total_pct = round(sum(holders), 2)
    log(f"  ✅ 前100地址占比（剔除 {100 - len(holders)} 个非持有者合约）: {total_pct}%")
    return total_pct


# ============================================================
# 4. ETH 销毁速率 - 公共节点 eth_feeHistory
# ============================================================
def fetch_burn_rate(blocks=7200, chunk=1024):
    """最近约 24 小时（7200 个区块）的基础费销毁量。

    每个区块销毁 = baseFeePerGas × gasUsed，gasUsed = gasUsedRatio × gasLimit。
    gasLimit 取最新区块的值（一天内基本不变）。不含 blob 费用的销毁，那部分量级很小。
    """
    log("计算 ETH 销毁速率 (公共节点 eth_feeHistory)...")
    latest = rpc("eth_getBlockByNumber", ["latest", False])
    if not latest:
        return None
    gas_limit = int(latest["gasLimit"], 16)
    newest = int(latest["number"], 16)
    burned_wei, counted = 0, 0
    while counted < blocks:
        n = min(chunk, blocks - counted)
        h = rpc("eth_feeHistory", [hex(n), hex(newest - counted), []])
        if not h or not h.get("gasUsedRatio"):
            log("  ⚠️ eth_feeHistory 中途失败，本项置空")
            return None
        # baseFeePerGas 比 gasUsedRatio 多一项（下一个区块的预估），按区块一一对应
        for base_fee, ratio in zip(h["baseFeePerGas"], h["gasUsedRatio"]):
            burned_wei += int(base_fee, 16) * ratio * gas_limit
        counted += len(h["gasUsedRatio"])
        time.sleep(0.3)
    daily = burned_wei / 1e18 * (7200 / counted)
    log(f"  ✅ 最近 {counted} 个区块销毁约 {daily:,.1f} ETH/天")
    return round(daily, 1)


# ============================================================
# 5. 稳定币市值 - DefiLlama
# ============================================================
def fetch_stablecoin_mcap():
    log("抓取 ETH 链上稳定币市值 (DefiLlama)...")
    d = safe_json(http_get("https://stablecoins.llama.fi/stablecoins?includePrices=false"))
    if not d:
        return None
    total = 0
    for sc in d.get('peggedAssets', []):
        eth_data = (sc.get('chainCirculating') or {}).get('Ethereum', {})
        total += eth_data.get('current', {}).get('peggedUSD', 0)
    total_b = total / 1e9
    log(f"  ✅ ETH链稳定币: ${total_b:.1f}B")
    return total_b


# ============================================================
# 沿用旧值
# ============================================================
def load_previous():
    try:
        with open(DATA_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def carry_forward(previous, field, today):
    """抓取失败时沿用上次的值，前提是它有日期且不超过 CARRY_FORWARD_DAYS 天。返回 (值, 日期)。"""
    value, as_of = previous.get(field), (previous.get("as_of") or {}).get(field)
    if value is None or not as_of:
        return None, None
    try:
        age = (today - date.fromisoformat(as_of)).days
    except ValueError:
        return None, None
    if age > CARRY_FORWARD_DAYS:
        return None, None
    log(f"  ↺ {field} 沿用 {as_of} 的值")
    return value, as_of


# ============================================================
# MAIN
# ============================================================
def main():
    log("=" * 60)
    log("ETH 链上数据抓取开始")

    previous = load_previous()
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    timestamp_cn = (now_utc + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M GMT+8')

    result = {
        'timestamp': now_utc.isoformat(),
        'timestamp_cn': timestamp_cn,
    }
    as_of = {}

    cg = fetch_coingecko()
    result['price_usd'] = cg.get('price_usd')
    result['price_change_24h'] = cg.get('price_change_24h')
    result['market_cap'] = cg.get('market_cap')
    result['circulating_supply'] = cg.get('circulating_supply')

    addr = fetch_coinmetrics_addresses()
    result['holder_count'] = addr.get('holder_count')
    result['active_addr_7d'] = addr.get('active_addr_7d')
    for f in ('holder_count', 'active_addr_7d'):
        if result[f] is not None:
            as_of[f] = addr['as_of']

    result['whale_top100_pct'] = fetch_whale_concentration()
    if result['whale_top100_pct'] is not None:
        as_of['whale_top100_pct'] = today.isoformat()

    result['burn_rate_daily'] = fetch_burn_rate()
    if result['burn_rate_daily'] is not None:
        as_of['burn_rate_daily'] = today.isoformat()

    result['stablecoin_mcap_b'] = fetch_stablecoin_mcap()

    for f in ('holder_count', 'active_addr_7d', 'whale_top100_pct', 'burn_rate_daily'):
        if result[f] is None:
            result[f], as_of[f] = carry_forward(previous, f, today)
            if as_of[f] is None:
                del as_of[f]

    # 目前没有免费且可靠的来源：明确置空，页面显示「暂无可靠数据源」，不参与评分
    result['staked_pct'] = None
    result['stake_conc_top5'] = None
    result['lth_pct'] = None
    result['distribution'] = None
    result['as_of'] = as_of

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"✅ 写入 {DATA_FILE}")
    log("=" * 60)
    return result


if __name__ == '__main__':
    main()
