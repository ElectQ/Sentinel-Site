# Recipes — operational memory

One entry per resolved case. Newest at the bottom. Format: **symptom →
diagnosis → fix → evidence**. Read before fixing; append after resolving.
Cases here are battle-tested; AGENTS.md holds the rules, this holds the
experience.

---

### rss feed 403 but site works
**Symptom**: `feed_fail_streak` climbing, `configured:http_403`, but L3
(html/LLM fallback) collects fine.
**Diagnosis**: feed endpoint is behind a different WAF rule than the site.
**Fix**: drop or replace `rss_url`; let the source ride on `html_llm`/
`browser_llm`, or find a working alternate feed.
**Cases**: `aff-wg`, `otterpwn`, `xpnsec-blog` (feed 403 long-term, L3 stable).

### site 403 for datacenter IPs (Cloudflare challenge)
**Symptom**: plain HTTP gets 403 with `server: cloudflare` + captcha page;
browser (Playwright) gets 200.
**Diagnosis**: client-fingerprint/JA3 filtering — IP change alone does not
help; egress proxy + real browser does.
**Fix**: `collect_mode: browser_llm` (or `browser_fallback: true`).
**Cases**: `unknowncheats-ac`, `xreous`, `cobaltstrike-blog`, `outflank-blog`
(all converted 2026-10, green since).

### proxy egress blocked by one small site
**Symptom**: source times out / handshake fails behind the egress proxy but
worked from runner IPs directly.
**Diagnosis**: small sites choke on datacenter egress ranges.
**Fix**: add `DOMAIN-SUFFIX,<domain>,DIRECT` to the mihomo rules inside the
`MIHOMO_CONFIG_B64` secret (human does the secret update), and note it here.
**Cases**: `redsiege.com` (fixed), `mist.com` (fixed; WAF is score-based —
also do NOT add extra probing for it).

### WAF with request scoring (mist.com pattern)
**Symptom**: 200 on first hit, 403 on rapid repeat.
**Diagnosis**: score-based WAF; any automated probing burns the score.
**Fix**: once a day via normal collection is fine. No health probes, no
retries beyond the standard policy, no diagnostics hitting the site more
than once per run.

### CI green locally red (or the reverse)
**Symptom**: behavior differs between local runs and GitHub Actions.
**Diagnosis**: different egress (Azure IP), different TLS stack, proxy path.
The GitHub environment is the product environment — its verdict wins.
**Fix**: always take evidence via `pulse-verify` (dispatch run), not local
runs. Do not "fix" a CI-only failure by changing code that only works
locally.

### workflow dispatch rejected: duplicate env key
**Symptom**: `HTTP 422: 'no_proxy' is already defined` on workflow dispatch.
**Diagnosis**: GitHub treats env keys case-insensitively; `NO_PROXY` +
`no_proxy` collide.
**Fix**: keep only the uppercase form.

### push rejected: remote moved (pulse bot commits daily)
**Symptom**: `! [rejected] main -> main (fetch first)`.
**Diagnosis**: the daily pulse bot commits bundles/state to `main`; your
local branch is behind.
**Fix**: `git pull --rebase --autostash` before every work session; rebase
agent branches onto `origin/main` before opening PRs.
