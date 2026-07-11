#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> NM V3 workflow check"
node 0d-scripts/check-workflow.mjs

run_npm_script_if_present() {
  local script_name="$1"
  node -e "const p=require('./package.json'); process.exit(p.scripts && p.scripts['$script_name'] ? 0 : 1)" >/dev/null 2>&1 || return 0
  echo "==> npm run $script_name"
  npm run "$script_name"
}

if [ -f package.json ]; then
  for script_name in lm lint typecheck test build; do
    run_npm_script_if_present "$script_name"
  done
else
  echo "WARN: package.json is absent; add complete project checks to 0d-scripts/verify.sh"
fi

echo "Full verification passed."
