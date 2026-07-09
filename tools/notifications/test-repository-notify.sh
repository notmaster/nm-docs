#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/nm-docs-notify-test.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

TEST_HOME="$TMP_ROOT/home"
CONFIG_DIR="$TEST_HOME/.config/nm-docs"
CONFIG_FILE="$CONFIG_DIR/nm-notify-feishu.env"
MOCK_BIN="$TMP_ROOT/bin"

mkdir -p "$CONFIG_DIR" "$MOCK_BIN"

write_config() {
  printf '%s\n' \
    'FEISHU_WEBHOOK_PROGRESS=https://example.invalid/progress' \
    'FEISHU_SIGN_SECRET_PROGRESS=progress-test-secret' \
    'FEISHU_WEBHOOK_ATTENTION=https://example.invalid/attention' \
    'FEISHU_SIGN_SECRET_ATTENTION=attention-test-secret' \
    >"$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE"
}

write_config
printf '%s\n' 'trace = -' >"$TEST_HOME/.curlrc"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'first_arg="${1:-}"' \
  'if [ "$first_arg" != "--disable" ]; then' \
  '  printf "%s\n" "curl --disable must be the first option" >&2' \
  '  exit 97' \
  'fi' \
  'payload=""' \
  'payload_source=""' \
  'url=""' \
  'config_source=""' \
  'connect_timeout=""' \
  'max_time=""' \
  'while [ "$#" -gt 0 ]; do' \
  '  case "$1" in' \
  '    --disable|--silent|--show-error) shift ;;' \
  '    --connect-timeout) connect_timeout="${2:-}"; shift 2 ;;' \
  '    --max-time) max_time="${2:-}"; shift 2 ;;' \
  '    --config) config_source="${2:-}"; shift 2 ;;' \
  '    --data-binary) payload_source="${2:-}"; shift 2 ;;' \
  '    -H|-X) shift 2 ;;' \
  '    *) printf "%s\n" "unexpected positional curl argument" >&2; exit 99 ;;' \
  '  esac' \
  'done' \
  'if [ "$connect_timeout" != "10" ] || [ "$max_time" != "30" ]; then' \
  '  printf "%s\n" "unexpected curl timeouts" >&2' \
  '  exit 98' \
  'fi' \
  'if [ "$config_source" != "/dev/fd/3" ]; then' \
  '  printf "%s\n" "webhook URL must use curl config fd 3" >&2' \
  '  exit 96' \
  'fi' \
  'if [ "$payload_source" != "@-" ]; then' \
  '  printf "%s\n" "payload must use curl stdin" >&2' \
  '  exit 95' \
  'fi' \
  'IFS= read -r config_line <"$config_source"' \
  'case "$config_line" in' \
  '  '\''url = "'\''*'\''"'\'') ;;' \
  '  *) printf "%s\n" "invalid curl URL config" >&2; exit 94 ;;' \
  'esac' \
  'url="${config_line#url = \"}"' \
  'url="${url%\"}"' \
  'payload="$(cat)"' \
  ': "${CAPTURE_DIR:?CAPTURE_DIR is required}"' \
  'printf "%s" "$url" >"$CAPTURE_DIR/url"' \
  'printf "%s" "$payload" >"$CAPTURE_DIR/payload.json"' \
  'if [ -n "${MOCK_EXIT_CODE:-}" ]; then' \
  '  printf "%s\n" "${MOCK_ERROR:-simulated transport failure}" >&2' \
  '  exit "$MOCK_EXIT_CODE"' \
  'fi' \
  'if [ -n "${MOCK_RESPONSE:-}" ]; then' \
  '  printf "%s\n" "$MOCK_RESPONSE"' \
  'else' \
  '  printf "%s\n" '\''{"code":0,"msg":"ok"}'\''' \
  'fi' \
  >"$MOCK_BIN/curl"
chmod +x "$MOCK_BIN/curl"

run_success_case() {
  local severity="$1"
  local event="$2"
  local expected_url="$3"
  local expected_color="$4"
  local capture="$TMP_ROOT/capture-$event-$severity"

  mkdir -p "$capture"
  HOME="$TEST_HOME" CAPTURE_DIR="$capture" PATH="$MOCK_BIN:$PATH" \
    "$ROOT/0d-scripts/notify-event.sh" \
    --event "$event" \
    --severity "$severity" \
    --title "Repository notification test" \
    --message "branch=feature/test status=verified" \
    >"$capture/stdout"

  CAPTURE_DIR="$capture" \
    EXPECTED_URL="$expected_url" \
    EXPECTED_EVENT="$event" \
    EXPECTED_SEVERITY="$severity" \
    EXPECTED_COLOR="$expected_color" \
    python3 - <<'PY'
import json
import os
from pathlib import Path

capture = Path(os.environ["CAPTURE_DIR"])
url = (capture / "url").read_text(encoding="utf-8")
raw_payload = (capture / "payload.json").read_text(encoding="utf-8")
payload = json.loads(raw_payload)

def require(condition, message):
    if not condition:
        raise SystemExit(message)

require(url == os.environ["EXPECTED_URL"], "notification routed to the wrong URL")
require(payload["msg_type"] == "interactive", "unexpected Feishu message type")
require(
    payload["card"]["header"]["template"] == os.environ["EXPECTED_COLOR"],
    "unexpected card color",
)
content = payload["card"]["elements"][0]["text"]["content"]
require("项目：nm-docs" in content, "project identity is missing")
require(f"event={os.environ['EXPECTED_EVENT']}" in content, "event ID is missing")
require(
    f"severity={os.environ['EXPECTED_SEVERITY']}" in content,
    "event severity is missing",
)
require("branch=feature/test status=verified" in content, "status message is missing")
require(payload["timestamp"].isdigit(), "signed timestamp is missing")
require(bool(payload["sign"]), "signature is missing")
require("progress-test-secret" not in raw_payload, "progress secret leaked")
require("attention-test-secret" not in raw_payload, "attention secret leaked")
PY
}

run_success_case \
  progress \
  work_started \
  https://example.invalid/progress \
  blue
run_success_case \
  progress \
  stage_completed \
  https://example.invalid/progress \
  blue
run_success_case \
  progress \
  work_completed \
  https://example.invalid/progress \
  blue
run_success_case \
  attention \
  attention_required \
  https://example.invalid/attention \
  red
run_success_case \
  attention \
  blocked \
  https://example.invalid/attention \
  red
run_success_case \
  attention \
  validation_failed \
  https://example.invalid/attention \
  red
run_success_case \
  progress \
  notify_test \
  https://example.invalid/progress \
  blue
run_success_case \
  attention \
  notify_test \
  https://example.invalid/attention \
  red

if HOME="$TEST_HOME" PATH="$MOCK_BIN:$PATH" \
  "$ROOT/0d-scripts/notify-event.sh" \
  --event invalid_severity \
  --severity urgent \
  --message "must fail" \
  >"$TMP_ROOT/invalid.out" 2>"$TMP_ROOT/invalid.err"; then
  echo "ERROR: invalid severity unexpectedly succeeded" >&2
  exit 1
fi
grep -F -- "--severity must be progress|attention" "$TMP_ROOT/invalid.err" >/dev/null

if HOME="$TEST_HOME" PATH="$MOCK_BIN:$PATH" \
  "$ROOT/0d-scripts/notify-event.sh" \
  --event blocked \
  --severity progress \
  --message "must fail" \
  >"$TMP_ROOT/mismatch.out" 2>"$TMP_ROOT/mismatch.err"; then
  echo "ERROR: event/severity mismatch unexpectedly succeeded" >&2
  exit 1
fi
grep -F "event blocked requires severity=attention" "$TMP_ROOT/mismatch.err" >/dev/null

if HOME="$TEST_HOME" PATH="$MOCK_BIN:$PATH" \
  "$ROOT/0d-scripts/notify-event.sh" \
  --event misspelled_event \
  --severity progress \
  --message "must fail" \
  >"$TMP_ROOT/unknown.out" 2>"$TMP_ROOT/unknown.err"; then
  echo "ERROR: unknown event unexpectedly succeeded" >&2
  exit 1
fi
grep -F "unsupported repository event" "$TMP_ROOT/unknown.err" >/dev/null

chmod 644 "$CONFIG_FILE"
if HOME="$TEST_HOME" PATH="$MOCK_BIN:$PATH" \
  "$ROOT/0d-scripts/notify-event.sh" \
  --event work_started \
  --severity progress \
  --message "must fail" \
  >"$TMP_ROOT/unsafe.out" 2>"$TMP_ROOT/unsafe.err"; then
  echo "ERROR: unsafe config permissions unexpectedly succeeded" >&2
  exit 1
fi
grep -F "unsafe config permissions" "$TMP_ROOT/unsafe.err" >/dev/null
write_config

REJECTION_CAPTURE="$TMP_ROOT/capture-rejection"
mkdir -p "$REJECTION_CAPTURE"
if HOME="$TEST_HOME" \
  CAPTURE_DIR="$REJECTION_CAPTURE" \
  MOCK_RESPONSE='{"code":19001,"msg":"simulated rejection"}' \
  PATH="$MOCK_BIN:$PATH" \
  "$ROOT/0d-scripts/notify-event.sh" \
  --event blocked \
  --severity attention \
  --message "must fail" \
  >"$TMP_ROOT/rejected.out" 2>"$TMP_ROOT/rejected.err"; then
  echo "ERROR: rejected Feishu response unexpectedly succeeded" >&2
  exit 1
fi
if ! grep -F "simulated rejection" "$TMP_ROOT/rejected.err" >/dev/null; then
  echo "ERROR: Feishu rejection message was not preserved" >&2
  sed -n '1,5p' "$TMP_ROOT/rejected.err" >&2
  exit 1
fi

TRANSPORT_CAPTURE="$TMP_ROOT/capture-transport"
mkdir -p "$TRANSPORT_CAPTURE"
if HOME="$TEST_HOME" \
  CAPTURE_DIR="$TRANSPORT_CAPTURE" \
  MOCK_EXIT_CODE=28 \
  MOCK_ERROR='simulated timeout' \
  PATH="$MOCK_BIN:$PATH" \
  "$ROOT/0d-scripts/notify-event.sh" \
  --event blocked \
  --severity attention \
  --message "must fail" \
  >"$TMP_ROOT/transport.out" 2>"$TMP_ROOT/transport.err"; then
  echo "ERROR: curl transport failure unexpectedly succeeded" >&2
  exit 1
fi
grep -F "curl failed: simulated timeout" "$TMP_ROOT/transport.err" >/dev/null

echo "Repository notification checks passed."
