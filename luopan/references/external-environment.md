# 外部环境信号与企业冲击传导

本文件用于把地缘政治、贸易、航运、能源、大宗商品、制裁、基础设施、气候、网络安全、采购与政策变化接入企业研究。外部信号只能说明环境变化，不能绕过企业暴露证据直接生成经营结论。

## 目录

1. 何时启用
2. 四层对象
3. 调查流程
4. World Monitor 适配原则
5. 质量与降级规则
6. 情景推演
7. 行业映射

## 何时启用

至少满足一项时启用：

- 企业跨国采购、生产、销售或融资；
- 依赖能源、矿产、芯片、航运、港口、管道或数据中心；
- 受制裁、关税、出口管制、政府采购或产业政策影响；
- 用户要求未来风险、压力测试、监控或领先指标；
- 行业属于核能源、稀土、矿业、半导体、军工航天、航运、石油天然气、大宗商品或跨境贸易。

本地服务型小企业若没有可证明的外部暴露，不要为了完整强行填充。

## 四层对象

### `source_health[]`

记录数据源组是否可用、何时最后成功、新鲜度预算、覆盖范围与回退状态。`unavailable`、`stale` 和未覆盖地区不能解释为风险不存在。

### `external_signals[]`

记录外部已经发生、推断或预测的信号。每条信号必须有时间、地理、方向、严重度、新鲜度和证据。聚合平台是二手数据提供者；核心事件尽量回到监管、政府、交易、运营商或基础数据集核验。

### `exposure_links[]`

回答外部信号为什么会影响研究企业。必须尽量锚定具体产品或供应链节点，并写明传导机制、敏感度、时间范围、缓冲因素与未知项。

没有客户地区、采购地、供应商、成本结构、航线或监管适用范围的证据时，敏感度不得写高置信结论。

### `scenarios[]` 与 `monitoring_plan[]`

情景记录冲击变量、传导路径、影响维度、领先指标和推翻条件。监控计划把关键指标转为可重复检查的触发器，不等于已建立自动定时任务。

## 调查流程

1. 先建立企业内部锚点：产品、客户地区、供应商地区、关键材料、物流节点、收入与成本口径。
2. 再选择外部数据域，不要无差别搬运全球新闻。
3. 写 `source_health[]`，明确当前入口是正常、部分、陈旧、不可用还是未配置。
4. 把外部事件写入 `external_signals[]`，保留原始证据、时间和数据口径。
5. 用 `exposure_links[]` 建立“外部事件 → 企业锚点 → 经营变量”的传导机制。
6. 只有传导链成立后，才将其写入论断、情景或未来判断。
7. 为高影响且可观察的变量建立 `monitoring_plan[]`。

聚合导入必须为每条记录生成独立 `evidence[]`。成功读取本地导出只说明入口可用，不等于事件已交叉验证；聚合来源和其提供的上游链接默认写 `unverified`，信号的 `evidence_ids` 必须引用原子证据而不是直接引用 `source_id`。

可执行脚本：

```powershell
# 无密钥：读取用户导出的结构化外部信号
.\run.cmd external_signal_collect.py --input raw/worldmonitor-export.json --out raw/external-signals.json

# 公开或已授权入口；401/403、HTTP 200 登录页或挑战页会明确降级
.\run.cmd external_signal_collect.py --url "https://example.org/public-feed.json" --out raw/external-signals.json

# 需要环境密钥的授权入口：URL origin 必须与可信 HTTPS origin 完全一致
.\run.cmd external_signal_collect.py `
  --url "https://signals.example.org/feed.json" `
  --api-key-env SIGNALS_API_KEY `
  --trusted-origin "https://signals.example.org" `
  --provider "Example Signals" `
  --freshness-budget-hours 24 `
  --out raw/external-signals.json

# 检查入口健康，不把未配置密钥解释成无风险
.\run.cmd source_health.py --out raw/source-health.json

# 将 search_health.py 的引擎探针结果纳入同一套 source_health[]
.\run.cmd source_health.py --search-health raw/search-health.json --out raw/source-health.json

# 两次研究之间做结构化差异
.\run.cmd snapshot_diff.py research-old.json research-new.json --out raw/snapshot-diff.json

# 依据已确认的基线和冲击假设计算区间
.\run.cmd scenario_calculate.py scenario-input.json --out raw/scenario-result.json

# 用当前观测触发人工复查清单
.\run.cmd monitor_evaluate.py research.json observations.json --out raw/monitor-result.json

# 后续真实值到来后评价区间覆盖和基准误差
.\run.cmd scenario_backtest.py raw/scenario-result.json actuals.json --out raw/scenario-scorecard.json

# 审核后把生成片段合并回唯一事实源；重复 ID 默认拒绝
.\run.cmd merge_fragment.py research.json raw/external-signals.json --out research.updated.json
```

这些脚本只生成候选信号、健康状态、差异和敏感性计算；不会自动把外部事件写成企业事实，也不会自动发布预警。

公共 URL 永不自动接收环境密钥。只有用户显式提供 `--trusted-origin`，且请求 URL 与它是同一个 HTTPS origin 时才附加密钥；跨 origin 重定向会剥离认证头。`source_health.py` 的自定义配置也遵守相同规则，并读取有限正文检查 Content-Type、JSON/text 可解析性、登录表单和 CAPTCHA；HTTP 200 只代表传输成功，不自动等于 `available`。`provider`、记录日期和新鲜度必须从显式参数、主机名与记录字段推导，不能因为变量名或适配器名称就冒充 World Monitor 或标记为 `fresh`。

`snapshot_diff.py` 会先对新旧两份快照执行完整 Schema 与语义校验，损坏快照直接拒绝。来源 `retrieved_at`、来源健康 `observed_at/last_success_at` 和 `meta.generated_at` 的纯刷新归入 metadata-only；原子证据 `observed_at` 是事实观察时间，变化仍按实质变更处理。真正业务字段变化写入 `changed` 并列出 `changed_fields`。

## World Monitor 适配原则

World Monitor 可作为可选的外部环境信号供应商，适合发现和结构化以下数据：

- 国家风险、冲突、制裁和政策；
- UN Comtrade 国家—国家—商品贸易流；
- 航运压力、AIS、咽喉要道和运价；
- 能源、管道、关键矿产与基础设施中断；
- 全球公共采购机会；
- 市场、预测与新闻情报。

使用边界：

- 不把国家级贸易流写成企业级供应关系；
- 不把综合风险分数当作原始事实；保留其组成信号、算法版本和新鲜度；
- 不把 World Monitor 的 AI 分析直接升级为罗盘事实；
- 免费仪表盘可用于人工发现，MCP/API 仅在用户已授权账号和费用时调用；
- Provider 字段写 `World Monitor`，来源 URL 尽量保存具体 API、数据页或其引用的原始上游；
- 聚合 feed 的“成功获取”不能标记为 `corroborated`；只有事件内容经过独立来源核对后才能升级验证状态；
- 罗盘不复制 World Monitor 源码，不依赖其 AGPL 代码运行。

## 质量与降级规则

- `freshness_budget_hours` 取决于数据：航运/冲突通常以小时计，贸易和产量可能以月或季度计。
- 数据超过预算写 `stale`，不要用最新标题掩盖陈旧底表。
- 聚合数据出现 `upstreamUnavailable`、`partial`、`stale` 或模拟数据标记时，必须传递到报告。
- 预测信号必须填写 `caveats`；高严重度判断若依赖陈旧数据，降低置信度并列入局限。
- 外部信号至少引用一条原子证据；高影响结论优先补第二个独立来源。
- 只搜到新闻而没有企业暴露证据时，写“环境风险候选”，不写“企业将受损”。

## 情景推演

情景不得只写故事。按以下链条填写：

```text
触发条件
→ 冲击变量（价格、交期、关税、需求、融资、停产概率）
→ 企业锚点（产品、客户、供应链节点）
→ 传导路径
→ 影响维度（收入、毛利、现金流、库存、份额、研发、合规）
→ 领先指标
→ 推翻条件
```

不要输出伪精确的利润影响数字。只有基线、弹性或可复核区间存在时才量化，否则给方向和条件。

## 行业映射

| 行业 | 优先外部信号 | 企业锚点 |
|---|---|---|
| 稀土/矿业 | 产地集中、贸易流、出口管制、矿价、港口 | 矿权、品位、分离产能、客户、长协、物流 |
| 核能源 | 许可、燃料贸易、铀价、制裁、电网、项目进度 | 反应堆/部件、燃料来源、认证、订单、工期 |
| 半导体 | 出口管制、晶圆产能、设备贸易、能源/水 | 制程、设备、客户地区、代工厂、库存 |
| 消费硬件 | 芯片/材料价格、海运、关税、海外政策 | SKU、BOM、代工、渠道库存、地区收入 |
| 航运/能源 | 咽喉要道、AIS、管道、战争险、库存 | 航线、船队、合同结构、码头/管道资产 |
