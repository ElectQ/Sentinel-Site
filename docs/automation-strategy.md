# 自动化策略

> 状态：草案 · 2026-10-15
> 依据：对 `state/sources.json`、94 份 bundle、`git log` 的实测，以及对目标站点的直接探测
> 适用范围：Sentinel-Site 的采集健康与源维护

---

## 摘要

**自动化"发现"和"重复劳动"，不自动化"判断"。**

当前系统缺的是**发现**，不是**修复**。53 个源里有 17 个存在问题，而这些问题全部是靠人工翻 git 历史才找到的——本该是每天自动跑出来的。

策略重心：**先补检测（Layer 0），再谈修复（Layer 2）。**

---

## 一、现状实测（2026-10-15）

### 1.1 总量

| 指标 | 值 |
|---|---|
| 配置源 | 53 |
| bundle 历史 | 94 份，2026-07-14 ~ 2026-10-15 |
| 存在问题的源 | **17** |
| `last_ok_at` 最新 | 2026-10-14T23:49 |

### 1.2 问题源清单

#### A 类 · 路径退化（静默降级，最高优先级）

`method != collect_mode`，RSS 路径失效后退到 browser+LLM，**不进 `sources_failed`，健康简报看不见**。

| 源 | 声明 | 实际 | 证据 |
|---|---|---|---|
| `redsiege-blog` | rss | browser_llm | `https://redsiege.com/feed/` 返回 **403**（已实测） |
| `aff-wg` | rss | browser_llm | 10-04 为 `rss/0`，10-06 变 `browser_llm/1`，10-08 起 `feed_fail_streak=3` |
| `otterpwn` | rss | browser_llm | `feed_fail_streak=3` |
| `xpnsec-blog` | rss | browser_llm | `feed_fail_streak=3` |

> 注：`aff-wg` / `otterpwn` / `xpnsec-blog` 的 RSS 从本机住宅 IP 实测**可通**
> （分别返回 10 / 7 / 1 条），说明失败与出口 IP 相关。见 §2。

#### B 类 · `feed_fail_streak` 卡住（暴露代码缺陷，见 §3.2）

| 源 | feed_fail_streak | 当前 method |
|---|---|---|
| `denizhalil-blogs` | 7 | rss |
| `bhis-blog` | 3 | **rss**（现在能跑，值却没清零） |
| `fluxsec` | 3 | rss |
| `r136a1` | 3 | rss |
| `zgao` | 1 | rss |

`bhis-blog` 是 §3.2 缺陷的铁证：`method=rss` 说明当前正常，但 `feed_fail_streak` 永久停在 3。

#### C 类 · 配置错误（`home_url` 指错，永远不可能产出）

| 源 | 实测证据 |
|---|---|
| `tradecraftgarden` | `home_url` 指向 `index.html`，**4098 字节**，全页 **2 个 href**。是一篇具体的技术文章（SyntaxHighlighter 代码块），**不是文章列表** |
| `systeminformer-blog` | `https://www.systeminformer.com/blog` 返回 **2.7KB**，12 个 href **全是 CSS/favicon/CDN**，无文章容器 |

这两个源不是"坏了"，是"配错了"。正确动作是**人决定**：改 URL、改 `collect_mode`、或删源。

#### D 类 · 外部阻断（不可修）

Cloudflare 挑战，本机直连亦超时（12s）：

| 源 | 证据 | 60 天失败率 |
|---|---|---|
| `cobaltstrike-blog` | `cf_challenge_unresolved status=403`；候选 63 | 18% |
| `outflank-blog` | `cf_challenge_unresolved status=403` | 18% |
| `openai-research` | CF 403；`access_tested_at` 为空（从未验证过） | — |
| `xreous` | CF 403；本机直连超时 | 0%（静默） |

DNS 解析均在 Cloudflare 段（104.26.x / 104.18.x / 172.67.x）。

#### E 类 · 高频采集失败

| 源 | 94 天失败次数 |
|---|---|
| `redsiege-blog` | **42** |
| `cobaltstrike-blog` | 13 |
| `lorenzomeacci` | 12 |
| `outflank-blog` | 12 |
| `denizhalil-blogs` | 7 |
| `r136a1` | 4 |
| `fluxsec` | 3 |
| `unknowncheats-ac` | 3 |
| `ibm-xforce` | 2 |
| `openai-research` / `zgao` | 1 |

---

## 二、根因：环境错配

```
config/sources.yaml 中 7 个源标记：
    access_tested_via: local_proxy_127.0.0.1:7890
    access_tested_at:  2026-07-14        ← 3 个月前，之后未复核

.github/workflows/daily-pulse.yml：
    未配置任何代理
    （src/sentinel/collectors/browser.py 会读 HTTPS_PROXY / HTTP_PROXY，
      但 CI 里一个都没设）
```

**这 7 个源的 `access_status` 描述的不是生产环境。**

| 源 | access_status | 验证方式 |
|---|---|---|
| `ibm-xforce` | intermittent | local_proxy_127.0.0.1:7890 |
| `unknowncheats-ac` | browser_required | local_proxy_127.0.0.1:7890 |
| `xreous` | browser_required | local_proxy_127.0.0.1:7890 |
| `cobaltstrike-blog` | browser_required | local_proxy_127.0.0.1:7890 |
| `safebreach-blog` | intermittent | local_proxy_127.0.0.1:7890 |
| `outflank-blog` | browser_required | local_proxy_127.0.0.1:7890 |
| `openai-research` | browser_required | **（未验证）** |

**后果**：源的可达性结论在代理环境下得出，生产在 GitHub Actions 裸 IP 上运行，导致 RSS 路径系统性失效 → 静默降级到 browser+LLM → 成本上升、产出下降。

---

## 三、已确认的代码缺陷

### 3.1 失败时 state 不落盘 → `fail_streak` 恒为 0

`src/sentinel/run.py`：

```python
for src in sources:
    result = articles_mod.collect_one(src, st, collected_at=now_iso)
    if not result["ok"]:
        failed.append({"id": src.id, "error": result.get("error")})
        continue                      # ← 跳过了下面的 save_sources
    ...
    state_mod.save_sources(st)        # 只有成功的源才走到这里
```

`collect_one` 在失败分支里做了 `sst["fail_streak"] += 1`，但 `run.py` 立即 `continue`，**该自增只存在于内存，从不落盘**。

实测 `state/sources.json`：

```
fail_streak   → 出现 0 次
last_new_at   → 出现 0 次
last_error    → 出现 0 次
last_ok_at    → 出现 53 次
```

**后果**：`sync_github_issues` 的 `streak >= ALERT_FAIL_STREAK(3)` 永远为假，**告警 issue 一个都创建不出来**。

### 3.2 L1 路径成功时不重置 `feed_fail_streak`

`src/sentinel/collectors/articles.py`：

```python
# L1：配置的 rss_url
if use_feed and source.rss_url:
    raw_items, err = rss.fetch_and_parse(feed_url)
    if err is None:
        via = "rss"                     # ← 没有重置 feed_fail_streak

# L2：remembered resolved feed
if use_feed and not via and sst.get("resolved_feed_url"):
    if err is None:
        via = "rss"
        sst["feed_fail_streak"] = 0     # ← 只有这里重置
```

所有 `collect_mode: rss` 的源都配了 `rss_url`，走 L1。**一旦失败过，`feed_fail_streak` 永久卡在历史值。**

### 3.3 未提交的工作区改动

```
 M .github/workflows/daily-pulse.yml      ← 新增 issues: write
 M src/sentinel/run.py                    ← +246 行：report_health / sync_github_issues / check_artifacts
 M src/sentinel/collectors/articles.py    ← fail_streak / last_new_at
 M src/sentinel/state.py
 M src/sentinel/analyzers/feed.py
 M src/sentinel/collectors/content.py
?? tests/test_health.py                    ← 未跟踪
```

`git show HEAD:src/sentinel/run.py | grep -c sync_github_issues` → **0**。

**健康检查与自动 issue 的全部代码只存在于本地，从未在生产运行过。**

---

## 四、自动化策略

### 核心原则

- **自动化"发现"和"重复劳动"，不自动化"判断"。**
- **制定标准必须人做，执行标准可以机器做。**
- **闸门位置由"失败是否响亮"决定。** 本系统的失败是静默的，所以闸门必须靠前。

### Layer 0 · 检测（全自动）— 现在就该做

5 个信号，全部从现有 state 读取，零额外采集成本：

| # | 信号 | 说明 | 当前可抓出 |
|---|---|---|---|
| 1 | `method != collect_mode` | **最干净**，直接说明"源没走该走的路" | 4 个 |
| 2 | `feed_fail_streak > 0` | 需先修 §3.2，否则卡住的值会误报 | 8 个 |
| 3 | bundle 的 `sources_failed` | 已在用 | 11 个 |
| 4 | `max(candidate.last_seen)` 停滞 | 仅对非 RSS 源有效 | 1 个 |
| 5 | `seen` 增长低于该源自身基线 | 需按源计算，勿用统一阈值 | 待定 |

输出：GitHub issue + 飞书提醒。

### Layer 1 · 分类（全自动）

agent 读 issue，只做分派，不做修复：

| 分类 | 判定 | 处理方 |
|---|---|---|
| `config-error` | `home_url` 指错 / 页面无文章列表 | 人决定 |
| `path-degraded` | `method != collect_mode` | 机器可试 |
| `blocked` | CF 403 / 验证码 / 需登录 | 人决定，agent 不碰 |
| `parse-broken` | 候选提取失败 | 机器可试（需 fixture） |
| `transient` | < 3 次失败且有恢复史 | 忽略，仅记录 |

**分类本身是最大价值**：把 53 个源的问题压缩成 5 类，每类有确定的处理路径。

### Layer 2 · 执行（分级自动化）

| 动作 | 自动化程度 | 理由 |
|---|---|---|
| 试替代 feed URL（`/feed/` → `/rss/` → `discover_feed`） | 全自动 + 自动合并 | 纯配置，可回滚，爆炸半径 = 1 个源 |
| 按 `source-recipes/` 套模板 | 全自动 + 自动合并 | 同上 |
| 改解析逻辑 | 自动提 PR，**人 merge** | 爆炸半径大 |
| 改共享 prompt | 自动提 PR + **全源 fixture 回归**，人 merge | 爆炸半径 = 22 个非 RSS 源 |
| 改阈值 / `report_health` / `enabled` | **禁止** | 防止 agent 让自己"看起来成功" |
| 标 `blocked` | 只能建议，**人确认** | 合规判断 |

### Layer 3 · 加新源（全自动 + 一次确认）

```
浏览器插件采 fixture（渲染后 DOM + 正样本 + 负样本 + 登录态标记）
  ↓
agent 查 docs/source-recipes/ → 选配方 → 生成 sources.yaml 条目
  ↓
离线验证（不打网络）：正样本必须全中 / 负样本必须 0 / 改版样本必须挂
  ↓
rss 且验证全过 → 自动合并
非 rss 或新建配方 → 人审
```

**这是唯一随规模增长的重复劳动，长期 ROI 最高。**

> **插件定位**：不是"加一个 URL"，是**采集带标注的 fixture**。
> 没有 fixture，agent 无法验证自己；活体探测（`sources.py check`）flaky 且会给出假阴性。

### Layer 4 · 复盘（全自动）

```
每周：agent 复盘已关闭的 issue
  → 同类问题出现 3 次 → 升格进 docs/code-standards.md 或 docs/source-recipes/
```

**这一层让人的输入量正比于"问题种类"，而非"问题次数"。**

---

## 五、明确不自动化的

| 事项 | 理由 |
|---|---|
| fixture 正负样本的**首次**录制 | ground truth，agent 自录 = 自己出题自己考 |
| `source-recipes/` 的**首次**编写 | 这是知识，不是执行 |
| `blocked` 源的放弃决策 | 合规边界（见 `Source` dataclass 注释：*"not permission to evade an access-control wall"*） |
| 合并到 main（初期） | 本系统失败静默，闸门必须靠前 |
| 通知中间件 / 多通道路由 | 53 个源、每天 1 次，不需要 |

---

## 六、触发式投资

每层的启动条件是**可观测的**，不是日程表：

| 层 | 启动条件 | 当前是否满足 |
|---|---|---|
| **Layer 0 检测** | 立即 | ✅ **做** |
| Layer 1 分类 | 检测层产出 > 3 issue/周 | 预计 ✅ |
| Layer 3 加新源 | 每周加源耗时 > 1 小时 | ❓ 取决于加源频率 |
| Layer 2 解析修复 | 每月解析故障 > 4 次 | ❌ 现约 0-2 次 |
| Layer 2 自动合并 | 每周审 PR > 5 次 | ❌ |

**Layer 2 的解析修复当前不满足启动条件。** 每月 0-2 次故障，为此建 5 周工程，回本周期约两年。

---

## 七、立即行动项

### 1. 修 CI 环境（约半天）

- 给 GitHub Actions 配置代理，或确认出口 IP 的直连能力
- 重新实测 §2 表中 7 个源的可达性
- 更新 `access_tested_at` / `access_tested_via`
- **预期效果：4 个"路径退化"的源可能自行恢复**

### 2. 修代码缺陷 + 配置（约 1 小时）

- [ ] `src/sentinel/run.py`：`save_sources` 移到 `continue` 之前（§3.1）
- [ ] `src/sentinel/collectors/articles.py`：L1 成功时也重置 `feed_fail_streak`（§3.2）
- [ ] `tradecraftgarden`：改 URL 或删源（§1.2 C 类）
- [ ] `systeminformer-blog`：改 URL 或删源（§1.2 C 类）
- [ ] 4 个 CF 403 源标 `access_status: blocked` 并 `enabled: false`

### 3. 提交健康检查 + 新增信号（约 1 天）

- [ ] 提交 §3.3 列出的全部工作区改动
- [ ] `daily-pulse.yml` 增加 `STRICT: "1"`（否则全源失败也 exit 0）
- [ ] 将 `report_health` 的 warnings 也传给 `sync_github_issues`
      （当前只有 `failed` 会变成 issue，产物异常/长期静默永远不会）
- [ ] **新增 `method != collect_mode` 检测** ← 投入产出比最高的一行

### 4. 复核

做完 1-3 后重新统计问题源数量。**预期从 17 降至 3~5。** 届时应重新评估 Layer 1/2 的必要性。

---

## 八、目标状态

三个月后的一天：

```
05:00  CI 采集 53 个源
05:15  Layer 0 检测 → 2 个异常
05:16  Layer 1 分类
         aff-wg           → path-degraded（RSS 失效，browser 兜底中）
         tradecraftgarden → config-error（home_url 是文章不是列表）
05:20  Layer 2 执行
         aff-wg           → 试 3 个候选 feed，找到可用的 → 提 PR → 自动合并
         tradecraftgarden → 无法自动决定 → 挂 sentinel-needs-human
05:30  飞书推一条：
         🔧 1 个需要决策: tradecraftgarden
         📊 日报: 53 源 / 51 正常 / 2 异常 / 47 篇新文章
05:31  bundle 产出

上午   人看飞书 → issue 里回一句「tradecraftgarden 删掉」→ agent 执行 → 关 issue
```

**人的日常动作：看一眼飞书，回一句话。**

目标指标：

| 指标 | 现在 | 目标 |
|---|---|---|
| 发现坏源 | 靠人工翻 git | **自动** |
| 加一个新源 | 30~60 分钟 | 10~15 分钟 |
| 每周人介入 | 不定 | **≤ 3 次** |
| 每月人决策 | — | **≤ 5 次** |

---

## 附录：指标口径更正（重要）

**不要用 `selected / candidates` 计算"选中率"。这两个都是累积量，不是当次快照。**

```
candidates  = 曾经出现过的候选 URL 集合         （只增不减，CAP = CANDIDATE_CAP_PER_SOURCE）
selected    = 曾被 LLM 选中过的候选的粘性布尔   （一旦 True 永远 True）
```

`src/sentinel/collectors/llm_fallback.py:_denoise_with_html`：

```python
known_urls = set(seen) | set(candidate_state)
eligible = [c for c in candidates if c["url"] not in known_urls]
if not eligible:
    return [], None, candidates      # err=None → ok=True
```

**稳定站点的首页链接，第二天就全部进入 `candidate_state` → `eligible` 永远为空 → `selected` 不再增长。**

实测 `aff-wg`：

```
首页文章链接数:              16
其中已在 candidate_state:    16     ← 全部
剩余 eligible（进入 LLM）:     0
```

**因此 `selected = 0` 是稳定站点的正常状态，不是故障信号。** 用它的比率判断健康会产生 100% 误报。

有效的替代信号见 §4 Layer 0。

---

## 附录：已验证的事实清单

| 结论 | 验证方式 |
|---|---|
| `redsiege.com/feed/` 返回 403 | 直接 HTTP 请求 |
| `aff-wg.org/feed/` 返回 200，10 items | 直接 HTTP 请求 + `rss.fetch_and_parse()` |
| `blog.otterpwn.com/index.xml` 返回 200，7 items | 直接 HTTP 请求 |
| `blog.xpnsec.com/rss.xml` 返回 200，1 item | 直接 HTTP 请求 |
| `tradecraftgarden.org/index.html` = 4098 字节，2 href | 直接 HTTP 请求 |
| `systeminformer.com/blog` = 2.7KB，12 href 全为 CSS | 直接 HTTP 请求 |
| `aff-wg.org` 首页可提取 17 个候选（16 文章 + /about/） | 运行 `html_links.extract_candidates()` |
| `state/sources.json` 无 `fail_streak` / `last_new_at` / `last_error` | `grep -c` |
| HEAD 版 `run.py` 无 `sync_github_issues` | `git show HEAD:...` |
| `candidates` 在 7 天内几乎不变（累积集合） | 逐 commit 比对 `state/sources.json` |
