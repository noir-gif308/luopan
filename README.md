# 罗盘 Luopan · 企业深层情报研究引擎 + 证据驱动写作技能

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/罗盘-v3.7.1-6f42c1)](./luopan/VERSION)
[![Schema](https://img.shields.io/badge/research.schema-1052行机器契约-6f42c1)](./luopan/research.schema.json)

本仓库开源三个面向 AI Agent 的技能（Skill），以及支撑它们运转的**跨 Agent 搜索适配层**：

| 组件 | 定位 | 一句话 |
|---|---|---|
| **罗盘 Luopan v3.7.1** | 企业深层情报研究引擎 | 把"资料堆砌"变成"可追溯判断"：结构化事实底座 → 机器校验 → 渲染报告 |
| **ai-worker v1.3.0** | 证据驱动内容写作 | 只从真实素材出发写文章，声称强度受证据边界约束 |
| **personal-narrative v1.0.0** | 第一人称个人叙事 | 零添加、只保护、只放大——写出来的人就是用户本人 |
| **搜索适配层** | 上述技能的采集底座 | 本机优先、多层降级、状态可审计的搜索/抓取/垂直来源适配器族 |

三个技能全部为 MIT 许可，设计目标是：**可在多 Agent 环境（Codex / Hermes / Claude Code 等）中长期复用、并发安全、输出可机器校验**。

---

## 目录

1. [仓库结构](#仓库结构)
2. [罗盘 Luopan](#罗盘-luopan)
   - [定位与设计承诺](#定位与设计承诺)
   - [工作原理](#工作原理)
   - [八阶段工作流](#八阶段工作流)
   - [三维路由：模式 / 目的 / 镜头](#三维路由模式--目的--镜头)
   - [核心对象模型](#核心对象模型)
   - [Schema 机器契约](#schema-机器契约)
   - [运行时隔离设计](#运行时隔离设计)
   - [红线与停止条件](#红线与停止条件)
3. [搜索适配层（重点）](#搜索适配层重点)
   - [设计原则](#设计原则)
   - [五层架构](#五层架构)
   - [适配器契约](#适配器契约)
   - [适配器清单](#适配器清单)
   - [环境变量配置参考](#环境变量配置参考)
   - [凭据与安全边界](#凭据与安全边界)
   - [社媒垂直适配器 MediaCrawler 详解](#社媒垂直适配器-mediacrawler-详解)
4. [适用 Agent 与集成方式（重点）](#适用-agent-与集成方式重点)
5. [写作双技能](#写作双技能)
   - [ai-worker：证据驱动内容系统](#ai-worker证据驱动内容系统)
   - [personal-narrative：第一人称个人叙事](#personal-narrative第一人称个人叙事)
   - [写作四线系统的关系](#写作四线系统的关系)
6. [快速开始](#快速开始)
7. [安全与合规声明](#安全与合规声明)
8. [许可证与第三方依赖](#许可证与第三方依赖)
9. [版本历史](#版本历史)

---

## 仓库结构

```
.
├── README.md                          # 本文件
├── LICENSE                            # MIT
├── luopan/                            # 罗盘技能本体（可直接挂载为 Agent Skill）
│   ├── SKILL.md                       # 技能入口：读取规则 / 工作流 / 红线（381 行）
│   ├── VERSION                         # 3.7.1
│   ├── research.schema.json            # JSON Schema 机器契约（1052 行，唯一事实底座）
│   ├── run.cmd / run.ps1               # 脚本统一执行入口（强制走隔离运行时）
│   ├── bootstrap-runtime.ps1           # 运行时初始化器（幂等、离线可用、并发互斥）
│   ├── requirements-runtime.txt        # 运行时最小依赖（3 个包，全部固定版本）
│   ├── agents/openai.yaml              # Codex Agent 清单（展示层，非逻辑层）
│   ├── references/                     # 16 份方法论文档（按需读取，不全部常驻上下文）
│   ├── scripts/                        # 28 个采集/校验/渲染/测试脚本（标准库优先）
│   └── examples/                       # 12 个合成示例与反例夹具（含故意损坏的校验样例）
├── adapters/                           # 搜索适配层（跨 Agent 共用）
│   ├── mediacrawler/mediacrawler_search.py   # 社媒 7 平台垂直来源适配器
│   └── multi-free-js/                  # 可选配套：推特 / 雪球本地浏览器采集脚本
├── writing-skills/                     # 写作双技能
│   ├── ai-worker/SKILL.md
│   └── personal-narrative/
│       ├── SKILL.md
│       └── references/syntax-quality.md
└── .gitignore                          # work/ raw/ 等研究产物永不提交
```

**不提交的内容**：`work/`（每次研究的中间产物）与 `raw/`（原始采集材料与 manifest 审计）属于每次研究独立生成的产物，由 `.gitignore` 排除；本仓库只发布方法与代码，不发布任何具体企业的研究数据。

---

## 罗盘 Luopan

### 定位与设计承诺

罗盘是一个面向**上市、未上市及信息稀缺企业与行业**的深层情报研究引擎，附带可选的（且必须显式启用的）投资视角。适用场景：主体消歧、产品市场、客户与供应商关系、竞争格局、商业结构、组织人才、供应链、真实用户体验、研发转化、替代数据、区间反推、异常信号、信息操纵风险、领先指标与不确定情报调查。

**设计承诺只有一句：输出可追溯判断，不输出资料堆砌。** 这句话落实为三条硬约束：

1. 先生成结构化事实源 `research.json`，**校验通过后**再运行渲染脚本生成 Markdown 与 HTML——禁止分别手写三份内容（杜绝"报告与数据底座脱节"）；
2. 每条论断必须绑定原子证据（原文摘录 + 可定位页码/章节/时间戳），搜索摘要永远只用于发现来源，不进入结论；
3. 未经证实的信息不删除、不冒充事实，统一降级进情报区 `intelligence_items[]` 并保留验证路径。

### 工作原理

```
Phase 0 决策问题定义
   → Phase 1 候选信源池 + 垂直查询计划
   → Phase 2 Day-1 假设与反证清单
   → Phase 3 结构化采集（sources → evidence → entities → claims）
   → Phase 4 过滤与三角验证
   → Phase 5 分析（机制优先，不搞打分表演）
   → Phase 6 商业切入 / 6B 投资视角 / 6C 专项镜头
   → Phase 7 独立验证（citation / contradiction / inference 三查）
   → Phase 8 校验 + 渲染（JSON 无效则不产出报告）
```

### 八阶段工作流

| 阶段 | 任务 | 关键产物 |
|---|---|---|
| Phase 0 | 自适应访谈循环定义决策问题；研究就绪门通过前不开始搜索 | `intake`（提问、回答、默认假设、未决问题、获准访问方式） |
| Phase 1 | 建立候选信源池；Deep 模式强制七类来源池全覆盖 | `source_health[]`、垂直查询计划 |
| Phase 2 | 写 1-3 条可证伪假设 + 反证清单；投资视角升级为 `investment_theses[]` | 假设 / 反证 / 最大未知项 |
| Phase 3 | 原子证据先行：`sources[]` → `evidence[]` → 实体/产品/供应链 → `claims[]` | `research.json` 主结构 |
| Phase 4 | 去重、转载溯源、SEO/软文识别、时间口径检查 | `discarded_sources[]` |
| Phase 5 | 机制解释先于评分；五层输出（事实→结构→行为信号→反方→综合判断） | 可追溯结论 |
| Phase 6 | 个人商业切入（`act_now`/`watch`/`avoid_now`）；投资视角与专项镜头仅在显式启用时执行 | 条件式判断（含失效条件） |
| Phase 7 | 独立验证者执行引用核查 / 反证搜索 / 推断核查；泄漏推理过程给验证者即失败 | `verification_mode` + 留档 |
| Phase 8 | Schema 校验 → 渲染 Markdown + HTML；无效 JSON 不产出报告 | 报告 + 事实底座同源 |

### 三维路由：模式 / 目的 / 镜头

研究深度、决策目的、专项镜头是**三个正交维度**，不做单字段混淆：

**`meta.mode`（深度）**：

| 模式 | 适用场景 | 默认深度 |
|---|---|---|
| Quick | 初识行业、筛选是否值得深挖 | 6-9 个代表实体，15-25 次网络操作 |
| Standard | 商业/求职/创业决策 | 9-15 个代表实体，Top 6-9 深挖 |
| Deep | 单一企业全景尽调 | 产品市场、客户、竞品、组织、替代数据与信息风险全覆盖 |

**`meta.research_purpose`（目的）**：`intelligence`（默认）/ `investment` / `both`。上市公司不自动触发投资视角——投资用途必须经用户明确确认，且执行投资访谈门（标的、估值日、持有期三要素齐备）。

**`meta.analysis_lenses[]`（专项镜头）**：默认空数组，仅按明确决策问题启用，最少镜头原则：

| 镜头 | 触发条件 | 结构化结果 |
|---|---|---|
| `earnings_delta` | 比较新旧财报/指引/经营拐点 | `period_reviews[]` |
| `thesis_drift` | 判断投资论文强化/弱化/破裂 | `thesis_changes[]` |
| `management` | 深挖承诺兑现与资本配置 | `management_commitments[]` / `capital_allocation_events[]` |
| `income` | 收益、高股息或分红安全 | `income_analysis` |
| `bottleneck` | 供应链瓶颈或卡点利润 | `bottleneck_nodes[]` |
| `decision_audit` | 买入前/加仓/投资决策纪律复核 | `decision_audit`（六道门） |

### 核心对象模型

六个概念严格分写，禁止混用：

| 对象 | 含义 | 例子 |
|---|---|---|
| `value_chain_position` | 企业位于价值链哪里 | 材料 / 零部件 / 制造 / 品牌 / 渠道 / 服务 |
| `power_tier` | 议价能力与依赖程度 | dominant / advantaged / competitive / dependent |
| `product_role` | 产品承担的经济角色 | 利润产品 / 规模产品 / 引流产品 / 战略产品 / 衰退产品 |
| `evidence_confidence` | 结论的证据可靠度（≠企业强弱） | 按证据层分级，缺失指标不按 0 分 |
| `observations[]` | 尚不能升级为事实、值得持续追踪的信号 | 招聘、招投标、价格、库存变动 |
| `intelligence_items[]` | 传闻、异常与矛盾信息（与事实区严格分离） | 来源动机 + 可信度 + 影响 + 验证方法 |

### Schema 机器契约

`research.schema.json`（1052 行）是唯一的事实底座契约。两道闸门：

1. `validate_research.py`：JSON Schema + 语义校验（如原子证据摘录必须能在来源摘录中逐字找到、`complete` 状态不得配 `verification_mode: none`、来源 URL 禁止携带 userinfo 等）；
2. `render_report.py`：渲染前**再次执行同一套校验**，无效 JSON 不产出报告。

`examples/` 内置 12 个夹具，其中含**故意损坏的反例**（非法日期格式、discovery-only 冒充证据、无企业暴露锚点的外部风险等），发布回归必须确认这些反例在严格运行时下失败——防止校验器静默退化。

### 运行时隔离设计

罗盘不信任宿主环境中的裸 `python`，自带初始化器与执行入口：

- `bootstrap-runtime.ps1` 将 Python 与固定版本依赖（`PyYAML==6.0.3`、`jsonschema[format]==4.26.0`、`Markdown==3.10.2`）安装到 `%LOCALAPPDATA%\Luopan\runtime`——**位于技能目录之外**，升级/重装技能不删除运行时；
- 幂等：解释器、依赖导入与依赖文件哈希未变化时不联网；
- 并发安全：命名互斥锁串行化多个 Agent 的同时初始化（最长等待 5 分钟）；
- 离线可用：`-Offline` 禁止下载，`-Wheelhouse <目录>` 指定本地 wheelhouse；
- `run.cmd` 只执行技能内脚本（绝对路径脚本直接拒绝），规避 PATH 劫持与 Execution Policy 问题。

### 红线与停止条件

罗盘内置 18 条红线（节选）：不把券商报告当一手披露、不把转载数量当交叉验证、不把评论情绪当故障率、不把相关性写成因果、不隐藏口径/时间/样本偏差、不从搜索摘要复制数字进结论、不把好公司直接写成好投资、不把目标价写成事实……

停止条件同样明确：核心判断均有可定位证据或明确推断标签；新增来源连续三次不改变结论；关键争议有正反证据或明确说明反方缺失；继续搜索的边际价值低于成本。

---

## 搜索适配层（重点）

搜索适配层是罗盘与写作技能的采集底座，也是本仓库**跨 Agent 共用的基础设施**。它回答一个问题：**在免费、合规、本机优先的前提下，如何拿到可审计的原始材料？**

### 设计原则

1. **本机优先链**：本地 SearXNG 中文优先 → 静态页普通 HTTP → Scrapling dynamic → 受控浏览器后备 → `manual_required` 人工接管。每一步失败都记录具体原因，绝不静默降级。
2. **可移植规则**：公共核心工作流不假设任何具体路径存在。能力探测顺序：本地 SearXNG → 环境原生搜索 → 其他可用搜索；抓取顺序：普通 HTTP → 动态浏览器 → stealth/反爬。所有外部依赖一律通过环境变量登记（见[环境变量配置参考](#环境变量配置参考)），未配置即优雅降级为 `not_configured`。
3. **低频、留档、可审计**：采集器只做低频候选发现、下载、哈希和审计；每个 URL 记录检索词、抓取方式、状态、失败原因、抓取时间与内容哈希；原始材料落盘 `raw/` 并生成 `manifest.json`。
4. **候选 ≠ 证据**：采集器产出的全部是候选（`discovery_only`），不得自动写入 `research.json` 或支撑论断；进入 `sources[]/evidence[]` 前必须经过原文提取与证据审查。

### 五层架构

```
┌─ 广搜层 ──  SearXNG / multi_free_source：发现别名、关键词、候选 URL
├─ 垂直层 ──  工商 / 招投标 / 专利商标 / 认证许可 / 环评 / 司法 / 招聘 / 社媒 / 官方披露
├─ 抓取层 ──  普通 HTTP → browser_capture 受控后备 →（授权后）stealth/CAPTCHA → manual_required
├─ 解析层 ──  从页面/PDF 提取主体、编号、产品、客户、金额、日期、关系边
└─ 证据层 ──  去重、原子摘录、来源激励、正反证据、时间口径
```

SearXNG 只承担广搜层的候选发现职责，不冒充垂直数据库；垂直层按来源类型分别查询官方入口与公开 API。

### 适配器契约

所有适配器遵守同一接口约定（对齐 `luopan/references/tool-adapters.md`）：

| 契约项 | 约定 |
|---|---|
| 调用形式 | CLI 命令 + `--out <file>` 输出候选 JSON（机器可读、可二次处理） |
| 状态分类 | `available` / `partial` / `unavailable` / `manual_required` / `not_configured`，每状态附 `observed_at` 与具体原因 |
| 原始材料 | 落盘 `raw/<分组>/`，附 `manifest.json` 采集审计（文件哈希、时间、来源） |
| 失败记录 | 失败必须写明原因（403、Cloudflare、重 JS、PDF 解析缺失……），不得静默伪装成"无结果" |
| 凭据隔离 | 密钥只经环境变量或显式 `--trusted-origin` 传入；账本只记用量不记查询文本 |

### 适配器清单

`luopan/scripts/` 共 28 个脚本，按职责分组：

**广搜与候选发现**

| 脚本 | 功能 | 依赖 |
|---|---|---|
| `multi_free_source.py` | 6 免费源并行聚合：Google News RSS（中/英，7 天时效）、SearXNG general + news、DuckDuckGo（免 key）、GitHub API、HN Algolia；可选微博 / 推特 / 雪球三源 | 本地 SearXNG 可选，缺失自动降级 |
| `search_health.py` | 搜索健康三探针：普通公司名 / 精确引号 / 官方域名；输出各引擎结果数、越域率、重复率、垃圾域名率、CAPTCHA/限流状态 | 无 |
| `source_discovery.py` | 官方披露轻量发现：`site-feed`（官网新闻 RSS）、`sec-ticker` / `sec-filings`（SEC）、`hkex-filings`（HKEX，自动解析 stockId，NEWS_ID 增量键）、`cninfo-filings`（巨潮，org_id 来自官方元数据，announcementId 增量键）；输出全部为 `discovery_only` 候选 | 无 |
| `vertical_plan.py` / `vertical_health.py` | 垂直查询计划生成 / 垂直入口可用性检查 | 无 |

**垂直采集（公开原始材料）**

| 脚本 | 功能 |
|---|---|
| `procurement_collect.py` | 政府采购/招投标公告候选采集（状态：`captured` / `empty` / `partial`，频控标记自动转受控浏览器后备） |
| `government_pdf_collect.py` | 政府 PDF 采集（环评 / 能评 / 排污许可等关键词族） |
| `external_discovery.py` | Common Crawl 归档 URL 发现、GDELT 新闻线索 |
| `external_signal_collect.py` | 外部信号（地缘/贸易/航运/能源/制裁等）导入；无密钥时用公开导出 |

**抓取与后备**

| 脚本 | 功能 |
|---|---|
| `browser_capture.py` | 受控浏览器后备入口：只允许 `dynamic` 模式，默认不运行 stealth、不解 CAPTCHA、不复用未授权 Cookie；`{401,402,403}` 与挑战页判定后返回 `manual_required` |
| `luopan_dynamic_bridge.py` | 每次调用独立空浏览器 Profile、只允许访问已批准的公开主机边界、输出有界 JSON；与 browser_capture 同包捆绑而非依赖外部可变 bridge |

**适配网关**

| 脚本 | 功能 | 硬约束 |
|---|---|---|
| `firecrawl_search.py` | Firecrawl 搜索 + 可选 `--scrape`；`includeDomains/excludeDomains` | 月度 1,000 积分硬上限（发送请求**前**检查账本，账本只记 creditsUsed/请求 ID/UTC 时间，不落查询文本与密钥）；自建端点必须 `--base-url` 与 `--trusted-origin` 完全匹配，跨 origin 重定向剥离 `Authorization` |

**数据管线**

| 脚本 | 功能 |
|---|---|
| `source_health.py` | 来源分组健康状态（覆盖度、新鲜度预算、缺项原因） |
| `source_intake.py` | 候选入库：原始文件 + 哈希 + manifest，只写 `raw/`，不触碰 `research.json` |
| `snapshot_diff.py` / `merge_fragment.py` | 研究版本对比 / 片段合并（审核后） |
| `scenario_calculate.py` / `scenario_backtest.py` / `investment_calculate.py` | 敏感性区间计算（标准库 Decimal，杜绝浮点 eval）/ 区间覆盖回测 / 累计与年化回报计算 |
| `monitor_evaluate.py` | 数值触发监控与需人工复核的监控事件 |

**校验与质量门**

| 脚本 | 功能 |
|---|---|
| `validate_research.py` | Schema + 语义双校验 |
| `render_report.py` | 渲染 Markdown + HTML（内部再次全量校验） |
| `validate_skill.py` | 技能自身完整性校验 |
| `runtime_doctor.py` / `runtime_smoke.py` | 运行时诊断（断链 venv 检测）/ 行为烟测 |
| `regression_suite.py` / `security_regression.py` | 离线发布回归：安全与语义全覆盖（含 DNS 隔离的凭据边界测试、报告消毒测试） |

### 环境变量配置参考

所有外部依赖均通过环境变量登记，未设置时优雅降级（`not_configured`），不会崩溃、不会静默伪造结果：

| 变量 | 用途 | 未设置时的行为 |
|---|---|---|
| `SEARXNG_URL` | 本地 SearXNG 地址 | 默认 `http://localhost:8080`；连接失败记录为该源 unavailable |
| `FIRECRAWL_API_KEY` | Firecrawl 官方 API | `not_configured`，不静默回退 |
| `FIRECRAWL_BASE_URL` | 自建 Firecrawl 端点 | 仅接受无 path/query/userinfo 的 HTTPS origin |
| `SCRAPLING_PYTHON` | Scrapling 虚拟环境解释器 | browser_capture 的 dynamic 后备返回 `manual_required` |
| `LUOPAN_CHROMIUM` | 专用 Chromium 可执行文件 | 回退系统 Chrome（`C:\Program Files\Google\Chrome\...`） |
| `WEIBO_COOKIE` / `RSSHUB_ENV_FILE` | 微博登录态（直接值 / 指向含 `WEIBO_COOKIES=` 的文件） | 微博源跳过（返回空） |
| `NODE` / `NODE_PATH` | Node 解释器 / 模块路径 | 推特、雪球源跳过 |
| `TWITTER_SEARCH_JS` / `XUEQIU_SEARCH_JS` | 本地浏览器采集脚本位置（本仓库 `adapters/multi-free-js/` 提供） | 对应源跳过 |
| `MEDIACRAWLER_DIR` | MediaCrawler 项目目录（社媒适配器） | 预检返回"环境变量未设置"，不尝试运行 |
| `LUOPAN_RAW_DIR` | 社媒原始材料落盘目录 | 默认 `raw/social` |
| `LUOPAN_RUNTIME_ROOT` | 运行时根目录覆盖 | 默认 `%LOCALAPPDATA%\Luopan\runtime` |
| `CHROMIUM_PATH` | `multi-free-js` 脚本的浏览器路径 | 脚本报错退出并提示设置 |

### 凭据与安全边界

适配层的安全边界是可测的（`security_regression.py` 覆盖）：

- 来源 URL 禁止携带 `user:password@host` userinfo；凭据只通过显式授权配置传递；
- 公共 feed URL 不得自动接收环境密钥；授权端点必须由用户显式提供与请求 URL **完全一致**的 HTTPS `trusted_origin`，跨 origin 重定向剥离凭据；
- Firecrawl 月度账本只记 `creditsUsed`、请求 ID 与 UTC 时间，不保存查询文本、正文或 API Key；
- 所有采集遵循"记录每个 URL 的抓取方式与失败原因"原则，失败不得伪装成无结果。

### 社媒垂直适配器 MediaCrawler 详解

`adapters/mediacrawler/mediacrawler_search.py` 是搜索适配层的社媒垂直来源实现，接口对齐上文契约，覆盖 7 个中文平台：

| 平台 | 键 | 字段映射要点 |
|---|---|---|
| 小红书 | `xhs` | `note_url` / `desc` |
| 抖音 | `dy` | `aweme_url` |
| 快手 | `ks` | `video_url`（注意：`viewd_count` 为官方字段名拼写） |
| B站 | `bili` | `video_url` / `video_comment` |
| 微博 | `wb` | 无独立标题，用 content 截断 |
| 贴吧 | `tieba` | `total_replay_num` |
| 知乎 | `zhihu` | `content_url` / `voteup_count` |

**调用链**：适配器 CLI → MediaCrawler CLI（`uv run main.py`，CDP 复用本地 Chrome 登录态）→ 解析各平台 `search_*.jsonl` → 输出统一候选 JSON + `raw/social/<platform>/` 落盘 + `manifest.json`。

**关键设计（来自真实踩坑经验）**：

- **登录态三级管理**：`--lt qrcode`（首次扫码，登录态持久化）→ `--lt cookie`（复用）；无人值守运行前强制预检登录态缓存（阈值 100KB），缺失时输出扫码指引而非静默失败；
- **subprocess 环境净化**：调用 MediaCrawler 前清空 `PYTHONPATH`——宿主 Agent 的 venv 污染会让 zhihu/ks 等平台崩溃（加载了错误版本的 tenacity/playwright）；
- **双根扫描**：wb/dy/ks 不读 `save_data_path` 仍写 `data/`，适配器对两个根都扫描；
- **超时必杀进程树**：`taskkill /T` 防 Chrome 孤儿窗口；
- **会话快照清理**：运行前后清 `Sessions/Tabs_*`，防空白标签页跨运行恢复积累（登录态存 Network/Cookies，不受影响）；
- **字段名以实测为准**：MediaCrawler 主程序参数名带下划线（`--crawler_max_notes_count` / `--get_comment` / `--headless`），README 旧参数名已失效。

> ⚠️ 第三方依赖声明：MediaCrawler 本体为 **NON-COMMERCIAL LEARNING LICENSE 1.1**，不包含在本仓库中；本适配器仅为接口封装层（MIT），使用者需自行获取 MediaCrawler 并遵守其许可证。

---

## 适用 Agent 与集成方式（重点）

罗盘的设计约束之一是多 Agent 环境下的**并发安全与互不污染**，因此它不绑定任何特定 Agent 框架。

| Agent | 集成方式 | 运行时 | 验证状态 |
|---|---|---|---|
| **Codex（OpenAI）** | 原生技能目录格式（SKILL.md + 目录结构）；`agents/openai.yaml` 提供清单（display_name + default_prompt） | 经 `run.cmd` 走隔离运行时；不向 Codex 自带 Python 装依赖 | ✅ 开发主环境，v3.7.1 在此持续演进 |
| **Hermes（Nous Research）** | `config.yaml` 的 `skills.external_dirs` 挂载；外部技能对 skill_manage 只读 | 同上；Hermes 会话需以 `PYTHONPATH=` 前缀调用，防宿主 venv 污染 | ✅ 已挂载实测（跨 Agent 联动共享同一适配器层） |
| **Claude Code** | SKILL.md frontmatter 格式兼容，直接放入技能目录 | 同上；初始化器与 Agent 无关 | ⚠️ 格式兼容，未在本机实测 |
| 其他遵循 SKILL.md 约定的框架 | 目录整体拷贝即可 | 同上 | 按框架能力自测 |

**多 Agent 并发的关键设计**：

1. **运行时唯一且位于技能目录之外**：多个 Agent 同时初始化同一运行时由命名互斥锁串行化；Agent A 升级技能不会清掉 Agent B 的运行时；
2. **执行入口唯一**：`run.cmd` 解析脚本路径、校验 requirements 哈希、拒绝绝对路径脚本——任何 Agent 都必须经过同一入口，规避各 Agent 自带 Python 的 ABI 差异；
3. **依赖固定版本**：运行时只装 3 个固定版本包；抓取器（Scrapling）与社媒爬虫（MediaCrawler）各自独立建环境，不向罗盘运行时叠加依赖。

**子代理部署注意**：子代理不继承父会话已加载的技能上下文。把研究任务委派给子代理时，必须显式注入相关 `references/` 的核心要点（触发场景、关键命令、坑），只写技能名是不够的——这是跨 Agent 复用该类技能最常见的失效模式。

---

## 写作双技能

两个写作技能与罗盘共享同一认识论：**不发明**。ai-worker 用"不发明"限制声称强度；personal-narrative 用"不发明"保证写出来的人是用户本人。

### ai-worker：证据驱动内容系统

**定位**：把真实发现（实验、观察、选择、失败、一手材料）变成能改变读者理解的内容，而不是模仿他人文风或制造冲突。稳定的作者能力是三个而非固定人设：实验者（一手材料）、判断者（什么重要、什么不确定、证据之后什么变了）、解释者（机制、证据边界、实践含义可读）。

**核心规则：Discovery Before Audience and Hook**——先有真实材料，再谈受众与钩子：

```
真实材料 → 作者的认知实际改变了什么 → 为什么超出作者本人重要
→ 谁从这一认知中受益 → 读者的认知带走什么 → 文章结构与段落流
→（仅当明确要求）单独的平台形式
```

**材料账本**：起草前逐项登记原始材料、触发时刻、事实、推断、未知项、读者收益、受益者、平台语境；账本薄就补料或收紧声称，不用流畅文笔掩盖证据缺口。

**六层证据边界**（互不替代）：官方声称 / 展示上限 / 基准测试 / 个人测试 / 生产使用。真实故障先陈述窄观察（"三次指令变成一次连续输出"），再说明要下一般性结论还需要什么测试。

**商业因果纪律**：时间顺序不是因果解释；事实 / 机制 / 推断 / 替代解释 / 未知项显式分离；判断企业"进入市场"不得用单一信号（展示/意向/交付/毛利/经营利润/质量服务逐级区分）。

**修订模式**：先保护（数字、人名、出处、限定词、作者特色词最高保护级），再声明修订范围（bounded / in-place / structural），结构诊断先于文笔抛光，作者痕迹不因"更顺"而被改写；连续方向反转的用户反馈触发 in-place 模式——只改最新反馈点名的位置，其余句子逐字保留。

**四层自检 L0-L3**：L0 真实（声称分层、不编造、缺口披露）；L1 读者契约（开头来自真实时刻、收益前置、结尾给判断工具）；L2 作者完整性（不借人设、不夸大观察、结论强度匹配证据、中文过 CGED 四类句法）；L3 分发与学习（文章可独立成立、平台资产仅在要求时生成、单篇反馈不升格为长期规则）。

### personal-narrative：第一人称个人叙事

**定位**：处理第一人称个人叙事——简历项目经历、个人故事、面试素材、自述、创业复盘；素材是用户的口语碎片与聊天原话。交付目标：读者读完记住一个人。

**核心原则：零添加，只保护，只放大。** 情感与人格不注入，只从用户原话中提取与保护。每条新增内容必须通过测试句：

> 这句话是对用户已有内容的看法/组织，还是对世界的新断言？
> 新断言 = 删除。看法 = 用户没要求，也删除。

**persona 卡**：每次任务现场提取四类素材——特色词（换个人不会这么说）、决策点（选择/放弃/止损及理由）、情绪痕迹（自我暴露）、核心命题（同一判断模式在 ≥2 个独立事件出现才升格）；每项必须能在用户原话中逐词指出出处，指不出出处的不得进入正文。

**句法即人格**：区分两种"粗糙"——人格性毛边（口语词、判断方式、有意的重复强调）保留；缺陷性毛糙（分句断裂、主宾缺失、动宾不搭、同段重复同词）必改。句法自审按 CGED 中文语法错误诊断四类（缺失/冗余/替换/语序）+ 标点执行，逐句读出声音判断停顿边界。

**硬性条款（违反即失败）**：语域替换（书面化用户原话）是实质性改动必须 flag；三层标记（已确认/待确认/模型推断）只有已确认进入正文；数字缺口用保守表述不填洞；交付附特色词保留率清单（逐词标注已保留/已改动/已删除）。

**借鉴来源（完整披露）**：人格提取框架与自我相似度天花板借自 cosmos-makers/writer-persona（8 轴压缩为 4 轴）；Stance 默认关、测试句借自 hannsxpeter/humanizer；真实性纪律与三层标记借自 coinluu/resume-jd-optimizer-cn；facts first 借自 wangranm-a11y/yueli-resume-writer；核心命题概念借自 larashero3-dotcom/writing-dna-skill；句法标准源自 CGED（IJCNLP 2017 学术评测）、pycorrector（shibing624）、Fenng/Tech-Doc-Style-Chinese、sparanoid/chinese-copywriting-guidelines。

### 写作四线系统的关系

```
ai-worker        客观认知文（证据账本）：不发明 → 限制声称强度
personal-narrative  第一人称叙事（人格素材保护）：不发明 → 写出来的人是本人
lieflat          成稿清理（11 项 AI 味特征；本仓库外，未开源）
humanizer        英文向清理（本仓库外，未开源）
```

---

## 快速开始

**前置要求**：Windows 10+ / PowerShell 5.1+；联网（首次初始化下载 Python 与 3 个固定版本依赖）；可选 `uv`（初始化器优先复用）。

```powershell
# 1. 初始化隔离运行时（幂等，重复运行无副作用）
cd luopan
powershell -ExecutionPolicy Bypass -File .\bootstrap-runtime.ps1

# 2. 诊断与冒烟
.\run.cmd runtime_doctor.py
.\run.cmd runtime_smoke.py

# 3. 技能自校验 + 示例夹具校验
.\run.cmd validate_skill.py
.\run.cmd validate_research.py examples\deep-synthetic.json
.\run.cmd render_report.py examples\deep-synthetic.json --out-dir output

# 4.（推荐）离线回归：安全 + 语义全量
.\run.cmd regression_suite.py
```

**一次最小研究**（Quick 模式）：让 Agent 加载 `luopan/SKILL.md`，按读取规则先读 `references/research-intake.md` 完成访谈，随后 `search_health.py` 探针 → `vertical_plan.py` 查询计划 → 结构化采集 → `validate_research.py` → `render_report.py`。

**完全离线部署**：`bootstrap-runtime.ps1 -Offline [-Wheelhouse D:\packages\luopan-wheelhouse]`（wheelhouse 须含 `requirements-runtime.txt` 全部传递依赖的二进制 wheel）。

---

## 安全与合规声明

- **公开信息优先**：默认只采集公开可访问信息；遇到验证码、登录或付费边界，仅在**用户明确授权**后尝试自动化，仍失败必须停在 `manual_required` 并转人工；
- **不获取非法信息**：不绕过付费墙获取未授权内容、不利用内部信息；付费商业数据库优先通过合法账号与授权接口使用；
- **凭据最小化**：仓库内不含任何密钥或登录态；全部凭据经环境变量注入且遵循 trusted-origin 规则；
- **目标站边界**：采集脚本内置低频、有界、可审计约束；使用者应遵守目标网站服务条款与当地法律法规；
- **不构成投资建议**：投资视角输出是带方法、假设与失效条件的条件式研究判断，不替代最终投资决策。

## 许可证与第三方依赖

- 本仓库全部代码与文档：**MIT** © 2026 大厂转型人强哥（见 [LICENSE](./LICENSE)）；
- 第三方运行时依赖（不随仓库分发）：Scrapling（按其许可证与 `uv.lock` 自建）、MediaCrawler（NON-COMMERCIAL LEARNING LICENSE 1.1）、本地 SearXNG（AGPL-3.0）、Firecrawl（官方 API 服务）、DuckDuckGo / GitHub / HN / Google News 公开接口。

## 版本历史

| 组件 | 版本 | 说明 |
|---|---|---|
| 罗盘 Luopan | v3.7.1 | 28 脚本 / 16 参考文档 / 1052 行 Schema；含回归与安全测试套件 |
| ai-worker | v1.3.0 | 材料账本、六层证据边界、修订模式、L0-L3 自检 |
| personal-narrative | v1.0.0 | persona 卡、CGED 四类句法自审、特色词保留率清单 |
| 搜索适配层 | — | 随罗盘演进；契约见 `luopan/references/tool-adapters.md` |
