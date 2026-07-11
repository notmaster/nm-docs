---
name: nm-init-project-v3
description: Initialize, inspect, migrate, update, or validate a project with the NM V3.1 lightweight Goal workflow. Use when Codex needs to create a new V3 project, migrate V3 3.0 requirements and acceptance documents to an optional spec, create or stamp 0a-docs/spec.md, check installed V3 version or drift, synchronize managed workflow files without losing project-owned AGENTS.md rules, test configured dual-channel Feishu notifications, or install the V3 Skill.
---

# NM Init Project V3

Use the deterministic tool. Do not manually copy template files.

## Commands

Prefer a local `nm-docs` checkout:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py init --target /absolute/project --source-dir /path/to/nm-docs
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py status --target /absolute/project
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py check --target /absolute/project --source-dir /path/to/nm-docs
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py update --target /absolute/project --source-dir /path/to/nm-docs --dry-run
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py migrate --target /absolute/project --source-dir /path/to/nm-docs --dry-run
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py create-spec --target /absolute/project --source-dir /path/to/nm-docs --dry-run
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py finish --target /absolute/project --file 0b-goals/0a-plans/plan-p001-example.md
```

When the repository path is unknown, use:

```bash
python3 "$HOME/.agents/skills/nm-init-project-v3/scripts/run_nm_v3.py" <command> ...
```

Repository-source and installed copies run the same digest-verified bundled
tool. The wrapper fails closed when its versioned binding or bundle is missing,
unsupported, or changed. It never searches for or downloads another executable.

## New Project

1. Determine the target, project name, and package name.
2. For an empty non-Git target, run `init`. The tool creates a bootstrap task
   commit, makes clean `main` and `dev` refs at that commit, and ends on `dev`.
3. For a non-empty non-Git target, dry-run and use `--no-git-init`; do not absorb
   unrelated files into an automatic commit.
4. Run:

```bash
npm install
npm run workflow:check
npm run verify
```

Start small work with a standalone Goal. Create `0a-docs/spec.md` only when the
administrator requests it.

## Existing Project

Before any update or migration, require:

- the target is the Git root;
- the working tree is clean;
- `git fetch --prune origin dev` succeeds;
- local `dev` exactly equals `origin/dev`;
- the tool-created task branch starts at that exact remote SHA.

Always run `update --dry-run` or `migrate --dry-run` first. V3 3.0 migration
creates a candidate `0a-docs/spec.md`, preserves marked project-owned AGENTS
blocks, archives markerless legacy guidance for administrator review, and moves
old Requirements/Acceptance files into `.delete-pending/`.

After changing a spec version/body and its YAML `body_sha256`, run:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py spec-stamp --target /absolute/project
```

This records version/hash only; it does not record administrator acceptance.

After a standalone Goal is verified or a Plan reaches `awaiting_review`, use
`finish` for one idempotent `work_completed` attention handoff. The command
validates workflow state and records the delivery result in template state.

## Notification Test

Only run a live test after explicit administrator instruction:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py notify-test --target /absolute/project --severity progress
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py notify-test --target /absolute/project --severity attention
```

## References

- Read `references/v3-lifecycle.md` before migration or workflow explanation.
- Read `references/install.md` for Skill installation questions.
