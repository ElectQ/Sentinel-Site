#!/usr/bin/env python3
"""Feishu webhook notifier for Sentinel-Site ops.

Usage:
  python3 notify.py report  "title" "body markdown"
  python3 notify.py approval "title" "body" "evidence_url"
  python3 notify.py alert "title" "body"

Title is rendered as "[<repo>] <kind-header> · <title>" where <repo>
defaults to "Sentinel-Site" (override with FEISHU_REPO_PREFIX).

Message format v1:
  header: [Sentinel-Site] 📋 日报 · <title>
  body:   markdown, trailing footer with source + run link when given
  footer: via FEISHU_FOOTER (plain text) and FEISHU_RUN_URL (link)

Reads FEISHU_WEBHOOK (required), FEISHU_SECRET (optional) from
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
HEADER = {"report": "📋 日报", "approval": "✅ PR 批准", "alert": "🚨 告警", "weekly": "📊 周报"}
COLOR["weekly"] = "turquoise"


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


def post(kind: str, title: str, md: str) -> None:
    webhook = os.environ["FEISHU_WEBHOOK"]
    prefix = os.environ.get("FEISHU_REPO_PREFIX", "Sentinel-Site")
    full_title = f"[{prefix}] {HEADER[kind]} · {title}"
    footer_src = os.environ.get("FEISHU_FOOTER")
    footer_url = os.environ.get("FEISHU_RUN_URL")
    if footer_src or footer_url:
        bits = []
        if footer_src:
            bits.append(f"来源: {footer_src}")
        if footer_url:
            bits.append(f"[运行详情]({footer_url})")
        md += "\n" + " · ".join(bits)
    payload: dict = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": full_title},
                       "template": COLOR[kind]},
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
    if kind == "approval" and len(args) >= 4:
        body += f"\n证据: {args[3]}"
    post(kind, title, body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
