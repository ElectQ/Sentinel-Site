#!/usr/bin/env python3
"""Feishu webhook notifier for Sentinel-Site ops.

Usage:
  python3 notify.py report  "title" "body markdown"
  python3 notify.py approval "title" "body" "evidence_url"
  python3 notify.py alert "title" "body"

Reads FEISHU_WEBHOOK (and optional FEISHU_SECRET) from
~/.config/sentinel/feishu.env or the environment. Stdlib only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ENV_FILE = Path.home() / ".config" / "sentinel" / "feishu.env"

COLOR = {"report": "green", "approval": "blue", "alert": "red"}
HEADER = {"report": "📋 运行报告", "approval": "✅ 待批准", "alert": "🚨 告警"}


def load_env() -> None:
    if os.environ.get("FEISHU_WEBHOOK"):
        return
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.digest(string_to_sign.encode("utf-8"), b"", hashlib.sha256)
    return base64.b64encode(digest).decode("utf-8")


def post(card_title: str, color: str, md: str) -> None:
    webhook = os.environ["FEISHU_WEBHOOK"]
    payload: dict = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": card_title},
                       "template": color},
            "elements": [{"tag": "div",
                          "text": {"tag": "lark_md", "content": md}}],
        },
    }
    secret = os.environ.get("FEISHU_SECRET")
    if secret:
        ts = int(time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = sign(secret, ts)
    req = urllib.request.Request(
        webhook, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.load(r)
    if resp.get("code") not in (0, None):
        print(f"feishu error: {resp}", file=sys.stderr)
        sys.exit(1)
    print("sent")


def main() -> int:
    load_env()
    args = sys.argv[1:]
    if len(args) < 3 or args[0] not in COLOR:
        print(__doc__)
        return 2
    kind, title, body = args[0], args[1], args[2]
    md = f"**{title}**\n{body}"
    if kind == "approval" and len(args) >= 4:
        md += f"\n证据: {args[3]}"
    post(f"{HEADER[kind]} {title}", COLOR[kind], md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
