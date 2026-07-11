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

# Severity selects the delivery channel. Event semantics select the card level;
# an attention notification is not necessarily an error.
case "$EVENT" in
  work_completed|workflow_completed)
    LEVEL="completed"
    ;;
  attention_required|mode_selection_required|phase_awaiting_acceptance|need_review)
    LEVEL="action_required"
    ;;
  task_skipped)
    LEVEL="warning"
    ;;
  blocked|validation_failed|mode_switch_conflict|repair_exhausted|git_conflict)
    LEVEL="error"
    ;;
  *)
    if [ "$SEVERITY" = "attention" ]; then
      LEVEL="action_required"
    else
      LEVEL="info"
    fi
    ;;
esac

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
