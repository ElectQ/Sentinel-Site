"""Incremental collection state, persisted in the repo across runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("SENTINEL_ROOT", ".")).resolve()
STATE_DIR = ROOT / "state"
SOURCES_FILE = STATE_DIR / "sources.json"
EMITTED_FILE = STATE_DIR / "emitted.json"


def load_sources() -> dict[str, Any]:
    if SOURCES_FILE.exists():
        return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    return {"sources": {}}


def _save(path: Path, value: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def save_sources(state: dict[str, Any]) -> None:
    sources = dict(state)
    sources.pop("emitted", None)
    _save(SOURCES_FILE, sources)


def _bundle_emitted() -> dict[str, Any]:
    emitted: dict[str, Any] = {}
    bundles = ROOT / "bundles"
    for path in bundles.glob("20*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in data.get("items") or []:
            source_id = item.get("who") or item.get("source_id") or ""
            external_id = item.get("external_id") or item.get("id") or ""
            if source_id and external_id:
                emitted.setdefault(
                    f"{source_id}:{external_id}",
                    {"bundle_date": data.get("collect_date") or path.stem},
                )
    return emitted


def load_emitted() -> dict[str, Any]:
    if EMITTED_FILE.exists():
        try:
            emitted = json.loads(EMITTED_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            emitted = {}
    else:
        emitted = {}
    if not emitted:
        emitted = _bundle_emitted()
    return emitted


def save_emitted(emitted: dict[str, Any]) -> None:
    _save(EMITTED_FILE, emitted)
