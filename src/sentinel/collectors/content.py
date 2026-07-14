"""Fetch and extract cleaned article text for newly emitted URLs only."""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from datetime import datetime, timezone
from typing import Any

from selectolax.parser import HTMLParser

from .. import llm
from ..normalize import canonicalize
from ..util import env_int
from . import browser, html_links
from .sources import Source

CONTENT_SELECTORS = (
    "article",
    "main",
    '[role="main"]',
    # vBulletin thread bodies (UnknownCheats and compatible forums). Selecting
    # individual posts avoids treating forum navigation and "similar threads"
    # tables as article content; the longest post is kept by extract_text().
    '[id^="post_message_"]',
    ".postcontent",
    ".postbody",
    ".entry-content",
    ".post-content",
    ".article-content",
    ".blog-post-content",
    ".single-post-content",
    ".td-post-content",
)
NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "footer",
    "header",
    "form",
    "aside",
    ".cookie",
    ".cookies",
    ".newsletter",
    ".social-share",
    ".related-posts",
)


def _jsonld_article_body(tree: HTMLParser) -> str:
    def find(value: Any) -> str:
        if isinstance(value, list):
            for item in value:
                found = find(item)
                if found:
                    return found
            return ""
        if not isinstance(value, dict):
            return ""
        body = value.get("articleBody")
        if isinstance(body, str) and body.strip():
            return body
        for key in ("@graph", "mainEntity", "itemListElement"):
            found = find(value.get(key))
            if found:
                return found
        return ""

    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text(strip=True)
        if not raw:
            continue
        try:
            found = find(json.loads(raw))
        except (TypeError, json.JSONDecodeError):
            continue
        if found:
            return found
    return ""


def _clean_text(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw in html_lib.unescape(text or "").splitlines():
        line = re.sub(r"[\t\r\f\v ]+", " ", raw).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines).strip()


def extract_text_with_method(document: str) -> tuple[str, str]:
    """Return cleaned text and the deterministic extraction method used."""
    if not document:
        return "", "empty"
    if "<" not in document and ">" not in document:
        return _clean_text(document), "plain"

    tree = HTMLParser(document)
    jsonld = _clean_text(_jsonld_article_body(tree))
    for selector in NOISE_SELECTORS:
        for node in tree.css(selector):
            node.decompose()

    choices: list[tuple[str, str]] = []
    for selector in CONTENT_SELECTORS:
        for node in tree.css(selector):
            text = _clean_text(node.text(separator="\n", strip=True))
            if text:
                choices.append((selector, text))
    if jsonld:
        choices.append(("jsonld:articleBody", jsonld))
    if not choices and tree.body:
        choices.append(("body", _clean_text(tree.body.text(separator="\n", strip=True))))
    if not choices:
        return "", "empty"
    method, best = max(choices, key=lambda item: len(item[1]))
    return best[: max(1, env_int("CONTENT_MAX_CHARS", 60000))], method


def extract_text(document: str) -> str:
    """Extract readable, untrusted text from a rendered HTML document/fragment."""
    return extract_text_with_method(document)[0]


def extract_block_candidates(document: str, *, limit: int = 12) -> list[dict[str, Any]]:
    """Build bounded DOM text blocks for the LLM fallback selector.

    Full HTML is never sent to the model; only short excerpts from these blocks
    are. The returned records keep full cleaned text locally for the chosen IDs.
    """
    if not document or ("<" not in document and ">" not in document):
        return []
    tree = HTMLParser(document)
    for selector in NOISE_SELECTORS:
        for node in tree.css(selector):
            node.decompose()

    rows: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    selectors = (*CONTENT_SELECTORS, "section", "div")
    for selector in selectors:
        for node in tree.css(selector):
            text = _clean_text(node.text(separator="\n", strip=True))
            if len(text) < 120 or text in seen_text:
                continue
            seen_text.add(text)
            link_chars = sum(
                len(_clean_text(a.text(separator=" ", strip=True)))
                for a in node.css("a")
            )
            link_ratio = min(1.0, link_chars / max(1, len(text)))
            if link_ratio > 0.65:
                continue
            score = int(min(len(text), 60_000) * (1.0 - link_ratio))
            rows.append(
                {
                    "kind": selector,
                    "text": text[: max(1, env_int("CONTENT_MAX_CHARS", 60000))],
                    "chars": len(text),
                    "link_ratio": link_ratio,
                    "score": score,
                }
            )
    rows.sort(key=lambda row: (int(row["score"]), int(row["chars"])), reverse=True)
    return rows[: max(1, limit)]


def _extract_with_llm_blocks(document: str, article: dict[str, Any]) -> str:
    blocks = extract_block_candidates(document)
    ids = llm.select_content_blocks(
        title=str(article.get("title") or ""),
        url=str(article.get("url") or ""),
        blocks=blocks,
    )
    selected: list[str] = []
    for idx in ids:
        if 0 <= idx < len(blocks):
            text = str(blocks[idx].get("text") or "")
            if text and text not in selected:
                selected.append(text)
    return _clean_text("\n\n".join(selected))


def _validate_final_url(final_url: str, source: Source) -> None:
    allowed = canonicalize(
        final_url,
        home_url=source.home_url,
        allowed_hosts=source.allowed_hosts or None,
        strip_query_keys=source.strip_query_keys or None,
    )
    if not allowed:
        raise RuntimeError(f"content_redirect_disallowed:{final_url}")


def _apply_content(
    article: dict[str, Any],
    text: str,
    *,
    status: str,
    via: str,
    final_url: str,
) -> dict[str, Any]:
    article["content"] = text
    article["content_format"] = "text/plain"
    article["content_status"] = status
    article["content_via"] = via
    article["content_source_url"] = final_url
    article["content_chars"] = len(text)
    article["content_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    article["content_fetched_at"] = datetime.now(timezone.utc).isoformat()
    article.pop("content_error", None)
    article.pop("content_html", None)
    return article


def enrich(article: dict[str, Any], source: Source) -> dict[str, Any]:
    """Best-effort content enrichment. Never drops a detected article."""
    article = dict(article)
    rss_document = str(article.get("content_html") or "")
    summary_document = str(article.get("summary") or "")
    rss_text = extract_text(rss_document) if rss_document else ""
    summary_text = extract_text(summary_document) if summary_document else ""
    min_chars = max(1, env_int("CONTENT_MIN_CHARS", 200))
    rss_min_chars = max(min_chars, env_int("CONTENT_RSS_MIN_CHARS", 800))

    if rss_text and len(rss_text) >= rss_min_chars:
        return _apply_content(
            article,
            rss_text,
            status="ok",
            via="rss",
            final_url=article["url"],
        )

    url = article["url"]
    errors: list[str] = []
    transports = (
        ("browser",)
        if source.collect_mode == "browser_llm"
        else (("http", "browser") if source.browser_fallback else ("http",))
    )
    for transport in transports:
        try:
            if transport == "browser":
                final_url, document = browser.fetch_html(url)
            else:
                final_url, document = html_links.fetch_html(
                    url, ssl_verify=source.ssl_verify
                )
            _validate_final_url(final_url, source)
            text, extraction_method = extract_text_with_method(document)
            content_via = transport
            if extraction_method == "body" or len(text) < min_chars:
                if llm.configured():
                    selected_text = _extract_with_llm_blocks(document, article)
                    if selected_text:
                        text = selected_text
                        content_via = f"{transport}_llm_blocks"
                elif extraction_method == "body":
                    raise RuntimeError("content_body_ambiguous_without_llm")
            if len(text) < min_chars:
                raise RuntimeError(f"content_too_short:{len(text)}")
            return _apply_content(
                article,
                text,
                status="ok",
                via=content_via,
                final_url=final_url,
            )
        except Exception as exc:
            errors.append(f"{transport}:{type(exc).__name__}:{exc}")

    partial = rss_text or summary_text
    if partial:
        result = _apply_content(
            article,
            partial,
            status="partial",
            via="rss_summary",
            final_url=url,
        )
        result["content_error"] = "; ".join(errors)[:500]
        return result

    article.pop("content_html", None)
    article["content"] = ""
    article["content_format"] = "text/plain"
    article["content_status"] = "failed"
    article["content_via"] = ""
    article["content_source_url"] = url
    article["content_chars"] = 0
    article["content_sha256"] = ""
    article["content_fetched_at"] = datetime.now(timezone.utc).isoformat()
    article["content_error"] = "; ".join(errors)[:500]
    return article
