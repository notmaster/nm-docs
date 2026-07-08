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

if [ ! -f "$ROOT/0b-goals/ROADMAP.md" ]; then
  echo "Warning: 0b-goals/ROADMAP.md is missing. Generate it from the confirmed Spec before implementation."
fi

if [ -n "$STATUS" ]; then
  echo "Workflow status: working tree has local changes. Update the ROADMAP phase status and report verification and acceptance state before stopping."
fi
