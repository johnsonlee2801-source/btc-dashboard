#!/usr/bin/env python3
"""
全站健康检查：页面是否可用、API 是否返回有效数据、各数据文件是否过期、关键字段是否为空。

每天由 .github/workflows/health-check.yml 运行；任何一项失败就退出码 1，工作流据此开/更新 Issue，
恢复后自动关闭。本地也可直接运行：python3 scripts/health_check.py

以前没有任何监控：定时任务挂了、数据源断了、页面 5xx 都没人知道，只能等用户看到「暂无」。
"""
import json, math, sys, urllib.request, urllib.error
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The monitor judges evidence with the consumer's own rule, so the two cannot drift apart.
from build_positioning_radar import MIN_HOLDERS, top10_concentration  # noqa: E402

BTC = "https://btc.flowhunt.net"
UA = {"User-Agent": "flowhunt-health-check/1.0 (+https://btc.flowhunt.net)"}

# 数据允许的最大年龄（小时）。定时任务会被 GitHub 延迟 0.5~4 小时，阈值留了余量。
MAX_AGE_HOURS = {
    "eth-data.json（每日）": 36,
    "cex-reserves.json（每日）": 60,
}
HALVINGS = ["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20"]
FLOW_BUCKETS = ("lt10k", "10k_100k", "100k_1m", "gt1m")

results = []  # (ok, name, detail)


def now_utc():
    return datetime.now(timezone.utc)


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))
    print(("  ✅ " if ok else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    return ok


def get(url, timeout=45):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def get_json(url):
    status, body = get(url)
    return status, json.loads(body)


def real(v):
    """A finite JSON number (bool excluded: it is an int subclass; Infinity parses in Python)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def hours_since(iso):
    """ISO 时间戳、YYYY-MM-DD 或毫秒时间戳距现在的小时数；解析失败返回 None。"""
    if iso is None or iso == "" or isinstance(iso, bool):
        return None
    try:
        if isinstance(iso, (int, float)):
            if not math.isfinite(iso):
                return None
            return (now_utc().timestamp() * 1000 - iso) / 3600000
        s = str(iso).replace("Z", "+00:00")
        if len(s) == 10:
            dt = datetime.combine(date.fromisoformat(s), datetime.min.time(), tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return (now_utc() - dt).total_seconds() / 3600
    except Exception:
        return None


def within(iso, limit_hours):
    """Observed, not from the future, and no older than the limit. Age 0 is fresh."""
    h = hours_since(iso)
    return h is not None and 0 <= h <= limit_hours


def check_age(name, iso, limit_hours):
    h = hours_since(iso)
    if h is None:
        return check(name, False, f"无法解析时间 {iso!r}")
    return check(name, 0 <= h <= limit_hours, f"{h:.1f} 小时前（上限 {limit_hours}）")


def signal_fresh(item):
    """Same rule as the browser (assets/observatory-model.js itemFresh): a finite value whose
    calendar day is 0..maxAgeDays before today's UTC date."""
    if not real(item.get("value")) or not isinstance(item.get("asOf"), str):
        return False
    try:
        day = date.fromisoformat(item["asOf"][:10])
    except ValueError:
        return False
    budget = item.get("maxAgeDays", 3)
    return real(budget) and 0 <= (now_utc().date() - day).days <= budget


def flow_day_ok(day):
    """Every bucket present with finite non-negative flows and a consistent net."""
    buckets = day.get("buckets") if isinstance(day, dict) else None
    if not isinstance(buckets, dict) or set(buckets) != set(FLOW_BUCKETS) or not real(day.get("net")):
        return False
    total, trades = 0.0, 0
    for b in buckets.values():
        if not (isinstance(b, dict) and all(real(b.get(k)) for k in ("buy", "sell", "net"))
                and isinstance(b.get("trades"), int) and not isinstance(b.get("trades"), bool)
                and b["buy"] >= 0 and b["sell"] >= 0 and b["trades"] >= 0
                and abs(b["buy"] - b["sell"] - b["net"]) <= 1):
            return False
        total += b["net"]; trades += b["trades"]
    return trades > 0 and abs(total - day["net"]) <= 4


def is_day(s):
    try:
        return isinstance(s, str) and len(s) == 10 and date.fromisoformat(s).isoformat() == s
    except ValueError:
        return False


def pair(v, lo, hi):
    return isinstance(v, list) and len(v) == 2 and all(real(x) and lo <= x <= hi for x in v)


def halving_ok(h):
    """Everything halving.html renders: windows, every cycle's peak and low, and its curve."""
    cycles, w = h.get("cycles"), h.get("windows") or {}
    if not isinstance(cycles, list) or [c.get("halving") for c in cycles if isinstance(c, dict)] != HALVINGS:
        return False, f"周期 {[c.get('halving') for c in cycles or [] if isinstance(c, dict)]}"
    if not (is_day(h.get("nextHalvingEstimate")) and pair(w.get("peakDays"), 0, 2000)
            and pair(w.get("lowDays"), 0, 2000) and pair(w.get("drawdownPct"), -100, 0)):
        return False, "窗口字段不完整"
    pos = lambda v: real(v) and v > 0
    for i, c in enumerate(cycles):
        peak, low = c.get("peak"), c.get("lowAfterPeak")
        curve = c.get("curve")
        # Completed cycles must carry their post-peak low; only the running cycle may lack one.
        low_ok = (isinstance(low, dict) and pos(low.get("close")) and real(low.get("day"))
                  and real(low.get("drawdownPct")) and is_day(low.get("date")))
        if not (pos(c.get("halvingClose")) and pos(c.get("lastClose")) and is_day(c.get("lastDate"))
                and isinstance(peak, dict) and pos(peak.get("close")) and real(peak.get("day"))
                and pos(peak.get("multiple")) and is_day(peak.get("date"))
                and (low_ok or (low is None and i == len(cycles) - 1))
                and isinstance(curve, list) and curve
                and all(isinstance(p, list) and len(p) == 2 and real(p[0]) and real(p[1]) and p[1] > 0 for p in curve)):
            return False, f"{c.get('halving')} 周期字段不完整"
    last = cycles[-1].get("lastDate")
    return within(last, 96), f"当前周期最后日期 {last}"


def main(report_path="health-report.md"):
    results.clear()
    print("页面")
    for url in (f"{BTC}/", f"{BTC}/eth", f"{BTC}/halving", f"{BTC}/distribution-radar", f"{BTC}/positioning-radar",
                f"{BTC}/og-image.jpg"):
        try:
            status, body = get(url)
            check(url, status == 200 and len(body) > 500, f"HTTP {status}, {len(body)} B")
        except Exception as e:
            check(url, False, str(e)[:120])

    print("API")
    try:
        _, t = get_json(f"{BTC}/api/ticker?symbol=BTC")
        check("/api/ticker BTC", isinstance(t.get("price"), (int, float)) and t["price"] > 1000, f"{t.get('price')} via {t.get('source')}")
    except Exception as e:
        check("/api/ticker BTC", False, str(e)[:120])
    try:
        _, d = get_json(f"{BTC}/api/distribution-radar")
        raw = d.get("raw") or {}
        failed = raw.get("sourcesFailed")
        # Missing failure metadata is not "no failures": fail closed.
        check("/api/distribution-radar", real(d.get("score")) and isinstance(failed, list) and len(failed) <= 3
              and real(d.get("coverage")) and d["coverage"] >= 70,
              f"score {d.get('score')}, 覆盖 {d.get('coverage')}%, 失败源 {[f.get('key') for f in failed or [] if isinstance(f, dict)] if isinstance(failed, list) else '未提供'}")
    except Exception as e:
        check("/api/distribution-radar", False, str(e)[:120])

    print("数据新鲜度与关键字段")
    try:
        _, snapshot = get_json(f"{BTC}/data/observatory.json")
        check_age("BTC/ETH 研究快照（每 6 小时）", snapshot.get("generatedAt"), 18)
        check("研究快照: schema v2", snapshot.get("schemaVersion") == 2, f"schemaVersion {snapshot.get('schemaVersion')}")
        for symbol, minimum in (("BTC", 12), ("ETH", 4)):
            a = (snapshot.get("assets") or {}).get(symbol) or {}
            p = (a.get("metrics") or {}).get("price") or {}
            value = p.get("value")
            check(f"研究快照: {symbol} 日收盘有效", real(value) and value > 0 and within(p.get("asOf"), 72),
                  f"as_of {p.get('asOf')}")
            # Re-judge every signal against today, as the page does: a carried snapshot keeps old
            # triggered states that the browser would hide.
            items = [i for g in a.get("groups") or [] for i in g.get("items") or [] if isinstance(i, dict)]
            known = sum(1 for i in items if signal_fresh(i))
            check(f"研究快照: {symbol} 有效信号 ≥{minimum}", known >= minimum, f"{known}/{len(items)} 项有新鲜数据")
            deriv = a.get("derivatives") or {}
            fresh = [k for k in ("funding", "long_short", "top_position", "dvol", "rr25")
                     if isinstance(deriv.get(k), dict) and not deriv[k].get("carriedForward")
                     and real(deriv[k].get("value")) and within(deriv[k].get("asOf"), 12)]
            check(f"研究快照: {symbol} 合约/期权数据（经新加坡中转）", len(fresh) >= 4, f"新鲜: {fresh}")
    except Exception as ex:
        check("BTC/ETH 研究快照", False, str(ex)[:120])

    try:
        _, store = get_json(f"{BTC}/data/onchain-history.json")
        series = store.get("series") or {}

        def latest_ok(k):
            obs = series.get(k)
            if not isinstance(obs, dict) or not obs:
                return False
            day = max(obs)
            return real(obs[day]) and within(day, 24 * 6)
        stale = [k for k in ("sth_cost", "supply_profit", "sth_profit", "lth_net30", "whale_1k_10k") if not latest_ok(k)]
        check("链上历史库: 核心序列 6 天内有更新", not stale, f"滞后或缺失: {stale}" if stale else "全部正常")
    except Exception as ex:
        check("链上历史库", False, str(ex)[:120])

    try:
        _, radar = get_json(f"{BTC}/data/positioning-summary.json")
        h = hours_since(radar.get("generatedAt"))
        check("资金雷达摘要: 3 小时内更新", within(radar.get("generatedAt"), 3),
              f"{'?' if h is None else f'{h:.1f}'} 小时前，状态 {radar.get('dataStatus')}")
        valid, majors = radar.get("valid"), radar.get("majors") or {}

        def major_ok(sym):
            m = majors.get(sym)
            return (isinstance(m, dict) and all(real(m.get(k)) for k in ("topLong", "accountLong", "oiUsd"))
                    and 0 <= m["topLong"] <= 1 and 0 <= m["accountLong"] <= 1 and within(m.get("asOf"), 3))
        # Count rows that are still within three hours NOW, not at generation time.
        by_hour = radar.get("validByAsOf")
        fresh_now = sum(n for t, n in by_hour.items() if isinstance(n, int) and t.isdigit() and within(int(t), 3)) \
            if isinstance(by_hour, dict) else 0
        valid = fresh_now
        check("资金雷达: 有效覆盖", radar.get("dataStatus") in ("available", "partial")
              and fresh_now >= 300 and within(radar.get("generatedAt"), 3)
              and major_ok("BTCUSDT") and major_ok("ETHUSDT"),
              f"当前仍新鲜 {valid}/{radar.get('universeTotal')}（生成时有效 {radar.get('valid')}，尝试 {radar.get('sampled')}），BTC/ETH {sorted(majors)}")
    except Exception as ex:
        check("资金雷达摘要", False, str(ex)[:120])

    try:
        _, halving = get_json(f"{BTC}/data/halving-cycles.json")
        check_age("减半周期数据（每日）", halving.get("generatedAt"), 48)
        ok, detail = halving_ok(halving)
        check("减半周期数据: 四个周期完整、当前周期在更新", ok, detail)
    except Exception as ex:
        check("减半周期数据", False, str(ex)[:120])

    # data.json (the pre-v2 pipeline) was retired on 2026-11-03; nothing reads it any more.
    try:
        _, flow = get_json(f"{BTC}/data/spot-flow.json")
        latest = {}
        for sym in ("BTC", "ETH"):
            days = ((flow.get("assets") or {}).get(sym) or {}).get("days") or []
            day = days[-1] if days and isinstance(days[-1], dict) else {}
            latest[sym] = day.get("date") if within(day.get("date"), 60) and flow_day_ok(day) else None
        check("现货分档资金流: 最近交易日完整", all(latest.values()), f"最新有效 {latest}")
    except Exception as e:
        check("现货分档资金流", False, str(e)[:120])

    try:
        _, ev = get_json(f"{BTC}/data/positioning-evidence.json")
        assets = ev.get("assets") or {}
        # Retained entries from earlier runs do not count: each needs its own recent observation,
        # and the same holder evidence the page requires (build_positioning_radar MIN_HOLDERS).
        def usable(x):
            if not (isinstance(x, dict) and within(x.get("asOf"), 48) and isinstance(x.get("holders"), list)
                    and isinstance(x.get("holderCount"), int) and x["holderCount"] >= MIN_HOLDERS):
                return False
            try:
                return top10_concentration(x["holders"], x.get("total")) is not None
            except (AttributeError, TypeError):
                return False
        current = sum(1 for x in assets.values() if usable(x))
        check("控盘证据: 48 小时内观测 ≥150 个代币", current >= 150,
              f"{current}/{len(assets)} 个在有效期内，失败 {len(ev.get('errors') or [])}")
    except Exception as e:
        check("控盘证据", False, str(e)[:120])

    try:
        _, e = get_json(f"{BTC}/eth-data.json")
        check_age("eth-data.json（每日）", e.get("timestamp"), MAX_AGE_HOURS["eth-data.json（每日）"])
        fields = ("holder_count", "active_addr_7d", "burn_rate_daily", "staked_pct", "stake_conc_top5",
                  "whale_top100_pct", "stablecoin_mcap_b", "stablecoin_change_30d", "burn_issuance_pct")
        as_of = e.get("as_of") or {}
        # Field dates are calendar days. A field that was not refreshed by the run is "carried":
        # its date then lags the run's own date by more than the one day the slowest source
        # (holder counts, published for the previous day) needs. The run itself must be within
        # 36h (checked above). burn_issuance_pct is derived from the burn rate and from issuance
        # (which uses total_staked), so it carries both dates.
        run = hours_since(e.get("timestamp"))
        run_day = (now_utc() - timedelta(hours=run)).date() if run is not None else None

        def current(d):
            return is_day(d) and run_day is not None and 0 <= (run_day - date.fromisoformat(d)).days <= 1

        deps = {f: [f] for f in fields}
        deps["burn_issuance_pct"] = ["burn_rate_daily", "total_staked"]
        bad = [f for f in fields if not real(e.get(f)) or not all(current(as_of.get(d)) for d in deps[f])]
        check("eth-data.json: 关键字段有值且未沿用旧值", not bad, f"缺失或过期 {bad}" if bad else "全部正常")
    except Exception as ex:
        check("eth-data.json", False, str(ex)[:120])

    try:
        _, c = get_json(f"{BTC}/data/cex-reserves.json")
        check_age("cex-reserves.json（每日）", c.get("anchor"), MAX_AGE_HOURS["cex-reserves.json（每日）"])
        limit = MAX_AGE_HOURS["cex-reserves.json（每日）"]
        for sym, minimum in (("BTC", 10), ("ETH", 8)):
            rows = ((c.get("assets") or {}).get(sym) or {}).get("exchanges") or []
            fresh = [x for x in rows if isinstance(x, dict) and real(x.get("latest")) and within(x.get("asOf"), limit)]
            late = [x.get("name") for x in rows if isinstance(x, dict) and x not in fresh]
            check(f"cex-reserves.json: {sym} 交易所各自新鲜", len(fresh) >= minimum and len(late) <= 2,
                  f"{len(fresh)}/{len(rows)} 家新鲜，延迟或无效 {late}")
    except Exception as ex:
        check("cex-reserves.json", False, str(ex)[:120])

    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    # 给工作流写 Issue 正文
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"健康检查 {now_utc().strftime('%Y-%m-%d %H:%M UTC')}：{len(results) - len(failed)}/{len(results)} 通过\n\n")
        for ok, name, detail in results:
            f.write(f"- {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else "") + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
