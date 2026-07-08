# Installation

## Install The V4 Skill

Default target:

```text
~/.agents/skills
```

Install from this repository:

```bash
bash tools/nm-v4/install-skill.sh --target-dir "$HOME/.agents/skills"
```

Install for a Codex-specific skill directory:

```bash
bash tools/nm-v4/install-skill.sh --target-dir "$HOME/.codex/skills"
```

After installation, start a new agent thread and invoke:

```text
Use $nm-init-project-v4 to initialize or update this project.
```

## Use The Tool Without A Skill

Initialize a new project:

```bash
python3 tools/nm-v4/nm_v4.py init --target /absolute/project --source-dir .
```

Update an existing Git project:

```bash
python3 tools/nm-v4/nm_v4.py update --target /absolute/project --source-dir . --dry-run
python3 tools/nm-v4/nm_v4.py update --target /absolute/project --source-dir .
```

Check a project:

```bash
python3 tools/nm-v4/nm_v4.py check --target /absolute/project --source-dir .
```

## Update Safety

`update` requires:

- target is a Git repository root;
- working tree is clean unless `--allow-dirty` is used;
- a new branch can be created.

The default update branch is:

```text
chore/sync-nm-workflow-v4-YYYYMMDD
```

Only `managed` framework files are overwritten on that branch; `create-only`
files such as `README.md`, `0b-goals/ROADMAP.md`, and `0a-docs/DECISIONS.md`
are never overwritten. The administrator inspects changes with Git.

When updating an NM V3 project, superseded V3 framework files are moved to
`.delete-pending/v3-superseded/` and old requirement documents stay in place
as Spec input material.

## V3 Equivalents

Existing V3 projects that are not migrating yet can keep using:

```bash
bash tools/nm-v3/install-skill.sh --target-dir "$HOME/.agents/skills"
python3 tools/nm-v3/nm_v3.py init --target /absolute/project --source-dir .
python3 tools/nm-v3/nm_v3.py update --target /absolute/project --source-dir . --dry-run
```
