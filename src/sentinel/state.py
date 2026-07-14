"""Incremental collection state, persisted in the repo across runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("SENTINEL_ROOT", ".")).resolve()
STATE_DIR = ROOT / "state"
SOURCES_FILE = STATE_DIR / "sources.json"


def load_sources() -> dict[str, Any]:
    if SOURCES_FILE.exists():
        return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    return {"sources": {}}


def save_sources(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_FILE.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
