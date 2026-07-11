# NM V3.1 Upgrade

English | [中文](nm-v3-3.1-upgrade.zh-CN.md)

NM V3.1 simplifies the preserved V3 Goal workflow and is the recommended
workflow for new projects. Recommendation does not declare production readiness,
grant protected or external authority, or adopt the V5 runner or authority
model.

## Version

- Workflow family: V3
- Template version: `3.1.0`
- State schema: `2`
- Direct migration source: `3.0.0`

Generated projects record the template version, source ref/commit and dirty
status when known, an exact rendered-source snapshot hash, managed file hashes,
timestamps, and optional spec version/body hash in
`.nm-template-state.json`. Use `nm_v3.py status` to inspect them.

## Main Changes

- Optional project spec at `0a-docs/spec.md`; project requirements and acceptance
  criteria share that document.
- No required Requirements, Acceptance, Design, prototype, release, project
  structure, decisions, or project-profile documents in the minimal template.
- `AGENTS.md` contains a project-owned reference allowlist. Unlisted optional
  documents are not read merely because they exist.
- Small work may use one standalone Goal. Planned work uses a Plan branch and
  just-in-time self-contained Goals.
- Goal implementation children write tests and self-review by default. An
  independent Reviewer is enabled only by pre-execution Goal configuration after
  an explicit administrator request.
- Goal-specific verification runs per Goal. Full project verification runs once
  after all Goals are integrated.
- Protected branches require exact remote-SHA checks and explicit administrator
  integration/push authority.
- Feishu progress and attention use required, distinct webhooks. Attention never
  falls back to progress, and final completion is always an attention handoff.
- Spec acceptance binds both version and body hash; same-version body changes
  cannot be stamped.
- Updates, migrations, and Spec creation use validated file transactions with
  rollback, and remote refs resolve to one immutable commit.
- Installed Skills bundle and verify the exact V3 tool instead of downloading a
  mutable executable.
- Goals are serial, and Plan/Goal evidence is bound to commit SHAs.
- Final completion uses an idempotent `finish` command and durable delivery
  record.

## Migration

Always inspect first:

```bash
python3 tools/nm-v3/nm_v3.py status --target /project
python3 tools/nm-v3/nm_v3.py migrate --target /project --source-dir . --dry-run
```

The explicit migration creates a task branch at exact `origin/dev`, combines
the old Requirements and Acceptance content into a draft spec, preserves
markerless legacy AGENTS guidance for administrator review, installs the new
project-owned rules blocks, and moves the two source documents into
`.delete-pending/v3-3.1.0-migration/`. The administrator must review the result;
migration does not accept the spec or authorize protected/external actions.

Legacy Design, release, decisions, structure, prompt, or project-profile files
are not silently deleted. Keep them only when useful and list active references
in `AGENTS.md`.

## Validation

Repository changes to V3 must pass:

```bash
npm run lm
npm run v3:check
npm run v3:test
npm run skill:v3:check
```

Generated projects run `npm run workflow:check` and their full `npm run verify`.
These checks are technical evidence, not administrator acceptance or authority.
