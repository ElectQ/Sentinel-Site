"""Shared HTTP client for feeds and HTML pages."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

from .util import env_str

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "45"))


def _insecure_hosts() -> set[str]:
    """Hosts that skip TLS verify (comma list). Use sparingly for MITM-proxy breakage."""
    raw = env_str("SSL_INSECURE_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def verify_for_url(url: str, *, source_ssl_verify: bool | None = None) -> bool | str:
    """Return httpx verify= value for this URL.

    - source_ssl_verify=False → never verify
    - host in SSL_INSECURE_HOSTS → never verify
    - else True (system/certifi defaults)
    """
    if source_ssl_verify is False:
        return False
    host = (urlparse(url).hostname or "").lower()
    if host and host in _insecure_hosts():
        return False
    # also match bare parent if listed without subdomain noise
    for h in _insecure_hosts():
        if host == h or host.endswith("." + h):
            return False
    return True


def client(**kwargs: Any) -> httpx.Client:
    headers = {
        "User-Agent": os.environ.get("HTTP_USER_AGENT", DEFAULT_UA),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    verify = kwargs.pop("verify", True)
    return httpx.Client(
        headers=headers,
        timeout=kwargs.pop("timeout", DEFAULT_TIMEOUT),
        follow_redirects=True,
        verify=verify,
        **kwargs,
    )


def get(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    accept: str | None = None,
    timeout: float | None = None,
    ssl_verify: bool | None = None,
) -> httpx.Response:
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    if accept:
        headers["Accept"] = accept
    kw: dict[str, Any] = {"verify": verify_for_url(url, source_ssl_verify=ssl_verify)}
    if timeout is not None:
        kw["timeout"] = timeout
    with client(**kw) as c:
        return c.get(url, headers=headers)


def probe(url: str, timeout: float = 8.0, *, ssl_verify: bool | None = None) -> tuple[str, int | None, str]:
    """Light reachability check. Returns (final_url, status, fetch_status)."""
    try:
        with client(timeout=timeout, verify=verify_for_url(url, source_ssl_verify=ssl_verify)) as c:
            try:
                r = c.head(url)
                if r.status_code in (405, 501) or r.status_code >= 400:
                    r = c.get(url, headers={"Range": "bytes=0-2047"})
            except httpx.HTTPError:
                r = c.get(url, headers={"Range": "bytes=0-2047"})

            final = str(r.url)
            code = r.status_code
            if code in (404, 410):
                return final, code, "not_found"
            if code in (401, 403):
                return final, code, "blocked"
            if 200 <= code < 400:
                return final, code, "ok"
            return final, code, "unknown"
    except Exception:
        return url, None, "unknown"
