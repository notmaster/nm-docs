#!/usr/bin/env bash
set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
BRANCH="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"
STATUS="$(git -C "$ROOT" status --short 2>/dev/null || true)"

case "$BRANCH" in
  main|master|dev)
    if [ -n "$STATUS" ]; then
      echo "ERROR: working tree has modifications on protected branch $BRANCH. Stop and ask the administrator to preserve or relocate them safely."
    fi
    ;;
esac

GOAL_COUNT="$(find "$ROOT/0b-goals/0b-current" -maxdepth 1 -type f ! -name ".gitkeep" 2>/dev/null | wc -l | tr -d " ")"
if [ "${GOAL_COUNT:-0}" -gt 1 ]; then
  echo "ERROR: multiple active Goal files exist under 0b-goals/0b-current."
fi

if [ -n "$STATUS" ]; then
  echo "Workflow status: local changes remain. Report Goal verification, review, authorization, and notification status before stopping."
fi
