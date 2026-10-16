"""Regenerate the source inventory table in README.md.
Usage: python -m sentinel.source_table [--check]
The table lives between HTML comments in README.md and is the only
machine-written region of that file. --check exits 1 when the region is
stale (used by CI); default mode rewrites it.
"""
from __future__ import annotations
import sys
from .collectors.sources import load_all
from .state import ROOT
README = ROOT / "README.md"
BEGIN = "<!-- source-table:begin (auto-generated, do not edit) -->"
END = "<!-- source-table:end -->"
def render() -> list[str]:
    sources = load_all()
    enabled = [s for s in sources if s.enabled]
    lines = [
        f"Current inventory: {len(enabled)} enabled "
        f"({sum(1 for s in enabled if s.collect_mode == 'rss')} `rss`, "
        f"{sum(1 for s in enabled if s.collect_mode == 'html_llm')} `html_llm`, "
        f"{sum(1 for s in enabled if s.collect_mode == 'browser_llm')} `browser_llm`), "
        f"{len(sources) - len(enabled)} disabled.",
        "",
        "| ID | Source | Home / feed | Mode |",
        "| --- | --- | --- | --- |",
    ]
    for s in sources:
        name = s.name + ("" if s.enabled else " *(disabled)*")
        parts = [f"[home]({s.home_url})"]
        if s.rss_url:
            parts.append(f"[feed]({s.rss_url})")
        lines.append(f"| `{s.id}` | {name} | {' · '.join(parts)} | `{s.collect_mode}` |")
    return lines
def main(argv: list[str] | None = None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    text = README.read_text(encoding="utf-8")
    begin, end = text.find(BEGIN), text.find(END)
    if begin == -1 or end == -1 or end < begin:
        print("README.md: source-table markers missing", file=sys.stderr)
        return 2
    block = BEGIN + "\n" + "\n".join(render()) + "\n" + END
    updated = text[:begin] + block + text[end + len(END):]
    if check:
        if updated == text:
            print("source table up to date")
            return 0
        print("source table stale: run `python -m sentinel.source_table`", file=sys.stderr)
        return 1
    if updated == text:
        print("source table up to date")
        return 0
    README.write_text(updated, encoding="utf-8")
    print("source table updated")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
