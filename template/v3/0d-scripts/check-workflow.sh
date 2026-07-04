#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

failures=0

fail() {
  echo "FAIL: $*"
  failures=$((failures + 1))
}

pass() {
  echo "OK: $*"
}

require_file() {
  local path="$1"
  if [ -f "$path" ]; then
    pass "$path exists"
  else
    fail "$path is missing"
  fi
}

require_dir() {
  local path="$1"
  if [ -d "$path" ]; then
    pass "$path exists"
  else
    fail "$path is missing"
  fi
}

echo "==> Checking V3 workflow structure"

require_file "AGENTS.md"
require_file "AGENTS.zh-CN.md"
require_file "PROJECT_STRUCTURE.md"
require_file "README.md"
require_file "0a-docs/DECISIONS.md"
require_file "0a-docs/0a-product/REQUIREMENTS.md"
require_file "0a-docs/0a-product/ACCEPTANCE.md"
require_file "0a-docs/0b-design/DESIGN.md"
require_file "0c-workflow/WORKFLOW_V3.md"
require_file "0c-workflow/BRANCHING.md"
require_file "0c-workflow/VERIFY.md"
require_file "0c-workflow/PLAN_TEMPLATE.md"
require_file "0c-workflow/GOAL_TEMPLATE.md"
require_file "0c-workflow/RELEASE_CHECKLIST.md"

require_dir "0b-goals/0a-plans"
require_dir "0b-goals/0b-current"
require_dir "0b-goals/0c-archive"

for script in 0d-scripts/verify.sh 0d-scripts/check-workflow.sh 0d-scripts/notify-admin.sh 0d-scripts/nm-notify-feishu.sh; do
  if [ -x "$script" ]; then
    pass "$script is executable"
  else
    fail "$script is not executable"
  fi
done

active_goal_count="$(find 0b-goals/0b-current -maxdepth 1 -type f ! -name ".gitkeep" 2>/dev/null | wc -l | tr -d " ")"
if [ "${active_goal_count:-0}" -le 1 ]; then
  pass "0b-goals/0b-current has at most one active Goal"
else
  fail "0b-goals/0b-current has multiple active Goal files"
fi

plan_pattern='^Plan-[0-9]{8}-PlanID[0-9]{3}-[A-Za-z0-9][A-Za-z0-9._-]*\.md$'
goal_pattern='^Goal-[0-9]{8}-PlanID[0-9]{3}-GoalID[0-9]{3}-[A-Za-z0-9][A-Za-z0-9._-]*\.md$'

while IFS= read -r file; do
  [ -z "$file" ] && continue
  name="$(basename "$file")"
  if [[ "$name" =~ $plan_pattern ]]; then
    pass "$file matches Plan naming"
  else
    fail "$file does not match Plan naming"
  fi
done < <(find 0b-goals/0a-plans -maxdepth 1 -type f ! -name ".gitkeep" 2>/dev/null)

while IFS= read -r file; do
  [ -z "$file" ] && continue
  name="$(basename "$file")"
  if [[ "$name" =~ $goal_pattern ]]; then
    pass "$file matches Goal naming"
  else
    fail "$file does not match Goal naming"
  fi
done < <(find 0b-goals/0b-current 0b-goals/0c-archive -maxdepth 1 -type f ! -name ".gitkeep" 2>/dev/null)

if command -v npx >/dev/null 2>&1; then
  echo "==> Checking DESIGN.md"
  npx @google/design.md lint 0a-docs/0b-design/DESIGN.md >/tmp/nm-design-lint.log 2>&1 || {
    cat /tmp/nm-design-lint.log
    fail "DESIGN.md failed design.md lint"
  }
  if [ "${failures:-0}" -eq 0 ]; then
    pass "DESIGN.md passed design.md lint"
  fi
else
  echo "WARN: npx is not available; skipped DESIGN.md lint"
fi

if [ "$failures" -gt 0 ]; then
  echo "Workflow check failed with $failures issue(s)."
  exit 1
fi

echo "Workflow check passed."
