# 搜索适配层调用架构（Search Adapter Fabric）

> 版本 v1.0 ｜ 2026-09-05 ｜ 维护：noir-gif308 ｜ 适用范围：罗盘 luopan + Hermes 多 Agent 本地检索栈
> 配套：`adapters/ddgs/ddgs_search.py`（适配器范例）｜ 上游约定：`luopan/references/tool-adapters.md`

## 0. 为什么需要编排（问题陈述）

- **历史教训**：本地检索曾单点依赖 SearXNG，实测 8 引擎挂 5（baidu/google/sogou 验证码、qwant 拒绝、yep 报错），通用检索层整体瘫痪。
- **当前现状**：已部署 12+ 个源（通用检索/新闻流/热榜/垂直/监控），若无编排会出现：重复结果、口径打架（如客户数三说并存）、单源失败拖垮整体、无法审计"哪条结论靠哪些源确认"。
- **设计目标**：多源并行互补（信息面）＋ 冲突可检测可标注（不打架）＋ 单源失败自动降级（稳定性）＋ 全链路可审计（manifest）。

## 1. 分层架构

```
L0 路由层   查询意图分类 → 选源策略（什么查询走什么源、并行几路）
L1 编排层   并行扇出 → 超时控制 → URL/标题去重 → 聚合 → 冲突消解 → 生成 manifest
L2 适配层   每源一个适配器：统一接口（CLI + --out JSON + source_health 子命令）
L3 消费层   罗盘 research 流程 / Hermes web_search(multi_free) / 人工查阅
```

分层铁律：**新增源只动 L2 + 注册表，不改 L0/L1**；编排层不感知源内部实现。

## 2. 源注册表（Source Registry）

| id | 适配器/入口 | 类型 | 权威等级 | 时效 | 成本 | 实测状态（2026-09-05） |
|---|---|---|---|---|---|---|
| ddgs | `adapters/ddgs/ddgs_search.py` | 通用网页检索 | secondary | 索引天级 | 免费 | ✅ 批量 15/15 成功、1.5-3.6s；约 17% 冷门词组合需黑名单过滤（已内置） |
| searxng | 本地 `:8080` | 通用检索兜底 | secondary | 索引天级 | 免费 | ⚠️ 仅 bing/sogou/yahoo 稳定，quark 间歇；baidu/google 验证码（IP 风控无解） |
| newsnow | 本地 `:4444/api/s?id=<源>` | 新闻流聚合 | secondary | 分钟级 | 免费 | ✅ baidu/36kr/bilibili 等源池实时返回 |
| dailyhot | 本地 `:6688/<平台>` | 中文平台热榜 | tertiary | 分钟级 | 免费 | ✅ 36氪(22)/B站(100)/知乎(29)/澎湃(20)/IT之家(48)；微博/抖音/快手被风控 |
| gnews-rss | multi_free 内置 | 新闻检索 | secondary | 分钟级 | 免费 | ✅ 接口 302 需跟随重定向（curl 加 `-L`） |
| akshare | `.akshare-venv` | 财经垂直 | secondary | 实时~天级 | 免费 | ✅ 含财联社电报/研报/公司新闻 |
| mediacrawler | `adapters/mediacrawler/` | 社媒垂直 7 平台 | primary（登录态） | 实时 | 免费（需扫码） | ⚠️ xhs 登录态过期待重扫；zhihu 有效 |
| procurement_collect | luopan scripts | 招标采购 | primary | 天级 | 免费 | ✅ 直连 ccgp 搜索接口 |
| source_discovery | luopan scripts | 监管/公司公告 | primary | 天级 | 免费 | ✅ SEC EDGAR + 巨潮 |
| wechat2rss | 公开服务 xlab.app | 微信公众号 RSS | secondary | ≤24h | 免费（私有部署付费） | ✅ 300+ 公众号公开端点 |
| changedetection | 本地 `:5000` | 网页变更监控 | primary | 实时（轮询） | 免费 | ✅ Docker 部署，盯关键页面"变更即推送" |
| horizon | 本地 docker | AI 过滤/日报层 | —（非原始源） | 日 | DeepSeek token | ✅ deepseek-chat 驱动，RSS→打分过滤→中英日报 |
| rsshub | 本地 `:1200` | RSS 路由工厂 | secondary | 分钟级 | 免费 | ✅ 华尔街见闻/36氪/虎嗅等订阅流 |

权威等级定义：**primary**=官方/监管/登录态一手源；**secondary**=搜索引擎索引与聚合媒体；**tertiary**=热榜/讨论/软文。

## 3. 路由规则（Routing Table）

| 查询意图 | 主源 | 补充源 | 兜底 |
|---|---|---|---|
| 公司基础事实/背景 | ddgs + searxng | 官网直抓 | source_discovery（登记/公告） |
| 近期动态/新闻 | newsnow + gnews-rss | ddgs 时间窗检索 | dailyhot 热榜 |
| 社媒口碑/员工评价 | mediacrawler（登录态） | dailyhot 热榜 | 搜索引擎站内 `site:` |
| 财经数据/快讯 | akshare | gnews-rss | ddgs |
| 招标/采购 | procurement_collect | changedetection 订阅招标搜索页 | 通用检索 |
| 微信生态内容 | wechat2rss 公开端点 | RSSHub 微信路由 | 放弃并标注 |
| 关键页面变更 | changedetection（订阅式，非查询式） | — | — |
| 每日监控流 | horizon（RSS 订阅 → AI 过滤 → 日报推送） | — | — |

## 4. 冲突消解协议（防"互相打架"核心）

1. **事实冲突**：权威等级仲裁 primary > secondary > tertiary；**冲突永不静默覆盖**，必须显式标注 `conflict` 并双列证据来源。
2. **数字口径冲突**（例：客户数 30万/34万/1万）：全部保留、各自标注来源与发布时间，报告并列呈现、不选边不下结论。
3. **时效冲突**：按发布时间对齐取最新；同一 URL 内容变化以 changedetection 记录为准。
4. **结果去重**：URL 规范化（去 query 参数/去 www）→ 标题指纹（前 30 字+长度）→ 正文内容 hash，三级去重。
5. **垃圾过滤**：中文查询按 CJK 规则 + 域名黑名单过滤（ddgs 适配器已内置，防止代理 IP 间歇降级时英文垃圾混入）。

## 5. 降级链

每类查询 3 级降级；单源失败**静默继续但写入 manifest**（谁挂了、为什么、耗时）：

- 通用检索：ddgs → searxng(bing/sogou/yahoo) → 官方站内搜索
- 新闻：newsnow → gnews-rss → ddgs 时间窗
- 社媒：mediacrawler → dailyhot → 搜索引擎 `site:` 站内
- 微信：wechat2rss → RSSHub → 标注不可得

## 6. 多源确认协议（Convergence）

信息需要"多方面大量信息源相互补充、筛选确认"时按此执行：

- **关键事实**（影响结论）：≥2 个独立源一致，或 1 个 primary 源 → 采信
- **单源事实**：标注 `unverified`
- **冲突事实**：标注 `contradict`，进报告风险区，不参与结论
- 落到罗盘：evidence 的 claim 必须能追溯到多源确认或 primary 源；discovery_only 的 SERP 摘要不得支撑结构化事实

## 7. 适配器接口约定（对齐 luopan tool-adapters.md）

```bash
python <adapter>.py "查询词" --limit 20 --out result.json   # 检索
python <adapter>.py source_health                           # 健康状态（采集前先跑）
```

- 输出格式：`{"meta": {"query", "source", "count", "elapsed_s", "health", "fetched_at"}, "items": [...]}`
- manifest 审计：每次编排运行记录每源 请求数/成功数/耗时/降级原因，落盘 `raw/manifest.json`
- 适配器运行环境注意：罗盘 runtime 不装第三方爬虫依赖；ddgs 适配器用 Hermes venv python 跑（已装 ddgs，venv 无 pip 用 `uv pip install --python`）

## 8. 稳定性实测数据（2026-09-05，本机）

| 源 | 测试 | 结果 |
|---|---|---|
| ddgs | 3 查询×5 轮重复 + 12 查询单轮 | 15/15 成功、零错误、1.5-3.6s；2/12 查询垃圾率高（过滤后可用） |
| searxng | 引擎池重启前后对比 | 修复后 sogou 复活（11 条）；brave/ddg/startpage 仍验证码（IP 风控） |
| dailyhot | 9 平台可达性 | 5 平台正常；微博 432 / 抖音 / 快手 / 虎嗅被风控 |
| newsnow | /api/s 实拉 | baidu/36kr 实时数据正常返回 |
| changedetection | 部署健康检查 | HTTP 200 |
| horizon | 24h 日报实测 | deepseek-chat 驱动（见部署记录） |

## 9. 演进规则

- **新增源**：写适配器（带 source_health）→ 注册表登记 → 路由表加行 → 本文档升版本；不改编排层。
- **删源**：连续 3 次 source_health 失败且无修复路径 → 从路由表降为兜底 → 观察 2 周再删。
- **实测数据**：每次重大变更跑一轮 benchmark 并更新第 8 节。
- **凭据**：登录态/API key 只存本地 `.env`/容器卷，不进仓库。
