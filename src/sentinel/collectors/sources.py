"""Load and manage config/sources.yaml."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..state import ROOT

CONFIG_PATH = ROOT / "config" / "sources.yaml"
COLLECT_MODES = frozenset({"auto", "rss", "html_llm", "browser_llm"})
ACCESS_STATUSES = frozenset({"direct", "browser_required", "intermittent", "blocked"})


@dataclass
class Source:
    id: str
    name: str
    home_url: str
    rss_url: str = ""
    collect_mode: str = "auto"
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    notes: str = ""
    allowed_hosts: list[str] = field(default_factory=list)
    # Source-specific volatile query parameters removed before diffing URLs.
    strip_query_keys: list[str] = field(default_factory=list)
    # TLS: None = default; False = skip verify for this source (proxy MITM etc.)
    ssl_verify: bool | None = None
    # When True, after HTTP fail try Playwright then LLM
    browser_fallback: bool = False
    # Operational reachability recorded by a live source check. This is
    # descriptive metadata, not permission to evade an access-control wall.
    access_status: str = "direct"
    access_issue: str = ""
    access_tested_at: str = ""
    access_tested_via: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Source:
        ssl_v = d.get("ssl_verify", None)
        if ssl_v is not None:
            ssl_v = bool(ssl_v)
        mode = str(d.get("collect_mode") or "auto").strip().lower()
        if mode not in COLLECT_MODES:
            raise ValueError(
                f"invalid collect_mode for {d.get('id')}: {mode}; "
                f"expected one of {sorted(COLLECT_MODES)}"
            )
        rss_url = str(d.get("rss_url") or "").strip()
        if mode == "rss" and not rss_url:
            raise ValueError(f"collect_mode=rss requires rss_url for {d.get('id')}")
        access_status = str(d.get("access_status") or "direct").strip().lower()
        if access_status not in ACCESS_STATUSES:
            raise ValueError(
                f"invalid access_status for {d.get('id')}: {access_status}; "
                f"expected one of {sorted(ACCESS_STATUSES)}"
            )
        return cls(
            id=str(d["id"]).strip(),
            name=str(d.get("name") or d["id"]).strip(),
            home_url=str(d["home_url"]).strip(),
            rss_url=rss_url,
            collect_mode=mode,
            tags=[str(t) for t in (d.get("tags") or [])],
            enabled=bool(d.get("enabled", True)),
            notes=str(d.get("notes") or ""),
            allowed_hosts=[str(h) for h in (d.get("allowed_hosts") or [])],
            strip_query_keys=[
                str(k).lower() for k in (d.get("strip_query_keys") or []) if str(k)
            ],
            ssl_verify=ssl_v,
            browser_fallback=bool(d.get("browser_fallback", False)),
            access_status=access_status,
            access_issue=str(d.get("access_issue") or "").strip(),
            access_tested_at=str(d.get("access_tested_at") or "").strip(),
            access_tested_via=str(d.get("access_tested_via") or "").strip(),
        )


def load_all(path: Path | None = None) -> list[Source]:
    p = path or CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"sources config not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raw = data.get("sources") or []
    sources = [Source.from_dict(x) for x in raw if x.get("id") and x.get("home_url")]
    return sources


def load_enabled(path: Path | None = None) -> list[Source]:
    return [s for s in load_all(path) if s.enabled]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        sources = load_all()
        for s in sources:
            flag = "on " if s.enabled else "off"
            rss = "rss" if s.rss_url else "   "
            br = "br" if s.browser_fallback else "  "
            print(
                f"[{flag}] [{rss}] [{br}] [{s.collect_mode:11}] "
                f"[{s.access_status:16}] {s.id:24} {s.home_url}"
            )
            if s.access_issue:
                tested = f" at={s.access_tested_at}" if s.access_tested_at else ""
                via = f" via={s.access_tested_via}" if s.access_tested_via else ""
                print(f"              access: {s.access_issue}{tested}{via}")
            if s.notes:
                print(f"              notes: {s.notes}")
        print(f"total={len(sources)} enabled={sum(1 for s in sources if s.enabled)}")
        return 0
    if cmd == "validate":
        sources = load_all()
        errors: list[str] = []
        ids = [s.id for s in sources]
        duplicates = sorted({sid for sid in ids if ids.count(sid) > 1})
        if duplicates:
            errors.append(f"duplicate_ids:{','.join(duplicates)}")
        for s in sources:
            if s.collect_mode == "auto":
                errors.append(f"{s.id}:collect_mode_must_be_explicit")
            if s.collect_mode == "rss" and not s.rss_url:
                errors.append(f"{s.id}:rss_url_required")
            if s.collect_mode == "browser_llm" and not s.browser_fallback:
                errors.append(f"{s.id}:browser_fallback_required")
            if s.access_status == "browser_required" and not s.browser_fallback:
                errors.append(f"{s.id}:access_browser_required_without_fallback")
            if s.access_status == "blocked" and s.enabled:
                errors.append(f"{s.id}:blocked_source_must_be_disabled")
        if errors:
            for error in errors:
                print(f"ERROR {error}")
            print(f"invalid={len(errors)}")
            return 1
        counts = {
            mode: sum(1 for s in sources if s.collect_mode == mode)
            for mode in sorted(COLLECT_MODES)
            if any(s.collect_mode == mode for s in sources)
        }
        print(f"valid={len(sources)} enabled={sum(1 for s in sources if s.enabled)} modes={counts}")
        return 0
    if cmd == "check":
        from . import browser, llm_fallback, rss

        wanted = set(argv[1:])
        sources = load_all() if wanted else load_enabled()
        if wanted:
            sources = [s for s in sources if s.id in wanted]
            missing = sorted(wanted - {s.id for s in sources})
            if missing:
                print(f"unknown_sources={','.join(missing)}", file=sys.stderr)
                return 2
        ok = 0
        for s in sources:
            via = "?"
            try:
                if s.collect_mode == "rss":
                    items, err = rss.fetch_and_parse(s.rss_url)
                    if err:
                        via = f"rss_fail:{err}"
                    else:
                        via = f"rss:{len(items)}"
                        ok += 1
                else:
                    force_browser = s.collect_mode == "browser_llm"
                    items, err, transport, candidates = (
                        llm_fallback.collect_heuristic(
                            s, force_browser=force_browser
                        )
                    )
                    if err:
                        via = f"{s.collect_mode}_fail:{err}"
                    else:
                        via = (
                            f"{transport}_candidates:{len(candidates)}"
                            f" selected:{len(items)}"
                        )
                        ok += 1
            except Exception as e:
                via = f"error:{e}"
            print(f"{s.id:24} mode={s.collect_mode:11} {via}")
        browser.close()
        print(f"checked={len(sources)} roughly_ok={ok}")
        return 0 if ok == len(sources) else 1
    print(
        "usage: python -m sentinel.sources [list|validate|check [source_id...]]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
