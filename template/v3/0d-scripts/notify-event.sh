#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVENT=""
SEVERITY=""
TITLE=""
MESSAGE=""
PROJECT=""

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --event|--severity|--title|--message|--project)
      [ "$#" -ge 2 ] || fail "$1 requires a value"
      case "$1" in
        --event) EVENT="$2" ;;
        --severity) SEVERITY="$2" ;;
        --title) TITLE="$2" ;;
        --message) MESSAGE="$2" ;;
        --project) PROJECT="$2" ;;
      esac
      shift 2
      ;;
    *) fail "unsupported argument: $1" ;;
  esac
done

[ -n "$EVENT" ] || fail "--event is required"
[ -n "$SEVERITY" ] || fail "--severity is required"

case "$EVENT" in
  work_started|goal_integrated) EXPECTED="progress" ;;
  work_completed|decision_required|needs_replan|blocked|validation_failed|git_conflict) EXPECTED="attention" ;;
  notify_test) EXPECTED="$SEVERITY" ;;
  *) fail "unsupported event: $EVENT" ;;
esac

case "$SEVERITY" in progress|attention) ;; *) fail "--severity must be progress|attention" ;; esac
[ "$SEVERITY" = "$EXPECTED" ] || fail "event $EVENT requires severity=$EXPECTED"

[ -n "$TITLE" ] || TITLE="[$SEVERITY] $EVENT"
case "$EVENT" in
  work_completed) LEVEL="completed" ;;
  decision_required|needs_replan) LEVEL="action_required" ;;
  blocked|validation_failed|git_conflict) LEVEL="error" ;;
  *)
    if [ "$SEVERITY" = "attention" ]; then
      LEVEL="action_required"
    else
      LEVEL="info"
    fi
    ;;
esac

ARGS=(--severity "$SEVERITY" --level "$LEVEL" --title "$TITLE" --message "event=$EVENT ${MESSAGE}")
[ -z "$PROJECT" ] || ARGS+=(--project "$PROJECT")
exec "$ROOT/0d-scripts/notify-admin.sh" "${ARGS[@]}"
