# Installation

## Install The V5 Skill (recommended)

Default target:

```text
~/.agents/skills
```

Install from this repository:

```bash
bash tools/nm-v5/install-skill.sh --target-dir "$HOME/.agents/skills"
```

Install for a Codex-specific skill directory:

```bash
bash tools/nm-v5/install-skill.sh --target-dir "$HOME/.codex/skills"
```

Open skills ecosystem (when available):

```bash
npx skills add notmaster/nm-docs --skill nm-init-project-v5
```

After installation, start a new agent thread and invoke:

```text
Use $nm-init-project-v5 to initialize or update this project.
```

## Use The V5 Tool Without A Skill

```bash
python3 tools/nm-v5/nm_v5.py init --target /absolute/project --source-dir .
python3 tools/nm-v5/nm_v5.py update --target /absolute/project --source-dir . --dry-run
python3 tools/nm-v5/nm_v5.py update --target /absolute/project --source-dir .
python3 tools/nm-v5/nm_v5.py check --target /absolute/project --source-dir .
python3 tools/nm-v5/nm_v5.py status --target /absolute/project
python3 tools/nm-v5/nm_v5.py notify-test --target /absolute/project
```

## Update Safety (V5)

`update` requires:

- target is a Git repository root;
- working tree is clean unless `--allow-dirty` is used;
- a new branch can be created.

Default update branch:

```text
chore/sync-nm-workflow-v5-YYYYMMDD
```

Only `managed` framework files are overwritten; `create-only` project content
(e.g. `README.md`, `0b-runtime/INDEX.yaml`, `DECISIONS.md`) is preserved.

## V4 Equivalents

```bash
bash tools/nm-v4/install-skill.sh --target-dir "$HOME/.agents/skills"
python3 tools/nm-v4/nm_v4.py init --target /absolute/project --source-dir .
python3 tools/nm-v4/nm_v4.py update --target /absolute/project --source-dir . --dry-run
```

## V3 Equivalents

```bash
bash tools/nm-v3/install-skill.sh --target-dir "$HOME/.agents/skills"
python3 tools/nm-v3/nm_v3.py init --target /absolute/project --source-dir .
python3 tools/nm-v3/nm_v3.py update --target /absolute/project --source-dir . --dry-run
```
