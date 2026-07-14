# Sentinel-Site

每日运行在 GitHub Actions 上的博客 / 官网 **新文章去噪采集器**（Collector，不是 Agent）。

契约形态对齐 [ElectQ/Sentinel-gh](https://github.com/ElectQ/Sentinel-gh) / [ElectQ/Soundwave](https://github.com/ElectQ/Soundwave)：`bundles/` 给下游（如 Megatron），`data/` 是内部归档。

- 按 **`config/sources.yaml`** 管理监控源（开关、采集渠道、标签、RSS）
- 新源先验证并显式标记 `rss`、`html_llm` 或 `browser_llm`
- RSS 与 URL state diff；HTML/LLM 与稳定 DOM 候选首次出现状态 diff
- 首跑建 baseline，不灌历史

## 数据契约（Megatron raw HTTP）

| 文件 | 说明 |
| --- | --- |
| **`bundles/index.json`** | 入口 + 就绪标记（`latest` / `days[]` / `sha256`） |
| **`bundles/YYYY-MM-DD.json`** | 当日新增文章（北京日期） |
| `data/articles/*` | 内部归档 |
| `data/feed/*` | 内部 feed |
| `state/sources.json` | 每源文章 seen / DOM candidates / resolved feed |

```
https://raw.githubusercontent.com/ElectQ/Sentinel-Site/main/bundles/index.json
https://raw.githubusercontent.com/ElectQ/Sentinel-Site/main/bundles/<date>.json
```

```bash
BASE=https://raw.githubusercontent.com/ElectQ/Sentinel-Site/main/bundles
curl -s "$BASE/index.json" | jq '{latest, days: (.days|length)}'
curl -s "$BASE/$(curl -s "$BASE/index.json" | jq -r .latest).json" \
  | jq '.stats, (.items[0] | {id, who, action, target, target_url, url, text, at})'
```

去重键：`(source_id, external_id)`，`source_id = blog_watch`。

### Bundle 条目（`items[]`）

| 字段 | 含义 |
| --- | --- |
| `url` / `target_url` | **文章链接（主产物）** |
| `title` / `target` | 标题 |
| `who` / `author` | 配置源 id |
| `action` | `publish` |
| `text` | 一句话发布事件描述（兼容 Sentinel-gh） |
| `content` | 清洗后的文章正文；失败时回退为 `text` |
| `content_status` | `ok` / `partial` / `failed` |
| `content_via` | `rss` / `http` / `browser` / `rss_summary` |
| `tags` | `kind:publish`, `src:<id>`, `via:<实际方式>`, `channel:<配置渠道>` |
| `external_id` | `a:` + sha1(url)[:16]（≤64） |

### Megatron 接入示例

```yaml
source_id: blog_watch
display_name: Blog Watch
adapter: bundle_pull
enabled: true
schedule:
  cron: "40 22 * * *"
config:
  index_url: https://raw.githubusercontent.com/ElectQ/Sentinel-Site/main/bundles/index.json
  verify_sha256: true
  max_days: 7
  external_repo: ElectQ/Sentinel-Site
```

## 管理监控源

编辑 `config/sources.yaml`：

```yaml
sources:
  - id: redheadsec
    name: RedHeadSec
    home_url: https://redheadsec.tech/
    rss_url: https://redheadsec.tech/rss/
    collect_mode: rss
    strip_query_keys: []                    # 可选：移除会话类动态查询参数
    tags: [blog]
    enabled: true
    notes: ""
```

```bash
uv run python -m sentinel.sources list
uv run python -m sentinel.sources validate
uv run python -m sentinel.sources check redheadsec
```

| `collect_mode` | 用途 |
| --- | --- |
| `rss` | 使用已验证的 `rss_url`，Feed 故障时才进入页面兜底 |
| `html_llm` | 普通 HTTP 获取 DOM，LLM 分类；明确 403/超时时可转 Playwright |
| `browser_llm` | 直接使用 Playwright 渲染 DOM，再由 LLM 分类 |

访问状态也保存在同一源配置中，便于把“正常直连”和“依赖回退”区分开：

| `access_status` | 含义 |
| --- | --- |
| `direct` | 当前普通 HTTP/RSS 可用 |
| `browser_required` | 当前普通 HTTP 被拒绝，但标准 Playwright 获取已验证 |
| `intermittent` | 当前可用，但有历史 403/TLS/Feed 波动，保留回退 |
| `blocked` | 普通 HTTP 和标准浏览器都失败；必须 `enabled: false` |

`access_issue`、`access_tested_at` 和 `access_tested_via` 记录最近一次实测证据。该状态是时间与网络出口相关的运行记录，不代表第三方站点永久可用。

新增来源时先运行 `validate` 做配置检查，再用 `check <id>` 按配置渠道实测。只有验证成功后才设 `enabled: true`。

### 新增源上线流程

1. 在 `config/sources.yaml` 添加一个稳定且永不复用的 `id`，先设 `enabled: false`。
2. 优先寻找站点官方 RSS/Atom；确认可用时用 `collect_mode: rss`。
3. 没有 Feed 的静态列表页用 `html_llm`；必须渲染或普通 HTTP 被拒绝时用 `browser_llm` 并设 `browser_fallback: true`。
4. 运行 `uv run python -m sentinel.sources validate`，再运行 `uv run python -m sentinel.sources check <id>`。
5. 检查候选是否都是同域内容，按需配置 `allowed_hosts`、`strip_query_keys`、`ssl_verify` 和 `browser_fallback`。
6. 非 RSS 源还要抽查至少一个真实详情页，确认 `content_status=ok` 且正文没有导航/广告噪声。
7. 验证通过后改为 `enabled: true`，提交配置并手动触发一次 `daily-pulse`。首次成功运行只建立 baseline，不灌历史。
8. 后续运行只处理 baseline 之后首次出现的规范化 URL；在 `bundle.stats.sources_failed`、`llm_usage` 和 `content_status` 中检查健康度。

常用配置字段：

| 字段 | 用途 |
| --- | --- |
| `id` | 稳定源标识；发布后不要修改或复用 |
| `home_url` | RSS 发现或非 RSS 列表页入口 |
| `rss_url` | 已验证的官方 RSS/Atom 地址 |
| `collect_mode` | `rss` / `html_llm` / `browser_llm` |
| `allowed_hosts` | 允许文章跳转到的同一内容域名集合 |
| `strip_query_keys` | 去掉会话、排序等会导致重复的动态查询参数 |
| `browser_fallback` | 普通 HTTP 失败时允许 Playwright |
| `ssl_verify` | 仅代理 MITM/坏证书源按需关闭校验 |
| `tags` / `notes` | 内容类型和运维说明 |

当前没有默认禁用源。`cobaltstrike-blog` 在 2026-07-14 本机 7890 代理环境下验证为“普通 HTTP 403、标准 Playwright 可读取列表”；GitHub 托管 Runner 的直连可用性仍应由每日健康结果持续确认。

## 工作原理

1. 按 `collect_mode` 使用 RSS、普通 HTML 或无头 Chromium
2. HTML 页面先确定性提取并规范化最多 80 个 DOM 候选 URL
3. DeepSeek 只从候选表中分类文章，禁止生成候选表外 URL
4. 只有从未出现过的候选才交给 LLM；无 key 或模型失败时该源失败关闭，不让宽松规则污染结果
5. RSS URL 与文章 `seen` 比较
6. HTML/LLM 候选另存 `first_seen`、`baseline`、`selected`，只输出 baseline 后首次出现且被分类为文章的 URL
7. 只对新增 URL 获取正文：RSS 优先使用 Feed 全文；HTML 先直连；无头源复用列表页的浏览器 context
8. 清洗正文并写入 `bundles/` + `data/`，Megatron 不需要再次启动浏览器

HTML/LLM 不比较整页 HTML。页面导航、广告和排序变化不会直接产生更新；每个新候选只在首次出现时分类，已拒绝或已收录的 URL 不会每天重复消耗 Token；首跑 baseline 中的旧链接不会因为提示词变化而误报。

这里的“每日”是调度频率，不是发布日期过滤条件：RSS 以规范化文章 URL 对 `seen` 做差集，HTML/浏览器源以规范化 DOM URL 对 `candidates` 做差集。即使文章发布时间较早，只要它是 Feed 延迟送达或本次第一次观察到的新 URL，仍会被处理；相反，同一 URL 的正文后来被修改不会再次发布。北京日期只决定 `bundles/YYYY-MM-DD.json` 的归档文件名。

正文按不可信输入处理：移除脚本、表单、导航和常见页面噪声，只保存纯文本与 SHA-256，不保存或执行网页脚本、附件和 iframe。`text` 保持 Sentinel-gh 风格的一句话事件；`content` 是供 Megatron 分析的正文扩展。

LLM 同样按不可信输入边界运行：程序先做同域 URL 规范化、广告/导航过滤和 state diff，只把从未出现过的候选编号、标题、路径及局部上下文交给模型；网页中的提示或指令不能改变任务，模型只能返回候选整数编号，不能生成 URL、选择器或执行动作。正文优先由 JSON-LD、语义标签和已验证的论坛/博客 DOM 规则提取，LLM 只作为确定性提取失败后的有限选择器。

内容边界是“技术相关而非纯政治/纯生活”：收录技术文章、安全研究、漏洞公告、技术新闻、产品或版本的技术发布新闻、事故报告、论坛讨论、问答与故障排查；日常场景中发现并讨论真实技术问题也收录。排除以政治立场为主且没有直接技术内容的文章、无技术信息的个人生活动态、广告、营销落地页和纯工具导航页。

难站在 `config/sources.yaml` 设 `browser_fallback: true`；TLS 被代理中间人破坏时可 `ssl_verify: false` 或 env `SSL_INSECURE_HOSTS=example.com`。

```bash
uv sync
uv run playwright install chromium
export https_proxy=http://127.0.0.1:7890 http_proxy=http://127.0.0.1:7890
export LLM_API_KEY=...
uv run python -m sentinel.run
```

## 配置（环境变量）

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `LLM_API_KEY` | — | L3 需要（也认 `DEEPSEEK_API_KEY`） |
| `LLM_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容 base |
| `LLM_MODEL` | `deepseek-v4-flash` | 可改为 `deepseek-v4-pro` |
| `PROBE_NEW_URLS` | `1` | 仅探测**新** URL；`0` 关闭 |
| `FEED_MAX_ITEMS` | `100` | 单个 RSS/Atom 每次最多解析的近期条目数 |
| `BROWSER_USER_AGENT` | 自动匹配浏览器 | 可选的无头浏览器 UA 覆盖值 |
| `BROWSER_EXECUTABLE_PATH` | Playwright bundled Chromium | 指向已有 Chrome/Chromium；GitHub Action 使用 `/usr/bin/google-chrome`，不下载浏览器 |
| `STRICT` | `0` | `1` 时任源失败 job 失败 |
| `ALLOW_HEURISTIC_FALLBACK` | `0` | 仅诊断用；`1` 时 LLM 缺失/失败后允许宽松规则，生产环境不建议开启 |
| `SEEN_CAP_PER_SOURCE` | `500` | 每源 seen 上限 |
| `CANDIDATE_CAP_PER_SOURCE` | `1000` | 每个 HTML/LLM 源保存的候选 URL 状态上限 |
| `CONTENT_MAX_CHARS` | `60000` | Bundle 中单篇清洗正文最大字符数 |
| `CONTENT_MIN_CHARS` | `200` | 页面正文成功判定的最小字符数 |
| `CONTENT_RSS_MIN_CHARS` | `800` | Feed 内容达到该长度时视为全文，不再访问文章页 |
| `SENTINEL_ROOT` | `.` | 仓库根 |

## 本地开发

```bash
uv sync
export LLM_API_KEY=...   # 仅无 RSS 源需要
uv run python -m sentinel.run
# 再跑一次：首跑 baseline 后才会 emit 新文
uv run python -m sentinel.run
```

## 调度

- `daily-pulse.yml`：每日 UTC 21:00，即次日北京时间 05:00 + `workflow_dispatch`
- 必需 Secret：`LLM_API_KEY`
- GitHub 托管 Runner 使用自身网络直连，不设置代理；`127.0.0.1:7890` 只用于本机验证
- GitHub `ubuntu-latest` 直接使用镜像内置的 `/usr/bin/google-chrome`，不会下载 Playwright Chromium
- 自托管 Runner 可通过 `BROWSER_EXECUTABLE_PATH` 指向本机已有 Chrome/Chromium
- bot 提交 `bundles/` `data/` `state/`

GitHub 配置步骤：在仓库 `Settings → Secrets and variables → Actions` 添加 Secrets，启用 Actions 的读写权限，然后在 `Actions → daily-pulse → Run workflow` 手动完成首次 baseline。不要删除或手工回退 `state/sources.json`；它是增量差集依据。CI 会在每次 push/PR 自动检查源配置、运行回归测试并编译包。
