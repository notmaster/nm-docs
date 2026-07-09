---
name: nm-init-project-v5
description: Initialize, update, check, status, notify-test, or install the NotMaster NM V5 hybrid workflow (disk state machine, runner + orchestrator + workers, staged/auto). Use when an agent needs to create a project from template/v5, migrate or sync V5 workflow files, install the skill, or operate nm_v5.py.
---

# NM Init Project V5

Use the deterministic NM V5 tool. Do not manually copy template files.

## Core Commands

Prefer the repository tool when `nm-docs` is available:

```bash
python3 /path/to/nm-docs/tools/nm-v5/nm_v5.py init --target /absolute/project --source-dir /path/to/nm-docs
python3 /path/to/nm-docs/tools/nm-v5/nm_v5.py update --target /absolute/project --source-dir /path/to/nm-docs --dry-run
python3 /path/to/nm-docs/tools/nm-v5/nm_v5.py check --target /absolute/project --source-dir /path/to/nm-docs
python3 /path/to/nm-docs/tools/nm-v5/nm_v5.py status --target /absolute/project
python3 /path/to/nm-docs/tools/nm-v5/nm_v5.py notify-test --target /absolute/project
```

When the repo path is unknown, use the skill wrapper:

```bash
python3 "$HOME/.agents/skills/nm-init-project-v5/scripts/run_nm_v5.py" init --target /absolute/project
```

The wrapper searches `NM_DOCS_DIR`, common local checkout paths, then downloads the tool from GitHub raw.

## New Project

1. Determine target directory, project name, package name.
2. Dry-run if the directory is non-empty.
3. Run `init`.
4. In the target project:

```bash
npm install
npm run workflow:check
npm run verify
```

1. Tell the administrator:
   - Confirm Spec under `0a-docs/0a-spec/` with `status: confirmed` (English Spec body).
   - Bootstrap `0b-runtime/INDEX.yaml` + task cards.
   - If mode is `unspecified`, choose **staged** or **auto**.
   - Design resolution: `0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md`.

## Existing Project Update

1. Confirm Git root; clean working tree (or ask user).
2. `update --dry-run`, then `update` after approval.
3. Default branch: `chore/sync-nm-workflow-v5-YYYYMMDD`.
4. Only `managed` files are overwritten; `create-only` project content is preserved.

## Installing This Skill

```bash
python3 /path/to/nm-docs/tools/nm-v5/nm_v5.py install-skill --target-dir "$HOME/.agents/skills"
```

### Open ecosystem install (skills CLI)

When publishing/consuming via the open skills tool:

```bash
npx skills add notmaster/nm-docs --skill nm-init-project-v5
```

(Exact flags depend on skills CLI version; prefer the repo install-skill command if `npx skills` layout differs.)

## References

- `references/v5-lifecycle.md`
- `references/install.md`
