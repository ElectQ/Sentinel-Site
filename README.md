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

## How it works

Each daily run:

1. Reads enabled sources from `config/sources.yaml`.
2. Collects entries through RSS/Atom, ordinary HTTP, or Playwright.
3. Normalizes URLs and removes tracking/session parameters, navigation links, and obvious promotions.
4. Compares URLs with `state/sources.json` and the cross-run emitted ledger.
5. Uses DeepSeek to classify new HTML candidates when deterministic rules are not sufficient.
6. Fetches and cleans the content of newly emitted articles.
7. Writes the daily feed, bundle, archive, and updated state.

Network timeouts and transient 429/5xx responses receive limited retries. Existing bundles are used to bootstrap the emitted ledger so previously published items are not re-emitted after a state reset.

The collection date is the Beijing date of the run. It is not a strict publication-date filter: a feed-delayed article may be published earlier but discovered today. The output records both publication and collection timestamps where available.

## Collection modes

| Mode | Description |
| --- | --- |
| `rss` | Read the configured RSS/Atom feed. If the feed fails, the collector may try a remembered or discovered feed and then fall back to the source page. |
| `html_llm` | Fetch the page over HTTP, extract candidate links, and use the LLM to classify new candidates. |
| `browser_llm` | Render the page with Playwright, then classify candidate links with the LLM. |

## Monitored sources

The current inventory is maintained in [`config/sources.yaml`](config/sources.yaml). All configured sources are currently enabled.

| ID | Source | Home / feed endpoint | Mode |
| --- | --- | --- | --- |
| `zdi-advisories` | Zero Day Initiative Advisories | [home](https://www.zerodayinitiative.com/advisories/published/) | `html_llm` |
| `mixbytes-blog` | MixBytes Blog | [home](https://mixbytes.io/blog) | `html_llm` |
| `ibm-xforce` | IBM Security Intelligence X-Force | [home](https://www.ibm.com/think/x-force) | `browser_llm` |
| `unknowncheats-ac` | UnknownCheats Anti-Cheat | [home](https://www.unknowncheats.me/forum/general-programming-and-reversing/) | `browser_llm` |
| `idov31-posts` | Ido Veltzman Posts | [home](https://idov31.github.io/posts) | `html_llm` |
| `redheadsec` | RedHeadSec | [home](https://redheadsec.tech/) · [RSS](https://redheadsec.tech/rss/) | `rss` |
| `cocomelonc` | cocomelonc | [home](https://cocomelonc.github.io/) · [feed](https://cocomelonc.github.io/feed.xml) | `rss` |
| `yage-ai` | yage.ai | [home](https://yage.ai/) · [Atom](https://yage.ai/feeds/atom.xml) | `rss` |
| `yage-share` | yage.ai Share | [home](https://yage.ai/share/) · [feed](https://yage.ai/share/feed.xml) | `rss` |
| `rastamouse` | Rasta Mouse | [home](https://rastamouse.me/) · [RSS](https://rastamouse.me/rss/) | `rss` |
| `naksyn-posts` | Naksyn Posts | [home](https://naksyn.com/posts/) · [Atom](https://naksyn.com/atom.xml) | `rss` |
| `lorenzomeacci` | Lorenzo Meacci | [home](https://lorenzomeacci.com/) | `html_llm` |
| `voltatech-blog` | VoltaTech Blog | [home](https://voltatech.in/blog/) · [RSS](https://voltatech.in/feed_rss_created.xml) | `rss` |
| `xreous` | Xreous | [home](https://xreous.io/posts/) | `browser_llm` |
| `aff-wg` | Adversary Fan Fiction Writers Guild | [home](https://aff-wg.org/) · [feed](https://aff-wg.org/feed/) | `rss` |
| `tradecraftgarden` | Tradecraft Garden | [home](https://tradecraftgarden.org/index.html) | `html_llm` |
| `deadeclipse-blog` | Nightmare Eclipse | [home](https://deadeclipse666.blogspot.com/) · [RSS](https://deadeclipse666.blogspot.com/feeds/posts/default?alt=rss) | `rss` |
| `zusda` | zusda | [home](https://zusda.github.io/) | `html_llm` |
| `sud0ru` | Sud0Ru | [home](https://sud0ru.ghost.io/) · [RSS](https://sud0ru.ghost.io/rss/) | `rss` |
| `fushuling` | fushuling | [home](https://fushuling.com/) | `html_llm` |
| `otterpwn` | OtterPwn Blog | [home](https://blog.otterpwn.com/) · [feed](https://blog.otterpwn.com/index.xml) | `rss` |
| `fluxsec` | FluxSec | [home](https://fluxsec.red/) · [RSS](https://fluxsec.red/rss.xml) | `rss` |
| `r136a1` | R136a1 | [home](https://r136a1.dev/) · [feed](https://r136a1.dev/feed.xml) | `rss` |
| `denizhalil-blogs` | DenizHalil Blogs | [home](https://denizhalil.com/blogs/) · [feed](https://denizhalil.com/feed/) | `rss` |
| `lolbas` | LOLBAS Project | [home](https://lolbas-project.github.io/) | `html_llm` |
| `cobaltstrike-blog` | Cobalt Strike Blog | [home](https://www.cobaltstrike.com/blog) | `browser_llm` |
| `bruteratel-blog` | Brute Ratel Blog | [home](https://bruteratel.com/blog/) · [feed](https://bruteratel.com/feed.xml) | `rss` |
| `safebreach-blog` | SafeBreach Blog | [home](https://www.safebreach.com/blog/) | `browser_llm` |
| `sandflysecurity-blog` | Sandfly Security Blog | [home](https://sandflysecurity.com/blog) · [RSS](https://sandflysecurity.com/blog/rss.xml) | `rss` |
| `hacktron-blog` | Hacktron AI Blog | [home](https://www.hacktron.ai/blog) · [RSS](https://www.hacktron.ai/rss.xml) | `rss` |
| `whiteknightlabs-blog` | White Knight Labs Blog | [home](https://whiteknightlabs.com/blog/) · [feed](https://whiteknightlabs.com/feed/) | `rss` |
| `systeminformer-blog` | System Informer Blog | [home](https://www.systeminformer.com/blog) | `html_llm` |
| `xlab-qianxin` | QiAnXin XLab Blog | [home](https://blog.xlab.qianxin.com/) · [RSS](https://blog.xlab.qianxin.com/rss/) | `rss` |
| `adsecurity` | ADSecurity.org | [home](https://adsecurity.org/) · [RSS](https://adsecurity.org/?feed=rss2) | `rss` |
| `outflank-blog` | Outflank Publications | [home](https://www.outflank.nl/bloG) | `browser_llm` |
| `g3tsyst3m` | G3tSyst3m Infosec Blog | [home](https://g3tsyst3m.com/) · [feed](https://g3tsyst3m.com/feed.xml) | `rss` |
| `z3bra` | Z3bra | [home](https://z3bra.cat/) · [feed](https://z3bra.cat/index.xml) | `rss` |
| `cymulate-blog` | Cymulate Blog | [home](https://cymulate.com/blog/) | `html_llm` |
| `xpnsec-blog` | XPN InfoSec Blog | [home](https://blog.xpnsec.com/) · [RSS](https://blog.xpnsec.com/rss.xml) | `rss` |
| `zgao` | Zgao Blog | [home](https://zgao.top/) · [RSS](https://zgao.top/feed/) | `rss` |
| `redsiege-blog` | Red Siege Blog | [home](https://redsiege.com/red-siege-blog/) | `html_llm` |
| `itm4n` | itm4n Blog | [home](https://itm4n.github.io/) · [feed](https://itm4n.github.io/feed.xml) | `rss` |
| `cognisys-labs` | Cognisys Group Labs | [home](https://labs.cognisys.group/) · [feed](https://labs.cognisys.group/feed.xml) | `rss` |
| `bhis-blog` | Black Hills Information Security | [home](https://www.blackhillsinfosec.com/blog/) · [feed](https://www.blackhillsinfosec.com/blog/feed/) | `rss` |
| `cisco-advisory` | Cisco Security Advisory | [home/feed](https://sec.cloudapps.cisco.com/security/center/psirtrss20/CiscoSecurityAdvisory.xml) | `rss` |
| `forti-ir` | FortiGuard IR Advisories | [home](https://fortiguard.fortinet.com/rss/ir.xml) · [RSS](https://filestore.fortinet.com/fortiguard/rss/ir.xml) | `rss` |
| `ivanti-advisory` | Ivanti Security Advisory | [home](https://www.ivanti.com/blog/topics/security-advisory) · [RSS](https://www.ivanti.com/blog/topics/security-advisory/rss) | `rss` |
| `paloalto-advisory` | Palo Alto Security Advisories | [home](https://security.paloaltonetworks.com/) · [RSS](https://security.paloaltonetworks.com/rss.xml) | `rss` |
| `mist-security` | Mist Security Alerts | [home](https://www.mist.com/documentation/category/security-alerts/) · [feed](https://www.mist.com/documentation/category/security-alerts/feed/) | `rss` |
| `sonicwall-advisory` | SonicWall Security Advisories | [home](https://psirt.global.sonicwall.com/) · [RSS](https://psirtapi.global.sonicwall.com/api/v1/feed/rss.xml) | `rss` |
| `watchtowr-labs` | watchTowr Labs | [home](https://labs.watchtowr.com/) · [RSS](https://labs.watchtowr.com/rss/) | `rss` |
| `openai-research` | OpenAI Research | [research index](https://openai.com/zh-Hans-CN/research/index/) | `browser_llm` |
| `anthropic-research` | Anthropic Research | [research index](https://www.anthropic.com/research) | `html_llm` |

## Outputs

| Path | Purpose |
| --- | --- |
| `bundles/index.json` | Bundle index, latest date, checksums, and available days |
| `bundles/YYYY-MM-DD.json` | Daily emitted articles for the Beijing collection date |
| `data/feed/` | Internal daily feed projection |
| `data/articles/` | Internal article archive |
| `state/sources.json` | Persistent per-source URL and candidate state |
| `state/emitted.json` | Cross-run emitted-item ledger used for deduplication |

Public bundle endpoint:

```text
https://raw.githubusercontent.com/ElectQ/Sentinel-Site/main/bundles/index.json
```

Each bundle item contains the article URL, title, source ID, publication time when available, collection time, cleaned content, content status, and stable `external_id`.

## Operations

The daily workflow runs at **21:00 UTC**, which is **05:00 Beijing time on the following day**. It can also be started manually with GitHub Actions.

```bash
# Install dependencies
uv sync

# Validate and inspect source configuration
uv run python -m sentinel.sources validate
uv run python -m sentinel.sources list
uv run python -m sentinel.sources check <source_id>

# Run the collector locally
export LLM_API_KEY=...
uv run python -m sentinel.run
```

CI validates the source configuration, runs the regression tests, and compiles the package. A source failure is recorded in bundle statistics and does not normally discard successful results from other sources.

## Adding a source

1. Add a stable ID and set `enabled: false` initially.
2. Prefer and verify an official RSS/Atom endpoint.
3. Select `rss`, `html_llm`, or `browser_llm` explicitly.
4. Run `validate` and `check <source_id>`.
5. Verify at least one real article page and its extracted content.
6. Enable the source and run one baseline collection before relying on incremental output.

Do not manually reset `state/sources.json`; it is the basis for incremental collection and deduplication.
