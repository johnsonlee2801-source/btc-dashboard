# BTC / ETH 观察台的数据与验证

页面：`index.html`、`eth.html`；共享资源：`assets/observatory*`。

## 更新

`python3 -B scripts/build_observatory.py` 使用 Python 标准库生成 `data/observatory.json`。不调用旧脚本的 AI 解析，不需要密钥，不执行 Git 操作。运行失败保留源观测日期，不将重试时间当数据时间；价格不可用时退出非零。

新增工作流 `Update BTC and ETH observatory` 每6小时运行（02:20 / 08:20 / 14:20 / 20:20 UTC），晚于原有 ETH/CEX 数据采集。其成功运行接入已有 `Deploy to Vercel` 发布入口；修改工作流并不表示已经上线。原 ETH、CEX、BTC 数据任务继续维护既有工具的数据。

现价通过 `/api/ticker` 单独获取并约每 30 秒刷新；API 返回 `asOf`。现价失败回退至带日期的完整日收盘，不将日收盘标为实时。价格对为 USDT（Coinbase 为 USD），页面显示实际来源。

## 公开来源

| 数据 | 来源 | 当前实现 |
| --- | --- | --- |
| 完整日线、200日均线、200周均线、周 RSI、90天收盘高点 | [Binance Spot API](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints) | 每币最多两批1000根日线；排除未收盘日线；周线为完整 UTC 周 |
| MVRV / Z-Score / SOPR / Puell / 实现价格、True Mean、LTH成本及部分 STH 指标 | [BGeometrics 公共接口](https://api.bitcoin-data.com/swagger-ui/index.html) | 每日1次快照+6次单指标请求，缓存24小时；部分接口免费值延迟7天，保留实际日期 |
| BTC 恐慌指数 | [Alternative.me](https://alternative.me/crypto/fear-and-greed-index/) | 卡片旁署名并链接；Bitcoin 指数不冒充 ETH 情绪 |
| 合约资金费率、账户多空比 | [Binance Futures](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api) | 带源时间；账户多空比为最新5分钟窗口，仅反映该交易所，非全市场 |
| BTC / ETH DVOL | [Deribit 公共 API](https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data) | 最近完整小时的隐含波动率指数；源失败保留未知 |
| ETH 地址、质押、销毁、稳定币、集中度 | 原有 `scripts/fetch_eth_data.py` 管线 | Coin Metrics / Blockscout / Ethereum 公共节点 / DefiLlama / validatorqueue；沿用逐项 `as_of` |
| BTC / ETH ETF | [Farside Investors](https://farside.co.uk/eth/) 官方 HTML 表格 | 分资产采集；真实交易日柱状图；括号负值、缺报行、空日期表头均有测试；请求失败保留原日期 |

所有请求无需账号、密钥或购买套餐。公共接口可用不保证长期稳定；不绕过登录或付费限制。接口或限额变化时显示缺失，不能静默替换口径。

## 规则

BTC 分三组：必要5项各8分，确认8项各5分，相对8项各2.5分，共100。相对第8项采用用户早期参考图明确给出的90天回撤20%条件；不是原作者未公开模型的精确复刻。阈值详见 `BTC_RULES` 及页面“计算方法”。

分数下界只计有效且满足条件的项；上界加上未知项的潜在分数。缺失/过期不是零分，也不是未触发。同一指标在不同组出现，不代表独立证据。没有完整回测，不展示截图中的命中率、误报率；不生成没有历史源支持的综合指数曲线。

完整 BTC 位置参考线需要同时有效的200周均线与STH成本；不以200日线或LTH成本冒充。缺少完整STH历史时不推断线上连续28日。组合信号由低于STH成本且距90天收盘高点回撤至少20%构成。

ETH 使用自身技术条件与协议事实，不套用BTC分数、矿工信号、STH模型或Bitcoin情绪。协议指标不作买卖打分。销毁量是7200区块基础费估算（不含blob），销毁/增发比中的增发是由质押量估算，详情注明口径与依赖日期。

巨鲸/散户、LTH/STH实体净变化、矿工收入/成本、哈希带及Pi Cycle底部，若没有已核验一致口径，保持缺失。地址不等于实体，储备变化不等于净买入。原作者署名不作为本站品牌使用。

## 本地检查

- Python：`python3 -B -m unittest discover -s tests -q`（路由测试需临时绑定127.0.0.1）。
- JavaScript：`node --test tests/observatory-model.test.cjs tests/ticker.test.cjs`。
- 浏览器：`tests/qa_observatory.py` 使用已有 Playwright，临时本地服务器，验证 BTC/ETH、桌面/移动端、筛选、日期、图表范围、说明弹窗和故障状态。测试行情和故障注入仅在测试上下文内，生产资源不含模拟价格。

本轮只实现和本地验收。未经另行明确授权，不提交、不推送、不生产部署。

本机预览：`python3 -B scripts/preview_observatory.py --port 8765`，访问 `http://127.0.0.1:8765/` 和 `/eth`。仅回环监听，行情走无需密钥的 Binance 公开代理；不修改生产服务。

本轮储备展示使用本仓库已存在的本地 `origin/master` 缓存中 2026-10-29 的公开储备快照，没有 fetch 或合并代码；原文件没有用户未提交修改。

最终本地验收：75项Python测试、14项Node测试、67项浏览器检查全部通过。BTC 22/31、ETH 21/22 个指标记录在有效期内；两个资产均有365天真实完整日线。两资产ETF和DVOL均已接通；CMC、25Δ风险逆转及部分专有实体/矿工模型保留缺失。最终公开采集无请求失败，缺失不等于网络失败。

## 发布授权

2026-10-29，用户在完成预览后明确要求立即推送上线。发布沿用 GitHub Actions `deploy-vercel.yml`；提交改版并同步远端仅涉及数据的更新，随后从干净的临时发布工作区完成验证和推送。初始本地验收阶段的“不提交、不推送、不部署”记录仅适用于当时阶段。生产验收以本次发布工作流和线上 BTC/ETH 页面为准。
