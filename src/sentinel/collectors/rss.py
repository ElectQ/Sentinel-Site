"""RSS / Atom fetch and parse."""

from __future__ import annotations

import time
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from ..http_client import get
from ..normalize import is_http_url
from ..util import env_int


def _entry_link(entry: Any) -> str:
    # Atom may have list of links
    links = getattr(entry, "links", None) or []
    if links:
        alt = None
        plain = None
        for ln in links:
            rel = (ln.get("rel") or "").lower()
            typ = (ln.get("type") or "").lower()
            href = ln.get("href") or ""
            if not href:
                continue
            if rel == "self":
                continue
            if rel in ("alternate", "") and (
                not typ or "html" in typ or typ.startswith("text/")
            ):
                alt = href
                break
            if plain is None and rel != "enclosure":
                plain = href
        if alt:
            return alt
        if plain:
            return plain
    link = getattr(entry, "link", None) or ""
    if link:
        return link
    guid = getattr(entry, "id", None) or getattr(entry, "guid", None) or ""
    if isinstance(guid, str) and is_http_url(guid):
        return guid
    return ""


def _entry_published(entry: Any) -> str:
    for key in ("published", "updated", "created"):
        raw = getattr(entry, key, None)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                from datetime import timezone

                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            pass
        # feedparser parsed struct
        parsed = getattr(entry, f"{key}_parsed", None)
        if parsed:
            try:
                return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", parsed)
            except Exception:
                pass
    return ""


def _entry_content(entry: Any) -> str:
    values: list[str] = []
    for content in getattr(entry, "content", None) or []:
        value = content.get("value") if hasattr(content, "get") else ""
        if value:
            values.append(str(value))
    encoded = getattr(entry, "content_encoded", None)
    if encoded:
        values.append(str(encoded))
    return max(values, key=len) if values else ""


def fetch_and_parse(
    feed_url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return (items, error). items may be empty on success."""
    try:
        r = get(
            feed_url,
            etag=etag,
            last_modified=last_modified,
            accept="application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        )
    except Exception as e:
        return [], f"http_error:{e}"

    if r.status_code == 304:
        return [], None
    if r.status_code >= 400:
        return [], f"http_{r.status_code}"

    body = r.text
    # crude HTML rejection
    low = body.lstrip()[:200].lower()
    if low.startswith("<!doctype html") or low.startswith("<html"):
        return [], "not_a_feed_html"

    parsed = feedparser.parse(body)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        return [], f"parse_error:{getattr(parsed, 'bozo_exception', 'bozo')}"

    items: list[dict[str, Any]] = []
    # Some WordPress feeds expose hundreds of historical entries. Keeping only
    # the newest slice prevents them from overflowing the per-source seen cap
    # and being re-emitted as false positives on the next run.
    max_items = max(1, env_int("FEED_MAX_ITEMS", 100))
    for entry in parsed.entries[:max_items]:
        link = _entry_link(entry)
        if not link:
            continue
        title = (getattr(entry, "title", None) or "").strip()
        summary = (getattr(entry, "summary", None) or getattr(entry, "description", None) or "")
        if hasattr(summary, "strip"):
            summary = summary.strip()
        else:
            summary = str(summary)
        author = ""
        if getattr(entry, "author", None):
            author = str(entry.author)
        items.append(
            {
                "url": link,
                "title": title or link,
                "summary": summary[:500] if summary else "",
                "content_html": _entry_content(entry),
                "published_at": _entry_published(entry),
                "author": author,
            }
        )
    return items, None
