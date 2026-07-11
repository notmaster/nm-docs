# Branching

## Protected Branches

- `main` or `master`: stable.
- `dev`: integration.
- No ordinary file modification is allowed while a protected branch is checked
  out. An explicitly classified `hotfix/*` is the only production-fix path.

## Ordinary Preflight

Before writing:

```bash
git status --short
git fetch --prune origin dev
git rev-parse dev
git rev-parse origin/dev
```

Stop if the tree is dirty, fetch fails, `origin/dev` is unavailable, local
`dev` differs from `origin/dev`, or the remote state is otherwise unknown.

## Branch Topology

Planned work:

```text
origin/dev
└── feature/plan-p001-slug
    ├── task/goal-p001-g001-slug
    ├── task/goal-p001-g002-slug
    └── task/goal-p001-g003-slug
```

Standalone work:

```text
origin/dev
└── task/goal-g001-slug
```

Goals are serial. A later Goal starts from the Plan head after the previous Goal
is integrated. V3.1 does not run parallel active Goals.

## Local Goal Integration

Goal-to-Plan integration is local automation and is permitted by an active
`Execute Plan <id>` instruction only when:

- Goal-specific verification passed;
- the configured self-review or independent review passed;
- the main agent inspected the returned report and diff;
- no stop condition remains;
- the expected Plan branch head has not moved.

Choose fast-forward, squash, or merge commit according to topology, commit
quality, audit value, conflict risk, and rollback needs. Record the strategy,
source/target SHAs, and result tree.

## Protected Integration

Plan-to-`dev`, protected push, and stable promotion always require explicit
administrator authorization. Re-fetch the target immediately before each
mutation. A previous instruction remains conditional on the target SHA and
verification; moved refs invalidate the old candidate evidence.

Never force-push a protected ref. Never merge a Plan branch directly into
stable; stable is promoted from the verified `dev` result.

## Hotfix

An administrator must explicitly classify a hotfix. Create `hotfix/*` from the
latest remote stable SHA, verify it, integrate it into stable only with explicit
authorization, then reconcile the exact fix into `dev` and reverify. Retain the
hotfix branch through release and rollback responsibility.

## Cleanup

- A completed Goal Worktree may be removed after its agent stopped and its
  commits are safely integrated.
- Retain Goal branches until Plan acceptance and `dev` integration.
- Delete a local short-lived branch only with exact-head ancestry or equivalent
  squash/tree proof and no remaining review, backup, dependency, release, or
  rollback responsibility.
- Never auto-delete protected, release, hotfix, unmerged, or active branches.
- Remote branch deletion requires a new explicit administrator instruction.
