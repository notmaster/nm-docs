# nm-docs

English | [中文](docs/README.zh-CN.md)

`nm-docs` maintains NotMaster workflow templates, Skills, and deterministic
tooling for AI-assisted project delivery.

## Recommended workflow: NM V3.1

**NM V3.1 (`3.1.0`) is the recommended workflow for new projects.** It keeps
project control in a small set of readable files and supports both quick changes
and planned multi-Goal development without requiring a heavyweight runtime.

V3.1 is recommended because it provides:

- an optional `0a-docs/spec.md` containing requirements and acceptance criteria;
- a project-owned reference allowlist in `AGENTS.md`, so agents read optional
  design, prototype, or Spec documents only when the project activates them;
- a standalone Goal path for small changes and a Plan-to-Goals path for larger
  work;
- self-contained Goal files that can be handed directly to an implementation
  agent;
- serial per-Goal tests and self-review, followed by one full verification after
  all Goals in a Plan are integrated;
- protected-branch rules with Plan and Goal branches based on exact Git SHAs;
- strict Feishu progress and attention channels, with final completion delivered
  as a visible attention handoff;
- transactional init, update, migration, status, validation, self-contained
  exact-tool Skill distribution, and idempotent completion commands.

Recommendation selects the default workflow; it does not authorize protected
branch updates, pushes, releases, deployments, production access, or other
external effects.

## V3.1 workflow

Use the smallest path that fits the work:

```text
Small request
  -> standalone Goal
  -> Goal implementation, tests, and self-review
  -> administrator integration decision

Planned work
  -> optional spec.md
  -> Plan
  -> just-in-time self-contained Goals
  -> each Goal: implemented -> verified -> integrated
  -> one full project verification
  -> administrator Plan review
```

The implementation agent writes tests and self-reviews by default. Set
`independent_reviewer_required: true` in a Goal only when the administrator asks
for an independent reviewer before execution.

## Start a project

Initialize a new project from this checkout:

```bash
python3 tools/nm-v3/nm_v3.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

Then validate the generated project:

```bash
cd /absolute/path/to/project
npm install
npm run workflow:check
npm run verify
```

For an existing V3 project, inspect status and preview the update before writing:

```bash
python3 tools/nm-v3/nm_v3.py status --target /absolute/path/to/project
python3 tools/nm-v3/nm_v3.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

Use `migrate --dry-run` instead of `update --dry-run` when converting a V3 3.0
project that still has separate Requirements and Acceptance documents. The
updater and migrator require a clean Git repository at the current remote `dev`
baseline and create an allowed task branch before changing files.

After the immutable `v3.1.0` release tag is published, install through the
interactive `vercel-labs/skills` flow:

```bash
npx skills add notmaster/nm-docs@v3.1.0 --global
```

Select `nm-init-project-v3` and the target agents in the prompt. Keep the
default single canonical installation under `~/.agents/skills`; do not maintain
independent copies in multiple agent directories.

Or use the built-in installer:

```bash
python3 tools/nm-v3/nm_v3.py install-skill \
  --target-dir "$HOME/.agents/skills"
```

Remote installation and update must use an administrator-reviewed immutable tag
rather than mutable `main`; see [Installation](docs/installation.md).

## Work in a generated project

- Read `AGENTS.md` first; its project-owned block identifies the optional
  documents active for that project.
- For a small or later-stage change, create one standalone Goal from
  `0c-workflow/GOAL_TEMPLATE.md`. A Spec is not required unless the
  administrator requests one.
- For larger work, optionally create `0a-docs/spec.md`, create a Plan from
  `0c-workflow/PLAN_TEMPLATE.md`, then create Goals just in time.
- Treat every Goal as a complete execution packet containing its required
  context, TODOs, acceptance criteria, commands, and execution record.
- Run Goal-specific tests before `verified -> integrated`; run the full project
  verification once after every Goal in the Plan is integrated.
- Wait for explicit administrator instructions before protected integration or
  push operations.

## Repository V3 commands

Changes to the V3 template, tool, or Skill must pass:

```bash
npm run lm
npm run v3:check
npm run v3:test
npm run skill:v3:check
npm run skill:v3:vercel:check
```

## Other workflow versions

- **V6**: its record-bound exact source snapshot is administrator-accepted after
  independent evidence review, but V6 remains `recommended=false` and
  `production_ready=false`.
- **V5**: retained as an experimental supervised-trial workflow; it is not
  recommended.
- **V7**: design work is shelved and has no implementation, template, tool,
  accepted snapshot, or active controller.
- **V1, V2, and V4**: retained for compatibility, existing projects, and
  historical reference.

Acceptance or verification of another version does not make it the recommended
workflow and does not transfer authority to a generated project.

## Repository layout

```text
template/v3/                  # Recommended self-contained V3.1 template
tools/nm-v3/                  # Deterministic V3.1 CLI and tests
skills/nm-init-project-v3/    # V3.1 agent entry and references
template/v6/                  # Administrator-accepted record-bound V6 snapshot
template/v5/                  # Experimental V5 trial workflow
template/v4/ … template/v1/  # Preserved earlier versions
docs/                         # User documentation and Chinese mirrors
```

## Documentation

- [NM V3.1 upgrade](docs/nm-v3-3.1-upgrade.md) / [中文](docs/nm-v3-3.1-upgrade.zh-CN.md)
- [V3.1 lifecycle](skills/nm-init-project-v3/references/v3-lifecycle.md)
- [V3.1 generated-project workflow](template/v3/0c-workflow/WORKFLOW_V3.md)
- [Template versions](docs/template-versions.md) / [中文](docs/template-versions.zh-CN.md)
- [Installation](docs/installation.md) / [中文](docs/installation.zh-CN.md)
- [Repository work notifications](docs/repository-notifications.md) / [中文](docs/repository-notifications.zh-CN.md)
- [V6 normative workflow Spec](docs/nm-v6-workflow-spec.md) / [中文管理员镜像](docs/nm-v6-workflow-spec.zh-CN.md)
