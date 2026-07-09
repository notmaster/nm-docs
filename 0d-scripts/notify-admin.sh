#!/usr/bin/env bash
set -euo pipefail

# Compatibility entry point required by the reused V5 event adapter.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMPLEMENTATION="$ROOT/template/v5/0d-scripts/nm-notify-feishu.sh"

if [ ! -x "$IMPLEMENTATION" ]; then
  echo "ERROR: V5 Feishu notification adapter is missing or not executable: $IMPLEMENTATION" >&2
  exit 1
fi

cd "$ROOT"
exec "$IMPLEMENTATION" "$@"
