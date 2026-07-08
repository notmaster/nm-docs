# Agent Rules

This file contains only the hard rules for every run. Full workflow: `0c-workflow/WORKFLOW_V4.md`. Launch recipes per agent CLI: `0c-workflow/AGENT_RECIPES.md`.

## Language And Environment

- Use Simplified Chinese for user communication, project documentation, and necessary code comments by default.
- Use UTC+8 as the default timezone.

## Execution Contract

- The session handoff set is three files: `AGENTS.md`, the confirmed Spec under `0a-docs/0a-spec/`, and `0b-goals/ROADMAP.md`. Read them before substantial work; load other workflow docs only when needed.
- Execute only a Spec whose frontmatter has `status: confirmed`.
- `0b-goals/ROADMAP.md` is the single runtime state file. Keep phase status, results, and handoff notes there. Record durable decisions in `0a-docs/DECISIONS.md`.
- Without a confirmed Spec and a ROADMAP phase entry, do not start substantial implementation. Ask the administrator first.

## Execution Modes

- `staged` (default): execute exactly one phase per session. Implement, verify, push, notify, then stop and wait for administrator acceptance. Merge to `dev` only after acceptance.
- `auto`: allowed only when the Spec frontmatter sets `execution_mode: auto` or the administrator authorizes it in the launch instruction. Execute phases serially; after verification passes, push, merge to `dev`, update the ROADMAP, notify, and continue.
- A launch instruction may override the Spec default mode.
- In `auto` mode, manual acceptance items must not block execution; append them to the ROADMAP manual acceptance backlog.

## Branching

- `dev` is the integration branch. Never develop directly on `main`.
- Each phase runs on a task branch created from the latest `dev`, using `feature/*`, `fix/*`, `docs/*`, `refactor/*`, or `chore/*`. Use `hotfix/*` only for urgent production fixes from `main`.
- ROADMAP bookkeeping commits (creation and status updates) may be committed directly on `dev`; all other changes go through task branches.
- Follow `0c-workflow/BRANCHING.md` for merge and cleanup rules. Never auto-delete `main`, `dev`, `release/*`, `hotfix/*`, unmerged branches, or branches still under review or acceptance.

## Execution Quality

- Before non-trivial work, state assumptions, risks, and success criteria.
- Prefer the simplest implementation. No unrequested features, abstractions, or opportunistic refactors.
- Every changed line must trace back to the current phase or an administrator request.

## Verification

- A phase is complete only after `./0d-scripts/verify.sh` and the phase `Verify:` commands in the ROADMAP pass.
- If the same category of verification failure cannot be fixed after 5 consecutive attempts, stop the repair loop and notify the administrator.
- During 0-to-1 development, local verification is the quality gate. Do not rely on remote CI.

## Notifications

- Use `./0d-scripts/notify-admin.sh` for phase completion, blockers, required decisions, and final completion.
- The project notification script is authoritative. Do not replace it with system-level notifiers unless the administrator explicitly authorizes the fallback. Project Feishu config: `~/.config/nm-docs/nm-notify-feishu.env`.
- Notification failure must not be silently treated as success.

## Safety And Stop Conditions

- Never overwrite uncommitted user changes. No destructive git operations unless explicitly requested.
- When files must be deleted, move them to `.delete-pending/` and wait for administrator confirmation.
- Stop and notify the administrator on: Spec conflicts without a conservative answer, scope expansion, need for real external accounts, paid resources, or production secrets or data, destructive migrations or irreversible operations, or `dev` merge conflicts that cannot be resolved safely.
