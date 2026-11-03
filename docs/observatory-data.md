# BTC / ETH 观察台的数据与验证（v2，2026-11）

页面：`index.html`、`eth.html`；共享外壳 `assets/site.css`（全站五个页面共用页头、导航、页脚）；观察台资源 `assets/observatory*`。

## 页面回答什么

每个信号都给出：当前值、触发线、距触发还差多少；与价格同比例变动的指标直接给出触发价（"需跌 X% → $Y"）；以及用同一公开数据算出的历史回测。BTC 另有：组合信号两条进度条、价格位置带、过去一年（及 2022-11 起全部）的观察指数走势、按价格排序的"价格阶梯"。

措辞只描述观察状态（无底部信号 / 进入关注区 / 低位信号增强 / 历史低位信号集中），不给操作指令；`tests/test_conservative_wording.py` 禁止"定投、加仓、抄底"等词。

## 数据管线

| 文件 | 生成 | 频率 |
| --- | --- | --- |
| `data/observatory.json`（schema v2） | `scripts/build_observatory.py` | 每 6 小时（Update BTC and ETH observatory） |
| `data/onchain-history.json` | 同上，经 `scripts/onchain_store.py` | 每次最多 8 次 BGeometrics 调用，按优先级增量刷新 |
| `data/halving-cycles.json` | `scripts/build_halving.py` | 同上工作流，失败不阻塞 |
| `data/positioning-radar.json`、`data/positioning-summary.json` | `scripts/build_positioning_radar.py` | 每小时 |
| `data/spot-flow.json` | `scripts/build_spot_flow.py`（Binance 现货 aggTrades 公开日数据，SHA-256 校验） | 随观察台工作流，只补新的 UTC 日，保留 30 天 |
| `data/positioning-evidence.json`、`data/exchange-addresses.json` | `scripts/build_positioning_evidence.py`、`scripts/build_exchange_labels.py` | 每天（Update positioning evidence），见 `positioning-radar-data.md` |

**已停用**：旧的 `data.json` 管线（`Update BTC dashboard data`，含 DeepSeek/FRED 调用）于 2026-11-03 停掉定时任务，只保留手动触发；页面不再读取，`data.json` 也不再部署。

现货资金流按单笔聚合成交金额分档（<1万、1–10万、10–100万、>100万 USDT），净额 = 主动买入 − 主动卖出。一个吃掉多个价位的大单会被拆成多条聚合成交，所以大单金额是保守值，>100万档通常接近 0。

### Binance 合约数据为什么要中转

`fapi.binance.com` 对美国 IP 返回 HTTP 451，GitHub Actions 的 runner 都在美国，所以资金雷达曾长期 0/519、观察台的资金费率和多空比一直缺失，而工作流仍显示成功。现在：

- `api/binance-futures.js` 是固定在新加坡（`regions: ['sin1']`）的 Edge 函数，只转发白名单内的公开行情 GET 端点，按批次（每次 ≤120 个请求）返回；
- `scripts/binance_futures.py` 在设置了 `BINANCE_PROXY_URL` 时走中转，否则直连（本地开发）；
- `api/distribution-radar.js` 也固定到新加坡，避免美国访客访问时同样失败。

### BGeometrics 免费额度

每 IP 每小时 10 次、每天 15 次；整段序列接口返回近 4 年日度数据，但部分序列（SOPR、MVRV-Z、Puell）比 snapshot 晚约 5 天发布。做法：

- snapshot（1 次调用）每天补最新的 MVRV / Z / SOPR / Puell / 实现价格 / 哈希率；
- 核心序列（STH 成本、STH 盈利占比、全网盈利占比、LTH 30 天净变化、1k–10k BTC 地址余额）每 20 小时刷新；其他每 2–7 天；
- STH-MVRV = 价格 ÷ STH 成本、价格 ÷ LTH 成本由本站自算（与官方值误差 <0.3%），不再单独调用；
- 历史合并保存，失败的运行不会丢数据；遇到 429 立刻停止本轮。

### 其他来源

| 数据 | 来源 |
| --- | --- |
| 日线、200 日 / 200 周均线、周 RSI、90 天高点、Pi Cycle 底部 | Binance 现货日线（2017 年起，4 页 × 1000 根） |
| 恐慌贪婪指数 | Alternative.me（全历史）、CoinMarketCap 公开图表接口 |
| 资金费率、全体账户多空人数比、大户持仓多空比 | Binance Futures（经新加坡中转；最新值用小时线，30 天前对比用日线） |
| DVOL、25Δ 风险逆转 | Deribit；RR25 由期权标记 IV 按 Black-Scholes 远期 delta 计算，插值到 30 天 |
| ETF 净流量 | Farside（当天美股收盘前的不完整行会被丢弃） |
| ETH 质押、销毁、地址、稳定币 | 原有 `scripts/fetch_eth_data.py` 管线（`eth-data.json`），作为"链上事实"展示，不计入信号 |
| 减半周期 | Coin Metrics 社区接口日收盘价（2012 年起） |

## 规则

BTC 16 项，每项只出现一次：大底必要 5 项（共 40）、大底确认 6 项（共 40）、相对底部 5 项（共 20）。阈值见 `scripts/signals.py` 的 `BTC_GROUPS`。组合信号：价格 < STH 成本 且 距 90 天收盘高点 ≥20%。

ETH 6 项低位条件（周线 RSI、Mayer、价/200 周线、90 天回撤、Pi Cycle 底部、ETH MVRV），只计数不打分。

缺失或过期的输入不点亮信号，指数按 0 计并单独标注"最多还可能 +X"。前端按访问时的日期重新判断时效（`assets/observatory-model.js`）。

## 回测口径

- 亮起天数、段数（间隔 >7 天算新的一段）；
- 亮起后 90 天价格变化的中位数与上涨占比；
- "3 个月低点"= 前后各 45 天内最低收盘；低点 ±7 天内亮过即算覆盖。

价格类信号样本从 2017 年起；链上类从 2022-11 起（BGeometrics 免费历史），只覆盖一轮熊转牛，页面上注明。

## 验证

```
python3 -B -m unittest discover -s tests -p 'test_*.py'
node --test tests/observatory-model.test.cjs tests/ticker.test.cjs tests/positioning-radar.test.cjs
python3 scripts/health_check.py   # 线上：页面、API、数据新鲜度，以及"有效信号数""合约数据是否经中转拿到""资金雷达覆盖率"
```
