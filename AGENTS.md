# Repository Agent Rules

This repository maintains reusable NotMaster workflow templates, skills, and deterministic tooling. Keep changes precise, versioned, and easy for other agents to execute.
For the Simplified Chinese administrator review copy, see `AGENTS.zh-CN.md`.

## Language And Documentation

- Write root-facing documentation in English by default.
- Provide Simplified Chinese translations for major user-facing docs under `docs/`.
- When changing this file, update `AGENTS.zh-CN.md` in the same change.
- Keep `README.md` focused on the recommended workflow version.
- Put previous versions, installation details, and migration notes in `docs/`.
- Keep agent-facing rules concise. Do not turn `AGENTS.md` into a full manual.

## Branching

- Use `dev` as the integration branch.
- Do not develop directly on `main`.
- Use task branches such as `feature/*`, `fix/*`, `docs/*`, `refactor/*`, or `chore/*`.
- Use `hotfix/*` only for urgent production fixes, and create it from `main`.
- Before merging back to `dev`, local verification must pass and the administrator must accept the work.
- Merge to `main` only when the user explicitly asks for a release or stable update.
- After a branch is merged, evaluate whether to clean it up. Never auto-delete `main`, `dev`, `release/*`, `hotfix/*`, unmerged branches, or branches still under review, acceptance, release, or rollback responsibility.

## Execution Quality

- Before starting a non-trivial task, state assumptions, risks, and success criteria.
- If a request has multiple reasonable interpretations, ask the administrator instead of choosing silently.
- Prefer the simplest implementation that satisfies the request. Do not add unrequested features, abstractions, or configuration.
- Keep changes surgical. Do not opportunistically refactor, reformat, or clean up unrelated code.
- Every changed line should trace back to the administrator request.

## Template Rules

- Treat `template/v3/manifest.json` as the source of truth for V3 template files.
- When adding or renaming V3 template files, update `manifest.json`, `PROJECT_STRUCTURE.md`, and `README.md`.
- Keep V3 files self-contained; generated projects should pass `npm run workflow:check` and `npm run verify`.
- Do not remove old template versions unless the user explicitly asks.

## Skill Rules

- Store repository-maintained skills under `skills/<skill-name>/`.
- Every skill must include a valid `SKILL.md` with concise trigger-oriented frontmatter.
- Put deterministic operations in `tools/` or `skills/<skill-name>/scripts/`; do not rely on prose for fragile file synchronization.
- Keep skill reference files one level below the skill and load them only when needed.
- Do not include unrelated README, changelog, or guide files inside skill folders.

## Tooling Rules

- Prefer deterministic scripts for init, update, audit, install, and validation operations.
- Existing-project update tools must require Git, check the working tree, create a branch, then write files.
- Do not silently discard project-specific guidance during migration. Preserve durable information in the appropriate V3 document.

## Safety

- Do not overwrite uncommitted user changes.
- Do not run destructive Git operations unless the administrator explicitly requests them.
- Before deleting any local or remote branch, confirm the working tree is clean and report the merge proof, branch role, and exact delete command.
- When files need to be deleted, prefer moving them to `.delete-pending/` and wait for administrator confirmation.

## Validation

- Run `npm run lm` after Markdown changes.
- Run `python3 tools/nm-v3/nm_v3.py check --target template/v3 --source-dir .` after V3 template or tool changes.
- Run the skill validator after editing skills:

```bash
python3 /Users/jango/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/nm-init-project-v3
```
