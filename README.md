# nm-docs

English | [中文](docs/README.zh-CN.md)

`nm-docs` maintains NotMaster workflow templates, skills, and deterministic tooling for AI-assisted project delivery.

The recommended workflow is currently **NM V3**, a lightweight goal-driven workflow built around:

```text
REQUIREMENTS.md
-> ACCEPTANCE.md
-> DESIGN.md
-> Plan
-> Goal
-> local verify
-> administrator acceptance
-> merge
```

## Recommended Version

Use [template/v3](template/v3) for new projects and workflow updates.

V3 focuses on:

- Administrator-owned requirements, acceptance criteria, and design documents.
- Plan and Goal files for controlled `/goal` execution.
- Local deterministic verification instead of heavy CI/CD during 0-to-1 development.
- Feishu notification hooks for administrator decisions.
- Prompt templates for requirements discovery, DESIGN.md authoring, Plan/Goal splitting, and security review.
- A small `AGENTS.md` instruction surface for agents.

## Quick Start

Initialize a new project from a local checkout:

```bash
python3 tools/nm-v3/nm_v3.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

Update an existing Git project:

```bash
python3 tools/nm-v3/nm_v3.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

Then run the same command without `--dry-run` after reviewing the plan.

Install the V3 skill for local agents:

```bash
bash tools/nm-v3/install-skill.sh --target-dir "$HOME/.agents/skills"
```

After installation, start a new agent thread and ask:

```text
Use $nm-init-project-v3 to initialize or update this project.
```

## Repository Layout

```text
template/v3/                 # Recommended NM V3 workflow template
skills/nm-init-project-v3/    # Agent skill wrapper for V3 init/update
tools/nm-v3/                  # Deterministic V3 CLI-style tooling
template/v2/                  # Previous V2 collaboration workflow
template/temp-*               # Legacy V1 base templates
docs/                         # User-facing documentation and translations
```

## Validation

Run repository checks:

```bash
npm install
npm run lm
python3 tools/nm-v3/nm_v3.py check --target template/v3 --source-dir .
```

For a generated V3 project, run inside that project:

```bash
npm install
npm run workflow:check
npm run verify
```

## More Documentation

- [Chinese README](docs/README.zh-CN.md)
- [Template versions](docs/template-versions.md)
- [Skill and tool installation](docs/installation.md)
- [V3 template README](template/v3/README.md)
- [V3 manifest](template/v3/manifest.json)
