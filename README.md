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

[`config/sources.yaml`](config/sources.yaml) is the single source of truth for the inventory. This README intentionally does not duplicate the table. Each entry defines `id` (stable, used in bundles and alert issues), `home_url`, optional `rss_url`, `collect_mode`, and `tags`.

```bash
uv run python -m sentinel.sources list      # render the current table
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
