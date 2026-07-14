"""Daily pipeline: scan configured sources → denoise new article URLs → bundles."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from . import llm
from . import state as state_mod
from .analyzers import bundle as bundle_mod
from .analyzers import feed as feed_mod
from .collectors import articles as articles_mod
from .collectors.sources import load_enabled
from .util import env_bool


def main() -> int:
    llm.reset_usage()
    sources = load_enabled()
    st = state_mod.load_sources()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    bj = bundle_mod.beijing_date(now)

    print(f"sources_enabled={len(sources)} beijing_date={bj}")

    emitted: list[dict] = []
    failed: list[dict] = []
    via_counts: dict[str, int] = {}
    baselines = 0

    for src in sources:
        result = articles_mod.collect_one(src, st, collected_at=now_iso)
        if not result["ok"]:
            failed.append({"id": src.id, "error": result.get("error")})
            print(f"FAIL {src.id}: {result.get('error')}")
            continue
        via = result["via"] or "?"
        via_counts[via] = via_counts.get(via, 0) + 1
        if result["baseline"]:
            baselines += 1
            print(
                f"OK   {src.id}: via={via} baseline=1 seen={len(result['all_normalized'])} new=0"
            )
        else:
            new = result["new_articles"]
            candidate_text = ""
            if via != "rss":
                candidate_text = (
                    f" candidates={result.get('candidate_count', 0)}"
                    f" candidate_new={result.get('candidate_new_count', 0)}"
                )
            content_counts: dict[str, int] = {}
            for article in new:
                status = article.get("content_status") or "missing"
                content_counts[status] = content_counts.get(status, 0) + 1
            content_text = f" content={content_counts}" if content_counts else ""
            print(
                f"OK   {src.id}: via={via} new={len(new)}"
                f"{candidate_text}{content_text}"
            )
            for a in new:
                a["emitted"] = True
                emitted.append(a)

    # archive only emitted new articles (baseline updates state only)
    articles_mod.archive(emitted, when=now)
    state_mod.save_sources(st)

    # For feed/bundle: use this run's emitted items (also re-readable from archive)
    day_articles = list(emitted)
    # also merge any already archived today (same-day rerun)
    archived = articles_mod.collected_on(now.date().isoformat())
    # prefer archived that were emitted (have url)
    by_id = {a.get("external_id") or a.get("url"): a for a in archived}
    for a in emitted:
        by_id[a.get("external_id") or a.get("url")] = a
    day_articles = list(by_id.values())

    feed = feed_mod.build(day_articles, date=bj)
    feed_mod.write(feed)
    print(f"feed {feed['date']}: items={feed['item_count']}")

    bpath = bundle_mod.write_bundle_from_feed(
        feed,
        collect_date=bj,
        collected_at=now_iso,
        stats_extra={
            "sources_ok": len(sources) - len(failed),
            "sources_failed": failed,
            "baselines": baselines,
            "via_sources": via_counts,
            "failed_lists": [f["id"] for f in failed],
            "llm_usage": llm.usage_snapshot(),
        },
    )
    print(f"bundle: {bpath} items={feed['item_count']} failed={len(failed)}")
    print(f"llm_usage: {llm.usage_snapshot()}")

    articles_mod.shutdown()

    if env_bool("STRICT", False) and failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
