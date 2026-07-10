"""Persist-before-call operation execution and observed-state reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from .actions import ActionDefinition, ActionExecutor, ActionResult, OperationRecorder
from .errors import ActionError, RecoveryError, TransitionError
from .failpoints import checkpoint
from .models import OperationObservation
from .workspace import Workspace


OPERATION_CLASSIFICATIONS = frozenset(
    {"completed", "not_started", "partial", "failed", "unknown"}
)


class ReadableOperationRecorder(OperationRecorder, Protocol):
    def get_operation(self, operation_id: str) -> Mapping[str, Any] | None: ...


class ReducerOperationRecorder:
    """Adapt ActionExecutor callbacks to the single reducer write boundary."""

    def __init__(
        self,
        reducer: Any,
        store: Any,
        *,
        run_id: str,
        expected_revision: int | Callable[[], int],
        scope: Mapping[str, Any] | None = None,
        fencing_token: int | None = None,
    ) -> None:
        self.reducer = reducer
        self.store = store
        self.run_id = run_id
        self._expected_revision = expected_revision
        self.scope = dict(scope or {})
        self.fencing_token = fencing_token

    def begin_operation(
        self,
        *,
        operation_id: str,
        action_id: str,
        idempotency_key: str,
        grant_id: str | None,
        grant_revision: int | None,
    ) -> Any:
        if not operation_id or operation_id != idempotency_key:
            raise TransitionError("operation ID must be the persisted idempotency key")
        existing = self.get_operation(operation_id)
        if existing is not None:
            if (
                existing.get("action_id") != action_id
                or existing.get("idempotency_key") != idempotency_key
            ):
                raise TransitionError("operation ID was already bound to another request")
            if existing.get("status") == "not_started":
                revision = self.expected_revision()
                self.reducer.restart_operation(
                    run_id=self.run_id,
                    expected_revision=revision,
                    operation_id=operation_id,
                    authorization_id=grant_id,
                    grant_revision=grant_revision,
                    idempotency_key=f"restart:{operation_id}:{revision}",
                    fencing_token=self.fencing_token,
                )
                current = self.get_operation(operation_id)
                return {**dict(current or existing), "_replayed": False}
            return {**dict(existing), "_replayed": True}
        scope = {**self.scope, "grant_revision": grant_revision}
        result = self.reducer.start_operation(
            run_id=self.run_id,
            expected_revision=self.expected_revision(),
            operation_id=operation_id,
            action_id=action_id,
            operation_kind="external_mutation",
            idempotency_key=idempotency_key,
            authorization_id=grant_id,
            gate_id=(
                str(scope["gate_id"])
                if isinstance(scope.get("gate_id"), str)
                else None
            ),
            scope=scope,
            fencing_token=self.fencing_token,
        )
        current = self.get_operation(operation_id)
        return {**dict(current or result), "_replayed": False}

    def finish_operation(
        self,
        *,
        operation_id: str,
        status: str,
        result: Mapping[str, Any] | None,
        error: str | None,
    ) -> Any:
        observed_action_id = "unknown"
        effect_id = None
        payload: dict[str, Any] = {}
        if result is not None:
            observed_action_id = str(result.get("action_id", observed_action_id))
            effect_id = result.get("effect_id")
            payload = dict(result)
        current = self.get_operation(operation_id)
        action_id = (
            str(current.get("action_id"))
            if isinstance(current, Mapping) and current.get("action_id")
            else observed_action_id
        )
        if effect_id is None and isinstance(current, Mapping):
            current_effect = current.get("effect_id")
            if isinstance(current_effect, str):
                effect_id = current_effect
        payload["observed_action_id"] = observed_action_id
        if error:
            payload["error"] = error
        observation = OperationObservation(
            operation_id=operation_id,
            action_id=action_id,
            status=status,
            effect_id=effect_id if isinstance(effect_id, str) else None,
            result=payload,
        )
        return self.reducer.record_operation_observation(
            run_id=self.run_id,
            expected_revision=self.expected_revision(),
            observation=observation,
            idempotency_key=f"observe:{operation_id}:{observed_action_id}:{status}",
        )

    def get_operation(self, operation_id: str) -> Mapping[str, Any] | None:
        value = self.store.get_operation(operation_id)
        return value if isinstance(value, Mapping) else None

    def expected_revision(self) -> int:
        if callable(self._expected_revision):
            return int(self._expected_revision())
        run = self.store.get_run(self.run_id)
        if isinstance(run, Mapping) and "revision" in run:
            return int(run["revision"])
        return int(self._expected_revision)


@dataclass(frozen=True)
class ReconciliationResult:
    operation_id: str
    classification: str
    observation: ActionResult
    reconciliation: ActionResult | None
    safe_to_retry: bool


class AmbiguousOperationError(RecoveryError):
    """A valid partial/unknown mutation result that must be reconciled."""

    def __init__(self, operation_id: str, result: ActionResult) -> None:
        super().__init__(
            f"operation {operation_id} is {result.status}; "
            "observe/reconcile before retry"
        )
        self.operation_id = operation_id
        self.result = result


class RecoveryController:
    """Never retry an ambiguous external mutation before observation."""

    def __init__(
        self,
        definitions: Mapping[str, ActionDefinition],
        executor: ActionExecutor,
        recorder: ReadableOperationRecorder,
    ) -> None:
        self.definitions = dict(definitions)
        self.executor = executor
        self.recorder = recorder

    def execute_mutation(
        self,
        action_id: str,
        *,
        workspace: Workspace,
        operation_id: str,
        grant_id: str,
        grant_revision: int,
        core_env: Mapping[str, str] | None = None,
        allow_network: bool = False,
    ) -> ActionResult:
        definition = self._mutation(action_id)
        try:
            result = self.executor.execute(
                definition,
                workspace=workspace,
                operation_id=operation_id,
                core_env=core_env,
                recorder=self.recorder,
                grant_id=grant_id,
                grant_revision=grant_revision,
                allow_network=allow_network,
            )
        except ActionError:
            # The executor persisted unknown/failed before propagating.  Caller
            # must explicitly reconcile; no blind retry occurs here.
            raise
        if result.status in {"partial", "unknown"}:
            raise AmbiguousOperationError(operation_id, result)
        return result

    def observe_reconcile(
        self,
        action_id: str,
        *,
        workspace: Workspace,
        operation_id: str,
        allow_network: bool = False,
    ) -> ReconciliationResult:
        mutation = self._mutation(action_id)
        observe = self.definitions.get(mutation.observe_action_id or "")
        reconcile = self.definitions.get(mutation.reconcile_action_id or "")
        if observe is None or reconcile is None:
            raise RecoveryError("mutation action has unresolved recovery actions")
        checkpoint("operation.before_observe")
        observation = self.executor.execute(
            observe,
            workspace=workspace,
            operation_id=operation_id,
            allow_network=allow_network,
        )
        checkpoint("operation.after_observe")
        classification = classify_observation(observation)
        if classification == "completed":
            self.recorder.finish_operation(
                operation_id=operation_id,
                status="succeeded",
                result=observation.as_dict(),
                error=None,
            )
            return ReconciliationResult(operation_id, classification, observation, None, False)
        if classification == "not_started":
            self.recorder.finish_operation(
                operation_id=operation_id,
                status="not_started",
                result=observation.as_dict(),
                error=None,
            )
            return ReconciliationResult(operation_id, classification, observation, None, True)
        if classification == "failed":
            self.recorder.finish_operation(
                operation_id=operation_id,
                status="failed",
                result=observation.as_dict(),
                error="observed external failure",
            )
            return ReconciliationResult(operation_id, classification, observation, None, False)

        checkpoint("operation.before_reconcile")
        reconciliation = self.executor.execute(
            reconcile,
            workspace=workspace,
            operation_id=operation_id,
            allow_network=allow_network,
        )
        checkpoint("operation.after_reconcile")
        reconciled_classification = classify_observation(reconciliation)
        if reconciled_classification not in {"completed", "not_started", "failed"}:
            self.recorder.finish_operation(
                operation_id=operation_id,
                status="unknown",
                result=reconciliation.as_dict(),
                error="external effect remains ambiguous after reconciliation",
            )
            raise RecoveryError("external effect remains ambiguous after reconciliation")
        status = "succeeded" if reconciled_classification == "completed" else reconciled_classification
        self.recorder.finish_operation(
            operation_id=operation_id,
            status=status,
            result=reconciliation.as_dict(),
            error=None if status in {"succeeded", "not_started"} else "reconciliation observed failure",
        )
        return ReconciliationResult(
            operation_id,
            reconciled_classification,
            observation,
            reconciliation,
            reconciled_classification == "not_started",
        )

    def recover_nonterminal(
        self,
        operation: Mapping[str, Any],
        *,
        workspace: Workspace,
        allow_network: bool = False,
    ) -> ReconciliationResult:
        operation_id = operation.get("operation_id")
        action_id = operation.get("action_id")
        if not isinstance(operation_id, str) or not isinstance(action_id, str):
            raise RecoveryError("nonterminal operation record is malformed")
        return self.observe_reconcile(
            action_id,
            workspace=workspace,
            operation_id=operation_id,
            allow_network=allow_network,
        )

    def _mutation(self, action_id: str) -> ActionDefinition:
        definition = self.definitions.get(action_id)
        if definition is None:
            raise RecoveryError(f"unknown action: {action_id}")
        if definition.kind != "external_mutation":
            raise RecoveryError(f"action is not an external mutation: {action_id}")
        return definition


def classify_observation(result: ActionResult) -> str:
    value = result.observed_state.get("classification")
    if value is None:
        value = result.observed_state.get("effect_status")
    if value in OPERATION_CLASSIFICATIONS:
        return str(value)
    if result.status == "succeeded" and result.observed_state.get("completed") is True:
        return "completed"
    if result.status == "failed":
        return "failed"
    if result.status == "partial":
        return "partial"
    return "unknown"
