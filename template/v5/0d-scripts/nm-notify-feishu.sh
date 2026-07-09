#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${HOME}/.config/nm-docs/nm-notify-feishu.env"
LEVEL="info"
TITLE="nm-docs notification"
MESSAGE=""
REQUESTED_PROJECT_NAME=""
# progress | attention | empty (use default webhook)
SEVERITY=""

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
    --severity)
      SEVERITY="${2:-}"
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

# Optional project-profile override of env var *names* (never secrets).
PROFILE_FILE="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/0c-workflow/project-profile.yml"
PROGRESS_WEBHOOK_ENV="FEISHU_WEBHOOK_PROGRESS"
PROGRESS_SECRET_ENV="FEISHU_SIGN_SECRET_PROGRESS"
ATTENTION_WEBHOOK_ENV="FEISHU_WEBHOOK_ATTENTION"
ATTENTION_SECRET_ENV="FEISHU_SIGN_SECRET_ATTENTION"
if [ -f "$PROFILE_FILE" ]; then
  # shellcheck disable=SC2034
  eval "$(
    PROFILE_FILE="$PROFILE_FILE" python3 - <<'PY'
import os
import re
from pathlib import Path

text = Path(os.environ["PROFILE_FILE"]).read_text(encoding="utf-8")
# Minimal YAML key scrape (no dependency on PyYAML).
patterns = {
    "progress_webhook_env": r"progress_webhook_env:\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)",
    "attention_webhook_env": r"attention_webhook_env:\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)",
    "progress_secret_env": r"progress_secret_env:\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)",
    "attention_secret_env": r"attention_secret_env:\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)",
}
out = {}
for key, pat in patterns.items():
    m = re.search(pat, text)
    if m:
        out[key] = m.group(1)

# Derive secret env names from webhook env names when only webhook keys are set.
if "progress_webhook_env" in out and "progress_secret_env" not in out:
    wh = out["progress_webhook_env"]
    if wh.endswith("_WEBHOOK_PROGRESS") or "WEBHOOK_PROGRESS" in wh:
        out["progress_secret_env"] = wh.replace("WEBHOOK", "SIGN_SECRET", 1)
    elif wh.startswith("FEISHU_WEBHOOK_"):
        out["progress_secret_env"] = "FEISHU_SIGN_SECRET_PROGRESS"
if "attention_webhook_env" in out and "attention_secret_env" not in out:
    wh = out["attention_webhook_env"]
    if wh.endswith("_WEBHOOK_ATTENTION") or "WEBHOOK_ATTENTION" in wh:
        out["attention_secret_env"] = wh.replace("WEBHOOK", "SIGN_SECRET", 1)
    elif wh.startswith("FEISHU_WEBHOOK_"):
        out["attention_secret_env"] = "FEISHU_SIGN_SECRET_ATTENTION"

mapping = {
    "progress_webhook_env": "PROGRESS_WEBHOOK_ENV",
    "progress_secret_env": "PROGRESS_SECRET_ENV",
    "attention_webhook_env": "ATTENTION_WEBHOOK_ENV",
    "attention_secret_env": "ATTENTION_SECRET_ENV",
}
for src, dst in mapping.items():
    if src in out:
        print(f'{dst}="{out[src]}"')
PY
  )"
fi

# Infer severity from level when caller only passed --level (legacy path).
if [ -z "$SEVERITY" ]; then
  LEVEL_LC="$(printf '%s' "$LEVEL" | tr '[:upper:]' '[:lower:]')"
  case "$LEVEL_LC" in
    error|failed|failure|blocked|action_required|needs_human|needs_replan)
      SEVERITY="attention"
      ;;
    *)
      SEVERITY="progress"
      ;;
  esac
fi

case "$SEVERITY" in
  progress|attention) ;;
  *)
    fail "--severity must be progress|attention (got: $SEVERITY)"
    ;;
esac

resolve_channel() {
  local severity="$1"
  local webhook_env secret_env webhook secret
  case "$severity" in
    progress)
      webhook_env="$PROGRESS_WEBHOOK_ENV"
      secret_env="$PROGRESS_SECRET_ENV"
      ;;
    attention)
      webhook_env="$ATTENTION_WEBHOOK_ENV"
      secret_env="$ATTENTION_SECRET_ENV"
      ;;
  esac
  webhook="${!webhook_env:-}"
  secret="${!secret_env:-}"
  if [ -z "$webhook" ]; then
    webhook="${FEISHU_WEBHOOK_URL:-}"
    secret="${FEISHU_SIGN_SECRET:-}"
  elif [ -z "$secret" ]; then
    secret="${FEISHU_SIGN_SECRET:-}"
  fi
  printf '%s\n%s\n' "$webhook" "$secret"
}

CHANNEL_LINES="$(resolve_channel "$SEVERITY")"
WEBHOOK_URL="$(printf '%s\n' "$CHANNEL_LINES" | sed -n '1p')"
SIGN_SECRET="$(printf '%s\n' "$CHANNEL_LINES" | sed -n '2p')"
PROJECT_NAME="${REQUESTED_PROJECT_NAME:-${FEISHU_PROJECT_NAME:-${PROJECT_NAME:-}}}"

if [ -z "$PROJECT_NAME" ]; then
  PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  PROJECT_NAME="$(basename "$PROJECT_ROOT")"
fi

if [ -z "$WEBHOOK_URL" ]; then
  fail "missing webhook for severity=$SEVERITY (set ${PROGRESS_WEBHOOK_ENV}/${ATTENTION_WEBHOOK_ENV} or FEISHU_WEBHOOK_URL) in $CONFIG_FILE"
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

echo "Project Feishu notification sent: [$LEVEL] severity=$SEVERITY $TITLE"
