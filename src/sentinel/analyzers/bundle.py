"""Soundwave-style day bundles — Megatron-facing contract surface."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

from ..state import ROOT

SCHEMA_VERSION = 1
SOURCE_ID = "blog_watch"
CST = timezone(timedelta(hours=8))
BUNDLES_DIR = ROOT / "bundles"


def beijing_date(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CST).strftime("%Y-%m-%d")


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str) and value:
        try:
            s = value.replace("Z", "+00:00")
            return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()
        except ValueError:
            return value
    return ""


def _producer() -> dict[str, Any]:
    try:
        ver = pkg_version("sentinel")
    except Exception:
        ver = "0.1.0"
    return {
        "name": "sentinel-site",
        "version": ver,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "commit": (os.environ.get("GITHUB_SHA") or "")[:7],
    }


def feed_item_to_contract(
    item: dict[str, Any], *, collected_at: str | None = None
) -> dict[str, Any]:
    who = item.get("actor") or ""
    who_url = item.get("actor_url") or ""
    title = item.get("title") or ""
    url = item.get("html_url") or ""
    text = item.get("text") or f"{who} published: {title}"
    at = _iso(item.get("created_at"))
    collected = _iso(collected_at or item.get("created_at"))
    via = item.get("via") or ""
    collect_mode = item.get("collect_mode") or "auto"
    article_content = item.get("content") or ""
    eid = str(item.get("id") or "")
    tags = ["kind:publish"]
    if who:
        tags.append(f"src:{who}")
    if via:
        tags.append(f"via:{via}")
    if collect_mode:
        tags.append(f"channel:{collect_mode}")

    return {
        "id": eid,
        "who": who,
        "who_url": who_url,
        "action": "publish",
        "target": title,
        "target_url": url,
        "text": text,
        "at": at,
        "external_id": eid,
        "url": url,
        "title": title,
        "content": article_content or text,
        "content_format": item.get("content_format") or "text/plain",
        "content_status": item.get("content_status") or "",
        "content_via": item.get("content_via") or "",
        "content_source_url": item.get("content_source_url") or url,
        "content_chars": int(item.get("content_chars") or len(article_content)),
        "content_sha256": item.get("content_sha256") or "",
        "content_fetched_at": _iso(item.get("content_fetched_at")),
        "author": who,
        "author_name": item.get("source_name") or who,
        "author_url": who_url,
        "published_at": at,
        "collected_at": collected,
        "tags": tags,
        "hashtags": [],
        "links": [u for u in (who_url, url) if u],
        "refs": {
            "actor": {"login": who, "url": who_url},
            "repo": None,
            "target_user": None,
            "forkee": None,
            "source": {
                "id": who,
                "name": item.get("source_name") or who,
                "home_url": who_url,
            },
            "article": {
                "title": title,
                "url": url,
                "content_sha256": item.get("content_sha256") or "",
            },
        },
        "media": {"photos": [], "videos": []},
        "metrics": {
            "circle_count": None,
            "trending": False,
            "trending_front_page": False,
        },
        "flags": {
            "kind": "publish",
            "via": via,
            "collect_mode": collect_mode,
            "time_precision": item.get("time_precision") or "daily_window",
            "is_follow": False,
            "is_repo_event": False,
            "url_corrected": bool(item.get("url_corrected")),
            "fetch_status": item.get("fetch_status") or "",
            "content_status": item.get("content_status") or "",
            "content_via": item.get("content_via") or "",
        },
    }


class BundleStore:
    def __init__(self, bundle_dir: Path | str | None = None, source_id: str = SOURCE_ID):
        self.dir = Path(bundle_dir) if bundle_dir else BUNDLES_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.source_id = source_id

    def path_for(self, date: str) -> Path:
        return self.dir / f"{date}.json"

    def write(
        self,
        date: str,
        items: list[dict[str, Any]],
        *,
        window_start: str | datetime,
        window_end: str | datetime,
        window_hours: int | None = None,
        stats_extra: dict[str, Any] | None = None,
        merge: bool = True,
    ) -> Path:
        path = self.path_for(date)
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() and merge else {}

        merged: dict[str, dict[str, Any]] = {
            it["external_id"]: it
            for it in existing.get("items", [])
            if it.get("external_id")
        }
        merged.update({it["external_id"]: it for it in items if it.get("external_id")})

        start, end = _iso(window_start), _iso(window_end)
        old_window = existing.get("collect_window") or {}
        if old_window.get("start") and start:
            start = min(start, old_window["start"])
        if old_window.get("end") and end:
            end = max(end, old_window["end"])

        ordered = sorted(
            merged.values(),
            key=lambda it: it.get("at") or it.get("published_at") or "",
            reverse=True,
        )

        by_kind: dict[str, int] = {}
        by_via: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for it in ordered:
            for tag in it.get("tags") or []:
                if tag.startswith("kind:"):
                    k = tag[5:]
                    by_kind[k] = by_kind.get(k, 0) + 1
                if tag.startswith("via:"):
                    v = tag[4:]
                    by_via[v] = by_via.get(v, 0) + 1
                if tag.startswith("src:"):
                    s = tag[4:]
                    by_source[s] = by_source.get(s, 0) + 1

        hours = window_hours
        if hours is None and start and end:
            try:
                hours = int(
                    (
                        datetime.fromisoformat(end) - datetime.fromisoformat(start)
                    ).total_seconds()
                    // 3600
                )
            except ValueError:
                hours = 24

        stats: dict[str, Any] = {
            "total": len(ordered),
            "by_kind": by_kind,
            "by_via": by_via,
            "by_source": by_source,
            "failed_lists": [],
        }
        if stats_extra:
            stats.update(stats_extra)

        bundle = {
            "schema_version": SCHEMA_VERSION,
            "source_id": self.source_id,
            "collect_date": date,
            "collect_window": {"start": start, "end": end, "hours": hours or 24},
            "producer": _producer(),
            "stats": stats,
            "items": ordered,
        }
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def rebuild_index(self) -> Path:
        days = []
        watermark = ""
        for path in sorted(self.dir.glob("*.json"), reverse=True):
            if path.name == "index.json":
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            body = path.read_bytes()
            days.append(
                {
                    "date": data["collect_date"],
                    "count": data["stats"]["total"],
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "window_end": (data.get("collect_window") or {}).get("end") or "",
                }
            )
            we = (data.get("collect_window") or {}).get("end") or ""
            if we:
                watermark = max(watermark, we)

        days_sorted = sorted(days, key=lambda d: d["date"], reverse=True)
        index = {
            "source_id": self.source_id,
            "schema_version": SCHEMA_VERSION,
            "latest": days_sorted[0]["date"] if days_sorted else "",
            "watermark": watermark,
            "updated_at": _iso(datetime.now(timezone.utc)),
            "days": days_sorted,
        }
        path = self.dir / "index.json"
        path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def write_from_feed(
        self,
        feed: dict[str, Any],
        *,
        collect_date: str | None = None,
        collected_at: str | None = None,
        stats_extra: dict[str, Any] | None = None,
        merge: bool = True,
    ) -> Path:
        date = collect_date or feed.get("date") or beijing_date()
        now = collected_at or datetime.now(timezone.utc).isoformat()
        items = [
            feed_item_to_contract(it, collected_at=now) for it in feed.get("items") or []
        ]
        pubs = [it["published_at"] for it in items if it.get("published_at")]
        if pubs:
            window_start, window_end = min(pubs), max(pubs)
        else:
            window_start = f"{date}T00:00:00+00:00"
            window_end = now

        extra = dict(stats_extra or {})
        if feed.get("summary"):
            extra.setdefault("by_via", (feed["summary"] or {}).get("by_via"))
            extra.setdefault("by_source", (feed["summary"] or {}).get("by_source"))
            extra.setdefault(
                "by_content_status",
                (feed["summary"] or {}).get("by_content_status"),
            )

        path = self.write(
            date,
            items,
            window_start=window_start,
            window_end=window_end,
            stats_extra=extra,
            merge=merge,
        )
        self.rebuild_index()
        return path


def write_bundle_from_feed(feed: dict[str, Any], **kwargs: Any) -> Path:
    return BundleStore().write_from_feed(feed, **kwargs)
