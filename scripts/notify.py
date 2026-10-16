#!/usr/bin/env python3
"""Feishu notifier for Sentinel-Site ops. Two backends:

  app      send as the custom app bot via im/v1/messages (needs
           FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_CHAT_ID) — default
  webhook  legacy custom-bot webhook (FEISHU_WEBHOOK [+ FEISHU_SECRET])

Usage:
  python3 notify.py report   "title" "body md"
  python3 notify.py approval "title" "body md" "evidence_url"
  python3 notify.py alert    "title" "body md"

Card format v1: "[Sentinel-Site] <emoji header> · <title>", optional footer
via FEISHU_FOOTER and FEISHU_RUN_URL. Reads config from
~/.config/sentinel/feishu.env or environment. Stdlib only.
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

COLOR = {"report": "green", "approval": "blue", "alert": "red",
         "weekly": "turquoise"}
HEADER = {"report": "📋 日报", "approval": "✅ PR 批准",
          "alert": "🚨 告警", "weekly": "📊 周报"}

_TOKEN = {"v": None, "exp": 0.0}


def load_env() -> None:
    if os.environ.get("FEISHU_WEBHOOK") or os.environ.get("FEISHU_APP_ID"):
        return
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _app_token() -> str:
    now = time.time()
    if _TOKEN["v"] and _TOKEN["exp"] > now + 60:
        return _TOKEN["v"]
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": os.environ["FEISHU_APP_ID"],
                         "app_secret": os.environ["FEISHU_APP_SECRET"]}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.load(r)
    if d.get("code") != 0:
        raise RuntimeError(f"tenant_token error: {d}")
    _TOKEN.update(v=d["tenant_access_token"], exp=now + d.get("expire", 7000))
    return _TOKEN["v"]


def _webhook_sign(secret: str, ts: int) -> str:
    return base64.b64encode(
        hmac.digest(f"{ts}\n{secret}".encode("utf-8"), b"", hashlib.sha256)
    ).decode()


def send(kind: str, title: str, md: str, receive_id: str | None = None) -> None:
    """Send one card. receive_id overrides FEISHU_CHAT_ID (app backend)."""
    prefix = os.environ.get("FEISHU_REPO_PREFIX", "Sentinel-Site")
    full_title = f"[{prefix}] {HEADER[kind]} · {title}"
    footer, url = os.environ.get("FEISHU_FOOTER"), os.environ.get("FEISHU_RUN_URL")
    if footer or url:
        bits = [b for b in (f"来源: {footer}" if footer else "",
                            f"[运行详情]({url})" if url else "") if b]
        md += "\n" + " · ".join(bits)
    card = {"config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": full_title},
                       "template": COLOR[kind]},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": md}}]}

    mode = os.environ.get("FEISHU_MODE") or (
        "app" if os.environ.get("FEISHU_APP_ID") and
                os.environ.get("FEISHU_CHAT_ID") else "webhook")

    if mode == "app":
        body = {"receive_id": receive_id or os.environ["FEISHU_CHAT_ID"],
                "msg_type": "interactive",
                "content": json.dumps(card)}
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {_app_token()}"})
    else:
        payload: dict = {"msg_type": "interactive", "card": card}
        secret = os.environ.get("FEISHU_SECRET")
        if secret:
            ts = int(time.time())
            payload.update(timestamp=str(ts), sign=_webhook_sign(secret, ts))
        req = urllib.request.Request(
            os.environ["FEISHU_WEBHOOK"], data=json.dumps(payload).encode(),
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
    send(kind, title, body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
