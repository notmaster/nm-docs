#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${HOME}/.config/nm-docs/nm-notify-feishu.env"
LEVEL="info"
TITLE="nm-docs notification"
MESSAGE=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --level)
      LEVEL="${2:-}"
      shift 2
      ;;
    --title)
      TITLE="${2:-}"
      shift 2
      ;;
    --message)
      MESSAGE="${2:-}"
      shift 2
      ;;
    *)
      MESSAGE="${MESSAGE}${MESSAGE:+ }$1"
      shift
      ;;
  esac
done

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Feishu notify config missing: $CONFIG_FILE"
  echo "Notification fallback [$LEVEL] $TITLE: $MESSAGE"
  exit 0
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

WEBHOOK_URL="${FEISHU_WEBHOOK_URL:-}"
SIGN_SECRET="${FEISHU_SIGN_SECRET:-}"

if [ -z "$WEBHOOK_URL" ]; then
  echo "Feishu notify config missing FEISHU_WEBHOOK_URL in $CONFIG_FILE"
  echo "Notification fallback [$LEVEL] $TITLE: $MESSAGE"
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is not available. Notification fallback [$LEVEL] $TITLE: $MESSAGE"
  exit 0
fi

TIMESTAMP="$(date +%s)"

PAYLOAD="$(LEVEL="$LEVEL" TITLE="$TITLE" MESSAGE="$MESSAGE" TIMESTAMP="$TIMESTAMP" SIGN_SECRET="$SIGN_SECRET" python3 - <<'PY'
import base64
import hashlib
import hmac
import json
import os

level = os.environ["LEVEL"]
title = os.environ["TITLE"]
message = os.environ["MESSAGE"]
timestamp = os.environ["TIMESTAMP"]
secret = os.environ.get("SIGN_SECRET", "")

payload = {
    "msg_type": "text",
    "content": {
        "text": f"[{level}] {title}\n{message}",
    },
}

if secret:
    key = f"{timestamp}\n{secret}".encode("utf-8")
    sign = base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode("utf-8")
    payload["timestamp"] = timestamp
    payload["sign"] = sign

print(json.dumps(payload, ensure_ascii=False))
PY
)"

curl -fsS -X POST \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$WEBHOOK_URL" >/dev/null || {
    echo "Feishu notification failed. Notification fallback [$LEVEL] $TITLE: $MESSAGE"
    exit 0
  }

echo "Feishu notification sent: [$LEVEL] $TITLE"
