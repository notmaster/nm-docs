# nm-docs

English | [中文](docs/README.zh-CN.md)

`nm-docs` maintains NotMaster workflow templates, Skills, and deterministic
tooling for AI-assisted project delivery.

## Current workflow status

- **V6**: the exact source snapshot identified by a valid
  `tools/nm-v6/administrator-acceptance.json` record is
  administrator-accepted after independent evidence review. Acceptance is not
  transferable to a modified or unrecorded snapshot. V6 remains
  `recommended=false` and `production_ready=false`.
- **V5**: retained as an experimental supervised-trial workflow. Its runner and
  checks do not authorize or independently prove unattended merge, release,
  deployment, production access, or production readiness.
- **V4 and earlier**: retained for existing projects and historical reference.

V6 uses one SQLite runtime authority, a deterministic reducer and gate engine,
signed trusted-control-plane records, standalone candidate workspaces, thin
Codex/GrokBuild/Claude adapters, content-addressed redacted evidence, protected
Git integration, recoverable delivery actions, audit chaining, and a durable
notification outbox. Staged and auto modes share the same state graph and
technical gates.

V6 does not import or resume V5's mutable `INDEX.yaml` or Task-card runtime.
Repository-level acceptance covers only the record-bound V6 implementation
snapshot. Every generated project must still define and confirm its own Spec,
pass its own gates, and present valid scoped grants before protected or external
effects.

## V6 repository commands

The V6 core requires Python 3.11 or newer. The repository wrapper locates an
eligible runtime or accepts `NM_V6_PYTHON`.

```bash
npm run lm
npm run v6:check
npm run v6:test
npm run skill:v6:check
```

Initialize a disposable or new project from this checkout:

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

Preview a safe existing-project update:

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

The updater requires a clean Git root, a successful fetch, exact
remote-tracking `dev`, an allowed new branch, outside-target staging, validation
before application, and deterministic resume or abort after an injected or real
failure.

Install the thin Skill from this checkout:

```bash
bash tools/nm-v6/install-skill.sh --target-dir "$HOME/.agents/skills"
```

The installer binds the Skill to the reviewed checkout and its executable V6
sources. Reinstall after a reviewed core update; digest drift fails closed.

## Generated V6 project

Inside a generated project:

```bash
npm install
npm run workflow:check
npm run workflow:test
npm run verify
```

These commands produce technical evidence; they do not confirm a project Spec,
sign an approval, grant protected/external authority, or transfer the upstream
repository snapshot's administrator acceptance to the generated project.

## Repository layout

```text
template/v6/                  # Self-contained V6 implementation
tools/nm-v6/                  # Deterministic CLI/core, schemas, and acceptance tests
skills/nm-init-project-v6/    # Thin agent entry over the same CLI
template/v5/                  # Experimental V5 trial workflow
skills/nm-init-project-v5/    # V5 maintenance Skill
tools/nm-v5/                  # V5 maintenance tooling
template/v4/ … template/v1/  # Preserved earlier versions
docs/                         # User documentation and administrator mirrors
```

## Documentation

- [V6 normative workflow Spec](docs/nm-v6-workflow-spec.md) / [中文管理员镜像](docs/nm-v6-workflow-spec.zh-CN.md)
- [V6 implementation traceability](docs/nm-v6-implementation-traceability.md)
- [Template versions](docs/template-versions.md) / [中文](docs/template-versions.zh-CN.md)
- [Installation](docs/installation.md) / [中文](docs/installation.zh-CN.md)
- [Repository work notifications](docs/repository-notifications.md) / [中文](docs/repository-notifications.zh-CN.md)
- [V6 template workflow](template/v6/0c-workflow/WORKFLOW_V6.md) / [中文](template/v6/0c-workflow/WORKFLOW_V6.zh-CN.md)
