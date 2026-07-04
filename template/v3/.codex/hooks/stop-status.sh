#!/usr/bin/env bash
set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG_FILE="${HOME}/.config/nm-docs/nm-notify-feishu.env"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Feishu notify config missing: $CONFIG_FILE"
fi

BRANCH="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"
STATUS="$(git -C "$ROOT" status --short 2>/dev/null || true)"

if [ "$BRANCH" = "main" ] && [ -n "$STATUS" ]; then
  echo "Warning: working tree has changes on main. Regular development should use a task branch from dev."
fi

GOAL_COUNT="$(find "$ROOT/0b-goals/0b-current" -maxdepth 1 -type f ! -name ".gitkeep" 2>/dev/null | wc -l | tr -d " ")"
if [ "${GOAL_COUNT:-0}" -gt 1 ]; then
  echo "Warning: multiple active Goal files found under 0b-goals/0b-current."
fi

if [ -n "$STATUS" ]; then
  echo "Workflow status: working tree has local changes. Report verification and acceptance status before stopping."
fi
