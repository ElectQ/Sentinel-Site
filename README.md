# Sentinel-Site

Sentinel-Site is a daily **technology-content collector**. It monitors security blogs, vendor advisories, technical projects, and engineering communities, detects newly discovered articles, extracts their content, and publishes machine-readable bundles for downstream systems such as Megatron.

It runs on GitHub Actions and is a collector, not an autonomous agent.

## Design goals

- Monitor a curated set of technical sources.
- Prefer official RSS/Atom feeds where available.
- Use HTTP or Playwright for sources without a usable feed.
- Use an LLM only where page structure requires article classification or content-block selection.
- Keep incremental state so previously seen URLs are not normally emitted again.
- Preserve source failures and content status in the output instead of hiding them.
- Treat web pages and extracted text as untrusted input.

## Pipeline

Each daily run:

1. Reads enabled sources from `config/sources.yaml`.
2. Collects entries through RSS/Atom, ordinary HTTP, or Playwright.
3. Normalizes URLs and removes tracking/session parameters, navigation links, and obvious promotions.
4. Compares URLs with `state/sources.json` and the cross-run emitted ledger.
5. Uses DeepSeek to classify new HTML candidates when deterministic rules are not sufficient.
6. Fetches and cleans the content of newly emitted articles.
7. Writes the daily feed, bundle, archive, and updated state.

Network timeouts and transient 429/5xx responses receive limited retries. Existing bundles bootstrap the emitted ledger, so items are not re-emitted after a state reset. The collection date is the Beijing date of the run; a feed-delayed article may be published earlier but discovered today.

## Collection modes

| Mode | Description |
| --- | --- |
| `rss` | Read the configured RSS/Atom feed. On failure, try a remembered or discovered feed, then fall back to the source page. |
| `html_llm` | Fetch the page over HTTP, extract candidate links, and use the LLM to classify new candidates. |
| `browser_llm` | Render the page with Playwright, then classify candidate links with the LLM. |

Current inventory: 55 enabled (35 `rss`, 10 `html_llm`, 10 `browser_llm`), 1 disabled.

## Source inventory

[`config/sources.yaml`](config/sources.yaml) is the single source of truth for the inventory. The table below is generated from it — edit the yaml, then run `python -m sentinel.source_table` (CI enforces this).

<!-- source-table:begin (auto-generated, do not edit) -->
Current inventory: 55 enabled (35 `rss`, 10 `html_llm`, 10 `browser_llm`), 1 disabled.

| ID | Source | Home / feed | Mode |
| --- | --- | --- | --- |
| `zdi-advisories` | Zero Day Initiative Advisories | [home](https://www.zerodayinitiative.com/advisories/published/) | `html_llm` |
| `mixbytes-blog` | MixBytes Blog | [home](https://mixbytes.io/blog) | `html_llm` |
| `ibm-xforce` | IBM Security Intelligence X-Force | [home](https://www.ibm.com/think/x-force) | `browser_llm` |
| `unknowncheats-ac` | UnknownCheats Anti-Cheat | [home](https://www.unknowncheats.me/forum/general-programming-and-reversing/) | `browser_llm` |
| `idov31-posts` | Ido Veltzman Posts | [home](https://idov31.github.io/posts) | `html_llm` |
| `redheadsec` | RedHeadSec | [home](https://redheadsec.tech/) · [feed](https://redheadsec.tech/rss/) | `rss` |
| `cocomelonc` | cocomelonc | [home](https://cocomelonc.github.io/) · [feed](https://cocomelonc.github.io/feed.xml) | `rss` |
| `yage-ai` | yage.ai | [home](https://yage.ai/) · [feed](https://yage.ai/feeds/atom.xml) | `rss` |
| `yage-share` | yage.ai share (Deep News) | [home](https://yage.ai/share/) · [feed](https://yage.ai/share/feed.xml) | `rss` |
| `rastamouse` | Rasta Mouse | [home](https://rastamouse.me/) · [feed](https://rastamouse.me/rss/) | `rss` |
| `naksyn-posts` | Naksyn posts | [home](https://naksyn.com/posts/) · [feed](https://naksyn.com/atom.xml) | `rss` |
| `lorenzomeacci` | Lorenzo Meacci | [home](https://lorenzomeacci.com/) | `html_llm` |
| `voltatech-blog` | VoltaTech Blog | [home](https://voltatech.in/blog/) · [feed](https://voltatech.in/feed_rss_created.xml) | `rss` |
| `xreous` | Xreous | [home](https://xreous.io/posts/) | `browser_llm` |
| `aff-wg` | Adversary Fan Fiction Writers Guild (Tradecraft Garden) | [home](https://aff-wg.org/) · [feed](https://aff-wg.org/feed/) | `browser_llm` |
| `deadeclipse-blog` | Nightmare Eclipse (Blogspot) | [home](https://deadeclipse666.blogspot.com/) · [feed](https://deadeclipse666.blogspot.com/feeds/posts/default?alt=rss) | `rss` |
| `zusda` | zusda | [home](https://zusda.github.io/) | `html_llm` |
| `sud0ru` | Sud0Ru | [home](https://sud0ru.ghost.io/) · [feed](https://sud0ru.ghost.io/rss/) | `rss` |
| `fushuling` | fushuling | [home](https://fushuling.com/) | `html_llm` |
| `otterpwn` | OtterPwn Blog | [home](https://blog.otterpwn.com/) · [feed](https://blog.otterpwn.com/index.xml) | `browser_llm` |
| `fluxsec` | FluxSec *(disabled)* | [home](https://fluxsec.red/) · [feed](https://fluxsec.red/rss.xml) | `rss` |
| `r136a1` | R136a1 | [home](https://r136a1.dev/) · [feed](https://r136a1.dev/feed.xml) | `rss` |
| `denizhalil-blogs` | DenizHalil Blogs | [home](https://denizhalil.com/blogs/) · [feed](https://denizhalil.com/feed/) | `rss` |
| `lolbas` | LOLBAS Project | [home](https://lolbas-project.github.io/) | `html_llm` |
| `cobaltstrike-blog` | Cobalt Strike Blog | [home](https://www.cobaltstrike.com/blog) | `browser_llm` |
| `bruteratel-blog` | Brute Ratel Blog | [home](https://bruteratel.com/blog/) · [feed](https://bruteratel.com/feed.xml) | `rss` |
| `safebreach-blog` | SafeBreach Blog | [home](https://www.safebreach.com/blog/) | `browser_llm` |
| `sandflysecurity-blog` | Sandfly Security Blog | [home](https://sandflysecurity.com/blog) · [feed](https://sandflysecurity.com/blog/rss.xml) | `rss` |
| `hacktron-blog` | Hacktron AI Blog | [home](https://www.hacktron.ai/blog) · [feed](https://www.hacktron.ai/rss.xml) | `rss` |
| `whiteknightlabs-blog` | White Knight Labs Blog | [home](https://whiteknightlabs.com/blog/) · [feed](https://whiteknightlabs.com/feed/) | `rss` |
| `systeminformer-blog` | System Informer Blog | [home](https://www.systeminformer.com/blog) | `html_llm` |
| `xlab-qianxin` | QiAnXin XLab Blog | [home](https://blog.xlab.qianxin.com/) · [feed](https://blog.xlab.qianxin.com/rss/) | `rss` |
| `adsecurity` | ADSecurity.org | [home](https://adsecurity.org/) · [feed](https://adsecurity.org/?feed=rss2) | `rss` |
| `outflank-blog` | Outflank Publications | [home](https://www.outflank.nl/blog/) | `browser_llm` |
| `g3tsyst3m` | G3tSyst3m Infosec Blog | [home](https://g3tsyst3m.com/) · [feed](https://g3tsyst3m.com/feed.xml) | `rss` |
| `z3bra` | Z3bra | [home](https://z3bra.cat/) · [feed](https://z3bra.cat/index.xml) | `rss` |
| `cymulate-blog` | Cymulate Blog | [home](https://cymulate.com/blog/) | `html_llm` |
| `xpnsec-blog` | XPN InfoSec Blog | [home](https://blog.xpnsec.com/) · [feed](https://blog.xpnsec.com/rss.xml) | `browser_llm` |
| `zgao` | Zgao Blog | [home](https://zgao.top/) · [feed](https://zgao.top/feed/) | `rss` |
| `redsiege-blog` | Red Siege Blog | [home](https://redsiege.com/red-siege-blog/) · [feed](https://redsiege.com/feed/) | `rss` |
| `itm4n` | itm4n Blog | [home](https://itm4n.github.io/) · [feed](https://itm4n.github.io/feed.xml) | `rss` |
| `cognisys-labs` | Cognisys Group Labs | [home](https://labs.cognisys.group/) · [feed](https://labs.cognisys.group/feed.xml) | `rss` |
| `bhis-blog` | Black Hills Information Security Blog | [home](https://www.blackhillsinfosec.com/blog/) · [feed](https://www.blackhillsinfosec.com/blog/feed/) | `rss` |
| `cisco-advisory` | Cisco Security Advisory | [home](https://sec.cloudapps.cisco.com/security/center/psirtrss20/CiscoSecurityAdvisory.xml) · [feed](https://sec.cloudapps.cisco.com/security/center/psirtrss20/CiscoSecurityAdvisory.xml) | `rss` |
| `forti-ir` | FortiGuard IR Advisories | [home](https://fortiguard.fortinet.com/rss/ir.xml) · [feed](https://filestore.fortinet.com/fortiguard/rss/ir.xml) | `rss` |
| `ivanti-advisory` | Ivanti Security Advisory | [home](https://www.ivanti.com/blog/topics/security-advisory) · [feed](https://www.ivanti.com/blog/topics/security-advisory/rss) | `rss` |
| `paloalto-advisory` | Palo Alto Networks Security Advisories | [home](https://security.paloaltonetworks.com/) · [feed](https://security.paloaltonetworks.com/rss.xml) | `rss` |
| `mist-security` | Mist Security Alerts | [home](https://www.mist.com/documentation/category/security-alerts/) · [feed](https://www.mist.com/documentation/category/security-alerts/feed/) | `rss` |
| `sonicwall-advisory` | SonicWall Security Advisories | [home](https://psirt.global.sonicwall.com/) · [feed](https://psirtapi.global.sonicwall.com/api/v1/feed/rss.xml) | `rss` |
| `watchtowr-labs` | watchTowr Labs | [home](https://labs.watchtowr.com/) · [feed](https://labs.watchtowr.com/rss/) | `rss` |
| `openai-research` | OpenAI Research | [home](https://openai.com/zh-Hans-CN/research/index/) | `browser_llm` |
| `anthropic-research` | Anthropic Research | [home](https://www.anthropic.com/research) | `html_llm` |
| `matheuzsecurity` | Matheuz Security | [home](https://matheuzsecurity.github.io/hacking/) · [feed](https://matheuzsecurity.github.io/hacking/index.xml) | `rss` |
| `guysrd` | Guy Shandy | [home](https://guysrd.github.io) · [feed](https://guysrd.github.io/feed.xml) | `rss` |
| `msrc` | Microsoft Security Update Guide | [home](https://msrc.microsoft.com/update-guide) · [feed](https://api.msrc.microsoft.com/update-guide/rss) | `rss` |
| `innei` | Shiro (Innei) | [home](https://innei.in/posts) · [feed](https://innei.in/feed) | `rss` |
<!-- source-table:end -->

```bash
uv run python -m sentinel.sources list      # render the current table in the terminal
uv run python -m sentinel.sources validate  # schema check (CI runs this)
```

## Egress proxy

GitHub Actions runners are blocked by several sources (403 / TLS interference). All collection traffic therefore routes through a local [mihomo](https://github.com/MetaCubeX/mihomo) instance:

- `scripts/up_proxy.sh` (CI-only) downloads a pinned mihomo release, decodes the `MIHOMO_CONFIG_B64` secret into a config, starts the proxy on `127.0.0.1:7890`, and verifies the egress IP. A failed self-check fails the run fast.
- The collect step sets `HTTPS_PROXY`/`HTTP_PROXY` to the local proxy; `NO_PROXY` excludes the LLM API so classification traffic never enters the pool. Git push is outside this step and stays direct.
- Node selection is a `url-test` group (`AUTO`): all nodes are health-checked every 300s, fastest wins, dead nodes are bypassed automatically.
- Per-site exceptions are `DOMAIN-SUFFIX,…,DIRECT` rules inside the secret config (currently `redsiege.com`, `mist.com` — both misbehave behind datacenter egress IPs but work from runner IPs directly).

The node list is static by design and decays over time. Refresh it when blocked-access alerts reappear, or every 1–2 months:

```bash
base64 -i config.yaml | gh secret set MIHOMO_CONFIG_B64
gh workflow run daily-pulse.yml   # verify the "proxy up, egress: …" log line
```

The secret config never lives in the repository.

## Repository layout

```
.github/workflows/   daily-pulse (schedule + proxy + collect + commit), ci (tests)
scripts/up_proxy.sh  CI egress proxy bootstrap + self-check
config/sources.yaml  source inventory (single source of truth)
src/sentinel/
  run.py             orchestration: collect → bundle → health → issue sync → webhook
  sources.py         inventory loading/validation + CLI
  state.py           state file I/O
  normalize.py       URL canonicalization, tracking-param stripping
  http_client.py     httpx wrapper: UA, retries, per-host TLS exceptions
  llm.py             DeepSeek client (classification, content-block selection)
  collectors/        collection layer
    articles.py      per-source pipeline + incremental diff + streak counters
    rss.py           feed fetch/parse with conditional requests
    html_links.py    candidate link extraction
    llm_fallback.py  http/browser + LLM fallback orchestration
    browser.py       Playwright lifecycle, anti-automation flags, env proxy
    content.py       article body fetch/clean, challenge detection
    discover.py      feed autodiscovery
  analyzers/         output layer
    feed.py          data/feed/latest.json projection
    bundle.py        daily bundle with stats
bundles/             daily output, committed (downstream contract + ledger bootstrap)
data/                feed projection and article archive
state/               incremental state (sources.json, emitted ledger)
```

## Outputs

| Path | Purpose |
| --- | --- |
| `bundles/index.json` | Bundle index, latest date, checksums, available days |
| `bundles/YYYY-MM-DD.json` | Daily emitted articles for the Beijing collection date |
| `data/feed/latest.json` | Internal latest feed projection |
| `data/articles/` | Internal article archive |
| `state/sources.json` | Per-source URL/candidate state and failure streaks |
| `state/emitted.json` | Cross-run emitted-item ledger for deduplication |

Public bundle endpoint:

```text
https://raw.githubusercontent.com/ElectQ/Sentinel-Site/main/bundles/index.json
```

Each bundle item carries the article URL, title, source ID, publication and collection timestamps, cleaned content, content status, and a stable `external_id` (the downstream join key).

## Alerting

At the end of each run, failures are classified and synced to GitHub Issues — one stable issue per source (`sentinel-alert` label). Categories: `采集失败` (collection failure, opens after `ALERT_FAIL_STREAK` = 3 consecutive runs), `访问受限` (blocked), `路径退化` (degraded path), `反爬拦截` (anti-bot block on content) — the latter three open immediately. A recovered source closes its issue automatically; a recurrence reopens the same issue with a fresh comment instead of creating a duplicate. A health report is also written to `GITHUB_STEP_SUMMARY`.

## Invariants

- `config/sources.yaml` is the inventory truth; never duplicate it into docs.
- Never hand-edit or reset `state/sources.json` / `state/emitted.json`; incremental collection and dedup are built on them.
- Bundle schema is additive-stable; `external_id` must never change meaning.
- `ALLOW_HEURISTIC_FALLBACK` stays `0` in production: accuracy over availability, a broken classifier must not turn navigation pages into articles.
- Proxy env applies to the collect step only; LLM and git traffic never route through the pool.

## Agent operations

Routine maintenance (source fixes, new sources, small code changes) is
executed by an ops agent running [pi](https://github.com/badlogic/pi-mono)
on a dedicated host. Its constitution lives in [`AGENTS.md`](AGENTS.md); its
cumulative repair playbook in [`docs/recipes.md`](docs/recipes.md).

Division of labor:

| Layer | Runs | Role |
| --- | --- | --- |
| GitHub Actions | workflows ①②③ | pure-code pipeline: collect, verify, evidence — never an agent |
| Ops host (pi) | `AGENTS.md` + cron | the only agent: triages failures, fixes, opens evidence-backed PRs |
| Humans | chat only | approve PRs, approve sources/nodes, intervene when escalated |

Issue close authority belongs to the daily run (objective result), not the
agent or a human's judgment. The agent's freedom ends at opening PRs; CI is
the referee for everyone, humans included.

## Operations

The daily workflow runs at **21:00 UTC** (**05:00 Beijing time, next day**) and can be dispatched manually.

```bash
uv sync                                        # install dependencies
uv run python -m sentinel.sources validate     # schema check
uv run python -m sentinel.sources check <id>   # probe one source end to end
uv run python -m sentinel.run --check          # offline health inspection
LLM_API_KEY=... uv run python -m sentinel.run  # full local run
```

A failing source is recorded in bundle statistics and never discards successful results from other sources.
