#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

echo "==> NM V5 verify"

if [ -x "./0d-scripts/check-workflow.sh" ]; then
  ./0d-scripts/check-workflow.sh
else
  echo "ERROR: check-workflow.sh missing or not executable" >&2
  exit 1
fi

if [ -f "package.json" ] && command -v npm >/dev/null 2>&1; then
  if node -e "const p=require('./package.json'); process.exit(p.scripts && p.scripts.lm ? 0 : 1)" 2>/dev/null; then
    echo "==> npm run lm"
    npm run lm
  fi
fi

echo "==> verify passed (extend this script with project tests)"
