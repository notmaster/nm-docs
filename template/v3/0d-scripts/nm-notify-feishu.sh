#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${HOME}/.config/nm-docs/nm-notify-feishu.env"
LEVEL="info"
TITLE="NM V3 notification"
MESSAGE=""
PROJECT=""
SEVERITY=""

fail() {
  echo "Project Feishu notification unavailable: $*" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --level|--title|--message|--project|--severity)
      [ "$#" -ge 2 ] || fail "$1 requires a value"
      case "$1" in
        --level) LEVEL="$2" ;;
        --title) TITLE="$2" ;;
        --message) MESSAGE="$2" ;;
        --project) PROJECT="$2" ;;
        --severity) SEVERITY="$2" ;;
      esac
      shift 2
      ;;
    *) fail "unsupported argument: $1" ;;
  esac
done

case "$SEVERITY" in progress|attention) ;; *) fail "--severity must be progress|attention" ;; esac
[ -f "$CONFIG_FILE" ] || fail "missing config: $CONFIG_FILE"

file_mode() {
  case "$(uname -s 2>/dev/null || true)" in
    Darwin|FreeBSD) stat -f "%Lp" "$1" 2>/dev/null || true ;;
    *) stat -c "%a" "$1" 2>/dev/null || true ;;
  esac
}

MODE="$(file_mode "$CONFIG_FILE")"
[ "$MODE" = "600" ] || fail "unsafe config permissions for $CONFIG_FILE: ${MODE:-unknown}; run chmod 600"

CONFIG_JSON="$(python3 - "$CONFIG_FILE" <<'PY'
import json
import re
import sys
from pathlib import Path

allowed = {
    "FEISHU_WEBHOOK_PROGRESS",
    "FEISHU_SIGN_SECRET_PROGRESS",
    "FEISHU_WEBHOOK_ATTENTION",
    "FEISHU_SIGN_SECRET_ATTENTION",
    "FEISHU_PROJECT_NAME",
}
values = {}
for number, raw in enumerate(Path(sys.argv[1]).read_text(encoding="utf-8").splitlines(), 1):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", line)
    if not match:
        raise SystemExit(f"invalid config line {number}")
    key, value = match.groups()
    if key not in allowed:
        raise SystemExit(f"unsupported config key on line {number}: {key}")
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    if "\x00" in value or "\n" in value or "\r" in value:
        raise SystemExit(f"unsafe value on line {number}")
    values[key] = value
print(json.dumps(values))
PY
)" || fail "failed to parse allowlisted KEY=VALUE config"

read_config() {
  CONFIG_JSON="$CONFIG_JSON" python3 - "$1" <<'PY'
import json
import os
import sys
print(json.loads(os.environ["CONFIG_JSON"]).get(sys.argv[1], ""))
PY
}

PROGRESS_WEBHOOK="$(read_config FEISHU_WEBHOOK_PROGRESS)"
ATTENTION_WEBHOOK="$(read_config FEISHU_WEBHOOK_ATTENTION)"
[ -n "$PROGRESS_WEBHOOK" ] || fail "FEISHU_WEBHOOK_PROGRESS is required"
[ -n "$ATTENTION_WEBHOOK" ] || fail "FEISHU_WEBHOOK_ATTENTION is required"
[ "$PROGRESS_WEBHOOK" != "$ATTENTION_WEBHOOK" ] || fail "progress and attention webhooks must be distinct"

if [ "$SEVERITY" = "progress" ]; then
  WEBHOOK_URL="$PROGRESS_WEBHOOK"
  SIGN_SECRET="$(read_config FEISHU_SIGN_SECRET_PROGRESS)"
else
  WEBHOOK_URL="$ATTENTION_WEBHOOK"
  SIGN_SECRET="$(read_config FEISHU_SIGN_SECRET_ATTENTION)"
fi

if [ -z "$PROJECT" ]; then
  PROJECT="$(read_config FEISHU_PROJECT_NAME)"
fi
if [ -z "$PROJECT" ]; then
  PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  PROJECT="$(basename "$PROJECT_ROOT")"
fi

command -v curl >/dev/null 2>&1 || fail "curl is unavailable"
TIMESTAMP="$(date +%s)"

PAYLOAD="$(LEVEL="$LEVEL" SEVERITY="$SEVERITY" TITLE="$TITLE" MESSAGE="$MESSAGE" PROJECT="$PROJECT" TIMESTAMP="$TIMESTAMP" SIGN_SECRET="$SIGN_SECRET" python3 - <<'PY'
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os

level = os.environ["LEVEL"]
timestamp = os.environ["TIMESTAMP"]
secret = os.environ.get("SIGN_SECRET", "")
severity = os.environ["SEVERITY"]
sent_at = datetime.fromtimestamp(int(timestamp), timezone.utc).astimezone(
    timezone(timedelta(hours=8))
).isoformat(timespec="seconds")
lines = [
    f"severity={severity} · sent {sent_at}",
    f"项目：{os.environ['PROJECT']}",
    os.environ.get("MESSAGE", "") or "-",
]
if level == "completed":
    lines.append("下一步：工作已完成，请管理员按当前工作流验收或归档。")
elif level == "action_required":
    lines.append("下一步：请返回当前 Agent 任务查看决策、风险或阻塞详情。")
elif level == "error":
    lines.append("下一步：请查看失败阶段、验证输出和当前 Goal 状态后决定如何处理。")

colors = {
    "completed": "green",
    "action_required": "yellow",
    "error": "red",
}
payload = {
    "msg_type": "interactive",
    "card": {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": colors.get(level, "blue"),
            "title": {"tag": "plain_text", "content": os.environ["TITLE"]},
        },
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}],
    },
}
if secret:
    key = f"{timestamp}\n{secret}".encode()
    payload["timestamp"] = timestamp
    payload["sign"] = base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()
print(json.dumps(payload, ensure_ascii=False))
PY
)"

CURL_CONFIG_URL="${WEBHOOK_URL//\\/\\\\}"
CURL_CONFIG_URL="${CURL_CONFIG_URL//\"/\\\"}"
RESPONSE="$(curl --disable --silent --show-error \
  --connect-timeout 10 --max-time 30 -X POST \
  -H "Content-Type: application/json" \
  --config /dev/fd/3 --data-binary @- \
  3<<<"url = \"$CURL_CONFIG_URL\"" 2>&1 <<<"$PAYLOAD")" || fail "curl failed: $RESPONSE"

PARSED="$(RESPONSE="$RESPONSE" python3 - <<'PY'
import json
import os
try:
    data = json.loads(os.environ["RESPONSE"])
except Exception:
    print("unknown|failed to parse Feishu response")
    raise SystemExit
print(f"{data.get('code', data.get('StatusCode', 'unknown'))}|{data.get('msg', data.get('message', data.get('StatusMessage', '')))}")
PY
)"
CODE="${PARSED%%|*}"
DETAIL="${PARSED#*|}"
[ "$CODE" = "0" ] || fail "Feishu rejected notification: ${DETAIL:-unknown error} (code: $CODE)"
echo "Project Feishu notification sent: severity=$SEVERITY $TITLE"
