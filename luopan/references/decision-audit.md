# 投资决策审计

仅在用户明确要求买入前检查、加仓复核、投资决策纪律或排除情绪干扰，并且 `research_purpose` 为 `investment/both` 时读取。本镜头位于企业事实与估值之后，只审计“是否具备行动准备度”，不重新采集一套事实、不重复估值、不生成第二个买卖结论。

## 六道门

填写 `decision_audit.gates[]`，六项必须各出现一次：

1. `thesis_clarity`：能否用简短、可证伪的语言说明赚钱机制、主要风险和失效条件。
2. `circle_of_competence`：用户是否理解关键变量与未知项；资料少不等于看不懂，看不懂也不等于企业差。
3. `downside_survivability`：悲观情景、流动性和最大损失是否在用户约束内；用户未提供风险承受时写 `unknown`。
4. `evidence_sufficiency`：方向性结论所需的价格、资本结构、反证和关键经营证据是否够用。
5. `behavioral_independence`：决策是否主要受 FOMO、他人推荐、近期涨跌、锚定、沉没成本或确认偏误推动。
6. `opportunity_cost`：是否明确与现金、指数、其他候选或暂不行动相比的取舍；不要求虚构精确回报。

`basis` 区分 `research_evidence`、`user_input` 和 `mixed`。事实类 `pass/fail` 必须引用原子证据；用户偏好与承受能力只能来自访谈，并通过 `user_answer_indices[]` 逐门引用 `intake.user_answers[]`，不得由 Agent 猜测。用户输入是决策约束，不得伪装成企业证据。

## 状态与冲突

- 六门全 `pass` 且没有待满足条件：`overall_status: ready`。
- 任一 `fail`：`overall_status: blocked`。
- 没有 `fail` 但存在 `unknown`：`overall_status: insufficient`。
- `conditional` 只用于六门全通过、但仍有明确非阻断条件需要在行动前满足的情况；把条件写入 `conditions[]`。`ready` 的 `conditions[]` 必须为空。

记录 `behavioral_flags[]` 和可比较的 `opportunity_cost`。`none` 不得与其他行为标记并存。

审计结论与 `investment_conclusion` 发生冲突时，不覆盖原事实或另造结论：保留冲突，并将 `consider_entry` 降为 `watch/indeterminate`。`stage: initial_entry` 要求当前持仓明确为 `not_held`，持仓未知时先补访谈；`stage: add_position` 要求当前持仓为 `held`。审计未就绪时可以维持 `hold`，但不得解释为允许加仓。本镜头不使用跨行业固定财务阈值，不把“好公司”“好证券”“好价格”“适合当前用户”混为一件事。
