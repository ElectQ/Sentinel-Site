"""Extract same-host candidate article links from a list page."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from selectolax.parser import HTMLParser

from ..http_client import get
from ..normalize import canonicalize, looks_like_non_article


PROMOTIONAL_TITLE_RE = re.compile(
    r"^(?:advertisement|sponsored|promoted)(?:\s+content)?$|"
    r"\brent\s+(?:this|a)\s+thread\b|"
    r"\bunlock\s+the\s+power\s+of\s+advertising\b",
    re.I,
)


def looks_like_promotion(url: str, title: str) -> bool:
    """Reject unmistakable same-site ad inventory before spending LLM tokens."""
    if PROMOTIONAL_TITLE_RE.search((title or "").strip()):
        return True
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    # vBulletin's targeted-ad pseudo-thread used by UnknownCheats and clones.
    if parsed.path.lower().endswith("/misc.php") and any(
        value.lower() == "tad" for value in query.get("do", [])
    ):
        return True
    return False


def fetch_html(url: str, *, ssl_verify: bool | None = None) -> tuple[str, str]:
    """Return (final_url, html_text). Raises on hard failure."""
    r = get(url, accept="text/html,application/xhtml+xml", ssl_verify=ssl_verify)
    if r.status_code >= 400:
        raise RuntimeError(f"http_{r.status_code}")
    return str(r.url), r.text


def extract_candidates(
    html: str,
    *,
    page_url: str,
    home_url: str,
    allowed_hosts: list[str] | None = None,
    strip_query_keys: list[str] | None = None,
    limit: int = 80,
) -> list[dict[str, str]]:
    tree = HTMLParser(html)
    for sel in ("script", "style", "noscript", "svg"):
        for n in tree.css(sel):
            n.decompose()

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        title = (a.text(strip=True) or "").strip()
        url = canonicalize(
            href,
            base=page_url,
            home_url=home_url,
            allowed_hosts=allowed_hosts,
            strip_query_keys=strip_query_keys,
        )
        if not url or url in seen:
            continue
        if looks_like_non_article(url):
            continue
        if looks_like_promotion(url, title):
            continue
        path = urlparse(url).path or ""
        if path.endswith(
            (".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".zip", ".pdf")
        ):
            continue
        context = ""
        parent = a.parent
        if parent is not None:
            nearby = " ".join(parent.text(separator=" ", strip=True).split())
            if nearby and nearby != title:
                context = nearby[:320]
        seen.add(url)
        out.append({"url": url, "title": title[:200], "context": context})
        if len(out) >= limit:
            break
    return out


def html_excerpt(html: str, max_chars: int = 12000) -> str:
    tree = HTMLParser(html)
    for sel in ("script", "style", "noscript", "svg", "nav", "footer", "header"):
        for n in tree.css(sel):
            n.decompose()
    text = tree.body.text(separator="\n", strip=True) if tree.body else tree.text()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)[:max_chars]
