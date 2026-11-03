# 资金与持仓雷达

用户于2026-10-31确认设计：BTC／ETH首页突出摘要，`/positioning-radar`显示完整多币种榜单。当前为本地实现，未提交、推送或部署。

## 数据路径

`scripts/build_positioning_radar.py`仅通过无需登录的公开GET读取Binance当前交易中的`COIN / USDT / PERPETUAL`合约。每0.4秒最多安排一个请求，4个工作线程，单请求超时12秒；遇401/403/418/429/451停止继续请求，不换地域或读取密钥。

输入是exchangeInfo、24h合约ticker，以及各合约的1h大户持仓比例、全体账户比例、OI历史和最近两次已结算资金费率。保留精确symbol/baseAsset，不将`1000`等前缀擅自剥离映射为链上资产。输出为`data/positioning-radar.json`。

合约数由exchangeInfo决定；`--limit N`仅用于明确标为部分样本的诊断，不用于正式全市场采集。UI显示采样数量、全市场分母、有效对齐覆盖、源错误。只显示数据覆盖范围内的排名。

## 定义与日期

- 大户：保证金余额前20%用户之持仓占比。全体账户含大户，不能标成互斥的纯散户人群。
- 对峙榜：双方在50%的两侧，OI至少1000万美元；按多头占比差的绝对值排序。拥挤榜/交叉表OI至少300万美元。
- 三个接口更新错位时，从已返回序列中取最新共同有效小时窗口。没有共同窗口则保留各自日期，不参加需要对齐的比较。
- 占比24h变化用百分点；OI变化用百分比，不能叫净流入。必须恰好相隔24h，不能用前一条代替。
- 资金费率为已结算百分比，时间是实际结算时间；间隔由最近两次结算求得，不能一律写8h。有效期为实际间隔+3h（最多27h），其余合约指标3h。
- 集中度、供应类按证据自带的有效期（GoPlus 前10口径 72h，其余 48h）；未来、空值、非有限数都无效。零值有效。
- 失败保留原日期；生成时间从不替代观测时间。`dataStatus`与快照生成是否成功分开：available / partial / unavailable。
- 合约清单或ticker整体失败时，输出明确的失败状态，保留原`universeAsOf`及每项时间。定时任务成功表示有效状态文件已更新，不表示全部数据源健康；退化会产生GitHub警告并在页面显示。格式/代码错误仍应失败。

## 链上与身份边界

**2026-11-03 起接通了自动证据管线**（工作流 `Update positioning evidence`，每天 01:10 UTC）：

1. `scripts/build_exchange_labels.py` → `data/exchange-addresses.json`：Binance 储备证明地址（经新加坡中转）、Bybit 月度储备证明 CSV、DefiLlama 交易所适配器的 `owners`。少于 200 个地址时保留旧地址簿。该文件不部署，只用于归类。
2. `scripts/build_positioning_evidence.py` → `data/positioning-evidence.json`：CoinGecko 把 baseAsset（去掉 `1000`/`1M` 等前缀并记录乘数）映射到市值最高的同名币和合约；原生链币（BTC、ETH、SOL、BNB 等，或平台即自身链的币）跳过；多链代币依次查询 GoPlus，取持有人最多的链（≥1000 人即停）。GoPlus 返回前10持有人、余额、锁仓与 DEX 池；每个地址归类为交易所 / 销毁 / DEX / 跨链桥 / 锁仓 / 未识别合约 / 未识别地址。GoPlus 免费额度约每分钟 20 次：每次运行 38 分钟预算，证据最旧的代币优先，未轮到的保留上次结果。
3. `build_positioning_radar.py` 的 `top10_concentration`：调整后集中度 = 剩余地址余额 ÷ (总供应 − 剔除余额)。只知道前10名，扣除后剩余地址不足10个，所以是**下界**。证据 72 小时有效；流通率取 CoinGecko 流通/总供应。

仍然缺失：解锁计划、做市商关联（无可核验的免费来源），保持“待核验”。原有的“完整账本”证据格式仍兼容（`ledgerComplete`）。

输出`concentrationAudit`保留总供应、总剔除、剩余供应、调整后前10分子、前10地址及至多40条剔除记录与链接。更多记录明确计数，链接到完整原账本。详情显示这些证据；不将百分比当作同一机构控制的证明。

阈值：高集中度≥95%，观察90%≤值<95%；流通率<35%；未来30日解锁>当前流通供应5%；原始前10的未知地址/锁定部分各>50%。未获得解锁信息显示“解锁待核验”，不显示“无解锁”。做市关联须带来源及披露日期，不能解释为当前净买入。

## 页面与运行

`assets/positioning-radar-model.js`是首页与完整页共用的纯排名模型。渲染用DOM文本及HTTPS链接白名单，不插入来源HTML。搜索、观察条件、排序、展开、键盘焦点、表格横向滚动、证据弹窗、返回标签页后重新判断日期均有本地浏览器覆盖。

定时准备文件：`.github/workflows/update-positioning-radar.yml`，每小时UTC第35分钟，25分钟超时；执行离线合同测试后采集并仅提交雷达快照。现有`deploy-vercel.yml`增加对应成功状态更新入口。此配置尚未上线，未运行任何远端工作流。

历史保留最近30天、每日最后一次必要观测摘要，最多31个UTC日期。高集中度新增/退出仅在存在精确24h、同币种同口径有效对比时统计；首日或缺口显示待核验。

本地预览沿用`python3 -B scripts/preview_observatory.py --port 8765`；新增扩展名隐藏路由已同时配置在预览器与Vercel。原有预览进程若在代码修改前启动，需要用新进程查看新路由；本轮不重启既有服务。

## 验证命令

```sh
python3 -B -m unittest discover -s tests -p test_positioning_radar.py -q
node --test tests/positioning-radar.test.cjs
python3 -B -m unittest discover -s tests -q
node --test tests/observatory-model.test.cjs tests/ticker.test.cjs tests/positioning-radar.test.cjs
```

浏览器使用已有Playwright/Chrome运行`tests/qa_positioning_radar.py`、`tests/qa_observatory.py`和`tests/qa_observatory_contract.py`，仅临时回环服务器。测试fixture只在测试环境存在。当前任务验证记录见对应实施计划的Execution ledger。

## 2026-10-31 发布授权

用户明确要求推送、部署并随后进行TDD检测。此授权取代本次实现阶段的本地发布限制。发布从独立工作树进行，保留主目录及重复文件；同步远端数据更新，沿用GitHub Actions唯一部署入口。正式域名、静态资源、数据与自动更新按发布后的实际结果另行验证。
