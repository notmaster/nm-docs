"""The only domain writer for the NM V6 SQLite authority."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Mapping, Protocol

from .authorization import (
    SHA256_PATTERN,
    VerifiedAuthorization,
    authorization_request_digest,
    authorization_scope_allows,
    parse_timestamp,
    validate_authorization_record,
)
from .errors import AuthorizationError, ContractError, TransitionError
from .evidence import EvidenceStore
from .failpoints import checkpoint
from .gates import validate_gate_decision, validate_gate_evidence_bindings
from .models import OperationObservation, TransitionProposal
from .outbox import NotificationIntent, retry_at, validate_intent
from .specs import validate_traceability
from .store import Store
from .transitions import (
    ATTEMPT_STATES,
    DEFAULT_TRANSITION_TABLE,
    PHASE_STATES,
    RUN_STATES,
    TASK_STATES,
    TERMINAL_RUN_STATES,
    TransitionRule,
    TransitionTable,
)
from .util import IDENTIFIER_PATTERNS, canonical_json, sha256_bytes, utc_now


class SignatureVerifier(Protocol):
    def verify(
        self, record: Mapping[str, Any], *, now: datetime | None = None
    ) -> VerifiedAuthorization: ...


MUTATING_OPERATION_KINDS = frozenset(
    {
        "git",
        "protected_ref",
        "external_mutation",
        "release",
        "publish",
        "deploy",
        "rollback",
    }
)

_MUTATION_ACTION_GATES: dict[str, tuple[str, str]] = {
    "integrate_dev": ("INTEGRATING_DEV", "DEV_INTEGRATION_GATE"),
    "hotfix_stable": ("HOTFIX_INTEGRATING_STABLE", "HOTFIX_STABLE_GATE"),
    "hotfix_reconcile_dev": (
        "HOTFIX_RECONCILING_DEV",
        "HOTFIX_RECONCILIATION_GATE",
    ),
    "release": ("RELEASING", "RELEASE_GATE"),
    "publish": ("RELEASING", "RELEASE_GATE"),
    "deploy": ("DEPLOYING", "DEPLOY_GATE"),
    "rollback": ("ROLLING_BACK", "ROLLBACK_GATE"),
}

_MUTATION_ACTION_SCOPE_BINDINGS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "integrate_dev": (
        ("protected_ref", None),
        ("candidate_commit", "candidate_commit"),
        ("target_commit", "target_commit"),
    ),
    "hotfix_stable": (
        ("protected_ref", None),
        ("candidate_commit", "candidate_commit"),
        ("target_commit", "target_commit"),
    ),
    "hotfix_reconcile_dev": (
        ("protected_ref", None),
        ("candidate_commit", "candidate_commit"),
        ("target_commit", "target_commit"),
    ),
    "release": (
        ("protected_ref", None),
        ("source_commit", "source_commit"),
        ("target_commit", "target_commit"),
        ("release_source_kind", "release_source_kind"),
        ("release_source_commit", "release_source_commit"),
        ("release_source_tree", "release_source_tree"),
        ("artifact_digest", "artifact_digest"),
    ),
    "publish": (
        ("protected_ref", None),
        ("source_commit", "source_commit"),
        ("target_commit", "target_commit"),
        ("release_source_kind", "release_source_kind"),
        ("release_source_commit", "release_source_commit"),
        ("release_source_tree", "release_source_tree"),
        ("artifact_digest", "artifact_digest"),
    ),
    "deploy": (
        ("artifact_digest", "artifact_digest"),
        ("environment_id", "environment_id"),
        ("environment_fingerprint", "environment_fingerprint"),
    ),
    "rollback": (
        ("artifact_digest", "artifact_digest"),
        ("environment_id", "environment_id"),
        ("environment_fingerprint", "environment_fingerprint"),
    ),
}


def required_mutation_scope_fields(action_id: str) -> tuple[str, ...]:
    """Return the complete, action-specific external Operation scope contract."""

    bindings = _MUTATION_ACTION_SCOPE_BINDINGS.get(action_id)
    if bindings is None:
        raise ContractError(f"unsupported external mutation action: {action_id}")
    return tuple(scope_field for scope_field, _decision_field in bindings)

_PREPLAN_STATES = frozenset(
    {
        "DISCOVERING",
        "SPEC_DRAFT",
        "SPEC_REVIEW",
        "SPEC_AWAITING_CONFIRMATION",
        "SPEC_CONFIRMED",
        "PLANNING",
    }
)

_EXTERNAL_STAGE_AUTHORIZATIONS = frozenset(
    {
        "integrate_dev",
        "hotfix_stable",
        "hotfix_reconcile_dev",
        "release",
        "deploy",
        "rollback",
    }
)

DOMAIN_EVENT_TYPES = frozenset(
    {
        "ADAPTER_REQUESTED",
        "ADAPTER_SESSION_RECORDED",
        "ADAPTER_RESULT_RECORDED",
        "ADAPTER_ATTEMPT_STALE",
        "TASK_BATCH_PLANNED",
        "TASK_RESULT_IMPORTED",
        "TASK_BATCH_MERGE_PLANNED",
        "TASK_BATCH_COMPLETED",
        "TASK_BATCH_BLOCKED",
        "CANDIDATE_BRANCH_BOUND",
        "CANDIDATE_BRANCH_ADVANCED",
        "MERGE_PROPOSED",
        "BRANCH_CLEANUP_DECIDED",
        "PROTECTED_REF_CHANGED",
        "PROTECTED_REF_PUSHED",
        "RELEASE_OPERATION_RECORDED",
        "DEPLOYMENT_OPERATION_RECORDED",
        "HEALTH_OPERATION_RECORDED",
        "ROLLBACK_OPERATION_RECORDED",
        "RECONCILIATION_RECORDED",
        "SECRET_REDACTION_RECORDED",
        "CONTROLLER_LAUNCH_REQUESTED",
        "CONTROLLER_STATUS_RECORDED",
    }
)

_FENCED_RUN_STATES = frozenset({"PAUSED", "ATTENTION_REQUIRED"})
_RUN_WRITE_FENCED_STATES = _FENCED_RUN_STATES | TERMINAL_RUN_STATES
_SAFE_POINT_EVENTS = frozenset(
    {
        "REQUEST_PAUSE",
        "RESUME",
        "CANCEL",
        "FAIL_UNRECOVERABLE",
        "COMPLETE_RUN",
        "SKIP_DEPLOY_NOT_APPLICABLE",
        "ROLLBACK_VERIFIED",
    }
)

_RUN_INPUT_PAYLOAD_FIELDS = frozenset(
    {"traceability", "spec_id", "spec_version"}
)


def _request_digest(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(dict(value)))


def _intent_documents(
    intents: Iterable[NotificationIntent | Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[NotificationIntent]]:
    documents: list[dict[str, Any]] = []
    normalized: list[NotificationIntent] = []
    for raw in intents:
        intent = validate_intent(raw)
        normalized.append(intent)
        documents.append(
            {
                "notification_id": intent.notification_id,
                "route": intent.route,
                "severity": intent.severity,
                "payload": intent.payload,
            }
        )
    return documents, normalized


class Reducer:
    """Validate proposals and commit one logical event per transaction."""

    def __init__(
        self,
        store: Store,
        *,
        transitions: TransitionTable = DEFAULT_TRANSITION_TABLE,
        evidence_store: EvidenceStore | None = None,
    ) -> None:
        self.store = store
        self.transitions = transitions
        self.evidence_store = evidence_store or EvidenceStore(store.path.parent / "evidence")

    @staticmethod
    def _run_row(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise TransitionError(f"unknown run: {run_id}")
        return row

    @staticmethod
    def _require_revision(row: sqlite3.Row, expected_revision: int) -> None:
        actual = int(row["revision"])
        if actual != expected_revision:
            raise TransitionError(
                f"stale expected revision: expected {expected_revision}, current {actual}"
            )

    @staticmethod
    def _require_nonterminal_run(run: Mapping[str, Any], *, action: str) -> None:
        state = str(run["state"])
        if state in TERMINAL_RUN_STATES:
            raise AuthorizationError(
                f"{action} is forbidden after run entered terminal state {state}"
            )

    @classmethod
    def _require_active_run(cls, run: Mapping[str, Any], *, action: str) -> None:
        cls._require_nonterminal_run(run, action=action)
        state = str(run["state"])
        if state in _FENCED_RUN_STATES:
            raise TransitionError(f"{action} is fenced while run is {state}")

    @staticmethod
    def _active_external_operation_ids(
        connection: sqlite3.Connection, run_id: str
    ) -> tuple[str, ...]:
        return tuple(
            str(row["operation_id"])
            for row in connection.execute(
                "SELECT operation_id FROM external_operations WHERE run_id = ? "
                "AND status IN ('started', 'partial', 'unknown') ORDER BY operation_id",
                (run_id,),
            ).fetchall()
        )

    @staticmethod
    def _bump_run(
        store: Store,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        expected_revision: int,
        timestamp: str,
    ) -> int:
        new_revision = expected_revision + 1
        store._cas_run_revision(
            connection,
            run_id=run_id,
            expected_revision=expected_revision,
            new_revision=new_revision,
            updated_at=timestamp,
        )
        return new_revision

    def create_run(
        self,
        *,
        run_id: str,
        spec_hash: str,
        config_hash: str,
        mode: str = "staged",
        run_kind: str = "normal",
        actor: str = "core",
        idempotency_key: str,
        payload: Mapping[str, Any] | None = None,
        outbox: Iterable[NotificationIntent | Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        if mode not in {"staged", "auto"} or run_kind not in {"normal", "hotfix"}:
            raise ContractError("invalid run mode or run kind")
        if not run_id or not spec_hash or not config_hash or not idempotency_key:
            raise ContractError("run_id, hashes, and idempotency_key are required")
        document = {
            "run_id": run_id,
            "spec_hash": spec_hash,
            "config_hash": config_hash,
            "mode": mode,
            "run_kind": run_kind,
            "payload": dict(payload or {}),
        }
        digest = _request_digest(document)
        scope = f"run:create:{run_id}"
        outbox_documents, normalized_outbox = _intent_documents(outbox)
        timestamp = utc_now()
        projection = {
            "kind": "run_create",
            **document,
            "revision": 0,
            "state": "DISCOVERING",
            "resume_state": None,
            "updated_at": timestamp,
        }
        event_payload = {"request": document, "projection": projection, "outbox": outbox_documents}
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            if connection.execute(
                "SELECT 1 FROM run_registry WHERE run_id = ?", (run_id,)
            ).fetchone():
                raise TransitionError(f"run already exists: {run_id}")
            connection.execute(
                "INSERT INTO run_registry(run_id, created_at) VALUES (?, ?)",
                (run_id, timestamp),
            )
            result = self.store._record_event(
                connection,
                scope=scope,
                run_id=run_id,
                run_revision=0,
                event_type="RUN_CREATED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={"run_id": run_id, "revision": 0, "state": "DISCOVERING"},
                outbox=normalized_outbox,
            )
            self.store._apply_projection(connection, projection)
            return result

    def amend_run_inputs(
        self,
        *,
        run_id: str,
        expected_revision: int,
        spec_hash: str,
        config_hash: str,
        impact_analysis: Mapping[str, Any],
        traceability: Mapping[str, Any] | None = None,
        idempotency_key: str,
        actor: str = "trusted-control-plane",
    ) -> dict[str, Any]:
        """Apply a versioned Spec/config amendment and invalidate old bindings.

        Evidence, gates, confirmations, and grants remain immutable audit records,
        but their old hash bindings can no longer authorize progress.  The run is
        returned to ``SPEC_DRAFT`` so a later transition cannot bypass review and
        confirmation of the amended inputs.
        """

        if not SHA256_PATTERN.fullmatch(spec_hash) or not SHA256_PATTERN.fullmatch(
            config_hash
        ):
            raise ContractError("amended Spec/config hashes must be lowercase SHA-256")
        if not isinstance(impact_analysis, Mapping) or not impact_analysis:
            raise ContractError("Spec/config amendment requires a nonempty impact analysis")
        reason = impact_analysis.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ContractError("Spec/config amendment impact analysis requires a reason")
        if traceability is not None:
            if not isinstance(traceability, Mapping):
                raise ContractError("amended traceability must be an object")
            validate_traceability(traceability)
        document = {
            "run_id": run_id,
            "expected_revision": expected_revision,
            "spec_hash": spec_hash,
            "config_hash": config_hash,
            "impact_analysis": dict(impact_analysis),
            "traceability": (
                dict(traceability) if traceability is not None else None
            ),
        }
        digest = _request_digest(document)
        scope_name = f"run:amend-inputs:{run_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            self._require_nonterminal_run(run, action="amend Spec/config inputs")
            if run["state"] in {
                "DISCOVERING",
                "SPEC_DRAFT",
                "SPEC_REVIEW",
                "SPEC_AWAITING_CONFIRMATION",
            }:
                raise TransitionError("only a confirmed Spec/config binding can be amended")
            if run["spec_hash"] == spec_hash and run["config_hash"] == config_hash:
                raise ContractError("Spec/config amendment must change at least one hash")
            active = self._active_external_operation_ids(connection, run_id)
            if active:
                raise TransitionError(
                    "Spec/config amendment requires reconciled external operations: "
                    + ", ".join(active)
                )

            invalidated_evidence = tuple(
                str(row["evidence_id"])
                for row in connection.execute(
                    "SELECT evidence_id FROM evidence_receipts WHERE run_id = ? "
                    "ORDER BY evidence_id",
                    (run_id,),
                ).fetchall()
            )
            invalidated_gates = tuple(
                str(row["gate_id"])
                for row in connection.execute(
                    "SELECT gate_id FROM gate_decisions WHERE run_id = ? ORDER BY gate_id",
                    (run_id,),
                ).fetchall()
            )
            invalidated_authorizations = tuple(
                str(row["authorization_id"])
                for row in connection.execute(
                    "SELECT authorization_id FROM authorization_records WHERE run_id = ? "
                    "AND record_type IN ('spec_confirmation', 'grant', 'approval') "
                    "ORDER BY authorization_id",
                    (run_id,),
                ).fetchall()
            )
            timestamp = utc_now()
            new_revision = expected_revision + 1
            previous_payload = json.loads(run["payload_json"])
            amendment_record = {
                "previous_spec_hash": run["spec_hash"],
                "previous_config_hash": run["config_hash"],
                "previous_state": run["state"],
                "impact_analysis": dict(impact_analysis),
                "invalidated_evidence_ids": list(invalidated_evidence),
                "invalidated_gate_ids": list(invalidated_gates),
                "invalidated_authorization_ids": list(invalidated_authorizations),
            }
            amended_payload = {
                **previous_payload,
                "latest_input_amendment": amendment_record,
            }
            if traceability is None:
                amended_payload.pop("traceability", None)
            else:
                amended_payload["traceability"] = dict(traceability)
            projection = {
                "kind": "run_control",
                "run_id": run_id,
                "previous_revision": expected_revision,
                "revision": new_revision,
                "state": "SPEC_DRAFT",
                "resume_state": None,
                "mode": run["mode"],
                "spec_hash": spec_hash,
                "config_hash": config_hash,
                "payload": amended_payload,
                "updated_at": timestamp,
            }
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="RUN_INPUTS_AMENDED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload={"request": document, "projection": projection},
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "state": "SPEC_DRAFT",
                    "spec_hash": spec_hash,
                    "config_hash": config_hash,
                    "invalidated_evidence_ids": list(invalidated_evidence),
                    "invalidated_gate_ids": list(invalidated_gates),
                    "invalidated_authorization_ids": list(invalidated_authorizations),
                },
            )
            self.store._apply_projection(connection, projection)
            return result

    def record_domain_event(
        self,
        *,
        run_id: str,
        expected_revision: int,
        event_type: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        actor: str,
    ) -> dict[str, Any]:
        """Record one allowlisted audit-only domain event through the authority."""

        if event_type not in DOMAIN_EVENT_TYPES:
            raise ContractError(f"unsupported audit domain event type: {event_type!r}")
        if not isinstance(payload, Mapping):
            raise ContractError("audit domain event payload must be an object")
        if not actor or not idempotency_key:
            raise ContractError("audit domain event actor and idempotency key are required")
        document = {
            "run_id": run_id,
            "expected_revision": expected_revision,
            "event_type": event_type,
            "payload": dict(payload),
        }
        digest = _request_digest(document)
        scope_name = f"domain-event:{run_id}:{event_type}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            timestamp = utc_now()
            new_revision = expected_revision + 1
            event_payload = {
                "record": dict(payload),
                "projection": {"kind": "immutable_record"},
            }
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type=event_type,
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "event_type": event_type,
                },
            )
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def create_entity(
        self,
        *,
        run_id: str,
        expected_revision: int,
        machine: str,
        entity_id: str,
        initial_state: str,
        idempotency_key: str,
        actor: str = "core",
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed = {"phase": PHASE_STATES, "task": TASK_STATES, "attempt": ATTEMPT_STATES}
        required_initial = {"phase": "PLANNED", "task": "PLANNED", "attempt": "CREATED"}
        if machine not in allowed or initial_state not in allowed[machine]:
            raise ContractError("invalid entity machine or initial state")
        if initial_state != required_initial[machine]:
            raise ContractError(
                f"{machine} entities must begin in {required_initial[machine]}"
            )
        document = {
            "run_id": run_id,
            "expected_revision": expected_revision,
            "machine": machine,
            "entity_id": entity_id,
            "initial_state": initial_state,
            "payload": dict(payload or {}),
        }
        digest = _request_digest(document)
        scope = f"entity:create:{machine}:{entity_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            self._require_active_run(run, action=f"create {machine}")
            if connection.execute(
                "SELECT 1 FROM entity_states WHERE machine = ? AND entity_id = ?",
                (machine, entity_id),
            ).fetchone():
                raise TransitionError(f"entity already exists: {machine}/{entity_id}")
            timestamp = utc_now()
            new_run_revision = expected_revision + 1
            projection = {
                "kind": "entity_create",
                "machine": machine,
                "entity_id": entity_id,
                "run_id": run_id,
                "revision": 0,
                "state": initial_state,
                "resume_state": None,
                "payload": dict(payload or {}),
                "updated_at": timestamp,
            }
            event_payload = {"request": document, "projection": projection}
            result = self.store._record_event(
                connection,
                scope=scope,
                run_id=run_id,
                run_revision=new_run_revision,
                event_type="ENTITY_CREATED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={
                    "run_id": run_id,
                    "run_revision": new_run_revision,
                    "machine": machine,
                    "entity_id": entity_id,
                    "revision": 0,
                    "state": initial_state,
                },
            )
            self.store._apply_projection(connection, projection)
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def _validate_fencing_token(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        resource_id: str,
        fencing_token: int,
        owner: str | None = None,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM leases WHERE resource_id = ?", (resource_id,)
        ).fetchone()
        if row is None or row["run_id"] != run_id or row["fencing_token"] != fencing_token:
            raise TransitionError("stale fencing token")
        if owner is not None and row["owner"] != owner:
            raise TransitionError("lease owner mismatch")
        if parse_timestamp(row["expires_at"], field="lease expires_at") <= datetime.now(UTC):
            raise TransitionError("lease is expired")

    def _require_gate_decisions(
        self,
        connection: sqlite3.Connection,
        *,
        rule: TransitionRule,
        gate_ids: tuple[str, ...],
        run: sqlite3.Row,
        machine: str,
        entity_id: str | None,
        current: sqlite3.Row,
        authorization_id: str | None,
    ) -> None:
        decisions: dict[str, Mapping[str, Any]] = {}
        for gate_id in gate_ids:
            row = connection.execute(
                "SELECT decision_json FROM gate_decisions WHERE gate_id = ? AND run_id = ?",
                (gate_id, run["run_id"]),
            ).fetchone()
            if row is None:
                raise TransitionError(f"unknown gate decision: {gate_id}")
            decision = json.loads(row["decision_json"])
            validate_gate_decision(decision)
            subjects = set(decision["subject_ids"])
            if run["run_id"] not in subjects:
                raise TransitionError(f"gate is not bound to the target run: {gate_id}")
            if machine != "run" and (
                entity_id is None or entity_id not in subjects
            ):
                raise TransitionError(
                    f"gate is not bound to the target {machine}: {gate_id}"
                )
            if decision["spec_hash"] != run["spec_hash"] or decision["config_hash"] != run["config_hash"]:
                raise TransitionError(f"gate binding is stale: {gate_id}")
            if decision["result"] not in {"passed", "not_applicable"}:
                raise TransitionError(f"gate did not pass: {gate_id}")
            if (
                decision["result"] == "not_applicable"
                and "NOT_APPLICABLE" not in rule.event
            ):
                raise TransitionError(
                    f"not-applicable gate cannot authorize {rule.event}: {gate_id}"
                )
            bound_authorization = decision.get("authorization_id")
            if bound_authorization is not None and bound_authorization != authorization_id:
                raise AuthorizationError(
                    f"gate authorization does not match transition: {gate_id}"
                )
            self._require_persisted_gate_evidence(
                connection,
                decision=decision,
                run=run,
                gate_id=gate_id,
            )
            if decision["gate_type"] in decisions:
                raise TransitionError(f"duplicate gate type supplied: {decision['gate_type']}")
            if decision["gate_type"] == "TASK_GATE":
                current_payload = json.loads(current["payload_json"])
                candidate_commit = current_payload.get("candidate_commit")
                if not isinstance(candidate_commit, str) or not candidate_commit:
                    raise TransitionError(
                        "TASK_GATE target lacks a persisted candidate_commit binding"
                    )
                if decision.get("candidate_commit") != candidate_commit:
                    raise TransitionError(
                        f"TASK_GATE candidate binding is stale: {gate_id}"
                    )
            if decision["gate_type"] == "COMPLETION_GATE":
                self._require_canonical_completion_acceptance(run, decision)
            decisions[decision["gate_type"]] = decision
        missing = [gate for gate in rule.required_gates if gate not in decisions]
        if missing:
            raise TransitionError(f"transition missing required gates: {', '.join(missing)}")

    def _require_persisted_gate_evidence(
        self,
        connection: sqlite3.Connection,
        *,
        decision: Mapping[str, Any],
        run: sqlite3.Row,
        gate_id: str,
    ) -> None:
        """Revalidate every immutable receipt and blob before Gate consumption."""

        resolved: dict[str, Mapping[str, Any]] = {}
        for raw_evidence_id in decision["evidence_ids"]:
            evidence_id = str(raw_evidence_id)
            evidence_row = connection.execute(
                "SELECT receipt_json FROM evidence_receipts "
                "WHERE evidence_id = ? AND run_id = ?",
                (evidence_id, run["run_id"]),
            ).fetchone()
            if evidence_row is None:
                raise TransitionError(f"gate evidence is missing: {evidence_id}")
            try:
                receipt = json.loads(evidence_row["receipt_json"])
                if (
                    receipt.get("run_id") != run["run_id"]
                    or receipt.get("spec_hash") != run["spec_hash"]
                    or receipt.get("config_hash") != run["config_hash"]
                ):
                    raise TransitionError(
                        f"gate evidence binding is stale: {evidence_id}"
                    )
                self.evidence_store.validate(receipt)
            except TransitionError:
                raise
            except Exception as exc:
                raise TransitionError(
                    f"gate evidence is invalid: {evidence_id}"
                ) from exc
            resolved[evidence_id] = receipt
        try:
            validate_gate_evidence_bindings(
                decision,
                resolved.get,
                lambda receipt: self.evidence_store.validate(receipt),
            )
        except Exception as exc:
            raise TransitionError(
                f"gate evidence bindings are invalid: {gate_id}"
            ) from exc

    def _active_authorization(
        self,
        connection: sqlite3.Connection,
        authorization_id: str,
    ) -> Mapping[str, Any]:
        row = connection.execute(
            "SELECT record_json FROM authorization_records WHERE authorization_id = ?",
            (authorization_id,),
        ).fetchone()
        if row is None:
            raise AuthorizationError(f"unknown authorization: {authorization_id}")
        revoked = connection.execute(
            "SELECT 1 FROM authorization_records WHERE record_type = 'revocation' "
            "AND target_authorization_id = ? LIMIT 1",
            (authorization_id,),
        ).fetchone()
        if revoked:
            raise AuthorizationError(f"authorization is revoked: {authorization_id}")
        record = json.loads(row["record_json"])
        validate_authorization_record(record)
        return record

    @staticmethod
    def _consume_one_time_authorization(
        connection: sqlite3.Connection,
        *,
        authorization_id: str,
        authorization: Mapping[str, Any],
        use_id: str,
    ) -> None:
        if not bool(
            authorization.get(
                "one_time", authorization.get("record_type") == "approval"
            )
        ):
            return
        if connection.execute(
            "SELECT 1 FROM authorization_uses WHERE authorization_id = ?",
            (authorization_id,),
        ).fetchone():
            raise AuthorizationError("one-time authorization was already consumed")
        connection.execute(
            "INSERT INTO authorization_uses(authorization_id, operation_id, used_at) "
            "VALUES (?, ?, ?)",
            (authorization_id, use_id, utc_now()),
        )

    def _require_mutation_stage_gate(
        self,
        connection: sqlite3.Connection,
        *,
        run: sqlite3.Row,
        action_id: str,
        operation_kind: str,
        gate_id: str | None,
        authorization_id: str | None,
        operation_scope: Mapping[str, Any],
    ) -> None:
        if operation_kind not in MUTATING_OPERATION_KINDS:
            if action_id in _MUTATION_ACTION_GATES:
                raise AuthorizationError(
                    f"sensitive action {action_id} must be an external mutation"
                )
            return
        expected = _MUTATION_ACTION_GATES.get(action_id)
        if expected is None:
            raise AuthorizationError(
                f"unsupported external mutation action: {action_id}"
            )
        expected_state, expected_gate_type = expected
        if run["state"] != expected_state:
            raise TransitionError(
                f"{action_id} requires run state {expected_state}, current {run['state']}"
            )
        if not isinstance(gate_id, str) or not gate_id:
            raise TransitionError(f"{action_id} requires its exact pre-action gate")
        row = connection.execute(
            "SELECT decision_json FROM gate_decisions WHERE gate_id = ? AND run_id = ?",
            (gate_id, run["run_id"]),
        ).fetchone()
        if row is None:
            raise TransitionError(f"unknown mutation gate: {gate_id}")
        decision = json.loads(row["decision_json"])
        validate_gate_decision(decision)
        if (
            decision["gate_type"] != expected_gate_type
            or decision["result"] != "passed"
            or decision["spec_hash"] != run["spec_hash"]
            or decision["config_hash"] != run["config_hash"]
        ):
            raise TransitionError(f"mutation gate is stale or has the wrong type: {gate_id}")
        if decision.get("authorization_id") != authorization_id:
            raise AuthorizationError("mutation gate authorization does not match Operation")
        self._require_persisted_gate_evidence(
            connection,
            decision=decision,
            run=run,
            gate_id=str(gate_id),
        )
        transition_row = connection.execute(
            "SELECT payload_json FROM events WHERE run_id = ? "
            "AND event_type = 'STATE_TRANSITION' ORDER BY sequence DESC",
            (run["run_id"],),
        ).fetchall()
        entered_with_gate = False
        for event in transition_row:
            payload = json.loads(event["payload_json"])
            projection = payload.get("projection", {})
            if (
                projection.get("machine") == "run"
                and projection.get("state") == run["state"]
            ):
                supplied = (
                    payload.get("request", {})
                    .get("proposal", {})
                    .get("gate_ids", [])
                )
                entered_with_gate = gate_id in supplied
                break
        if not entered_with_gate:
            raise TransitionError(
                "mutation gate was not the gate used to enter the current stage"
            )
        bindings = _MUTATION_ACTION_SCOPE_BINDINGS[action_id]
        missing = [
            scope_field
            for scope_field, _decision_field in bindings
            if not isinstance(operation_scope.get(scope_field), str)
            or not operation_scope[scope_field]
        ]
        if missing:
            raise TransitionError(
                f"{action_id} Operation scope is missing required fields: "
                + ", ".join(missing)
            )
        for scope_field, decision_field in bindings:
            if decision_field is None:
                continue
            supplied = operation_scope[scope_field]
            bound = decision.get(decision_field)
            if supplied != bound:
                raise TransitionError(
                    f"Operation {scope_field} does not match mutation gate"
                )
        if action_id in {"release", "publish"}:
            source_kind = operation_scope.get("release_source_kind")
            reconciliation_gate = operation_scope.get(
                "hotfix_reconciliation_gate_id"
            )
            if source_kind == "hotfix_stable":
                if (
                    not isinstance(reconciliation_gate, str)
                    or not reconciliation_gate
                    or reconciliation_gate
                    != decision.get("hotfix_reconciliation_gate_id")
                ):
                    raise TransitionError(
                        "hotfix release Operation lacks its exact reconciliation result gate"
                    )
            elif reconciliation_gate is not None:
                raise TransitionError(
                    "normal release Operation cannot cite hotfix reconciliation"
                )

    @staticmethod
    def _canonical_mandatory_acceptance_ids(run: sqlite3.Row) -> tuple[str, ...]:
        try:
            payload = json.loads(run["payload_json"])
            traceability = payload["traceability"]
            if not isinstance(traceability, Mapping):
                raise ContractError("traceability must be an object")
            report = validate_traceability(traceability)
        except (KeyError, TypeError, ValueError, ContractError) as exc:
            raise TransitionError(
                "COMPLETION_GATE requires valid canonical persisted traceability"
            ) from exc
        return report.mandatory_acceptance_ids

    @staticmethod
    def _canonical_delivery_contract(
        run: sqlite3.Row,
    ) -> tuple[str, str, tuple[str, ...]]:
        try:
            payload = json.loads(run["payload_json"])
            traceability = payload["traceability"]
            if not isinstance(traceability, Mapping):
                raise ContractError("traceability must be an object")
            validate_traceability(traceability)
            delivery = traceability["required_delivery_stages"]
            if not isinstance(delivery, Mapping):
                raise ContractError("required_delivery_stages must be an object")
            release = delivery["release"]
            deploy = delivery["deploy"]
            environments = delivery["environments"]
            if release not in {"required", "not_applicable"}:
                raise ContractError("release decision is invalid")
            if deploy not in {"required", "not_applicable"}:
                raise ContractError("deploy decision is invalid")
            if (
                not isinstance(environments, list)
                or not all(isinstance(item, str) and item for item in environments)
                or len(environments) != len(set(environments))
            ):
                raise ContractError("delivery environments are invalid")
        except (KeyError, TypeError, ValueError, ContractError) as exc:
            raise TransitionError(
                "delivery transition requires canonical persisted traceability"
            ) from exc
        return str(release), str(deploy), tuple(environments)

    @classmethod
    def _require_canonical_delivery_transition(
        cls,
        run: sqlite3.Row,
        *,
        event: str,
        proposal_payload: Mapping[str, Any],
        projected_payload: Mapping[str, Any],
    ) -> None:
        delivery_events = {
            "START_RELEASE",
            "SKIP_RELEASE_NOT_APPLICABLE",
            "RELEASE_OBSERVED",
            "PREPARE_DEPLOYMENT",
            "START_DEPLOYMENT",
            "SKIP_DEPLOY_NOT_APPLICABLE",
            "DEPLOYMENT_OBSERVED",
            "CONTINUE_DEPLOYMENT",
            "COMPLETE_RUN",
            "DEPLOYMENT_REQUIRES_ROLLBACK",
            "START_ROLLBACK",
            "ROLLBACK_OBSERVED",
            "ROLLBACK_VERIFIED",
        }
        if event not in delivery_events:
            return
        release, deploy, environments = cls._canonical_delivery_contract(run)
        if event in {"START_RELEASE", "RELEASE_OBSERVED"} and release != "required":
            raise TransitionError("persisted traceability does not require release")
        if event == "SKIP_RELEASE_NOT_APPLICABLE" and release != "not_applicable":
            raise TransitionError("persisted traceability does not mark release not_applicable")
        if event in {
            "START_DEPLOYMENT",
            "DEPLOYMENT_OBSERVED",
            "CONTINUE_DEPLOYMENT",
            "DEPLOYMENT_REQUIRES_ROLLBACK",
            "START_ROLLBACK",
            "ROLLBACK_OBSERVED",
            "ROLLBACK_VERIFIED",
        } and deploy != "required":
            raise TransitionError("persisted traceability does not require deployment")
        if event == "SKIP_DEPLOY_NOT_APPLICABLE":
            if deploy != "not_applicable" or environments:
                raise TransitionError(
                    "persisted traceability does not explicitly skip deployment"
                )
            return
        if deploy != "required" or event in {
            "START_RELEASE",
            "SKIP_RELEASE_NOT_APPLICABLE",
            "RELEASE_OBSERVED",
            "PREPARE_DEPLOYMENT",
        }:
            return
        completed = projected_payload.get("runtime_delivery_completed", [])
        if (
            not isinstance(completed, list)
            or not all(isinstance(item, Mapping) for item in completed)
        ):
            raise TransitionError("persisted delivery completion records are malformed")
        completed_keys = tuple(str(item.get("logical_key", "")) for item in completed)
        if completed_keys != environments[: len(completed_keys)]:
            raise TransitionError("delivery environments were not completed in canonical order")
        if event == "START_DEPLOYMENT":
            index = proposal_payload.get("environment_index")
            key = proposal_payload.get("environment_key")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index != len(completed_keys)
                or index >= len(environments)
                or key != environments[index]
            ):
                raise TransitionError(
                    "deployment does not target the next canonical environment"
                )
        elif event == "CONTINUE_DEPLOYMENT":
            next_index = proposal_payload.get("next_environment_index")
            if (
                isinstance(next_index, bool)
                or not isinstance(next_index, int)
                or next_index != len(completed_keys)
                or next_index >= len(environments)
            ):
                raise TransitionError(
                    "deployment continuation does not target the next environment"
                )
        elif event == "COMPLETE_RUN" and completed_keys != environments:
            raise TransitionError(
                "COMPLETED requires every canonical delivery environment in order"
            )

    @classmethod
    def _require_canonical_completion_acceptance(
        cls,
        run: sqlite3.Row,
        decision: Mapping[str, Any],
    ) -> None:
        canonical = cls._canonical_mandatory_acceptance_ids(run)
        supplied = tuple(decision.get("mandatory_acceptance_ids", ()))
        if supplied != canonical:
            raise TransitionError(
                "COMPLETION_GATE mandatory_acceptance_ids do not match canonical "
                "persisted traceability"
            )

    def _require_transition_authorization(
        self,
        connection: sqlite3.Connection,
        *,
        rule: TransitionRule,
        authorization_id: str | None,
        run: sqlite3.Row,
        event: str,
        payload: Mapping[str, Any],
    ) -> None:
        requirement = rule.required_authorization
        if requirement is None:
            return
        if not authorization_id:
            raise AuthorizationError(
                f"transition {event} requires trusted authorization: {requirement}"
            )
        record = self._active_authorization(connection, authorization_id)
        if requirement == "spec_confirmation":
            if record.get("record_type") != "spec_confirmation":
                raise AuthorizationError("SPEC confirmation record has the wrong type")
            if record.get("spec_hash") != run["spec_hash"]:
                raise AuthorizationError("SPEC confirmation hash mismatch")
            return
        if record.get("record_type") not in {"grant", "approval"}:
            raise AuthorizationError("protected transition needs a grant or approval")
        if requirement in _EXTERNAL_STAGE_AUTHORIZATIONS:
            expected_record_type = "grant" if run["mode"] == "auto" else "approval"
            if record.get("record_type") != expected_record_type:
                raise AuthorizationError(
                    f"{run['mode']} mutation requires a trusted "
                    f"{expected_record_type} record"
                )
        allowed_actions = record.get("allowed_actions", [])
        action = requirement if requirement in allowed_actions else event
        if not authorization_scope_allows(
            record,
            run_id=run["run_id"],
            spec_hash=run["spec_hash"],
            config_hash=run["config_hash"],
            action=action,
            environment=payload.get("environment_id"),
            protected_ref=payload.get("protected_ref"),
        ):
            raise AuthorizationError("authorization scope does not cover the transition")
        if requirement not in _EXTERNAL_STAGE_AUTHORIZATIONS:
            self._consume_one_time_authorization(
                connection,
                authorization_id=authorization_id,
                authorization=record,
                use_id=(
                    f"TRANSITION:{run['run_id']}:{event}:{int(run['revision'])}"
                ),
            )

    def transition(
        self,
        proposal: TransitionProposal,
        *,
        machine: str = "run",
        entity_id: str | None = None,
        outbox: Iterable[NotificationIntent | Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        document = {
            "proposal": {
                "run_id": proposal.run_id,
                "expected_revision": proposal.expected_revision,
                "event": proposal.event,
                "actor": proposal.actor,
                "idempotency_key": proposal.idempotency_key,
                "payload": proposal.payload,
                "gate_ids": list(proposal.gate_ids),
                "authorization_id": proposal.authorization_id,
                "fencing_token": proposal.fencing_token,
            },
            "machine": machine,
            "entity_id": entity_id,
        }
        digest = _request_digest(document)
        scope = f"transition:{proposal.run_id}:{machine}:{entity_id or proposal.run_id}"
        outbox_documents, normalized_outbox = _intent_documents(outbox)
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope,
                idempotency_key=proposal.idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, proposal.run_id)
            self._require_revision(run, proposal.expected_revision)
            if machine != "run":
                self._require_active_run(
                    run, action=f"transition {machine}/{entity_id or ''}"
                )
            if machine == "run" and proposal.event in _SAFE_POINT_EVENTS:
                active = self._active_external_operation_ids(connection, proposal.run_id)
                if active:
                    raise TransitionError(
                        f"transition {proposal.event} requires reconciled external operations: "
                        + ", ".join(active)
                    )
            if machine == "run":
                current = run
            else:
                if entity_id is None:
                    raise ContractError("entity_id is required for non-run transitions")
                current = connection.execute(
                    "SELECT * FROM entity_states WHERE machine = ? AND entity_id = ? AND run_id = ?",
                    (machine, entity_id, proposal.run_id),
                ).fetchone()
                if current is None:
                    raise TransitionError(f"unknown {machine}: {entity_id}")
            if proposal.fencing_token is not None:
                resource_id = proposal.payload.get("lease_resource_id")
                if not isinstance(resource_id, str) or not resource_id:
                    raise TransitionError("fenced transition must name lease_resource_id")
                self._validate_fencing_token(
                    connection,
                    run_id=proposal.run_id,
                    resource_id=resource_id,
                    fencing_token=proposal.fencing_token,
                    owner=(
                        str(proposal.payload["lease_owner"])
                        if proposal.payload.get("lease_owner")
                        else None
                    ),
                )
            current_payload = json.loads(current["payload_json"])
            context: dict[str, Any] = {
                **json.loads(run["payload_json"]),
                **current_payload,
                **proposal.payload,
                "mode": run["mode"],
                "run_kind": run["run_kind"],
                "recorded_resume_state": current["resume_state"],
            }
            rule, target = self.transitions.validate(
                machine=machine,
                from_state=current["state"],
                event=proposal.event,
                context=context,
            )
            self._require_gate_decisions(
                connection,
                rule=rule,
                gate_ids=proposal.gate_ids,
                run=run,
                machine=machine,
                entity_id=entity_id,
                current=current,
                authorization_id=proposal.authorization_id,
            )
            self._require_transition_authorization(
                connection,
                rule=rule,
                authorization_id=proposal.authorization_id,
                run=run,
                event=proposal.event,
                payload=proposal.payload,
            )
            timestamp = utc_now()
            new_run_revision = proposal.expected_revision + 1
            state_patch = proposal.payload.get("state_patch", {})
            if not isinstance(state_patch, Mapping):
                raise ContractError("state_patch must be an object")
            protected_input_fields = sorted(
                _RUN_INPUT_PAYLOAD_FIELDS.intersection(state_patch)
            )
            if machine == "run" and protected_input_fields:
                raise ContractError(
                    "run input fields may only change through amend_run_inputs: "
                    + ", ".join(protected_input_fields)
                )
            projected_payload = {**current_payload, **dict(state_patch)}
            if machine == "run":
                self._require_canonical_delivery_transition(
                    run,
                    event=proposal.event,
                    proposal_payload=proposal.payload,
                    projected_payload=projected_payload,
                )
            if target in {"PAUSED", "ATTENTION_REQUIRED"}:
                resume_state = current["state"]
            elif current["state"] in {"PAUSED", "ATTENTION_REQUIRED"}:
                resume_state = None
            else:
                resume_state = current["resume_state"]
            projection = {
                "kind": "transition",
                "machine": machine,
                "entity_id": entity_id,
                "run_id": proposal.run_id,
                "previous_revision": int(current["revision"]),
                "revision": (
                    new_run_revision if machine == "run" else int(current["revision"]) + 1
                ),
                "previous_run_revision": proposal.expected_revision,
                "run_revision": new_run_revision,
                "state": target,
                "resume_state": resume_state,
                "payload": projected_payload,
                "updated_at": timestamp,
            }
            if machine == "run" and target in _RUN_WRITE_FENCED_STATES:
                projection["fenced_leases"] = [
                    {
                        "resource_id": str(row["resource_id"]),
                        "owner": str(row["owner"]),
                        "fencing_token": int(row["fencing_token"]),
                    }
                    for row in connection.execute(
                        "SELECT resource_id, owner, fencing_token FROM leases "
                        "WHERE run_id = ? ORDER BY resource_id",
                        (proposal.run_id,),
                    ).fetchall()
                ]
            event_payload = {
                "request": document,
                "transition_table_version": self.transitions.version,
                "rule": {
                    "from_state": current["state"],
                    "event": proposal.event,
                    "guards": list(rule.guard),
                    "required_gates": list(rule.required_gates),
                    "required_authorization": rule.required_authorization,
                    "to_state": target,
                },
                "projection": projection,
                "outbox": outbox_documents,
            }
            result = self.store._record_event(
                connection,
                scope=scope,
                run_id=proposal.run_id,
                run_revision=new_run_revision,
                event_type="STATE_TRANSITION",
                actor=proposal.actor,
                idempotency_key=proposal.idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={
                    "run_id": proposal.run_id,
                    "run_revision": new_run_revision,
                    "machine": machine,
                    "entity_id": entity_id,
                    "from_state": current["state"],
                    "state": target,
                },
                outbox=normalized_outbox,
            )
            self.store._apply_projection(connection, projection)
            if machine != "run":
                self._bump_run(
                    self.store,
                    connection,
                    run_id=proposal.run_id,
                    expected_revision=proposal.expected_revision,
                    timestamp=str(result["event_created_at"]),
                )
            return result

    def create_authorization_request(
        self,
        *,
        run_id: str,
        expected_revision: int,
        request_id: str,
        request_type: str,
        scope: Mapping[str, Any],
        expires_at: str,
        idempotency_key: str,
        nonce: str | None = None,
        actor: str = "control-plane-requester",
    ) -> dict[str, Any]:
        expiry = parse_timestamp(expires_at, field="expires_at")
        if expiry <= datetime.now(UTC):
            raise AuthorizationError("authorization request is already expired")
        request_nonce = nonce or sha256_bytes(
            f"{run_id}\0{request_id}\0{idempotency_key}".encode("utf-8")
        )[:32]
        with self.store._write_transaction() as connection:
            run = self._run_row(connection, run_id)
            document = {
                "schema_version": "nm-v6/authorization-request-v1",
                "request_id": request_id,
                "request_type": request_type,
                "run_id": run_id,
                "spec_hash": run["spec_hash"],
                "config_hash": run["config_hash"],
                "scope": dict(scope),
                "expected_revision": expected_revision + 1,
                "expires_at": expires_at,
                "nonce": request_nonce,
            }
            digest = authorization_request_digest(document)
            operation_scope = f"authorization:request:{run_id}"
            replay = self.store._idempotency_result(
                connection,
                scope=operation_scope,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            self._require_revision(run, expected_revision)
            timestamp = utc_now()
            new_revision = expected_revision + 1
            try:
                connection.execute(
                    "INSERT INTO authorization_requests(request_id, run_id, request_type, nonce, "
                    "request_digest, expected_revision, scope_json, expires_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        request_id,
                        run_id,
                        request_type,
                        request_nonce,
                        digest,
                        new_revision,
                        canonical_json(dict(scope)).decode("utf-8"),
                        expires_at,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthorizationError("authorization request nonce or ID was replayed") from exc
            event_payload = {
                "request": document,
                "projection": {"kind": "authorization"},
            }
            result = self.store._record_event(
                connection,
                scope=operation_scope,
                run_id=run_id,
                run_revision=new_revision,
                event_type="AUTHORIZATION_REQUESTED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "request": {**document, "request_digest": digest},
                },
            )
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    @staticmethod
    def _request_matches_record(
        request: sqlite3.Row,
        record: Mapping[str, Any],
        *,
        current_revision: int,
    ) -> None:
        if parse_timestamp(request["expires_at"], field="request expires_at") <= datetime.now(UTC):
            raise AuthorizationError("authorization challenge request is expired")
        if request["nonce"] != record.get("nonce"):
            raise AuthorizationError("authorization nonce does not match its request")
        if request["run_id"] and request["run_id"] != record.get("run_id", request["run_id"]):
            raise AuthorizationError("authorization run scope was expanded")
        if int(request["expected_revision"]) != current_revision:
            raise AuthorizationError("authorization request revision is stale")
        scope = json.loads(request["scope_json"])
        for key, value in scope.items():
            if record.get(key) != value:
                raise AuthorizationError(f"authorization scope mismatch for {key}")
        if record.get("record_type") in {"grant", "approval"}:
            if record.get("request_digest") != request["request_digest"]:
                raise AuthorizationError("authorization request digest mismatch")
            if record.get("grant_revision") != current_revision:
                raise AuthorizationError("authorization grant revision is stale")

    def import_authorization(
        self,
        record: Mapping[str, Any],
        verifier: SignatureVerifier,
        *,
        expected_revision: int | None = None,
        idempotency_key: str | None = None,
        actor: str = "trusted-control-plane",
    ) -> dict[str, Any]:
        verified = verifier.verify(record)
        idempotency = idempotency_key or f"import:{verified.authorization_id}"
        request_material = {
            "authorization_id": verified.authorization_id,
            "record_digest": verified.record_digest,
        }
        digest = _request_digest(request_material)
        scope_name = f"authorization:import:{verified.authorization_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency,
                request_digest=digest,
                replay_allowed=False,
            )
            if replay is not None:
                return replay

            request: sqlite3.Row | None = None
            if verified.request_digest:
                request = connection.execute(
                    "SELECT * FROM authorization_requests WHERE request_digest = ?",
                    (verified.request_digest,),
                ).fetchone()
            elif verified.record_type not in {"revocation"}:
                request = connection.execute(
                    "SELECT * FROM authorization_requests WHERE nonce = ?",
                    (verified.nonce,),
                ).fetchone()
            run_id = verified.run_id or (request["run_id"] if request else None)
            run: sqlite3.Row | None = None
            current_revision: int | None = None
            if run_id is not None:
                run = self._run_row(connection, run_id)
                current_revision = int(run["revision"])
                if verified.record_type != "revocation":
                    self._require_nonterminal_run(
                        run, action=f"import {verified.record_type}"
                    )
                if expected_revision is not None and expected_revision != current_revision:
                    raise TransitionError(
                        f"stale authorization import revision: expected {expected_revision}, current {current_revision}"
                    )

            if verified.record_type == "revocation":
                target = connection.execute(
                    "SELECT run_id FROM authorization_records WHERE authorization_id = ?",
                    (verified.target_authorization_id,),
                ).fetchone()
                if target is None:
                    raise AuthorizationError("revocation target does not exist")
                if target["run_id"] != run_id:
                    raise AuthorizationError("revocation cannot cross run scope")
            else:
                if request is None:
                    raise AuthorizationError("authorization has no matching challenge request")
                if current_revision is None:
                    raise AuthorizationError("authorization request has no run revision")
                self._request_matches_record(
                    request, verified.record, current_revision=current_revision
                )
                expected_type = request["request_type"]
                compatible = {
                    "spec_confirmation": {"spec_confirmation"},
                    "implementation_authorization": {"implementation_authorization"},
                    "grant": {"grant", "approval"},
                    "approval": {"approval"},
                }.get(expected_type, {expected_type})
                if verified.record_type not in compatible:
                    raise AuthorizationError("authorization record type mismatches its request")

            timestamp = utc_now()
            new_revision = current_revision + 1 if current_revision is not None else None
            try:
                connection.execute(
                    "INSERT INTO authorization_records(authorization_id, record_type, run_id, "
                    "request_digest, nonce, authenticator_id, record_digest, record_json, issued_at, "
                    "expires_at, target_authorization_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        verified.authorization_id,
                        verified.record_type,
                        run_id,
                        verified.request_digest,
                        verified.nonce,
                        verified.authenticator_id,
                        verified.record_digest,
                        canonical_json(verified.record).decode("utf-8"),
                        verified.issued_at,
                        verified.expires_at,
                        verified.target_authorization_id,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthorizationError("authorization ID, nonce, or record was replayed") from exc
            event_payload = {
                "authorization_id": verified.authorization_id,
                "record_type": verified.record_type,
                "record_digest": verified.record_digest,
                "target_authorization_id": verified.target_authorization_id,
                "projection": {"kind": "authorization"},
            }
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type=(
                    "AUTHORIZATION_REVOKED"
                    if verified.record_type == "revocation"
                    else "AUTHORIZATION_IMPORTED"
                ),
                actor=actor,
                idempotency_key=idempotency,
                request_digest=digest,
                payload=event_payload,
                result={
                    "authorization_id": verified.authorization_id,
                    "record_type": verified.record_type,
                    "run_id": run_id,
                    "revision": new_revision,
                },
            )
            if run_id is not None and current_revision is not None:
                self._bump_run(
                    self.store,
                    connection,
                    run_id=run_id,
                    expected_revision=current_revision,
                    timestamp=str(result["event_created_at"]),
                )
            return result

    def start_operation(
        self,
        *,
        run_id: str,
        expected_revision: int,
        operation_id: str,
        action_id: str,
        operation_kind: str,
        idempotency_key: str,
        authorization_id: str | None = None,
        gate_id: str | None = None,
        scope: Mapping[str, Any] | None = None,
        fencing_token: int | None = None,
        actor: str = "controller",
    ) -> dict[str, Any]:
        if not isinstance(operation_id, str) or not IDENTIFIER_PATTERNS[
            "operation"
        ].fullmatch(operation_id):
            raise ContractError("operation_id has invalid V6 identifier format")
        if not isinstance(action_id, str) or not action_id:
            raise ContractError("action_id must be a nonempty string")
        operation_scope = dict(scope or {})
        if gate_id is not None:
            if operation_scope.get("gate_id") not in {None, gate_id}:
                raise ContractError("Operation scope gate_id conflicts with gate_id")
            operation_scope["gate_id"] = gate_id
        document = {
            "run_id": run_id,
            "expected_revision": expected_revision,
            "operation_id": operation_id,
            "action_id": action_id,
            "operation_kind": operation_kind,
            "operation_idempotency_key": idempotency_key,
            "authorization_id": authorization_id,
            "gate_id": gate_id,
            "scope": operation_scope,
            "fencing_token": fencing_token,
        }
        digest = _request_digest(document)
        event_scope = f"operation:start:{run_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=event_scope,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            self._require_nonterminal_run(run, action=f"start operation {action_id}")
            if run["state"] in _FENCED_RUN_STATES:
                raise TransitionError(
                    f"new operations are fenced while run is {run['state']}"
                )
            if connection.execute(
                "SELECT 1 FROM external_operations WHERE operation_id = ? OR idempotency_key = ?",
                (operation_id, idempotency_key),
            ).fetchone():
                raise TransitionError("duplicate external operation identity")
            self._require_mutation_stage_gate(
                connection,
                run=run,
                action_id=action_id,
                operation_kind=operation_kind,
                gate_id=gate_id,
                authorization_id=authorization_id,
                operation_scope=operation_scope,
            )
            authorization: Mapping[str, Any] | None = None
            if operation_kind in MUTATING_OPERATION_KINDS and not authorization_id:
                raise AuthorizationError("external mutation requires authorization")
            if authorization_id:
                authorization = self._active_authorization(connection, authorization_id)
                if authorization.get("record_type") not in {"grant", "approval"}:
                    raise AuthorizationError("operation authorization must be a grant or approval")
                if operation_kind in MUTATING_OPERATION_KINDS:
                    expected_record_type = (
                        "grant" if run["mode"] == "auto" else "approval"
                    )
                    if authorization.get("record_type") != expected_record_type:
                        raise AuthorizationError(
                            f"{run['mode']} mutation requires a trusted "
                            f"{expected_record_type} record"
                        )
                if not authorization_scope_allows(
                    authorization,
                    run_id=run_id,
                    spec_hash=run["spec_hash"],
                    config_hash=run["config_hash"],
                    action=action_id,
                    environment=operation_scope.get("environment_id"),
                    protected_ref=operation_scope.get("protected_ref"),
                ):
                    raise AuthorizationError("authorization scope does not cover the operation")
                if bool(
                    authorization.get(
                        "one_time", authorization.get("record_type") == "approval"
                    )
                ):
                    self._consume_one_time_authorization(
                        connection,
                        authorization_id=authorization_id,
                        authorization=authorization,
                        use_id=operation_id,
                    )
                else:
                    connection.execute(
                        "INSERT INTO authorization_uses(authorization_id, operation_id, used_at) "
                        "VALUES (?, ?, ?)",
                        (authorization_id, operation_id, utc_now()),
                    )
            if fencing_token is not None:
                resource_id = operation_scope.get("lease_resource_id")
                if not isinstance(resource_id, str) or not resource_id:
                    raise TransitionError("fenced operation must name lease_resource_id")
                self._validate_fencing_token(
                    connection,
                    run_id=run_id,
                    resource_id=resource_id,
                    fencing_token=fencing_token,
                    owner=(
                        str(operation_scope["lease_owner"])
                        if operation_scope.get("lease_owner")
                        else None
                    ),
                )
            timestamp = utc_now()
            new_revision = expected_revision + 1
            projection = {
                "kind": "operation_start",
                "operation_id": operation_id,
                "run_id": run_id,
                "action_id": action_id,
                "operation_kind": operation_kind,
                "operation_idempotency_key": idempotency_key,
                "authorization_id": authorization_id,
                "grant_revision": (
                    authorization.get("grant_revision") if authorization else None
                ),
                "fencing_token": fencing_token,
                "scope": operation_scope,
                "gate_id": gate_id,
                "started_at": timestamp,
            }
            event_payload = {"request": document, "projection": projection}
            result = self.store._record_event(
                connection,
                scope=event_scope,
                run_id=run_id,
                run_revision=new_revision,
                event_type="EXTERNAL_OPERATION_STARTED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "operation_id": operation_id,
                    "status": "started",
                },
            )
            self.store._apply_projection(connection, projection)
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def restart_operation(
        self,
        *,
        run_id: str,
        expected_revision: int,
        operation_id: str,
        authorization_id: str | None,
        grant_revision: int | None,
        idempotency_key: str,
        fencing_token: int | None = None,
        actor: str = "recovery-controller",
    ) -> dict[str, Any]:
        """Re-arm one observed-not-started Operation under its original scope.

        The Operation ID remains the idempotency key.  Completed, ambiguous,
        failed, revoked, fenced, or differently authorized Operations cannot be
        invoked again.
        """

        if not isinstance(operation_id, str) or not IDENTIFIER_PATTERNS[
            "operation"
        ].fullmatch(operation_id):
            raise ContractError("operation_id has invalid V6 identifier format")
        document = {
            "run_id": run_id,
            "expected_revision": expected_revision,
            "operation_id": operation_id,
            "authorization_id": authorization_id,
            "grant_revision": grant_revision,
            "fencing_token": fencing_token,
        }
        digest = _request_digest(document)
        scope_name = f"operation:restart:{operation_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            self._require_nonterminal_run(run, action=f"restart operation {operation_id}")
            if run["state"] in _FENCED_RUN_STATES:
                raise TransitionError(
                    f"new operations are fenced while run is {run['state']}"
                )
            operation = connection.execute(
                "SELECT * FROM external_operations WHERE operation_id = ? AND run_id = ?",
                (operation_id, run_id),
            ).fetchone()
            if operation is None or operation["status"] != "not_started":
                raise TransitionError(
                    "only an independently observed not_started Operation may retry"
                )
            if operation["authorization_id"] != authorization_id:
                raise AuthorizationError("Operation retry authorization changed")
            if operation["grant_revision"] != grant_revision:
                raise AuthorizationError("Operation retry grant revision changed")
            operation_scope = json.loads(operation["scope_json"])
            self._require_mutation_stage_gate(
                connection,
                run=run,
                action_id=str(operation["action_id"]),
                operation_kind=str(operation["operation_kind"]),
                gate_id=operation_scope.get("gate_id"),
                authorization_id=authorization_id,
                operation_scope=operation_scope,
            )
            if authorization_id is not None:
                authorization = self._active_authorization(connection, authorization_id)
                if not authorization_scope_allows(
                    authorization,
                    run_id=run_id,
                    spec_hash=run["spec_hash"],
                    config_hash=run["config_hash"],
                    action=operation["action_id"],
                    environment=operation_scope.get("environment_id"),
                    protected_ref=operation_scope.get("protected_ref"),
                ):
                    raise AuthorizationError("authorization no longer covers Operation retry")
            recorded_token = operation["fencing_token"]
            if recorded_token != fencing_token:
                raise TransitionError("Operation retry fencing token changed")
            if recorded_token is not None:
                resource_id = operation_scope.get("lease_resource_id")
                if not isinstance(resource_id, str) or not resource_id:
                    raise TransitionError("fenced Operation retry lacks lease_resource_id")
                self._validate_fencing_token(
                    connection,
                    run_id=run_id,
                    resource_id=resource_id,
                    fencing_token=recorded_token,
                    owner=(
                        str(operation_scope["lease_owner"])
                        if operation_scope.get("lease_owner")
                        else None
                    ),
                )
            timestamp = utc_now()
            new_revision = expected_revision + 1
            projection = {
                "kind": "operation_restart",
                "operation_id": operation_id,
                "updated_at": timestamp,
            }
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="EXTERNAL_OPERATION_RESTARTED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload={"request": document, "projection": projection},
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "operation_id": operation_id,
                    "status": "started",
                },
            )
            self.store._apply_projection(connection, projection)
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def record_operation_observation(
        self,
        observation: OperationObservation,
        *,
        run_id: str,
        expected_revision: int,
        idempotency_key: str,
        fencing_token: int | None = None,
        actor: str = "recovery-controller",
    ) -> dict[str, Any]:
        status = "completed" if observation.status == "succeeded" else observation.status
        if status not in {
            "completed",
            "not_started",
            "partial",
            "failed",
            "unknown",
            "cancelled",
        }:
            raise ContractError(f"invalid operation observation status: {observation.status}")
        document = {
            "operation_id": observation.operation_id,
            "action_id": observation.action_id,
            "status": status,
            "effect_id": observation.effect_id,
            "result": observation.result,
            "fencing_token": fencing_token,
        }
        digest = _request_digest(document)
        scope_name = f"operation:observe:{observation.operation_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            operation = connection.execute(
                "SELECT * FROM external_operations WHERE operation_id = ? AND run_id = ?",
                (observation.operation_id, run_id),
            ).fetchone()
            if operation is None or operation["action_id"] != observation.action_id:
                raise TransitionError("operation observation identity mismatch")
            if operation["status"] not in {"started", "partial", "unknown"}:
                raise TransitionError("operation observation is stale")
            recorded_token = operation["fencing_token"]
            if recorded_token is not None and fencing_token != recorded_token:
                raise TransitionError("stale operation fencing token")
            if observation.effect_id:
                duplicate = connection.execute(
                    "SELECT operation_id FROM external_operations WHERE effect_id = ? "
                    "AND operation_id <> ? LIMIT 1",
                    (observation.effect_id, observation.operation_id),
                ).fetchone()
                if duplicate:
                    raise TransitionError("external effect is bound to another operation")
            timestamp = utc_now()
            new_revision = expected_revision + 1
            projection = {
                "kind": "operation_observation",
                "operation_id": observation.operation_id,
                "status": status,
                "effect_id": observation.effect_id,
                "result": observation.result,
                "updated_at": timestamp,
            }
            event_payload = {"observation": document, "projection": projection}
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="EXTERNAL_OPERATION_OBSERVED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "operation_id": observation.operation_id,
                    "status": status,
                },
            )
            self.store._apply_projection(connection, projection)
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def record_evidence(
        self,
        *,
        run_id: str,
        expected_revision: int,
        receipt: Mapping[str, Any],
        idempotency_key: str,
        actor: str = "gate-executor",
    ) -> dict[str, Any]:
        self.evidence_store.validate(receipt)
        if receipt.get("run_id") != run_id:
            raise ContractError("evidence run binding mismatch")
        document = dict(receipt)
        digest = _request_digest(document)
        scope_name = f"evidence:record:{run_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            if receipt["spec_hash"] != run["spec_hash"] or receipt["config_hash"] != run["config_hash"]:
                raise TransitionError("evidence Spec/config binding is stale")
            timestamp = utc_now()
            new_revision = expected_revision + 1
            checkpoint("evidence.before_receipt_insert")
            try:
                connection.execute(
                    "INSERT INTO evidence_receipts(evidence_id, run_id, evidence_type, receipt_digest, "
                    "receipt_json, stdout_digest, stderr_digest, result, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        receipt["evidence_id"],
                        run_id,
                        receipt["evidence_type"],
                        digest,
                        canonical_json(document).decode("utf-8"),
                        receipt["stdout_digest"],
                        receipt["stderr_digest"],
                        receipt["result"],
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise TransitionError("duplicate evidence receipt") from exc
            checkpoint("evidence.after_receipt_insert")
            event_payload = {
                "evidence_id": receipt["evidence_id"],
                "receipt_digest": digest,
                "projection": {"kind": "evidence"},
            }
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="EVIDENCE_RECORDED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "evidence_id": receipt["evidence_id"],
                    "receipt_digest": digest,
                },
            )
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def record_gate(
        self,
        *,
        run_id: str,
        expected_revision: int,
        decision: Mapping[str, Any],
        idempotency_key: str,
        actor: str = "gate-evaluator",
    ) -> dict[str, Any]:
        validate_gate_decision(decision)
        if decision.get("run_id") not in {None, run_id}:
            raise ContractError("gate run binding mismatch")
        digest = _request_digest(dict(decision))
        scope_name = f"gate:record:{run_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            if decision["run_revision"] != expected_revision:
                raise TransitionError("gate decision revision is stale")
            if decision["spec_hash"] != run["spec_hash"] or decision["config_hash"] != run["config_hash"]:
                raise TransitionError("gate Spec/config binding is stale")
            if run_id not in decision["subject_ids"]:
                raise TransitionError("gate decision is not bound to its persisted run")
            if decision["gate_type"] == "COMPLETION_GATE":
                self._require_canonical_completion_acceptance(run, decision)
            if decision.get("authorization_id"):
                authorization = self._active_authorization(
                    connection, str(decision["authorization_id"])
                )
                if authorization.get("run_id") not in {None, run_id}:
                    raise AuthorizationError("gate authorization run binding mismatch")
                if authorization.get("record_type") in {"grant", "approval"} and (
                    authorization.get("spec_hash") != run["spec_hash"]
                    or authorization.get("config_hash") != run["config_hash"]
                ):
                    raise AuthorizationError("gate authorization Spec/config binding mismatch")
            def resolve_gate_evidence(evidence_id: str) -> Mapping[str, Any] | None:
                row = connection.execute(
                    "SELECT receipt_json FROM evidence_receipts WHERE evidence_id = ? AND run_id = ?",
                    (evidence_id, run_id),
                ).fetchone()
                return json.loads(row["receipt_json"]) if row is not None else None

            for evidence_id in decision["evidence_ids"]:
                receipt = resolve_gate_evidence(str(evidence_id))
                if receipt is None:
                    raise TransitionError(
                        f"gate evidence does not exist: {evidence_id}"
                    )
                self.evidence_store.validate(receipt)
                if (
                    receipt["spec_hash"] != run["spec_hash"]
                    or receipt["config_hash"] != run["config_hash"]
                ):
                    raise TransitionError(
                        f"gate evidence binding is stale: {evidence_id}"
                    )
            validate_gate_evidence_bindings(
                decision,
                resolve_gate_evidence,
                lambda receipt: self.evidence_store.validate(receipt),
            )
            timestamp = utc_now()
            new_revision = expected_revision + 1
            try:
                connection.execute(
                    "INSERT INTO gate_decisions(gate_id, run_id, gate_type, gate_version, result, "
                    "run_revision, decision_digest, decision_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        decision["gate_id"],
                        run_id,
                        decision["gate_type"],
                        decision["gate_version"],
                        decision["result"],
                        decision["run_revision"],
                        decision["decision_digest"],
                        canonical_json(dict(decision)).decode("utf-8"),
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise TransitionError("duplicate gate decision") from exc
            event_payload = {
                "gate_id": decision["gate_id"],
                "gate_type": decision["gate_type"],
                "decision_digest": decision["decision_digest"],
                "projection": {"kind": "gate"},
            }
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="GATE_DECIDED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "gate_id": decision["gate_id"],
                    "result": decision["result"],
                },
            )
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def acquire_lease(
        self,
        *,
        run_id: str,
        expected_revision: int,
        resource_id: str,
        owner: str,
        lease_seconds: int,
        idempotency_key: str,
        attempt_id: str | None = None,
        write_set: Iterable[str] = (),
        actor: str = "scheduler",
    ) -> dict[str, Any]:
        if lease_seconds < 1 or not resource_id or not owner:
            raise ContractError("lease resource, owner, and positive duration are required")
        from .scheduler import TaskDefinition, write_sets_overlap

        normalized_write_set = TaskDefinition(
            resource_id, write_set=tuple(write_set)
        ).write_set
        document = {
            "run_id": run_id,
            "expected_revision": expected_revision,
            "resource_id": resource_id,
            "owner": owner,
            "lease_seconds": lease_seconds,
            "attempt_id": attempt_id,
            "write_set": list(normalized_write_set),
        }
        digest = _request_digest(document)
        scope_name = f"lease:acquire:{resource_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            self._require_active_run(run, action="acquire lease")
            now = datetime.now(UTC)
            for active in connection.execute(
                "SELECT resource_id, write_set_json FROM leases "
                "WHERE run_id = ? AND resource_id <> ? AND expires_at > ?",
                (
                    run_id,
                    resource_id,
                    now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                ),
            ).fetchall():
                active_write_set = tuple(json.loads(active["write_set_json"]))
                if write_sets_overlap(normalized_write_set, active_write_set):
                    raise TransitionError(
                        "declared write set conflicts with active lease: "
                        f"{active['resource_id']}"
                    )
            current = connection.execute(
                "SELECT * FROM leases WHERE resource_id = ?", (resource_id,)
            ).fetchone()
            if current is not None:
                expiry = parse_timestamp(current["expires_at"], field="lease expires_at")
                if expiry > now:
                    raise TransitionError(
                        f"lease is already owned by {current['owner']} until {current['expires_at']}"
                    )
            counter = connection.execute(
                "SELECT last_fencing_token FROM lease_fencing_counters "
                "WHERE resource_id = ?",
                (resource_id,),
            ).fetchone()
            fencing_token = int(counter["last_fencing_token"]) + 1 if counter else 1
            acquired_at = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
            expires_at = (now + timedelta(seconds=lease_seconds)).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
            new_revision = expected_revision + 1
            projection = {
                "kind": "lease_upsert",
                "resource_id": resource_id,
                "run_id": run_id,
                "owner": owner,
                "attempt_id": attempt_id,
                "fencing_token": fencing_token,
                "acquired_at": acquired_at,
                "heartbeat_at": acquired_at,
                "expires_at": expires_at,
                "write_set": list(normalized_write_set),
            }
            event_payload = {"request": document, "projection": projection}
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="LEASE_ACQUIRED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload=event_payload,
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "resource_id": resource_id,
                    "owner": owner,
                    "fencing_token": fencing_token,
                    "expires_at": expires_at,
                },
            )
            self.store._apply_projection(connection, projection)
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def heartbeat_lease(
        self,
        *,
        run_id: str,
        expected_revision: int,
        resource_id: str,
        owner: str,
        fencing_token: int,
        lease_seconds: int,
        idempotency_key: str,
        actor: str = "scheduler",
    ) -> dict[str, Any]:
        if lease_seconds < 1:
            raise ContractError("lease_seconds must be positive")
        document = {
            "run_id": run_id,
            "resource_id": resource_id,
            "owner": owner,
            "fencing_token": fencing_token,
            "lease_seconds": lease_seconds,
        }
        digest = _request_digest(document)
        scope_name = f"lease:heartbeat:{resource_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            self._require_active_run(run, action="heartbeat lease")
            self._validate_fencing_token(
                connection,
                run_id=run_id,
                resource_id=resource_id,
                fencing_token=fencing_token,
                owner=owner,
            )
            current = connection.execute(
                "SELECT * FROM leases WHERE resource_id = ?", (resource_id,)
            ).fetchone()
            assert current is not None
            now = datetime.now(UTC)
            heartbeat_at = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
            expires_at = (now + timedelta(seconds=lease_seconds)).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
            projection = {
                "kind": "lease_upsert",
                "resource_id": resource_id,
                "run_id": run_id,
                "owner": owner,
                "attempt_id": current["attempt_id"],
                "fencing_token": fencing_token,
                "acquired_at": current["acquired_at"],
                "heartbeat_at": heartbeat_at,
                "expires_at": expires_at,
                "write_set": json.loads(current["write_set_json"]),
            }
            new_revision = expected_revision + 1
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="LEASE_HEARTBEAT",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload={"request": document, "projection": projection},
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "resource_id": resource_id,
                    "fencing_token": fencing_token,
                    "expires_at": expires_at,
                },
            )
            self.store._apply_projection(connection, projection)
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def release_lease(
        self,
        *,
        run_id: str,
        expected_revision: int,
        resource_id: str,
        owner: str,
        fencing_token: int,
        idempotency_key: str,
        actor: str = "scheduler",
    ) -> dict[str, Any]:
        document = {
            "run_id": run_id,
            "resource_id": resource_id,
            "owner": owner,
            "fencing_token": fencing_token,
        }
        digest = _request_digest(document)
        scope_name = f"lease:release:{resource_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            self._validate_fencing_token(
                connection,
                run_id=run_id,
                resource_id=resource_id,
                fencing_token=fencing_token,
                owner=owner,
            )
            timestamp = utc_now()
            new_revision = expected_revision + 1
            projection = {
                "kind": "lease_delete",
                "resource_id": resource_id,
                "owner": owner,
                "fencing_token": fencing_token,
            }
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="LEASE_RELEASED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload={"request": document, "projection": projection},
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "resource_id": resource_id,
                    "released": True,
                },
            )
            self.store._apply_projection(connection, projection)
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def enqueue_notification(
        self,
        *,
        run_id: str,
        expected_revision: int,
        intent: NotificationIntent | Mapping[str, Any],
        idempotency_key: str,
        actor: str = "controller",
    ) -> dict[str, Any]:
        normalized = validate_intent(intent)
        document = {
            "route": normalized.route,
            "severity": normalized.severity,
            "payload": normalized.payload,
            "notification_id": normalized.notification_id,
        }
        digest = _request_digest(document)
        scope_name = f"notification:enqueue:{run_id}"
        outbox_documents, outbox_items = _intent_documents((normalized,))
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            timestamp = utc_now()
            new_revision = expected_revision + 1
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="NOTIFICATION_ENQUEUED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload={
                    "notification": document,
                    "projection": {"kind": "notification"},
                    "outbox": outbox_documents,
                },
                result={"run_id": run_id, "revision": new_revision, "queued": True},
                outbox=outbox_items,
            )
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def record_notification_attempt(
        self,
        *,
        run_id: str,
        expected_revision: int,
        notification_id: str,
        succeeded: bool,
        idempotency_key: str,
        error: str | None = None,
        actor: str = "notification-dispatcher",
    ) -> dict[str, Any]:
        document = {
            "notification_id": notification_id,
            "succeeded": succeeded,
            "error": error,
        }
        digest = _request_digest(document)
        scope_name = f"notification:attempt:{notification_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            row = connection.execute(
                "SELECT * FROM notification_outbox WHERE notification_id = ? AND run_id = ?",
                (notification_id, run_id),
            ).fetchone()
            if row is None or row["status"] == "delivered":
                raise TransitionError("notification attempt is missing or already delivered")
            timestamp = utc_now()
            attempt_count = int(row["attempt_count"]) + 1
            status = "delivered" if succeeded else "retry"
            next_attempt_at = timestamp if succeeded else retry_at(
                attempt_count=attempt_count
            )
            projection = {
                "kind": "notification_attempt",
                "notification_id": notification_id,
                "previous_attempt_count": int(row["attempt_count"]),
                "attempt_count": attempt_count,
                "status": status,
                "next_attempt_at": next_attempt_at,
                "delivered_at": timestamp if succeeded else None,
                "last_error": None if succeeded else (error or "delivery failed"),
                "updated_at": timestamp,
            }
            new_revision = expected_revision + 1
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type=(
                    "NOTIFICATION_DELIVERED"
                    if succeeded
                    else "NOTIFICATION_DELIVERY_FAILED"
                ),
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload={"attempt": document, "projection": projection},
                result={
                    "run_id": run_id,
                    "revision": new_revision,
                    "notification_id": notification_id,
                    "status": status,
                    "attempt_count": attempt_count,
                },
            )
            self.store._apply_projection(connection, projection)
            self._bump_run(
                self.store,
                connection,
                run_id=run_id,
                expected_revision=expected_revision,
                timestamp=str(result["event_created_at"]),
            )
            return result

    def set_mode(
        self,
        *,
        run_id: str,
        expected_revision: int,
        mode: str,
        authorization_id: str,
        idempotency_key: str,
        actor: str = "trusted-control-plane",
    ) -> dict[str, Any]:
        if mode not in {"staged", "auto"}:
            raise ContractError("mode must be staged or auto")
        document = {
            "run_id": run_id,
            "expected_revision": expected_revision,
            "mode": mode,
            "authorization_id": authorization_id,
        }
        digest = _request_digest(document)
        scope_name = f"run:mode:{run_id}"
        with self.store._write_transaction() as connection:
            replay = self.store._idempotency_result(
                connection,
                scope=scope_name,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            run = self._run_row(connection, run_id)
            self._require_revision(run, expected_revision)
            self._require_active_run(run, action="change mode")
            if run["state"] in _PREPLAN_STATES:
                raise TransitionError(
                    "mode changes require a confirmed Spec and passed PLAN_GATE"
                )
            authorization = self._active_authorization(connection, authorization_id)
            if mode == "auto" and authorization.get("record_type") != "grant":
                raise AuthorizationError("auto mode requires a trusted grant record")
            if mode == "staged" and authorization.get("record_type") not in {
                "grant",
                "approval",
            }:
                raise AuthorizationError(
                    "staged mode requires a trusted grant or approval record"
                )
            allowed = authorization.get("allowed_actions", [])
            requested_action = f"mode_set_{mode}"
            action = requested_action if requested_action in allowed else "mode_set"
            if not authorization_scope_allows(
                authorization,
                run_id=run_id,
                spec_hash=run["spec_hash"],
                config_hash=run["config_hash"],
                action=action,
            ):
                raise AuthorizationError("authorization does not cover the mode change")
            self._consume_one_time_authorization(
                connection,
                authorization_id=authorization_id,
                authorization=authorization,
                use_id=f"MODE:{run_id}:{mode}:{expected_revision}",
            )
            timestamp = utc_now()
            new_revision = expected_revision + 1
            projection = {
                "kind": "run_control",
                "run_id": run_id,
                "previous_revision": expected_revision,
                "revision": new_revision,
                "mode": mode,
                "spec_hash": run["spec_hash"],
                "config_hash": run["config_hash"],
                "updated_at": timestamp,
            }
            result = self.store._record_event(
                connection,
                scope=scope_name,
                run_id=run_id,
                run_revision=new_revision,
                event_type="MODE_CHANGED",
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=digest,
                payload={"request": document, "projection": projection},
                result={"run_id": run_id, "revision": new_revision, "mode": mode},
            )
            self.store._apply_projection(connection, projection)
            return result
