# Branching (NM V5)

## Branches

| Branch | Role |
| --- | --- |
| `main` / `master` | Stable release only |
| `dev` | Integration baseline for day-to-day work |
| `feature/*`, `fix/*`, `docs/*`, `refactor/*`, `chore/*`, `task/*` | Work branches from **dev** |
| `hotfix/*` | Urgent production fix from **main** only |

## Hard rules

1. Except hotfix: **do not** create work branches from `main`/`master`.
2. **Do not** commit implementation directly on `dev`. Always branch from latest `dev`.
3. Before starting the next work unit: **merge into `dev` and sync**. Merge method (merge commit, squash, ff) is agent judgment based on history cleanliness and conflict risk.
4. After merge, **evaluate** deleting the work branch if fully merged and not needed for review. Never auto-delete protected branches (`main`, `dev`, `release/*`, `hotfix/*`, unmerged, in-review).
5. Index/task bookkeeping may land via the same work branch merge; do not use direct `dev` commits as a loophole for large implementation.

## Suggested flow per Task

```text
git fetch
git switch dev && git pull --ff-only
git switch -c task/TASK-P01-01
# ... implement + verify ...
# merge back to dev (PR or local merge per project norms)
# delete work branch if safe
```

## Conflicts

If merge to `dev` is unsafe: stop, set blocked, emit `git_conflict`, do not force-push.
