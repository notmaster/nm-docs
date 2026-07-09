#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

exec "$ROOT/0d-scripts/nm-notify-feishu.sh" "$@"
