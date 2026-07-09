#!/usr/bin/env bash
set -euo pipefail

# Stable nm-docs repository entry point. Reuse only the V5 notification
# adapter; this does not opt the repository into the V5 workflow runtime.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMPLEMENTATION="$ROOT/template/v5/0d-scripts/notify-event.sh"
ARGS=("$@")
EVENT=""
SEVERITY=""

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --event)
      [ "$#" -ge 2 ] || fail "--event requires a value"
      EVENT="$2"
      shift 2
      ;;
    --severity)
      [ "$#" -ge 2 ] || fail "--severity requires a value"
      SEVERITY="$2"
      shift 2
      ;;
    --title|--message|--project)
      [ "$#" -ge 2 ] || fail "$1 requires a value"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

[ -n "$EVENT" ] || fail "--event is required"
[ -n "$SEVERITY" ] || fail "--severity is required"

case "$SEVERITY" in
  progress|attention) ;;
  *) fail "--severity must be progress|attention" ;;
esac

case "$EVENT" in
  work_started|stage_completed|work_completed)
    EXPECTED_SEVERITY="progress"
    ;;
  attention_required|blocked|validation_failed)
    EXPECTED_SEVERITY="attention"
    ;;
  notify_test)
    EXPECTED_SEVERITY="$SEVERITY"
    ;;
  *)
    fail "unsupported repository event: $EVENT"
    ;;
esac

if [ "$SEVERITY" != "$EXPECTED_SEVERITY" ]; then
  fail "repository event $EVENT requires severity=$EXPECTED_SEVERITY"
fi

if [ ! -x "$IMPLEMENTATION" ]; then
  fail "V5 notification event adapter is missing or not executable: $IMPLEMENTATION"
fi

cd "$ROOT"
exec "$IMPLEMENTATION" "${ARGS[@]}"
