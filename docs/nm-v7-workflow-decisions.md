---
workflow_version: V7
decision_revision: rev9
supersedes_decision_revision: rev8
status: p0_implementation_input
experimental: true
recommended: false
production_ready: false
decision_id_namespace: V7-DEC
next_decision_id: V7-DEC-142
language: en
normative: true
admin_mirror: nm-v7-workflow-decisions.zh-CN.md
implementation_authorized: false
rev8_source_sha256: d3648c96e19a37d4f26f001b21922f3b4964c6a8ec5483e1717d284039c18bb2
rev8_zh_source_sha256: da5ebc441ee57904d154c3571c7b351c9d573519057e84f2e23297c657e2c1f1
rev7_source_sha256: 25560b30b604808dd4b43d2707e46b942022793ebbecfb11e7c5eac9aeea0c84
rev5_source_sha256: 8e059ef378b313a7d0eb3a0e20f863c5852e0c7286f61b9a97379483687b2d58
rev5_zh_registry_sha256: 0943e27357ea7bc7403f34cbd54d1812a4c6ec5467c4c7bc95f59dd1a53516ac
rev7_zh_111_119_registry_sha256: aedb76949bb0bd449226b0c47dc4aa150144646f88946a2f290ed3f0ae57ecbc
---

# V7 Workflow Final Decision Register (Decision Revision rev9)

English (normative) | [简体中文管理员镜像](nm-v7-workflow-decisions.zh-CN.md)

`V7`, `V6`, and similar uppercase identifiers are workflow versions. `rev9`,
`rev8`, and similar lowercase identifiers are revisions of the V7 decision
register. They use separate namespaces.

`status: p0_implementation_input` means that this document may be used to plan
P0. It does not authorize implementation, integration, push, acceptance,
activation, release, deployment, or any other protected or external effect. A
control session must still supply exact cooperative P0 provenance, or a future
real provider must issue exact authenticated authority, for the next scope.

## 1. Problem and goals

- Let an Agent implement autonomously under a complete task contract, explicit
  authority boundaries, and observable acceptance criteria, with the lowest
  practical daily process and context cost.
- Constrain authority, Git, safety, evidence, acceptance, recovery, and material
  records, without prescribing implementation technique.
- Keep a real fast path for simple work: two successful P0 CLI calls around the
  implementation, no stages, and no additional role. The stable `integrate`
  compatibility command remains present and fails closed without side effects
  in P0, but it is not part of the default P0 Agent flow or context. The
  complete three-command integration path belongs to P1.
- Keep digest, journal, lease, and recovery details inside the CLI and out of
  default Agent context.
- Let the administrator trace contract and candidate revisions, material
  decisions, file changes, validation, repair, review, and integration facts.
- Ensure that the accepted candidate, integrated tree, and target baseline are
  bound exactly.
- Deliver the local runtime as `P0-core` and safe installation as `P0-install`,
  while keeping Standard orchestration outside the Simple default context.
- Defer the protected integration stack to `P1-core`, when a real trusted
  provider has been selected.

## 2. Constraints and assumptions

### Hard constraints

- Preserve V1 through V6. V7 is independent and must not change an older
  version merely to make V7 pass.
- The first V7 implementation remains subject to the current repository rules
  and cannot accept, authorize, activate, or integrate itself.
- `plan | supervised | auto` expresses intent only. It grants no implementation,
  deletion, protected-ref, external, release, or deployment authority.
- P0 `auto` may run only local actions within an exact administrator instruction
  and its cooperative provenance. Protected or external `auto` requires a real
  P1 provider grant; P0 provenance is not that grant.
- Documentation, YAML, local records, leases, and a local CLI under one system
  account provide cooperative constraints and deterministic detection, not an
  adversarial security boundary.
- P0 has no real external adapter, authenticated authority provider,
  protected-target mutation, or controller activation. P0 authority records are
  cooperative provenance only. `task integrate` returns
  `integration_unavailable` before creating a journal, lease, planned commit,
  claim, or ref update.
- P0 stops on the task aggregate branch. It does not update `dev` or activate
  V7.
- P0 has exactly three public, project-persisted core Schemas: project/config,
  work-item envelope, and receipt. It must not add a fourth core Schema. Internal
  versioned record formats for manifests, locks, leases, journals, authorities,
  and CLI results do not count as core Schemas and must not create another
  user-visible state machine.
- The only user-visible task states are `draft | ready | in_progress |
  verifying | blocked | accepted | cancelled | superseded`.
- Do not add a resident Runner, database, event-sourcing system, heartbeat
  service, risk-scoring engine, or default user-visible step.
- Ordinary protected integration targets only `dev`. Stable integration, push,
  release, and deployment each require separate authority in P1.
- Record unavailable model, token, cost, or exact-version data as `unknown`; do
  not infer it.

### Key assumptions

- An administrator or control session can supply cooperative P0 provenance for
  an external implementation instruction. The local CLI can verify its frozen
  fields and bindings but cannot prove cryptographic issuer identity or resist
  a malicious same-account process.
- Without a trusted control plane, protected-ref and external effects fail
  closed.
- V7 does not claim to contain a malicious local program already authorized to
  run. P0 rejects unknown or external actions before spawn according to a
  trusted baseline action catalog, and detects scoped Git mutation after spawn.
- The Simple limits of 4 KiB (`4096` bytes) for the inline request and 16 KiB
  (`16384` bytes) for V7-owned mandatory initial context are experimental
  defaults that a trusted baseline may lower or, in a later decision, revise.
- A remote-backed ordinary task requires standing project policy plus applicable
  P0 cooperative provenance, or future exact provider-backed authority, for the
  initial network fetch. A fetch is an external read and updates remote-tracking
  refs; it is not silently classified as purely local.
- The recorded rev5 source and registry digests identify the historical input.
  A digest can prove text identity, not semantic equivalence.

## 3. Confirmed decisions

### Stable decision register: V7-DEC-001–110

The following meanings are carried forward from rev5. Rev6 did not validly
reassign any of these IDs. Later amendments in this register control when a
summary would otherwise be ambiguous or inconsistent.

#### Execution modes and Git

- `V7-DEC-001`: `plan | supervised | auto` expresses intent only and is not
  authority.
- `V7-DEC-002`: `auto` executes only actions explicitly allowed by a trusted
  grant.
- `V7-DEC-003`: each main task uses an aggregate branch; stage branches merge
  back serially.
- `V7-DEC-004`: a sub-Agent report is only an evidence index; the main Agent
  verifies directly.
- `V7-DEC-005`: documents and tools provide cooperative constraints and
  deterministic detection, not permission isolation.
- `V7-DEC-006`: P0 implements no real external adapter; local Git remains a core
  capability.
- `V7-DEC-007`: each main task defaults to an independent worktree and a
  single-writer lease.
- `V7-DEC-008`: task, stable branch, remote visibility, and release advance
  separately.
- `V7-DEC-009`: semantic completion boundaries use `--no-ff`; baseline sync uses
  a normal merge.
- `V7-DEC-010`: split only at a real acceptance boundary; simple work uses the
  Simple profile.

#### Documents, state, and records

- `V7-DEC-011`: a verbatim Spec may be frozen only after a secret preflight.
- `V7-DEC-012`: Front Matter stores machine declarations; Markdown stores the
  contract, rationale, and human explanation.
- `V7-DEC-013`: the main Agent owns branch topology; an Executor may not switch,
  merge, rebase, or push.
- `V7-DEC-014`: `accepted` means the current candidate binding is valid, not an
  irreversible terminal state.
- `V7-DEC-015`: task records permanently retain their original path.
- `V7-DEC-016`: stage order expresses the default dependency; only exceptional
  dependencies use `depends_on`.
- `V7-DEC-017`: product deletion requires both trusted baseline policy and
  frozen-contract authority.
- `V7-DEC-018`: tasks use a fixed vocabulary and controlled transitions.
- `V7-DEC-019`: a non-Git project may be initialized only after safety checks.
- `V7-DEC-020`: a hotfix uses the remote stable baseline and separate authority.
- `V7-DEC-021`: the task path is `0b-tasks/<task-id>-<slug>/`.
- `V7-DEC-022`: the task ID uses a project-time-zone timestamp and a short random
  suffix.
- `V7-DEC-023`: stage Front Matter stores current declarations; the main-task
  progress table is derived.
- `V7-DEC-024`: `AGENTS.md` configures the project time zone; exact times use an
  ISO 8601 offset.
- `V7-DEC-025`: one Agent attempt is one implementation, repair, or review
  episode.
- `V7-DEC-026`: record only decisions affecting scope, architecture, risk,
  compatibility, or acceptance.
- `V7-DEC-027`: distinguish origin, validation, stage-baseline, and candidate
  SHAs.

#### Acceptance, recovery, and notification

- `V7-DEC-028`: acceptance criteria use stable IDs, observable outcomes,
  methods, and evidence.
- `V7-DEC-029`: one contract revision permits at most two ordinary repair rounds
  by default.
- `V7-DEC-030`: high-risk or uncertain work requires an independent Reviewer.
- `V7-DEC-031`: notification requires a narrow project grant; failure does not
  change engineering acceptance.
- `V7-DEC-032`: task YAML, `mode=auto`, and Agent claims are not durable grants.
- `V7-DEC-033`: a task lease lives in the Git common directory and is not
  version-controlled.
- `V7-DEC-034`: durable recovery guarantees only committed or explicit
  checkpoint state.
- `V7-DEC-035`: one file or ref may be atomic; a multi-resource operation must be
  reentrant, fail closed, and recoverable.
- `V7-DEC-036`: worktrees use a configurable path outside the repository and do
  not record machine-specific absolute paths.
- `V7-DEC-037`: commit understandable units; rewrite history only on an
  unshared, unhanded-off stage branch.
- `V7-DEC-038`: clean local resources only after integration proof and closed
  responsibility; never delete a remote branch automatically.

#### Spec, template, and model

- `V7-DEC-039`: arbitrary Markdown can be imported only as `draft`.
- `V7-DEC-040`: implementation, repair, and review handoffs must persist.
- `V7-DEC-041`: tooling proves structure and binding; the main Agent and
  Reviewer own semantic correctness.
- `V7-DEC-042`: provide one `nm-v7` CLI and no resident Runner.
- `V7-DEC-043`: Spec formatting creates a new candidate and never overwrites or
  silently changes the source.
- `V7-DEC-044`: `difficulty` and `risk` are independent fields.
- `V7-DEC-045`: provide a read-only model comparison report; do not duplicate
  implementation by default.
- `V7-DEC-046`: the recommended Spec requires only a minimum semantic core.
- `V7-DEC-047`: a stage file is a self-contained local contract; an Agent loads
  only relevant context.
- `V7-DEC-048`: the work-item envelope owns machine fields; Markdown owns
  semantic sections.
- `V7-DEC-049`: keep root `AGENTS.md` short and load detailed rules on demand.
- `V7-DEC-050`: C is the product candidate, A is the acceptance-record head, and
  M is the integration commit.
- `V7-DEC-051`: validation commands are invoked explicitly and bound to the
  candidate revision.
- `V7-DEC-052`: task types use a small fixed enum plus optional labels.
- `V7-DEC-053`: provide short Formatter, Executor, Reviewer, and Fixer prompts.

#### Version and project governance

- `V7-DEC-054`: branch names are flat.
- `V7-DEC-055`: an unstarted stage may be adjusted without changing the
  contract; history is never silently rewritten.
- `V7-DEC-056`: V7 remains experimental and preserves V1 through V6.
- `V7-DEC-057`: acceptance is scenario-based and constrains Simple overhead.
- `V7-DEC-058`: the Feishu adapter stays in P1 and does not depend on the V5
  Runner.
- `V7-DEC-059`: a project may pin a CLI version, but an inactive candidate is
  not a trust root.
- `V7-DEC-060`: non-secret project configuration is in `AGENTS.md` Front Matter.
- `V7-DEC-061`: the administrator-acceptance record binds a source-manifest
  digest and is not part of the bound source set.
- `V7-DEC-062`: source management, template generation, and project-installation
  ownership are distinct.
- `V7-DEC-063`: P0 retains only three core machine Schemas.
- `V7-DEC-064`: a local target update uses a clone-local lease and
  expected-old-SHA CAS.
- `V7-DEC-065`: only controlled record and evidence changes are allowed from C
  to A.
- `V7-DEC-066`: retain the complete scope but implement it in P0 and P1.
- `V7-DEC-067`: a project can have only one active control version at a time.

#### Authority and candidate closure

- `V7-DEC-068`: V7 uses a cooperative threat model.
- `V7-DEC-069`: acceptance binds contract revision, validation baseline,
  candidate revision, supporting evidence, and any required Reviewer receipt.
- `V7-DEC-070`: a field-level authority matrix selects fact sources; conflicts
  fail closed.
- `V7-DEC-071`: local integration, remote visibility, stabilization, and
  release/deployment are separate facts.
- `V7-DEC-072`: a required Reviewer is independent and binds the current
  candidate revision.
- `V7-DEC-073`: the state vocabulary is `draft | ready | in_progress | verifying
  | blocked | accepted | cancelled | superseded`.
- `V7-DEC-074`: the default deletion policy is `quarantine_unless_contract`.
- `V7-DEC-075`: a task enters `ready` only when open items are cleared, the
  contract is complete, and the revision digest is fixed.
- `V7-DEC-076`: init, update, and migration require a dry run first.
- `V7-DEC-077`: current gates use B or an accepted repository-external
  controller.
- `V7-DEC-078`: hotfix classification, stable integration, push, release, and
  reconciliation into `dev` require separate authority.
- `V7-DEC-079`: generated projects disable notifications by default.
- `V7-DEC-080`: difficulty affects model and decomposition; risk affects
  permissions and gates.
- `V7-DEC-081`: continuing P1, accepting a snapshot, activating a controller,
  and integrating `dev` are separate administrator decisions.

#### Exact invariants

- `V7-DEC-082`: repair count binds the contract revision; a new C does not reset
  it, and target sync is not a repair.
- `V7-DEC-083`: B/C/A/M enforce ancestry, parent, equal-tree, and CAS invariants.
- `V7-DEC-084`: `evidence_set_digest` hashes only explicitly selected supporting
  evidence.
- `V7-DEC-085`: a grant binds project, task, target, contract, controller,
  candidate, action, and anti-replay data.
- `V7-DEC-086`: an inactive P0 artifact cannot accept, authorize, activate, or
  integrate itself.
- `V7-DEC-087`: tooling never automatically destroys a dirty worktree.
- `V7-DEC-088`: known secret patterns are checked before persistence, without a
  claim to detect every secret.
- `V7-DEC-089`: automatic deletion excludes out-of-scope, ignored, untracked,
  symlink-escape, and trust-root paths.
- `V7-DEC-090`: the Simple profile has hard file, commit, and pause limits.
- `V7-DEC-091`: each role loads minimum context; tooling does not scan complete
  task history.
- `V7-DEC-092`: source, template, and ownership manifests are distinct concepts.
- `V7-DEC-093`: decisions use sequential revision labels and stable
  `V7-DEC-NNN` IDs.
- `V7-DEC-094`: `ready → in_progress` verifies implementation authority;
  `blocked` stores `resume_status`.
- `V7-DEC-095`: a candidate revision binds contract revision, B, and C.
- `V7-DEC-096`: a Simple receipt embeds supporting evidence; hard limits apply
  only to the first-success happy path.
- `V7-DEC-097`: a grant provider uses nonce and operation digest for idempotent
  recovery.
- `V7-DEC-098`: a candidate CLI may be product-tested but cannot be its own
  trust root.
- `V7-DEC-099`: validation uses structured argv, a restricted environment,
  side-effect classification, and complete secret handling.
- `V7-DEC-100`: P0 deletion permits only an administrator-confirmed exact path
  to a regular file tracked in B.
- `V7-DEC-101`: template manifest, ownership manifest, and safe init foundations
  belong to P0.

#### Boundaries added in rev5

- `V7-DEC-102`: `contract_revision_digest` covers every semantic and gating
  field.
- `V7-DEC-103`: `implementation_authority_ref` is trusted provenance for the
  administrator's implementation instruction.
- `V7-DEC-104`: the current candidate cannot change the safety configuration or
  action catalog used to review itself.
- `V7-DEC-105`: a grant uses `not_before`/`expires_at` and a fixed write-ahead
  journal order.
- `V7-DEC-106`: a lease uses owner token, expected head, and fencing generation.
- `V7-DEC-107`: manifests use domain-separated canonical digests; P0 implements
  safe `init apply`.
- `V7-DEC-108`: a Simple short request defaults to at most 4 KiB and preloaded
  workflow context to at most 16 KiB.
- `V7-DEC-109`: P0 has no real external adapter; a fake provider is not a
  production adapter.
- `V7-DEC-110`: newly reviewed safety, recovery, lease, init, and complexity
  scenarios enter the P0 tests.

### Decisions added or amended in rev6–rev9

- `V7-DEC-111` (`amends: V7-DEC-100, V7-DEC-107`): init transaction
  rollback/cleanup is a separate transaction-cleanup domain, not product
  deletion. It may remove only creations that the journal proves belong to the
  current transaction and still match exactly.
- `V7-DEC-112` (`superseded_by: V7-DEC-119`): workflow version and decision
  revision are represented separately; the then-current target was
  `workflow_version: V7 / decision_revision: rev6`.
- `V7-DEC-113` (`amends: V7-DEC-093`): an allocated decision ID never changes
  meaning. Supplement with a new `amends` ID; replace completely with
  `superseded_by`; moving a section does not change its ID.
- `V7-DEC-114` (`amends: V7-DEC-014, V7-DEC-018, V7-DEC-073,
  V7-DEC-094`): only `draft | ready | in_progress | verifying` may enter
  `blocked`; `accepted` does not enter it directly.
- `V7-DEC-115` (`amends: V7-DEC-069, V7-DEC-082, V7-DEC-095,
  V7-DEC-102`): `contract_revision_digest` binds revision identity, source
  identity, and all semantic and gating fields.
- `V7-DEC-116` (`amends: V7-DEC-021, V7-DEC-022, V7-DEC-060,
  V7-DEC-061, V7-DEC-062, V7-DEC-067, V7-DEC-092, V7-DEC-107`): a source
  manifest is a neutral source inventory and is explicitly in P0; restore the
  canonical task path, task ID, single project/config location, and single
  active control version.
- `V7-DEC-117` (`amends: V7-DEC-022, V7-DEC-024`): the default project time zone
  is IANA `Asia/Shanghai`; event time uses ISO 8601/RFC 3339 with its actual
  offset.
- `V7-DEC-118` (`amends: V7-DEC-057, V7-DEC-079, V7-DEC-086,
  V7-DEC-088, V7-DEC-089, V7-DEC-099, V7-DEC-100, V7-DEC-101,
  V7-DEC-109, V7-DEC-110`): restore the P0 mandatory validation commands,
  independent Reviewer, and safety test matrix; notification runtime tests
  remain in P1.
- `V7-DEC-119` (`supersedes: V7-DEC-112`): the administrator confirmed that the
  attached full text was decision revision rev6; the then-current register was
  `workflow_version: V7 / decision_revision: rev7` and superseded rev6. The two
  namespaces remained separate.
- `V7-DEC-120` (`supersedes: V7-DEC-119`): this full register is
  `workflow_version: V7 / decision_revision: rev8` and supersedes rev7. Existing
  decision text and history for V7-DEC-001–119 are not silently reassigned.
- `V7-DEC-121` (`amends: V7-DEC-030, V7-DEC-041, V7-DEC-057,
  V7-DEC-069, V7-DEC-072, V7-DEC-090, V7-DEC-096, V7-DEC-118`): the ordinary
  task Reviewer gate applies only when the frozen contract has
  `review_required=true`. Simple requires a trusted-baseline determination of
  `review_required=false`, so a missing Reviewer does not block its acceptance.
  A `task_candidate_review` is distinct from the mandatory P0
  `controller_source_technical_review`; the latter proves technical review only
  and grants no source acceptance, activation, or integration authority. Both
  use different `receipt_kind` values in the existing receipt Schema.
- `V7-DEC-122` (`amends: V7-DEC-063, V7-DEC-073`): the three core Schemas are the
  only public project-persisted contract Schemas, and the eight task states are
  the only user-visible state vocabulary. Internal errors, manifest formats,
  locks, leases, journal phases, authority records, and receipt kinds are not
  extra core Schemas or a second task state machine.
- `V7-DEC-123` (`amends: V7-DEC-011, V7-DEC-022, V7-DEC-039, V7-DEC-043,
  V7-DEC-046, V7-DEC-048, V7-DEC-075, V7-DEC-094, V7-DEC-103,
  V7-DEC-108, V7-DEC-116`): under separate standing or exact fetch authority,
  the trusted main control session first obtains B, then produces a compact
  Simple contract, preallocates its valid unused task ID, computes its digest,
  and issues implementation authority bound to B without adding a user-visible
  command. `task start` rechecks the clean baseline and B, creates the allowed
  non-protected task branch at B before any project write, and performs only an
  in-memory secret preflight, closed-Schema validation, digest calculation,
  implementation-authority validation, persistence, freeze, and guarded state
  transition. It does not invent ACs, infer risk, resolve ambiguity, or act as a
  Formatter. Missing or uncertain semantics remain `draft` for trusted control
  clarification; only a complete contract that fails Simple eligibility
  upgrades to Standard. Implementation authority binds repository/project,
  task, target ref, B, exact contract digest, allowed local action and path
  scope, active controller digest, issuer, control session, `not_before`,
  `expires_at`, and nonce. A task file, environment variable, or candidate
  branch cannot issue it.
- `V7-DEC-124` (`amends: V7-DEC-018, V7-DEC-029, V7-DEC-034,
  V7-DEC-035, V7-DEC-073, V7-DEC-094, V7-DEC-105, V7-DEC-106,
  V7-DEC-114`): `blocked → resume_status` is not a direct assignment. Resume
  reruns every entry gate for the destination. Resuming `in_progress`
  revalidates implementation authority; resuming `verifying` revalidates B, C,
  HEAD, candidate binding, and required evidence. Exhausting ordinary repair
  rounds enters `blocked`. `revise-contract` may freeze that revision and move
  `blocked → draft`; otherwise an authenticated, same-revision
  `additional_repair_allowance` must bind the contract digest, current attempt
  count, new finite limit, issuer, and expiry before guarded resume can permit
  another repair. It is issued by the candidate-external authenticated
  administrator control session and authorizes a separately gated
  `blocked → in_progress` transition without rewriting `resume_status`. In P1,
  every claim has `claim_attempt_id`; no-effect failures end as
  `aborted_pre_effect`; unknown effects or conflicting evidence end as
  `reconcile_required`; no new protected action starts until reconciliation.
  The same nonce and operation may be reclaimed idempotently, while one nonce
  with another operation is rejected.
- `V7-DEC-125` (`amends: V7-DEC-027, V7-DEC-051, V7-DEC-064,
  V7-DEC-068, V7-DEC-076, V7-DEC-077, V7-DEC-087, V7-DEC-099,
  V7-DEC-104, V7-DEC-110`): validation observes only current HEAD/index/tracked
  tree, the current task or aggregate ref, the target/tracking ref that supplied
  B, and explicitly bound controller/trust-root refs. Unrelated task refs may
  move concurrently. This detects but cannot prevent same-account mutation.
  Safety policy and the action catalog come from B or an accepted external
  controller, never C. Before an ordinary remote-backed task, an authorized
  `git fetch --prune origin dev` must succeed and B must equal exact
  `origin/dev`; local `dev` must not be divergent, and the task branch starts at
  B. P1 fetches the protected target
  again immediately before integration and again before push when push is a
  separate action. A moved target invalidates old validation, review,
  acceptance, and grant.
- `V7-DEC-126` (`amends: V7-DEC-012, V7-DEC-028, V7-DEC-046,
  V7-DEC-048, V7-DEC-069, V7-DEC-095, V7-DEC-102, V7-DEC-107,
  V7-DEC-115`): `task.md` contains one machine-locatable immutable contract
  block. Every human semantic input—goal, scope, non-goals, constraints, frozen
  assumptions, and ACs—is inside it; mutable state, progress, and receipts are
  outside. The digest encoding is fixed as follows:

  ```text
  frame(x) = uint64_be(byte_length(x)) || x

  contract_revision_digest =
    SHA-256(
      "nm-v7.contract-revision.v1\0" ||
      frame(canonical_gate_json) ||
      frame(contract_block_utf8)
    )
  ```

  The block is strict UTF-8 without BOM, uses LF, is Unicode NFC, includes its
  delimiters in the digest, and is rejected rather than silently normalized.
  The closed gate object uses a Spec-fixed canonical JSON encoding: array order
  is preserved, `null` is explicit, duplicate keys, floating-point values, and
  unknown gate fields are rejected. The Spec fixes domain bytes, framing,
  digest bytes, and lowercase-hex representation.
- `V7-DEC-127` (`amends: V7-DEC-093, V7-DEC-113, V7-DEC-118`): mechanical checks
  prove bytes, digests, IDs, and declared relations, not semantic equivalence.
  The rev5 full-source digest is
  `8e059ef378b313a7d0eb3a0e20f863c5852e0c7286f61b9a97379483687b2d58`.
  Extracting its 110 V7-DEC-001–110 definition lines, changing only bold ID
  delimiters to backticks, joining the UTF-8 lines in original order with one LF
  and appending exactly one final LF, produces the historical Chinese registry
  digest
  `0943e27357ea7bc7403f34cbd54d1812a4c6ec5467c4c7bc95f59dd1a53516ac`,
  identical to rev7. Applying the same ordered-line-plus-final-LF rule without
  formatting substitution to rev7's Chinese V7-DEC-111–119 definition lines
  produces
  `aedb76949bb0bd449226b0c47dc4aa150144646f88946a2f290ed3f0ae57ecbc`;
  the Chinese mirror preserves those lines exactly. Independent semantic review
  remains required for the English translation, meanings, and amendments;
  future tooling may only prove that reviewed text did not drift.
- `V7-DEC-128` (`amends: V7-DEC-032, V7-DEC-033, V7-DEC-061,
  V7-DEC-067, V7-DEC-069, V7-DEC-070, V7-DEC-077, V7-DEC-085,
  V7-DEC-086, V7-DEC-097, V7-DEC-103, V7-DEC-104`): the authority matrix is
  complete: Git owns tree, commit, ref, and topology facts; the envelope on the
  authoritative task ref owns current declarations and the frozen contract; A
  owns immutable technical evidence, task review, and task acceptance receipts;
  a candidate-external authenticated control session owns implementation
  authority; a P1 authenticated provider owns integration grants and claims;
  a candidate-external authenticated administrator control plane owns source
  acceptance, activation, active controller digest, task-recovery authority,
  additional repair allowance, and lease-takeover authority. Lease and journal data
  in the Git common directory are recovery state only and never authority.
  Ordinary task `accepted` may be produced by deterministic gates of the active
  controller; controller-source acceptance and activation may only come from
  the authenticated administrator control plane. Conflicts fail closed.
- `V7-DEC-129` (`amends: V7-DEC-050, V7-DEC-065, V7-DEC-083,
  V7-DEC-128`): tighten candidate
  topology to `parent(A) = C`, `parents(M) = [B, A]`, and `tree(M) = tree(A)`.
  A is a single-parent commit whose only parent is C, so no intermediate commit may temporarily
  change and restore a trust root. A stores the ordinary task acceptance receipt
  at the permanent task path. After P1 CAS, the integration receipt is not
  written back to A or M; it is create-once at
  `$GIT_COMMON_DIR/nm-v7/receipts/integration/<operation-digest>.json`, binds the
  observed target SHA, and survives task worktree and branch cleanup. It is
  clone-local recovery evidence, not cross-clone persistence. Before deleting
  the whole clone or closing remote-delivery responsibility, an authenticated
  provider or external audit store must retain the finalized receipt. The target
  ref and M topology remain the authoritative integration fact; a receipt never
  authorizes or overrides Git.
- `V7-DEC-130` (`amends: V7-DEC-047, V7-DEC-049, V7-DEC-057,
  V7-DEC-090, V7-DEC-091, V7-DEC-096, V7-DEC-108, V7-DEC-110`): the 16 KiB limit
  applies only to the exact UTF-8 output of `nm-v7 context render`. A Simple
  bundle includes the compact V7 role rules, the complete canonical contract
  block—including its ACs and the inline request appearing once—the relevant file
  index, delimiters, and minimum binding digests. It excludes raw source audit
  copies, Schemas, historical receipts, completed tasks, recovery manuals,
  platform/system prompts, conversation, ambient root rules loaded outside the
  renderer, and later Agent reads. `context render --report` records each input
  path, section, digest, and byte count, plus the ambient root `AGENTS.md` byte
  count separately. Tests assert renderer output and reads only; they do not
  claim to constrain later Agent behavior.
- `V7-DEC-131` (`amends: V7-DEC-006, V7-DEC-031, V7-DEC-035,
  V7-DEC-042, V7-DEC-050, V7-DEC-058, V7-DEC-064, V7-DEC-066,
  V7-DEC-071, V7-DEC-077, V7-DEC-078, V7-DEC-081, V7-DEC-083,
  V7-DEC-085, V7-DEC-097, V7-DEC-105, V7-DEC-106, V7-DEC-109,
  V7-DEC-110, V7-DEC-118`): P0 implements the local candidate closure
  `start → implementation → verify → A` and retains B/C/A, implementation
  authority, conditional review, contract digest, validation, safe init,
  manifests, deletion guards, and context rendering. P0 exposes `task
  integrate`, but it must return `integration_unavailable` without side effects
  before planned M, claim, protection journal, target lease, or ref mutation.
  Integration grant/provider interfaces, fake and real providers, claim/nonce
  recovery, protection journal, target lease, planned M, CAS, integration
  receipt, source acceptance, protected integration, and activation move
  together to P1. Their complete tests move with them; P0 instead tests the
  no-side-effect refusal.
- `V7-DEC-132` (`amends: V7-DEC-003, V7-DEC-007, V7-DEC-010,
  V7-DEC-025, V7-DEC-033, V7-DEC-036, V7-DEC-040, V7-DEC-045,
  V7-DEC-051, V7-DEC-057, V7-DEC-090, V7-DEC-096, V7-DEC-106`): Simple uses
  the current clean, eligible worktree. Before any project write, `task start`
  creates the allowed non-protected task branch at exact B in that worktree;
  CLI mutations use a command-scoped
  atomic lock and expected-head CAS, with no default extra worktree or
  long-lived lease. An extra worktree and Standard task-writer lease are used
  only for parallel top-level work, a real multi-writer case, cross-session
  handoff, or explicit isolation. After expiry, takeover requires clean state,
  exact expected head, no effect-unknown operation, generation CAS, and one of
  explicit release, trusted session-termination evidence, or scoped
  administrator recovery authority. Simple upgrades only when eligibility,
  semantic scope, risk, deletion/migration/external/trust-root action,
  concurrency, a real stage/review/sub-Agent/handoff boundary, or a hard limit
  requires it. An authorized baseline-freshness fetch required by standing
  project policy is preflight and does not itself trigger an upgrade; a second
  receipt alone does not. On the first-success happy path, the task directory
  has one file before A and at most two after A, B..C has at most one
  implementation commit, A adds exactly one acceptance commit, and there is no
  administrator pause through A; an invoked `integrate` may cause one post-A
  decision stop. One failed validation may add one repair commit and remain
  Simple; exceeding these commit, file, or pause bounds upgrades to Standard.
  Stage checks are scoped and the final C receives one complete validation. P0
  stores only a model identifier or `unknown`; detailed model episodes and
  comparison move to P1.
- `V7-DEC-133` (`amends: V7-DEC-019, V7-DEC-060, V7-DEC-076,
  V7-DEC-101, V7-DEC-107, V7-DEC-111`): P0 init accepts an empty target or a
  target in which every managed path is absent or already exactly owned by the
  same manifest. A conflicting existing `AGENTS.md` or any other managed path
  returns `update_required` before writes; transactional update of an existing
  project belongs to P1. Before each create, the external journal durably writes
  and syncs transaction ID, canonical path, `absent_before`, type, mode, and
  expected digest; only then may the creation occur. Rollback follows that
  write-ahead proof. A second apply is read-only success only when the ownership
  manifest and every managed digest match exactly.
- `V7-DEC-134` (`supersedes: V7-DEC-120`): this full register is
  `workflow_version: V7 / decision_revision: rev9` and supersedes rev8. The
  frozen rev8 English and Chinese full-source SHA-256 digests are respectively
  `d3648c96e19a37d4f26f001b21922f3b4964c6a8ec5483e1717d284039c18bb2` and
  `da5ebc441ee57904d154c3571c7b351c9d573519057e84f2e23297c657e2c1f1`.
  They prove byte identity only. Existing decision text and history for
  V7-DEC-001–133 are not silently reassigned.
- `V7-DEC-135` (`amends: V7-DEC-050, V7-DEC-083, V7-DEC-087,
  V7-DEC-089, V7-DEC-095, V7-DEC-099, V7-DEC-104, V7-DEC-110,
  V7-DEC-123, V7-DEC-125, V7-DEC-129, V7-DEC-131, V7-DEC-132`): candidate
  closure covers history and the verification worktree. Let
  `candidate_commits = Reachable(C) \ Reachable(B)`. The
  `candidate_touched_entries` set is the union of recursive leaf-entry deltas
  for every parent edge of every candidate commit. Regular-file, symlink, and
  gitlink OID/mode/type changes count; implicit directory-tree OIDs do not.
  Rename/copy inference is disabled, so old-path deletion and new-path addition
  are checked separately. The Spec uses case-sensitive, strict UTF-8 NFC,
  repository-relative path bytes and only typed exact-path or directory-prefix
  scope entries; it rejects glob/negation, absolute, empty, dot-segment,
  non-representable, and case-colliding paths. Controlled workflow records must
  match a Spec-fixed, CLI-managed exact path, field, and content allowlist.
  Every product path and non-cleanup action touched anywhere in candidate history
  must be allowed by the frozen contract, the applicable implementation-scope
  record—P0 cooperative provenance or P1 provider-backed authority—and the
  B-bound action catalog. The final `tree(B) → tree(C)` delta defines product
  actions. Product deletion means an
  entry present in B and absent from final C and retains its additional dual
  authority. Removing a history-only entry that its most recent scope-admission
  gate proved absent, was first introduced after that gate, and is absent from
  both B and final C is
  `candidate_cleanup`, not product deletion;
  it is an implicit recovery action only when its original addition was allowed,
  requires the same path scope, and grants no deletion capability. Any Simple
  trust-root touch fails. Standard
  also requires an available B/external-controller-bound extension, exact
  path/action bindings, and applicable review; current gates still use B or an
  accepted external controller, and C can affect only later tasks. At verify
  entry and after the complete validation set, HEAD and task ref must equal C,
  index and tracked worktree must equal `tree(C)`, all non-ignored untracked
  entries must be absent, and every ignored or non-ignored untracked entry under
  product scope, controlled-record paths, or trust-root paths must be absent.
  Entry enumeration is recursive and includes directories and symlinks.
  Validation temporary output uses a directory outside both the worktree and
  Git common directory. Failure invalidates evidence, prevents A, and preserves
  the scene without clean or deletion. Scope-external ignored dependencies and
  caches are not hashed, and P0 does not claim hermetic validation.
- `V7-DEC-136` (`amends: V7-DEC-002, V7-DEC-005, V7-DEC-032,
  V7-DEC-068,
  V7-DEC-077, V7-DEC-094, V7-DEC-103, V7-DEC-109, V7-DEC-123,
  V7-DEC-124, V7-DEC-128, V7-DEC-131, V7-DEC-132`): P0 implementation,
  fetch, additional-repair, task-recovery, and lease-takeover authority records
  are cooperative controller provenance for external administrator
  instructions, not cryptographic capabilities, issuer-authentication proofs,
  or an adversarial security boundary. Every record binds an authority class,
  canonical encoding/digest, declared issuer/session, applicable controller,
  local-wall-clock `not_before`/`expires_at`, and class-scoped nonce. Fetch
  provenance binds repository/project, canonical remote identity, target
  ref/refspec, fetch action and policy, and optionally an administrator-supplied
  expected remote SHA; it cannot require a not-yet-obtained B, task, or contract.
  Implementation provenance is issued after fetch and binds exact B, task,
  contract digest, controller, action, and path scope. Additional-repair,
  recovery, and lease-takeover records use their separately fixed current-state
  bindings. Classes are never interchangeable. The CLI maintains a durable
  `{authority_class, nonce} → record_digest` claim for idempotent same-pair reuse
  and rejection of a different digest within that class. The same nonce literal
  may exist independently in another class, but a record can never be presented
  as or converted into another class. The claim is
  a candidate-external internal record under `$GIT_COMMON_DIR/nm-v7/`, written
  and synced under the existing command lock after all read-only gates and
  before the first authorized mutation. It survives process restart, serializes
  concurrent use, supports same-pair recovery, rejects a different digest, and
  is retained until the bound operation or task responsibility closes. Task files, environment
  variables, and candidate-controlled refs or paths cannot issue provenance.
  P0 local `auto` actions require the exact administrator instruction and this
  cooperative gate; it is not a trusted/durable grant. P1 protected or external
  `auto` actions require a real-provider grant. P0 has no trusted clock,
  asynchronous revocation, or
  cryptographic issuer verification, and a malicious same-account process can
  forge, alter, or bypass local records. Only class-applicable cancellation,
  supersession, contract revision, binding mismatch, and expiry invalidate a
  record; an unrelated task/contract event does not invalidate fetch provenance.
  Authenticated,
  non-forgeable authority requires a real P1 provider with explicit trust,
  clock, replay, and revocation semantics.
- `V7-DEC-137` (`amends: V7-DEC-090, V7-DEC-096, V7-DEC-102,
  V7-DEC-115, V7-DEC-123, V7-DEC-124, V7-DEC-130, V7-DEC-132`): profile is
  selected before contract digest, authority provenance, and S, and is immutable
  within that contract revision. `task start` validates but never changes it.
  The 4096-byte request and 16384-byte initial-context limits remain start-time
  eligibility gates. Commit and pause budget overruns, and overruns composed
  only of otherwise allowed controller records, set mutable
  `observed_complexity=over_budget`; they do not change profile, digest, or
  authority and grant no capability. An unallowed task/product path remains a
  candidate-closure failure, not a budget overrun. A newly required deletion,
  migration, external/protected action, trust-root action, high-risk review,
  stage, sub-Agent, handoff, concurrency, or wider permission enters existing
  `blocked` with reason `profile_upgrade_required`; continuation requires a new
  Standard contract revision, digest, and authority. No silent profile mutation
  or ninth state is added.
- `V7-DEC-138` (`amends: V7-DEC-003, V7-DEC-013, V7-DEC-018,
  V7-DEC-034, V7-DEC-035, V7-DEC-039, V7-DEC-043, V7-DEC-050,
  V7-DEC-073, V7-DEC-075, V7-DEC-083, V7-DEC-094, V7-DEC-123,
  V7-DEC-124, V7-DEC-125, V7-DEC-128, V7-DEC-129, V7-DEC-132`): before any
  project write, ref
  mutation, branch creation, worktree switch, or task-ID consumption, `task
  start` completes secret, closed-Schema, completeness, profile-consistency,
  digest, cooperative-provenance, ID/ref-uniqueness, B, cleanliness, and
  baseline checks. Before S it also requires no non-ignored untracked entry
  anywhere and no ignored or non-ignored untracked entry under product scope,
  controlled-record paths, or trust-root paths, using the recursive entry rules
  of V7-DEC-135. The same scope-admission gate runs against the complete
  replacement scope before any `revise-contract` revision-start commit or new
  authority becomes effective; its scope and empty-set digest are stored in the
  controlled revision record. Deterministic preflight failure has no such side
  effect. An
  incomplete request returns `contract_incomplete` with a bounded missing-field
  summary and does not persist a project draft. Standard Formatter or trusted
  control prepares draft candidates outside the project; start accepts only a
  complete candidate. A successful start creates CLI-owned start-contract
  commit S with `parent(S)=B`, containing only the controlled task envelope,
  frozen contract, and `state=in_progress` after the ready/in-progress gates.
  It creates and attaches the task ref, and returns only with
  `HEAD=task_ref=S`, index and tracked worktree equal `tree(S)`, and clean
  eligible worktree. The Agent advances that ref through implementation commits.
  Budget-conforming first-success Simple topology is `B-S-C-A`; one failed
  candidate uses `B-S-I-C-A`, where I is the failed implementation and C is
  always final. S and A are not implementation commits; those budget cases have
  respectively three or four commits after B. Extra otherwise-authorized
  implementation commits only set observed complexity. In every case S is an
  ancestor of C, verify requires `HEAD=task_ref=C`, never stages or commits Agent
  product changes, and creates A only after all gates pass by
  `CAS(task_ref, old=C, new=A)`, with `parent(A)=C`.
  P0 `verifying` is a command-local derived state under the command lock, bound
  to exact C; it is not committed or stored as `resume_status`. The task-ref
  envelope remains authoritative for durable declarations, while one Git-common
  command checkpoint is recovery state only and adds no state vocabulary. An
  interruption discards all partial evidence and returns to the prior durable
  state when its binding remains valid; otherwise it reports `blocked` with
  `resume_status=in_progress`. The next verify reruns the complete set. A is
  never rewritten; post-acceptance rework advances through a descendant C and a
  new A. No state-only commit is added on the budget-conforming implementation,
  repair, or verify path. An identical existing S is idempotent only after the
  clean eligible worktree is attached at S; a conflicting B, digest, ref, or
  worktree fails closed. `revise-contract` likewise writes a single
  revision-start commit only after the complete replacement revision and new
  authority pass preflight; it does not persist a half-complete draft.
- `V7-DEC-139` (`amends: V7-DEC-030, V7-DEC-041, V7-DEC-044,
  V7-DEC-069, V7-DEC-072, V7-DEC-075, V7-DEC-080, V7-DEC-121,
  V7-DEC-123`): the closed Schema and start/revision gates enforce
  `risk=high ⇒ review_required=true`; low risk may still explicitly require
  review, while Simple requires `risk=low` and `review_required=false`. V7 adds
  no uncertainty Boolean or risk engine. Unresolved semantic uncertainty makes
  the contract incomplete; material residual uncertainty accepted by the
  administrator is classified high risk. The CLI does not infer risk, but
  rejects the invalid field combination before writes. Runtime risk changes use
  the new-revision path from V7-DEC-137.
- `V7-DEC-140` (`amends: V7-DEC-047, V7-DEC-049, V7-DEC-057,
  V7-DEC-091, V7-DEC-096, V7-DEC-099, V7-DEC-108, V7-DEC-110,
  V7-DEC-125, V7-DEC-130`): V7-owned mandatory initial context is the exact
  renderer output plus every V7-owned rule byte automatically injected or
  required before a role's first task action. V7 ownership comes only from the
  ownership manifest or exact managed-section markers; mixed project text is
  never inferred as V7-owned. V7-generated root-rule bytes are included;
  platform/system prompts and project-owned non-V7 guidance are excluded and
  reported separately. Simple and each implemented Standard role use the same
  16384-byte UTF-8 ceiling and require no other V7 Spec, Schema, history, or
  recovery document on the happy path. Later business-file and exception-driven
  reads are outside this initial metric. Redaction precedes digest, display, and
  persistence. Every validation action records exit/signal, raw and redacted
  byte counts, separate domain-framed SHA-256 digests of redacted stdout and
  stderr, and a truncation flag. Each stream receives a fixed 2048-byte excerpt
  budget split into 1024-byte UTF-8-safe head and tail, without cross-stream
  reallocation. One P0 structured CLI result and one canonical receipt are each
  at most 16384 bytes. Required identity, binding, status, digest, and AC-result
  fields are never truncated; excerpt budgets are allocated in frozen AC/action
  order and only excerpts may be shortened or omitted. If required fields alone
  exceed the ceiling, A is not created and `receipt_budget_exceeded` returns a
  bounded result. Exception and scope-violation summaries use the same policy.
  P0 stores no raw digest or full per-command log, and receipts/history are not
  in the default bundle.
- `V7-DEC-141` (`amends: V7-DEC-006, V7-DEC-031, V7-DEC-045,
  V7-DEC-053, V7-DEC-057, V7-DEC-058, V7-DEC-066, V7-DEC-071,
  V7-DEC-076, V7-DEC-078, V7-DEC-081, V7-DEC-100, V7-DEC-101,
  V7-DEC-104, V7-DEC-107, V7-DEC-109, V7-DEC-110, V7-DEC-118,
  V7-DEC-131, V7-DEC-133`): delivery
  uses independently authorized and reported slices. `P0-core` is the Simple
  and zero-stage Standard aggregate runtime: contract, immutable verbatim
  Standard source, cooperative provenance, S/task branch, Agent C, history
  scope, untracked gate, structured validation, conditional Reviewer, A,
  context, and the fail-closed integrate stub.
  `P0-install` is the three manifests, init dry-run/apply, external journal,
  rollback/recovery, template, and Init Skill; both slices are required before
  claiming complete P0. `P0-standard-extension` adds Formatter, stages,
  sub-Agent/handoff, optional worktree/lease, and positive
  deletion/trust-root workflows; a request needing an unavailable extension
  fails closed. `P1-core` is real provider-backed authority and protected `dev`
  grant, claim, journal, lease, planned M, CAS, and integration receipt.
  Updater/migration, hotfix/stable/push, release/deploy, notification, model
  comparison, and controller-lifecycle capabilities are separate optional
  extensions with their own authorization and acceptance. Availability comes
  only from a capability catalog bound to B or an accepted external controller;
  C, a task, or the environment cannot enable a slice. Completion of one slice
  never implies another. The P0 default bundle shows only `task start →
  implementation → task verify`; the integrate stub remains callable and
  tested but is omitted. Verify returns `task_status=accepted`,
  `candidate_scope=local`, and `integration_available=false`, without adding an
  `accepted_local` state.

## 4. Scope

### P0: local candidate closure

`P0-core` contains the daily runtime:

- English V7 implementation Spec and complete Simplified Chinese administrator
  mirror, short root rules, recommended Spec, compact-contract input, main-task
  and receipt templates, immutable verbatim Standard source storage, and exactly
  the three existing core Schemas.
- In-memory secret preflight, canonical contract revision, frozen profile,
  cooperative controller provenance, guarded state/revision transitions, and
  guarded resume.
- Simple plus zero-stage Standard aggregate execution, cooperatively authorized baseline
  fetch, S/task branch, command-scoped lock, Agent C, history/path/action scope,
  worktree/untracked closure, and B/S/C/A topology.
- Structured final validation, trusted action classification, secret handling,
  conditional ordinary-task Reviewer, bounded evidence/output, A, and
  `context render` with V7-owned initial-context accounting.
- One model identifier or `unknown`, the independent technical Reviewer for the
  V7 source candidate, and the callable but default-hidden no-side-effect
  `task integrate` refusal.

`P0-install` contains the safe distribution path:

- `template/v7`, the neutral source, template, and project-ownership manifests,
  `init --dry-run`, no-conflict `init apply`, external write-ahead init journal,
  rollback/recovery, and the Init Skill.

Both slices are required before claiming complete P0. All installations remain
inactive and P0 does not update `dev`.

`P0-standard-extension` is separately deliverable and contains the Standard
Formatter, stage templates and branches, sub-Agent/handoff, optional
worktree/lease/checkpoint, and positive
deletion/trust-root workflows. A request that needs an unavailable extension
fails closed. Availability comes only from the B/external-controller-bound
capability catalog; none of this enters the Simple default bundle.

### P1: protected and external closure

`P1-core` contains only the protected `dev` closure:

- The first administrator-selected real provider for authenticated
  implementation/control and integration authority, plus its test-only fake.
- Grant/claim/nonce recovery, protection journal with failure outcomes, target
  lease, planned M, CAS, and durable integration receipt.
- Independent source review and source acceptance needed for that provider,
  separately authorized integration, and final-position digest recomputation.

Separate optional extensions contain existing-project update/migration;
hotfix/stable/push; release/deployment; Feishu notification; detailed model
episodes/comparison; and final controller activation. Each has its own authority
and acceptance and does not block or follow automatically from `P1-core`.

### Out of scope

- Changing or deleting V1 through V6 to accommodate V7.
- A resident Runner, database, event system, heartbeat service, fourth core
  Schema, or second user-visible task state machine.
- Extra Simple happy-path roles, stages, or pauses.
- Default push, release, deployment, notification, or production access.
- Enabling the P1 fake provider through CLI, environment variables, or project
  configuration.
- Treating test success as real authority, acceptance, or activation.
- Persisting full conversations, per-command logs, or unredacted secrets.
- Claiming cryptographic issuer identity or hermetic validation from P0 checks.
- Automatic multi-model duplicate implementation.

## 5. Operational design

### 5.1 Input, contract, and authority

- Formal Specs and Simple inline requests receive an in-memory known-secret
  preflight before persistence.
- Standard stores an immutable verbatim source snapshot whose commands remain
  inert. Simple stores its short request once inside the immutable contract
  block.
- `task.md` is the only canonical task contract. Raw input is immutable evidence,
  not a second contract authority.
- After a cooperatively authorized fetch preflight obtains B, the administrator
  or control session supplies a complete compact contract, preallocated unused
  task ID, frozen profile, and cooperative implementation-authority provenance
  bound to B. The profile is selected before digest and provenance issuance.
- Fetch provenance uses its remote/ref/policy binding and is never accepted as
  implementation provenance. Implementation provenance is issued only after B
  and the exact contract digest exist; all other provenance classes use their
  fixed class-specific binding matrix.
- `task start` performs every deterministic preflight before project or ref
  mutation, accepts only a complete contract, and never fabricates semantics or
  changes profile. Failure returns a bounded error such as
  `contract_incomplete` without consuming the task ID or persisting a draft.
- Once scope is known, start—and every revision that admits a new path or
  trust-root scope—recursively applies the same global non-ignored and scoped
  ignored/non-ignored untracked gate as verify before claiming new provenance or
  writing its start record.
- After those read-only gates, start durably claims the provenance nonce under
  the command lock before its first mutation. A crash may leave only that
  recovery claim; an exact retry reuses it and a different binding is rejected.
- Standard Formatter or trusted control may prepare and update a draft candidate
  outside the project, with mapping and unresolved-gap reports. It becomes
  authoritative only when complete and successfully persisted by start or
  `revise-contract`; this preparation is absent from the Simple bundle.
- Successful start creates S with `parent(S)=B`, freezes the contract in its
  controlled task envelope, records `state=in_progress` after both entry gates,
  creates and attaches the task ref at S, and returns with
  `HEAD=task_ref=S` and tracked state equal `tree(S)`. A matching S is
  idempotent only from a clean eligible worktree; any identity, B, digest, ref,
  or worktree conflict fails closed.

### 5.2 State, revision, and digest

The task graph is:

```text
draft → ready → in_progress → verifying → accepted
verifying → in_progress
accepted → verifying
draft|ready|in_progress|verifying → blocked
blocked → guarded resume to resume_status
blocked --[revise-contract]→ draft
blocked --[additional_repair_allowance]→ in_progress
draft|ready|in_progress|verifying|blocked → cancelled|superseded
accepted --[no integration fact AND no pending-recovery fact]→ cancelled|superseded
```

- `ready → in_progress`, and every resumed entry to `in_progress`, validates the
  current P0 cooperative provenance or, when implemented, P1 provider-backed
  authority.
- Entering `blocked` atomically stores its guarded resume target. P0 never stores
  `verifying` as that target; an interrupted verification discards partial
  evidence and resumes only by rerunning the complete set from `in_progress`.
- Waiting for integration authority or target recheck remains `accepted`.
- In P0, `verifying` is a command-local derived state bound to exact C, not a
  task-ref commit. A command checkpoint in the Git common directory is recovery
  state only. A binding invalidation after acceptance enters this derived state;
  interruption returns to the prior durable state if still valid, otherwise to
  `blocked` with `resume_status=in_progress`. A later candidate descends from
  the old A; A is never rewritten.
- Pre-integration `accepted` may enter `cancelled | superseded` only when there
  is no local or remote integration fact and no prepared, claimed, or
  effect-unknown operation. An integrated product issue creates a successor,
  hotfix, or rollback task.
- Profile is immutable within a contract revision. A new capability, permission,
  or material risk that invalidates the profile enters
  `blocked(profile_upgrade_required)`; only a complete new revision, digest, and
  authority may continue it.
- Semantic contract changes use `revise-contract` and freeze the old revision.
  The complete replacement, full-scope admission gate, and new authority are
  preflighted before one revision-start commit records the logical `blocked →
  draft → ready → in_progress` gate sequence and its empty-set digest. No
  half-complete project draft is persisted. A changed task identity or core goal
  creates a successor.
- `cancelled` and `superseded` are terminal task states. Their immutable receipts
  preserve the prior state, reason, actor provenance, and time.

The candidate digest remains:

```text
candidate_revision_digest =
  SHA-256(
    "nm-v7.candidate-revision.v1\0" ||
    frame(contract_revision_digest_bytes) ||
    frame(B_bytes) ||
    frame(C_bytes)
  )
```

The canonical gate object includes project, task, revision and parent identity;
source snapshot digest; profile, difficulty, risk, and `review_required`; target
and target ref; requested action classes and path scope; `delete_allow`; and
every other closed-Schema machine gate. Goal, success criteria, scope,
non-goals, constraints, frozen assumptions, and all ACs occur only in the exact
contract block bytes. Mutable status/time, attempts, handoffs,
`observed_complexity`, model metadata, evidence/review/receipts,
authority/grant/lease/journal, and B/S/C/A/M are excluded from both digest
inputs.

### 5.3 Candidate, evidence, and acceptance

P0 enforces:

```text
B is an ancestor of C
parent(S) = B
S is an ancestor of C
HEAD = task_ref = C before acceptance
parent(A) = C
CAS(task_ref, old=C, new=A)
candidate_commits = Reachable(C) \ Reachable(B)
candidate_touched_entries =
  union of recursive leaf-entry deltas for every parent edge of candidate_commits
tree(A) differs from tree(C) only by the C-to-A allowlist
```

- S is the CLI-managed start-contract commit. C is the final product candidate. A
  adds only controlled acceptance state, C and revision bindings, bounded
  summaries, and immutable receipts.
- C does not record its own SHA or candidate digest. A does not record its own
  SHA.
- Recursive regular-file, symlink, and gitlink OID/mode/type deltas are checked;
  implicit directory-tree OIDs are not. Rename/copy inference is off, so both
  deletion and addition paths are checked. The fixed exact/prefix matcher from
  V7-DEC-135 rejects every unsupported path. CLI-managed workflow records must
  exactly match the fixed B-to-C path/field/content allowlist. Every history-
  touched product path and non-cleanup action must satisfy contract scope, the
  applicable P0 cooperative or P1 provider-backed implementation scope, and the
  B-bound action catalog. Product deletion authority is evaluated on the final
  B-to-C delta.
  Removing a candidate-created entry absent from both B and final C is allowed
  `candidate_cleanup` only when its addition was allowed; it remains within the
  same path scope and grants no deletion power.
- Simple forbids any trust-root touch. Standard additionally requires the
  capability catalog to enable the extension, exact path/action bindings, and
  applicable review; a changed trust root cannot govern the task that changes
  it.
- The path and field allowlists forbid contract, AC, risk, deletion authority,
  project config, Schema, provider, action catalog, or trust-root changes from C
  to A.
- All required ACs run once on final aggregate C. Stage checks are scoped and
  historical.
- `evidence_set_digest` covers only explicitly selected supporting evidence, not
  acceptance or integration receipts.
- When `review_required=true`, the Reviewer did not implement or repair the
  candidate and binds contract revision, B, C, candidate digest, and findings.
  Missing, stale, non-independent, `unable`, `changes_required`, or unresolved
  blocking review prevents acceptance. With `review_required=false`, no task
  Reviewer receipt is required. `risk=high` with `review_required=false` is
  rejected before task persistence.

### 5.4 Simple, Standard, and context

Simple requires one goal, one writer, `difficulty=low`, `risk=low`,
`review_required=false`, no deletion,
migration, contract-requested external/protected action, trust-root change,
Reviewer, handoff, sub-Agent, or real stage boundary, plus the 4096/16384-byte
limits. A cooperatively authorized baseline-freshness fetch required by standing project
policy is preflight and does not itself make the task Standard.

The P0 success path is:

```text
nm-v7 task start
→ start-contract commit S
→ Agent implementation and committed final candidate C
→ nm-v7 task verify
→ accepted candidate A
→ task_status=accepted, candidate_scope=local,
  integration_available=false
```

- `task integrate` remains callable and tested. In P0 it returns
  `integration_unavailable` without side effects, but it is absent from the
  default rendered workflow. P1 executes it only with an exact provider-backed
  grant.
- On the budget-conforming Simple path, the task directory contains only
  `task.md` before acceptance and adds at most one receipt. An otherwise allowed
  controller-record overrun is observed, while an undeclared path fails closure.
  This does not restrict product-file changes elsewhere within scope.
- Simple creates no stage, evidence directory, ordinary log, default extra
  worktree, persistent lease, Formatter, sub-Agent, Fixer, or Reviewer.
- Budget-conforming first success uses `B-S-C-A`; one actual repair uses
  `B-S-I-C-A`, with I the failed candidate and C the final candidate. S and A do
  not count as implementation commits. Extra authorized commits are observed;
  every topology still requires S ancestor C, `task_ref=C`, and CAS from C to A.
  Verify never stages or commits Agent product changes.
- Commit/pause or otherwise allowed controller-record budget overruns set
  mutable `observed_complexity=over_budget` and do not alter profile. An
  undeclared file or newly required capability still fails closure or requires a
  new Standard revision.
- V7-owned mandatory initial context is renderer output plus automatically
  injected or pre-action V7 rule bytes. It is self-contained for the happy path
  and remains within 16384 bytes for Simple and each implemented Standard role.
  Platform, system, and project-owned non-V7 context is reported separately;
  later business reads are outside the metric.

### 5.5 Git, validation, locking, and recovery

- For a remote-backed ordinary task, cooperative control provenance permits
  preflight to fetch
  `origin/dev` and records exact B. After the contract and authority are bound,
  `task start` confirms the working tree and scoped ignored paths satisfy the
  V7-DEC-135 entry gate, local `dev` is not divergent, and the tracking ref still
  equals B. Only after all other start gates and the durable nonce claim pass
  does it create S, attach the allowed task ref, and return at clean
  `HEAD=task_ref=S`.
- The main Agent owns topology. A worker commits only on its assigned branch and
  does not switch, merge, rebase, push, or update a protected ref.
- Independent top-level tasks may use separate worktrees; work inside one task
  is serial by default.
- P0 CLI writes use a command-scoped lock plus expected-head CAS. Only an
  available `P0-standard-extension` may use a persistent writer lease when
  parallelism, handoff, or isolation makes it necessary.
- Durable recovery guarantees only commits or explicit checkpoints. Dirty or
  unknown state is preserved for recovery; tooling never reset, clean, stash,
  checkout, delete, or overwrite it automatically.
- Validation uses structured argv, `shell=false`, a fixed cwd, and a strict
  environment allowlist with no grant, webhook, SSH, or production credential.
- Only actions marked local by B or an external accepted action catalog may
  spawn. Unknown or external actions are rejected before spawn.
- At verify entry and after the complete validation set, require
  `HEAD=task_ref=C`, index and tracked worktree equal `tree(C)`, no non-ignored
  untracked entry anywhere, no ignored or non-ignored untracked entry under
  product scope, controlled-record paths, or trust-root paths, and the scoped
  refs from V7-DEC-125 unchanged. Recursive enumeration includes directories and
  symlinks. A mismatch invalidates evidence and preserves the scene without
  automatic cleanup.
- Validation uses `TMPDIR` and declared temporary output outside both the
  worktree and Git common directory. P0 does not scan every ignored dependency
  or claim hermetic execution.
- Output and exceptions are redacted before digest, display, or persistence.
  Each action stores raw/redacted byte counts, separate framed digests of the
  redacted streams, fixed 1024-byte head/tail per stream, and truncation flags.
  Required receipt fields never truncate; if they alone exceed 16384 bytes,
  `receipt_budget_exceeded` prevents A. P0 stores no raw digest or full log.

### 5.6 Deletion, manifests, and init

- Product deletion always requires both B's trusted policy and the frozen
  contract's administrator-confirmed exact path. `P0-core` rejects the positive
  action; only a capability-catalog-enabled `P0-standard-extension` may permit a
  regular file tracked in B. Globs, directories, submodules, symlinks,
  ignored/untracked or out-of-scope paths, trust roots, and quarantine bypass
  remain rejected.
- V7-DEC-135 `candidate_cleanup` is separate: it may remove only an in-scope
  candidate-created entry absent from both B and final C and never authorizes a
  final product deletion.
- Source, template, and ownership manifests are separate. A source manifest is
  a neutral exact inventory and produces no acceptance or activation.
- A manifest excludes itself and administrator acceptance records from entries,
  stores no self-digest, and is digested by the caller using domain-separated
  canonical bytes.
- P0 init never overwrites or transactionally edits a conflicting managed path.
  Such a target requires the P1 updater.
- The init journal lives outside the target and binds controller/source
  manifest, target root, and transaction ID. It syncs each create intent before
  creation.
- Rollback removes only a regular file created by this transaction, absent
  before apply, and still matching type, mode, and digest. It removes directories
  in reverse order only after safe child-by-child cleanup and only when empty.
- Drift, replacement, symlink, unknown content, out-of-scope paths, or an
  incomplete journal preserves the scene and returns `recovery_required`.
- An exact ownership-manifest match makes a second apply read-only success.

### 5.7 P1 integration and controller lifecycle

P1 restores the complete integration invariant:

```text
B is an ancestor of C
parent(A) = C
parents(M) = [B, A]
tree(M) = tree(A)
CAS(target_ref, old=B, new=M)
```

- A grant binds repository/project, task, target, contract/candidate revision,
  active controller source digest, B, A, acceptance receipt, action, planned M,
  control session, nonce, `not_before`, and `expires_at`.
- The selected real provider defines and enforces its verifier or trusted IPC,
  issuer trust roots, clock/skew rules, replay behavior, and revocation policy.
  Only that provider-backed path may claim authenticated or non-forgeable
  implementation, recovery, source, or integration authority.
- Provider claim uses `{nonce, operation_digest}`. The same pair is idempotent;
  one nonce with a different operation is rejected.
- The protection journal orders planned M, prepared, claim attempt, claimed,
  target/time recheck, CAS, `cas_applied`, and finalized, with
  `aborted_pre_effect` and `reconcile_required` outcomes.
- Expiry before CAS requires a new grant. After a proven CAS, recovery only
  completes records and never repeats the protected effect.
- A target lease is separate from a task-writer lease and uses owner token,
  expected head, generation, and expiry.
- Local integration, remote visibility, stable promotion, release, and
  deployment remain separate facts and authorities.
- `P1-core` source closure ends at: independent final source review →
  authenticated administrator acceptance of the exact source digest → separate
  exact integration authority → final target fetch and final-position digest
  recomputation → CAS and finalized receipt. When the controller-lifecycle
  extension is delivered, it then requires a separate activation of that exact
  accepted and integrated digest.
- A candidate change to controller, Schema, provider, action catalog, deletion
  policy, or protected-branch config applies only to a later task.

## 6. Risks and resolved blockers

- A same-account Agent can bypass local tooling. Real isolation still requires
  repository-external permissions, branch protection, or an OS/network sandbox.
- P0 cooperative provenance detects deterministic field and binding mismatch;
  it does not authenticate an issuer, provide a trusted clock or asynchronous
  revocation, or prevent a malicious local process from forging or bypassing it.
- Candidate-history and worktree checks detect scoped Git closure failures but
  do not hash every scope-external ignored dependency/cache or provide hermetic
  execution.
- Secret detection is heuristic.
- P0 has no protected integration or real provider; every such action fails
  closed.
- Final-candidate full validation costs more than selective evidence reuse; P0
  deliberately chooses the simpler rule.
- Init drift leaves recoverable residue instead of guessing.
- The historical digest proves registry-text identity, not machine-understood
  semantic equivalence.
- rev9 addresses the identified P0 specification gaps in candidate scope,
  cooperative authority claims, profile revision, start topology,
  risk/reviewer mapping, and workflow-owned context/output accounting. It also
  separates delivery slices. This conclusion does not authorize implementation,
  source acceptance, integration, or any protected/external effect.

## 7. Acceptance criteria

### P0 completion gate

Future P0 implementation must pass and report:

```console
npm run v7:check
npm run v7:test
npm run skill:v7:check
git diff --check
npm run lm
```

It must also satisfy:

- English normative Spec and Chinese administrator mirror match in decision IDs,
  authority, state, invariant, scope, and acceptance meaning.
- The Chinese mirror's V7-DEC-001–110 definition lines match the bound rev5
  Chinese registry digest, and its V7-DEC-111–119 lines match the bound rev7
  Chinese registry digest. The English source has the same ID order and an
  independently reviewed semantic translation; it is not expected to have
  either Chinese byte digest. The rev8 English and Chinese full-source digests
  match their frozen inputs, and V7-DEC-120–141 relations and revision metadata
  are mechanically consistent. Semantic equivalence is not claimed from a hash.
- `P0-core` and `P0-install` have separately reported acceptance, and complete
  P0 is claimed only after both pass. An optional extension reports its own
  status and cannot be inferred from either slice.
- The P0 final candidate has an independent
  `controller_source_technical_review` with no unresolved blocking finding.
- That review does not accept the source snapshot, activate a controller, or
  authorize integration.
- P0 produces only an inactive candidate and waits for a separate decision to
  continue P1.

### Required P0 scenarios

- A valid cooperative provenance record starts and resumes only its exact bound
  operation. Missing/malformed records, authority-class mismatch, applicable
  binding mismatch (remote/ref for fetch or B/task/contract/action/path for
  implementation), local-clock expiry, post-binding mutation, and cross-binding
  nonce reuse within one class fails. The same nonce and record digest revalidate idempotently.
  Process restart and concurrent same-pair/different-digest cases prove durable,
  locked claim behavior. The same nonce literal may be independently claimed in
  another class, but presenting a record as another class fails. Tests do not
  claim cryptographic issuer authenticity.
- A complete eligible Simple contract reaches `accepted` without a Reviewer.
  `risk=high, review_required=false` fails before writes; a required, stale,
  non-independent, or blocking review prevents acceptance.
- `task start` never invents semantics or changes profile. Incomplete or
  uncertain input returns `contract_incomplete` without consuming the
  preallocated task ID or creating a ref, branch, worktree, or project write. A
  successful retry creates and attaches exact S at B and returns at
  `HEAD=task_ref=S`; matching S is idempotent only from a clean eligible
  worktree, and a conflict fails closed. A pre-existing ignored or non-ignored
  entry under product, controlled-record, or trust-root scope fails before S and
  cannot later be absorbed by `candidate_cleanup`.
- Budget-conforming first-success Simple produces `B-S-C-A`; one actual repair
  produces `B-S-I-C-A`; extra authorized commits only set observed complexity.
  C is always final, S must be its ancestor, verify requires
  `HEAD=task_ref=C`, and A uses `parent(A)=C` plus CAS from C. Detached C,
  task-ref mismatch, missing S ancestry, stale CAS, and uncommitted Agent changes
  fail; verify never creates C itself.
- Profile is fixed before digest and provenance. Pure commit/pause budget
  overrun changes only `observed_complexity`; a new capability or wider scope
  enters `blocked(profile_upgrade_required)` and requires a new Standard
  revision and provenance.
- A resumed state reruns all destination gates and cannot bypass authority
  provenance, candidate binding, scope, or review.
- P0 verification interruption discards partial evidence, never resumes
  `verifying`, and reruns the complete set from `in_progress`; invalidated
  accepted work advances through a descendant C and never rewrites old A.
- Contract identity, gate, or immutable-block changes alter the contract digest;
  mutable state, time, `observed_complexity`, evidence, and run metadata do not.
- B or C changes alter the candidate digest and invalidate bound evidence,
  review, and acceptance.
- Candidate-history scope catches an out-of-scope change later restored. Tests
  cover recursive leaf entries but not directory-tree OIDs; rename endpoints;
  mode/type/symlink/gitlink; exact/prefix matching and rejected path forms;
  controlled workflow records; applicable P0/P1 implementation scope; action
  catalog; and deletion authority. P0-core rejects every Simple trust-root touch
  and every positive request when the Standard extension is unavailable; that
  extension owns its exact-binding positive case when implemented.
- A failed candidate may make an allowed in-scope file addition and repaired C may remove it
  as `candidate_cleanup` when the path is absent from B and final C; this does
  not require or create product-deletion authority. Final deletion of a B entry
  still requires the dual gate. Scope widening over a pre-existing ignored entry
  fails its revision admission gate and cannot convert that entry into cleanup.
- Verify rejects a pre-existing or validation-created non-ignored untracked
  entry and an ignored in-scope, controlled-path, or trust-root entry, including
  recursive directory and symlink cases. It accepts declared temporary output
  outside the repository and preserves failures without cleanup. C-to-A
  path/field allowlists remain enforced.
- Concurrent unrelated refs do not fail validation; changes to scoped task,
  target, or trust-root refs do.
- Standing fetch provenance can operate before B/task/contract exist but binds
  exact repository, remote, ref/refspec, policy, and action. Wrong bindings,
  failed/stale fetch, and reuse as implementation provenance fail; successful
  fetch records B and branch ancestry starts at exact `origin/dev`.
- Validation rejects shell injection, environment leakage, unknown/external
  actions, and scoped candidate/ref mutation. Tests fix redaction-before-digest,
  separate framed redacted-stream digests, raw/redacted counts, frozen-order
  1024-byte head/tail allocation, 16384-byte result/receipt limits, required-
  field preservation, and `receipt_budget_exceeded`; P0 persists no raw digest
  or full command log.
- Core deletion guards reject missing dual authority and every excluded path.
  A positive deletion or trust-root workflow fails closed when the Standard
  extension is unavailable and is tested separately when that extension exists.
- `P0-install` init does not overwrite existing content, protected refs,
  remotes, or push. Conflicts return `update_required` before writes; journal
  ordering is write-ahead; rollback affects only exact current-transaction
  creations; drift preserves the scene.
- Source-manifest existence alone produces no source acceptance or activation;
  self-entry, missing/extra runtime files, and path/type/mode/content drift fail.
- P0 exposes no activation capability and rejects project/config input that
  declares multiple active control versions.
- Simple has no stage or extra role, its default task-record topology stays
  within budget, and its request plus V7-owned mandatory initial context satisfy
  4096/16384-byte limits. Each implemented Standard role uses the same initial
  ceiling and the Simple happy path reads no other V7 workflow document.
- `task integrate` is absent from the default bundle and returns
  `integration_unavailable` before any planned M, provider call, journal, target
  lease, receipt, or ref change. Verify reports `task_status=accepted`,
  `candidate_scope=local`, and `integration_available=false`.
- Generated P0 projects statically keep notification disabled.

### P1 acceptance

- The selected real provider rejects forged/tampered capabilities, wrong
  authenticated issuers, provider-defined replay, clock, expiry, and revocation
  failures for the authority classes it owns. A valid provider-backed
  implementation record passes the same candidate-closure scope gate as P0.
- Grant/provider, nonce/claim, journal crash points, expiry boundaries, target
  lease fencing, planned M, CAS, and integration-receipt scenarios pass,
  including one successful fixture CAS and effect-unknown reconciliation.
- The second target-freshness check invalidates stale evidence and authority;
  push performs its own immediate check when separate.
- `P1-core` acceptance proves only provider-backed authority and protected
  `dev` closure. Updater/migration, hotfix/stable/push, release/deploy,
  notification, model comparison, and controller lifecycle each report a
  separate extension result using controlled fixtures until real adapters are
  selected.
- When delivered, the notification extension remains off by default, requires a
  narrow grant, and never changes engineering acceptance.
- `P1-core` requires the final source snapshot's new independent review,
  authenticated administrator acceptance, separately authorized integration,
  and final-position digest verification. When delivered, the
  controller-lifecycle extension additionally requires separate activation.
- When delivered, activation rejects a second active control version and
  preserves the previous authenticated activation record on failure.
- Acceptance leaves `experimental=true`, `recommended=false`, and
  `production_ready=false` until a later independent designation changes them.
