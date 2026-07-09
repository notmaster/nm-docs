#!/usr/bin/env bash
set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG_FILE="${HOME}/.config/nm-docs/nm-notify-feishu.env"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Feishu notify config missing: $CONFIG_FILE"
fi

BRANCH="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"
STATUS="$(git -C "$ROOT" status --short 2>/dev/null || true)"

if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  if [ -n "$STATUS" ]; then
    echo "Warning: working tree has changes on $BRANCH. Day-to-day work should use a branch from dev."
  fi
fi

if [ "$BRANCH" = "dev" ] && [ -n "$STATUS" ]; then
  echo "Warning: direct changes on dev. Prefer a task branch from dev for implementation."
fi

if [ ! -f "$ROOT/0b-runtime/INDEX.yaml" ]; then
  echo "Warning: 0b-runtime/INDEX.yaml is missing. Bootstrap runtime from the confirmed Spec before implementation."
fi

if [ -n "$STATUS" ]; then
  echo "Workflow status: working tree has local changes. Update INDEX/task cards, verification, and notify events before stopping."
fi
