# research.json 写入规则

`research.schema.json` 是机器契约。本文件解释不可由 JSON Schema 完整表达的语义。

## 目录

1. 唯一事实源与调研前提
2. ID、研究目的与专项镜头
3. 时间、口径与空值
4. 不确定信息与信息稀缺企业
5. 覆盖、独立性与反证

## 唯一事实源

- `research.json` 是唯一可编辑研究产物。
- Markdown 和 HTML 必须由 `scripts/render_report.py` 生成。
- 修改结论时先修改 JSON，再重新校验和渲染。

## 调研前提

建议填写 `intake`：记录已询问的问题、用户回答、采用的默认假设、仍未解决的问题和获准使用的访问方式。用户要求直接开始时用 `interaction_mode: defaults_disclosed`，并把默认假设显示在报告中；主体歧义或需要付费/对外动作时不能只写假设继续。

## ID 与引用

- 来源：`src-*`
- 实体：`ent-*`
- 产品：`prd-*`
- 供应链节点：`sc-*`
- 指标：`met-*`
- 体验信号：`ux-*`
- 研发信号：`rd-*`
- 论断：`clm-*`
- 机会：`opp-*`
- 产品市场：`pm-*`
- 客户群：`cust-*`
- 竞争者：`comp-*`
- 商业结构关系：`bm-*`
- 组织信号：`org-*`
- 外部观察：`obs-*`
- 叙事风险：`nar-*`
- 未证实情报：`intel-*`
- 原子证据：`evd-*`
- 情景：`scn-*`
- 来源健康：`sh-*`
- 外部信号：`ext-*`
- 企业暴露：`exp-*`
- 监控项：`mon-*`
- 关系边：`rel-*`
- 代理估算：`est-*`
- 投资论点：`invth-*`
- 估值情景：`val-*`
- 财报期间复核：`per-*`
- 管理层承诺：`mcom-*`
- 资本配置事件：`cap-*`
- 投资论文变化：`td-*`
- 瓶颈节点：`bn-*`

论断通过 `evidence_ids` 引用原子证据、指标、体验或研发信号，不能直接引用来源记录、产品或实体本身充当证据。来源记录只描述文档整体；论断必须落到带方向、非空定位和观察日期的原子证据。原子证据的规范化摘录必须是对应 `source.excerpt` 的子串，防止证据层改写或反转来源原文。

Deep 模式的论断必须填写 `claim_components[]`，把复合句拆成分别可验证的子判断。每个子判断单独绑定证据、置信度和剩余未知，防止部分证据支撑整句结论。

外部环境相关对象遵循：`source_health[]` 记录数据入口状态，`external_signals[]` 记录环境变化，`exposure_links[]` 证明企业具体暴露，`scenarios[]` 描述冲击传导，`monitoring_plan[]` 保存后续触发器。外部信号不能直接代替企业暴露证据。

## 研究目的与投资对象

- `meta.mode` 只表示 Quick/Standard/Deep 深度；`meta.research_purpose` 表示 `intelligence`、`investment` 或 `both`；`meta.analysis_lenses[]` 只表示显式启用的专项镜头，三者不得混用。跨主体比较由两份同口径研究文档编排完成，不伪装成单份 `research.json` 模式。
- `research_purpose`、`analysis_lenses` 和 `information_regime` 是必填路由字段；普通研究显式写 `intelligence`、空镜头数组和真实信息环境。专项字段存在但镜头未启用、或镜头启用却缺对应结构时校验失败。
- `investment_context` 保存具体投资工具、估值日、持有期、参考价值、持仓、进入路径和资本结构状态。公司名称不能代替证券或股权标的。
- `investment_theses[]` 保存可证伪的业务、估值和风险论点；投资模式要求 3-7 条，至少覆盖 `business`、`valuation` 和 `risk`。
- `valuation_scenarios[]` 使用 `val-*`，包含唯一的 `downside/base/upside`；目标值必须满足悲观不高于基准、基准不高于乐观。
- `expected_total_return` 和 `expected_annual_return` 必须由 `investment_context.reference_value`、目标值和持有期复算，误差超过 `0.000001` 时校验失败。
- `investment_conclusion` 必须锚定 `base` 情景，保存价格条件、期限、失效条件和证据。`hold/reduce/exit` 只能用于已持有标的。
- 方向性结论要求参考数据 `fresh`、资本结构 `verified` 且三情景齐全；不满足时使用 `watch/indeterminate` 并把缺口写入未知项和局限。

## 专项镜头

- `earnings_delta` 使用 `period_reviews[]`。当前期和对比期指标必须分别绑定不同原子证据；会计口径不明时不得把数字差直接解释为经营变化。
- `management` 使用 `management_commitments[]` 与 `capital_allocation_events[]`。已兑现、部分兑现、未兑现或撤回的承诺必须有结果证据；`missed` 只能在截止日后判定。资本配置金额、币种和精确公告日期必须出现在证据摘录中。
- `thesis_drift` 只能与 `investment/both` 同时使用。`thesis_changes[]` 的当前状态必须与对应 `investment_theses[]` 一致；纯措辞变化不得改变状态和方向；非措辞变化按来源发布日期核对基线窗口。
- `income` 只能与 `investment/both` 同时使用。除 `insufficient_data` 外必须包含 `base/adverse/severe`，并完整检查覆盖、债务、结构性衰退、治理和证据五个阻断门；每个情景必须保存可复算组成项、分配额和 Schema 固定公式，渲染器从输入自动生成公式说明。
- `bottleneck` 使用 `bottleneck_nodes[]` 并关联已有 `supply_chain_nodes[]`。高置信 confirmed 至少需要两个独立发布者、两条实质不同证据和四个已观察维度；所有已填写量化值必须出现在引用摘录中，未知数值使用 `null`。
- `decision_audit` 只能与 `investment/both` 同时使用。它使用单例 `decision_audit` 审计六道决策门；事实类判断引用原子证据，用户约束通过 `user_answer_indices[]` 逐门引用 `intake.user_answers[]`。任一门 `fail/unknown` 时不得输出 `consider_entry`；`conditional` 必须列出结构化 `conditions[]`。

## 时间与口径

- `published_at`、`retrieved_at`、证据 `observed_at`、外部信号和观察项 `as_of` 使用有效 ISO 8601 日期或日期时间，不接受“近期”“2026左右”等自由文本。
- 指标必须写 `period`、`unit` 和 `scope`。
- 预测值在 `metric_type` 标记 `estimate` 或 `forecast`。
- `actual` 和 `proxy` 的 `value` 必须是 JSON 数字，并能在所引原子证据摘录中核对；不可把数字写成字符串跳过核验。
- 不同口径的数字不得直接比较；需要比较时写明调整方法。
- 投资参考价格、股本、净现金/负债、汇率和财务口径必须匹配 `valuation_as_of`；目标价值属于模型结果，不得写入 `actual` 指标。

## 空值

未知值使用 `null` 或省略可选字段，并在 `limitations` 说明。禁止用 0 代表未知。

`meta.research_status: blocked` 表示主体歧义、访问边界或关键用户选择使研究不能安全继续。此时允许 Deep 章节、关系边和代理估算为空，但必须保留 `intake`、`key_unknowns`、`limitations`，并在适用时填写主体消歧和足迹缺口；不得为了通过 Deep 门控编造经营内容。

## 不确定信息

- 可观察但解释未定的变化写入 `observations[]`。
- 来源或真实性未完全确认的信息写入 `intelligence_items[]`。
- 二者不得直接作为高置信事实；需要升级时先补证据，再写入 `claims[]`。
- `intelligence_items[]` 必须保留原始说法、来源关系、来源动机、正反信号、影响和下一验证动作。
- `intelligence_items[].raw_source_evidence_ids` 必须指向真正承载原始说法的原子证据，不能用无关财报或指标装饰一条自行生成的传闻。
- `metrics[].evidence_ids` 必须指向原子证据；`source_ids` 只说明文档归属，不承担数字定位。
- `metrics[].source_ids` 必须与 `evidence_ids` 展开后的实际来源集合完全一致；任何一边多报或漏报都视为血缘错误。

## 信息稀缺企业

- `meta.information_regime` 使用 `private_sparse`。
- `identity_resolution` 先解决法定主体、品牌、域名、地址、联系方式和产品型号的对应关系。
- `footprint_coverage[]` 逐项记录主体、所有权、产品、客户、供应商、产能、组织、技术、渠道、司法和监管覆盖。
- `complete` 状态要求主体、产品、客户、组织和监管足迹为 `covered`；无法证明不适用的维度不得用 `not_applicable` 掩盖缺口。
- `relationship_edges[]` 保存客户、供应商、股东、渠道和关联方关系，区分 verified/inferred/alleged。
- `proxy_estimates[]` 只保存有输入证据、公式、上下界、敏感项和交叉检查的区间估算。

## 覆盖、独立性与反证

- `source_coverage.status: covered` 至少引用一个视角匹配、非 `discovery_only`、含非空原文摘录的来源。
- Deep 标记 `complete` 时，所有必需视角的 `covered` 记录还必须包含至少一个 `verified/corroborated` 来源；全是 `unverified` 只能降为 `partial`。
- `discovery_only` 来源不能通过 `evidence`、指标或信号间接支撑任何论断或指标。
- 高置信事实没有一手来源时，至少引用两个不同发布者、不同规范化 URL、非空且不同 `content_hash` 的可信来源。
- 高置信推断/预测写 `counter_search_status: searched_found` 时，`counter_evidence_ids` 不得为空，且必须指向 `stance: contradicts` 的原子证据。
- Source URL 禁止携带 `user:password@host` 等 userinfo；凭据只通过显式授权配置传递。
- 竞争者 `evidence_ids` 展开后的来源必须全部列入 `competitor_source_ids`，且至少有竞争者自身或独立监管/市场来源。
- `research_status: complete` 仍必须列出非空 `limitations`；完整表示关键覆盖达标，不表示研究没有边界。
