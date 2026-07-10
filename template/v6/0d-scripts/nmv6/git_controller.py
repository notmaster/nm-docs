"""Fail-closed Git policy, merge proposals, protected CAS, and cleanup facts."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .authorization import authorization_scope_allows, validate_authorization_record
from .cleanup_review import (
    CLEANUP_FACTS_SCHEMA_VERSION,
    INTEGRATION_PROOF_SCHEMA_VERSION,
    INTEGRATION_RECEIPT_SCHEMA_VERSION,
    REQUEST_SCHEMA_VERSION as CLEANUP_REVIEW_REQUEST_SCHEMA_VERSION,
    seal_cleanup_facts,
    seal_cleanup_integration_proof,
    seal_cleanup_integration_receipt,
    seal_cleanup_review_request,
    validate_cleanup_review_observations,
    validate_cleanup_review_request,
)
from .errors import AuthorizationError, ContractError, GitPolicyError
from .failpoints import checkpoint
from .gates import validate_gate_decision
from .merge_review import (
    MERGE_STRATEGIES as MERGE_REVIEW_STRATEGIES,
    REQUEST_SCHEMA_VERSION as MERGE_REVIEW_REQUEST_SCHEMA_VERSION,
    seal_merge_review_request,
    validate_merge_review_observations,
    validate_merge_review_request,
)
from .util import canonical_json, run_command, sha256_bytes, utc_now


MERGE_STRATEGIES = frozenset({"fast_forward", "squash", "merge_commit"})
DEFAULT_WORK_PREFIXES = ("feature/", "fix/", "docs/", "refactor/", "chore/", "task/")
_BRANCH = re.compile(r"^(?!/)(?!.*(?:\.\.|//|@\{|\\|\s))(?!.*\.$)[A-Za-z0-9._/-]+$")


@dataclass(frozen=True)
class MergeProposal:
    source_ref: str
    source_commit: str
    target_ref: str
    target_commit: str
    purpose: str
    sharing_status: str
    strategy: str
    rationale: str
    candidate_tree: str
    expected_result_tree: str
    rollback_ref: str
    gate_ids: tuple[str, ...]
    authorization_id: str

    def __post_init__(self) -> None:
        if self.strategy not in MERGE_STRATEGIES:
            raise ContractError(f"unsupported merge strategy: {self.strategy!r}")
        for name in (
            "source_ref",
            "source_commit",
            "target_ref",
            "target_commit",
            "purpose",
            "sharing_status",
            "rationale",
            "candidate_tree",
            "expected_result_tree",
            "rollback_ref",
            "authorization_id",
        ):
            if not getattr(self, name):
                raise ContractError(f"merge proposal {name} must not be empty")
        if not self.gate_ids:
            raise ContractError("merge proposal must cite a passed gate")


@dataclass(frozen=True)
class MergeReceipt:
    strategy: str
    source_commit: str
    target_before: str
    target_after: str
    result_tree: str
    rollback_ref: str
    authorization_id: str
    executed_at: str


@dataclass(frozen=True)
class PushReceipt:
    remote: str
    branch: str
    before: str
    after: str
    force: bool
    observed_after: str
    executed_at: str


@dataclass(frozen=True)
class NonProtectedRefReceipt:
    grant_id: str
    action: str
    remote: str
    ref: str
    expected_sha: str
    observed_after: str | None
    force: bool
    executed_at: str


class ProtectedMutationAuthority(Protocol):
    """Validate persisted gate and administrator authority at point of use."""

    def require_proposal(
        self,
        proposal: "MergeProposal",
        *,
        action: str,
        protected_ref: str,
        required_gate_type: str,
    ) -> None: ...

    def require_hotfix_creation(
        self,
        *,
        branch: str,
        stable_commit: str,
        protected_ref: str,
        authorization_id: str,
    ) -> None: ...


class StoreProtectedMutationAuthority:
    """Resolve protected-mutation authority from the canonical SQLite journal.

    Gate and authorization materialized rows are checked against their
    append-only journal events before their contents are trusted.  This class
    never accepts caller-supplied ``authorized`` or ``gate_passed`` booleans.
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    def require_proposal(
        self,
        proposal: MergeProposal,
        *,
        action: str,
        protected_ref: str,
        required_gate_type: str,
    ) -> None:
        self.store.integrity_check()
        authorization = self._authorization(
            proposal.authorization_id,
            action=action,
            protected_ref=protected_ref,
        )
        run_id = str(authorization["run_id"])
        spec_hash = str(authorization["spec_hash"])
        config_hash = str(authorization["config_hash"])
        matching_gate = False
        for gate_id in proposal.gate_ids:
            gate = self.store.get_gate(gate_id)
            if not isinstance(gate, Mapping):
                raise GitPolicyError(f"protected mutation gate is unavailable: {gate_id}")
            try:
                validate_gate_decision(gate)
            except ContractError as exc:
                raise GitPolicyError(f"protected mutation gate is invalid: {gate_id}") from exc
            if not self._journal_has_gate(gate_id, str(gate["decision_digest"])):
                raise GitPolicyError("protected mutation gate differs from the canonical journal")
            if gate.get("result") != "passed":
                raise GitPolicyError("protected mutation requires a passed deterministic gate")
            if (
                gate.get("run_id") != run_id
                or gate.get("spec_hash") != spec_hash
                or gate.get("config_hash") != config_hash
            ):
                raise GitPolicyError("protected mutation gate has stale run or input bindings")
            gate_authorization = gate.get("authorization_id")
            if gate_authorization not in {None, proposal.authorization_id}:
                raise GitPolicyError("protected mutation gate cites another authorization")
            if gate.get("gate_type") == required_gate_type:
                if gate_authorization != proposal.authorization_id:
                    raise GitPolicyError("mutation gate does not cite the proposal authorization")
                source_field = (
                    "source_commit" if required_gate_type == "RELEASE_GATE" else "candidate_commit"
                )
                if gate.get(source_field) != proposal.source_commit:
                    raise GitPolicyError("mutation gate source binding differs from the proposal")
                if gate.get("target_commit") != proposal.target_commit:
                    raise GitPolicyError("mutation gate target binding differs from the proposal")
                matching_gate = True
        if not matching_gate:
            raise GitPolicyError(
                f"protected mutation requires a passed {required_gate_type} receipt"
            )

    def require_hotfix_creation(
        self,
        *,
        branch: str,
        stable_commit: str,
        protected_ref: str,
        authorization_id: str,
    ) -> None:
        self.store.integrity_check()
        self._authorization(
            authorization_id,
            action="hotfix",
            protected_ref=protected_ref,
        )
        if not branch or not stable_commit:
            raise GitPolicyError("hotfix branch creation lacks exact branch or stable binding")

    def _authorization(
        self,
        authorization_id: str,
        *,
        action: str,
        protected_ref: str,
    ) -> Mapping[str, Any]:
        record = self.store.get_authorization(authorization_id)
        if not isinstance(record, Mapping):
            raise GitPolicyError("protected mutation authorization is unavailable")
        try:
            verified = validate_authorization_record(record)
        except AuthorizationError as exc:
            raise GitPolicyError("protected mutation authorization is invalid or expired") from exc
        if verified.record_type not in {"grant", "approval"}:
            raise GitPolicyError("protected mutation requires a grant or staged approval")
        if not self._journal_has_authorization(
            authorization_id, verified.record_digest
        ):
            raise GitPolicyError(
                "protected mutation authorization differs from the canonical journal"
            )
        if self.store.authorization_is_revoked(authorization_id):
            raise GitPolicyError("protected mutation authorization was revoked")
        run_id = record.get("run_id")
        spec_hash = record.get("spec_hash")
        config_hash = record.get("config_hash")
        if not all(isinstance(value, str) and value for value in (run_id, spec_hash, config_hash)):
            raise GitPolicyError("protected mutation authorization lacks run/input bindings")
        run = self.store.get_run(str(run_id))
        if not isinstance(run, Mapping) or (
            run.get("spec_hash") != spec_hash or run.get("config_hash") != config_hash
        ):
            raise GitPolicyError("protected mutation authorization is stale for the run")
        if not authorization_scope_allows(
            record,
            run_id=str(run_id),
            spec_hash=str(spec_hash),
            config_hash=str(config_hash),
            action=action,
            protected_ref=protected_ref,
        ):
            raise GitPolicyError("protected mutation is outside the persisted authorization scope")
        return record

    def _journal_has_authorization(self, authorization_id: str, digest: str) -> bool:
        return any(
            event.get("event_type") == "AUTHORIZATION_IMPORTED"
            and event.get("payload", {}).get("authorization_id") == authorization_id
            and event.get("payload", {}).get("record_digest") == digest
            for event in self.store.list_events()
        )

    def _journal_has_gate(self, gate_id: str, digest: str) -> bool:
        return any(
            event.get("event_type") == "GATE_DECIDED"
            and event.get("payload", {}).get("gate_id") == gate_id
            and event.get("payload", {}).get("decision_digest") == digest
            for event in self.store.list_events()
        )


class StoreNonProtectedRefAuthority:
    """Resolve and atomically consume an exact signed remote-ref grant.

    The caller's action document is never authority.  Its complete mutable
    scope must equal the ``nonprotected_ref`` object in a canonical imported
    grant, which is itself bound to the persisted authorization request by the
    signed request digest.  Claiming the authorization is durable and happens
    before the external Git effect so a crash cannot make it reusable.
    """

    _REQUEST_SCOPE_FIELDS = frozenset(
        {
            "run_id",
            "spec_hash",
            "config_hash",
            "allowed_actions",
            "allowed_environments",
            "allowed_protected_refs",
            "one_time",
            "nonprotected_ref",
        }
    )

    def __init__(self, store: Any) -> None:
        self.store = store

    def claim(self, grant: Mapping[str, Any]) -> None:
        authorization_id = grant.get("administrator_authorization_id")
        if not isinstance(authorization_id, str) or not authorization_id:
            raise GitPolicyError(
                "nonprotected-ref action lacks its canonical authorization ID"
            )
        caller_scope = {
            key: grant[key]
            for key in (
                "grant_id",
                "action",
                "remote",
                "ref",
                "expected_sha",
                "force",
                "one_time",
                "expires_at",
            )
        }
        self.store.integrity_check()
        with self.store._write_transaction() as connection:
            row = connection.execute(
                "SELECT record_json, record_digest, request_digest FROM "
                "authorization_records WHERE authorization_id = ?",
                (authorization_id,),
            ).fetchone()
            if row is None:
                raise GitPolicyError(
                    "nonprotected-ref authorization is unavailable from the canonical store"
                )
            record = json.loads(row["record_json"])
            try:
                verified = validate_authorization_record(record)
            except AuthorizationError as exc:
                raise GitPolicyError(
                    "nonprotected-ref authorization is invalid or expired"
                ) from exc
            if verified.record_type != "grant":
                raise GitPolicyError(
                    "nonprotected-ref mutation requires an explicit signed grant"
                )
            if (
                verified.authorization_id != authorization_id
                or verified.record_digest != row["record_digest"]
            ):
                raise GitPolicyError(
                    "nonprotected-ref authorization differs from its canonical record"
                )
            imported = False
            for event in connection.execute(
                "SELECT payload_json FROM events WHERE event_type = 'AUTHORIZATION_IMPORTED'"
            ):
                payload = json.loads(event["payload_json"])
                if (
                    payload.get("authorization_id") == authorization_id
                    and payload.get("record_digest") == verified.record_digest
                ):
                    imported = True
                    break
            if not imported:
                raise GitPolicyError(
                    "nonprotected-ref authorization is absent from the canonical journal"
                )
            if connection.execute(
                "SELECT 1 FROM authorization_records WHERE record_type = 'revocation' "
                "AND target_authorization_id = ? LIMIT 1",
                (authorization_id,),
            ).fetchone():
                raise GitPolicyError("nonprotected-ref authorization was revoked")
            request = connection.execute(
                "SELECT run_id, scope_json FROM authorization_requests "
                "WHERE request_digest = ?",
                (row["request_digest"],),
            ).fetchone()
            if request is None:
                raise GitPolicyError(
                    "nonprotected-ref authorization lacks its canonical request"
                )
            request_scope = json.loads(request["scope_json"])
            if set(request_scope) != self._REQUEST_SCOPE_FIELDS:
                raise GitPolicyError(
                    "nonprotected-ref authorization request has unknown or incomplete scope"
                )
            signed_scope = record.get("nonprotected_ref")
            if signed_scope != caller_scope or request_scope.get(
                "nonprotected_ref"
            ) != caller_scope:
                raise GitPolicyError(
                    "nonprotected-ref action differs from the exact signed grant scope"
                )
            for field in (
                "run_id",
                "spec_hash",
                "config_hash",
                "allowed_actions",
                "allowed_environments",
                "allowed_protected_refs",
                "one_time",
            ):
                if request_scope.get(field) != record.get(field):
                    raise GitPolicyError(
                        "nonprotected-ref authorization expanded its requested scope"
                    )
            run = connection.execute(
                "SELECT spec_hash, config_hash FROM runs WHERE run_id = ?",
                (record.get("run_id"),),
            ).fetchone()
            if (
                run is None
                or request["run_id"] != record.get("run_id")
                or run["spec_hash"] != record.get("spec_hash")
                or run["config_hash"] != record.get("config_hash")
            ):
                raise GitPolicyError(
                    "nonprotected-ref authorization is stale for its canonical run"
                )
            if not authorization_scope_allows(
                record,
                run_id=str(record["run_id"]),
                spec_hash=str(record["spec_hash"]),
                config_hash=str(record["config_hash"]),
                action=str(grant["action"]),
            ):
                raise GitPolicyError(
                    "nonprotected-ref action is outside the persisted authorization scope"
                )
            operation_id = f"git-nonprotected:{grant['grant_id']}"
            if connection.execute(
                "SELECT 1 FROM authorization_uses WHERE authorization_id = ? "
                "OR operation_id = ? LIMIT 1",
                (authorization_id, operation_id),
            ).fetchone():
                raise GitPolicyError("nonprotected-ref authorization was already consumed")
            connection.execute(
                "INSERT INTO authorization_uses(authorization_id, operation_id, used_at) "
                "VALUES (?, ?, ?)",
                (
                    authorization_id,
                    operation_id,
                    utc_now(),
                ),
            )


_CLEANUP_RESPONSIBILITY_ASSERTIONS = (
    "review_responsibility_closed",
    "backup_retention_absent",
    "dependent_work_closed",
    "release_responsibility_closed",
    "rollback_responsibility_closed",
    "audit_retention_absent",
    "explicit_retention_absent",
)
_ACTIVE_ATTEMPT_STATES = frozenset({"CREATED", "DISPATCHED", "RUNNING", "COLLECTING"})
_ACTIVE_OPERATION_STATES = frozenset({"planned", "started", "partial", "unknown"})
_DELIVERY_RETENTION_STATES = frozenset(
    {
        "RELEASING",
        "DEPLOYING",
        "ROLLBACK_REQUIRED",
        "ROLLING_BACK",
    }
)
_TERMINAL_CLEANUP_REVIEW_STATES = frozenset(
    {"POST_DEPLOY_VERIFYING", "POST_ROLLBACK_VERIFYING"}
)


@dataclass(frozen=True)
class CanonicalCleanupSnapshot:
    """Point-in-time cleanup facts derived from canonical controller state."""

    run_id: str | None
    input_revision: int | None
    live_lease_ids: tuple[str, ...] = ()
    live_session_ids: tuple[str, ...] = ()
    dependent_workspace_paths: tuple[str, ...] = ()
    responsibility_evidence_id: str | None = None
    responsibility_assertions: tuple[tuple[str, bool], ...] = ()
    authority_available: bool = True

    @property
    def responsibilities_closed(self) -> bool:
        values = dict(self.responsibility_assertions)
        return all(values.get(name) is True for name in _CLEANUP_RESPONSIBILITY_ASSERTIONS)


class CleanupFactAuthority(Protocol):
    """Read canonical cleanup facts and journal cleanup decisions/receipts."""

    def snapshot(
        self, *, run_id: str | None, branch: str, head: str
    ) -> CanonicalCleanupSnapshot: ...

    def record(
        self,
        *,
        run_id: str,
        input_revision: int,
        record: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]: ...


class StoreCleanupFactAuthority:
    """Derive cleanup blockers from SQLite and persist their audit records.

    Caller booleans are reviewer recommendations only.  Leases, provider
    sessions, workspace dependencies, and responsibility closure are resolved
    from the canonical Store at the point of use.  Missing responsibility
    evidence fails closed.
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    @staticmethod
    def _payload_values(value: Any, names: frozenset[str]) -> tuple[str, ...]:
        found: set[str] = set()

        def visit(current: Any) -> None:
            if isinstance(current, Mapping):
                for key, child in current.items():
                    if key in names and isinstance(child, str) and child:
                        found.add(child)
                    else:
                        visit(child)
            elif isinstance(current, list):
                for child in current:
                    visit(child)

        visit(value)
        return tuple(sorted(found))

    @staticmethod
    def _is_live_timestamp(value: str) -> bool:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise GitPolicyError("canonical lease has an invalid expiry") from exc
        if parsed.tzinfo is None:
            raise GitPolicyError("canonical lease expiry lacks a timezone")
        return parsed.astimezone(UTC) > datetime.now(UTC)

    def snapshot(
        self, *, run_id: str | None, branch: str, head: str
    ) -> CanonicalCleanupSnapshot:
        if not isinstance(run_id, str) or not run_id:
            raise GitPolicyError("canonical branch cleanup requires an exact run_id")
        self.store.integrity_check()
        session_names = frozenset({"session_id", "provider_session_id", "adapter_session_id"})
        workspace_names = frozenset(
            {"workspace", "workspace_path", "candidate_workspace", "disposable_workspace"}
        )
        live_leases: set[str] = set()
        live_sessions: set[str] = set()
        workspace_paths: set[str] = set()
        active_operation_ids: set[str] = set()
        responsibility_evidence_id: str | None = None
        responsibility_assertions: dict[str, bool] = {}
        with self.store._lock:
            connection = self.store._connection
            run = connection.execute(
                "SELECT revision, state, spec_hash, config_hash FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise GitPolicyError("canonical branch cleanup run is unavailable")
            for lease in connection.execute(
                "SELECT resource_id, expires_at FROM leases WHERE run_id = ? ORDER BY resource_id",
                (run_id,),
            ).fetchall():
                if self._is_live_timestamp(str(lease["expires_at"])):
                    live_leases.add(str(lease["resource_id"]))
            for entity in connection.execute(
                "SELECT machine, entity_id, state, payload_json FROM entity_states "
                "WHERE run_id = ? ORDER BY machine, entity_id",
                (run_id,),
            ).fetchall():
                payload = json.loads(entity["payload_json"])
                if entity["machine"] == "attempt" and entity["state"] in _ACTIVE_ATTEMPT_STATES:
                    live_sessions.update(self._payload_values(payload, session_names))
                for raw_path in self._payload_values(payload, workspace_names):
                    path = Path(raw_path).expanduser()
                    if not path.is_absolute():
                        path = self.store.path.parent / path
                    if path.exists():
                        workspace_paths.add(str(path.resolve()))
            for operation in connection.execute(
                "SELECT operation_id, status, scope_json, result_json FROM external_operations "
                "WHERE run_id = ? ORDER BY operation_id",
                (run_id,),
            ).fetchall():
                if operation["status"] not in _ACTIVE_OPERATION_STATES:
                    continue
                active_operation_ids.add(str(operation["operation_id"]))
                live_sessions.update(
                    self._payload_values(json.loads(operation["scope_json"]), session_names)
                )
                live_sessions.update(
                    self._payload_values(json.loads(operation["result_json"]), session_names)
                )
            evidence_rows = connection.execute(
                "SELECT evidence_id, receipt_json FROM evidence_receipts "
                "WHERE run_id = ? AND evidence_type = 'branch_cleanup_responsibility' "
                "ORDER BY created_at DESC, evidence_id DESC",
                (run_id,),
            ).fetchall()
            for row in evidence_rows:
                receipt = json.loads(row["receipt_json"])
                if (
                    receipt.get("producer") != "nm-v6-core/cleanup-evaluator"
                    or receipt.get("result") != "passed"
                    or receipt.get("spec_hash") != run["spec_hash"]
                    or receipt.get("config_hash") != run["config_hash"]
                    or receipt.get("source_commit") != head
                    or f"branch:{branch}" not in receipt.get("subject_ids", [])
                    or f"branch-head:{head}" not in receipt.get("subject_ids", [])
                ):
                    continue
                if run["state"] in _TERMINAL_CLEANUP_REVIEW_STATES and (
                    active_operation_ids
                    or receipt.get("assertions", {}).get(
                        "terminal_resource_proof_complete"
                    )
                    is not True
                ):
                    continue
                responsibility_evidence_id = str(row["evidence_id"])
                raw_assertions = receipt.get("assertions", {})
                responsibility_assertions = {
                    name: raw_assertions.get(name) is True
                    for name in _CLEANUP_RESPONSIBILITY_ASSERTIONS
                }
                break
            if run["state"] in _DELIVERY_RETENTION_STATES:
                responsibility_assertions["release_responsibility_closed"] = False
                responsibility_assertions["rollback_responsibility_closed"] = False
            return CanonicalCleanupSnapshot(
                run_id=run_id,
                input_revision=int(run["revision"]),
                live_lease_ids=tuple(sorted(live_leases)),
                live_session_ids=tuple(sorted(live_sessions)),
                dependent_workspace_paths=tuple(sorted(workspace_paths)),
                responsibility_evidence_id=responsibility_evidence_id,
                responsibility_assertions=tuple(sorted(responsibility_assertions.items())),
            )

    def record(
        self,
        *,
        run_id: str,
        input_revision: int,
        record: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        # Import lazily so Git policy remains usable without constructing the
        # workflow controller and to keep the Store's reducer as its sole
        # domain-event writer.
        from .reducer import Reducer

        try:
            return Reducer(self.store).record_domain_event(
                run_id=run_id,
                expected_revision=input_revision,
                event_type="BRANCH_CLEANUP_DECIDED",
                payload=record,
                idempotency_key=idempotency_key,
                actor="git-cleanup-controller",
            )
        except Exception as exc:
            if isinstance(exc, GitPolicyError):
                raise
            raise GitPolicyError("cannot persist canonical branch cleanup record") from exc


@dataclass(frozen=True)
class CleanupFacts:
    branch: str
    expected_head: str
    integration_receipt: MergeReceipt | None
    ancestry_proven: bool = False
    patch_or_tree_equivalent: bool = False
    under_review: bool = False
    backed_up: bool = False
    dependent_work: bool = False
    release_responsibility: bool = False
    rollback_responsibility: bool = False
    audit_retention: bool = False
    live_lease: bool = False
    live_session: bool = False
    dependent_workspace: bool = False
    explicitly_retain: bool = False
    run_id: str | None = None


@dataclass(frozen=True)
class CleanupDecision:
    result: str
    branch: str
    head: str
    reasons: tuple[str, ...]
    decided_at: str
    facts_digest: str = ""
    run_id: str | None = None
    input_revision: int | None = None
    decision_event_id: str | None = None


@dataclass(frozen=True)
class CleanupReceipt:
    result: str
    branch: str
    deleted_head: str
    prior_decision_at: str
    reevaluated_at: str
    executed_at: str
    facts_digest: str = ""
    run_id: str | None = None
    input_revision: int | None = None
    decision_event_id: str | None = None
    execution_event_id: str | None = None


class GitController:
    def __init__(
        self,
        repository: Path,
        *,
        remote: str = "origin",
        stable_branch: str = "main",
        integration_branch: str = "dev",
        work_branch_prefixes: Sequence[str] = DEFAULT_WORK_PREFIXES,
        hotfix_prefix: str = "hotfix/",
        nonprotected_store: Any | None = None,
        protected_authority: ProtectedMutationAuthority | None = None,
        cleanup_store: Any | None = None,
        cleanup_authority: CleanupFactAuthority | None = None,
    ) -> None:
        self.repository = repository.resolve()
        self.remote = remote
        self.stable_branch = _validate_branch(stable_branch)
        self.integration_branch = _validate_branch(integration_branch)
        if self.integration_branch != "dev":
            raise ContractError("V6 integration branch must be literal dev")
        if self.stable_branch == self.integration_branch:
            raise ContractError("stable and integration branches must differ")
        self.work_branch_prefixes = tuple(work_branch_prefixes)
        self.hotfix_prefix = hotfix_prefix
        self.protected_authority = protected_authority
        if nonprotected_store is None and isinstance(
            protected_authority, StoreProtectedMutationAuthority
        ):
            nonprotected_store = protected_authority.store
        self.nonprotected_authority = (
            StoreNonProtectedRefAuthority(nonprotected_store)
            if nonprotected_store is not None
            else None
        )
        if cleanup_store is None and isinstance(
            protected_authority, StoreProtectedMutationAuthority
        ):
            cleanup_store = protected_authority.store
        if cleanup_store is None and nonprotected_store is not None:
            cleanup_store = nonprotected_store
        if cleanup_store is not None and cleanup_authority is not None:
            raise ContractError("configure cleanup_store or cleanup_authority, not both")
        self.cleanup_authority = cleanup_authority or (
            StoreCleanupFactAuthority(cleanup_store)
            if cleanup_store is not None
            else None
        )
        if not self.work_branch_prefixes or any(
            not isinstance(prefix, str) or not prefix.endswith("/") for prefix in self.work_branch_prefixes
        ):
            raise ContractError("work branch prefixes must be nonempty slash-terminated strings")
        if not hotfix_prefix.endswith("/"):
            raise ContractError("hotfix prefix must end in slash")
        result = run_command(("git", "rev-parse", "--show-toplevel"), cwd=self.repository)
        if Path(result.stdout.strip()).resolve() != self.repository:
            raise GitPolicyError("repository must be the authoritative Git root")

    @property
    def protected_branches(self) -> tuple[str, str]:
        return (self.stable_branch, self.integration_branch)

    def assert_clean(self) -> None:
        status = run_command(
            ("git", "status", "--porcelain=v1", "--untracked-files=all"),
            cwd=self.repository,
        ).stdout
        if status.strip():
            raise GitPolicyError("authoritative working tree is dirty or contains unexpected files")

    def fetch_branch(self, branch: str) -> str:
        branch = _validate_branch(branch)
        self._assert_remote_exists()
        result = run_command(
            ("git", "fetch", "--prune", "--no-tags", self.remote, branch),
            cwd=self.repository,
            check=False,
        )
        if result.returncode != 0:
            raise GitPolicyError(f"failed to fetch {self.remote}/{branch}")
        remote_ref = f"refs/remotes/{self.remote}/{branch}"
        return self.resolve_commit(remote_ref)

    def fetch_dev(self, *, expected_remote: str | None = None, reconcile_local: bool = True) -> str:
        self.assert_clean()
        remote_sha = self.fetch_branch(self.integration_branch)
        if expected_remote is not None and remote_sha != expected_remote:
            raise GitPolicyError("remote dev moved from its expected revision")
        local_ref = self._heads_ref(self.integration_branch)
        local_sha = self.try_resolve_commit(local_ref)
        if local_sha is None:
            if reconcile_local:
                self._update_ref(local_ref, remote_sha, None)
            else:
                raise GitPolicyError("local dev is missing")
        elif local_sha != remote_sha:
            if not self.is_ancestor(local_sha, remote_sha):
                raise GitPolicyError("local dev is divergent or contains local-only commits")
            if not reconcile_local:
                raise GitPolicyError("local dev is stale")
            self._update_ref(local_ref, remote_sha, local_sha)
        return remote_sha

    def fetch_stable(
        self, *, expected_remote: str | None = None, reconcile_local: bool = True
    ) -> str:
        self.assert_clean()
        remote_sha = self.fetch_branch(self.stable_branch)
        if expected_remote is not None and remote_sha != expected_remote:
            raise GitPolicyError("remote stable moved from its expected revision")
        local_ref = self._heads_ref(self.stable_branch)
        local_sha = self.try_resolve_commit(local_ref)
        if local_sha is None:
            if reconcile_local:
                self._update_ref(local_ref, remote_sha, None)
            else:
                raise GitPolicyError("local stable is missing")
        elif local_sha != remote_sha:
            if not self.is_ancestor(local_sha, remote_sha):
                raise GitPolicyError("local stable is divergent or contains local-only commits")
            if not reconcile_local:
                raise GitPolicyError("local stable is stale")
            self._update_ref(local_ref, remote_sha, local_sha)
        return remote_sha

    def create_work_branch(
        self,
        branch: str,
        *,
        expected_remote_dev: str | None = None,
    ) -> str:
        branch = _validate_branch(branch)
        if not any(branch.startswith(prefix) and len(branch) > len(prefix) for prefix in self.work_branch_prefixes):
            raise GitPolicyError(f"normal work branch has an invalid prefix: {branch}")
        self._assert_new_branch(branch)
        base = self.fetch_dev(expected_remote=expected_remote_dev)
        self._update_ref(self._heads_ref(branch), base, None)
        return base

    def create_hotfix_branch(
        self,
        branch: str,
        *,
        authorization_id: str,
        expected_remote_stable: str | None = None,
    ) -> str:
        branch = _validate_branch(branch)
        if not branch.startswith(self.hotfix_prefix) or len(branch) <= len(self.hotfix_prefix):
            raise GitPolicyError("hotfix branch must use the configured hotfix prefix")
        if not authorization_id:
            raise GitPolicyError("hotfix creation requires trusted administrator authorization")
        self._assert_new_branch(branch)
        base = self.fetch_stable(expected_remote=expected_remote_stable)
        authority = self._protected_authority()
        authority.require_hotfix_creation(
            branch=branch,
            stable_commit=base,
            protected_ref=self.stable_branch,
            authorization_id=authorization_id,
        )
        self._update_ref(self._heads_ref(branch), base, None)
        return base

    def build_merge_review_request(
        self,
        *,
        review_id: str,
        run_id: str,
        spec_hash: str,
        config_hash: str,
        source_ref: str,
        target_branch: str,
        purpose: str,
        sharing_status: str,
        single_logical_change: bool,
        disposable: bool,
        audit_boundary_required: bool,
        rollback_boundary_required: bool,
        allowed_strategies: Iterable[str],
        future_gate_id: str,
        authorization_id: str,
        rollback_ref: str,
    ) -> dict[str, Any]:
        """Seal a merge-review request from current Git facts and core policy.

        Callers may supply intent, configured strategy policy, and future
        authority bindings.  Object IDs, graph facts, commit quality counts,
        route kinds, and strategy result trees are always recomputed here.
        """

        target_branch = _validate_branch(target_branch)
        self._assert_protected(target_branch)
        source_branch = self._branch_from_exact_ref(source_ref)
        source_commit = self.resolve_commit(source_ref)
        target_ref = self._heads_ref(target_branch)
        target_commit = self.resolve_commit(target_ref)
        route = self._merge_review_route(
            source_branch=source_branch,
            source_commit=source_commit,
            target_branch=target_branch,
            target_commit=target_commit,
        )
        allowed = self._canonical_merge_review_strategies(allowed_strategies)
        source_tree = self.tree_of(source_commit)
        target_tree = self.tree_of(target_commit)
        merge_base = self._unique_merge_base(source_commit, target_commit)
        target_is_ancestor = self.is_ancestor(target_commit, source_commit)
        source_is_ancestor = self.is_ancestor(source_commit, target_commit)
        source_only_commits = self._rev_list_count(f"{target_commit}..{source_commit}")
        target_only_commits = self._rev_list_count(f"{source_commit}..{target_commit}")
        merge_commit_count = self._rev_list_count(
            "--min-parents=2", f"{target_commit}..{source_commit}"
        )
        subjects = run_command(
            ("git", "log", "--format=%s", f"{target_commit}..{source_commit}", "--"),
            cwd=self.repository,
        ).stdout.splitlines()
        fixup_commit_count = sum(
            1 for subject in subjects if re.match(r"^(?:fixup|squash)!", subject)
        )
        commits_suitable = (
            source_only_commits > 0
            and merge_commit_count == 0
            and fixup_commit_count == 0
        )
        exact_source_tree_required = route in {
            "dev_to_stable",
            "hotfix_to_stable",
        }
        strategy_results = self._merge_review_strategy_results(
            source_commit=source_commit,
            target_commit=target_commit,
            source_tree=source_tree,
            exact_source_tree_required=exact_source_tree_required,
        )
        if self.resolve_commit(source_ref) != source_commit:
            raise GitPolicyError("merge review source moved during fact collection")
        if self.resolve_commit(target_ref) != target_commit:
            raise GitPolicyError("merge review target moved during fact collection")
        source_kind, target_kind = {
            "work_to_dev": ("work_branch", "dev"),
            "dev_to_stable": ("dev", "stable"),
            "hotfix_to_stable": ("hotfix", "stable"),
            "hotfix_to_dev": ("hotfix", "dev"),
        }[route]
        return seal_merge_review_request(
            {
                "schema_version": MERGE_REVIEW_REQUEST_SCHEMA_VERSION,
                "review_id": review_id,
                "run_id": run_id,
                "spec_hash": spec_hash,
                "config_hash": config_hash,
                "route": route,
                "source_kind": source_kind,
                "target_kind": target_kind,
                "source_ref": source_ref,
                "source_commit": source_commit,
                "source_tree": source_tree,
                "target_ref": target_ref,
                "target_commit": target_commit,
                "target_tree": target_tree,
                "purpose": purpose,
                "sharing_status": sharing_status,
                "topology": {
                    "merge_base": merge_base,
                    "target_is_ancestor": target_is_ancestor,
                    "source_is_ancestor": source_is_ancestor,
                    "source_only_commits": source_only_commits,
                    "target_only_commits": target_only_commits,
                },
                "commit_quality": {
                    "commit_count": source_only_commits,
                    "merge_commit_count": merge_commit_count,
                    "fixup_commit_count": fixup_commit_count,
                    "commits_suitable": commits_suitable,
                    "single_logical_change": single_logical_change,
                    "disposable": disposable,
                },
                "audit_boundary_required": audit_boundary_required,
                "rollback_boundary_required": rollback_boundary_required,
                "rollback_ref": rollback_ref,
                "allowed_strategies": allowed,
                "strategy_results": strategy_results,
                "exact_source_tree_required": exact_source_tree_required,
                "future_gate_id": future_gate_id,
                "authorization_id": authorization_id,
            }
        )

    def build_merge_proposal_from_review(
        self,
        *,
        request: Mapping[str, Any],
        observation: Mapping[str, Any],
        review_id: str,
        run_id: str,
        spec_hash: str,
        config_hash: str,
        purpose: str,
        sharing_status: str,
        single_logical_change: bool,
        disposable: bool,
        audit_boundary_required: bool,
        rollback_boundary_required: bool,
        allowed_strategies: Iterable[str],
        future_gate_id: str,
        authorization_id: str,
        rollback_ref: str,
    ) -> MergeProposal:
        """Revalidate a reviewed request against Git and build its proposal."""

        try:
            sealed_request = validate_merge_review_request(request)
            target_ref = str(sealed_request["target_ref"])
            target_prefix = "refs/heads/"
            if not target_ref.startswith(target_prefix):
                raise GitPolicyError("merge review target is not an exact branch ref")
            target_branch = _validate_branch(target_ref.removeprefix(target_prefix))
            current_request = self.build_merge_review_request(
                review_id=review_id,
                run_id=run_id,
                spec_hash=spec_hash,
                config_hash=config_hash,
                source_ref=str(sealed_request["source_ref"]),
                target_branch=target_branch,
                purpose=purpose,
                sharing_status=sharing_status,
                single_logical_change=single_logical_change,
                disposable=disposable,
                audit_boundary_required=audit_boundary_required,
                rollback_boundary_required=rollback_boundary_required,
                allowed_strategies=allowed_strategies,
                future_gate_id=future_gate_id,
                authorization_id=authorization_id,
                rollback_ref=rollback_ref,
            )
            if canonical_json(current_request) != canonical_json(sealed_request):
                raise GitPolicyError(
                    "merge review request differs from current Git facts or core policy"
                )
            reviewed = validate_merge_review_observations(
                sealed_request, [observation]
            )
        except ContractError as exc:
            raise GitPolicyError("merge review evidence is invalid") from exc
        if reviewed["decision"] != "propose":
            raise GitPolicyError("merge reviewer cannot propose a valid strategy")
        strategy = str(reviewed["strategy"])
        proposal = self.build_merge_proposal(
            source_ref=str(sealed_request["source_ref"]),
            target_branch=target_branch,
            strategy=strategy,
            purpose=purpose,
            sharing_status=sharing_status,
            rationale=str(reviewed["rationale"]),
            rollback_ref=rollback_ref,
            gate_ids=(future_gate_id,),
            authorization_id=authorization_id,
        )
        if (
            proposal.source_commit != sealed_request["source_commit"]
            or proposal.target_commit != sealed_request["target_commit"]
            or proposal.candidate_tree != sealed_request["source_tree"]
            or proposal.expected_result_tree != reviewed["expected_result_tree"]
        ):
            raise GitPolicyError("merge proposal substituted reviewed Git facts")
        exact_source_tree = bool(sealed_request["exact_source_tree_required"])
        self.validate_proposal(
            proposal, require_source_tree_result=exact_source_tree
        )
        return proposal

    def build_merge_proposal(
        self,
        *,
        source_ref: str,
        target_branch: str,
        strategy: str,
        purpose: str,
        sharing_status: str,
        rationale: str,
        rollback_ref: str,
        gate_ids: Iterable[str],
        authorization_id: str,
    ) -> MergeProposal:
        target_branch = _validate_branch(target_branch)
        self._assert_protected(target_branch)
        source_commit = self.resolve_commit(source_ref)
        target_ref = self._heads_ref(target_branch)
        target_commit = self.resolve_commit(target_ref)
        candidate_tree = self.tree_of(source_commit)
        result_tree = self.simulate_result_tree(
            source_commit=source_commit,
            target_commit=target_commit,
            strategy=strategy,
        )
        proposal = MergeProposal(
            source_ref=source_ref,
            source_commit=source_commit,
            target_ref=target_ref,
            target_commit=target_commit,
            purpose=purpose,
            sharing_status=sharing_status,
            strategy=strategy,
            rationale=rationale,
            candidate_tree=candidate_tree,
            expected_result_tree=result_tree,
            rollback_ref=rollback_ref,
            gate_ids=tuple(gate_ids),
            authorization_id=authorization_id,
        )
        route = self._proposal_route(proposal)
        if route == "dev_to_stable" and result_tree != candidate_tree:
            raise GitPolicyError("normal stable promotion must preserve the exact dev tree")
        return proposal

    def validate_proposal(
        self,
        proposal: MergeProposal,
        *,
        require_source_tree_result: bool = False,
    ) -> None:
        route = self._proposal_route(proposal)
        current_source = self.resolve_commit(proposal.source_ref)
        current_target = self.resolve_commit(proposal.target_ref)
        if current_source != proposal.source_commit:
            raise GitPolicyError("merge proposal source moved")
        if current_target != proposal.target_commit:
            raise GitPolicyError("merge proposal target moved")
        if self.tree_of(current_source) != proposal.candidate_tree:
            raise GitPolicyError("merge proposal candidate tree mismatch")
        simulated = self.simulate_result_tree(
            source_commit=current_source,
            target_commit=current_target,
            strategy=proposal.strategy,
        )
        if simulated != proposal.expected_result_tree:
            raise GitPolicyError("merge proposal result tree mismatch")
        stable_promotion = route == "dev_to_stable"
        if (require_source_tree_result or stable_promotion) and simulated != proposal.candidate_tree:
            raise GitPolicyError("stable promotion tree must exactly equal verified source tree")
        if proposal.strategy == "fast_forward" and not self.is_ancestor(
            proposal.target_commit, proposal.source_commit
        ):
            raise GitPolicyError("fast-forward proposal is not topologically valid")

    def execute_proposal(
        self,
        proposal: MergeProposal,
        *,
        require_source_tree_result: bool = False,
    ) -> MergeReceipt:
        self.assert_clean()
        route = self._proposal_route(proposal)
        action, required_gate = self._route_authority(route)
        self._protected_authority().require_proposal(
            proposal,
            action=action,
            protected_ref=self._target_branch(proposal),
            required_gate_type=required_gate,
        )
        self.validate_proposal(proposal, require_source_tree_result=require_source_tree_result)
        if proposal.strategy == "fast_forward":
            new_commit = proposal.source_commit
        else:
            parents = [proposal.target_commit]
            if proposal.strategy == "merge_commit":
                parents.append(proposal.source_commit)
            new_commit = self._commit_tree(
                proposal.expected_result_tree,
                parents=parents,
                message=f"NM V6 {proposal.purpose}: {proposal.strategy}",
            )
        if self.tree_of(new_commit) != proposal.expected_result_tree:
            raise GitPolicyError("created integration commit has an unexpected tree")
        branch = self._target_branch(proposal)
        observed_remote = self.fetch_branch(branch)
        if observed_remote != proposal.target_commit:
            raise GitPolicyError(
                "protected remote ref moved before integration; proposal evidence is stale"
            )
        checkpoint("git.before_protected_update")
        self._update_ref(proposal.target_ref, new_commit, proposal.target_commit)
        checkpoint("git.after_protected_update")
        return MergeReceipt(
            proposal.strategy,
            proposal.source_commit,
            proposal.target_commit,
            new_commit,
            proposal.expected_result_tree,
            proposal.rollback_ref,
            proposal.authorization_id,
            utc_now(),
        )

    def simulate_result_tree(
        self,
        *,
        source_commit: str,
        target_commit: str,
        strategy: str,
    ) -> str:
        if strategy not in MERGE_STRATEGIES:
            raise GitPolicyError(f"unsupported merge strategy: {strategy}")
        source_commit = self.resolve_commit(source_commit)
        target_commit = self.resolve_commit(target_commit)
        if strategy == "fast_forward":
            if not self.is_ancestor(target_commit, source_commit):
                raise GitPolicyError("source cannot fast-forward target")
            return self.tree_of(source_commit)
        result = run_command(
            ("git", "merge-tree", "--write-tree", target_commit, source_commit),
            cwd=self.repository,
            check=False,
        )
        if result.returncode != 0:
            raise GitPolicyError("merge simulation reported a conflict")
        tree = result.stdout.splitlines()[0].strip() if result.stdout else ""
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", tree):
            raise GitPolicyError("merge simulation did not produce a tree object")
        return self.resolve_tree(tree)

    def push_protected_cas(
        self,
        branch: str,
        *,
        expected_remote: str,
        new_commit: str,
        proposal: MergeProposal,
    ) -> PushReceipt:
        branch = _validate_branch(branch)
        self._assert_protected(branch)
        expected_remote = self.resolve_commit(expected_remote)
        new_commit = self.resolve_commit(new_commit)
        local_mutation_pending = False
        push_reconciled_as_succeeded = False
        try:
            route = self._proposal_route(proposal)
            if branch != self._target_branch(proposal):
                raise GitPolicyError(
                    "protected push branch differs from the authorized proposal"
                )
            action, required_gate = self._route_authority(route)
            self._protected_authority().require_proposal(
                proposal,
                action=action,
                protected_ref=branch,
                required_gate_type=required_gate,
            )
            if expected_remote != proposal.target_commit:
                raise GitPolicyError(
                    "protected push expected revision differs from the proposal"
                )
            if self.resolve_commit(proposal.target_ref) != new_commit:
                raise GitPolicyError(
                    "protected local ref does not equal the proposed result"
                )
            local_mutation_pending = True
            if self.tree_of(new_commit) != proposal.expected_result_tree:
                raise GitPolicyError("protected push tree differs from the verified proposal")
            observed = self.remote_head(branch)
            if observed != expected_remote:
                raise GitPolicyError("protected remote ref moved before push")
            if not self.is_ancestor(expected_remote, new_commit):
                raise GitPolicyError("non-fast-forward protected push is always forbidden")
            lease = f"--force-with-lease=refs/heads/{branch}:{expected_remote}"
            checkpoint("git.before_protected_push")
            result = run_command(
                (
                    "git",
                    "push",
                    "--porcelain",
                    lease,
                    self.remote,
                    f"{new_commit}:refs/heads/{branch}",
                ),
                cwd=self.repository,
                check=False,
            )
            if result.returncode != 0:
                reconciled = self.remote_head(branch)
                if reconciled != new_commit:
                    raise GitPolicyError("protected remote CAS push failed")
                push_reconciled_as_succeeded = True
            else:
                push_reconciled_as_succeeded = True
            checkpoint("git.after_protected_push")
            observed_after = self.remote_head(branch)
            if observed_after != new_commit:
                raise GitPolicyError(
                    "protected remote result does not equal authorized commit"
                )
        except GitPolicyError as exc:
            if local_mutation_pending and not push_reconciled_as_succeeded:
                try:
                    self._restore_local_protected_ref(proposal, new_commit)
                except GitPolicyError as restore_exc:
                    raise GitPolicyError(
                        f"{exc}; local protected ref restoration failed: {restore_exc}"
                    ) from restore_exc
            raise
        return PushReceipt(
            self.remote,
            branch,
            expected_remote,
            new_commit,
            False,
            observed_after,
            utc_now(),
        )

    def execute_nonprotected_ref_grant(
        self,
        grant: Mapping[str, Any],
        new_commit: str | None = None,
    ) -> NonProtectedRefReceipt:
        """Consume one exact backup-push or remote-delete grant, never both."""

        required = {
            "grant_id",
            "action",
            "remote",
            "ref",
            "expected_sha",
            "force",
            "one_time",
            "expires_at",
            "administrator_authorization_id",
        }
        if set(grant) != required:
            raise GitPolicyError("nonprotected-ref grant fields are incomplete or unknown")
        grant_id = grant["grant_id"]
        action = grant["action"]
        remote = grant["remote"]
        ref = grant["ref"]
        expected_sha = grant["expected_sha"]
        if not all(
            isinstance(value, str) and value
            for value in (grant_id, action, remote, ref, expected_sha, grant["expires_at"], grant["administrator_authorization_id"])
        ):
            raise GitPolicyError("nonprotected-ref grant contains an invalid string field")
        if action not in {"push_backup", "delete_remote"}:
            raise GitPolicyError("nonprotected-ref grant action is unsupported")
        if remote != self.remote:
            raise GitPolicyError("nonprotected-ref grant names a different remote")
        if grant["force"] is not False or grant["one_time"] is not True:
            raise GitPolicyError("nonprotected-ref grant must be one-time with force:false")
        try:
            expiry = datetime.fromisoformat(str(grant["expires_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise GitPolicyError("nonprotected-ref grant expiry is invalid") from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise GitPolicyError("nonprotected-ref grant is expired")
        if not ref.startswith("refs/heads/"):
            raise GitPolicyError("nonprotected-ref grant must name an exact branch ref")
        branch = _validate_branch(ref.removeprefix("refs/heads/"))
        if branch in self.protected_branches:
            raise GitPolicyError("nonprotected-ref grant cannot mutate a protected branch")
        expected_sha = self.resolve_commit(str(expected_sha))
        authority = self.nonprotected_authority
        if authority is None:
            raise GitPolicyError(
                "nonprotected-ref action requires the canonical SQLite authorization store"
            )
        resolved_new: str | None = None
        if action == "push_backup":
            if new_commit is None:
                raise GitPolicyError("backup-push grant requires the exact commit")
            resolved_new = self.resolve_commit(new_commit)
            if resolved_new != expected_sha:
                raise GitPolicyError("backup-push commit differs from the granted SHA")
            current_before = self.try_remote_head(branch)
            if current_before is not None and not self.is_ancestor(
                current_before, resolved_new
            ):
                raise GitPolicyError("backup push would be non-fast-forward")
        else:
            if new_commit is not None:
                raise GitPolicyError("remote deletion cannot reuse a backup-push payload")
            if self.try_remote_head(branch) != expected_sha:
                raise GitPolicyError("remote deletion target differs from the granted SHA")
        # Claim before the external effect. A crash cannot make the same grant
        # usable for a second effect; recovery must observe the exact ref.
        authority.claim({**dict(grant), "expected_sha": expected_sha})
        if action == "push_backup":
            assert resolved_new is not None
            current = self.try_remote_head(branch)
            if current is not None and not self.is_ancestor(current, resolved_new):
                raise GitPolicyError("backup push would be non-fast-forward")
            result = run_command(
                ("git", "push", "--porcelain", self.remote, f"{resolved_new}:{ref}"),
                cwd=self.repository,
                check=False,
            )
            if result.returncode != 0 or self.remote_head(branch) != resolved_new:
                raise GitPolicyError("backup push failed or produced an unexpected ref")
            observed_after: str | None = resolved_new
        else:
            current = self.try_remote_head(branch)
            if current != expected_sha:
                raise GitPolicyError("remote deletion target differs from the granted SHA")
            # A preceding observation is not a deletion guard: the ref may
            # move between ls-remote and receive-pack.  Bind the delete itself
            # to the exact signed SHA with Git's atomic ref lease.  This is a
            # compare-and-swap precondition, not permission for an
            # unconditional force push; the policy/receipt remains force:false.
            lease = f"--force-with-lease={ref}:{expected_sha}"
            result = run_command(
                ("git", "push", "--porcelain", lease, self.remote, f":{ref}"),
                cwd=self.repository,
                check=False,
            )
            observed_after = self.try_remote_head(branch)
            if observed_after is not None:
                if observed_after != expected_sha:
                    raise GitPolicyError(
                        "remote branch deletion CAS rejected a moved ref"
                    )
                raise GitPolicyError("remote branch deletion failed reconciliation")
            if result.returncode != 0:
                # receive-pack may report a transport failure after committing
                # the deletion.  The exact observed absence is authoritative.
                observed_after = None
        receipt = NonProtectedRefReceipt(
            str(grant_id),
            str(action),
            str(remote),
            str(ref),
            expected_sha,
            observed_after,
            False,
            utc_now(),
        )
        return receipt

    def remote_head(self, branch: str) -> str:
        branch = _validate_branch(branch)
        result = run_command(
            ("git", "ls-remote", "--heads", self.remote, f"refs/heads/{branch}"),
            cwd=self.repository,
            check=False,
        )
        if result.returncode != 0:
            raise GitPolicyError(f"cannot observe remote branch {branch}")
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            raise GitPolicyError(f"remote branch {branch} is missing or ambiguous")
        sha, ref = lines[0].split(maxsplit=1)
        if ref != f"refs/heads/{branch}":
            raise GitPolicyError("remote returned an unexpected ref")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", sha):
            raise GitPolicyError("remote returned an invalid object ID")
        return sha.lower()

    def try_remote_head(self, branch: str) -> str | None:
        try:
            return self.remote_head(branch)
        except GitPolicyError as exc:
            if "missing or ambiguous" in str(exc):
                return None
            raise

    def _build_cleanup_review_material(
        self,
        *,
        review_id: str,
        run_id: str,
        spec_hash: str,
        config_hash: str,
        branch: str,
        target_branch: str,
        receipt_id: str,
        integration_receipt: MergeReceipt,
        caller_facts: CleanupFacts | None,
    ) -> tuple[dict[str, Any], CleanupFacts]:
        """Recompute cleanup review facts without trusting reviewer booleans."""

        branch = _validate_branch(branch)
        target_branch = _validate_branch(target_branch)
        self._assert_protected(target_branch)
        if not isinstance(integration_receipt, MergeReceipt):
            raise GitPolicyError("cleanup review requires an exact MergeReceipt")
        if integration_receipt.strategy not in MERGE_STRATEGIES:
            raise GitPolicyError("cleanup MergeReceipt has an invalid strategy")

        def exact_commit(value: str, *, subject: str) -> str:
            if not isinstance(value, str) or re.fullmatch(
                r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value
            ) is None:
                raise GitPolicyError(f"cleanup {subject} is not an exact commit")
            resolved = self.resolve_commit(value)
            if resolved != value:
                raise GitPolicyError(f"cleanup {subject} is not an exact commit")
            return resolved

        source_commit = exact_commit(
            integration_receipt.source_commit, subject="source commit"
        )
        target_before = exact_commit(
            integration_receipt.target_before, subject="target-before commit"
        )
        target_after = exact_commit(
            integration_receipt.target_after, subject="target-after commit"
        )
        result_tree = self.resolve_tree(integration_receipt.result_tree)
        if result_tree != integration_receipt.result_tree:
            raise GitPolicyError("cleanup receipt result tree is not exact")
        observed_result_tree = self.tree_of(target_after)
        if observed_result_tree != result_tree:
            raise GitPolicyError("cleanup receipt result tree differs from Git")
        if (
            integration_receipt.strategy == "fast_forward"
            and target_after != source_commit
        ):
            raise GitPolicyError(
                "cleanup fast-forward receipt does not end at its source commit"
            )

        caller = caller_facts or CleanupFacts(
            branch=branch,
            expected_head=source_commit,
            integration_receipt=integration_receipt,
            run_id=run_id,
        )
        if not isinstance(caller, CleanupFacts):
            raise GitPolicyError("cleanup caller facts must use CleanupFacts")
        if caller.branch != branch or caller.expected_head != source_commit:
            raise GitPolicyError("cleanup caller facts changed the core branch binding")
        if caller.run_id not in {None, run_id}:
            raise GitPolicyError("cleanup caller facts changed the core run binding")
        if (
            caller.integration_receipt is not None
            and caller.integration_receipt != integration_receipt
        ):
            raise GitPolicyError("cleanup caller facts substituted the MergeReceipt")

        authority = self.cleanup_authority
        if authority is None:
            raise GitPolicyError(
                "cleanup review requires canonical Store cleanup authority"
            )
        source_ref = self._heads_ref(branch)
        target_ref = self._heads_ref(target_branch)
        observed_head = self.try_resolve_commit(source_ref)
        remote_source_head = self.try_remote_head(branch)
        local_target_head = self.resolve_commit(target_ref)
        remote_target_head = self.remote_head(target_branch)
        if local_target_head != remote_target_head:
            raise GitPolicyError(
                "cleanup review target local and configured-remote refs differ"
            )
        linked_worktrees = self._linked_worktree_paths(branch)
        snapshot = authority.snapshot(
            run_id=run_id,
            branch=branch,
            head=observed_head or source_commit,
        )
        if snapshot.run_id != run_id or snapshot.input_revision is None:
            raise GitPolicyError("cleanup authority returned a stale run snapshot")

        target_contains_result = self.is_ancestor(
            target_after, local_target_head
        )
        ancestry_proven = (
            integration_receipt.strategy != "squash"
            and self.is_ancestor(source_commit, target_after)
        )
        if integration_receipt.strategy == "squash":
            simulated_tree = self.simulate_result_tree(
                source_commit=source_commit,
                target_commit=target_before,
                strategy="squash",
            )
            patch_equivalent = simulated_tree == result_tree
            tree_equivalent = observed_result_tree == result_tree
        else:
            patch_equivalent = False
            tree_equivalent = observed_result_tree == result_tree

        receipt_document = seal_cleanup_integration_receipt(
            {
                "schema_version": INTEGRATION_RECEIPT_SCHEMA_VERSION,
                "receipt_id": receipt_id,
                "strategy": integration_receipt.strategy,
                "source_commit": source_commit,
                "target_ref": target_ref,
                "target_before": target_before,
                "target_after": target_after,
                "result_tree": result_tree,
                "rollback_ref": integration_receipt.rollback_ref,
                "authorization_id": integration_receipt.authorization_id,
                "executed_at": integration_receipt.executed_at,
            }
        )
        proof_document = seal_cleanup_integration_proof(
            {
                "schema_version": INTEGRATION_PROOF_SCHEMA_VERSION,
                "proof_kind": (
                    "patch_tree_equivalence"
                    if integration_receipt.strategy == "squash"
                    else "graph_ancestry"
                ),
                "strategy": integration_receipt.strategy,
                "source_head": source_commit,
                "target_commit": target_after,
                "current_target_head": local_target_head,
                "target_tree": observed_result_tree,
                "target_contains_integration_result": target_contains_result,
                "ancestry_proven": ancestry_proven,
                "patch_equivalent": patch_equivalent,
                "tree_equivalent": tree_equivalent,
            }
        )

        assertions = dict(snapshot.responsibility_assertions)
        caller_responsibility_blockers = {
            "review_responsibility_closed": caller.under_review,
            "backup_retention_absent": caller.backed_up,
            "dependent_work_closed": caller.dependent_work,
            "release_responsibility_closed": caller.release_responsibility,
            "rollback_responsibility_closed": caller.rollback_responsibility,
            "audit_retention_absent": caller.audit_retention,
            "explicit_retention_absent": caller.explicitly_retain,
        }
        responsibilities = {
            name: assertions.get(name) is True
            and not caller_responsibility_blockers[name]
            for name in caller_responsibility_blockers
        }
        live_leases = set(snapshot.live_lease_ids)
        live_sessions = set(snapshot.live_session_ids)
        dependent_workspaces = set(snapshot.dependent_workspace_paths)
        if caller.live_lease:
            live_leases.add("caller-asserted-live-lease")
        if caller.live_session:
            live_sessions.add("caller-asserted-live-session")
        if caller.dependent_workspace:
            dependent_workspaces.add("caller-asserted-dependent-workspace")
        facts_document = seal_cleanup_facts(
            {
                "schema_version": CLEANUP_FACTS_SCHEMA_VERSION,
                "run_id": run_id,
                "input_revision": snapshot.input_revision,
                "branch": branch,
                "expected_head": source_commit,
                "observed_head": observed_head,
                "authority_available": snapshot.authority_available,
                "responsibility_evidence_id": snapshot.responsibility_evidence_id,
                "is_protected": branch in self.protected_branches,
                "retained_pattern": branch.startswith(
                    ("release/", self.hotfix_prefix)
                ),
                "remote_branch_status": (
                    "present" if remote_source_head is not None else "absent"
                ),
                "remote_head": remote_source_head,
                "checked_out": bool(linked_worktrees),
                "linked_worktree_paths": list(linked_worktrees),
                "responsibilities": responsibilities,
                "blockers": {
                    "live_lease_ids": sorted(live_leases),
                    "live_session_ids": sorted(live_sessions),
                    "dependent_workspace_paths": sorted(dependent_workspaces),
                },
            }
        )
        request = seal_cleanup_review_request(
            {
                "schema_version": CLEANUP_REVIEW_REQUEST_SCHEMA_VERSION,
                "review_id": review_id,
                "run_id": run_id,
                "spec_hash": spec_hash,
                "config_hash": config_hash,
                "input_revision": snapshot.input_revision,
                "branch": branch,
                "branch_head": source_commit,
                "integration_receipt": receipt_document,
                "integration_proof": proof_document,
                "cleanup_facts": facts_document,
            }
        )
        core_facts = CleanupFacts(
            branch=branch,
            expected_head=source_commit,
            integration_receipt=integration_receipt,
            ancestry_proven=(
                ancestry_proven and target_contains_result
                if integration_receipt.strategy != "squash"
                else False
            ),
            patch_or_tree_equivalent=(
                patch_equivalent and tree_equivalent and target_contains_result
                if integration_receipt.strategy == "squash"
                else False
            ),
            under_review=caller.under_review,
            backed_up=caller.backed_up,
            dependent_work=caller.dependent_work,
            release_responsibility=caller.release_responsibility,
            rollback_responsibility=caller.rollback_responsibility,
            audit_retention=caller.audit_retention,
            live_lease=caller.live_lease,
            live_session=caller.live_session,
            dependent_workspace=caller.dependent_workspace,
            explicitly_retain=caller.explicitly_retain,
            run_id=run_id,
        )

        current_snapshot = authority.snapshot(
            run_id=run_id,
            branch=branch,
            head=observed_head or source_commit,
        )
        if (
            self.try_resolve_commit(source_ref) != observed_head
            or self.try_remote_head(branch) != remote_source_head
            or self.resolve_commit(target_ref) != local_target_head
            or self.remote_head(target_branch) != remote_target_head
            or self._linked_worktree_paths(branch) != linked_worktrees
            or current_snapshot != snapshot
        ):
            raise GitPolicyError("cleanup facts changed during request construction")
        return request, core_facts

    def build_cleanup_review_request(
        self,
        *,
        review_id: str,
        run_id: str,
        spec_hash: str,
        config_hash: str,
        branch: str,
        target_branch: str,
        receipt_id: str,
        integration_receipt: MergeReceipt,
        caller_facts: CleanupFacts | None = None,
    ) -> dict[str, Any]:
        """Seal a cleanup request from current Git and canonical Store facts."""

        try:
            request, _ = self._build_cleanup_review_material(
                review_id=review_id,
                run_id=run_id,
                spec_hash=spec_hash,
                config_hash=config_hash,
                branch=branch,
                target_branch=target_branch,
                receipt_id=receipt_id,
                integration_receipt=integration_receipt,
                caller_facts=caller_facts,
            )
            return request
        except ContractError as exc:
            raise GitPolicyError("cannot seal current cleanup review facts") from exc

    def validate_cleanup_review_decision(
        self,
        *,
        request: Mapping[str, Any],
        observation: Mapping[str, Any],
        review_id: str,
        run_id: str,
        spec_hash: str,
        config_hash: str,
        branch: str,
        target_branch: str,
        receipt_id: str,
        integration_receipt: MergeReceipt,
        caller_facts: CleanupFacts | None = None,
    ) -> CleanupDecision:
        """Recompute current facts, validate AI advice, then run core cleanup."""

        try:
            reviewed_request = validate_cleanup_review_request(request)
            current_request, core_facts = self._build_cleanup_review_material(
                review_id=review_id,
                run_id=run_id,
                spec_hash=spec_hash,
                config_hash=config_hash,
                branch=branch,
                target_branch=target_branch,
                receipt_id=receipt_id,
                integration_receipt=integration_receipt,
                caller_facts=caller_facts,
            )
            if canonical_json(reviewed_request) != canonical_json(current_request):
                raise GitPolicyError(
                    "cleanup review request differs from current core facts"
                )
            reviewed_observation = validate_cleanup_review_observations(
                current_request, [observation]
            )
        except ContractError as exc:
            raise GitPolicyError("cleanup review evidence is invalid") from exc
        core_decision = self.evaluate_cleanup(core_facts)
        if reviewed_observation["decision"] != core_decision.result:
            raise GitPolicyError(
                "cleanup reviewer decision differs from deterministic core"
            )
        return core_decision

    def evaluate_cleanup(self, facts: CleanupFacts) -> CleanupDecision:
        branch = _validate_branch(facts.branch)
        current = self.try_resolve_commit(self._heads_ref(branch))
        authority = self.cleanup_authority
        if authority is None:
            snapshot = CanonicalCleanupSnapshot(
                run_id=facts.run_id,
                input_revision=None,
                authority_available=False,
            )
        else:
            snapshot = authority.snapshot(
                run_id=facts.run_id,
                branch=branch,
                head=current or facts.expected_head,
            )
        linked_worktrees = self._linked_worktree_paths(branch)
        reasons: list[str] = []
        if current is None:
            reasons.append("branch_missing")
        elif current != facts.expected_head:
            reasons.append("branch_moved")
        if branch in self.protected_branches or branch.startswith(("release/", self.hotfix_prefix)):
            reasons.append("protected_or_retained_pattern")
        # These are conservative reviewer claims.  False values are never
        # treated as proof that a responsibility is absent.
        for field in (
            "under_review",
            "backed_up",
            "dependent_work",
            "release_responsibility",
            "rollback_responsibility",
            "audit_retention",
            "live_lease",
            "live_session",
            "dependent_workspace",
            "explicitly_retain",
        ):
            if getattr(facts, field):
                reasons.append(field)
        if not snapshot.authority_available:
            reasons.append("canonical_cleanup_authority_unavailable")
        if snapshot.live_lease_ids:
            reasons.append("live_lease")
        if snapshot.live_session_ids:
            reasons.append("live_session")
        if snapshot.dependent_workspace_paths:
            reasons.append("dependent_workspace")
        responsibility_reasons = {
            "review_responsibility_closed": "under_review",
            "backup_retention_absent": "backed_up",
            "dependent_work_closed": "dependent_work",
            "release_responsibility_closed": "release_responsibility",
            "rollback_responsibility_closed": "rollback_responsibility",
            "audit_retention_absent": "audit_retention",
            "explicit_retention_absent": "explicitly_retain",
        }
        assertions = dict(snapshot.responsibility_assertions)
        if snapshot.authority_available and snapshot.responsibility_evidence_id is None:
            reasons.append("canonical_responsibility_evidence_missing")
        if snapshot.authority_available:
            for assertion, reason in responsibility_reasons.items():
                if assertions.get(assertion) is False or (
                    snapshot.responsibility_evidence_id is not None
                    and assertions.get(assertion) is not True
                ):
                    reasons.append(reason)
        if linked_worktrees:
            reasons.append("linked_worktree_or_checkout")
        if facts.integration_receipt is None:
            reasons.append("missing_integration_receipt")
        elif facts.integration_receipt.strategy == "squash":
            if not facts.patch_or_tree_equivalent:
                reasons.append("missing_squash_equivalence")
        elif not facts.ancestry_proven:
            reasons.append("missing_ancestry_proof")
        reasons = list(dict.fromkeys(reasons))
        administrative = {
            "branch_missing",
            "branch_moved",
            "canonical_cleanup_authority_unavailable",
            "canonical_responsibility_evidence_missing",
        }
        if not reasons:
            result = "delete_local"
        elif "branch_moved" in reasons or set(reasons).issubset(administrative):
            result = "request_administrator"
        else:
            result = "retain"
        facts_material = {
            "schema_version": "nm-v6/branch-cleanup-facts-v1",
            "run_id": snapshot.run_id,
            "input_revision": snapshot.input_revision,
            "branch": branch,
            "expected_head": facts.expected_head,
            "observed_head": current,
            "integration_receipt": (
                asdict(facts.integration_receipt)
                if facts.integration_receipt is not None
                else None
            ),
            "ancestry_proven": facts.ancestry_proven,
            "patch_or_tree_equivalent": facts.patch_or_tree_equivalent,
            "reviewer_retention_claims": {
                field: bool(getattr(facts, field))
                for field in (
                    "under_review",
                    "backed_up",
                    "dependent_work",
                    "release_responsibility",
                    "rollback_responsibility",
                    "audit_retention",
                    "live_lease",
                    "live_session",
                    "dependent_workspace",
                    "explicitly_retain",
                )
            },
            "canonical_snapshot": asdict(snapshot),
            "linked_worktree_paths": list(linked_worktrees),
        }
        facts_digest = sha256_bytes(canonical_json(facts_material))
        decision = CleanupDecision(
            result,
            branch,
            current or facts.expected_head,
            tuple(reasons),
            utc_now(),
            facts_digest,
            snapshot.run_id,
            snapshot.input_revision,
        )
        if (
            authority is not None
            and snapshot.run_id is not None
            and snapshot.input_revision is not None
        ):
            persisted = authority.record(
                run_id=snapshot.run_id,
                input_revision=snapshot.input_revision,
                record={
                    "schema_version": "nm-v6/branch-cleanup-record-v1",
                    "record_kind": "decision",
                    "facts_digest": facts_digest,
                    "facts": facts_material,
                    "decision": {
                        "result": result,
                        "branch": branch,
                        "head": decision.head,
                        "reasons": reasons,
                        "decided_at": decision.decided_at,
                    },
                },
                idempotency_key=(
                    f"cleanup-decision:{sha256_bytes(branch.encode('utf-8'))}:"
                    f"{snapshot.input_revision}:{facts_digest}"
                ),
            )
            decision = replace(
                decision,
                decision_event_id=(
                    str(persisted["event_id"]) if persisted.get("event_id") else None
                ),
            )
        return decision

    def delete_local_branch(
        self,
        decision: CleanupDecision,
        *,
        current_facts: CleanupFacts,
    ) -> CleanupReceipt:
        if decision.result != "delete_local":
            raise GitPolicyError("cleanup decision does not authorize local deletion")
        if decision.run_id != current_facts.run_id:
            raise GitPolicyError("cleanup decision and current facts belong to different runs")
        fresh = self.evaluate_cleanup(current_facts)
        if (
            fresh.result != "delete_local"
            or fresh.branch != decision.branch
            or fresh.head != decision.head
        ):
            raise GitPolicyError(
                "branch cleanup facts changed; a fresh delete_local decision is required"
            )
        if decision.branch in self.protected_branches or decision.branch.startswith(
            ("release/", self.hotfix_prefix)
        ):
            raise GitPolicyError("protected or retained branch cannot be deleted")
        if self._linked_worktree_paths(decision.branch):
            raise GitPolicyError("branch is checked out in a worktree")
        self._delete_ref(self._heads_ref(decision.branch), decision.head)
        receipt = CleanupReceipt(
            "deleted",
            decision.branch,
            decision.head,
            decision.decided_at,
            fresh.decided_at,
            utc_now(),
            fresh.facts_digest,
            fresh.run_id,
            fresh.input_revision,
            fresh.decision_event_id,
        )
        authority = self.cleanup_authority
        if (
            authority is not None
            and fresh.run_id is not None
            and fresh.input_revision is not None
        ):
            # Recording the fresh decision increments the canonical revision
            # exactly once.  Any intervening state change makes this CAS fail
            # instead of silently attaching a receipt to stale facts.
            persisted = authority.record(
                run_id=fresh.run_id,
                input_revision=fresh.input_revision + 1,
                record={
                    "schema_version": "nm-v6/branch-cleanup-record-v1",
                    "record_kind": "execution_receipt",
                    "facts_digest": fresh.facts_digest,
                    "decision_event_id": fresh.decision_event_id,
                    "receipt": {
                        "result": receipt.result,
                        "branch": receipt.branch,
                        "deleted_head": receipt.deleted_head,
                        "prior_decision_at": receipt.prior_decision_at,
                        "reevaluated_at": receipt.reevaluated_at,
                        "executed_at": receipt.executed_at,
                    },
                },
                idempotency_key=(
                    f"cleanup-execution:{sha256_bytes(fresh.branch.encode('utf-8'))}:"
                    f"{fresh.input_revision + 1}:{fresh.facts_digest}"
                ),
            )
            receipt = replace(
                receipt,
                execution_event_id=(
                    str(persisted["event_id"]) if persisted.get("event_id") else None
                ),
            )
        return receipt

    def changed_paths(self, base: str, candidate: str) -> tuple[str, ...]:
        result = run_command(
            ("git", "diff", "--name-only", "-z", base, candidate, "--"),
            cwd=self.repository,
        )
        return tuple(sorted(path for path in result.stdout.split("\0") if path))

    def tree_of(self, commit: str) -> str:
        return self.resolve_tree(f"{commit}^{{tree}}")

    def resolve_commit(self, value: str) -> str:
        result = run_command(
            ("git", "rev-parse", "--verify", f"{value}^{{commit}}"),
            cwd=self.repository,
            check=False,
        )
        sha = result.stdout.strip()
        if result.returncode != 0 or not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
            raise GitPolicyError(f"cannot resolve commit: {value}")
        return sha.lower()

    def try_resolve_commit(self, value: str) -> str | None:
        try:
            return self.resolve_commit(value)
        except GitPolicyError:
            return None

    def resolve_tree(self, value: str) -> str:
        result = run_command(
            ("git", "rev-parse", "--verify", f"{value}^{{tree}}"),
            cwd=self.repository,
            check=False,
        )
        sha = result.stdout.strip()
        if result.returncode != 0 or not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
            raise GitPolicyError(f"cannot resolve tree: {value}")
        return sha.lower()

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        result = run_command(
            ("git", "merge-base", "--is-ancestor", ancestor, descendant),
            cwd=self.repository,
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise GitPolicyError("cannot determine Git ancestry")
        return result.returncode == 0

    def _protected_authority(self) -> ProtectedMutationAuthority:
        if self.protected_authority is None:
            raise GitPolicyError(
                "protected Git mutation requires a canonical gate/authorization resolver"
            )
        return self.protected_authority

    def _target_branch(self, proposal: MergeProposal) -> str:
        prefix = "refs/heads/"
        if not proposal.target_ref.startswith(prefix):
            raise GitPolicyError("merge proposal target is not an exact local branch ref")
        branch = _validate_branch(proposal.target_ref.removeprefix(prefix))
        self._assert_protected(branch)
        return branch

    def _source_branch(self, proposal: MergeProposal) -> str:
        prefix = "refs/heads/"
        source = proposal.source_ref
        if source.startswith(prefix):
            return _validate_branch(source.removeprefix(prefix))
        if source.startswith("refs/") or re.fullmatch(r"[0-9a-fA-F]{40,64}", source):
            raise GitPolicyError("protected integration source must be an exact local branch")
        return _validate_branch(source)

    def _branch_from_exact_ref(self, source_ref: str) -> str:
        prefix = "refs/heads/"
        if not isinstance(source_ref, str) or not source_ref.startswith(prefix):
            raise GitPolicyError("merge review source must be an exact local branch ref")
        branch = source_ref.removeprefix(prefix)
        try:
            return _validate_branch(branch)
        except ContractError as exc:
            raise GitPolicyError("merge review source branch is invalid") from exc

    def _merge_review_route(
        self,
        *,
        source_branch: str,
        source_commit: str,
        target_branch: str,
        target_commit: str,
    ) -> str:
        if self.resolve_commit(self._heads_ref(source_branch)) != source_commit:
            raise GitPolicyError("merge review source branch moved during fact collection")
        if target_branch == self.integration_branch:
            if source_branch.startswith(self.hotfix_prefix) and len(
                source_branch
            ) > len(self.hotfix_prefix):
                return "hotfix_to_dev"
            if any(
                source_branch.startswith(prefix) and len(source_branch) > len(prefix)
                for prefix in self.work_branch_prefixes
            ):
                return "work_to_dev"
            raise GitPolicyError(
                "dev merge review requires an allowed work or hotfix branch"
            )
        if target_branch == self.stable_branch:
            if source_branch == self.integration_branch:
                return "dev_to_stable"
            if source_branch.startswith(self.hotfix_prefix) and len(
                source_branch
            ) > len(self.hotfix_prefix):
                if not self.is_ancestor(target_commit, source_commit):
                    raise GitPolicyError(
                        "hotfix merge review source is not based on current stable"
                    )
                return "hotfix_to_stable"
            raise GitPolicyError("stable merge review requires dev or a hotfix branch")
        raise GitPolicyError("merge review target is outside configured protected refs")

    @staticmethod
    def _canonical_merge_review_strategies(
        allowed_strategies: Iterable[str],
    ) -> list[str]:
        if isinstance(allowed_strategies, (str, bytes)):
            raise ContractError("allowed merge strategies must be an iterable of names")
        provided = tuple(allowed_strategies)
        if (
            not provided
            or any(
                not isinstance(strategy, str)
                or strategy not in MERGE_REVIEW_STRATEGIES
                for strategy in provided
            )
            or len(provided) != len(set(provided))
        ):
            raise ContractError("allowed merge strategies are empty, duplicate, or invalid")
        return [
            strategy
            for strategy in MERGE_REVIEW_STRATEGIES
            if strategy in provided
        ]

    def _unique_merge_base(self, source_commit: str, target_commit: str) -> str:
        result = run_command(
            ("git", "merge-base", "--all", source_commit, target_commit),
            cwd=self.repository,
            check=False,
        )
        candidates = tuple(
            line.strip() for line in result.stdout.splitlines() if line.strip()
        )
        if result.returncode != 0 or len(candidates) != 1:
            raise GitPolicyError("merge review requires exactly one Git merge base")
        return self.resolve_commit(candidates[0])

    def _rev_list_count(self, *arguments: str) -> int:
        result = run_command(
            ("git", "rev-list", "--count", *arguments),
            cwd=self.repository,
            check=False,
        )
        value = result.stdout.strip()
        if result.returncode != 0 or not value.isdigit():
            raise GitPolicyError("cannot compute merge review commit counts")
        return int(value)

    def _merge_review_strategy_results(
        self,
        *,
        source_commit: str,
        target_commit: str,
        source_tree: str,
        exact_source_tree_required: bool,
    ) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for strategy in MERGE_REVIEW_STRATEGIES:
            try:
                result_tree = self.simulate_result_tree(
                    source_commit=source_commit,
                    target_commit=target_commit,
                    strategy=strategy,
                )
            except GitPolicyError:
                results[strategy] = {
                    "valid": False,
                    "conflict": strategy != "fast_forward",
                    "expected_result_tree": None,
                }
                continue
            exact_tree_valid = (
                not exact_source_tree_required or result_tree == source_tree
            )
            results[strategy] = {
                "valid": exact_tree_valid,
                "conflict": False,
                "expected_result_tree": result_tree if exact_tree_valid else None,
            }
        return results

    def _proposal_route(self, proposal: MergeProposal) -> str:
        target = self._target_branch(proposal)
        source = self._source_branch(proposal)
        if self.resolve_commit(self._heads_ref(source)) != proposal.source_commit:
            raise GitPolicyError("merge proposal source branch does not match its recorded commit")
        if target == self.integration_branch:
            if source.startswith(self.hotfix_prefix) and len(source) > len(self.hotfix_prefix):
                return "hotfix_to_dev"
            if any(
                source.startswith(prefix) and len(source) > len(prefix)
                for prefix in self.work_branch_prefixes
            ):
                return "work_to_dev"
            raise GitPolicyError("dev accepts only an allowed work branch or hotfix reconciliation")
        if target == self.stable_branch:
            if source == self.integration_branch:
                if self.resolve_commit(self._heads_ref(self.integration_branch)) != proposal.source_commit:
                    raise GitPolicyError("stable promotion source does not equal current dev")
                return "dev_to_stable"
            if source.startswith(self.hotfix_prefix) and len(source) > len(self.hotfix_prefix):
                if not self.is_ancestor(proposal.target_commit, proposal.source_commit):
                    raise GitPolicyError("hotfix source is not based on the expected stable revision")
                return "hotfix_to_stable"
            raise GitPolicyError("stable accepts only verified dev or an exact hotfix branch")
        raise GitPolicyError("merge proposal target is outside configured protected refs")

    @staticmethod
    def _route_authority(route: str) -> tuple[str, str]:
        routes = {
            "work_to_dev": ("integrate_dev", "DEV_INTEGRATION_GATE"),
            "hotfix_to_dev": (
                "hotfix_reconcile_dev",
                "HOTFIX_RECONCILIATION_GATE",
            ),
            "dev_to_stable": ("release", "RELEASE_GATE"),
            "hotfix_to_stable": (
                "hotfix_stable",
                "HOTFIX_STABLE_GATE",
            ),
        }
        try:
            return routes[route]
        except KeyError as exc:
            raise GitPolicyError(f"unsupported protected Git route: {route}") from exc

    def _commit_tree(self, tree: str, *, parents: Sequence[str], message: str) -> str:
        argv = ["git", "commit-tree", tree]
        for parent in parents:
            argv.extend(("-p", parent))
        timestamp = utc_now()
        environment = {
            **os.environ,
            "GIT_AUTHOR_NAME": "NM V6 Controller",
            "GIT_AUTHOR_EMAIL": "nm-v6@invalid.local",
            "GIT_COMMITTER_NAME": "NM V6 Controller",
            "GIT_COMMITTER_EMAIL": "nm-v6@invalid.local",
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
        }
        argv.extend(("-m", message))
        result = run_command(tuple(argv), cwd=self.repository, env=environment, check=False)
        if result.returncode != 0:
            raise GitPolicyError("cannot create integration commit")
        commit = result.stdout.strip()
        return self.resolve_commit(commit)

    def _branch_in_linked_worktree(self, branch: str) -> bool:
        return bool(self._linked_worktree_paths(branch))

    def _linked_worktree_paths(self, branch: str) -> tuple[str, ...]:
        branch = _validate_branch(branch)
        result = run_command(("git", "worktree", "list", "--porcelain"), cwd=self.repository)
        target = f"refs/heads/{branch}"
        paths: list[str] = []
        current_path: str | None = None
        current_branch: str | None = None
        for line in (*result.stdout.splitlines(), ""):
            if not line:
                if current_path is not None and current_branch == target:
                    paths.append(str(Path(current_path).resolve()))
                current_path = None
                current_branch = None
            elif line.startswith("worktree "):
                current_path = line.removeprefix("worktree ")
            elif line.startswith("branch "):
                current_branch = line.removeprefix("branch ")
        return tuple(sorted(set(paths)))

    def _assert_new_branch(self, branch: str) -> None:
        if branch in self.protected_branches:
            raise GitPolicyError("worker branch cannot be protected")
        if self.try_resolve_commit(self._heads_ref(branch)) is not None:
            raise GitPolicyError(f"branch already exists: {branch}")

    def _assert_protected(self, branch: str) -> None:
        if branch not in self.protected_branches:
            raise GitPolicyError(f"ref is not a configured protected branch: {branch}")

    def _assert_remote_exists(self) -> None:
        remotes = run_command(("git", "remote"), cwd=self.repository).stdout.splitlines()
        if self.remote not in remotes:
            raise GitPolicyError(f"configured remote does not exist: {self.remote}")

    def _update_ref(self, ref: str, new: str, old: str | None) -> None:
        argv = ["git", "update-ref", ref, new]
        if old is not None:
            argv.append(old)
        result = run_command(tuple(argv), cwd=self.repository, check=False)
        if result.returncode != 0:
            raise GitPolicyError(f"compare-and-swap failed for {ref}")

    def _delete_ref(self, ref: str, old: str) -> None:
        result = run_command(("git", "update-ref", "-d", ref, old), cwd=self.repository, check=False)
        if result.returncode != 0:
            raise GitPolicyError(f"compare-and-swap deletion failed for {ref}")

    def _restore_local_protected_ref(
        self, proposal: MergeProposal, attempted_commit: str
    ) -> None:
        current = self.try_resolve_commit(proposal.target_ref)
        if current == proposal.target_commit:
            return
        if current != attempted_commit:
            raise GitPolicyError(
                "local protected ref changed concurrently and cannot be restored safely"
            )
        self._update_ref(
            proposal.target_ref,
            proposal.target_commit,
            attempted_commit,
        )

    @staticmethod
    def _heads_ref(branch: str) -> str:
        return f"refs/heads/{branch}"


def _validate_branch(value: str) -> str:
    if not isinstance(value, str) or not _BRANCH.fullmatch(value):
        raise ContractError(f"invalid Git branch name: {value!r}")
    if value.startswith("-") or value.endswith("/") or "/." in value or value.endswith(".lock"):
        raise ContractError(f"invalid Git branch name: {value!r}")
    return value
