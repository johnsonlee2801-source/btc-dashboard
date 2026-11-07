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
  每个数据源要通过品种、成功码和时效校验才算可用（失败只记录固定错误码，不转发上游内容）；合约/现货成交比只用两侧都拿到的同一组交易所；有数据的指标权重不足 70% 时返回“数据不足”、不出分。同一实例 30 秒内复用结果，上游 418/429 的主机按 Retry-After 暂停。

### BGeometrics 免费额度

每 IP 每小时 10 次、每天 15 次；整段序列接口返回近 4 年日度数据，但部分序列（SOPR、MVRV-Z、Puell）比 snapshot 晚约 5 天发布。做法：

- snapshot（1 次调用）每天补最新的 MVRV / Z / SOPR / Puell / 实现价格 / 哈希率；
- 核心序列（STH 成本、STH 盈利占比、全网盈利占比、LTH 30 天净变化、1k–10k BTC 地址余额）每 20 小时刷新；其他每 2–7 天；
- STH-MVRV = 价格 ÷ STH 成本、价格 ÷ LTH 成本由本站自算（与官方值误差 <0.3%），不再单独调用；
- 历史合并保存，失败的运行不会丢数据；遇到 429 立刻停止本轮。

### checkonchain 公开图表

`scripts/checkonchain.py` 每 12 小时读取 6 张 checkonchain 公开图表（CDN 上的静态 Plotly 页面，每张一次请求，带全部日度历史），解析出：MVRV Z-Score 与 Z = −1 对应价格、NUPL、矿工收入 ÷ 估算生产成本、LTH 30 天净变化、各规模实体 30 天净变化（虾米/螃蟹/10–100/100–1k/巨鲸 1k–10k/>10k）、True Mean、LTH 成本。合并进 `data/onchain-history.json`（键名 `cc_*`，2017 年起），当天未收盘的那个点不存。某张图失败或改了曲线名，只记错误，保留已有历史。

这些正是笑苍生等公开抄底看板引用的口径；之前用 BGeometrics 地址口径时，巨鲸 30 天（−701 vs −5,645）、LTH 30 天（−110k vs −204k）、MVRV-Z（0.72 vs −0.45）都对不上。

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

BTC 21 项（2026-11-07 起，与公开的抄底指数同结构）：大底必要 5 项 × 8 分、大底确认 8 项 × 5 分、相对底部 8 项 × 2.5 分。全网盈利占比（<60 / <50）、周线 RSI（<35 / <30）、STH 盈利占比（<30 / <15）、Puell（<0.5 / <0.7）以不同阈值各计一次，规则键见 `scripts/signals.py` 的 `BTC_GROUPS` 与 `ALIASES`。按此模型回算 2026-11-06 = 26.5，与参考图一致。组合信号：价格 < STH 成本 且 距 90 天收盘高点 ≥20%。

价格位置带：参考线 = max(200 日均线, STH 成本)；收盘连续 28 天在线上进入"线上 满28天"，之后需连续 28 天收在线下才退出（滞回，一两天跌破不重置）；低于 200 周均线单独成档。

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
# 每项按观测日期逐条复核（不信任生成时间与 stale 标记）：信号按今天重算是否过期、储备逐交易所逐资产、控盘证据逐代币、ETH 逐字段。
```
