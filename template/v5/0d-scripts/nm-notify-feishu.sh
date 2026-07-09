#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${HOME}/.config/nm-docs/nm-notify-feishu.env"
LEVEL="info"
TITLE="nm-docs notification"
MESSAGE=""
REQUESTED_PROJECT_NAME=""

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
    --project)
      REQUESTED_PROJECT_NAME="${2:-}"
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
PROJECT_NAME="${REQUESTED_PROJECT_NAME:-${FEISHU_PROJECT_NAME:-${PROJECT_NAME:-}}}"

if [ -z "$PROJECT_NAME" ]; then
  PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  PROJECT_NAME="$(basename "$PROJECT_ROOT")"
fi

if [ -z "$WEBHOOK_URL" ]; then
  fail "missing FEISHU_WEBHOOK_URL in $CONFIG_FILE"
fi

if ! command -v curl >/dev/null 2>&1; then
  fail "curl is not available"
fi

TIMESTAMP="$(date +%s)"

PAYLOAD="$(LEVEL="$LEVEL" TITLE="$TITLE" MESSAGE="$MESSAGE" PROJECT_NAME="$PROJECT_NAME" TIMESTAMP="$TIMESTAMP" SIGN_SECRET="$SIGN_SECRET" python3 - <<'PY'
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import os

level = os.environ["LEVEL"]
title = os.environ["TITLE"]
message = os.environ["MESSAGE"]
project_name = os.environ["PROJECT_NAME"]
timestamp = os.environ["TIMESTAMP"]
secret = os.environ.get("SIGN_SECRET", "")

def header_template(value):
    normalized = value.lower().replace("-", "_")
    if normalized in {"success", "done", "completed", "merged", "merged_to_dev"}:
        return "green"
    if normalized in {"error", "failed", "failure", "blocked"}:
        return "red"
    if normalized in {"warning", "warn", "action_required", "needs_human", "needs_replan"}:
        return "yellow"
    if normalized in {"no_change", "skipped", "noop"}:
        return "grey"
    return "blue"

def next_step(value):
    normalized = value.lower().replace("-", "_")
    if normalized in {"action_required", "needs_human", "needs_replan"}:
        return "请管理员在当前 Agent 会话中回复确认或选择。"
    if normalized in {"error", "failed", "failure", "blocked"}:
        return "请查看失败阶段、终端输出和当前 Goal 状态后决定下一步。"
    if normalized in {"success", "done", "completed", "merged", "merged_to_dev"}:
        return "无需立即操作，按当前工作流继续验收或归档。"
    return "如需处理，请回到当前 Agent 会话继续。"

def is_diagnostic(value):
    normalized = value.lower().replace("-", "_")
    return normalized in {
        "action_required",
        "needs_human",
        "needs_replan",
        "warning",
        "warn",
        "error",
        "failed",
        "failure",
        "blocked",
    }

def markdown_block(content):
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}

sent_at = datetime.fromtimestamp(int(timestamp), timezone.utc).astimezone(
    timezone(timedelta(hours=8))
).strftime("%Y-%m-%d %H:%M:%S UTC+8")

lines = [
    f"{level} · sent {sent_at}",
    f"项目：{project_name}",
    message or "-",
]

if is_diagnostic(level):
    lines.append(f"下一步：{next_step(level)}")

payload = {
    "msg_type": "interactive",
    "card": {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": header_template(level),
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": [markdown_block("\n".join(lines))],
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
