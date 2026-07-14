"""URL canonicalization, RSS-oriented fixes, and optional new-URL probing."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from .http_client import probe
from .util import env_bool

TRACKING_QUERY_PREFIXES = ("utm_", "mc_")
TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "ref",
        "spo",
        "spm",
        "pk_campaign",
        "pk_kwd",
    }
)

NON_ARTICLE_PATH_RE = re.compile(
    r"(?:^|/)(?:tag|tags|category|categories|author|authors|page|login|search|wp-admin|"
    r"cart|checkout|account|privacy|terms|cookie)(?:/|$)",
    re.I,
)


def external_id_for(url: str) -> str:
    """Stable id ≤64 chars for Megatron IngestItem."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"a:{digest}"


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def resolve_url(base: str, href: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith(("javascript:", "mailto:", "tel:", "data:")):
        return ""
    return urljoin(base, href)


def strip_tracking(
    url: str,
    *,
    extra_query_keys: list[str] | None = None,
) -> str:
    p = urlparse(url)
    if not p.query:
        return urlunparse(p._replace(fragment=""))
    dropped = {k.lower() for k in (extra_query_keys or [])}
    kept: list[tuple[str, str]] = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        lk = k.lower()
        if lk in TRACKING_QUERY_KEYS or lk in dropped:
            continue
        if any(lk.startswith(pref) for pref in TRACKING_QUERY_PREFIXES):
            continue
        kept.append((k, v))
    query = urlencode(kept, doseq=True)
    return urlunparse(p._replace(query=query, fragment=""))


def strip_amp(url: str) -> str:
    p = urlparse(url)
    path = p.path or ""
    if path.endswith("/amp"):
        path = path[: -len("/amp")] or "/"
    elif path.endswith("/amp/"):
        path = path[: -len("/amp/")] + "/"
    q = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in ("outputtype", "amp")
    ]
    return urlunparse(p._replace(path=path, query=urlencode(q, doseq=True)))


def allowed_host_set(home_url: str, allowed_hosts: list[str] | None) -> set[str]:
    hosts = {h.lower() for h in (allowed_hosts or []) if h}
    if not hosts and home_url:
        hh = host_of(home_url)
        if hh:
            hosts.add(hh)
            if hh.startswith("www."):
                hosts.add(hh[4:])
            else:
                hosts.add(f"www.{hh}")
    return hosts


def canonicalize(
    url: str,
    *,
    base: str = "",
    home_url: str = "",
    allowed_hosts: list[str] | None = None,
    strip_query_keys: list[str] | None = None,
) -> str:
    """Return cleaned absolute URL, or empty string if invalid / disallowed."""
    raw = resolve_url(base or home_url, url) if (base or home_url) else url
    if not raw:
        return ""
    raw = strip_tracking(
        strip_amp(raw.strip()), extra_query_keys=strip_query_keys
    )
    if not is_http_url(raw):
        return ""

    p = urlparse(raw)
    host = (p.hostname or "").lower()
    netloc = host
    if p.port and not (
        (p.scheme == "http" and p.port == 80)
        or (p.scheme == "https" and p.port == 443)
    ):
        netloc = f"{host}:{p.port}"
    path = p.path or "/"
    if not path:
        path = "/"

    clean = urlunparse((p.scheme.lower(), netloc, path, "", p.query, ""))

    hosts = allowed_host_set(home_url, allowed_hosts)
    if hosts and host not in hosts:
        return ""
    return clean


def looks_like_non_article(url: str) -> bool:
    if not url:
        return True
    path = urlparse(url).path or "/"
    if path in ("", "/"):
        return True
    return bool(NON_ARTICLE_PATH_RE.search(path))


def normalize_article(
    item: dict[str, Any],
    *,
    base: str,
    home_url: str,
    allowed_hosts: list[str] | None = None,
    strip_query_keys: list[str] | None = None,
    source_id: str,
    via: str,
) -> dict[str, Any] | None:
    raw_url = item.get("url") or item.get("link") or ""
    raw_saved = raw_url
    url = canonicalize(
        raw_url,
        base=base,
        home_url=home_url,
        allowed_hosts=allowed_hosts,
        strip_query_keys=strip_query_keys,
    )
    if not url:
        return None
    home_can = canonicalize(
        home_url,
        home_url=home_url,
        allowed_hosts=allowed_hosts,
        strip_query_keys=strip_query_keys,
    )
    if home_can and home_can == url:
        return None

    title = (item.get("title") or "").strip() or url
    published_at = item.get("published_at") or item.get("published") or ""
    author = item.get("author") or source_id

    eid = external_id_for(url)
    out: dict[str, Any] = {
        "id": eid,
        "external_id": eid,
        "url": url,
        "title": title,
        "author": author,
        "published_at": published_at,
        "source_id": source_id,
        "via": via,
        "raw_url": raw_saved,
        "url_corrected": bool(raw_saved and strip_tracking(raw_saved) != url),
    }
    if item.get("summary"):
        out["summary"] = str(item["summary"])[:500]
    if item.get("content_html"):
        # Kept only in-memory until a newly emitted article is enriched; raw
        # feed HTML is removed before archive/bundle persistence.
        out["content_html"] = str(item["content_html"])[:2_000_000]
    return out


def maybe_probe_new(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Optionally probe only new URLs; drop hard 404/410."""
    if not env_bool("PROBE_NEW_URLS", True):
        for a in articles:
            a.setdefault("fetch_status", "skipped")
        return articles

    kept: list[dict[str, Any]] = []
    for a in articles:
        final, _code, status = probe(a["url"])
        a["fetch_status"] = status
        if status == "not_found":
            continue
        if status == "ok" and final and final != a["url"]:
            new_url = canonicalize(final, home_url=a["url"])
            if new_url:
                a["url"] = new_url
                a["id"] = external_id_for(new_url)
                a["external_id"] = a["id"]
                a["url_corrected"] = True
        kept.append(a)
    return kept
