# Agent Rules

This file contains only the hard rules that the agent must follow on every run.
For the full workflow, read `0c-workflow/WORKFLOW_V3.md`.

## Language And Environment

- Use Simplified Chinese for user communication, project documentation, and necessary code comments by default.
- Use UTC+8 as the default timezone.

## Branching

- The default integration branch is `dev`.
- Do not perform regular development directly on `main`.
- Regular tasks must branch from `dev` and use one of these prefixes:
  `feature/*`, `fix/*`, `docs/*`, `refactor/*`, or `chore/*`.
- Use `hotfix/*` only for urgent production fixes, and create it from `main`.
- Before merging back to `dev`, local verification must pass and the administrator must accept the work, unless both the active Plan and the active Goal set `auto_merge_to_dev: true`.

## Goal Workflow

- Plans live under `0b-goals/0a-plans/` and must use `Plan-<YYYYMMDD>-PlanID<001>-<slug>.md`.
- Active Goals live under `0b-goals/0b-current/` and must use `Goal-<YYYYMMDD>-PlanID<001>-<GoalID001>-<slug>.md`.
- Before implementation, read the active Goal under `0b-goals/0b-current/` and its referenced Plan.
- `0b-goals/0b-current/` must contain at most one active Goal by default. If multiple Goal files exist, stop and ask the administrator which one is active.
- If no active Goal exists, do not start substantial implementation. Ask the administrator whether a Goal should be created first.
- When the administrator requests a new feature, behavior change, or complex bugfix, create or update a Goal first and wait for administrator confirmation before implementation.
- If the administrator explicitly asks for automatic implementation, automatic fixing, or no confirmation, the agent may create the Goal and then execute it immediately.
- Default execution fields are `administrator_review_required: true`, `auto_execute_goals: false`, `auto_merge_to_dev: false`, and `auto_push: true`.
- After a Goal is complete, the agent may push the working branch for backup when `auto_push: true`.
- Do not merge into `dev` unless the administrator explicitly approves it or both the active Plan and the active Goal set `auto_merge_to_dev: true`.
- Full automatic execution may split a Plan into Goals, execute them serially, verify, push, merge, archive, and continue only when the administrator explicitly authorizes it through the Plan fields.
- When automatic execution completes or becomes blocked, call `0d-scripts/notify-admin.sh` to notify the administrator.

## Execution Quality

- Before starting a non-trivial task, state the assumptions, risks, and success criteria.
- If the request has multiple reasonable interpretations, do not choose silently. Ask the administrator or write the ambiguity into the Goal and wait for confirmation.
- Prefer the simplest implementation that satisfies the request. Do not add unrequested features, abstractions, or configuration.
- Keep changes surgical. Do not opportunistically refactor, reformat, or clean up unrelated code.
- Every changed line should trace back to the active Goal or the administrator request.
- Record important product, design, architecture, deployment, or workflow decisions in `0a-docs/DECISIONS.md`.

## Verification

- Before a Goal is considered complete, run local verification according to `0c-workflow/VERIFY.md`.
- The default verification entrypoint is `./0d-scripts/verify.sh`.
- The lightweight workflow check entrypoint is `./0d-scripts/check-workflow.sh`.
- `0c-workflow/project-profile.yml` declares the project type and verification requirements. In the early template, `verify.sh` is not required to parse this file automatically.
- If the same category of verification failure cannot be fixed after 5 consecutive attempts, stop the repair loop and notify the administrator.
- During 0-to-1 development, do not rely on remote CI as the quality gate.

## Notifications

- For questions that require administrator confirmation or for important status updates, call `0d-scripts/notify-admin.sh`.
- Feishu notification is recommended, not blocking.
- The Feishu config path is fixed at `~/.config/nm-docs/nm-notify-feishu.env`.
- If the Feishu config is missing, scripts must print a clear warning and exit successfully without blocking development.

## Safety

- Do not overwrite uncommitted user changes.
- Do not run destructive git operations unless the administrator explicitly requests them.
- When files need to be deleted, prefer moving them to `.delete-pending/` and wait for administrator confirmation.
- If acceptance criteria are unclear, verification commands are missing, external services are unavailable, or safety risks exist, stop and ask the administrator.
