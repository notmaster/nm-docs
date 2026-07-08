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

echo "==> Checking V4 workflow structure"

require_file "AGENTS.md"
require_file "AGENTS.zh-CN.md"
require_file "CLAUDE.md"
require_file "GROK.md"
require_file "PROJECT_STRUCTURE.md"
require_file "README.md"
require_file "0a-docs/DECISIONS.md"
require_file "0b-goals/ROADMAP.md"
require_file "0c-workflow/WORKFLOW_V4.md"
require_file "0c-workflow/SPEC_TEMPLATE.md"
require_file "0c-workflow/AGENT_RECIPES.md"
require_file "0c-workflow/BRANCHING.md"
require_file "0c-workflow/VERIFY.md"
require_file "0c-workflow/RELEASE_CHECKLIST.md"

require_dir "0a-docs/0a-spec"
require_dir "0a-docs/0b-design/prototype"
require_dir ".delete-pending"

for script in 0d-scripts/verify.sh 0d-scripts/check-workflow.sh 0d-scripts/notify-admin.sh 0d-scripts/nm-notify-feishu.sh 0d-scripts/run-goals.py; do
  if [ -x "$script" ]; then
    pass "$script is executable"
  else
    fail "$script is not executable"
  fi
done

spec_pattern='^SPEC-[A-Za-z0-9][A-Za-z0-9._-]*-V[0-9]+\.md$'

while IFS= read -r file; do
  [ -z "$file" ] && continue
  name="$(basename "$file")"
  if [[ "$name" =~ $spec_pattern ]]; then
    pass "$file matches Spec naming"
  else
    fail "$file does not match Spec naming (SPEC-<slug>-V<n>.md)"
  fi
done < <(find 0a-docs/0a-spec -maxdepth 1 -type f ! -name ".gitkeep" 2>/dev/null)

if [ -f "0b-goals/ROADMAP.md" ]; then
  if grep -Eq '^execution_mode: (staged|auto)$' 0b-goals/ROADMAP.md; then
    pass "ROADMAP declares a valid execution_mode"
  else
    fail "ROADMAP is missing 'execution_mode: staged|auto' in its frontmatter"
  fi

  spec_value="$(grep -m1 -E '^spec:' 0b-goals/ROADMAP.md | sed -E 's/^spec:[[:space:]]*//' | tr -d '"' | tr -d "'" || true)"
  if [ -z "$spec_value" ]; then
    pass "ROADMAP is not initialized yet (spec is empty)"
  elif [ -f "$spec_value" ]; then
    pass "ROADMAP spec reference exists: $spec_value"
  else
    fail "ROADMAP references a missing Spec file: $spec_value"
  fi
fi

if command -v python3 >/dev/null 2>&1; then
  pass "python3 is available for 0d-scripts/run-goals.py"
else
  echo "WARN: python3 is not available; auto mode runner cannot be used"
fi

if [ "$failures" -gt 0 ]; then
  echo "Workflow check failed with $failures issue(s)."
  exit 1
fi

echo "Workflow check passed."
