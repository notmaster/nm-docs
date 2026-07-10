# Repository Agent Rules

This repository maintains reusable NotMaster workflow templates, skills, and deterministic tooling. Keep changes precise, explicitly versioned, and easy for other agents to execute.

`AGENTS.md` is the normative execution source for agents. `AGENTS.zh-CN.md` is its complete Simplified Chinese administrator-review mirror. If they conflict, follow this file, report the drift, and fix both in the same change. In this repository, **administrator** means the user who controls the current task and its external effects.

## Workflow Status And Authority

- V5 is experimental and retained for supervised trials only. Its current runner and built-in checks do not authorize or independently prove unattended merge, release, deployment, production access, or production readiness.
- `docs/nm-v6-workflow-spec.md` is the normative V6 design and acceptance source; its Chinese file is an administrator mirror. `template/v6`, `tools/nm-v6`, and `skills/nm-init-project-v6` form the V6 implementation. An exact V6 source snapshot is accepted only while a valid `tools/nm-v6/administrator-acceptance.json` record binds independently reviewed evidence and explicit administrator acceptance to that snapshot. The record-bound snapshot is administrator-accepted, but `recommended=false` and `production_ready=false`; any source drift invalidates that status.
- The existence, reading, review, or prior implementation of a Spec does not authorize a new implementation change or any protected/external action. Require explicit administrator instructions or a valid future V6 grant for the exact scope.
- V5 is not recommended. Although the record-bound V6 snapshot is accepted, do not describe V6 as recommended or production-ready unless a later, separately authorized designation changes those flags.
- Preserve V1-V5 unless the administrator explicitly authorizes removal. Do not change older versions merely to make a newer version pass.

## Language, Documentation, And Context

- Write user-facing documentation at the repository root in English by default.
- Provide complete Simplified Chinese mirrors for major user-facing documents under `docs/`.
- Change this file and `AGENTS.zh-CN.md` together; do not add, remove, or weaken a rule in only one language.
- Keep `README.md` focused on current workflow status and the recommended or active version when one exists. Put historical versions, installation details, and migration notes in `docs/`.
- Load this English execution source and only the version-specific documents needed for the current task. Do not load Chinese mirrors, historical versions, platform recipes, or recovery manuals unless the task requires them.
- Keep always-loaded agent rules concise. Link to detailed Specs and references instead of copying their manuals here.

## Work Authorization And Execution Quality

- A request to inspect, review, audit, explain, diagnose, or report status authorizes read-only checks only. It does not authorize file edits, branch/ref changes, staging, commits, merges, pushes, releases, or deployments.
- A request to change or build authorizes only scoped edits and normal implementation steps. Merge, push, release, deployment, destructive operations, and other external effects require explicit administrator authorization or, after V6 is implemented and accepted, a valid scoped V6 grant.
- Before a non-trivial task, state assumptions, material risks, and success criteria.
- Ask the administrator only when an ambiguity would materially change scope, authority, external state, safety, or the result. Otherwise perform safe read-only discovery, state the low-risk assumption, and continue.
- Prefer the simplest implementation that satisfies the request. Do not add unrequested features, abstractions, configuration, refactors, formatting, or cleanup.
- Keep changes surgical. Every changed line must trace to the current administrator request. Fix a validation failure only when the in-scope change caused it and the fix is necessary to validate that change; report pre-existing or unrelated failures without fixing them unless separately authorized.

## Repository Work Notifications

- For non-trivial change or build tasks, delivery through `./0d-scripts/notify-event.sh` to the configured project Feishu channels is a standing administrator-authorized external effect unless the administrator opts out for that task. This authorizes only status notifications, not any other external action.
- Emit `progress` only on material state changes: work start after preflight, completion of a meaningful stage, and final verified completion. Do not send routine heartbeats, one notification per command, or repeats for unchanged state.
- Emit `attention` before stopping for an administrator decision or authorization, a safety or secret risk, an unsafe Git condition or conflict, an exhausted repair or verification path, or another blocker that prevents safe progress.
- Messages must identify the task or branch and briefly state completed work, current status, next action, and material risk. Never include secrets, credentials, production data, raw webhook values, or unnecessarily detailed logs.
- Notifications communicate status only; they do not authorize, accept, merge, release, or deploy. Delivery failure does not invalidate completed work, but it must be reported and must not be hidden or rerouted through a system-level notifier without explicit administrator authorization.
- The root scripts deliberately reuse only the V5 notification adapter. This does not adopt the V5 runner or authority model and does not change V5's experimental status. See [Repository Work Notifications](docs/repository-notifications.md) for the event catalog, commands, and limitations.

## Git And Branching

- `dev` is the integration branch. The configured stable branch is `main` or `master` (`main` in this repository). Stable and `dev` are protected.
- AI workers and ordinary implementation sessions must not edit, commit on, reset, rebase, or force-push a protected branch. Hotfix is not an exception to direct protected-branch editing. Only an authorized integration action may update a protected ref after verification.
- Before starting a new ordinary change, inspect the working tree, run `git fetch --prune origin dev`, and create an allowed task branch at the exact `origin/dev` SHA. Use `feature/*`, `fix/*`, `docs/*`, `refactor/*`, `chore/*`, or `task/*`.
- Stop before writing if the working tree contains unexplained changes, fetch fails, remote state is unknown, or local `dev` has diverged. Never carry, stash, overwrite, or commit user changes merely to switch branches.
- A hotfix requires explicit administrator classification. Fetch the remote stable branch, create `hotfix/*` at its exact SHA, implement there, then integrate into stable after the current workflow's applicable verification and explicit authorization. Reconcile the same fix into `dev` and reverify. Retain the hotfix branch until release and rollback responsibility closes.
- Ordinary work integrates only into `dev`. Promote verified `dev` to stable only for an explicitly authorized release or stable update. Reconcile any stable-only or hotfix change back into `dev` before subsequent ordinary work.
- Before integration, required local checks must pass and the current repository requires explicit administrator acceptance. A V6 controller running an accepted, record-bound source snapshot may instead use a valid staged approval or scoped auto grant; rules text, prompts, agent reports, and process exit codes never substitute for gates or authorization.
- Immediately before integrating or pushing a protected ref, fetch its remote target again and compare it with the recorded expected SHA. If it moved, stop, resynchronize the candidate, and rerun affected checks and acceptance; old evidence or approval must not authorize the changed target.
- The AI must select the merge strategy from fast-forward, squash, or merge commit based on branch purpose, sharing status, topology, commit quality, auditability, conflict risk, and rollback needs. Record source/target SHAs, rationale, expected result tree, and verification. Rebase only an unpublished disposable source branch; never rewrite shared history without explicit authorization.
- Push stable or `dev` only after the corresponding authorized integration and verification, and report before/after SHAs. Other branches stay local unless the administrator explicitly names the branch, remote, and backup/review purpose. Never force-push protected refs. Remote deletion always requires a new explicit authorization separate from push authorization.
- After integration, record `delete_local`, `retain`, or `request_administrator`. Delete a local task branch only with exact-head integration proof (ancestry or squash patch/tree equivalence) and no review, dependency, backup, worktree, session, release, or rollback responsibility. Never auto-delete `main`, `master`, `dev`, `release/*`, `hotfix/*`, unmerged branches, or branches still in use.

## Enforcement, Templates, Skills, And Tools

- `AGENTS.md`, Skills, prompts, model memory, and agent self-reports are context, not technical enforcement or acceptance evidence. Branch protection, state transitions, permissions, gates, release, and deployment constraints in generated workflows must be enforced by deterministic code and executable tests.
- Prefer deterministic scripts for init, update, audit, install, synchronization, and validation. Do not rely on prose for fragile file operations.
- For every manifest-backed template, `template/<version>/manifest.json` is the source of truth for its generated file set. When adding or renaming template files, update the manifest, that version's structure documentation when present, and repository-facing version documentation.
- Keep each template version self-contained. The V6 Spec governs `template/v6`; do not weaken it, import mutable V5 runtime state, or treat an implementation snapshot as accepted merely because files or checks exist. Only a valid administrator-acceptance record can bind accepted status to its exact source snapshot.
- Store repository-maintained skills under `skills/<skill-name>/`. Every skill must contain a valid, concise, trigger-oriented `SKILL.md`; keep references one level below it and load them only when needed. Do not add unrelated README, changelog, or guide files inside skill folders.
- Existing-project update tools must require Git, validate a clean and current remote `dev` baseline, create an allowed branch before writing, stage output outside the target when practical, and validate before applying.
- Never silently discard project-specific guidance during migration. Preserve durable information in the appropriate version-specific, project-owned document.

## Safety

- Do not overwrite, stash, commit, move across branches, or otherwise absorb uncommitted user changes without explicit authorization.
- Do not run destructive Git or external operations unless explicitly authorized. Evidence-backed deletion of a fully integrated local task branch is permitted only under the cleanup rule above; remote or unmerged branch deletion is not.
- When project files need deletion, move them to `.delete-pending/` and wait for administrator confirmation unless a confirmed Spec explicitly defines another reversible policy.
- Do not expose secrets, production credentials, or production data to agents, tests, logs, evidence, or notifications.

## Validation And Evidence

- Run `git diff --check` for every change and `npm run lm` after Markdown changes.
- After V3, V4, or V5 template/tool changes, run the corresponding `npm run v3:check`, `npm run v4:check`, or `npm run v5:check` command.
- After V6 template, tool, schema, or runtime changes, run `npm run v6:check` and `npm run v6:test`.
- After changing a repository skill, run the corresponding `npm run skill:<version>:check` command when available. Do not copy user-specific absolute validator paths into agent rules.
- Run syntax checks and the smallest complete relevant test suite for changed scripts or tools. For generated projects, run their declared `workflow:check`, workflow tests when present, and `verify` commands.
- For bilingual documents, verify both structure and semantics, including stable IDs, status, requirements, and acceptance mappings where applicable; Markdown lint alone is insufficient.
- V6 changes must keep the Spec-required commands passing: `npm run lm`, `npm run v6:check`, `npm run v6:test`, and `npm run skill:v6:check`.
- Report the exact validation commands and results. Mark required checks that were not run as `not run`; agent claims and exit code alone are not independent acceptance evidence.
