"""L3: LLM denoise from HTML + candidate links (default DeepSeek text).

HTML may come from plain httpx or (last resort) headless browser.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .. import llm
from . import browser, html_links
from .sources import Source


def _load_page(
    source: Source,
    *,
    force_browser: bool = False,
) -> tuple[str, str, str | None]:
    """Return (page_url, html, transport) or ("", "", error).

    transport: http | browser
    """
    if not force_browser:
        try:
            page_url, html = html_links.fetch_html(
                source.home_url, ssl_verify=source.ssl_verify
            )
            return page_url, html, "http"
        except Exception as e:
            http_err = f"html_fetch:{e}"
    else:
        http_err = "forced_browser"

    # browser last resort
    if not source.browser_fallback and not force_browser:
        # still allow auto-browser when env BROWSER_AUTO=1 and http failed with 403/ssl
        from ..util import env_bool

        if not env_bool("BROWSER_AUTO", True):
            return "", "", http_err
        # auto only on clear bot-wall signals
        if "http_403" not in http_err and "http_401" not in http_err and "SSL" not in http_err and "certificate" not in http_err:
            # timeout etc. may also benefit from browser
            if "timed out" not in http_err and "timeout" not in http_err.lower():
                return "", "", http_err

    if not browser.available():
        return "", "", f"{http_err}; browser_unavailable"

    try:
        page_url, html = browser.fetch_html(source.home_url)
        return page_url, html, "browser"
    except Exception as e:
        return "", "", f"{http_err}; browser:{e}"


def _denoise_with_html(
    source: Source,
    page_url: str,
    html: str,
    *,
    use_llm: bool,
    known_urls: set[str] | None = None,
    baseline_only: bool = False,
) -> tuple[list[dict[str, Any]], str | None, list[dict[str, str]]]:
    candidates = html_links.extract_candidates(
        html,
        page_url=page_url,
        home_url=source.home_url,
        allowed_hosts=source.allowed_hosts or None,
        strip_query_keys=source.strip_query_keys or None,
    )
    if not candidates:
        return [], "no_candidates", []

    # The state diff happens before classification: the model should only see
    # DOM links that have never appeared in a previous successful scan.  This
    # prevents old navigation/product links from being reconsidered every day
    # and avoids emitting historical articles when the classifier changes.
    eligible = [] if baseline_only else candidates
    if known_urls:
        eligible = [c for c in eligible if c["url"] not in known_urls]
    if not eligible:
        return [], None, candidates

    if not use_llm:
        return _heuristic_from_candidates(eligible), None, candidates

    if not llm.configured():
        return [], "no_llm_key", candidates

    excerpt = html_links.html_excerpt(html)
    try:
        picked = llm.select_articles_from_page(
            source_name=source.name,
            home_url=source.home_url,
            candidates=eligible,
            html_excerpt=excerpt,
        )
    except Exception as e:
        return [], f"llm_error:{e}", candidates

    cand_urls = {c["url"] for c in eligible}
    out: list[dict[str, Any]] = []
    for a in picked:
        url = (a.get("url") or "").strip()
        if url not in cand_urls and url.rstrip("/") not in {
            x.rstrip("/") for x in cand_urls
        }:
            continue
        exact = (
            url
            if url in cand_urls
            else next((c for c in cand_urls if c.rstrip("/") == url.rstrip("/")), url)
        )
        title = a.get("title") or next(
            (c["title"] for c in eligible if c["url"] == exact), exact
        )
        out.append({"url": exact, "title": title})
    return out, None, candidates


def _heuristic_from_candidates(candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in candidates:
        title = (c.get("title") or "").strip()
        url = c["url"]
        if len(title) < 8:
            continue
        segs = [s for s in (urlparse(url).path or "").split("/") if s]
        if len(segs) < 1:
            continue
        low = title.lower()
        if low in {"read more", "learn more", "home", "blog", "about", "contact"}:
            continue
        out.append({"url": url, "title": title})
        if len(out) >= 40:
            break
    return out


def collect(
    source: Source,
    *,
    force_browser: bool = False,
    known_urls: set[str] | None = None,
    baseline_only: bool = False,
) -> tuple[list[dict[str, Any]], str | None, str, list[dict[str, str]]]:
    """Return (raw articles, error, transport, all DOM candidates).

    transport is http|browser|"" for logging via tag (llm / browser_llm).
    """
    page_url, html, transport_or_err = _load_page(source, force_browser=force_browser)
    if not html:
        return [], transport_or_err or "html_empty", "", []

    # transport_or_err is transport name when ok
    transport = transport_or_err or "http"
    raw, err, candidates = _denoise_with_html(
        source,
        page_url,
        html,
        use_llm=True,
        known_urls=known_urls,
        baseline_only=baseline_only,
    )
    return raw, err, transport, candidates


def collect_heuristic(
    source: Source,
    *,
    force_browser: bool = False,
    known_urls: set[str] | None = None,
    baseline_only: bool = False,
) -> tuple[list[dict[str, Any]], str | None, str, list[dict[str, str]]]:
    page_url, html, transport_or_err = _load_page(source, force_browser=force_browser)
    if not html:
        return [], transport_or_err or "html_empty", "", []
    transport = transport_or_err or "http"
    raw, err, candidates = _denoise_with_html(
        source,
        page_url,
        html,
        use_llm=False,
        known_urls=known_urls,
        baseline_only=baseline_only,
    )
    return raw, err, transport, candidates
