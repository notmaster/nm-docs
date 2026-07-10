"""One foreground/background control loop and fail-closed lifecycle proposals."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from .errors import AuthorizationError, ContractError, RecoveryError, TransitionError
from .models import OperationObservation, TransitionProposal
from .scheduler import Lease, Scheduler, TaskDefinition
from .util import canonical_json


class FailureClass(StrEnum):
    DETERMINISTIC_ACCEPTANCE = "deterministic_acceptance"
    SPEC_CONFLICT = "spec_conflict"
    POLICY_PERMISSION = "policy_permission"
    MERGE_CONFLICT = "merge_conflict"
    TRANSIENT_INFRASTRUCTURE = "transient_infrastructure"
    ADAPTER_PROTOCOL = "adapter_protocol"
    EXTERNAL_PARTIAL_UNKNOWN = "external_partial_unknown"
    ENVIRONMENT_HEALTH = "environment_health"


@dataclass(frozen=True)
class RetryPolicy:
    budgets: Mapping[FailureClass, int] = field(
        default_factory=lambda: {
            FailureClass.TRANSIENT_INFRASTRUCTURE: 3,
            FailureClass.ADAPTER_PROTOCOL: 2,
        }
    )

    def budget(self, failure_class: FailureClass) -> int:
        value = self.budgets.get(failure_class, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContractError("retry budgets must be nonnegative integers")
        return value


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    requires_attention: bool
    reason: str
    next_attempt: int


def decide_retry(
    failure_class: FailureClass,
    *,
    attempts: int,
    policy: RetryPolicy,
    failure_fingerprint: str,
    previous_fingerprint: str | None,
    input_changed: bool,
) -> RetryDecision:
    if attempts < 0:
        raise ContractError("attempt count cannot be negative")
    if failure_class == FailureClass.EXTERNAL_PARTIAL_UNKNOWN:
        return RetryDecision(False, True, "observe/reconcile is required before retry", attempts)
    retryable = policy.budget(failure_class)
    if retryable == 0:
        return RetryDecision(False, True, f"{failure_class} is not automatically retryable", attempts)
    if (
        failure_class == FailureClass.DETERMINISTIC_ACCEPTANCE
        and previous_fingerprint == failure_fingerprint
        and not input_changed
    ):
        return RetryDecision(False, True, "unchanged deterministic failure cannot loop", attempts)
    if attempts >= retryable:
        return RetryDecision(False, True, "retry budget exhausted", attempts)
    return RetryDecision(True, False, "bounded retry permitted", attempts + 1)


def failure_fingerprint(
    failure_class: FailureClass,
    *,
    command_digest: str,
    input_digest: str,
    environment_digest: str,
    message: str,
) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "class": failure_class.value,
                "command": command_digest,
                "input": input_digest,
                "environment": environment_digest,
                "message": message,
            }
        )
    ).hexdigest()


class DurableLauncher(Protocol):
    """Launch a restartable controller process and persist its identity."""

    def launch(self, run_id: str) -> Mapping[str, Any]: ...


class OperationReconciler(Protocol):
    def __call__(self, operation: Mapping[str, Any]) -> str | Mapping[str, Any]: ...


_SAFE_OPERATION_OBSERVATIONS = frozenset(
    {"completed", "not_started", "failed", "cancelled"}
)


class WorkflowController:
    """Both execution modes call ``drive_once`` over the same durable state."""

    def __init__(
        self,
        reducer: Any,
        store: Any | None = None,
        *,
        run_id: str | None = None,
        scheduler: Scheduler | None = None,
        retry_policy: RetryPolicy | None = None,
        actor: str = "nm-v6-controller",
        signature_verifier: Any | None = None,
        durable_launcher: DurableLauncher | None = None,
        operation_reconciler: OperationReconciler | None = None,
        drive_step: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> None:
        self.reducer = reducer
        self.store = store or getattr(reducer, "store", None)
        if self.store is None:
            raise ContractError("WorkflowController requires the reducer's canonical store")
        self.run_id = run_id
        self.scheduler = scheduler
        self.retry_policy = retry_policy or RetryPolicy()
        self.actor = actor
        self.signature_verifier = signature_verifier
        self.durable_launcher = durable_launcher
        self.operation_reconciler = operation_reconciler
        self.drive_step = drive_step

    def drive_once(
        self,
        run_id: str,
        step: Callable[[Mapping[str, Any]], bool],
    ) -> bool:
        run = self.store.get_run(run_id)
        if not isinstance(run, Mapping):
            raise ContractError(f"unknown run: {run_id}")
        if run.get("state") in {"COMPLETED", "ROLLED_BACK", "FAILED", "CANCELLED"}:
            return False
        return bool(step(run))

    def run_foreground(
        self,
        run_id: str,
        step: Callable[[Mapping[str, Any]], bool],
        *,
        max_steps: int | None = None,
    ) -> int:
        if max_steps is not None and max_steps < 1:
            raise ContractError("max_steps must be positive")
        count = 0
        while max_steps is None or count < max_steps:
            if not self.drive_once(run_id, step):
                break
            count += 1
        return count

    def run_detached(self, run_id: str, launcher: DurableLauncher | None) -> Mapping[str, Any]:
        if launcher is None:
            raise ContractError(
                "detached execution requires a durable external launcher; threads/PIDs are not runtime truth"
            )
        receipt = launcher.launch(run_id)
        if not isinstance(receipt, Mapping) or not receipt.get("controller_id"):
            raise ContractError("durable launcher did not return a persisted controller identity")
        return receipt

    def select_tasks(
        self,
        *,
        completed: Iterable[str],
        active: Mapping[str, Lease],
        limit: int | None = None,
        run_id: str | None = None,
    ) -> tuple[TaskDefinition, ...]:
        if self.scheduler is None:
            raise ContractError("controller has no scheduler")
        effective_run_id = run_id or self.run_id
        if effective_run_id:
            run = self.store.get_run(effective_run_id)
            if not isinstance(run, Mapping):
                raise ContractError(f"unknown run: {effective_run_id}")
            if run.get("state") in {
                "PAUSED",
                "ATTENTION_REQUIRED",
                "COMPLETED",
                "ROLLED_BACK",
                "FAILED",
                "CANCELLED",
            }:
                return ()
        return self.scheduler.select(completed=completed, active=active, limit=limit)

    def pause_proposal(
        self,
        *,
        run_id: str,
        expected_revision: int,
        current_state: str,
        reason: str,
        active_operations: Iterable[Mapping[str, Any]] = (),
        reconcile: OperationReconciler | None = None,
    ) -> TransitionProposal:
        observations = self._reconcile_active(active_operations, reconcile=reconcile)
        unsafe = [
            item
            for item in observations
            if item["classification"] not in _SAFE_OPERATION_OBSERVATIONS
        ]
        if unsafe:
            return self._attention_proposal(
                run_id=run_id,
                expected_revision=expected_revision,
                current_state=current_state,
                reason="pause requested while an external effect remains unreconciled",
                observations=observations,
            )
        return TransitionProposal(
            run_id=run_id,
            expected_revision=expected_revision,
            event="REQUEST_PAUSE",
            actor=self.actor,
            idempotency_key=f"pause:{run_id}:{expected_revision}",
            payload={
                "resume_state": current_state,
                "reason": reason,
                "external_observations": observations,
                "safe_pause_point": True,
                "actors_fenced": True,
                "external_operations_reconciled": True,
            },
        )

    def cancel_proposal(
        self,
        *,
        run_id: str,
        expected_revision: int,
        current_state: str,
        reason: str,
        active_operations: Iterable[Mapping[str, Any]] = (),
        reconcile: OperationReconciler | None = None,
    ) -> TransitionProposal:
        observations = self._reconcile_active(active_operations, reconcile=reconcile)
        unsafe = [
            item
            for item in observations
            if item["classification"] not in _SAFE_OPERATION_OBSERVATIONS
        ]
        if unsafe:
            return self._attention_proposal(
                run_id=run_id,
                expected_revision=expected_revision,
                current_state=current_state,
                reason="cancellation waiting for external-effect reconciliation",
                observations=observations,
            )
        return TransitionProposal(
            run_id=run_id,
            expected_revision=expected_revision,
            event="CANCEL",
            actor=self.actor,
            idempotency_key=f"cancel:{run_id}:{expected_revision}",
            payload={
                "resume_state": current_state,
                "reason": reason,
                "external_observations": observations,
                "actors_fenced": True,
                "external_operations_reconciled": True,
            },
        )

    def retry_proposal(
        self,
        *,
        run_id: str,
        expected_revision: int,
        task_id: str,
        failure_class: FailureClass,
        attempts: int,
        failure_fingerprint: str,
        previous_fingerprint: str | None,
        input_changed: bool,
    ) -> TransitionProposal:
        decision = decide_retry(
            failure_class,
            attempts=attempts,
            policy=self.retry_policy,
            failure_fingerprint=failure_fingerprint,
            previous_fingerprint=previous_fingerprint,
            input_changed=input_changed,
        )
        event = "RETRYABLE_FAILURE" if decision.retry else "REQUIRE_ATTENTION"
        return TransitionProposal(
            run_id=run_id,
            expected_revision=expected_revision,
            event=event,
            actor=self.actor,
            idempotency_key=f"retry:{run_id}:{task_id}:{expected_revision}",
            payload={
                "task_id": task_id,
                "failure_class": failure_class.value,
                "failure_fingerprint": failure_fingerprint,
                "next_attempt": decision.next_attempt,
                "reason": decision.reason,
                "requires_attention": decision.requires_attention,
                "retry_allowed": decision.retry,
                "actors_fenced": not decision.retry,
                "external_operations_reconciled": not decision.retry,
            },
        )

    def environment_mismatch_proposal(
        self,
        *,
        run_id: str,
        expected_revision: int,
        current_state: str,
        evidence_id: str,
        configured_identity: str,
        configured_fingerprint: str,
        authorized_identity: str,
        authorized_fingerprint: str,
    ) -> TransitionProposal:
        """Bind a persisted identity mismatch to a fail-closed attention event."""

        if not evidence_id:
            raise ContractError("environment mismatch requires persisted evidence")
        receipt = self.store.get_evidence(evidence_id)
        run = self.store.get_run(run_id)
        if not isinstance(receipt, Mapping) or not isinstance(run, Mapping):
            raise ContractError("environment mismatch evidence or run is unavailable")
        if receipt.get("run_id") != run_id:
            raise ContractError("environment mismatch evidence belongs to another run")
        if (
            receipt.get("spec_hash") != run.get("spec_hash")
            or receipt.get("config_hash") != run.get("config_hash")
        ):
            raise ContractError("environment mismatch evidence has a stale input binding")
        observed_identity = receipt.get("environment_id")
        observed_fingerprint = receipt.get("environment_fingerprint")
        if not isinstance(observed_identity, str) or not isinstance(
            observed_fingerprint, str
        ):
            raise ContractError("environment identity evidence lacks identity or fingerprint")
        mismatch = (
            observed_identity != configured_identity
            or observed_fingerprint != configured_fingerprint
            or observed_identity != authorized_identity
            or observed_fingerprint != authorized_fingerprint
        )
        if not mismatch:
            raise ContractError("environment identity matches configured and authorized scope")
        return TransitionProposal(
            run_id=run_id,
            expected_revision=expected_revision,
            event="REQUIRE_ATTENTION",
            actor=self.actor,
            idempotency_key=f"environment-mismatch:{run_id}:{evidence_id}:{expected_revision}",
            payload={
                "resume_state": current_state,
                "reason": "observed environment identity is outside configured or authorized scope",
                "required_decision": "correct_environment_identity_or_authorization",
                "actors_fenced": True,
                "external_operations_reconciled": True,
                "evidence_ids": [evidence_id],
                "environment_observation": {
                    "observed_identity": observed_identity,
                    "observed_fingerprint": observed_fingerprint,
                    "configured_identity": configured_identity,
                    "configured_fingerprint": configured_fingerprint,
                    "authorized_identity": authorized_identity,
                    "authorized_fingerprint": authorized_fingerprint,
                },
            },
        )

    def submit(self, proposal: TransitionProposal, *, machine: str = "run", entity_id: str | None = None) -> Any:
        return self.reducer.transition(proposal, machine=machine, entity_id=entity_id)

    def handle_cli(self, command: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Dispatch lifecycle CLI requests without bypassing reducer authority."""

        run_id = str(arguments.get("run_id") or self.run_id or "")
        if not run_id:
            raise ContractError("controller command requires run_id")
        run = self.store.get_run(run_id)
        if not isinstance(run, Mapping):
            raise ContractError(f"unknown run: {run_id}")
        revision = int(run["revision"])
        state = str(run["state"])

        if command == "spec":
            spec_command = arguments.get("spec_command")
            if spec_command == "confirmation" and arguments.get("confirmation_command") == "request":
                if state not in {"SPEC_REVIEW", "SPEC_AWAITING_CONFIRMATION"}:
                    raise TransitionError(
                        "Spec confirmation can only be requested from review or awaiting confirmation"
                    )
                if state == "SPEC_REVIEW":
                    self.submit(
                        TransitionProposal(
                            run_id=run_id,
                            expected_revision=revision,
                            event="REQUEST_SPEC_CONFIRMATION",
                            actor=self.actor,
                            idempotency_key=f"spec-await-confirmation:{run_id}:{revision}",
                        )
                    )
                    current = self.store.get_run(run_id)
                    if not isinstance(current, Mapping):
                        raise ContractError("Spec confirmation transition lost canonical run state")
                    revision = int(current["revision"])
                scope = {
                    "spec_hash": run["spec_hash"],
                    "decision": "confirmed",
                }
                return self.reducer.create_authorization_request(
                    run_id=run_id,
                    expected_revision=revision,
                    request_id=f"AUTHREQ-{run_id}-{revision + 1}",
                    request_type="spec_confirmation",
                    scope=scope,
                    expires_at=str(arguments["expires_at"]),
                    idempotency_key=f"spec-confirmation-request:{run_id}:{revision}",
                    actor=self.actor,
                )
            if spec_command == "confirm":
                if state != "SPEC_AWAITING_CONFIRMATION":
                    raise TransitionError(
                        "Spec confirmation record requires SPEC_AWAITING_CONFIRMATION"
                    )
                imported = self._import_signed_record(arguments, expected_revision=revision)
                current = self.store.get_run(run_id)
                if not isinstance(current, Mapping):
                    raise ContractError("Spec confirmation import lost canonical run state")
                return {
                    "schema_version": "nm-v6/controller-result-v1",
                    "run_id": run_id,
                    "revision": int(current["revision"]),
                    "state": str(current["state"]),
                    "result": "confirmation_recorded_gate_pending",
                    "authorization": dict(imported),
                }
            raise ContractError("unsupported Spec lifecycle command")

        if command == "authorize":
            authorize_command = arguments.get("authorize_command")
            if authorize_command == "request":
                from .util import load_json

                scope = load_json(_required_path(arguments, "scope"))
                if not isinstance(scope, Mapping):
                    raise ContractError("authorization scope file must contain an object")
                return self.reducer.create_authorization_request(
                    run_id=run_id,
                    expected_revision=revision,
                    request_id=f"AUTHREQ-{run_id}-{revision + 1}",
                    request_type="grant",
                    scope=scope,
                    expires_at=str(arguments["expires_at"]),
                    idempotency_key=f"authorization-request:{run_id}:{revision}",
                    actor=self.actor,
                )
            if authorize_command in {"approve", "revoke"}:
                return self._import_signed_record(arguments, expected_revision=revision)
            raise ContractError("unsupported authorization lifecycle command")

        if command == "mode":
            if arguments.get("mode_command") != "set":
                raise ContractError("unsupported mode command")
            mode = str(arguments.get("mode", ""))
            grant_id = arguments.get("grant_id")
            if not isinstance(grant_id, str) or not grant_id:
                raise AuthorizationError("persisted mode change requires a trusted grant")
            return self.reducer.set_mode(
                run_id=run_id,
                expected_revision=revision,
                mode=mode,
                authorization_id=grant_id,
                idempotency_key=f"mode:{run_id}:{revision}:{mode}",
                actor=self.actor,
            )

        if command == "run":
            if bool(arguments.get("detach")) and not bool(arguments.get("child")):
                return dict(self.run_detached(run_id, self.durable_launcher))
            if self.drive_step is None:
                return {
                    "schema_version": "nm-v6/controller-result-v1",
                    "run_id": run_id,
                    "revision": revision,
                    "state": state,
                    "result": "waiting_for_dispatcher",
                }
            steps = self.run_foreground(
                run_id,
                self.drive_step,
                max_steps=1 if arguments.get("once") else None,
            )
            latest = self.store.get_run(run_id)
            dispatch_result = getattr(self.drive_step, "last_result", None)
            result = {
                "schema_version": "nm-v6/controller-result-v1",
                "run_id": run_id,
                "steps": steps,
                "state": latest["state"] if isinstance(latest, Mapping) else state,
                "revision": latest["revision"] if isinstance(latest, Mapping) else revision,
            }
            if isinstance(dispatch_result, Mapping):
                result.update(
                    {
                        "result": dispatch_result.get(
                            "result", "driven" if steps else "waiting_for_input"
                        ),
                        "dispatch": dict(dispatch_result),
                    }
                )
                if dispatch_result.get("waiting_for"):
                    result["waiting_for"] = dispatch_result["waiting_for"]
            else:
                result["result"] = "driven" if steps else "waiting_for_input"
            return result

        if command == "pause":
            observations = self._reconcile_active(
                self._active_operations(run_id),
                reconcile=self.operation_reconciler,
                persist=True,
            )
            current = self.store.get_run(run_id)
            if not isinstance(current, Mapping):
                raise ContractError(f"unknown run after reconciliation: {run_id}")
            revision = int(current["revision"])
            state = str(current["state"])
            unsafe = [
                item
                for item in observations
                if item["classification"] not in _SAFE_OPERATION_OBSERVATIONS
            ]
            if unsafe:
                proposal = self._attention_proposal(
                    run_id=run_id,
                    expected_revision=revision,
                    current_state=state,
                    reason="pause requested while an external effect remains unreconciled",
                    observations=observations,
                )
            else:
                proposal = TransitionProposal(
                    run_id=run_id,
                    expected_revision=revision,
                    event="REQUEST_PAUSE",
                    actor=self.actor,
                    idempotency_key=f"pause:{run_id}:{revision}",
                    payload={
                        "resume_state": state,
                        "reason": str(
                            arguments.get("reason")
                            or "administrator requested pause"
                        ),
                        "external_observations": observations,
                        "safe_pause_point": True,
                        "actors_fenced": True,
                        "external_operations_reconciled": True,
                    },
                )
            return self.submit(proposal)

        if command == "resume":
            resume_state = run.get("resume_state")
            if not isinstance(resume_state, str) or not resume_state:
                raise ContractError("run has no validated resume state")
            proposal = TransitionProposal(
                run_id=run_id,
                expected_revision=revision,
                event="RESUME",
                actor=self.actor,
                idempotency_key=f"resume:{run_id}:{revision}",
                payload={
                    "resume_state": resume_state,
                    "external_operations_reconciled": not self._active_operations(run_id),
                },
            )
            return self.submit(proposal)

        if command == "cancel":
            authorization_id = arguments.get("grant_id") or _run_payload(run).get(
                "cancel_authorization_id"
            )
            if not isinstance(authorization_id, str) or not authorization_id:
                raise AuthorizationError("cancellation requires trusted authorization")
            observations = self._reconcile_active(
                self._active_operations(run_id),
                reconcile=self.operation_reconciler,
                persist=True,
            )
            current = self.store.get_run(run_id)
            if not isinstance(current, Mapping):
                raise ContractError(f"unknown run after reconciliation: {run_id}")
            revision = int(current["revision"])
            state = str(current["state"])
            unsafe = [
                item
                for item in observations
                if item["classification"] not in _SAFE_OPERATION_OBSERVATIONS
            ]
            if unsafe:
                proposal = self._attention_proposal(
                    run_id=run_id,
                    expected_revision=revision,
                    current_state=state,
                    reason="cancellation waiting for external-effect reconciliation",
                    observations=observations,
                )
            else:
                proposal = TransitionProposal(
                    run_id=run_id,
                    expected_revision=revision,
                    event="CANCEL",
                    actor=self.actor,
                    idempotency_key=f"cancel:{run_id}:{revision}",
                    payload={
                        "resume_state": state,
                        "reason": str(
                            arguments.get("reason")
                            or "administrator requested cancellation"
                        ),
                        "external_observations": observations,
                        "actors_fenced": True,
                        "external_operations_reconciled": True,
                    },
                    authorization_id=authorization_id,
                )
            return self.submit(proposal)

        if command == "reconcile":
            operations = self._active_operations(run_id)
            if operations and self.operation_reconciler is None:
                raise RecoveryError("reconcile command requires an observed-state reconciler")
            observations = self._reconcile_active(
                operations, reconcile=self.operation_reconciler, persist=True
            )
            latest = self.store.get_run(run_id)
            if not isinstance(latest, Mapping):
                raise ContractError(f"unknown run after reconciliation: {run_id}")
            return {
                "schema_version": "nm-v6/reconciliation-result-v1",
                "run_id": run_id,
                "revision": int(latest["revision"]),
                "observations": observations,
                "result": (
                    "reconciled"
                    if all(
                        item["classification"] in _SAFE_OPERATION_OBSERVATIONS
                        for item in observations
                    )
                    else "attention_required"
                ),
            }

        if command == "notify-test":
            from .outbox import NotificationIntent, notification_identity

            route = str(arguments.get("route") or "")
            notification_id = notification_identity(
                event_id=f"notify-test:{run_id}:{revision}",
                route=route,
                severity="progress",
            )
            return self.reducer.enqueue_notification(
                run_id=run_id,
                expected_revision=revision,
                intent=NotificationIntent(
                    route=route,
                    severity="progress",
                    payload={"event": "notify_test", "run_id": run_id},
                    notification_id=notification_id,
                ),
                idempotency_key=notification_id,
                actor=self.actor,
            )

        raise ContractError(f"unsupported controller command: {command}")

    def _import_signed_record(
        self, arguments: Mapping[str, Any], *, expected_revision: int
    ) -> Mapping[str, Any]:
        if self.signature_verifier is None:
            raise AuthorizationError(
                "signed record import requires an agent-inaccessible trusted verifier"
            )
        from .util import load_json

        record = load_json(_required_path(arguments, "record"))
        if not isinstance(record, Mapping):
            raise ContractError("signed authorization record must be an object")
        return self.reducer.import_authorization(
            record,
            self.signature_verifier,
            expected_revision=expected_revision,
            idempotency_key=f"authorization-import:{run_id_from_record(record)}",
            actor="trusted-control-plane",
        )

    def _active_operations(self, run_id: str) -> tuple[Mapping[str, Any], ...]:
        operation_ids: set[str] = set()
        for event in self.store.list_events(run_id=run_id):
            payload = event.get("payload", {})
            if not isinstance(payload, Mapping):
                continue
            projection = payload.get("projection", {})
            if isinstance(projection, Mapping) and isinstance(
                projection.get("operation_id"), str
            ):
                operation_ids.add(str(projection["operation_id"]))
        active: list[Mapping[str, Any]] = []
        for operation_id in sorted(operation_ids):
            operation = self.store.get_operation(operation_id)
            if isinstance(operation, Mapping) and operation.get("status") in {
                "started",
                "partial",
                "unknown",
            }:
                active.append(operation)
        return tuple(active)

    def _reconcile_active(
        self,
        operations: Iterable[Mapping[str, Any]],
        *,
        reconcile: OperationReconciler | None,
        persist: bool = False,
    ) -> list[dict[str, Any]]:
        values = tuple(operations)
        if values and reconcile is None:
            raise RecoveryError("active external Operations require a reconciler")
        observations: list[dict[str, Any]] = []
        for operation in values:
            operation_id = operation.get("operation_id")
            if not isinstance(operation_id, str):
                raise RecoveryError("active operation lacks operation_id")
            raw = reconcile(operation) if reconcile is not None else "unknown"
            if isinstance(raw, Mapping):
                classification = raw.get("classification", raw.get("status"))
                effect_id = raw.get("effect_id", operation.get("effect_id"))
                result = raw.get("result", raw.get("observed_state", {}))
                already_persisted = raw.get("persisted") is True
            else:
                classification = raw
                effect_id = operation.get("effect_id")
                result = {"classification": classification}
                already_persisted = False
            if classification not in {
                "completed",
                "not_started",
                "partial",
                "failed",
                "unknown",
                "cancelled",
            }:
                raise RecoveryError(
                    f"reconciler returned an invalid classification: {classification!r}"
                )
            if effect_id is not None and not isinstance(effect_id, str):
                raise RecoveryError("reconciler effect_id must be a string or null")
            if not isinstance(result, Mapping):
                raise RecoveryError("reconciler result must be an object")
            if persist and not already_persisted:
                action_id = operation.get("action_id")
                if not isinstance(action_id, str) or not action_id:
                    raise RecoveryError("active operation lacks action_id")
                current = self.store.get_run(str(operation.get("run_id") or self.run_id or ""))
                if not isinstance(current, Mapping):
                    raise RecoveryError("active operation is not bound to a known run")
                self.reducer.record_operation_observation(
                    OperationObservation(
                        operation_id=operation_id,
                        action_id=action_id,
                        status=str(classification),
                        effect_id=str(effect_id) if effect_id is not None else None,
                        result=dict(result),
                    ),
                    run_id=str(current["run_id"]),
                    expected_revision=int(current["revision"]),
                    idempotency_key=(
                        f"control-reconcile:{operation_id}:{classification}:"
                        f"{effect_id or 'none'}:"
                        f"{hashlib.sha256(canonical_json(dict(result))).hexdigest()[:16]}"
                    ),
                    actor=self.actor,
                )
            observations.append(
                {"operation_id": operation_id, "classification": classification}
            )
        return observations

    def _attention_proposal(
        self,
        *,
        run_id: str,
        expected_revision: int,
        current_state: str,
        reason: str,
        observations: list[dict[str, Any]],
    ) -> TransitionProposal:
        return TransitionProposal(
            run_id=run_id,
            expected_revision=expected_revision,
            event="REQUIRE_ATTENTION",
            actor=self.actor,
            idempotency_key=f"attention:{run_id}:{expected_revision}",
            payload={
                "resume_state": current_state,
                "reason": reason,
                "required_decision": "reconcile_external_operation",
                "external_observations": observations,
                "actors_fenced": True,
                "external_operations_reconciled": not observations,
            },
        )


def _required_path(arguments: Mapping[str, Any], field: str) -> Path:
    value = arguments.get(field)
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field} path is required")
    return Path(value).expanduser().resolve()


def _run_payload(run: Mapping[str, Any]) -> Mapping[str, Any]:
    value = run.get("payload", {})
    return value if isinstance(value, Mapping) else {}


def run_id_from_record(record: Mapping[str, Any]) -> str:
    for field in (
        "confirmation_id",
        "authorization_id",
        "grant_id",
        "approval_id",
        "revocation_id",
    ):
        value = record.get(field)
        if isinstance(value, str) and value:
            return value
    raise ContractError("signed record lacks a stable identifier")


def _replace_event(
    proposal: TransitionProposal,
    event: str,
    *,
    authorization_id: str | None = None,
) -> TransitionProposal:
    return replace(
        proposal,
        event=event,
        authorization_id=(
            authorization_id if authorization_id is not None else proposal.authorization_id
        ),
    )
