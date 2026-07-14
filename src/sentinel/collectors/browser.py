"""Headless Chromium fetch — last-resort path for CF / bot walls.

Uses Playwright. Only invoked when plain HTTP fails (403/SSL/timeout) or
source.browser_fallback is forced. Returns rendered HTML for LLM denoise.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..util import env_bool, env_int, env_str

# Shared browser process per run (lazy)
_browser: Any = None
_playwright: Any = None
_contexts: dict[str, Any] = {}


def available() -> bool:
    if env_bool("BROWSER_ENABLED", True) is False:
        return False
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _proxy_from_env() -> dict[str, str] | None:
    """Playwright proxy from standard env (prefer http_proxy for HTTP proxy)."""
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = os.environ.get(key)
        if not val:
            continue
        # Playwright wants http:// host for HTTP proxies; socks5 ok as-is
        return {"server": val}
    return None


def _ensure_browser():
    global _browser, _playwright
    if _browser is not None:
        return _browser
    launch_kwargs: dict[str, Any] = {
        "headless": env_bool("BROWSER_HEADLESS", True),
    }
    executable_path = env_str("BROWSER_EXECUTABLE_PATH")
    if executable_path:
        executable = Path(executable_path).expanduser()
        if not executable.is_file():
            raise RuntimeError(f"browser_executable_not_found:{executable}")
        launch_kwargs["executable_path"] = str(executable)

    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright().start()
    proxy = _proxy_from_env()
    if proxy:
        launch_kwargs["proxy"] = proxy
    _browser = _playwright.chromium.launch(**launch_kwargs)
    return _browser


def close() -> None:
    global _browser, _playwright, _contexts
    for context in list(_contexts.values()):
        try:
            context.close()
        except Exception:
            pass
    _contexts = {}
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    try:
        if _playwright is not None:
            _playwright.stop()
    except Exception:
        pass
    _browser = None
    _playwright = None


def _context_key(url: str) -> str:
    host = (urlparse(url).hostname or "default").lower()
    return host[4:] if host.startswith("www.") else host


def _ensure_context(url: str):
    key = _context_key(url)
    if key in _contexts:
        return _contexts[key]

    browser = _ensure_browser()
    ua = env_str("BROWSER_USER_AGENT") or env_str("HTTP_USER_AGENT")
    if not ua:
        # Keep the UA version and OS aligned with the actual bundled browser.
        if sys.platform == "darwin":
            platform_token = "Macintosh; Intel Mac OS X 10_15_7"
        elif sys.platform.startswith("win"):
            platform_token = "Windows NT 10.0; Win64; x64"
        else:
            platform_token = "X11; Linux x86_64"
        ua = (
            f"Mozilla/5.0 ({platform_token}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{browser.version} Safari/537.36"
        )

    context = browser.new_context(
        user_agent=ua,
        locale="en-US",
        viewport={"width": 1365, "height": 900},
        java_script_enabled=True,
        ignore_https_errors=True,  # MITM / broken chains after proxy
    )
    _contexts[key] = context
    return context


def fetch_html(
    url: str,
    *,
    wait_until: str = "domcontentloaded",
    timeout_ms: int | None = None,
    wait_extra_ms: int | None = None,
) -> tuple[str, str]:
    """Return (final_url, rendered_html). Raises on hard failure."""
    if not available():
        raise RuntimeError("playwright_not_installed_or_disabled")

    timeout_ms = timeout_ms or env_int("BROWSER_TIMEOUT_MS", 60000)
    wait_extra_ms = wait_extra_ms if wait_extra_ms is not None else env_int("BROWSER_WAIT_MS", 2000)
    context = _ensure_context(url)
    page = context.new_page()
    try:
        page.set_default_timeout(timeout_ms)
        resp = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        if wait_extra_ms > 0:
            page.wait_for_timeout(wait_extra_ms)
        # light scroll to trigger lazy lists
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight/3)")
            page.wait_for_timeout(500)
        except Exception:
            pass
        final = page.url
        html = page.content()
        status = resp.status if resp is not None else 0
        # Cloudflare challenge pages are often 403/503 with "Just a moment"
        low = html[:4000].lower()
        if status in (401, 403) and ("just a moment" in low or "cf-browser-verification" in low):
            # wait longer once for challenge
            page.wait_for_timeout(env_int("BROWSER_CF_WAIT_MS", 8000))
            html = page.content()
            final = page.url
            low = html[:4000].lower()
            if "just a moment" in low or "checking your browser" in low:
                raise RuntimeError(f"cf_challenge_unresolved status={status}")
        if status >= 400 and len(html) < 500:
            raise RuntimeError(f"http_{status}")
        return final, html
    finally:
        try:
            page.close()
        except Exception:
            pass
