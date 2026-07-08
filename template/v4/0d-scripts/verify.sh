#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

echo "==> Running local verification"
echo "Project profile: 0c-workflow/project-profile.yml"

if [ -x "0d-scripts/check-workflow.sh" ]; then
  echo "==> Checking workflow structure"
  bash 0d-scripts/check-workflow.sh
fi

run_npm_script_if_present() {
  local script_name="$1"

  if [ ! -f package.json ]; then
    return 0
  fi

  node -e "const p=require('./package.json'); process.exit(p.scripts && p.scripts['$script_name'] ? 0 : 1)" >/dev/null 2>&1 || return 0

  echo "==> npm run $script_name"
  npm run "$script_name"
}

if [ -f package.json ]; then
  run_npm_script_if_present "lm"
  run_npm_script_if_present "lint"
  run_npm_script_if_present "typecheck"
  run_npm_script_if_present "test"
  run_npm_script_if_present "build"
else
  echo "No package.json found. Add project-specific checks to 0d-scripts/verify.sh."
fi

echo "==> Verification finished"
