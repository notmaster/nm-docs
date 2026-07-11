#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILLS_VERSION="1.5.16"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT

export HOME="$TEMP_ROOT/home"
export npm_config_cache="$TEMP_ROOT/npm-cache"
unset NM_DOCS_DIR
mkdir -p "$HOME" "$TEMP_ROOT/work"
python3 "$REPO_ROOT/tools/nm-v3/nm_v3.py" init \
  --target "$TEMP_ROOT/project" \
  --source-dir "$REPO_ROOT" \
  --no-git-init

cd "$TEMP_ROOT/work"
npx --yes "skills@$SKILLS_VERSION" add \
  "$REPO_ROOT/skills/nm-init-project-v3" \
  --global \
  --agent codex \
  --yes

INSTALLED="$HOME/.agents/skills/nm-init-project-v3"
CODEX_INSTALL="$HOME/.codex/skills/nm-init-project-v3"
test -f "$INSTALLED/.nm-v3-binding.json"
test -f "$INSTALLED/scripts/vendor/nm_v3.py"
if [[ -e "$CODEX_INSTALL" || -L "$CODEX_INSTALL" ]]; then
  test -L "$CODEX_INSTALL"
fi
python3 "$INSTALLED/scripts/run_nm_v3.py" status --target "$TEMP_ROOT/project"

LIST_OUTPUT="$(npx --yes "skills@$SKILLS_VERSION" list --global --agent codex)"
case "$LIST_OUTPUT" in
  *nm-init-project-v3*) ;;
  *)
    echo "installed V3 Skill was not listed by vercel-labs/skills" >&2
    exit 1
    ;;
esac

npx --yes "skills@$SKILLS_VERSION" remove \
  nm-init-project-v3 \
  --global \
  --agent codex \
  --yes
test ! -e "$INSTALLED"

# The published branch is used only to exercise GitHub source-lock/update
# behavior in the isolated HOME. The remote artifact is not executed; actual
# installation documentation requires an immutable release tag.
npx --yes "skills@$SKILLS_VERSION" add \
  https://github.com/notmaster/nm-docs/tree/main/skills/nm-init-project-v3 \
  --global \
  --agent codex \
  --yes
test -f "$HOME/.agents/.skill-lock.json"
UPDATE_OUTPUT="$(npx --yes "skills@$SKILLS_VERSION" update \
  nm-init-project-v3 --global --yes)"
case "$UPDATE_OUTPUT" in
  *"Checking skills from source: notmaster/nm-docs"*) ;;
  *)
    echo "GitHub-installed V3 Skill was not tracked for updates" >&2
    exit 1
    ;;
esac
npx --yes "skills@$SKILLS_VERSION" remove \
  nm-init-project-v3 \
  --global \
  --agent codex \
  --yes

echo "vercel-labs/skills $SKILLS_VERSION V3 compatibility passed."
