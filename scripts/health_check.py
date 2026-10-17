#!/usr/bin/env python3
"""
全站健康检查：页面是否可用、API 是否返回有效数据、各数据文件是否过期、关键字段是否为空。

每天由 .github/workflows/health-check.yml 运行；任何一项失败就退出码 1，工作流据此开/更新 Issue，
恢复后自动关闭。本地也可直接运行：python3 scripts/health_check.py

以前没有任何监控：定时任务挂了、数据源断了、页面 5xx 都没人知道，只能等用户看到「暂无」。
"""
import json, sys, urllib.request, urllib.error
from datetime import datetime, timezone, date

BTC = "https://btc.flowhunt.net"
UA = {"User-Agent": "flowhunt-health-check/1.0 (+https://btc.flowhunt.net)"}

# 数据允许的最大年龄（小时）。定时任务会被 GitHub 延迟 0.5~4 小时，阈值留了余量。
MAX_AGE_HOURS = {
    "data.json（BTC，每 3 小时）": 12,
    "eth-data.json（每日）": 36,
    "cex-reserves.json（每日）": 60,
}

results = []  # (ok, name, detail)


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


def hours_since(iso):
    """ISO 时间戳或 YYYY-MM-DD 距现在的小时数；解析失败返回 None。"""
    if not iso:
        return None
    try:
        s = str(iso).replace("Z", "+00:00")
        if len(s) == 10:
            dt = datetime.combine(date.fromisoformat(s), datetime.min.time(), tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return None


def check_age(name, iso, limit_hours):
    h = hours_since(iso)
    if h is None:
        return check(name, False, f"无法解析时间 {iso!r}")
    return check(name, h <= limit_hours, f"{h:.1f} 小时前（上限 {limit_hours}）")


def main():
    print("页面")
    for url in (f"{BTC}/", f"{BTC}/eth", f"{BTC}/halving", f"{BTC}/distribution-radar",
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
        failed = (d.get("raw") or {}).get("sourcesFailed") or []
        check("/api/distribution-radar", isinstance(d.get("score"), (int, float)) and len(failed) <= 3,
              f"score {d.get('score')}, 失败源 {failed}")
    except Exception as e:
        check("/api/distribution-radar", False, str(e)[:120])

    print("数据新鲜度与关键字段")
    try:
        _, d = get_json(f"{BTC}/data.json")
        check_age("data.json（BTC，每 3 小时）", d.get("timestamp"), MAX_AGE_HOURS["data.json（BTC，每 3 小时）"])
        oc = d.get("onchain") or {}
        check("data.json: MVRV/NUPL 非陈旧", oc.get("mvrv_zscore") is not None and not oc.get("mvrv_zscore_stale"),
              f"as_of {oc.get('mvrv_zscore_as_of')}, age {oc.get('mvrv_zscore_age_days')} 天")
        check("data.json: Puell/LTH-MVRV 存在且未过期", oc.get("puell") is not None and not oc.get("puell_stale")
              and oc.get("lth_mvrv") is not None and not oc.get("lth_mvrv_stale"),
              f"puell {oc.get('puell')}@{oc.get('puell_as_of')}, lth_mvrv {oc.get('lth_mvrv')}@{oc.get('lth_mvrv_as_of')}")
        check("data.json: DXY / ETF / 美联储 / TIPS 存在",
              isinstance((d.get("dxy") or {}).get("value"), (int, float)) and (d.get("etf") or {}).get("sum5d") is not None
              and (d.get("fed") or {}).get("fed_direction") and d.get("tips") is not None,
              f"dxy {(d.get('dxy') or {}).get('value')}, etf {(d.get('etf') or {}).get('sum5d')}, fed {(d.get('fed') or {}).get('fed_direction')}, tips {d.get('tips')}")
        check("data.json: 200 周均线 / 市场兜底值", isinstance((d.get("ma200w") or {}).get("value"), (int, float))
              and isinstance((d.get("market") or {}).get("ma200d"), (int, float)))
    except Exception as e:
        check("data.json", False, str(e)[:120])

    try:
        _, e = get_json(f"{BTC}/eth-data.json")
        check_age("eth-data.json（每日）", e.get("timestamp"), MAX_AGE_HOURS["eth-data.json（每日）"])
        fields = ("holder_count", "active_addr_7d", "burn_rate_daily", "staked_pct", "stake_conc_top5",
                  "whale_top100_pct", "stablecoin_mcap_b", "stablecoin_change_30d", "burn_issuance_pct")
        missing = [f for f in fields if e.get(f) is None]
        check("eth-data.json: 关键字段非空", not missing, f"缺失 {missing}" if missing else "全部存在")
    except Exception as ex:
        check("eth-data.json", False, str(ex)[:120])

    try:
        _, c = get_json(f"{BTC}/data/cex-reserves.json")
        check_age("cex-reserves.json（每日）", c.get("anchor"), MAX_AGE_HOURS["cex-reserves.json（每日）"])
        n_btc = len((c.get("assets") or {}).get("BTC", {}).get("exchanges") or [])
        stale = [x["name"] for a in (c.get("assets") or {}).values() for x in a.get("exchanges", []) if x.get("stale")]
        check("cex-reserves.json: 交易所数量与新鲜度", n_btc >= 10 and len(stale) <= 2, f"BTC {n_btc} 家，延迟 {stale}")
    except Exception as ex:
        check("cex-reserves.json", False, str(ex)[:120])

    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    # 给工作流写 Issue 正文
    with open("health-report.md", "w", encoding="utf-8") as f:
        f.write(f"健康检查 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}：{len(results) - len(failed)}/{len(results)} 通过\n\n")
        for ok, name, detail in results:
            f.write(f"- {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else "") + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
