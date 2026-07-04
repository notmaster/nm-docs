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

fail() {
  echo "Project Feishu notification unavailable: $*" >&2
  exit 1
}

file_mode() {
  local file="$1"
  local os
  os="$(uname -s 2>/dev/null || printf unknown)"
  if [ "$os" = "Darwin" ] || [ "$os" = "FreeBSD" ]; then
    stat -f "%Lp" "$file" 2>/dev/null || true
  else
    stat -c "%a" "$file" 2>/dev/null || true
  fi
}

if [ ! -f "$CONFIG_FILE" ]; then
  fail "missing project config: $CONFIG_FILE"
fi

MODE="$(file_mode "$CONFIG_FILE")"
if [ "$MODE" != "600" ]; then
  fail "unsafe config permissions for $CONFIG_FILE: ${MODE:-unknown}. Run: chmod 600 \"$CONFIG_FILE\""
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

WEBHOOK_URL="${FEISHU_WEBHOOK_URL:-}"
SIGN_SECRET="${FEISHU_SIGN_SECRET:-}"

if [ -z "$WEBHOOK_URL" ]; then
  fail "missing FEISHU_WEBHOOK_URL in $CONFIG_FILE"
fi

if ! command -v curl >/dev/null 2>&1; then
  fail "curl is not available"
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

RESPONSE="$(curl --silent --show-error -X POST \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$WEBHOOK_URL" 2>&1)" || {
  fail "curl failed: $RESPONSE"
}

PARSED="$(RESPONSE="$RESPONSE" python3 - <<'PY'
import json
import os

try:
    data = json.loads(os.environ["RESPONSE"])
except Exception:
    print("unknown|failed to parse Feishu response")
    raise SystemExit

code = data.get("code", data.get("StatusCode", "unknown"))
message = data.get("msg", data.get("message", data.get("StatusMessage", "")))
print(f"{code}|{message}")
PY
)"

CODE="${PARSED%%|*}"
FEISHU_MESSAGE="${PARSED#*|}"

if [ "$CODE" != "0" ]; then
  fail "Feishu rejected notification: ${FEISHU_MESSAGE:-unknown error} (code: $CODE)"
fi

echo "Project Feishu notification sent: [$LEVEL] $TITLE"
