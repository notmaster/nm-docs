#!/usr/bin/env bash
set -euo pipefail

# Emit a V5 workflow event to configured channels (Feishu first).
# Usage:
#   ./0d-scripts/notify-event.sh --event phase_completed --severity progress --message "..."
#   ./0d-scripts/notify-event.sh --event need_review --severity attention --title "..." --message "..."

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
EVENT=""
SEVERITY="progress"
TITLE=""
MESSAGE=""
PROJECT=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --event)
      EVENT="${2:-}"
      shift 2
      ;;
    --severity)
      SEVERITY="${2:-}"
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
      PROJECT="${2:-}"
      shift 2
      ;;
    *)
      MESSAGE="${MESSAGE}${MESSAGE:+ }$1"
      shift
      ;;
  esac
done

if [ -z "$EVENT" ]; then
  echo "ERROR: --event is required" >&2
  exit 1
fi

case "$SEVERITY" in
  progress|attention) ;;
  *)
    echo "ERROR: --severity must be progress|attention" >&2
    exit 1
    ;;
esac

if [ -z "$TITLE" ]; then
  TITLE="[$SEVERITY] $EVENT"
fi

LEVEL="info"
if [ "$SEVERITY" = "attention" ]; then
  LEVEL="error"
fi

export NM_NOTIFY_EVENT="$EVENT"
export NM_NOTIFY_SEVERITY="$SEVERITY"

# Route progress/attention to split Feishu webhooks when configured.
ARGS=(
  --severity "$SEVERITY"
  --level "$LEVEL"
  --title "$TITLE"
  --message "event=$EVENT severity=$SEVERITY ${MESSAGE}"
)
if [ -n "$PROJECT" ]; then
  ARGS+=(--project "$PROJECT")
fi

exec "$ROOT/0d-scripts/notify-admin.sh" "${ARGS[@]}"
