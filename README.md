# nm-docs

English | [中文](docs/README.zh-CN.md)

`nm-docs` maintains NotMaster workflow templates, skills, and deterministic tooling for AI-assisted project delivery.

The recommended workflow is currently **NM V5**, a hybrid spec-driven workflow:

```text
SPEC (confirmed)
-> runtime INDEX + Task cards (disk truth)
-> runner + short orchestrator + workers
-> staged (phase acceptance) or auto (hard-stop only / authorized skip)
-> merge to dev per task unit
```

## Recommended Version

Use [template/v5](template/v5) for new projects and workflow updates.

V5 focuses on:

- Disk state machine: thin `0b-runtime/INDEX.yaml` + per-task cards (not conversation memory).
- Hybrid orchestration: deterministic runner, short orchestrator sessions, worker sessions with minimum context packs.
- Two modes: `staged` and `auto`, with forced admin choice when mode is unspecified; mode can switch on resume with conflict explanation.
- Self-repair default **10**; `skip_on_fail` only when explicitly set (auto).
- Event-based notifications (pluggable channels; Feishu first).
- Agent docs in **English**; Simplified Chinese admin mirrors; ratified design resolution v1 under the template.
- CLI + Skill dual entry (`tools/nm-v5`, `skills/nm-init-project-v5`).

Design resolution (v1): [template/v5/0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md](template/v5/0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md)

## Quick Start

Initialize a new project from a local checkout:

```bash
python3 tools/nm-v5/nm_v5.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

Update an existing Git project:

```bash
python3 tools/nm-v5/nm_v5.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

Then run the same command without `--dry-run` after reviewing the plan.

Status and notify test:

```bash
python3 tools/nm-v5/nm_v5.py status --target /absolute/path/to/project
python3 tools/nm-v5/nm_v5.py notify-test --target /absolute/path/to/project
python3 tools/nm-v5/nm_v5.py notify-test --target /absolute/path/to/project --severity attention
```

Feishu setup (global env + dual channel): see
[template/v5/0c-workflow/NOTIFY_EVENTS.md](template/v5/0c-workflow/NOTIFY_EVENTS.md).

Install the V5 skill for local agents:

```bash
bash tools/nm-v5/install-skill.sh --target-dir "$HOME/.agents/skills"
```

Open skills ecosystem (when available):

```bash
npx skills add notmaster/nm-docs --skill nm-init-project-v5
```

After installation, start a new agent thread and ask:

```text
Use $nm-init-project-v5 to initialize or update this project.
```

## Repository Layout

```text
template/v5/                  # Recommended NM V5 hybrid workflow template
skills/nm-init-project-v5/    # Agent skill wrapper for V5 init/update
tools/nm-v5/                  # Deterministic V5 CLI-style tooling
template/v4/                  # Previous V4 spec-driven workflow
skills/nm-init-project-v4/    # V4 skill
tools/nm-v4/                  # V4 tooling
template/v3/                  # Previous V3 goal-driven workflow
skills/nm-init-project-v3/    # V3 skill
tools/nm-v3/                  # V3 tooling
template/v2/                  # Earlier V2 collaboration workflow
template/v1/                  # Legacy V1 base template
docs/                         # User-facing documentation and translations
```

## Validation

Run repository checks:

```bash
npm install
npm run lm
python3 tools/nm-v5/nm_v5.py check --target template/v5 --source-dir .
python3 tools/nm-v4/nm_v4.py check --target template/v4 --source-dir .
python3 tools/nm-v3/nm_v3.py check --target template/v3 --source-dir .
```

For a generated V5 project, run inside that project:

```bash
npm install
npm run workflow:check
npm run verify
```

## More Documentation

- [Chinese README](docs/README.zh-CN.md)
- [Template versions](docs/template-versions.md)
- [Skill and tool installation](docs/installation.md)
- [V5 template README](template/v5/README.md)
- [V5 design resolution v1](template/v5/0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md)
- [V5 manifest](template/v5/manifest.json)
- [V4 template README](template/v4/README.md)
- [V4 design decisions (zh-CN)](docs/nm-v4-design-decisions.zh-CN.md)
