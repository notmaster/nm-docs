# NM V4 Lifecycle

## Source Of Truth

- Repository: `https://github.com/notmaster/nm-docs.git`
- Template: `template/v4/`
- Manifest: `template/v4/manifest.json`
- Deterministic tool: `tools/nm-v4/nm_v4.py`
- Project state: `.nm-template-state.json`

## Main Flow

V4 is spec-driven:

```text
SPEC (0a-docs/0a-spec/, status: confirmed)
-> ROADMAP (0b-goals/ROADMAP.md, phase table + per-phase acceptance)
-> one fresh session per phase
   staged: implement -> verify -> push -> notify -> wait for acceptance -> merge to dev
   auto:   implement -> verify -> push -> merge to dev -> notify -> next phase (runner)
-> final acceptance (manual acceptance backlog in the ROADMAP)
```

Key files:

- Spec naming: `SPEC-<slug>-V<n>.md` under `0a-docs/0a-spec/`.
- `0b-goals/ROADMAP.md` is the single runtime state file. Never overwrite it during updates.
- Session handoff set: `AGENTS.md` + Spec + `ROADMAP.md`.
- Execution modes: `staged` (per-phase administrator gate) and `auto`
  (unattended runner `0d-scripts/run-goals.py`, permissions tier `bypass` or `sandbox`).

## Update Policy

For existing projects, require Git and a clean working tree. Create a branch before writing. Only `managed` framework files are overwritten on that branch; `create-only` files (README, ROADMAP, DECISIONS, prompts other than security-review, verify.sh, configs) are preserved. Git diff is the review mechanism.

V3 migration extras:

- Superseded V3 framework files are moved to `.delete-pending/v3-superseded/` and wait for administrator confirmation: `WORKFLOW_V3.md`, `PLAN_TEMPLATE.md`, `GOAL_TEMPLATE.md`, `discover-requirements.md`, `plan-goals-from-requirements.md`, `write-design-md.md`.
- `REQUIREMENTS.md`, `ACCEPTANCE.md`, and `DESIGN.md` stay in place as Spec input material. The Spec itself is synthesized by the administrator and the agent together; the tool never rewrites documents.
- Old `0b-goals` Plan and Goal files are project history; leave them in place.

Do not silently discard old project-specific guidance. Preserve durable facts by moving them into the appropriate V4 file:

- `0a-docs/DECISIONS.md` for product, design, architecture, deployment, or process decisions.
- `0c-workflow/project-profile.yml` for project type and verification expectations.
- `PROJECT_STRUCTURE.md` for structure facts.
- The Spec for product scope, constraints, and acceptance.

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
