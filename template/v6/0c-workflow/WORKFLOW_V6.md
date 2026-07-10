# NM V6 Workflow

English | [简体中文](WORKFLOW_V6.zh-CN.md)

## Authority

V6 uses one SQLite database at `.nm/runtime/v6/state.sqlite3`. Append-only
lifecycle events are canonical; current tables and human projections are
rebuildable. The reducer is the only state writer. Agents, adapters, action
processes, notifications, and exit codes only propose or observe facts.

## Lifecycle

```text
DISCOVERING -> SPEC_DRAFT -> SPEC_REVIEW -> SPEC_AWAITING_CONFIRMATION
-> SPEC_CONFIRMED -> PLANNING -> READY -> IMPLEMENTING
-> PHASE_VERIFYING -> [PHASE_AWAITING_ACCEPTANCE] -> INTEGRATING_DEV
-> INTEGRATION_VERIFYING -> RELEASE_READY -> [RELEASING]
-> RELEASE_VERIFIED -> DEPLOY_READY -> [DEPLOYING]
-> [POST_DEPLOY_VERIFYING] -> COMPLETED
```

Brackets mark a stage that may be bypassed only by its explicit workflow rule:
auto Phase continuation, or a confirmed `not_applicable` release/deploy
decision. Every path to `COMPLETED` still requires `COMPLETION_GATE`.

Hotfixes use the separate stable-based path and must reconcile the exact effect
back into `dev`. Deployment failure enters rollback or attention; successful
rollback ends in `ROLLED_BACK`, never `COMPLETED`.

## Gates and evidence

The core independently executes configured checks in an isolated candidate.
Evidence receipts bind Spec/config hashes, commits, actions, stored redacted
output digests, artifacts, environments, operation IDs, evaluator versions,
and time. A missing or corrupt blob invalidates its receipt.

Protected and external mutations require both:

1. the applicable technical pre-action gate; and
2. a persisted staged approval or exact scoped auto grant.

Result gates re-observe protected refs, tags, releases, artifacts, deployments,
and rollback targets. Approval permits an operation; it cannot make a failed
technical gate pass.

## Work and Git

- Ordinary work starts at the exact fetched remote-tracking `dev` revision on
  `feature/*`, `fix/*`, `docs/*`, `refactor/*`, `chore/*`, or `task/*`.
- Workers receive standalone clones with no authoritative Git metadata,
  protected-ref credentials, or runtime database.
- Task candidates are verified and combined into a Phase candidate. Only the
  deterministic integrator may update `dev` after target CAS and verification.
- An AI reviewer proposes fast-forward, squash, or merge commit. The controller
  validates the resulting tree and executes only an authorized proposal.
- Cleanup uses an evidence-backed `delete_local`, `retain`, or
  `request_administrator` decision. Remote deletion always needs a new grant.

## Modes

`staged` and `auto` use the same transitions, gates, evidence, retries, Git
policy, and permission boundaries. They differ only in approval source and
continuation. An auto grant is signed, persisted, revocable, expiring, and bound
to one run, Spec/config hashes, action set, protected refs, and environments.

## Interruptions

Every external mutation persists its Operation ID before invocation. After a
timeout, malformed result, process loss, controller restart, pause, cancel, or
revocation, the recovery controller observes external state and classifies the
operation as completed, not started, partial, failed, or unknown. Retry occurs
only after reconciliation. Unknown effects enter `ATTENTION_REQUIRED`.

## Runtime dispatcher and background controller

The generated CLI always composes a configured dispatcher, durable child
launcher, and observed-state reconciler. `run --once` either advances one
ungated deterministic edge or reports the exact gate, authorization, worker
result, or administrator input it is waiting for. A missing dispatcher is not a
valid waiting state.

`run --detach` journals controller identity and status in the canonical SQLite
event chain before launching an external child. Files under
`.nm/runtime/v6/controllers/` are disposable projections marked
`authoritative: false`; deletion or tampering cannot change launch, recovery,
or workflow status semantics. No thread or PID is runtime truth.

`workflow:test` creates a disposable database, repository, local bare remote,
and isolated workspaces. It executes every configured fake action through the
scheduler, reducer, gates, Git, delivery, and recovery controllers, including
partial/unknown observation and reconciliation plus independently verified
rollback. It refuses non-fake secret providers and fails when an action cannot
execute.

## Project responsibilities

The project supplies complete JSON action definitions, verification commands,
environment identity probes, named secret references, and safe release/deploy/
rollback implementations. V6 supplies ordering, gates, authorization, evidence,
isolation, audit, recovery, and the durable notification outbox.
