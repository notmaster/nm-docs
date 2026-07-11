# Verification

## Workflow Structure

Run:

```bash
npm run workflow:check
```

This validates core files, project references, optional spec metadata, Plan and
Goal names/frontmatter, state prerequisites, protected-branch dirtiness, and
notification entry points.

## Goal Verification

Each Goal declares the smallest complete commands that prove its own acceptance
criteria. The implementation child agent writes tests, runs those commands, and
self-reviews by default. An independent reviewer runs only when the Goal was
configured before execution with:

```yaml
review:
  independent_reviewer_required: true
```

Goal verification does not run the full project verification unless the Goal
explicitly requires it.

## Full Verification

After every Goal is integrated into the Plan branch, run once:

```bash
./0d-scripts/verify.sh
```

The command must run `workflow:check` plus the complete project lint, typecheck,
test, build, and other required checks. A Plan cannot enter `awaiting_review`
until this exact integrated result passes.

## Evidence

Record:

- exact commands;
- `pass`, `fail`, or `not-run`;
- concise failure summary and repair count;
- tested commit/tree SHA;
- self-review or independent-review result;
- skipped checks and reasons.

Do not copy raw terminal logs, credentials, webhook values, production data, or
other secrets into Plan/Goal files.

Record the Goal test commit in `verification_commit`, the Goal-to-Plan result in
`integration_commit`, and the final Plan test commit in
`full_verification_commit`. Status text without these bindings is insufficient.

## Manual Acceptance

Keep these separate:

- automated verification;
- agent review;
- administrator acceptance.

UI, product judgment, wording, and real external-service behavior may include
screenshots, preview URLs, or a checklist, but remain
`awaiting_administrator` until the administrator decides.
