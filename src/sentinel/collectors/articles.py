"""Orchestrate per-source collect: RSS → discover → HTML/LLM → browser+LLM."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..normalize import maybe_probe_new, normalize_article
from ..state import ROOT
from ..util import env_bool, env_int
from . import browser, content, discover, llm_fallback, rss
from .sources import Source

ARTICLES_DIR = ROOT / "data" / "articles"
SEEN_CAP = env_int("SEEN_CAP_PER_SOURCE", 500)
CANDIDATE_CAP = env_int("CANDIDATE_CAP_PER_SOURCE", 1000)


def _source_state(st: dict[str, Any], source_id: str) -> dict[str, Any]:
    sources = st.setdefault("sources", {})
    if source_id not in sources:
        sources[source_id] = {
            "seen": {},
            "baseline_initialized": False,
            "candidates": {},
            "candidates_initialized": False,
            "resolved_feed_url": "",
            "feed_fail_streak": 0,
            "method": "",
            "last_ok_at": "",
        }
    return sources[source_id]


def collect_one(
    source: Source,
    st: dict[str, Any],
    *,
    collected_at: str | None = None,
) -> dict[str, Any]:
    """Collect + normalize + diff for one source."""
    now = collected_at or datetime.now(timezone.utc).isoformat()
    sst = _source_state(st, source.id)
    seen: dict[str, Any] = sst.setdefault("seen", {})
    candidate_state: dict[str, Any] = sst.setdefault("candidates", {})
    candidates_were_initialized = bool(sst.get("candidates_initialized"))
    is_baseline = not bool(
        sst.get("baseline_initialized") or sst.get("last_ok_at") or seen
    )

    raw_items: list[dict[str, Any]] = []
    raw_candidates: list[dict[str, Any]] = []
    via = ""
    err: str | None = None
    feed_url = ""

    # L1: configured rss
    use_feed = source.collect_mode in {"auto", "rss"}

    if use_feed and source.rss_url:
        feed_url = source.rss_url
        raw_items, err = rss.fetch_and_parse(feed_url)
        if err is None:
            via = "rss"
        else:
            feed_url = ""

    # remembered resolved feed
    if use_feed and not via and sst.get("resolved_feed_url"):
        feed_url = sst["resolved_feed_url"]
        raw_items, err = rss.fetch_and_parse(feed_url)
        if err is None:
            via = "rss"
            sst["feed_fail_streak"] = 0
        else:
            sst["feed_fail_streak"] = int(sst.get("feed_fail_streak") or 0) + 1
            if sst["feed_fail_streak"] >= env_int("FEED_FAIL_STREAK", 3):
                sst["resolved_feed_url"] = ""
            feed_url = ""
            err = None

    # L2: discover
    if use_feed and not via:
        found = discover.discover_feed(source.home_url)
        if found:
            raw_items, err = rss.fetch_and_parse(found)
            if err is None:
                via = "rss"
                feed_url = found
                sst["resolved_feed_url"] = found
                sst["feed_fail_streak"] = 0
            else:
                err = None

    # L3: plain HTTP HTML + LLM (or heuristic)
    if not via:
        force_browser = source.collect_mode == "browser_llm"
        known_urls = set(seen) | set(candidate_state)
        # Existing state created before candidate tracking must first snapshot
        # the whole current DOM. Otherwise old technical articles that were not
        # in `seen` look new when the LLM is introduced or its prompt changes.
        candidate_baseline = not candidates_were_initialized
        raw_items, err, transport, raw_candidates = llm_fallback.collect(
            source,
            force_browser=force_browser,
            known_urls=known_urls,
            baseline_only=candidate_baseline,
        )
        if err is None:
            if transport == "browser_heuristic":
                via = "browser_heuristic"
            elif transport == "http_heuristic":
                via = "heuristic"
            else:
                via = "browser_llm" if transport == "browser" else "llm"
        else:
            # Accuracy is more important than availability. A missing/broken
            # classifier must not silently turn navigation, ads, or product
            # landing pages into articles. Heuristic fallback is opt-in for
            # diagnostics only.
            if not env_bool("ALLOW_HEURISTIC_FALLBACK", False):
                return {
                    "ok": False,
                    "via": "",
                    "new_articles": [],
                    "all_normalized": [],
                    "error": err,
                    "baseline": is_baseline,
                    "source_id": source.id,
                }

            # Optional diagnostic fallback on the same path.
            raw_items, herr, transport, raw_candidates = (
                llm_fallback.collect_heuristic(
                    source,
                    force_browser=force_browser,
                    known_urls=known_urls,
                    baseline_only=candidate_baseline,
                )
            )
            if herr is None and raw_items:
                via = "browser_heuristic" if transport == "browser" else "heuristic"
                err = None
            else:
                # L4: force headless browser + LLM
                if source.browser_fallback and not force_browser:
                    # Explicit hard-site fallback after the normal path failed.
                    raw_items, berr, transport, raw_candidates = llm_fallback.collect(
                        source,
                        force_browser=True,
                        known_urls=known_urls,
                        baseline_only=candidate_baseline,
                    )
                    if berr is None:
                        if transport == "browser_heuristic":
                            via = "browser_heuristic"
                        elif transport == "http_heuristic":
                            via = "heuristic"
                        else:
                            via = "browser_llm" if transport == "browser" else "llm"
                        err = None
                    else:
                        raw_items, bherr, transport, raw_candidates = (
                            llm_fallback.collect_heuristic(
                                source,
                                force_browser=True,
                                known_urls=known_urls,
                                baseline_only=candidate_baseline,
                            )
                        )
                        if bherr is None and raw_items:
                            via = (
                                "browser_heuristic"
                                if transport == "browser"
                                else "heuristic"
                            )
                            err = None
                        else:
                            return {
                                "ok": False,
                                "via": "",
                                "new_articles": [],
                                "all_normalized": [],
                                "error": f"{err}; heuristic:{herr}; browser:{berr}; browser_h:{bherr}",
                                "baseline": is_baseline,
                                "source_id": source.id,
                            }
                else:
                    return {
                        "ok": False,
                        "via": "",
                        "new_articles": [],
                        "all_normalized": [],
                        "error": f"{err}; heuristic:{herr}; browser_fallback_disabled",
                        "baseline": is_baseline,
                        "source_id": source.id,
                    }

    base = feed_url or source.home_url
    normalized: list[dict[str, Any]] = []
    for it in raw_items:
        n = normalize_article(
            it,
            base=base,
            home_url=source.home_url,
            allowed_hosts=source.allowed_hosts or None,
            strip_query_keys=source.strip_query_keys or None,
            source_id=source.id,
            via=via,
        )
        if n:
            n["source_name"] = source.name
            n["home_url"] = source.home_url
            n["collected_at"] = now
            n["collect_mode"] = source.collect_mode
            normalized.append(n)

    by_id: dict[str, dict[str, Any]] = {}
    for n in normalized:
        by_id[n["external_id"]] = n
    normalized = list(by_id.values())

    # For HTML/LLM sources, diff deterministic DOM candidates separately from
    # the LLM selection. Baseline links cannot be emitted later just because
    # the LLM omitted them once and selected them on a later run.
    candidate_new_count = 0
    if via != "rss":
        normalized_candidates: dict[str, dict[str, Any]] = {}
        for candidate in raw_candidates:
            n = normalize_article(
                candidate,
                base=source.home_url,
                home_url=source.home_url,
                allowed_hosts=source.allowed_hosts or None,
                strip_query_keys=source.strip_query_keys or None,
                source_id=source.id,
                via=via,
            )
            if n:
                normalized_candidates[n["url"]] = n

        for url, candidate in normalized_candidates.items():
            record = candidate_state.get(url)
            if record is None:
                candidate_new_count += 1
                record = {
                    "title": candidate.get("title") or url,
                    "first_seen": now,
                    "baseline": bool(
                        is_baseline or not candidates_were_initialized or url in seen
                    ),
                    "selected": False,
                }
                candidate_state[url] = record
            record["last_seen"] = now
            if candidate.get("title"):
                record["title"] = candidate["title"]

        selected_urls = {n["url"] for n in normalized}
        for url in selected_urls:
            record = candidate_state.setdefault(
                url,
                {
                    "title": url,
                    "first_seen": now,
                    "baseline": bool(
                        is_baseline or not candidates_were_initialized or url in seen
                    ),
                },
            )
            record["selected"] = True
            record["last_selected"] = now
            record["selector"] = via

        sst["candidates_initialized"] = True
        if len(candidate_state) > CANDIDATE_CAP:
            candidate_items = sorted(
                candidate_state.items(),
                key=lambda kv: kv[1].get("last_seen")
                or kv[1].get("first_seen")
                or "",
                reverse=True,
            )
            candidate_state = dict(candidate_items[:CANDIDATE_CAP])
        sst["candidates"] = candidate_state

    if via == "rss":
        new_articles = [n for n in normalized if n["url"] not in seen]
    else:
        new_articles = [
            n
            for n in normalized
            if n["url"] not in seen
            and not bool((candidate_state.get(n["url"]) or {}).get("baseline"))
        ]
    emit = [] if is_baseline else list(new_articles)
    if not is_baseline and emit:
        emit = maybe_probe_new(emit)
        emit = [content.enrich(article, source) for article in emit]

    for n in normalized:
        url = n["url"]
        if url not in seen:
            seen[url] = {
                "title": n.get("title"),
                "first_seen": now,
                "published_at": n.get("published_at") or "",
            }
    for enriched in emit:
        record = seen.setdefault(
            enriched["url"],
            {
                "title": enriched.get("title"),
                "first_seen": now,
                "published_at": enriched.get("published_at") or "",
            },
        )
        record["content_status"] = enriched.get("content_status") or ""
        record["content_sha256"] = enriched.get("content_sha256") or ""
        record["content_fetched_at"] = enriched.get("content_fetched_at") or ""
    if len(seen) > SEEN_CAP:
        items = sorted(
            seen.items(),
            key=lambda kv: kv[1].get("first_seen") or "",
            reverse=True,
        )
        sst["seen"] = dict(items[:SEEN_CAP])
    else:
        sst["seen"] = seen

    sst["method"] = via
    sst["last_ok_at"] = now
    sst["baseline_initialized"] = True
    if feed_url and via == "rss":
        sst["resolved_feed_url"] = feed_url

    return {
        "ok": True,
        "via": via,
        "new_articles": emit,
        "all_normalized": normalized,
        "error": None,
        "baseline": is_baseline,
        "source_id": source.id,
        "candidate_count": len(raw_candidates),
        "candidate_new_count": candidate_new_count,
    }


def archive(records: list[dict[str, Any]], *, when: datetime | None = None) -> None:
    if not records:
        return
    when = when or datetime.now(timezone.utc)
    month = when.strftime("%Y-%m")
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTICLES_DIR / f"{month}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def collected_on(date: str) -> list[dict[str, Any]]:
    month = date[:7]
    path = ARTICLES_DIR / f"{month}.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ca = (rec.get("collected_at") or "")[:10]
        if ca != date:
            continue
        eid = rec.get("external_id") or rec.get("id") or rec.get("url")
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        out.append(rec)
    return out


def shutdown() -> None:
    """Release browser process if any."""
    browser.close()
