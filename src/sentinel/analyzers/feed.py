"""Internal daily feed projection."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from ..state import ROOT

FEED_DIR = ROOT / "data" / "feed"
SCHEMA_VERSION = 1


def build(day_articles: list[dict[str, Any]], *, date: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    items: list[dict[str, Any]] = []
    for a in day_articles:
        # only "new" emissions should be archived with emit flag; feed uses archived new ones
        items.append(
            {
                "id": a.get("external_id") or a.get("id"),
                "kind": "publish",
                "text": f"{a.get('source_id') or a.get('author')} published: {a.get('title')}",
                "actor": a.get("source_id") or a.get("author") or "",
                "actor_url": a.get("home_url") or "",
                "created_at": a.get("published_at") or a.get("collected_at") or now,
                "html_url": a.get("url"),
                "title": a.get("title") or "",
                "via": a.get("via") or "",
                "collect_mode": a.get("collect_mode") or "auto",
                "content": a.get("content") or "",
                "content_format": a.get("content_format") or "text/plain",
                "content_status": a.get("content_status") or "",
                "content_via": a.get("content_via") or "",
                "content_source_url": a.get("content_source_url") or "",
                "content_chars": int(a.get("content_chars") or 0),
                "content_sha256": a.get("content_sha256") or "",
                "content_fetched_at": a.get("content_fetched_at") or "",
                "content_error": a.get("content_error") or "",
                "time_precision": (
                    "exact" if a.get("published_at") else "daily_window"
                ),
                "source_name": a.get("source_name") or "",
                "fetch_status": a.get("fetch_status") or "",
                "url_corrected": bool(a.get("url_corrected")),
            }
        )

    items.sort(key=lambda it: it.get("created_at") or "", reverse=True)
    by_via = Counter(it.get("via") or "unknown" for it in items)
    by_src = Counter(it.get("actor") or "?" for it in items)
    by_content_status = Counter(
        it.get("content_status") or "missing" for it in items
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "date": date,
        "generated_at": now,
        "item_count": len(items),
        "kinds_included": ["publish"],
        "items": items,
        "summary": {
            "by_kind": {"publish": len(items)},
            "by_via": dict(by_via),
            "by_source": dict(by_src),
            "by_content_status": dict(by_content_status),
        },
    }


def write(feed: dict[str, Any]) -> None:
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    day = feed["date"]
    body = json.dumps(feed, ensure_ascii=False, indent=2) + "\n"
    (FEED_DIR / f"{day}.json").write_text(body, encoding="utf-8")
    (FEED_DIR / "latest.json").write_text(body, encoding="utf-8")
