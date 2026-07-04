# Repository Agent Rules

This repository maintains reusable NotMaster workflow templates, skills, and deterministic tooling. Keep changes precise, versioned, and easy for other agents to execute.

## Language And Documentation

- Write root-facing documentation in English by default.
- Provide Simplified Chinese translations for major user-facing docs under `docs/`.
- Keep `README.md` focused on the recommended workflow version.
- Put previous versions, installation details, and migration notes in `docs/`.
- Keep agent-facing rules concise. Do not turn `AGENTS.md` into a full manual.

## Branching

- Use `dev` as the integration branch.
- Do not develop directly on `main`.
- Use task branches such as `feature/*`, `fix/*`, `docs/*`, `refactor/*`, or `chore/*`.
- Merge to `main` only when the user explicitly asks for a release or stable update.

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

## Validation

- Run `npm run lm` after Markdown changes.
- Run `python3 tools/nm-v3/nm_v3.py check --target template/v3 --source-dir .` after V3 template or tool changes.
- Run the skill validator after editing skills:

```bash
python3 /Users/jango/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/nm-init-project-v3
```
