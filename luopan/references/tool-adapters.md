# 搜索与抓取适配

## 目录

- [本机优先链](#本机优先链)
- [罗盘专用运行时](#罗盘专用运行时)
- [投资情景计算](#投资情景计算)
- [可移植规则](#可移植规则)
- [搜索质量门控](#搜索质量门控)
- [搜索健康检查](#搜索健康检查)
- [建议的本机分层](#建议的本机分层)
- [Firecrawl 适配](#firecrawl-适配)
- [文档提取](#文档提取)
- [原始材料目录](#原始材料目录)

## 本机优先链

1. 使用 SearXNG 做中文优先搜索：`http://127.0.0.1:8080/search?q=<query>&format=json&language=zh-CN`。
2. 静态页面先用普通 HTTP 获取。
3. 页面为空、残缺或依赖 JavaScript 时使用 Scrapling dynamic。
4. HTTP 失败或页面依赖 JavaScript 时使用受控的 `browser_capture.py` dynamic 后备；罗盘工作流允许升级为 stealth 或 CAPTCHA 自动求解尝试（须经用户明确授权），仍失败时降级为 `manual_required` 并请求用户接管。

Scrapling 抓取器与罗盘运行时相互独立，不共用虚拟环境：

- 罗盘运行时不承载抓取器依赖；Scrapling 按其官方 `uv.lock` 单独重建。
- 若本机已配置 Scrapling，通过环境变量 `SCRAPLING_PYTHON` 登记其虚拟环境解释器（如 `…\Scrapling\.venv\Scripts\python.exe`），`browser_capture.py` 读取该变量定位抓取器。
- 不要通过复制 site-packages 或设置 `PYTHONPATH` 强行复用：不同 Python ABI 的 `.pyd` 会产生隐蔽错误。
- 可用 `runtime_doctor.py --venv <路径>` 检查已配置虚拟环境是否断链（`pyvenv.cfg` 的 `home` 不存在即为断链空壳）。

## 罗盘专用运行时

罗盘核心采集与转换脚本主要使用标准库；严格 Schema 和正常 HTML 渲染分别需要 `jsonschema[format]` 和 `Markdown`。运行时也安装 `PyYAML`，用于兼容外部官方 Skill 校验器；罗盘自身的 `validate_skill.py` 不依赖第三方 YAML 包。首次运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap-runtime.ps1
```

初始化脚本优先寻找现有 `uv`，创建 `%LOCALAPPDATA%\Luopan\runtime`，不会修改系统 PATH、Codex 托管 Python、Hermes 或 Scrapling 环境。以后统一通过公开入口 `run.cmd` 执行，避免 PATH 中的旧 venv、PowerShell Execution Policy 或同名程序劫持。

初始化成功后会记录依赖文件哈希并执行行为烟测；依赖未变化且烟测通过时，重复运行不会重新解析依赖或访问网络。命名互斥锁会串行化多个本机 Agent 的同时初始化，最长等待 5 分钟。运行时存在但基础解释器断链时，默认目录或带罗盘标记的目录可以自动重建；对未标记的自定义非空目录会拒绝清理，防止误伤其他项目。

完全离线时，必须已经具备 uv 管理的目标 Python，并且依赖已在 uv 缓存或本地 wheelhouse：

```powershell
# 仅使用 uv 本地缓存；禁止 Python 和包下载
powershell -ExecutionPolicy Bypass -File .\bootstrap-runtime.ps1 -Offline

# 仅使用指定 wheelhouse；与 -Offline 同用时也禁止 Python 下载
powershell -ExecutionPolicy Bypass -File .\bootstrap-runtime.ps1 `
  -Offline `
  -Wheelhouse "D:\packages\luopan-wheelhouse"
```

`-Wheelhouse` 目录必须包含 `requirements-runtime.txt` 中直接依赖及其全部传递依赖的兼容 wheel。初始化器只接受 binary wheel，不在本机临时编译源码包。

## 投资情景计算

投资视角使用标准库 `Decimal` 计算累计与年化回报，避免把外部 Skill 中未经测试的浮点 `eval` 工具带入罗盘：

```powershell
.\run.cmd investment_calculate.py examples\investment-calculator-input.json --out raw\investment-scenarios.json
```

输入必须包含正的参考价值与持有期，以及唯一的 `downside/base/upside` 目标值；目标值顺序错误、重复情景、负值或非有限数字会失败关闭。脚本只计算回报，不判断估值方法和假设是否合理。

## 可移植规则

不要在公共核心工作流中假设上述路径一定存在。能力探测顺序：

1. local SearXNG；
2. 环境原生搜索；
3. 其他可用搜索。

抓取顺序：

1. 普通 HTTP/原生 fetch；
2. 动态浏览器抓取；
3. stealth/反爬抓取。

记录每个 URL 的检索词、抓取方式、状态、失败原因、抓取时间和内容哈希。不要高并发轰击目标网站。

## 搜索质量门控

本机 SearXNG 是候选发现器，不是事实数据库。当前聚合引擎可能忽略英文 `site:` 约束、混入百科/百家号/聚合站，甚至返回尚未核验的未来事件。

- 搜索结果必须先按真实域名过滤，标题中出现官方机构名不代表链接来自官方域名。
- 涉及上市、许可、召回、合同和监管状态时，优先直取 SEC/HKEX/交易所、政府监管、公司 IR 或正式公告。
- 若用户纠正了时效性事实，立即废弃旧假设，从权威登记或监管文件重新建立时间线。
- 搜索摘要只用于定位 URL；即使摘要看起来完整，也不得写入 `evidence excerpt`。
- `site:` 结果出现越域时，标记该搜索提供者的域名约束不可靠，改用精确标题、站内目录、监管 API 或已知官方入口。

## 搜索健康检查

开始 Deep 研究前，对当前搜索提供者做三条探针：普通公司名、精确引号、已知官方域名。记录各引擎结果数、越域率、重复率、垃圾域名率和 CAPTCHA/限流状态。

若 Google/Baidu 被 CAPTCHA 暂停、`site:` 越域或默认请求实际只剩一个引擎，必须在报告中声明搜索降级，不得把“无结果”解释成“无信息”。

不要依赖默认综合搜索完成所有任务。建立查询矩阵：

- 法定名/历史名/品牌/创始人；
- 域名、ICP备案、电话、地址、邮箱域；
- 产品型号、认证号、专利申请人、商标；
- `招标/中标/验收/供应商/经销商/招聘/环评/处罚/诉讼/召回/投诉`；
- 客户名、供应商名和投资人名的反向组合查询。

对政府、监管、交易所和已知垂直门户，优先直达站点目录、公开 API 或站内搜索；当前聚合引擎的 `site:` 只能作为候选发现。

## 建议的本机分层

1. **广搜层**：SearXNG 发现别名、关键词和候选 URL；显式指定引擎并记录失效引擎。
2. **垂直层**：工商、政府采购、专利/商标、认证许可、环评、司法、招聘、App/电商等按来源类型分别查询。
3. **抓取层**：普通 HTTP → 受控 `browser_capture.py` 的 Scrapling `dynamic` 后备 → stealth/CAPTCHA 求解尝试 → `manual_required`。保存原始 HTML/文本、内容哈希与抓取日志。验证码、登录、付费或显式访问控制允许自动尝试（须经用户明确授权），仍打不通时必须停在 `manual_required`。
4. **解析层**：从页面/PDF 提取主体、编号、产品、客户、金额、日期和关系边。
5. **证据层**：去重、原子摘录、来源激励、正反证据和时间口径。

SearXNG 不应承担垂直数据库职责。可选的付费工商/市场数据库优先通过合法账号和授权接口/GUI 使用；账号不可得时允许尝试其他通道并记录阻断（须经用户明确授权）。

## Firecrawl 适配

若存在 `FIRECRAWL_API_KEY`，可运行：

```powershell
.\run.cmd firecrawl_search.py "企业法定名 客户 供应商" --limit 10 --scrape
.\run.cmd firecrawl_search.py "企业法定名 中标" --include-domain ccgp.gov.cn --scrape
# 自建 Firecrawl：密钥只允许发往显式匹配的 HTTPS origin
.\run.cmd firecrawl_search.py "企业法定名 客户 供应商" `
  --base-url "https://firecrawl.internal.example" `
  --trusted-origin "https://firecrawl.internal.example" `
  --limit 10 --scrape
```

Firecrawl Search 提供独立搜索入口、`includeDomains/excludeDomains` 和搜索后抓取；适合候选发现与正文获取一体化。它不等于 Brave Search 的索引，也不能替代垂直数据库。无 API Key 时保持 `not_configured`，不得静默回退并宣称 Firecrawl 已执行。

### 月度积分硬限制

罗盘默认将 Firecrawl 的月度上限设为 **1,000 积分**。每次成功响应只把 `creditsUsed`、请求 ID 和 UTC 时间写入当前用户的紧凑账本：`%LOCALAPPDATA%\Luopan\firecrawl-usage.json`；不会保存查询文本、正文或 API Key。达到 1,000 后，适配器在**发送请求前**返回 `quota_exhausted`，不再调用 API；UTC 月份变化时自动开始新账本。

```powershell
# 默认：1,000 积分硬上限
.\run.cmd firecrawl_search.py "企业法定名 客户" --limit 5

# 查看本月用量账本
Get-Content "$env:LOCALAPPDATA\Luopan\firecrawl-usage.json"

# 特定一次实验的更小预算（不改变默认全局限额）
.\run.cmd firecrawl_search.py "企业法定名 客户" --monthly-credit-limit 100
```

`--scrape` 的积分消耗可能远高于单纯搜索（例如 PDF 的每页解析会计入 credits）；因此默认先不加 `--scrape` 做候选发现，只对已选择的少量高价值 URL 使用抓取。

官方 `https://api.firecrawl.dev` 是代码内固定的可信 origin。使用自建或代理端点时，`--base-url` 只接受无 path/query/userinfo 的 HTTPS origin，并且必须与 `--trusted-origin` 完全一致；跨 origin 重定向会剥离 `Authorization`。不要为了绕过该门禁把陌生域名写成可信 origin。

## 文档提取

- HTML 优先抽取正文并保留原始文件。
- PDF 优先使用本机已有 PDF 解析库；若系统 Python 缺少依赖，可探测已配置工具环境，不要直接放弃原始披露。
官方 `https://data.sec.gov/submissions/CIK##########.json` 可建立美国发行人的正式申报时间线。罗盘的 `source_discovery.py` 还提供轻量元数据发现（全部默认 `discovery_only`，不下载正文）：

```powershell
.\run.cmd source_discovery.py site-feed https://www.example.com/newsroom/ --out work\official-feed.json
.\run.cmd source_discovery.py sec-ticker AAPL --out work\sec-entity.json
.\run.cmd source_discovery.py sec-filings 320193 --limit 50 --out work\sec-filings.json
.\run.cmd source_discovery.py hkex-filings 700 20260101 20260131 --limit 100 --out work\hkex-filings.json
.\run.cmd source_discovery.py cninfo-filings 000001 gssz0000001 20260101 20260131 --limit 100 --out work\cninfo-filings.json
.\run.cmd external_discovery.py common-crawl example.com/* --out work\archive-urls.json
.\run.cmd external_discovery.py gdelt "Example Corp" --days 30 --out work\news-leads.json
```

HKEX 会先从其官方 active-stock metadata 解析内部 `stockId`，再调用 Listed Company Information Search；`NEWS_ID` 是增量键。CNINFO 的 `org_id` 必须来自其官方 stock metadata；`announcementId` 是增量键。二者的输出都只允许作为候选入口。使用 `source_intake.py` 将候选保存为每次研究独立的原始材料：

```powershell
.\run.cmd source_intake.py work\hkex-filings.json --out-dir raw\official-disclosures\hkex
```

该步骤只写 `raw/**/manifest.json` 与原始文件哈希，不会写 `research.json`、`sources[]`、`evidence[]` 或 `source_health[].source_ids`；PDF/HTML 仍须提取可定位原文并经证据审查后才能进入 `sources[]/evidence[]`。CNINFO 的元数据与官方静态文件、SEC 的 `data.sec.gov` 与 `www.sec.gov` Archives 是代码中明确列出的窄跨域链，其他跨域候选会被拒绝。查询空结果、非 JSON 和端点故障必须保留 `source_health` 的 `partial/unavailable` 状态，不得写成无披露。

抓取失败必须记录具体原因，例如地区 403、Cloudflare、重 JavaScript、PDF 解析器缺失；不得静默换成低质量转载。

## 原始材料目录

对垂直来源使用每次研究独立目录，例如：

```text
raw/
  procurement/manifest.json
  procurement/search/*.html
  procurement/details/*.html
  government-pdf/manifest.json
  government-pdf/pages/*.html
  government-pdf/pdf/*.pdf
  browser/manual-captures.json
```

`manifest.json` 是采集审计，不是研究结论。只有从原始页面/PDF提取、定位并写入 `evidence[]` 的内容才能支撑论断。
