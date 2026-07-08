# nm-docs

English | [中文](docs/README.zh-CN.md)

`nm-docs` maintains NotMaster workflow templates, skills, and deterministic tooling for AI-assisted project delivery.

The recommended workflow is currently **NM V4**, a lightweight spec-driven workflow built around:

```text
SPEC (confirmed)
-> ROADMAP (phases)
-> one fresh agent session per phase
-> local verify
-> staged acceptance gate, or unattended auto runner
-> merge to dev
```

## Recommended Version

Use [template/v4](template/v4) for new projects and workflow updates.

V4 focuses on:

- A single administrator-owned Spec contract instead of separate requirement, acceptance, and design documents.
- A single runtime state file (`0b-goals/ROADMAP.md`) instead of Plan and Goal layers.
- One fresh agent session per phase, handed over through files, to avoid long-run context degradation.
- Two execution modes: `staged` with a per-phase administrator acceptance gate, and `auto` with an unattended runner that merges to `dev` after verification.
- Agent-neutral rules in `AGENTS.md`, thin pointer files for Claude Code and Grok, and launch recipes per CLI.
- Local deterministic verification and Feishu notification hooks.

## Quick Start

Initialize a new project from a local checkout:

```bash
python3 tools/nm-v4/nm_v4.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

Update an existing Git project, including NM V3 projects:

```bash
python3 tools/nm-v4/nm_v4.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

Then run the same command without `--dry-run` after reviewing the plan.

Install the V4 skill for local agents:

```bash
bash tools/nm-v4/install-skill.sh --target-dir "$HOME/.agents/skills"
```

After installation, start a new agent thread and ask:

```text
Use $nm-init-project-v4 to initialize or update this project.
```

## Repository Layout

```text
template/v4/                  # Recommended NM V4 spec-driven workflow template
skills/nm-init-project-v4/    # Agent skill wrapper for V4 init/update
tools/nm-v4/                  # Deterministic V4 CLI-style tooling
template/v3/                  # Previous V3 goal-driven workflow
skills/nm-init-project-v3/    # V3 skill, kept for existing projects
tools/nm-v3/                  # V3 tooling
template/v2/                  # Earlier V2 collaboration workflow
template/v1/                  # Legacy V1 base template, retained for reference
docs/                         # User-facing documentation and translations
```

## Validation

Run repository checks:

```bash
npm install
npm run lm
python3 tools/nm-v4/nm_v4.py check --target template/v4 --source-dir .
python3 tools/nm-v3/nm_v3.py check --target template/v3 --source-dir .
```

For a generated V4 project, run inside that project:

```bash
npm install
npm run workflow:check
npm run verify
```

## More Documentation

- [Chinese README](docs/README.zh-CN.md)
- [Template versions](docs/template-versions.md)
- [Skill and tool installation](docs/installation.md)
- [V4 design decisions (zh-CN)](docs/nm-v4-design-decisions.zh-CN.md)
- [V4 template README](template/v4/README.md)
- [V4 manifest](template/v4/manifest.json)
- [V3 template README](template/v3/README.md)
