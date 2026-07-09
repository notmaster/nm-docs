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

echo "==> Checking V5 workflow structure"

require_file "AGENTS.md"
require_file "AGENTS.zh-CN.md"
require_file "CLAUDE.md"
require_file "GROK.md"
require_file "PROJECT_STRUCTURE.md"
require_file "README.md"
require_file "0a-docs/DECISIONS.md"
require_file "0b-runtime/INDEX.yaml"
require_file "0b-runtime/issues-ledger.md"
require_file "0c-workflow/WORKFLOW_V5.md"
require_file "0c-workflow/WORKFLOW_V5.zh-CN.md"
require_file "0c-workflow/SPEC_TEMPLATE.md"
require_file "0c-workflow/TASK_CARD.md"
require_file "0c-workflow/AGENT_RECIPES.md"
require_file "0c-workflow/BRANCHING.md"
require_file "0c-workflow/VERIFY.md"
require_file "0c-workflow/NOTIFY_EVENTS.md"
require_file "0c-workflow/CONTEXT_PACKING.md"
require_file "0c-workflow/RELEASE_CHECKLIST.md"
require_file "0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md"
require_file "0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.zh-CN.md"

require_dir "0a-docs/0a-spec"
require_dir "0a-docs/0b-design/prototype"
require_dir "0b-runtime/tasks"
require_dir ".delete-pending"

for script in \
  0d-scripts/verify.sh \
  0d-scripts/check-workflow.sh \
  0d-scripts/notify-admin.sh \
  0d-scripts/notify-event.sh \
  0d-scripts/nm-notify-feishu.sh \
  0d-scripts/run-workflow.py; do
  if [ -x "$script" ]; then
    pass "$script is executable"
  else
    fail "$script is not executable"
  fi
done

# EN/ZH pair warnings for core agent docs
for en in AGENTS.md 0c-workflow/WORKFLOW_V5.md 0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md; do
  case "$en" in
    AGENTS.md) zh="AGENTS.zh-CN.md" ;;
    0c-workflow/WORKFLOW_V5.md) zh="0c-workflow/WORKFLOW_V5.zh-CN.md" ;;
    *) zh="${en%.md}.zh-CN.md" ;;
  esac
  if [ -f "$en" ] && [ -f "$zh" ]; then
    pass "locale pair ok: $en + $zh"
  else
    fail "missing locale pair: $en / $zh"
  fi
done

spec_pattern='^SPEC-[A-Za-z0-9][A-Za-z0-9._-]*-V[0-9]+\.md$'
while IFS= read -r file; do
  [ -z "$file" ] && continue
  name="$(basename "$file")"
  # allow zh-CN mirrors
  if [[ "$name" == *.zh-CN.md ]]; then
    pass "$file is Spec admin mirror"
    continue
  fi
  if [[ "$name" =~ $spec_pattern ]]; then
    pass "$file matches Spec naming"
  else
    fail "$file does not match Spec naming (SPEC-<slug>-V<n>.md)"
  fi
done < <(find 0a-docs/0a-spec -maxdepth 1 -type f ! -name ".gitkeep" 2>/dev/null)

if [ -f "0b-runtime/INDEX.yaml" ]; then
  if grep -Eq '^mode:[[:space:]]*(unspecified|staged|auto)[[:space:]]*$' 0b-runtime/INDEX.yaml; then
    pass "INDEX declares a valid mode"
  else
    fail "INDEX mode must be unspecified|staged|auto"
  fi
  if grep -Eq '^repair_max_attempts:[[:space:]]*10[[:space:]]*$' 0b-runtime/INDEX.yaml \
    || grep -Eq '^repair_max_attempts:[[:space:]]*[0-9]+[[:space:]]*$' 0b-runtime/INDEX.yaml; then
    pass "INDEX declares repair_max_attempts"
  else
    fail "INDEX missing repair_max_attempts"
  fi
fi

if command -v python3 >/dev/null 2>&1; then
  pass "python3 is available for 0d-scripts/run-workflow.py"
else
  echo "WARN: python3 is not available; auto runner cannot be used"
fi

if [ "$failures" -gt 0 ]; then
  echo "==> check-workflow failed: $failures issue(s)"
  exit 1
fi

echo "==> check-workflow passed"
