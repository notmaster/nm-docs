---
name: nm-init-project-v4
description: Initialize, update, check, or install the NotMaster NM V4 spec-driven workflow for a project. Use when an agent needs to create a new project from template/v4, migrate an existing Git project (including NM V3 projects) to V4 rules, synchronize V4 workflow files, install the skill into ~/.agents/skills or another skills directory, summarize V4 workflow changes, or preserve project-specific guidance while adopting NM V4.
---

# NM Init Project V4

Use the deterministic NM V4 tool. Do not manually copy template files.

## Core Commands

Prefer the repository tool when `nm-docs` is available:

```bash
python3 /path/to/nm-docs/tools/nm-v4/nm_v4.py init --target /absolute/project --source-dir /path/to/nm-docs
python3 /path/to/nm-docs/tools/nm-v4/nm_v4.py update --target /absolute/project --source-dir /path/to/nm-docs --dry-run
python3 /path/to/nm-docs/tools/nm-v4/nm_v4.py check --target /absolute/project --source-dir /path/to/nm-docs
```

When the repo path is unknown, use the skill wrapper:

```bash
python3 "$HOME/.agents/skills/nm-init-project-v4/scripts/run_nm_v4.py" init --target /absolute/project
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

1. Tell the administrator to start with the Spec:
   - Draft it with `0a-docs/0c-prompts/write-spec.md` (optionally review with `review-spec.md`).
   - Save the confirmed copy as `0a-docs/0a-spec/SPEC-<slug>-V<n>.md` with `status: confirmed`.
   - Then let an agent generate `0b-goals/ROADMAP.md` per `0c-workflow/WORKFLOW_V4.md`.

## Existing Project Update

Before writing:

1. Confirm the target is a Git repository root.
1. Check `git status --short`.
1. If the working tree is dirty, stop and ask the user to commit or stash.
1. Run `update --dry-run`.
1. Run `update` only after the dry-run output is acceptable.

`update` creates a branch named `chore/sync-nm-workflow-v4-YYYYMMDD` by default. It overwrites only `managed` framework files (AGENTS rules, pointer files, workflow docs, check and runner scripts); `create-only` files such as `README.md`, `ROADMAP.md`, `DECISIONS.md`, and `verify.sh` are never overwritten. Git diff on the branch is the review mechanism.

When updating an NM V3 project, the tool additionally:

- Moves superseded V3 framework files (`WORKFLOW_V3.md`, `PLAN_TEMPLATE.md`, `GOAL_TEMPLATE.md`, and the V3 prompts) to `.delete-pending/v3-superseded/` for administrator confirmation.
- Keeps `REQUIREMENTS.md`, `ACCEPTANCE.md`, and `DESIGN.md` in place and reports them as Spec input material.

After update, work with the administrator to:

- Synthesize a V4 Spec from the old requirement documents, then mark it `status: confirmed`.
- Move durable project-specific facts into `0a-docs/DECISIONS.md`, `0c-workflow/project-profile.yml`, `PROJECT_STRUCTURE.md`, or the Spec itself.
- Keep V4 framework rules in `AGENTS.md`; do not bloat it with project backlog.
- Existing `0b-goals/0a-plans/`, `0b-goals/0b-current/`, and `0b-goals/0c-archive/` content is project history; leave it in place.

## Installing This Skill

Use:

```bash
python3 /path/to/nm-docs/tools/nm-v4/nm_v4.py install-skill --target-dir "$HOME/.agents/skills"
```

Default install target is `~/.agents/skills` because it is shared by most local agent tools. Use `--target-dir` for another skills directory.

## References

- Read `references/v4-lifecycle.md` before doing a migration or explaining the workflow.
- Read `references/install.md` when the user asks how to install the skill.
