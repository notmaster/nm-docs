---
name: nm-init-project-v3
description: Initialize, update, check, or install the NotMaster NM V3 goal-driven workflow for a project. Use when Codex needs to create a new project from template/v3, migrate an existing Git project to V3 rules, synchronize V3 workflow files, install the skill into ~/.agents/skills or another skills directory, summarize V3 workflow changes, or preserve project-specific guidance while adopting NM V3.
---

# NM Init Project V3

Use the deterministic NM V3 tool. Do not manually copy template files.

## Core Commands

Prefer the repository tool when `nm-docs` is available:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py init --target /absolute/project --source-dir /path/to/nm-docs
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py update --target /absolute/project --source-dir /path/to/nm-docs --dry-run
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py check --target /absolute/project --source-dir /path/to/nm-docs
```

When the repo path is unknown, use the skill wrapper:

```bash
python3 "$HOME/.agents/skills/nm-init-project-v3/scripts/run_nm_v3.py" init --target /absolute/project
```

The wrapper searches `NM_DOCS_DIR`, common local checkout paths, then downloads the current tool from GitHub raw.

## New Project

1. Determine the target directory, project name, and package name.
1. Run a dry run first when the directory exists and is not empty.
1. Run `init`.
1. In the target project, run:

```bash
npm install
npm run workflow:check
npm run verify
```

1. Tell the administrator to start with:
   - `0a-docs/0a-product/REQUIREMENTS.md`
   - `0a-docs/0a-product/ACCEPTANCE.md`
   - `0a-docs/0b-design/DESIGN.md`

## Existing Project Update

Before writing:

1. Confirm the target is a Git repository root.
1. Check `git status --short`.
1. If the working tree is dirty, stop and ask the user to commit or stash.
1. Run `update --dry-run`.
1. Run `update` only after the dry-run output is acceptable.

`update` creates a branch named `chore/sync-nm-workflow-v3-YYYYMMDD` by default, then syncs V3 files. Existing template paths are overwritten on that branch so the administrator can inspect diffs with Git.

After update, inspect old project-specific material:

- Existing `AGENTS.md`, `CLAUDE.md`, README, workflow docs, and project structure.
- Move durable project-specific facts into `0a-docs/DECISIONS.md`, `0c-workflow/project-profile.yml`, `PROJECT_STRUCTURE.md`, or `REQUIREMENTS.md`.
- Keep V3 framework rules in `AGENTS.md`; do not bloat it with project backlog.

## Installing This Skill

Use:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py install-skill --target-dir "$HOME/.agents/skills"
```

Default install target is `~/.agents/skills` because it is shared by most local agent tools. Use `--target-dir` for another skills directory.

## References

- Read `references/v3-lifecycle.md` before doing a migration or explaining the workflow.
- Read `references/install.md` when the user asks how to install the skill.
