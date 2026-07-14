"""Auto-discover RSS/Atom feed URLs from a home page."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from ..http_client import get
from . import rss

COMMON_PATHS = (
    "/feed",
    "/feed/",
    "/rss",
    "/rss/",
    "/rss.xml",
    "/atom.xml",
    "/feed.xml",
    "/index.xml",
    "/feeds/posts/default",
    "/feeds/posts/default?alt=rss",
)


def _same_host(a: str, b: str) -> bool:
    ha = (urlparse(a).hostname or "").lower()
    hb = (urlparse(b).hostname or "").lower()
    if not ha or not hb:
        return False
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def discover_feed(home_url: str) -> str | None:
    """Return a working feed URL or None."""
    try:
        r = get(home_url, accept="text/html,application/xhtml+xml")
    except Exception:
        return None
    if r.status_code >= 400:
        return None

    base = str(r.url)
    html = r.text
    candidates: list[str] = []

    try:
        tree = HTMLParser(html)
        for node in tree.css('link[rel="alternate"]'):
            typ = (node.attributes.get("type") or "").lower()
            href = node.attributes.get("href") or ""
            if not href:
                continue
            if "rss" in typ or "atom" in typ or "xml" in typ:
                candidates.append(urljoin(base, href))
    except Exception:
        pass

    origin = f"{urlparse(base).scheme}://{urlparse(base).netloc}"
    for path in COMMON_PATHS:
        candidates.append(origin + path)
        home_path = urlparse(home_url).path.rstrip("/")
        if home_path and home_path != "/":
            candidates.append(urljoin(base.rstrip("/") + "/", path.lstrip("/")))

    seen: set[str] = set()
    empty_valid: str | None = None
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        items, err = rss.fetch_and_parse(cand)
        if err is not None:
            continue
        if items:
            return cand
        if empty_valid is None:
            empty_valid = cand
    return empty_valid
