---
name: luopan
description: 上市、未上市及信息稀缺企业与行业的深层情报和可选投资视角研究引擎。用于主体消歧、产品市场、客户与供应商关系、竞争、商业结构、组织人才、供应链、真实用户体验、研发转化、替代数据、区间反推、异常信号、信息操纵风险、领先指标和不确定情报调查；当用户要求企业深度研究、产业尽调、潜力企业筛选、产品/供应链剖析、估值与投资论点跟踪，或专项分析财报增量、管理层承诺兑现、投资论文漂移、收益安全和供应链瓶颈时使用。不替用户作最终投资决定，不非法获取内部信息或绕过付费/认证边界。
---

# 罗盘 v3.7.1

输出可追溯判断，不输出资料堆砌。先生成结构化事实源 `research.json`，校验通过后再运行脚本生成 Markdown 和 HTML；禁止分别手写三份内容。

## 读取规则

- 每次研究先读 `references/source-policy.md`。
- 深度研究单一企业时必须读 `references/company-intelligence.md`。
- 研究未上市、信息稀缺、官网简单或疑似多主体经营的企业时必须读 `references/private-sparse-company.md`。
- 研究实体制造、消费硬件、原材料、零部件或供应链企业时，再读 `references/manufacturing.md`。
- 需要评分、机会判断或商业切入建议时，再读 `references/methodology.md`。
- 需要本机搜索和抓取时，再读 `references/tool-adapters.md`。
- 需要工商、采购、专利、备案、认证、环评、司法、招聘和渠道来源时读 `references/vertical-sources.md`。
- 企业存在跨国、能源、矿产、航运、制裁、政策或基础设施暴露，或用户要求压力测试/持续监控时读 `references/external-environment.md`。
- 用户明确说“投资视角”、询问估值/买卖方向，或访谈确认研究用于证券或股权投资时，必须读 `references/investment-view.md`。
- 用户要比较新旧财报、追踪管理层承诺/资本配置或判断投资论文是否漂移时，读 `references/temporal-analysis.md`。
- 用户明确要求收益、高股息、分红安全或现金收入视角时，读 `references/income-investment.md`。
- 用户明确要求供应链卡点、瓶颈利润池或瓶颈解除风险时，读 `references/bottleneck-analysis.md`；实体供应链基础分析仍先读 `references/manufacturing.md`。
- 用户明确要求买入前检查、加仓复核、决策纪律或排除情绪干扰时，读 `references/decision-audit.md`；它只审计既有投资结论，不重复估值。
- 用户只给研究对象、用途或边界不清时读 `references/research-intake.md`。
- 工商、专利、商标、ICP、认证或司法入口需要验证码/浏览器时读 `references/browser-vertical-workflow.md`。
- 写入 `research.json` 前读 `references/schema.md`，并以 `research.schema.json` 为机器契约。

## 运行时

不要信任 PATH 中的裸 `python`。首次使用先运行 `bootstrap-runtime.ps1`，把 Python 与 `PyYAML`、`jsonschema[format]`、`Markdown` 安装到 `%LOCALAPPDATA%\Luopan\runtime`；此运行时位于 Skill 目录之外，升级或重装 Skill 不会删除它。之后统一用 `run.cmd` 执行脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap-runtime.ps1
.\run.cmd runtime_doctor.py
.\run.cmd runtime_smoke.py
.\run.cmd validate_skill.py
.\run.cmd validate_research.py research.json
.\run.cmd render_report.py research.json --out-dir output
```

若首次初始化需要下载 Python 或依赖，必须获得用户允许。不要向 Codex 自带 Python 安装依赖，也不要复用其他项目的 `.venv`。读取 `references/tool-adapters.md` 了解诊断和降级。

初始化成功后重复运行是幂等的：解释器、依赖导入和依赖文件哈希未变化时不会再次联网；依赖安装或升级后再运行完整烟测。命名互斥锁会串行化多个 Agent 的同时初始化。离线主机使用 `bootstrap-runtime.ps1 -Offline`；有本地 wheelhouse 时再加 `-Wheelhouse <目录>`。离线模式要求目标 Python 已由 uv 安装，本地缓存或 wheelhouse 包含所有传递依赖。

## 模式

用三个正交维度路由，不要把研究深度、决策目的和专项镜头混成一个字段。

根据任务复杂度选择最小充分深度 `meta.mode`：

| 模式 | 适用场景 | 默认深度 |
|---|---|---|
| Quick | 初识行业、筛选是否值得深挖 | 6-9 个代表实体，15-25 次网络操作 |
| Standard | 商业/求职/创业决策 | 9-15 个代表实体，Top 6-9 深挖 |
| Deep | 单一企业全景尽调 | 产品市场、客户、竞品、组织、替代数据与信息风险全覆盖 |

跨主体比较不是 `meta.mode`。当前版本先为每个主体分别生成并校验同深度、同时间、同地理口径的 `research.json`，再做人工审阅的综合比较；在独立比较 Schema 与合成器落地前，不得把单主体报告标成 Compare。

根据决策目的设置 `meta.research_purpose`：

| 研究目的 | 触发条件 | 额外成本 |
|---|---|---|
| `intelligence` | 默认；理解企业、合作、采购、求职、创业或竞争 | 无投资专属采集 |
| `investment` | 用户明确要求投资视角、估值或买卖方向 | 增加证券、资本结构、估值和投资论点 |
| `both` | 用户同时要企业全貌和投资决策 | 共用同一事实底座，再增加投资层 |

不要仅因研究对象是上市公司就自动切到投资视角。用户未明确投资用途时使用 `intelligence`；触发投资视角后执行投资访谈门，不允许用企业质量代替价格与回报判断。

根据明确决策问题设置 `meta.analysis_lenses[]`；默认必须为空，不得因“可能有用”自动全开：

| 专项镜头 | 触发条件 | 结构化结果 |
|---|---|---|
| `earnings_delta` | 比较新旧财报、指引或经营拐点 | `period_reviews[]` |
| `thesis_drift` | 判断投资论文强化、弱化或破裂 | `thesis_changes[]` |
| `management` | 深挖承诺兑现与资本配置 | `management_commitments[]` / `capital_allocation_events[]` |
| `income` | 明确要求收益、高股息或分红安全 | `income_analysis` |
| `bottleneck` | 明确要求供应链瓶颈或卡点利润 | `bottleneck_nodes[]` |
| `decision_audit` | 买入前、加仓或投资决策纪律复核 | `decision_audit` |

镜头只增加专项采集，不替代基础证据链。`income`、`thesis_drift` 和 `decision_audit` 只能与 `investment/both` 同时使用；研究上市公司、制造企业或最新财报本身都不能自动开启对应镜头。一次任务只选解决决策问题所需的最少镜头。

不要默认研究 30-50 家公司。先建候选池，再按代表性、权力、增长、争议和用户目标选样本。

## 核心对象模型

分开描述，不得混用：

1. `value_chain_position`：企业位于价值链哪里，例如材料、零部件、制造、品牌、渠道、服务。
2. `power_tier`：企业议价能力和依赖程度，例如 dominant、advantaged、competitive、dependent。
3. `product_role`：产品承担什么经济角色，例如利润产品、规模产品、引流产品、战略产品、衰退产品。
4. `evidence_confidence`：结论有多少可靠证据，不等于企业强弱。
5. `observations`：尚不能升级为事实，但值得持续追踪的外部信号。
6. `intelligence_items`：传闻、异常和矛盾信息；保留但不与事实混写。

禁止用“上游/中游/下游”同时表达产业链位置和权力等级。

## 工作流

### Phase 0：定义决策问题

开始任何搜索、抓取或结论写作前，先执行 `references/research-intake.md` 的自适应访谈循环。即使用户已给出较多信息，也先检查是否仍有会改变主体、路线或判断的缺口；不要把默认假设埋进研究。

首轮提 3-5 个高信息量问题，优先套取：

- 最终决策：理解企业、竞争判断、合作/采购、创业切入、求职还是投资研究；
- 地理与时间范围，以及更关心历史兑现还是未来 1-3 年潜力；
- 优先深挖的产品、客户、技术、供应链、管理层或风险；
- 已知法定名、品牌、域名、创始人、产品型号、所在地或其他消歧线索；
- 是否允许使用浏览器处理公开站点验证码，以及是否有合法授权的商业数据库账号。

若为投资研究，还要优先问清：具体证券/股权标的、估值截止日、计划持有期、当前是否持有；目标回报和最大可接受损失可由用户选择提供或明确保留为未知。未确认具体标的、估值日或持有期时不得越过投资研究就绪门。

把用户提供的内容区分为“用户确认的事实主张、用户推测/怀疑、待核验线索、用户持有的文件或入口”，都只作为检索种子，不能未经外部证据核验直接升级为事实。回答后先更新研究简报，再只追问剩余的最高价值缺口；后续每轮最多 3 个问题，不重复询问，不为了形式凑问题。

只有研究就绪门通过后才开始：决策问题明确；主体/产品边界足以消歧；地理与时间范围可执行；优先矛盾和用户已知线索已提取；访问/付费/对外边界明确；剩余未知可以通过公开研究处理或在报告中诚实保留。若任一缺口可能使研究对象或结论方向反转，继续追问。达到门槛后用 6 行以内复述研究简报并直接开工；存在重大误解风险时再请求确认。

用户明确要求跳过访谈时，可采用 `references/research-intake.md` 的默认假设并公开记录，但主体歧义、同名企业、研究对象边界或对外/付费动作仍必须暂停确认。访谈不得无限持续：连续两轮回答没有新增可执行线索时，说明剩余缺口和降级后的研究模式，由用户选择继续补充或按 `partial` 开始。

确认并写入：

- 用户要理解、进入、创业、求职还是比较。
- 行业产品边界、地理范围、客户类型、时间范围。
- 用户约束；没有明确画像时使用 `general`，不要编造个人条件。
- 本次采用的模式和停止条件。
- 研究目的：`intelligence`、`investment` 或 `both`；缺省为 `intelligence`。
- 信息环境：`listed`、`private_visible`、`private_sparse` 或 `unknown`。这是证据条件，不是企业质量评级。
- `intake`：记录提问、用户回答、默认假设、未解决问题和获准访问方式；让报告读者知道研究建立在什么前提上。
- `analysis_lenses`：记录明确启用的专项镜头；没有专项问题时写空数组。

若为 `private_sparse`，先完成主体消歧：法定名称、别名、注册标识、域名/ICP备案、地址、电话、专利/认证申请人和产品型号。主体仍歧义时，不得继续写经营结论。

### Phase 1：建立候选信源池

按 `references/source-policy.md` 搜索，至少覆盖：

- 监管与统计；
- 企业原始披露；
- 产品、客户与用户体验；
- 供应链和渠道；
- 技术、专利、认证和研发产出；
- 高质量二手研究与反方材料。
- 产品榜单、渠道、客户、供应商、招聘、员工流动、专利/认证、招投标、应用/网站流量、价格与库存等替代数据。

单一企业 Deep 模式必须按 `references/company-intelligence.md` 建立官方、对手、客户、供应商、员工、监管和行为数据七类来源池。任何一类完全缺失都要解释原因。

开始 Deep 或 `private_sparse` 调研前，若存在本地 SearXNG，先运行：

```powershell
.\run.cmd search_health.py "企业法定名" --official-domain example.com
```

诊断为 `degraded` 时，SearXNG 只能用于别名和候选发现；立即切换到垂直来源和已知官方入口，并将搜索降级写入局限。

生成垂直查询计划：

```powershell
.\run.cmd vertical_plan.py "企业法定名" --brand "品牌" --founder "创始人" --domain example.com --product "产品型号"
```

检查垂直入口可用性：

```powershell
.\run.cmd vertical_health.py
```

公开采购和政府 PDF 可用配套采集器留存原始材料：

```powershell
.\run.cmd procurement_collect.py "企业法定名" --alias "历史名或子公司" --product "产品型号" --out-dir raw/procurement
.\run.cmd government_pdf_collect.py "企业法定名" --keyword 环评 --keyword 能评 --keyword 排污许可 --out-dir raw/government-pdf
```

采集器只做低频候选发现、下载、哈希和审计，不把命中自动解释为事实。采购采集只有解析出公告候选时才标 `captured`；HTTP 200 空白页或无候选 HTML 分别保留为 `empty/partial`。采购 HTTP 命中频控标记时，自动调用批准的 `scripts/browser_capture.py`（仅 Scrapling `dynamic`）保存动态 HTML/文本和哈希，再解析候选；该后备不运行 stealth、不解 CAPTCHA、不复用未授权 Cookie。若动态页仍出现验证码、登录或付费边界，才返回 `manual_required`。工商、CNIPA、ICP 和司法等高风控入口仍使用 `references/browser-vertical-workflow.md` 的人工浏览器流程。

先记录来源元数据，再摘录证据。搜索摘要只能用于发现来源，不能直接支撑核心结论。

若外部环境会实质影响企业，按 `references/external-environment.md` 填写 `source_health[]`、`external_signals[]` 和 `exposure_links[]`。禁止从国家风险、运价或商品价格直接跳到企业结论；必须先证明企业具体产品、客户、供应商、地区或物流节点的暴露。World Monitor 只能作为可选聚合信号源，不替代企业级工商、专利、客户、供应商或海关证据。

执行层脚本：无密钥时用 `scripts/external_signal_collect.py --input` 导入公开导出；用 `scripts/source_health.py` 检查入口或转换 `search_health.py` 结果；用 `scripts/source_discovery.py` 从官方 Feed、SEC、HKEX 或 CNINFO 生成 `discovery_only` 候选；用 `scripts/source_intake.py` 将这些候选保存为原始材料和哈希（仍不得自动写入 `research.json`）；用 `scripts/snapshot_diff.py` 比较研究版本；用 `scripts/scenario_calculate.py` 计算有基线的敏感性区间；用 `scripts/monitor_evaluate.py` 执行数值触发或生成需人工复核的监控事件；用 `scripts/scenario_backtest.py` 在真实值到来后评价区间覆盖与误差；审核后用 `scripts/merge_fragment.py` 合并片段。读取 `references/external-environment.md` 获取参数与降级规则；读取 `references/tool-adapters.md` 获取官方披露候选的抓取边界。

公共 feed URL 不得自动接收环境密钥。授权端点必须由用户显式提供与请求 URL 完全匹配的 HTTPS `trusted_origin`；跨 origin 重定向必须剥离凭据。自建 Firecrawl 同样执行此规则。

聚合信号导入只证明聚合记录存在：每条记录必须生成独立 `evidence[]`，聚合 feed 与上游链接默认保持 `unverified`；不得把“接口可用”写成“事件已交叉验证”。

### Phase 2：建立 Day-1 假设与反证清单

写 1-3 条可被推翻的假设，并为每条列出：

- 什么证据支持；
- 什么证据会推翻；
- 当前最大未知项。

投资视角把其中 3-7 条升级为 `investment_theses[]`：每条必须有状态、反证条件、监控指标和复查频率。企业优秀、行业增长和股价便宜是三个不同假设，不得合并成一句。

### Phase 3：结构化采集

先填 `sources[]` 和原子证据 `evidence[]`，再填 `entities[]`、`products[]`、`supply_chain_nodes[]`、`experience_signals[]`、`rd_signals[]`、`metrics[]`，最后才写 `claims[]`。一个 `evidence` 只摘录一个可定位事实、行为或说法，必须填写非空页码/章节/时间戳定位和观察日期；其规范化摘录必须能在对应 `source.excerpt` 中逐字找到，禁止让原子证据改写或反转来源原文。Deep 模式的每条论断必须填写 `claim_components[]`，将收入、份额、利润、因果和预测等组成部分逐项绑定证据与未知项。

Deep 模式必须填写 `source_coverage[]`，逐项说明公司、监管、竞争者、客户、渠道、供应商、员工和行为数据是否覆盖；`covered` 至少引用一个视角匹配、非 `discovery_only` 且含原文摘录的来源。缺失时写 `gap_reason` 和下一搜索动作，禁止用搜索摘要、空摘录或沉默伪装成已覆盖。

`meta.research_status` 必须写 `complete`、`partial` 或 `blocked`。客户、渠道、供应商、员工或行为数据存在实质缺口时只能标 `partial/blocked`；模式名 `deep` 只表示采用 Deep 框架，不等于研究已完整完成。

垃圾信息处理写入 `discarded_sources[]`：说明是重复转载、SEO/软文、无原始链接、口径不明，还是因潜在影响重大而降级到 `intelligence_items[]`。有价值但未证实的信息不得直接丢弃。

Deep 模式还必须填写：

- `product_markets[]`：产品类型、市场定义、份额、价格带、用户群、区域、渠道和生命周期；
- `competitors[]`：直接竞争者、替代品、跨界进入者和上下游反向进入；
- `customer_segments[]`：客户任务、付费者、使用者、决策链和流失原因；
- `business_model_links[]`：获客、变现、交叉补贴、现金占用和产品飞轮；
- `organization_signals[]`：高管、关键团队、招聘增减、人才流动和组织缺口；
- `observations[]`：招聘、招投标、价格、渠道库存、供应商订单、专利/认证等领先信号；
- `external_signals[]`：地缘、贸易、航运、能源、商品、制裁、基础设施和政策信号；
- `exposure_links[]`：外部信号到产品、供应链、收入、成本和现金流的可审计传导；
- `scenario_results[]`：基于已确认基线和明确冲击假设的下界、基准和上界敏感性计算；
- `narrative_risks[]`：选择性披露、口径变化、夸张指标、关联交易和言行矛盾；
- `intelligence_items[]`：未经证实但可能重要的情报，写明来源动机、可信度、影响和验证方法。

`private_sparse` 还应填写：

- `identity_resolution`：法定主体、品牌、标识符和剩余歧义；
- `footprint_coverage[]`：主体、所有权、产品、客户、供应商、产能、组织、技术、渠道、司法和监管的覆盖状态；
- `relationship_edges[]`：股东、关联方、客户、供应商、渠道和人才流动关系；
- `proxy_estimates[]`：用客户、合同、产能、网点、席位或人员反推的区间估算。

`investment` 或 `both` 还必须填写：

- `investment_context`：具体投资工具、上市地/交易代码或私募进入路径、估值日、参考价格或估值、持有期、币种、持仓状态及对应证据；
- `investment_theses[]`：基本面、估值、管理层、资产负债表、催化剂和风险假设，逐条保存支持/反方证据、失效条件和复查节奏；
- `valuation_scenarios[]`：悲观、基准、乐观三情景，公开方法、公式、假设、目标价值、年化回报和证据；
- `investment_conclusion`：条件式立场、适用价格条件、核心理由、失效条件和置信度。

专项镜头只在启用时填写：

- `earnings_delta`：写入跨期指标变化、会计/口径信号及其对原判断的影响；
- `management`：写入可定位的原始承诺、兑现证据和重大资本配置结果；
- `thesis_drift`：只把证据变化记录为漂移，区分基本面、估值、证据增强和纯措辞变化；
- `income`：写入分配历史、现金覆盖、债务再融资、悲观削减情景和阻断门；
- `bottleneck`：写入集中度、扩产周期、替代、利用率、需求、认证、利润捕获和解除条件，不用红灯数量代替机制判断。
- `decision_audit`：只审计论点清晰度、能力圈、下行承受、证据充分度、行为独立性和机会成本；不重算估值，不另造买卖结论。

投资数据有时间耦合：参考价格、股本、净现金/负债和财务口径必须匹配估值日。公司质量证据不能替代市场价格证据；目标价值不能伪装成可观察事实。上市证券在三情景不齐、价格证据缺失或资本结构口径未核实时，只能输出 `indeterminate` 或 `watch`。未上市股权还要披露进入路径、流动性、稀释和退出约束，禁止硬套二级市场买卖结论。

`private_sparse + complete` 的主体、产品、客户、组织和监管足迹必须真正 `covered`；`not_applicable` 不是规避调查缺口的占位符。无法证明不适用时标 `partial/gap` 并保留原因和下一动作。

未上市小企业不要从“公司新闻”正向搜到底。按 `references/private-sparse-company.md` 从工商、招投标、客户、供应商、专利/认证、环评/产能、招聘、渠道、诉讼和产品型号反向拼接足迹。

竞争者的优势/弱点必须至少绑定一条竞争者自身原始材料或独立监管/市场证据；`competitor_source_ids` 必须真实包含 `evidence_ids` 展开后的来源，不能放一个未使用的竞争者来源装饰被研究企业自己的材料。未证实情报必须用 `raw_source_evidence_ids` 保存承载原始说法的原子证据；若原始说法无法保存，只能降为“待研究问题”，不能写进情报簿。指标必须通过 `metrics[].evidence_ids` 引用原子证据，且 `metrics[].source_ids` 必须与这些证据的实际来源完全一致；禁止回退到来源级大段摘要或错配来源绕过定位与口径检查。

所有数字必须绑定来源、日期、口径和原文摘录。`actual/proxy` 指标值必须是 JSON 数字，不得用字符串绕过原文数字核对。来源和证据时间使用有效 ISO 8601 日期或日期时间。没有原文链接或定位的数字不得进入核心判断。

先核对研究截止日期与监管登记。看似违背旧知识的上市、财报、许可或召回，必须以正式文件核验，禁止直接按记忆判为假消息。若公司边界因并购、拆分或重组变化，先写明本期 scope change，再比较历史数据。

实体供应链研究必须执行 `references/manufacturing.md`，至少回答：

- 哪些是规模产品、利润产品、引流产品和战略产品；证据是否足以判断。
- 单品收入、毛利、价格带、销量、售后和生命周期能否分离；不能分离时明确未知。
- 产品的关键材料、核心零部件、代工/自制环节、关键供应商、渠道和终端客户。
- 哪些节点构成卡脖子、单点故障、成本传导或库存风险。
- 用户真正购买的任务是什么；高频赞扬、故障、退货和长期体验是什么。
- 研发投入是否转化为专利质量、量产产品、客户采用、良率、成本或溢价。

### Phase 4：过滤和三角验证

执行来源去重、转载溯源、SEO/软文/水军识别和时间口径检查。

核心结论原则上满足以下之一：

- 一手来源直接支持；
- 两个相互独立的高质量来源交叉支持；
- 明确标记为推断，并公开推断链和反证。

任何 `discovery_only` 来源都不能通过原子证据、指标或信号间接支撑论断。高置信事实若没有一手来源，至少需要两个已验证/交叉确认的来源，并同时具备不同发布者、不同规范化 URL、非空且不同的 `content_hash`。转载、同一 URL 的不同标题或同一底稿不构成独立来源。高置信推断/预测若标记 `searched_found`，必须引用至少一条 `stance: contradicts` 的反证；没有找到反证时用 `searched_none` 并解释搜索范围。

用户评论必须按平台、型号、版本、购买时间和问题类型聚类。评论数量不能直接代表市场发生率。

不要删除只有单一来源但潜在影响巨大的信息。无法进入事实层时降级为 `intelligence_item`，并保留：原始说法、来源关系、动机偏差、支持/反对信号、若为真的影响、下一验证动作。

### Phase 5：分析而非打分表演

先解释机制，再给分数。权力分析至少考虑：

- 定价与成本传导；
- 客户和供应商集中度；
- 转换成本与替代品；
- 现金转换周期；
- 渠道控制、标准、牌照、品牌或网络效应；
- 证据覆盖率。

营运资金使用 DSO、DPO、CCC 与同行及历史比较：低 DSO、高 DPO、低或负 CCC 通常更强，但必须结合商业模式。禁止使用“应收高=回款快”或“应付低=占供应商资金”。

缺失指标不得按 0 分。证据覆盖不足时只给区间或定性判断。

按五层输出：

1. 事实底座；
2. 产品、客户、市场、竞争与商业结构；
3. 外部行为和领先指标；
4. 反方、异常、叙事风险与未证实情报；
5. 综合判断、关键未知和未来验证清单。

### Phase 6：个人商业切入分析

对可进入机会评估：痛点强度、客户是否已付费、可触达性、最小可复制切片、启动成本、验证周期、个人时间依赖、大厂内置风险、扩展路径和失败成本。

输出 `act_now`、`watch` 或 `avoid_now`，不得替用户作最终创业决定。

### Phase 6B：投资视角

仅在 `meta.research_purpose` 为 `investment` 或 `both` 时执行 `references/investment-view.md`。先判断企业质量和资本配置，再判断当前价格隐含的增长；按悲观、基准、乐观三情景计算目标价值与年化回报，最后给条件式 `consider_entry`、`watch`、`hold`、`reduce`、`exit`、`avoid` 或 `indeterminate`。

方向性结论必须同时说明适用对象、价格/估值条件、持有期、关键假设和失效条件。它是研究判断，不替用户作最终交易决定；如果用户未提供持仓状态，不输出只对持有人有意义的 `hold/reduce/exit`。

### Phase 6C：专项镜头

只执行 `meta.analysis_lenses[]` 中已启用的镜头。时间演化镜头比较事实和证据，不比较文风；收益镜头不得用显示股息率替代可分配现金和偿债分析；瓶颈镜头不得把供给紧张直接写成企业获利，必须证明利润捕获与解除条件；决策审计只检查既有投资结论的决策准备度，不重复企业质量和估值判断。专项结论若与基础研究冲突，显式保留冲突并降低置信度，不覆盖原事实。

跨期数值、单位和期间必须分别出现在当前期与对比期原子证据中；管理层结果来源必须晚于且不同于原承诺，`missed` 只能在截止日后判定；论文漂移按来源发布日期检查基线窗口。收益情景必须保存可复算组成项、分配额和公式，阻断门只要存在 `unknown/fail` 就不得输出 `consider_entry/hold`；高置信确认瓶颈必须有两个独立发布者和实质不同的支持证据，所有已填量化值必须能在摘录核对。所有专项报告必须渲染证据定位。

决策审计的六道门必须齐全。研究事实类判断引用原子证据，风险承受、能力圈和行为偏差用 `user_answer_indices[]` 逐门引用调研回答；只要存在 `fail/unknown`，不得输出 `consider_entry`。审计不得把主观“不舒服”改写成企业事实，也不得用固定 ROE、毛利率或 PE 阈值跨行业一票否决。首次进入审计要求明确未持仓，加仓审计要求当前持仓状态为 `held`；`ready` 不得遗留待满足条件，审计未就绪时可以维持 `hold`，但不得解释为允许加仓。

### Phase 7：独立验证

若环境支持独立 agent，将 `claim + evidence excerpt + URL + scope` 交给未参与写作的验证者，分别执行：

- citation check；
- contradiction search；
- inference check。

不要把原作者的推理过程或预期答案泄漏给验证者。若只能自审，明确标记 `verification_mode: self_review`。

`research_status: complete` 不得配 `verification_mode: none`。当前 Schema 只校验验证模式声明，不保存独立验证者身份与过程；使用 `independent` 时必须把验证输出与报告同目录留档，并在局限中说明验证范围。没有留档时降为 `self_review`，不得只改标签。

### Phase 8：校验和渲染

运行：

```powershell
.\run.cmd validate_research.py research.json
.\run.cmd render_report.py research.json --out-dir output
```

渲染脚本会再次执行同一套 Schema 与语义校验；无效 JSON 不生成报告。校验失败时先修 JSON，不要直接修改生成的 Markdown/HTML。

发布回归还必须确认 `examples/invalid-date-format.json` 在严格运行时下因 `meta.generated_at` 不是 `date-time` 而失败，防止 FormatChecker 再次失效。

## 停止条件

满足以下条件即可停止继续搜索：

- 核心判断均有可定位证据或明确推断标签；
- 新增来源连续三次没有改变实体、数字或核心判断；
- 关键争议至少有正反证据或明确说明反方缺失；
- 高影响外部风险已建立企业暴露链，或明确写明尚无企业级暴露证据；
- 用户决策所需的最大未知项已列出；
- 继续搜索的边际价值低于成本。
- Deep 模式的产品市场、客户、竞品、组织、替代数据、叙事风险七个维度均有结论或明确缺口。
- 投资视角的标的、估值日、持有期、三情景、核心投资假设和结论失效条件均已结构化；否则降级为 `partial` 或 `indeterminate`。
- 已启用专项镜头均有对应结构化结果、证据和缺口；未启用镜头不产生额外采集负担。

## 红线

- 不把券商报告标成公司一手披露。
- 不把转载文章数量当交叉验证数量。
- 不把评论情绪当产品故障率。
- 不用研发费用率单独证明技术壁垒或未来潜力。
- 不用公司整体毛利率证明某个产品是利润产品。
- 不把相关性写成因果。
- 不隐藏口径、时间、样本偏差和矛盾信息。
- 不为了 Top N 凑数。
- 不从搜索摘要复制数字进入结论。
- 不生成无法由 `research.json` 复现的报告内容。
- 不因信息尚未证实而静默删除；降级到情报区而不是混入事实区。
- 不把招聘数、专利数、下载量或社交热度单独当成业绩增长证明。
- 不把管理层说法视为中立事实；同时分析披露激励、遗漏和口径变化。
- 不把好公司直接写成好投资；价格、资本结构和持有期必须进入判断。
- 不用单一乐观情景、静态 PE 或未经复核的股本生成方向性买卖结论。
- 不把目标价写成事实；它只能是带方法、假设和失效条件的估值结果。
- 不因读取了财报就自动开启财报增量，不因企业分红就自动开启收益镜头，不因存在供应链就自动判定瓶颈。
- 不把报告措辞变化当投资论文漂移，不把股价变化当基本面变化。
