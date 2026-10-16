#!/usr/bin/env bash
# Start mihomo egress proxy for collection. Config comes from MIHOMO_CONFIG_B64 secret.
set -euo pipefail

MIHOMO_VERSION=v1.19.32
BIN=/tmp/mihomo-bin

if [ ! -x "$BIN" ]; then
  curl -fsSL "https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/mihomo-linux-amd64-${MIHOMO_VERSION}.gz" | gunzip > "$BIN"
  chmod +x "$BIN"
fi

install -d -m 700 /tmp/mihomo
printf '%s' "$MIHOMO_CONFIG_B64" | base64 -d > /tmp/mihomo/config.yaml
chmod 600 /tmp/mihomo/config.yaml

"$BIN" -d /tmp/mihomo -f /tmp/mihomo/config.yaml > /tmp/mihomo/mihomo.log 2>&1 &

for i in $(seq 1 15); do
  ip=$(curl -fsS --max-time 5 -x http://127.0.0.1:7890 https://api.ipify.org || true)
  if [ -n "$ip" ]; then
    echo "proxy up, egress: $ip"
    exit 0
  fi
  sleep 1
done

echo "::error::proxy self-check failed"
tail -30 /tmp/mihomo/mihomo.log
exit 1
