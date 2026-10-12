#!/bin/sh
set -eu
: "${BOT_TOKEN:?BOT_TOKEN is required}"
: "${MT_API_ID:?MT_API_ID is required}"
: "${MT_API_HASH:?MT_API_HASH is required}"
: "${PUBLIC_URL:?PUBLIC_URL is required}"
export TELEGRAM_LOCAL_API_URL=http://127.0.0.1:8081
mkdir -p /data/telegram-api
# API listens only on container loopback; only Python app exposes the public webhook port.
telegram-bot-api --api-id="${MT_API_ID}" --api-hash="${MT_API_HASH}" \
  --local --http-ip-address=127.0.0.1 --http-port=8081 \
  --dir=/data/telegram-api &
API_PID=$!
cleanup() { kill "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
# Wait for HTTP API to answer; no bot calls until it is reachable.
python - <<'PY'
import time, urllib.request
for attempt in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:8081/", timeout=2)
        break
    except Exception as exc:
        # HTTP 404 means listener is ready.
        if getattr(exc, "code", None) == 404:
            break
        time.sleep(1)
else:
    raise SystemExit("Local Telegram API did not become ready")
PY
python -u main.py
