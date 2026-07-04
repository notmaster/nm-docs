# Installation

## Install The V3 Skill

Default target:

```text
~/.agents/skills
```

Install from this repository:

```bash
bash tools/nm-v3/install-skill.sh --target-dir "$HOME/.agents/skills"
```

Install for a Codex-specific skill directory:

```bash
bash tools/nm-v3/install-skill.sh --target-dir "$HOME/.codex/skills"
```

After installation, start a new agent thread and invoke:

```text
Use $nm-init-project-v3 to initialize or update this project.
```

## Use The Tool Without A Skill

Initialize a new project:

```bash
python3 tools/nm-v3/nm_v3.py init --target /absolute/project --source-dir .
```

Update an existing Git project:

```bash
python3 tools/nm-v3/nm_v3.py update --target /absolute/project --source-dir . --dry-run
python3 tools/nm-v3/nm_v3.py update --target /absolute/project --source-dir .
```

Check a project:

```bash
python3 tools/nm-v3/nm_v3.py check --target /absolute/project --source-dir .
```

## Update Safety

`update` requires:

- target is a Git repository root;
- working tree is clean unless `--allow-dirty` is used;
- a new branch can be created.

The default update branch is:

```text
chore/sync-nm-workflow-v3-YYYYMMDD
```

Template files are overwritten on that branch so the administrator can inspect changes with Git.
