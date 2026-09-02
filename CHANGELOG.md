# 变更记录（Changelog）

本文件记录本仓库的公开版修订。罗盘上游版本号见 `luopan/VERSION`；写作技能版本见各自 SKILL.md frontmatter。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [v3.7.1-public.2] - 2026-09-02

### 新增
- `.github/workflows/ci.yml`：GitHub Actions 持续验证（Windows runner 上完成 bootstrap → 冒烟 → 技能自校验 → 99 项离线回归 → 示例渲染 → 反例夹具必须失败），每次推送自动执行
- `CHANGELOG.md`：本文件

### 修正
- README「拉取即用边界」措辞精确化：`multi_free_source` 中零外部依赖的为 Google News RSS / GitHub / HN 三个免费源；SearXNG 两源与 ddgs 源属可选增强（此前"6 个免费源零外部依赖"不精确）
- README 系统要求表：注明 MediaCrawler 适配器的超时清理逻辑仅 Windows（依赖 `taskkill`）
- `.gitignore` 增加 `output/`（渲染产物）

## [v3.7.1-public.1] - 2026-09-02

### 新增
- 首次公开发布：罗盘 Luopan v3.7.1（SKILL.md + 1052 行 Schema + 28 脚本 + 16 参考文档 + 12 示例夹具 + 隔离运行时）+ ai-worker v1.3.0 + personal-narrative v1.0.0 + 搜索适配层（MediaCrawler 社媒适配器、multi-free JS 配套）
- README：罗盘工作流/三维路由/Schema 契约、搜索适配层契约与清单、环境变量配置参考、适用 Agent 矩阵、写作双技能、快速开始、系统适配矩阵、外部组件下载路径、安全合规声明、许可证与第三方依赖

### 变更
- 本机路径全部环境变量化（去除 11 处硬编码默认值），未配置即优雅降级
- 个人化授权表述（"用户 2026-08-17 授权"）改为规范表述"须经用户明确授权"（5 处）
- 排除研究产物（work/、raw/、调研草稿）出库

### 修复
- `bootstrap-runtime.ps1` 的 `LUOPAN_RUNTIME_ROOT` 支持：参数默认值接入环境变量，与 `run.ps1` 统一（修复隔离运行时初始化落错目录）；采用 PowerShell 5.1 兼容写法（param 块后的语句赋值）

## [v3.7.1] - 罗盘上游基线（本仓库建立前的版本）

罗盘 Luopan v3.7.1 上游基线：28 脚本 / 16 参考文档 / 1052 行 Schema / 回归与安全测试套件。本仓库自该版本起进行公开化适配；上游继续由原作者维护。
