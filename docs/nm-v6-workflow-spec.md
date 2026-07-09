---
spec_id: SPEC-NM-WORKFLOW-V6-V1
document_title: NM V6 Workflow
status: review-ready
version: 1
workflow: v6
language: en
normative: true
admin_mirror: nm-v6-workflow-spec.zh-CN.md
implementation_authorized: false
---

# NM V6 Workflow Specification

English | [中文](nm-v6-workflow-spec.zh-CN.md)

## 1. Document control and authority

This document is the normative implementation and acceptance contract for NM
V6. It is written for an AI implementation agent and an independent acceptance
agent.

The words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative.

- The English document is the agent execution source. The Simplified Chinese
  mirror is a complete administrator review copy.
- Requirement and acceptance identifiers are stable. Removed identifiers MUST
  be marked `retired` and MUST NOT be reused.
- A behavioral change MUST increment `version` and produce a new content hash.
- No generated file, prompt, adapter, project configuration, or runtime record
  may weaken this Spec.
- While `status` is `review-ready` and `implementation_authorized` is `false`,
  agents MAY review this Spec but MUST NOT start V6 implementation merely
  because the file exists.
- Implementation begins only after the administrator changes the status to
  `confirmed` and authorizes implementation, or gives equivalent explicit
  instructions in the implementation task.
- After confirmation, an implementation conflict with this Spec is a hard stop;
  the agent MUST request a versioned Spec amendment instead of silently choosing
  new behavior.

### 1.1 Canonical Spec hash

The normative `spec_hash` is lowercase SHA-256 over these bytes:

1. Parse the English frontmatter and construct one mapping named `metadata`
   containing exactly the keys `spec_id`, `document_title`, `version`,
   `workflow`, `language`, `normative`, and `admin_mirror` with their parsed
   values. A selected key missing, or an English frontmatter key other than
   those seven plus `status`, `implementation_authorized`, or `content_hash`,
   fails validation.
2. Set `metadata_bytes` to
   `json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")`.
3. The body starts with the first character after the line terminator of the
   closing frontmatter `---` line. Convert CRLF and lone CR to LF, remove all
   trailing LF characters, append exactly one LF, encode as UTF-8 without a BOM,
   and perform no Unicode normalization; call the result `body_bytes`.
4. Hash `metadata_bytes + b"\n---body---\n" + body_bytes`.

`status`, `implementation_authorized`, a displayed `content_hash`, and all
confirmation/authorization records are excluded. Their changes therefore do
not change normative content identity. The validator MUST calculate the hash;
it MUST NOT trust a hash copied into the document.

Spec confirmation and implementation authorization are separate immutable
trusted control-plane records that reference `spec_id`, `version`, and
`spec_hash`. Frontmatter status fields are review hints and are not sufficient
authorization for the runtime core.

A confirmation record contains `confirmation_id`, `spec_id`, `version`,
`spec_hash`, `decision: confirmed`, administrator identity, issue time, nonce,
authenticator ID, and signature/MAC. An implementation-authorization record
additionally names the implementation task/scope and expiry. Both use the trust
boundary in Section 12.1.

## 2. Problem and objective

NM V6 MUST provide a minimal reliable closed-loop workflow for long-running,
interruptible AI-assisted projects. The loop covers:

1. goal discovery and requirement clarification;
2. confirmed specification and implementation planning;
3. isolated implementation;
4. independent verification and acceptance;
5. integration into `dev`;
6. promotion from `dev` to the stable branch;
7. release and publication;
8. deployment and post-deployment verification;
9. failure reconciliation and rollback.

The same platform-neutral semantics MUST support:

- Codex, GrokBuild, and Claude Code;
- `staged` and `auto` modes;
- one agent or multiple agents;
- foreground or background execution.

V6 is a redesign from the target outcome. It is not constrained by V5 file,
command, runtime-state, or generated-project compatibility.

## 3. Scope

### 3.1 In scope

- Versioned Goals, Requirements, Acceptance criteria, Decisions, Phases, Tasks,
  Attempts, Evidence, Gates, Operations, and approvals.
- A transactional disk-backed state machine, deterministic reducer, scheduler,
  gate evaluator, evidence store, and recovery controller.
- Thin agent adapters for Codex, GrokBuild, and Claude Code.
- Isolated candidate workspaces, single/multi-agent scheduling, background
  supervision, concurrency control, and stale-result rejection.
- Git branch protection, integration, promotion, push policy, merge-strategy
  decisions, and branch-cleanup decisions.
- Project-supplied verification, build, release, publish, deploy, health, and
  rollback actions.
- Environment confirmation, credential boundaries, idempotency, audit records,
  notification outbox, and observed-state reconciliation.
- Static contract checks and executable normal, abnormal, concurrent, and crash
  recovery acceptance scenarios.
- A V6 template, deterministic CLI/core, thin Skill, concise English agent
  rules, and complete Simplified Chinese administrator documentation.

### 3.2 Non-goals

- Compatibility with V5 runtime files, commands, or generated projects.
- Automatic migration or resumption of an in-progress V5 run.
- A general-purpose agent operating system or hosted orchestration service.
- Reimplementing every provider-native subagent feature behind one artificial
  universal API.
- Provisioning project infrastructure, commands, environments, credentials, or
  rollback targets. The project supplies them; V6 validates and orchestrates
  them.
- Treating model judgment, process exit code, or a prompt instruction as proof
  that a deterministic gate passed.
- Exhaustively testing every model version and execution-mode combination.
- Keeping provider manuals, recovery playbooks, historical reports, or the full
  repository in permanent model context.
- Physical deletion of project files. The repository `.delete-pending/` policy
  remains in force unless a later administrator resolution changes it.
- Using real production release, deployment, notification, or credentials in
  V6's mandatory acceptance suite.

## 4. Assumptions and fixed design decisions

| ID | Decision |
| --- | --- |
| `V6-DEC-001` | Projects provide concrete command actions, environment identity probes, configuration, and credential references. V6 owns ordering, authorization, gates, evidence, and recovery. |
| `V6-DEC-002` | The reference core runs on Python 3.11 or newer and uses the standard-library `sqlite3` module. Adding a mandatory runtime service or non-standard runtime dependency requires an administrator-approved Spec amendment. |
| `V6-DEC-003` | One local SQLite database in the authoritative checkout is the transactional runtime authority. Append-only lifecycle events are canonical inside that database; current-state tables are updated in the same transaction and are rebuildable materialized views. JSON, YAML, Markdown, prompts, notifications, and conversations are not runtime truth. |
| `V6-DEC-004` | `main` or `master` is the configurable stable branch; new projects default to `main`. The integration branch is fixed as `dev`. Stable and `dev` MUST differ. |
| `V6-DEC-005` | Even for a hotfix, AI MUST NOT edit or commit directly on the stable branch. A hotfix uses `hotfix/*` from the exact stable revision, then gated integration to stable and reconciliation into `dev`. |
| `V6-DEC-006` | Normal work branches are local by default. The remote normally carries stable and `dev`; any other branch is pushed only under an explicit administrator backup or review grant. |
| `V6-DEC-007` | Local branches may be automatically deleted only after an evidence-backed cleanup decision. Remote branch deletion always requires explicit administrator authorization. |
| `V6-DEC-008` | The default integration unit is a Phase candidate. Task candidates may be combined on an ephemeral Phase integration branch; unaccepted staged work MUST NOT enter `dev`. A project MAY configure Task-level integration only if the same Phase acceptance semantics remain enforceable. |
| `V6-DEC-009` | Selecting `auto` is administrator authorization for the persisted, displayed scope. After a required gate passes, the deterministic controller may automatically merge, release, publish, deploy, or roll back only within that scope. |

## 5. Normative invariants

| ID | Invariant |
| --- | --- |
| `V6-INV-001` | A single transactional core store is the only mutable workflow truth. |
| `V6-INV-002` | Only the deterministic reducer may commit workflow state transitions. Agents and adapters return proposals or observations. |
| `V6-INV-003` | A hard gate passes only from evidence independently collected or verified by the core. Agent self-report is advisory only. |
| `V6-INV-004` | `staged` and `auto` share one state graph, gate definitions, evidence rules, Git rules, permission model, and action adapters. They differ only in approval source and continuation policy. |
| `V6-INV-005` | `auto` authorization is explicit, persisted, revocable, and limited to one run, Spec hash, configuration hash, action set, protected-ref set, and environment set. |
| `V6-INV-006` | AI workers never receive protected-branch write authority, remote push credentials, release/deploy credentials, or direct state-store write access. |
| `V6-INV-007` | Except for the hotfix flow, every implementation branch originates from the latest verified `dev` revision recorded for its work unit. |
| `V6-INV-008` | No AI worker edits, commits on, resets, rebases, or force-pushes `main`, `master`, or `dev`. Only authorized deterministic actions may update protected refs after their gates pass. |
| `V6-INV-009` | A normal release records an exact independently verified source `dev` revision and produces a stable tree exactly equal to that verified tree. Ordinary work branches never merge directly to stable. |
| `V6-INV-010` | Concurrent work uses isolated workspaces, leases, fencing tokens, expected revisions, idempotency keys, and serialized protected-branch integration. |
| `V6-INV-011` | An interrupted external operation is reconciled against observed external state before retry. Exit code zero alone never proves progress. |
| `V6-INV-012` | Release and deployment evidence binds the confirmed Spec hash, source commit, artifact digest, configuration hash, target environment identity, and operation ID. |
| `V6-INV-013` | Secrets are referenced by name and injected only into the minimum deterministic action that needs them. They never enter agent context, projections, notifications, or ordinary logs. |
| `V6-INV-014` | Always-loaded instructions contain only correctness and safety invariants. Platform recipes, diagnostics, and recovery procedures load on demand. |
| `V6-INV-015` | A run cannot become `COMPLETED` while a mandatory Acceptance criterion lacks valid evidence or a required delivery stage was silently skipped. |
| `V6-INV-016` | Rules in `AGENTS.md`, `CLAUDE.md`, prompts, Skills, or model memory are context, not an enforcement boundary. Core policy MUST remain effective when an agent ignores them. |

## 6. Required architecture

The platform-neutral implementation MUST contain these components:

1. **Contract validator** — validates the Spec, project configuration, adapter
   configuration, identifiers, traceability, action definitions, manifests, and
   bilingual documentation contract.
2. **Transactional state store** — owns the SQLite schema, migrations,
   append-only event journal, current materialized state, leases, grants,
   evidence metadata, and outbox.
3. **Reducer** — the only state-transition writer. It validates expected run
   revision, transition type, actor, authorization, idempotency key,
   prerequisites, evidence references, and any fencing token in one transaction.
4. **Scheduler** — selects ready work from the Task DAG and respects dependency,
   write-set, concurrency, lease, and integration constraints.
5. **Agent adapter host** — maps one versioned request/result protocol to each
   supported CLI without leaking provider-specific flags into the core.
6. **Workspace manager** — creates disposable isolated candidate workspaces and
   imports candidate output only after policy validation.
7. **Gate executor** — independently runs configured checks and creates evidence
   receipts. It does not trust the worker's report.
8. **Git integration controller** — validates ancestry and candidate output,
   receives an AI merge-strategy proposal, enforces policy, performs the
   authorized operation, and records integration and cleanup receipts.
9. **Delivery controller** — builds immutable artifacts and invokes project
   release, publish, deploy, health, and rollback actions.
10. **Recovery controller** — reconciles interrupted agent, Git, remote,
    release, deployment, and rollback operations with observed external state.
11. **Audit and notification outbox** — persists audit events and notification
    intent before delivery. Notification failure never changes a business gate.

Workers MUST NOT invoke the reducer, mutate its database, update protected Git
refs, push a remote, or run a credentialed delivery action.

## 7. Identifiers and traceability

### 7.1 Identifier classes

| Entity | Format |
| --- | --- |
| Goal | `GOAL-<NNN>` |
| Requirement | `REQ-<NNN>` |
| Acceptance criterion | `AC-<NNN>` |
| Decision | `DEC-<NNN>` |
| Phase | `PHASE-<NNN>` |
| Task | `TASK-<NNN>` |
| Attempt | `ATTEMPT-<run-id>-<NNN>` |
| Evidence | `EVID-<run-id>-<NNN>` |
| Gate decision | `GATE-<run-id>-<NNN>` |
| External operation | `OP-<run-id>-<NNN>` |
| Approval or grant | `AUTH-<run-id>-<NNN>` |

Identifiers MUST remain stable across textual edits. A superseded entity keeps
its identifier and records its replacement.

These formats apply to project Specs. This workflow meta-Spec uses the distinct
`V6-DEC-*`, `V6-INV-*`, `V6-REQ-*`, and `V6-AC-*` namespaces.

### 7.2 Required traceability

- Every confirmed Requirement MUST trace to at least one Goal.
- Every mandatory Acceptance criterion MUST trace to at least one Requirement.
- Every Acceptance criterion MUST declare `required_by_stage` as one of
  `task`, `phase`, `dev_integration`, `release`, `deploy`, or `completion`.
  Earlier gates check only the mandatory criteria due by that stage;
  `COMPLETION_GATE` checks all mandatory criteria.
- Every Task MUST trace to one or more Acceptance criteria or an explicitly
  identified enabling Requirement.
- Every passed gate MUST cite valid evidence receipts.
- `COMPLETED` requires valid evidence coverage for every mandatory Acceptance
  criterion.
- A skipped optional Task MUST prove that it does not leave a mandatory
  Acceptance criterion uncovered.
- A Spec amendment creates a new Spec hash and invalidates evidence whose
  subject, assumptions, commands, or expected result changed.
- Every `V6-DEC-*` and `V6-INV-*` MUST trace through at least one `V6-REQ-*` to
  executable Acceptance evidence. The coverage tables in Section 27 are
  normative.

## 8. Discovery and Spec lifecycle

The workflow MUST support requirement discovery rather than assume a finished
request.

```text
DISCOVERING
  -> SPEC_DRAFT
  -> SPEC_REVIEW
  -> SPEC_AWAITING_CONFIRMATION
  -> SPEC_CONFIRMED
  -> PLANNING
```

Discovery records MUST contain:

- requested outcome;
- constraints and assumptions;
- open questions and administrator decisions;
- identified risks;
- success and failure conditions.

A confirmed project Spec MUST contain:

- immutable document version and content hash;
- administrator confirmation identity and timestamp;
- Goal, Requirement, and Acceptance IDs;
- mandatory/optional classification and `required_by_stage` for every
  Acceptance criterion;
- required delivery stages;
- target environments or an explicit `not_applicable` decision;
- safety constraints and non-goals;
- acceptance actions or project-profile references.

A confirmed Spec is immutable. A semantic change creates a new version and
requires impact analysis before execution resumes.

## 9. Canonical state and persistence

### 9.1 Storage rules

- The reference database location is `.nm/runtime/v6/state.sqlite3` in the
  authoritative checkout. `.nm/runtime/` MUST be ignored by Git and excluded
  from worker workspaces.
- SQLite Write-Ahead Logging, foreign-key enforcement, `synchronous=FULL`, and a
  bounded busy timeout MUST be enabled. Startup and crash recovery MUST run an
  integrity check before advancing state.
- Append-only lifecycle events in the database are canonical. A transition
  transaction MUST insert exactly one logical event and update its materialized
  state, audit references, and outbox intent atomically.
- Human-readable status, issues, task reports, and audit exports are disposable
  projections. Each MUST declare the last projected event sequence and be
  reproducible from the database.
- Project Specs and immutable Task definitions are versioned inputs, not mutable
  runtime truth.
- Every run has a monotonic revision. State writes use compare-and-swap.
- Each external operation has a globally unique idempotency key.
- A stale revision, lease, operation result, or fencing token MUST be rejected.
- Schema migrations are versioned, transactional, forward-only, backed up
  before application, and covered by fixture tests.
- A redacted evidence blob is written to a same-filesystem temporary path,
  flushed and fsynced, atomically renamed to its digest path, and only then
  referenced by a committed database receipt. Directory metadata is fsynced
  where the platform supports it. A receipt whose blob is absent or has the
  wrong digest is invalid. Unreferenced blobs are quarantined and garbage
  collected only after a configured grace period; recovery never invents a
  receipt for an orphan.

### 9.2 Minimum logical records

The schema MUST represent at least:

- runs and revisions;
- immutable Spec/configuration snapshots and hashes;
- Goals, Requirements, Acceptance criteria, Decisions, Phases, and Tasks;
- dependencies and declared write sets;
- attempts, sessions, processes, workspaces, leases, and fencing tokens;
- evidence receipts and content-addressed raw-output references;
- gate decisions and approvals/auto grants;
- Git branches, commits, merge proposals, integrations, pushes, and cleanup
  decisions;
- artifacts, releases, deployments, environment observations, health checks,
  and rollbacks;
- append-only events, reconciliation records, audit records, and notification
  outbox items.

### 9.3 Run states

```text
DISCOVERING
SPEC_DRAFT
SPEC_REVIEW
SPEC_AWAITING_CONFIRMATION
SPEC_CONFIRMED
PLANNING
READY
IMPLEMENTING
PHASE_VERIFYING
PHASE_AWAITING_ACCEPTANCE
INTEGRATING_DEV
INTEGRATION_VERIFYING
HOTFIX_IMPLEMENTING
HOTFIX_VERIFYING
HOTFIX_INTEGRATING_STABLE
HOTFIX_STABLE_VERIFYING
HOTFIX_RECONCILING_DEV
HOTFIX_DEV_VERIFYING
RELEASE_READY
RELEASING
RELEASE_VERIFIED
DEPLOY_READY
DEPLOYING
POST_DEPLOY_VERIFYING
COMPLETED

PAUSED
ATTENTION_REQUIRED
ROLLBACK_REQUIRED
ROLLING_BACK
POST_ROLLBACK_VERIFYING
ROLLED_BACK
FAILED
CANCELLED
```

Allowed success-path transitions are:

```text
DISCOVERING -> SPEC_DRAFT -> SPEC_REVIEW -> SPEC_AWAITING_CONFIRMATION
SPEC_AWAITING_CONFIRMATION -> SPEC_CONFIRMED -> PLANNING -> READY
READY -> IMPLEMENTING -> PHASE_VERIFYING
PHASE_VERIFYING -> PHASE_AWAITING_ACCEPTANCE -> INTEGRATING_DEV  # staged
PHASE_VERIFYING -> INTEGRATING_DEV                               # auto
INTEGRATING_DEV -> INTEGRATION_VERIFYING
INTEGRATION_VERIFYING -> IMPLEMENTING                            # more Phases
INTEGRATION_VERIFYING -> RELEASE_READY                           # all Phases done
RELEASE_READY -> RELEASING -> RELEASE_VERIFIED                   # release required
RELEASE_READY -> RELEASE_VERIFIED                                # release not applicable
RELEASE_VERIFIED -> DEPLOY_READY
DEPLOY_READY -> DEPLOYING -> POST_DEPLOY_VERIFYING -> COMPLETED  # deploy required
DEPLOY_READY -> COMPLETED                                        # deploy not applicable

READY -> HOTFIX_IMPLEMENTING -> HOTFIX_VERIFYING                 # hotfix run
HOTFIX_VERIFYING -> HOTFIX_INTEGRATING_STABLE
HOTFIX_INTEGRATING_STABLE -> HOTFIX_STABLE_VERIFYING
HOTFIX_STABLE_VERIFYING -> HOTFIX_RECONCILING_DEV
HOTFIX_RECONCILING_DEV -> HOTFIX_DEV_VERIFYING -> RELEASE_READY
```

`SPEC_REVIEW` MAY return to `SPEC_DRAFT`, and rejected confirmation MAY return
to `SPEC_REVIEW`. A failed Phase check MAY return to `IMPLEMENTING` only through
a recorded repair decision. A hotfix path requires `run_kind: hotfix` and the
administrator's trusted hotfix authorization. The two direct not-applicable edges require their
stage gate to record `not_applicable`; every edge to `COMPLETED` also requires
`COMPLETION_GATE`.

Any nonterminal operational state MAY request `PAUSED` or
`ATTENTION_REQUIRED` after fencing active actors and recording its resume state.
An external-mutation state such as release, deployment, or rollback MUST reach a
reconciled safe point before it becomes `PAUSED`. Resume returns only to the
validated state after reconciliation. A deployment failure follows
`ROLLBACK_REQUIRED -> ROLLING_BACK -> POST_ROLLBACK_VERIFYING -> ROLLED_BACK`; an
unrecoverable failure enters `FAILED`. `COMPLETED`, `ROLLED_BACK`, `FAILED`, and
`CANCELLED` are terminal. Cancellation reaches `CANCELLED` only after active
external Operations are cancelled or reconciled.

The implementation MUST encode a versioned transition table whose rows contain
`from_state`, `event`, `guard`, `required_gate`, `required_authorization`, and
`to_state`. Every transition not listed in that table is invalid. The table MUST
cover confirmation rejection, Phase acceptance/rejection, repair, lease loss,
pause request, attention/resume, cancellation, external-operation unknown, and
rollback outcomes. A rejected Phase returns to implementation only through a
recorded repair decision; a Spec rejection returns to review. A lost lease may
make a Task ready again only when fencing succeeded and no external mutation is
unreconciled.

`ATTENTION_REQUIRED` MUST retain a validated resume state, reason, required
decision, and current external observations. It is not a success state.

Normal stage ordering MUST NOT be bypassed. A delivery stage may be skipped only
when the confirmed Spec and corresponding gate explicitly record
`not_applicable`; absent configuration is not skip authorization.

### 9.4 Phase states

```text
PLANNED -> ACTIVE -> VERIFYING
VERIFYING -> AWAITING_ACCEPTANCE -> ACCEPTED -> INTEGRATED   # staged
VERIFYING -> ACCEPTED -> INTEGRATED                          # auto
ACTIVE|VERIFYING -> BLOCKED|CANCELLED
```

Phase `INTEGRATED` means the exact accepted Phase candidate passed
`DEV_INTEGRATION_GATE`, the controller updated the protected ref, and
`DEV_INTEGRATION_RESULT_GATE` proved both local and configured-remote `dev`
equal the authorized result.

### 9.5 Task states

```text
PLANNED -> READY -> LEASED -> RUNNING -> CANDIDATE
CANDIDATE -> VERIFYING -> VERIFIED -> INTEGRATED
RUNNING|VERIFYING -> RETRYABLE_FAILURE -> READY
RUNNING|VERIFYING -> BLOCKED|CANCELLED
READY|BLOCKED -> SKIPPED    # optional-only rule
```

An agent cannot directly create `VERIFIED`, `INTEGRATED`, or `SKIPPED`.
Task `INTEGRATED` means the verified Task candidate was incorporated into the
Phase candidate; it does not by itself mean the Task reached `dev`.

### 9.6 Attempt states

```text
CREATED -> DISPATCHED -> RUNNING -> COLLECTING
COLLECTING -> SUCCEEDED|FAILED|TIMED_OUT|CANCELLED|LOST
```

A process that exits successfully without a valid structured result becomes
`FAILED`, not `SUCCEEDED`.

## 10. Gate model

### 10.1 Gate receipt

Each decision MUST record:

- gate type and version;
- subject IDs;
- Spec and configuration hashes;
- source, candidate, and target commits where applicable;
- artifact digest and target environment identity where applicable;
- prerequisite decision IDs and evidence IDs;
- staged approval or auto-grant ID when the gate authorizes a protected or
  external mutation; technical-only gates record `null`;
- evaluator identity and version;
- result, reason, timestamp, and run revision.

### 10.2 Required gates

Delivery gates MAY return `not_applicable` only when the confirmed Spec contains
the matching explicit decision. In that case the gate validates the decision
and stage traceability instead of requiring an action-specific artifact or
environment. Missing configuration never implies `not_applicable`.

| Gate | Minimum prerequisites |
| --- | --- |
| `SPEC_GATE` | Schema valid; IDs unique; stage annotations and mandatory traceability complete; canonical Spec hash and trusted administrator confirmation record present. |
| `PLAN_GATE` | Task DAG valid and acyclic; mandatory Acceptance criteria covered; path bounds, actions, dependencies, and write sets declared. |
| `TASK_GATE` | Candidate diff within policy; candidate commit identified; Task acceptance independently rerun; no prohibited state or protected-ref mutation. |
| `PHASE_GATE` | Mandatory Phase Tasks verified; permitted skips recorded; combined candidate passes Phase verification. |
| `DEV_INTEGRATION_GATE` | Proposed target exactly `dev`; candidate lineage allowed; expected remote-tracking target unchanged; simulated result tree and merge proposal valid; full verification passes in an isolated candidate. |
| `DEV_INTEGRATION_RESULT_GATE` | Observed local and remote `dev` refs equal the authorized results; resulting tree equals the verified simulated tree; push receipt and post-update checks pass. |
| `HOTFIX_STABLE_GATE` | Trusted hotfix authorization present; `hotfix/*` base equals expected stable; simulated stable tree, proposal, independent verification, rollback ref, and unchanged target pass. |
| `HOTFIX_STABLE_RESULT_GATE` | Observed local and configured-remote stable refs equal the authorized CAS result; push receipt, resulting tree, and post-update checks pass. |
| `HOTFIX_RECONCILIATION_GATE` | Simulated `dev` reconciliation contains the exact hotfix effect; current remote `dev` is expected; affected verification and proposal pass. |
| `HOTFIX_RECONCILIATION_RESULT_GATE` | Observed local and configured-remote `dev` refs equal the authorized CAS result; push receipt proves it contains the exact hotfix effect, matches the authorized tree, and passes affected post-update verification. |
| `RELEASE_GATE` | `release_source_kind`, commit, and tree fixed to verified `dev` for normal release or verified hotfix stable for hotfix release; all criteria due by release covered; immutable artifact, stable-result tree, metadata, idempotency, observe/reconcile, rollback target, and any required hotfix-reconciliation receipt valid. |
| `RELEASE_RESULT_GATE` | Observed stable ref, tag, published release, and artifact digest match the authorized receipt; partial/unknown effects were reconciled. |
| `DEPLOY_GATE` | All mandatory criteria with `required_by_stage <= deploy` covered; artifact fixed; environment confirmed; credentials referenced; preflight, idempotency, observe/reconcile, and rollback readiness present. |
| `POST_DEPLOY_GATE` | Health, smoke, and project observations pass for the exact artifact and environment. |
| `ROLLBACK_GATE` | Rollback target exists; environment confirmed; rollback and post-rollback verification actions available. |
| `POST_ROLLBACK_GATE` | Observed environment equals the rollback target and post-rollback verification passes; otherwise the run cannot become `ROLLED_BACK`. |
| `COMPLETION_GATE` | Every mandatory Acceptance criterion has valid evidence; every Phase is integrated; release/deployment is successful or explicitly not applicable; no mandatory work or rollback responsibility remains unresolved. |

A failed gate MUST NOT be converted to success by an agent report, retry count,
notification, mode, approval, or process exit code. Approval permits an action;
it does not replace its technical gate.

## 11. Evidence model

A core-produced evidence receipt MUST contain at least:

```yaml
evidence_id:
evidence_type:
producer:
run_id:
subject_ids: []
spec_hash:
config_hash:
source_commit:
candidate_commit:
release_source_kind:
release_source_commit:
release_source_tree:
hotfix_reconciliation_gate_id:
artifact_digest:
environment_id:
environment_fingerprint:
operation_id:
attempt_id:
command_action_id:
argv_digest:
working_directory:
started_at:
finished_at:
exit_code:
result:
stdout_digest:
stderr_digest:
tool_versions: {}
redaction_version:
```

- Only successfully redacted output MAY be persisted in the content-addressed
  evidence directory. `stdout_digest` and `stderr_digest` identify the exact
  stored redacted bytes.
- An implementation MAY calculate a separately named `raw_stream_digest` while
  streaming, but MUST NOT retain or export the raw bytes. The raw digest does
  not replace the stored-content digest.
- If output cannot be reliably redacted, the core MUST discard it, mark evidence
  collection failed, and prevent the gate from passing.
- Evidence for a different Spec, configuration, commit, artifact, environment,
  action definition, or relevant toolchain fingerprint is invalid.
- Agent output MAY be stored as `advisory_observation`; it cannot alone satisfy
  a deterministic hard gate.
- Gate evaluation MUST re-check evidence validity at transition time.
- Evidence retention and redaction policy MUST be declared in project
  configuration. A receipt is complete only when all required binding fields,
  stored-content digests, producer/evaluator versions, and redaction version are
  present and validate.

## 12. `staged` and `auto` modes

### 12.1 Trusted administrator control plane

Administrator approval MUST originate from a control-plane capability that is
not available to an agent, worker workspace, adapter, project action, or agent
context. A caller-supplied `created_by` string is not proof.

The reference local flow is challenge based:

1. `authorize request` writes an immutable request containing a nonce, request
   digest, Spec/config hashes, exact scope, expected state revision, and expiry.
2. The administrator approves that digest through a separate authenticated TTY,
   OS-protected helper, or pre-created signed grant whose signing capability is
   inaccessible to agents.
3. `authorize approve` verifies the signature/MAC, identity, nonce, expiry,
   request digest, and current revision before storing a one-time or scoped
   authorization record.
4. `authorize revoke` creates a trusted revocation record.

The mandatory ordering for `auto` is
`SPEC_GATE -> PLAN_GATE -> display exact scope -> trusted administrator approval`.
Technical gates before protected mutation do not require an authorization ID.

Starting a protected or external Operation MUST atomically bind the current
grant revision and consume any one-time authorization. Revocation prevents
Operations that have not started. An already started Operation is fenced from
further steps and reconciled to a safe observed state; it is never reported as
cancelled merely because the grant was revoked.

### 12.2 Shared semantics

Mode MUST NOT change:

- state transitions or gate order;
- evidence requirements or acceptance commands;
- retry classification;
- Git protection or merge validation;
- secret access or environment confirmation;
- rollback readiness.

### 12.3 `staged`

`staged` requires a persisted administrator approval at each configured
approval point. At minimum, approval is required before:

- integrating an accepted Phase candidate into `dev`;
- promoting `dev` to stable, tagging, or publishing a release;
- deploying to each protected environment;
- rolling back unless a previously approved emergency policy covers it.

No protected ref or external environment changes before the applicable approval
exists.

### 12.4 `auto`

Selecting `auto` through the trusted control plane is the administrator
authorization event. Before approval, the CLI MUST display the exact scope. The
verified grant contains:

```yaml
grant_id:
run_id:
spec_hash:
config_hash:
allowed_actions: []
allowed_environments: []
allowed_protected_refs: []
created_by:
created_at:
expires_at:
revoked_at:
request_digest:
nonce:
grant_revision:
authenticator_id:
authenticator_signature:
```

The grant:

- is limited to one run, Spec hash, configuration hash, named actions,
  environments, and protected refs;
- expires on completion, cancellation, revocation, timeout, Spec change, or a
  relevant configuration change;
- permits automatic merge, promotion, release, publication, deployment, and
  rollback only after the corresponding gates pass;
- never grants those credentials or operations to an AI worker;
- converts any out-of-scope action into `ATTENTION_REQUIRED` instead of silently
  broadening authority.

Changing mode is a persisted transition. In-flight actions MUST first be
cancelled or reconciled. A CLI-only override that is not persisted is invalid.

## 13. Roles and permission boundaries

| Role or component | Allowed | Forbidden |
| --- | --- | --- |
| Inspector | Read declared repository paths and projections | Writes, credentials, transitions |
| Planner agent | Propose plan, Tasks, context, and risks | Runtime transitions, protected refs |
| Worker agent | Modify disposable candidate workspace and run unprivileged Task actions | State database, protected refs, push, release/deploy credentials |
| Review agent | Inspect candidate and return advisory findings | Passing deterministic gates |
| Gate executor | Run unprivileged configured checks in a disposable candidate and return evidence | Protected refs, delivery credentials, direct state writes, arbitrary implementation edits |
| Git integrator | Execute a validated proposal after authorization | Arbitrary implementation edits, deployment |
| Release action | Build, tag, and publish the exact authorized artifact | General repository editing, deployment |
| Deploy action | Deploy the exact authorized artifact to the exact environment | Repository implementation edits |
| Rollback action | Restore the recorded rollback target | Expanding environment or artifact scope |
| Core reducer | Validate and record transitions | Inventing requirements, commands, or credentials |

Worker isolation MUST prevent a raw Git command from changing protected refs in
the authoritative repository. Prompt instructions alone do not satisfy this
requirement.

Project-supplied verification scripts are untrusted to the same degree as
workers. The gate executor MUST expose only the action env allowlist, no delivery
credentials, and no writable authoritative Git metadata; network is denied by
default unless that action explicitly declares and the gate policy permits it.
A script that attempts `git update-ref`, push, state-store access, or undeclared
credential access MUST fail without changing authoritative state.

## 14. Agent adapter contract

### 14.1 Required operations

Every adapter MUST expose the logical operations:

```text
probe
start
poll
cancel
collect
```

The implementation MAY use subprocesses, sessions, or provider-native features
internally.

### 14.2 Capability discovery

`probe` MUST return structured data for:

- adapter and CLI version;
- availability and authentication readiness without exposing credentials;
- headless and structured-output support;
- resume and cancellation support;
- native subagent and background-task support;
- available sandbox and permission modes;
- actual project-instruction sources and relevant size limits when detectable.

The core MUST degrade gracefully when optional capabilities are absent. Native
subagents, provider resume, hooks, and background tasks are optimizations, never
correctness dependencies.

### 14.3 Request envelope

```yaml
protocol_version:
operation_id:
run_id:
attempt_id:
role:
workspace:
context_manifest:
expected_output_schema:
deadline:
fencing_token:
allowed_capabilities: []
```

The envelope MUST NOT contain push, release, deployment, or production secrets.

### 14.4 Result envelope

```yaml
protocol_version:
operation_id:
attempt_id:
status:
session_id:
candidate_commit:
changed_paths: []
observations: []
requested_followups: []
usage: {}
adapter_diagnostics: {}
```

Malformed, missing, stale, mismatched, or unsupported results are failures.

Provider-specific command flags, permission names, event formats, session
behavior, and rule discovery MUST remain inside the thin adapter. Core code MUST
NOT branch on Codex-, Grok-, or Claude-specific CLI details.

Each adapter MUST have deterministic fake conformance tests. Installed real
CLIs MAY be tested by opt-in smoke jobs that consult then-current official
provider documentation. Real-CLI smoke tests MUST NOT alter core expectations or
perform high-impact actions.

## 15. Scheduler, agents, and concurrency

- Single-agent mode is the normal scheduler with worker concurrency `1`.
- Multi-agent mode permits multiple ready Tasks only when dependencies, declared
  write sets, and workspace isolation allow it.
- Phase order is serial by default. Ready Tasks inside a Phase MAY run
  concurrently.
- Protected-branch integration is always serialized through a merge queue.
- Overlapping declared write sets MUST serialize unless a reviewed conflict-safe
  strategy exists.
- Undeclared overlap discovered from actual candidate diffs MUST be detected
  before integration.
- Every claimed Task has a lease owner, heartbeat, expiry, fencing token, and
  Attempt ID.
- A stale worker result is rejected even when the provider reports success.
- Duplicate dispatch with the same idempotency key has one logical effect.
- If `dev` moves after a candidate's recorded base, the candidate MUST be
  resynchronized and all affected gates rerun before integration.
- A merge conflict enters `ATTENTION_REQUIRED`; the system MUST NOT force-push,
  select a side silently, or discard changes.

## 16. Foreground, background, and recovery

Foreground and background execution use the same state store, reducer, and
gates. A PID or live conversation is not runtime truth.

The CLI MUST provide equivalent lifecycle operations for:

```text
run
run --detach
status
pause
resume
cancel
reconcile
```

After controller restart, process loss, or SIGKILL, the recovery controller
MUST:

1. acquire a new lease and fencing token;
2. identify nonterminal Attempts and external Operations;
3. inspect actual provider session, process, workspace, Git ref, remote,
   artifact registry, deployment, and environment state as applicable;
4. classify each Operation as `completed`, `not_started`, `partial`, `failed`,
   or `unknown`;
5. attach reconciliation evidence;
6. resume, retry idempotently, roll back, or enter `ATTENTION_REQUIRED`.

The core MUST load a recovery procedure only for the observed failure class.
Recovery MUST NOT depend on conversation memory.

## 17. Context management

Every agent Attempt MUST receive a content-addressed context manifest containing
only:

- permanent safety and correctness invariants;
- current Goal, Requirement, and Acceptance slices;
- current Phase and Task definition;
- allowed and prohibited paths;
- dependency and interface facts required by the Task;
- relevant durable Decisions;
- acceptance actions;
- expected result schema;
- references to optional on-demand material.

Each included file or slice has a digest. The manifest records byte size and an
estimated token count. On-demand additions are referenced, budget-checked, and
audited.

Provider recipes, recovery manuals, historical reports, unrelated Tasks, and
the full repository MUST NOT be loaded by default. Platform entry files MAY
point to one invariant source but MUST NOT duplicate or weaken it.

## 18. Project configuration and action contract

The project supplies commands and secret references. V6 supplies validation,
authorization, execution order, evidence, and recovery.

The configuration file is versioned JSON so the Python standard-library core
can parse it without an additional runtime dependency. This topology fragment
shows required references; it is not a complete instance and omitted fields are
not defaults:

```json
{
  "schema_version": "nm-v6/project-v1",
  "project": {"name": "example"},
  "git": {
    "remote": "origin",
    "stable_branch": "main",
    "integration_branch": "dev",
    "protected_branches": ["main", "dev"],
    "work_branch_prefixes": ["feature/", "fix/", "docs/", "refactor/", "chore/", "task/"],
    "hotfix_prefix": "hotfix/",
    "other_branch_push": "administrator_grant_only",
    "remote_branch_delete": "administrator_grant_only",
    "force_push": "forbidden",
    "integration_unit": "phase",
    "merge_strategies": ["fast_forward", "squash", "merge_commit"]
  },
  "scheduler": {"max_workers": 1, "lease_seconds": 120},
  "context": {"max_manifest_bytes": 131072, "max_estimated_tokens": 24000},
  "actions": {
    "task_verify": "task_verify",
    "phase_verify": "phase_verify",
    "full_verify": "full_verify",
    "build": "build",
    "release": "release",
    "publish": "publish"
  },
  "delivery": {
    "artifact_digest_result_field": "artifact_digest",
    "environments": {
      "production": {
        "expected_identity": "project-production",
        "identity_probe": "identity_probe",
        "preflight": "preflight",
        "deploy": "deploy",
        "health": "health",
        "rollback": "rollback",
        "post_rollback_verify": "post_rollback_verify"
      }
    }
  },
  "action_definitions": {},
  "secret_references": {},
  "notifications": {"routes": []}
}
```

Every entry in `actions` and `delivery` MUST resolve to exactly one
`nm-v6/action-v1` definition with all fields below; no implicit default is
permitted:

| Field | Contract |
| --- | --- |
| `schema_version` | Literal `nm-v6/action-v1`. |
| `action_id` | Unique stable ID matching its configuration key. |
| `kind` | `pure`, `external_observe`, or `external_mutation`. |
| `argv` | Nonempty string array; no raw shell string or interpolation. |
| `cwd` | Repository-relative declared directory. |
| `timeout_seconds` | Positive bounded integer. |
| `accepted_exit_codes` | Nonempty integer array. |
| `env_allowlist` | Names that may be inherited from the controller environment. |
| `core_injected_env` | Names the core supplies, including an Operation ID when required. |
| `secret_refs` | Named references only, never values. |
| `result_schema` | Versioned structured-result schema ID. |
| `idempotency` | `not_applicable`, `read_only`, or `required`; `required` declares exact Operation-ID injection. |
| `observe_action_id` | Required for `external_mutation`; points to an `external_observe` action. |
| `reconcile_action_id` | Required for `external_mutation`; points to an idempotent reconciliation action. |

Release, publish, deploy, and rollback are always `external_mutation`. Build is
`pure` and MUST return an artifact digest. Identity probes and health checks are
`external_observe`. Project scripts for complex behavior are allowed, but their
invocation still follows this argv contract.

Every action result MUST validate as `nm-v6/action-result-v1` and contain:

```json
{
  "protocol_version": "nm-v6/action-result-v1",
  "action_id": "release",
  "operation_id": "OP-example-001",
  "status": "succeeded",
  "effect_id": "provider-effect-id-or-null",
  "artifact_digest": "sha256-or-null",
  "environment_id": "environment-or-null",
  "environment_fingerprint": "fingerprint-or-null",
  "observed_state": {},
  "started_at": "RFC3339",
  "finished_at": "RFC3339",
  "diagnostics": {},
  "redactions": []
}
```

`status` is one of `succeeded`, `failed`, `partial`, or `unknown`. Required
identity/digest/effect fields are conditional on action kind and are defined by
the JSON Schema; an empty or malformed success result is a failure.

The core injects the persisted Operation ID exactly as declared, validates the
result before recording progress, and invokes observe/reconcile after timeout,
process loss, malformed result, or an ambiguous provider response. The identity
probe's structured result MUST equal both the configured expected identity and
the authorization scope.

`template/v6/project.example.json` MUST be a complete instance with every
referenced action and fake secret provider defined. It MUST pass `v6:check` and
drive the mandatory fake end-to-end suite; the abbreviated topology above is
not accepted as that fixture.

Validation MUST reject:

- an integration branch other than literal `dev`, or stable equal to `dev`;
- incomplete protected-branch declarations;
- an unconfirmed or ambiguous environment identity;
- deployment without identity, health, rollback, post-rollback verification,
  observe, and reconciliation actions;
- credential values instead of references;
- raw shell interpolation;
- release, publish, deploy, or rollback actions without idempotency,
  structured-result, observe, or reconciliation metadata;
- missing full verification;
- unknown schema or adapter protocol versions.

## 19. Git workflow

### 19.1 Protected branches and normal work

The remote normally contains one configured stable branch and `dev`.

1. An AI worker MUST NOT modify, commit on, reset, rebase, or force-push the
   stable branch or `dev`.
2. Before normal work, the core runs `git fetch --prune <remote> dev` without
   agent credentials, resolves `refs/remotes/<remote>/dev`, and records that
   exact SHA and fetch time. Local `dev` must equal it or be cleanly
   fast-forwarded to it by the controller; a divergent/local-only `dev`, failed
   fetch, or unknown remote state stops. The work branch uses an allowed prefix
   and starts at that exact remote-tracking SHA.
3. Only the deterministic Git integrator may update `dev`, after
   `DEV_INTEGRATION_GATE` and the applicable staged approval or auto grant.
4. Only the deterministic release controller may promote verified `dev` content
   to stable after `RELEASE_GATE`.
5. Ordinary work branches MUST NOT merge directly to stable.
6. Stable and `dev` MAY be pushed to the configured remote after their gate and
   authorization. The exact before/after remote refs are recorded.
7. Other branches remain local. An important branch may be pushed only when the
   administrator explicitly grants backup or review publication for that named
   branch and remote.
8. Force-push to protected refs is forbidden. Force-push elsewhere requires an
   explicit administrator grant and is outside the default V6 workflow.
9. A dirty, unexpected, or user-modified authoritative working tree causes a
   hard stop before Git mutation.
10. Immediately before integration, the core fetches again and compare-and-swaps
    the expected remote `dev`. If it moved, the candidate is resynchronized and
    every affected gate is rerun; the old receipt cannot authorize a merge.

An authorization for a nonprotected remote-ref action has this minimum scope:

```yaml
grant_id:
action: push_backup | delete_remote
remote:
ref:
expected_sha:
force: false
one_time: true
expires_at:
administrator_authorization_id:
```

The controller validates the exact ref and SHA and records an execution receipt.
A backup-push grant cannot authorize deletion; remote deletion always consumes
a new grant.

### 19.2 Hotfix

A hotfix is the only workflow based on stable:

1. The administrator explicitly classifies or authorizes the work as a hotfix.
2. Fetch the configured remote stable ref, require local stable to match or
   fast-forward cleanly, record its SHA, and create `hotfix/*` at that exact SHA.
3. Implement on that branch, never directly on stable.
4. Independently verify and integrate to stable through
   `HOTFIX_STABLE_GATE`/`HOTFIX_STABLE_RESULT_GATE`.
5. Reconcile the exact hotfix effect back into `dev` through
   `HOTFIX_RECONCILIATION_GATE`/`HOTFIX_RECONCILIATION_RESULT_GATE`; conflicts
   require attention, and affected verification is rerun.
6. Retain the branch until release and rollback responsibility closes.

### 19.3 Merge-strategy decision

Before work/Phase integration to `dev`, normal promotion to stable, hotfix
integration, or hotfix reconciliation, an AI reviewer MUST propose one allowed strategy based on
branch purpose, sharing status, topology, commit quality, audit needs, conflict
risk, and rollback needs:

- **fast-forward** — target is an ancestor, commits are already suitable, and a
  separate integration boundary is unnecessary;
- **squash** — the branch is one logical change and intermediate commits are
  noisy or disposable;
- **merge commit** — meaningful commits, shared history, auditability, or a clear
  integration/rollback boundary should be preserved.

Rebase is source-branch preparation, not a protected-branch merge strategy. It
is allowed only on an unpublished disposable source branch. Rewriting a pushed
or retained branch requires explicit administrator authorization.

The proposal MUST record:

- source and target refs and commits;
- branch purpose and sharing/publication status;
- topology and candidate tree digest;
- selected strategy and rationale;
- expected resulting tree;
- rollback reference;
- gates and authorization used.

The deterministic controller validates and executes the proposal. An invalid
strategy, unexpected target movement, tree mismatch, or missing evidence stops
integration.

### 19.4 Branch-cleanup decision

After integration, an AI reviewer MUST assess whether the source branch can be
deleted. The deterministic core validates the factual claims and records one
cleanup result:

```text
delete_local
retain
request_administrator
```

The decision records:

- source branch head and integration receipt;
- graph ancestry or, after squash, patch/tree equivalence proof;
- review, backup, dependent-work, release, rollback, and audit responsibility;
- protected-pattern and remote-branch status;
- local and remote recommendation with rationale.

Local automatic deletion is permitted only when the exact branch head is safely
integrated and no responsibility remains. The branch MUST also have no linked
worktree, checkout, live lease, provider session, or dependent disposable
workspace. The controller disposes safe candidate workspaces before deleting
the ref and records the deletion receipt.

The system MUST NOT automatically delete:

- `main`, `master`, or `dev`;
- `release/*` or `hotfix/*`;
- an unmerged or only partially integrated branch;
- a branch under review or acceptance;
- a branch required by dependent work;
- a branch inside a release or rollback retention window;
- a branch explicitly marked for retention or remote backup.

Remote branch deletion always requires a new explicit administrator
authorization, even when local deletion is safe.

After `request_administrator`, the answer creates a new input revision. The AI
reviewer and core MUST re-evaluate current branch facts before any deletion; an
old recommendation is never an execution authorization.

## 20. Release, deployment, and rollback

### 20.1 Release and publication

Every release declares `release_source_kind` as `dev` or `hotfix_stable` plus an
exact source commit and tree digest. A normal release uses an exact verified
`dev`; a hotfix release uses the verified stable result of
`HOTFIX_STABLE_RESULT_GATE`, even when `dev` contains unrelated unreleased work.
Promotion from `dev` to stable, hotfix integration, and hotfix reconciliation
use the merge-proposal contract in Section 19.3. For a normal promotion, the
resulting stable tree MUST equal the verified `dev` tree exactly, regardless of
the allowed strategy selected.

Before changing stable, tagging, or publishing:

- all mandatory Acceptance criteria due by `release` have valid evidence;
- repository and remote relationships are known and unchanged;
- full verification passes on the integration candidate;
- the build produces an immutable artifact digest;
- version, tag, changelog, and release metadata pass project actions;
- rollback target and Operation idempotency key are recorded;
- staged approval or the auto grant covers every action and protected ref.

The release receipt binds source kind/commit/tree, resulting stable commit/tree,
version/tag, artifact digest, action outputs, and remote-ref results. A normal
receipt binds the verified source `dev` commit. A hotfix receipt binds the
verified hotfix stable commit and also references the corresponding hotfix
reconciliation result receipt; it MUST NOT falsely identify the current `dev`
head as its build source.

`RELEASE_GATE` authorizes the exact planned effects;
`RELEASE_RESULT_GATE` independently observes them. A timeout or partial/unknown
stable update, tag, release, or publication MUST be observed and reconciled
before retry. The source tree digest, build artifact digest, resulting stable
tree, tag target, published version, and provider effect IDs form one binding
chain; any mismatch stops delivery.

### 20.2 Deployment

Before deployment:

- a project identity probe identifies the target environment;
- observed identity equals the configured and authorized identity;
- the exact artifact digest is fixed;
- credentials are injected only into the deploy action;
- preflight and rollback-readiness gates pass;
- an idempotency key exists;
- the current deployed version is recorded as rollback target.

Repeated invocation with the same idempotency key MUST NOT create a duplicate
logical deployment.

### 20.3 Post-deployment and rollback

`DEPLOYING` is not success. The run proceeds through
`POST_DEPLOY_VERIFYING`.

A health or smoke failure causes:

- `ROLLBACK_REQUIRED` when a valid rollback path exists;
- automatic rollback only when the auto grant includes the exact environment
  and rollback action;
- otherwise `ATTENTION_REQUIRED`.

A successful rollback ends in `ROLLED_BACK`, not `COMPLETED`. A rollback failure
ends in `FAILED` or `ATTENTION_REQUIRED` with preserved evidence and current
environment observations.

Rollback success is provisional until `post_rollback_verify` produces structured
evidence and `POST_ROLLBACK_GATE` passes. Failure of that verification does not
enter `ROLLED_BACK`; it retains `POST_ROLLBACK_VERIFYING` observations and
requires attention or another authorized recovery action.

## 21. Failures, retries, optional work, and cancellation

Failures MUST be classified at least as:

- deterministic acceptance failure;
- Spec conflict;
- policy or permission violation;
- merge conflict;
- transient infrastructure failure;
- agent or adapter protocol failure;
- external operation `partial` or `unknown`;
- environment health failure.

Only configured retryable classes may retry automatically. Retries use bounded
budgets and backoff. Repeating the same deterministic failure without a changed
input, command, environment, or implementation is forbidden.

Optional work may be skipped only when:

- the confirmed Spec marks it optional;
- no mandatory Acceptance criterion becomes uncovered;
- the skip decision and reason are recorded;
- staged approval or auto policy permits it.

Cancellation is a state transition. It requests cancellation, fences stale
actors, reconciles external Operations, and preserves evidence. Killing a
process alone is not cancellation.

## 22. Audit, notifications, and supply chain

### 22.1 Audit and notification outbox

The append-only audit record MUST include:

- state transitions;
- administrator approvals and auto grants;
- adapter request/result metadata;
- evidence receipts and gate decisions;
- merge proposals and branch-cleanup decisions;
- protected-ref changes and pushes;
- release, deployment, health, and rollback Operations;
- reconciliation results;
- secret redaction events;
- notification delivery Attempts.

Each audit row has a monotonic sequence, previous-row digest, canonical event
digest, event type, actor, run revision, and timestamp. Normal APIs expose no
update/delete path. Startup, export, and acceptance verification check sequence
continuity and the digest chain; a mismatch enters `ATTENTION_REQUIRED` and
blocks high-impact actions.

Notifications consume a durable outbox. A delivery failure is retried
independently and MUST NOT advance or roll back workflow business state.
Duplicate delivery uses a stable notification idempotency key.

### 22.2 Supply-chain controls

- Runtime and test dependencies MUST be declared and version-constrained.
- Downloaded adapter/tool artifacts MUST have an allowlisted origin and verified
  digest or signature.
- The core records Python, SQLite, Git, adapter, CLI, schema, and evaluator
  versions in evidence.
- Automatic provider CLI self-update MUST be disabled during a run when the
  provider permits it; an observed version change invalidates affected evidence.
- Generated template files MUST be covered by `template/v6/manifest.json` with
  deterministic content hashes in the install/update plan.
- Mandatory CI MUST run without real provider, remote, notification, release, or
  deployment credentials.

## 23. CLI, update safety, and generated-project behavior

The deterministic CLI MUST expose equivalent operations for:

```text
init
update
check
status [--json]
spec confirmation request
spec confirm                 # trusted control plane only
plan
mode set
authorize request
authorize approve
authorize revoke
run [--detach]
pause
resume
cancel
reconcile
adapter probe
evidence show
audit export
notify-test
```

Requirements:

- `init` creates or validates configured stable and `dev` branches and leaves a
  clean repository. It makes no implementation commit directly on either.
- `update` requires a Git root, clean-tree preflight, a successful fetch, a new
  allowed branch from the exact remote-tracking `dev`, staging outside the
  target, validation before application, and transactional resume or abort
  behavior.
- Existing user changes and project-specific guidance MUST NOT be overwritten.
- `check` validates all schemas, traceability, state-source uniqueness,
  instructions, bilingual pairs, manifest coverage, branch policy, adapter
  configuration, action contracts, and delivery contracts.
- `status` is a projection from canonical state and is available as human text
  and versioned JSON.
- The Skill is a thin entry over the same CLI. It MUST NOT implement a second
  workflow in prose or scripts.
- Agent-accessible invocations may create authorization requests, but only the
  trusted control plane can approve or revoke them. `mode set auto` without a
  verified grant leaves the run waiting for authorization.
- The same boundary applies to Spec confirmation: an agent may request it, but
  only trusted `spec confirm` produces the confirmation record used by
  `SPEC_GATE`.

The repository implementation MUST provide these stable acceptance commands:

```bash
npm run lm
npm run v6:check
npm run v6:test
npm run skill:v6:check
```

A generated V6 project MUST provide:

```bash
npm run workflow:check
npm run workflow:test
npm run verify
```

## 24. Instruction and documentation layout

The implementation MUST provide:

- concise English repository rules containing only permanent invariants;
- a complete synchronized Simplified Chinese administrator mirror;
- this normative implementation Spec and its administrator mirror;
- project configuration, protocol, and schema references;
- provider-specific adapter references selected only by the adapter;
- recovery references selected by failure class;
- generated status, audit, and evidence views;
- no mutable runtime status inside Task Markdown.

Platform entry files MUST point to the same invariant source and MUST NOT claim
that model instruction discovery is an enforcement mechanism.

## 25. Implementation requirements

| ID | Requirement |
| --- | --- |
| `V6-REQ-001` | Implement discovery, Spec review, canonical Spec hashing, trusted explicit confirmation, stage-annotated Acceptance criteria, and stable traceability IDs. |
| `V6-REQ-002` | Implement one SQLite runtime authority and deterministic reducer with transactional events, CAS, idempotency, migrations, and rebuildable views. |
| `V6-REQ-003` | Enforce the Run, Phase, Task, Attempt, hotfix, rollback, and failure state machines through a versioned transition table. |
| `V6-REQ-004` | Implement complete core-produced evidence receipts, atomic redacted content-addressed outputs, validity rules, and evidence-backed gate decisions. |
| `V6-REQ-005` | Implement all mandatory pre-action and observed-result gates from Spec through normal/hotfix integration, post-deployment, completion, and post-rollback. |
| `V6-REQ-006` | Implement `staged` and `auto` through one state/gate model and an agent-inaccessible trusted control plane for persisted approvals, grants, and revocations. |
| `V6-REQ-007` | Implement thin versioned Codex, Grok, and Claude adapters with capability probing and structured results. |
| `V6-REQ-008` | Enforce role, worker/gate workspace, protected-ref, credential, network, and state-write isolation. |
| `V6-REQ-009` | Implement one scheduler for single/multi-agent and foreground/background use. |
| `V6-REQ-010` | Implement leases, heartbeats, fencing, write-set conflict detection, stale-result rejection, and serialized integration. |
| `V6-REQ-011` | Implement crash recovery and observed-state reconciliation for agent, Git, release, deployment, and rollback Operations. |
| `V6-REQ-012` | Implement content-addressed minimum context manifests, budgets, and audited on-demand loading. |
| `V6-REQ-013` | Enforce exact remote-tracking `dev` and hotfix ancestry, branch prefixes, protected refs, promotion, push grants, target CAS, and dirty-tree rules. |
| `V6-REQ-014` | Implement validated AI merge proposals and evidence-backed local/remote branch-cleanup decisions. |
| `V6-REQ-015` | Implement source/artifact/tag-bound release, environment-bound deployment, structured observe/reconcile, post-deployment verification, and verified rollback. |
| `V6-REQ-016` | Implement versioned JSON project configuration and complete deterministic argv/action-result/idempotency contracts. |
| `V6-REQ-017` | Enforce environment identity, secret-reference, minimum injection, and redaction rules. |
| `V6-REQ-018` | Implement classified retries, optional-work skip constraints, attention, and cancellation. |
| `V6-REQ-019` | Implement append-only audit records and a durable idempotent notification outbox. |
| `V6-REQ-020` | Implement safe `init`, `update`, `check`, `status`, lifecycle commands, and a thin installation Skill. |
| `V6-REQ-021` | Keep permanent model instructions minimal and load platform/recovery details only on demand; maintain complete English/Chinese documentation pairs. |
| `V6-REQ-022` | Preserve V1–V5 and reject automatic import or resumption of mutable V5 runtime state. |
| `V6-REQ-023` | Implement dependency, downloaded-artifact, version-drift, template-manifest, and credential-free CI supply-chain controls. |
| `V6-REQ-024` | Trace every Decision and Invariant through Requirements to evidence, and produce a scoped implementation-file traceability report for every mandatory `V6-AC-*`. |

## 26. Acceptance criteria

Every `V6-AC-*` is mandatory unless a later confirmed resolution changes it.
`V6-AC-044` is an independent-review criterion; all others are automated.
Automated tests MUST use disposable repositories, local bare remotes,
isolated HOME/config directories, fake secrets, fake agent CLIs, and fake
release/deployment/notification targets. They MUST NOT send real notifications,
push a real remote, or touch a real environment.

| ID | Acceptance |
| --- | --- |
| `V6-AC-001` | A valid confirmed Spec passes; missing IDs, stage annotations, trusted confirmation, unique IDs, acyclic links, or mandatory coverage fails. |
| `V6-AC-002` | A semantic confirmed-Spec change creates a new canonical hash and invalidates affected evidence before any later transition. |
| `V6-AC-003` | All disposable projections can be deleted and rebuilt to the same logical state from the SQLite authority. |
| `V6-AC-004` | A stale expected revision, duplicate non-idempotent request, or stale fencing token is rejected. |
| `V6-AC-005` | An agent exiting zero without a valid structured result produces no progress transition. |
| `V6-AC-006` | An agent claiming tests passed cannot satisfy `TASK_GATE` when the independently rerun action fails. |
| `V6-AC-007` | An agent attempting to write runtime state or a protected ref cannot affect authoritative state or refs. |
| `V6-AC-008` | The versioned transition table rejects every omitted/unguarded transition, including direct `READY -> COMPLETED` or completion without `COMPLETION_GATE`. |
| `V6-AC-009` | In `staged`, `dev`, stable, release, and deployment targets remain unchanged until their corresponding approvals exist. |
| `V6-AC-010` | In `auto`, trusted authorized merge, release, and deployment occur after passing gates without another prompt; a failed gate or out-of-scope target prevents action. |
| `V6-AC-011` | Mode choice and changes survive restart; Spec/configuration change, trusted revocation, cancellation, completion, or expiry invalidates the old auto grant. |
| `V6-AC-012` | Codex, Grok, and Claude fake adapters pass the same protocol suite; malformed, stale, mismatched, and unsupported responses fail cleanly. |
| `V6-AC-013` | An adapter without native subagents, resume, or background support completes through fallback sessions with identical core semantics. |
| `V6-AC-014` | Single-worker and multi-worker runs over one fixture produce equivalent accepted trees and mandatory Acceptance coverage. |
| `V6-AC-015` | Nonoverlapping Tasks may run concurrently; declared or actual overlapping writes are serialized or stopped before integration. |
| `V6-AC-016` | Two controllers cannot own the same lease; a late result after lease takeover is rejected. |
| `V6-AC-017` | SIGKILL immediately before and after state writes, verification, integration, release, deployment, and rollback resumes without duplicate logical effects. |
| `V6-AC-018` | A detached run survives controller restart and recovers status without conversation or PID memory; pause persists, stops new dispatch, and resumes only to its recorded state. |
| `V6-AC-019` | Normal work on `main`, `master`, `dev`, an invalid prefix, or a base other than the recorded remote-tracking `dev` is rejected before implementation. |
| `V6-AC-020` | A hotfix starts at fetched stable, changes only `hotfix/*`, passes stable and dev-reconciliation pre/result gates, and rejects direct stable editing, conflict, or any case where either configured-remote stable/dev was not updated to the authorized result. |
| `V6-AC-021` | Only the deterministic controller updates `dev`; stable receives only a tree exactly equal to verified `dev` or a gated hotfix, with observed-result receipts. |
| `V6-AC-022` | Stable/`dev` pushes follow authorization; an ordinary branch push is denied until a trusted grant names its action, branch, SHA, remote, and expiry. |
| `V6-AC-023` | Fast-forward, squash, and merge-commit fixtures produce a decision receipt and expected tree; invalid proposals or moved targets are rejected. |
| `V6-AC-024` | Cleanup deletes an eligible local branch but preserves protected, unmerged, in-review, dependent, backed-up, hotfix, release, rollback-retained, checked-out, or active branches. |
| `V6-AC-025` | Squash cleanup requires recorded patch/tree equivalence rather than a false graph-merged claim; remote deletion still requires a new administrator grant. |
| `V6-AC-026` | Fake secrets never appear in prompts, projections, logs, evidence output, audit exports, or notifications. |
| `V6-AC-027` | Configuration containing a secret value, raw shell interpolation, ambiguous environment, incomplete action definition/result schema, or delivery without observe/reconcile/verified rollback is rejected. |
| `V6-AC-028` | An environment identity mismatch stops before deployment and produces `ATTENTION_REQUIRED` with evidence. |
| `V6-AC-029` | Repeating deployment with one idempotency key creates exactly one fake external deployment. |
| `V6-AC-030` | A partial or unknown deployment is reconciled from observed state before retry. |
| `V6-AC-031` | Post-deployment failure rolls back automatically only when the grant covers the environment and action; otherwise it waits for attention. |
| `V6-AC-032` | Rollback reaches `ROLLED_BACK` only after `POST_ROLLBACK_GATE`; rollback or post-rollback verification failure preserves evidence and never reports `COMPLETED`. |
| `V6-AC-033` | Context manifests stay within configured budget, contain required invariants and Acceptance slices, and audit every on-demand addition. |
| `V6-AC-034` | A retryable transient failure retries within budget; an unchanged deterministic failure does not loop; exhausted work requires attention. |
| `V6-AC-035` | An optional Task cannot be skipped when doing so leaves a mandatory Acceptance criterion uncovered. |
| `V6-AC-036` | Notification failure leaves gate/business state unchanged, persists an outbox item, and retries without duplicate notification identity. |
| `V6-AC-037` | `init` produces a clean repository with distinct stable and `dev`; no implementation commit is made directly on either. |
| `V6-AC-038` | An injected `update` failure preserves user files and supports deterministic resume or abort on its allowed work branch. |
| `V6-AC-039` | `check` rejects duplicate mutable runtime facts in Markdown and detects missing manifest entries, instruction conflicts, or missing English/Chinese pairs. |
| `V6-AC-040` | End-to-end fake scenarios cover staged single foreground, auto multi-agent background, crash/resume, false worker success, merge conflict, partial deployment, and rollback. |
| `V6-AC-041` | A clean generated V6 project passes `workflow:check`, `workflow:test`, and `verify`. |
| `V6-AC-042` | V1–V5 remain present, V5 remains marked experimental, and attempting to resume a V5 INDEX/task-card runtime is refused with a documented boundary. |
| `V6-AC-043` | Dependency constraints, downloaded-artifact verification, provider-version drift, manifest hashes, and credential-free CI controls fail closed under injected violations. |
| `V6-AC-044` | Automated structure checks plus independent semantic review confirm the English normative Spec and Simplified Chinese mirror have the same IDs, status, decisions, requirements, and acceptance criteria. |
| `V6-AC-045` | A generated traceability report maps every `V6-REQ-*` to in-scope implementation files and passing evidence, and maps every in-scope changed file to at least one Requirement. |
| `V6-AC-046` | Hash fixtures prove the exact canonical algorithm across LF/CRLF, trailing-LF, and frontmatter-key-order normalization; changing excluded control fields keeps the hash, while any change to canonicalized normative bytes changes it and invalidates the old confirmation. |
| `V6-AC-047` | Agent-created or tampered approval data, replayed nonce, expanded scope, wrong revision, expired grant, and unauthorized revoke are rejected; a revoke/start race has exactly the atomic semantics in Section 12.1. |
| `V6-AC-048` | A mandatory deploy-stage Acceptance criterion does not block `RELEASE_GATE`, does block `COMPLETION_GATE` until satisfied, and a missing/invalid `required_by_stage` fails Spec validation. |
| `V6-AC-049` | Table-driven tests remove or corrupt each prerequisite of every gate, including each pre-action/result-gate pair; each affected gate fails without target mutation. |
| `V6-AC-050` | The complete example JSON validates; each action/result field is enforced; partial/unknown release and publish are observed/reconciled before an idempotent retry. |
| `V6-AC-051` | Evidence fixtures reject missing binding fields or wrong digests; only redacted stored bytes are retrievable and digested; unredactable secret output fails evidence collection without persistence. |
| `V6-AC-052` | Dirty authoritative trees, stale/divergent local `dev`, fetch failure, invalid prefixes, moved remote refs, and result-tree mismatches fail closed; resynchronization invalidates old Git evidence. |
| `V6-AC-053` | Normal and hotfix fixtures prove one unbroken release-source-kind/commit/tree -> artifact -> stable-tree -> tag -> published-version binding and reject substitution at every link; the hotfix fixture has extra unreleased `dev` commits and must build from verified hotfix stable while citing its dev-reconciliation receipt. |
| `V6-AC-054` | Pause, cancel, or grant revocation during each external mutation fences new steps, reconciles the active effect, and cannot enter `PAUSED`/`CANCELLED` prematurely. |
| `V6-AC-055` | Audit fixtures cover every required event class, reject update/delete or sequence tampering, and rebuild an equivalent ordered export after restart. |
| `V6-AC-056` | A malicious verify action attempting `git update-ref`, push, state writes, network, or delivery-secret access fails without affecting authority or leaking credentials. |
| `V6-AC-057` | Nonprotected ref grants enforce exact action/ref/SHA/remote, one-time use, expiry, and `force: false`; a backup-push grant cannot delete and remote deletion requires a new grant. |
| `V6-AC-058` | SIGKILL at every evidence-blob write/fsync/rename/receipt boundary yields either one valid receipt+blob or a quarantined orphan; missing/corrupt blobs invalidate gates and integrity checks catch database corruption. |
| `V6-AC-059` | Static traceability validation proves every `V6-DEC-*` and `V6-INV-*` reaches at least one Requirement and executable Acceptance item. |
| `V6-AC-060` | Branch cleanup refuses linked worktrees, checkouts, live leases/sessions, and dependent workspaces; after administrator input it re-evaluates facts and records a fresh execution receipt. |

For `V6-AC-045`, an in-scope implementation file is any tracked source,
configuration, schema, manifest, template, Skill, script, test, or documentation
file created or changed for V6, including root integration files. Generated
runtime/evidence output, caches, vendored dependencies, and disposable test
repositories are out of scope and MUST NOT be committed. A translation maps to
`V6-REQ-021` plus the Requirement of the behavior it mirrors.

## 27. Requirement-to-acceptance map

### 27.1 Requirement coverage

| Requirement | Acceptance IDs |
| --- | --- |
| `V6-REQ-001` | `V6-AC-001`, `V6-AC-002`, `V6-AC-035`, `V6-AC-046`, `V6-AC-048` |
| `V6-REQ-002` | `V6-AC-003`, `V6-AC-004`, `V6-AC-017`, `V6-AC-058` |
| `V6-REQ-003` | `V6-AC-005`, `V6-AC-008`, `V6-AC-018`, `V6-AC-054` |
| `V6-REQ-004` | `V6-AC-006`, `V6-AC-029`, `V6-AC-030`, `V6-AC-051`, `V6-AC-058` |
| `V6-REQ-005` | `V6-AC-006`, `V6-AC-009`, `V6-AC-010`, `V6-AC-031`, `V6-AC-032`, `V6-AC-048`, `V6-AC-049` |
| `V6-REQ-006` | `V6-AC-009`, `V6-AC-010`, `V6-AC-011`, `V6-AC-047`, `V6-AC-054` |
| `V6-REQ-007` | `V6-AC-012`, `V6-AC-013` |
| `V6-REQ-008` | `V6-AC-007`, `V6-AC-019`, `V6-AC-021`, `V6-AC-026`, `V6-AC-056` |
| `V6-REQ-009` | `V6-AC-014`, `V6-AC-018`, `V6-AC-040` |
| `V6-REQ-010` | `V6-AC-015`, `V6-AC-016`, `V6-AC-052` |
| `V6-REQ-011` | `V6-AC-017`, `V6-AC-018`, `V6-AC-030`, `V6-AC-050`, `V6-AC-054`, `V6-AC-058` |
| `V6-REQ-012` | `V6-AC-033` |
| `V6-REQ-013` | `V6-AC-019`, `V6-AC-020`, `V6-AC-021`, `V6-AC-022`, `V6-AC-052`, `V6-AC-057` |
| `V6-REQ-014` | `V6-AC-023`, `V6-AC-024`, `V6-AC-025`, `V6-AC-060` |
| `V6-REQ-015` | `V6-AC-028`, `V6-AC-029`, `V6-AC-030`, `V6-AC-031`, `V6-AC-032`, `V6-AC-050`, `V6-AC-053` |
| `V6-REQ-016` | `V6-AC-027`, `V6-AC-037`, `V6-AC-038`, `V6-AC-050` |
| `V6-REQ-017` | `V6-AC-026`, `V6-AC-027`, `V6-AC-028`, `V6-AC-051` |
| `V6-REQ-018` | `V6-AC-034`, `V6-AC-035`, `V6-AC-054` |
| `V6-REQ-019` | `V6-AC-036`, `V6-AC-055` |
| `V6-REQ-020` | `V6-AC-037`, `V6-AC-038`, `V6-AC-039`, `V6-AC-041` |
| `V6-REQ-021` | `V6-AC-033`, `V6-AC-039`, `V6-AC-044` |
| `V6-REQ-022` | `V6-AC-042` |
| `V6-REQ-023` | `V6-AC-043` |
| `V6-REQ-024` | `V6-AC-045`, `V6-AC-059` |

### 27.2 Decision coverage

| Decision | Requirements |
| --- | --- |
| `V6-DEC-001` | `V6-REQ-005`, `V6-REQ-015`, `V6-REQ-016`, `V6-REQ-017` |
| `V6-DEC-002` | `V6-REQ-002`, `V6-REQ-020`, `V6-REQ-023` |
| `V6-DEC-003` | `V6-REQ-002`, `V6-REQ-004`, `V6-REQ-019` |
| `V6-DEC-004` | `V6-REQ-013`, `V6-REQ-020` |
| `V6-DEC-005` | `V6-REQ-013`, `V6-REQ-014` |
| `V6-DEC-006` | `V6-REQ-013` |
| `V6-DEC-007` | `V6-REQ-014` |
| `V6-DEC-008` | `V6-REQ-009`, `V6-REQ-013` |
| `V6-DEC-009` | `V6-REQ-006` |

### 27.3 Invariant coverage

| Invariant | Requirements |
| --- | --- |
| `V6-INV-001` | `V6-REQ-002` |
| `V6-INV-002` | `V6-REQ-002`, `V6-REQ-003` |
| `V6-INV-003` | `V6-REQ-004`, `V6-REQ-005` |
| `V6-INV-004` | `V6-REQ-006` |
| `V6-INV-005` | `V6-REQ-006` |
| `V6-INV-006` | `V6-REQ-008`, `V6-REQ-017` |
| `V6-INV-007` | `V6-REQ-013` |
| `V6-INV-008` | `V6-REQ-008`, `V6-REQ-013` |
| `V6-INV-009` | `V6-REQ-013`, `V6-REQ-015` |
| `V6-INV-010` | `V6-REQ-009`, `V6-REQ-010` |
| `V6-INV-011` | `V6-REQ-011`, `V6-REQ-015` |
| `V6-INV-012` | `V6-REQ-004`, `V6-REQ-015`, `V6-REQ-017` |
| `V6-INV-013` | `V6-REQ-008`, `V6-REQ-017` |
| `V6-INV-014` | `V6-REQ-012`, `V6-REQ-021` |
| `V6-INV-015` | `V6-REQ-003`, `V6-REQ-005` |
| `V6-INV-016` | `V6-REQ-008`, `V6-REQ-021` |

## 28. Representative scenario matrix

| Scenario | Mode | Agents | Controller | Adapter coverage | Required result |
| --- | --- | --- | --- | --- | --- |
| Discovery through accepted Phase | staged | single | foreground | Codex fake | Stops before `dev`; approval resumes exact candidate |
| Full delivery | auto | multiple | background | Grok fake | Parallel safe Tasks, serialized integration, release, deploy, health, complete |
| Capability fallback | staged | single | background | Claude fake without subagent/resume | Same core semantics through fresh sessions |
| Untrusted worker | both | single | foreground | each fake adapter | False pass, path violation, protected-ref attempt, malformed result cannot pass gate |
| Authorization attack | both | mixed | foreground | fake trusted control plane | Forgery, replay, scope expansion, expiry, and revoke/start race fail closed |
| Concurrency and stale work | auto | multiple | two controllers | mixed fake adapters | One lease owner; overlap and late results rejected |
| Crash matrix | both | mixed | restart | fake adapters/actions | Idempotent recovery at every transition/external-action boundary |
| Git policy | both | mixed | foreground | fake reviewer | Normal, hotfix, all merge strategies, push rules, and cleanup retention pass |
| Delivery failure | auto | mixed | background | fake release/deployment | Partial release/publish/deploy, wrong environment, health failure, and verified rollback outcomes classify correctly |

Mandatory CI uses fake adapters and fake delivery systems. Optional real-CLI
smoke jobs cover currently supported Codex, GrokBuild, and Claude Code versions
without changing core semantics or external state.

## 29. Implementation sequence and deliverables

### 29.1 Implementation protocol

The implementation agent MUST:

1. verify that this Spec is confirmed and implementation is authorized;
2. fetch the configured remote and create an allowed work branch from latest
   `dev`; it MUST NOT implement on `main`, `master`, or `dev`;
3. create a Requirement-to-file/test plan before substantive implementation;
4. implement in the priority order below without weakening later gates to make
   earlier tests pass;
5. run acceptance from clean disposable fixtures and produce the traceability
   report;
6. stop on a Spec conflict rather than editing the confirmed Spec;
7. request administrator acceptance before integration in `staged`, or use only
   the exact confirmed auto grant in `auto`;
8. after integration, produce and act on the evidence-backed branch-cleanup
   decision.

### 29.2 Priority order

| Priority | Deliverable |
| --- | --- |
| P0 | Canonical Spec/traceability schemas, trusted authorization control plane, SQLite authority, transition table/reducer, atomic redacted evidence, pre/result gates, permission boundary, protected Git refs/hotfix, complete action validator, fake adapters, and fail-closed tests. |
| P1 | Scheduler/concurrency, background lifecycle, blob/external-operation crash reconciliation, merge decisions/cleanup, release/publish/deploy/verified-rollback fake actions, audit/outbox, and abnormal-path tests. |
| P2 | Real thin adapters, context budgeting, supply-chain checks, template/init/update/Skill, bilingual documentation, generated-project verification, and optional real-CLI smoke tests. |

P0, P1, and P2 are implementation order, not optional scope. V6 cannot be
declared complete until all mandatory Acceptance criteria pass.

### 29.3 Required repository products

At minimum, implementation creates:

- `template/v6/` with `manifest.json`, concise agent rules, project
  configuration example, generated-project scripts, and English/Chinese docs;
- `tools/nm-v6/` with the deterministic CLI/core, schemas, adapter host,
  trusted authorization interface, provider adapters, fake adapters, and tests;
- `skills/nm-init-project-v6/` as a thin CLI entry with a valid `SKILL.md`;
- versioned schemas for project Spec, configuration, adapter request/result,
  action/result, transition table, context manifest, evidence, gates,
  approvals/grants/revocations, status JSON, and audit export;
- fixtures for unit, integration, invalid transition, concurrency, crash,
  delivery, and Git-policy tests;
- an implementation traceability report mapping files, Requirements,
  Acceptance criteria, and evidence.

The implementation MUST NOT:

- modify or remove V1–V5 merely to make V6 pass;
- reinterpret V5 mutable runtime files as V6 truth;
- require a real provider CLI, remote push, notification, release, or production
  deployment in mandatory CI;
- mark an Acceptance criterion passed without executable evidence or an
  explicitly identified administrator-only review record;
- mark V6 as the recommended production workflow before all automated evidence
  exists and the administrator explicitly accepts the implementation.

## 30. Definition of done

V6 implementation is complete only when:

1. every `V6-REQ-*` is implemented or explicitly changed by a newer confirmed
   administrator resolution;
2. every mandatory `V6-AC-*` has reproducible evidence from a clean checkout;
3. static validation, invalid transitions, concurrency, interruption recovery,
   and representative long-running scenarios pass;
4. no critical gate is bypassable through direct file editing, agent
   self-report, exit code, mode, notification failure, or stale output;
5. protected Git refs, credentials, release, deployment, and rollback authority
   remain outside AI worker capability;
6. the generated template passes its own checks and verification;
7. the bilingual documentation explains remaining operational risks and project
   responsibilities;
8. an independent acceptance agent reviews the evidence and reports each
   `V6-AC-*` as `pass`, `fail`, or `not_run` without treating implementer claims
   as evidence;
9. the administrator explicitly accepts the implementation before V6 is marked
   recommended or production-ready.
