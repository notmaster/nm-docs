# NM V3 Lifecycle

## Source Of Truth

- Repository: `https://github.com/notmaster/nm-docs.git`
- Template: `template/v3/`
- Manifest: `template/v3/manifest.json`
- Deterministic tool: `tools/nm-v3/nm_v3.py`
- Project state: `.nm-template-state.json`

## Main Flow

V3 uses:

```text
REQUIREMENTS.md
-> ACCEPTANCE.md
-> DESIGN.md
-> Plan
-> Goal
-> local verify
-> push branch backup
-> administrator acceptance
-> merge
```

Plans live in `0b-goals/0a-plans/` and use:

```text
Plan-<YYYYMMDD>-PlanID<001>-<slug>.md
```

Current Goals live in `0b-goals/0b-current/` and use:

```text
Goal-<YYYYMMDD>-PlanID<001>-<GoalID001>-<slug>.md
```

## Update Policy

For existing projects, require Git and a clean working tree. Create a branch before writing. Template files may be overwritten on that branch; Git diff is the review mechanism.

Do not silently discard old project-specific guidance. Preserve durable facts by moving them into the appropriate V3 file:

- `0a-docs/DECISIONS.md` for product, design, architecture, deployment, or process decisions.
- `0c-workflow/project-profile.yml` for project type and verification expectations.
- `PROJECT_STRUCTURE.md` for structure facts.
- `REQUIREMENTS.md` for product scope and constraints.

## Validation

After init or update, run:

```bash
npm install
npm run workflow:check
npm run verify
```

If package installation is not appropriate, run:

```bash
bash 0d-scripts/check-workflow.sh
bash 0d-scripts/verify.sh
```
