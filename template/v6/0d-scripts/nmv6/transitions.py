"""Versioned, fail-closed Run/Phase/Task/Attempt transition table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .errors import TransitionError


TRANSITION_TABLE_VERSION = "nm-v6/transitions-v1"
RESUME_STATE = "__RECORDED_RESUME_STATE__"

RUN_STATES = frozenset(
    {
        "DISCOVERING",
        "SPEC_DRAFT",
        "SPEC_REVIEW",
        "SPEC_AWAITING_CONFIRMATION",
        "SPEC_CONFIRMED",
        "PLANNING",
        "READY",
        "IMPLEMENTING",
        "PHASE_VERIFYING",
        "PHASE_AWAITING_ACCEPTANCE",
        "INTEGRATING_DEV",
        "INTEGRATION_VERIFYING",
        "HOTFIX_IMPLEMENTING",
        "HOTFIX_VERIFYING",
        "HOTFIX_INTEGRATING_STABLE",
        "HOTFIX_STABLE_VERIFYING",
        "HOTFIX_RECONCILING_DEV",
        "HOTFIX_DEV_VERIFYING",
        "RELEASE_READY",
        "RELEASING",
        "RELEASE_VERIFIED",
        "DEPLOY_READY",
        "DEPLOYING",
        "POST_DEPLOY_VERIFYING",
        "COMPLETED",
        "PAUSED",
        "ATTENTION_REQUIRED",
        "ROLLBACK_REQUIRED",
        "ROLLING_BACK",
        "POST_ROLLBACK_VERIFYING",
        "ROLLED_BACK",
        "FAILED",
        "CANCELLED",
    }
)
PHASE_STATES = frozenset(
    {"PLANNED", "ACTIVE", "VERIFYING", "AWAITING_ACCEPTANCE", "ACCEPTED", "INTEGRATED", "BLOCKED", "CANCELLED"}
)
TASK_STATES = frozenset(
    {"PLANNED", "READY", "LEASED", "RUNNING", "CANDIDATE", "VERIFYING", "VERIFIED", "INTEGRATED", "RETRYABLE_FAILURE", "BLOCKED", "CANCELLED", "SKIPPED"}
)
ATTEMPT_STATES = frozenset(
    {"CREATED", "DISPATCHED", "RUNNING", "COLLECTING", "SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED", "LOST"}
)

TERMINAL_RUN_STATES = frozenset({"COMPLETED", "ROLLED_BACK", "FAILED", "CANCELLED"})
EXTERNAL_MUTATION_STATES = frozenset(
    {"INTEGRATING_DEV", "HOTFIX_INTEGRATING_STABLE", "HOTFIX_RECONCILING_DEV", "RELEASING", "DEPLOYING", "ROLLING_BACK"}
)


@dataclass(frozen=True)
class TransitionRule:
    machine: str
    from_state: str
    event: str
    guard: tuple[str, ...]
    required_gates: tuple[str, ...]
    required_authorization: str | None
    to_state: str

    @property
    def required_gate(self) -> str | tuple[str, ...] | None:
        if not self.required_gates:
            return None
        if len(self.required_gates) == 1:
            return self.required_gates[0]
        return self.required_gates


def _truthy(name: str) -> Callable[[Mapping[str, Any]], bool]:
    return lambda context: bool(context.get(name))


GUARDS: dict[str, Callable[[Mapping[str, Any]], bool]] = {
    "always": lambda _context: True,
    "discovery_complete": _truthy("discovery_complete"),
    "review_decision_recorded": _truthy("review_decision_recorded"),
    "mode_staged": lambda context: context.get("mode") == "staged",
    "mode_auto": lambda context: context.get("mode") == "auto",
    "normal_run": lambda context: context.get("run_kind") == "normal",
    "hotfix_run": lambda context: context.get("run_kind") == "hotfix",
    "more_phases": _truthy("more_phases"),
    "more_environments": _truthy("more_environments"),
    "all_phases_done": _truthy("all_phases_done"),
    "release_required": _truthy("release_required"),
    "release_not_applicable": _truthy("release_not_applicable"),
    "deploy_required": _truthy("deploy_required"),
    "deploy_not_applicable": _truthy("deploy_not_applicable"),
    "repair_decision_recorded": _truthy("repair_decision_recorded"),
    "safe_pause_point": _truthy("safe_pause_point"),
    "actors_fenced": _truthy("actors_fenced"),
    "external_operations_reconciled": _truthy("external_operations_reconciled"),
    "failure_classified": _truthy("failure_classified"),
    "resume_state_matches": lambda context: bool(context.get("resume_state"))
    and context.get("resume_state") == context.get("recorded_resume_state"),
    "structured_result_valid": _truthy("structured_result_valid"),
    "retry_allowed": _truthy("retry_allowed"),
    "optional_task": _truthy("optional_task"),
    "mandatory_coverage_preserved": _truthy("mandatory_coverage_preserved"),
    "lease_fenced": _truthy("lease_fenced"),
    "phase_rejected": _truthy("phase_rejected"),
    "hotfix_effect_exact": _truthy("hotfix_effect_exact"),
}


def _rule(
    machine: str,
    source: str,
    event: str,
    target: str,
    *,
    guard: Iterable[str] = ("always",),
    gates: Iterable[str] = (),
    authorization: str | None = None,
) -> TransitionRule:
    return TransitionRule(
        machine=machine,
        from_state=source,
        event=event,
        guard=tuple(guard),
        required_gates=tuple(gates),
        required_authorization=authorization,
        to_state=target,
    )


def _run_rules() -> list[TransitionRule]:
    rows = [
        _rule("run", "DISCOVERING", "DRAFT_SPEC", "SPEC_DRAFT", guard=("discovery_complete",)),
        _rule("run", "SPEC_DRAFT", "SUBMIT_SPEC_REVIEW", "SPEC_REVIEW"),
        _rule("run", "SPEC_REVIEW", "REVISE_SPEC", "SPEC_DRAFT", guard=("review_decision_recorded",)),
        _rule("run", "SPEC_REVIEW", "REQUEST_SPEC_CONFIRMATION", "SPEC_AWAITING_CONFIRMATION"),
        _rule("run", "SPEC_AWAITING_CONFIRMATION", "REJECT_SPEC_CONFIRMATION", "SPEC_REVIEW", guard=("review_decision_recorded",)),
        _rule("run", "SPEC_AWAITING_CONFIRMATION", "CONFIRM_SPEC", "SPEC_CONFIRMED", gates=("SPEC_GATE",), authorization="spec_confirmation"),
        _rule("run", "SPEC_CONFIRMED", "START_PLANNING", "PLANNING"),
        _rule("run", "PLANNING", "PLAN_READY", "READY", gates=("PLAN_GATE",)),
        _rule("run", "READY", "START_IMPLEMENTATION", "IMPLEMENTING", guard=("normal_run",)),
        _rule("run", "IMPLEMENTING", "START_PHASE_VERIFICATION", "PHASE_VERIFYING"),
        _rule("run", "PHASE_VERIFYING", "AWAIT_PHASE_ACCEPTANCE", "PHASE_AWAITING_ACCEPTANCE", guard=("mode_staged",), gates=("PHASE_GATE",)),
        _rule("run", "PHASE_VERIFYING", "START_DEV_INTEGRATION", "INTEGRATING_DEV", guard=("mode_auto",), gates=("PHASE_GATE", "DEV_INTEGRATION_GATE"), authorization="integrate_dev"),
        _rule("run", "PHASE_AWAITING_ACCEPTANCE", "START_DEV_INTEGRATION", "INTEGRATING_DEV", guard=("mode_staged",), gates=("PHASE_GATE", "DEV_INTEGRATION_GATE"), authorization="integrate_dev"),
        _rule("run", "INTEGRATING_DEV", "DEV_INTEGRATION_APPLIED", "INTEGRATION_VERIFYING", gates=("DEV_INTEGRATION_GATE",), authorization="integrate_dev"),
        _rule("run", "INTEGRATION_VERIFYING", "CONTINUE_IMPLEMENTATION", "IMPLEMENTING", guard=("more_phases",), gates=("DEV_INTEGRATION_RESULT_GATE",)),
        _rule("run", "INTEGRATION_VERIFYING", "ALL_PHASES_INTEGRATED", "RELEASE_READY", guard=("all_phases_done",), gates=("DEV_INTEGRATION_RESULT_GATE",)),
        _rule("run", "PHASE_VERIFYING", "REPAIR_PHASE", "IMPLEMENTING", guard=("phase_rejected", "repair_decision_recorded")),
        _rule("run", "READY", "START_HOTFIX", "HOTFIX_IMPLEMENTING", guard=("hotfix_run",), authorization="hotfix"),
        _rule("run", "HOTFIX_IMPLEMENTING", "START_HOTFIX_VERIFICATION", "HOTFIX_VERIFYING"),
        _rule("run", "HOTFIX_VERIFYING", "START_HOTFIX_STABLE_INTEGRATION", "HOTFIX_INTEGRATING_STABLE", gates=("HOTFIX_STABLE_GATE",), authorization="hotfix_stable"),
        _rule("run", "HOTFIX_INTEGRATING_STABLE", "HOTFIX_STABLE_APPLIED", "HOTFIX_STABLE_VERIFYING", gates=("HOTFIX_STABLE_GATE",), authorization="hotfix_stable"),
        _rule("run", "HOTFIX_STABLE_VERIFYING", "START_HOTFIX_DEV_RECONCILIATION", "HOTFIX_RECONCILING_DEV", gates=("HOTFIX_STABLE_RESULT_GATE", "HOTFIX_RECONCILIATION_GATE"), authorization="hotfix_reconcile_dev"),
        _rule("run", "HOTFIX_RECONCILING_DEV", "HOTFIX_DEV_APPLIED", "HOTFIX_DEV_VERIFYING", gates=("HOTFIX_RECONCILIATION_GATE",), authorization="hotfix_reconcile_dev"),
        _rule("run", "HOTFIX_DEV_VERIFYING", "HOTFIX_RECONCILED", "RELEASE_READY", guard=("hotfix_effect_exact",), gates=("HOTFIX_RECONCILIATION_RESULT_GATE",)),
        _rule("run", "RELEASE_READY", "START_RELEASE", "RELEASING", guard=("release_required",), gates=("RELEASE_GATE",), authorization="release"),
        _rule("run", "RELEASE_READY", "SKIP_RELEASE_NOT_APPLICABLE", "RELEASE_VERIFIED", guard=("release_not_applicable",), gates=("RELEASE_GATE",)),
        _rule("run", "RELEASING", "RELEASE_OBSERVED", "RELEASE_VERIFIED", gates=("RELEASE_RESULT_GATE",)),
        _rule("run", "RELEASE_VERIFIED", "PREPARE_DEPLOYMENT", "DEPLOY_READY"),
        _rule("run", "DEPLOY_READY", "START_DEPLOYMENT", "DEPLOYING", guard=("deploy_required",), gates=("DEPLOY_GATE",), authorization="deploy"),
        _rule("run", "DEPLOY_READY", "SKIP_DEPLOY_NOT_APPLICABLE", "COMPLETED", guard=("deploy_not_applicable",), gates=("DEPLOY_GATE", "COMPLETION_GATE")),
        _rule("run", "DEPLOYING", "DEPLOYMENT_OBSERVED", "POST_DEPLOY_VERIFYING"),
        _rule("run", "POST_DEPLOY_VERIFYING", "CONTINUE_DEPLOYMENT", "DEPLOY_READY", guard=("more_environments",), gates=("POST_DEPLOY_GATE",)),
        _rule("run", "POST_DEPLOY_VERIFYING", "COMPLETE_RUN", "COMPLETED", gates=("POST_DEPLOY_GATE", "COMPLETION_GATE")),
        _rule("run", "DEPLOYING", "DEPLOYMENT_REQUIRES_ROLLBACK", "ROLLBACK_REQUIRED", guard=("external_operations_reconciled",)),
        _rule("run", "POST_DEPLOY_VERIFYING", "POST_DEPLOYMENT_FAILED", "ROLLBACK_REQUIRED", guard=("failure_classified",)),
        _rule("run", "ROLLBACK_REQUIRED", "START_ROLLBACK", "ROLLING_BACK", gates=("ROLLBACK_GATE",), authorization="rollback"),
        _rule("run", "ROLLING_BACK", "ROLLBACK_OBSERVED", "POST_ROLLBACK_VERIFYING"),
        _rule("run", "POST_ROLLBACK_VERIFYING", "ROLLBACK_VERIFIED", "ROLLED_BACK", gates=("POST_ROLLBACK_GATE",)),
    ]
    pausable = sorted(RUN_STATES - TERMINAL_RUN_STATES - {"PAUSED", "ATTENTION_REQUIRED"})
    for state in pausable:
        guards = ["safe_pause_point", "actors_fenced"]
        if state in EXTERNAL_MUTATION_STATES:
            guards.append("external_operations_reconciled")
        rows.append(_rule("run", state, "REQUEST_PAUSE", "PAUSED", guard=guards))
    rows.append(_rule("run", "PAUSED", "RESUME", RESUME_STATE, guard=("resume_state_matches", "external_operations_reconciled")))
    attention_sources = sorted(RUN_STATES - TERMINAL_RUN_STATES - {"ATTENTION_REQUIRED"})
    for state in attention_sources:
        rows.append(
            _rule(
                "run",
                state,
                "REQUIRE_ATTENTION",
                "ATTENTION_REQUIRED",
                guard=("actors_fenced",),
            )
        )
    rows.append(_rule("run", "ATTENTION_REQUIRED", "RESUME", RESUME_STATE, guard=("resume_state_matches", "external_operations_reconciled")))
    cancellable = sorted(RUN_STATES - TERMINAL_RUN_STATES)
    for state in cancellable:
        rows.append(_rule("run", state, "CANCEL", "CANCELLED", guard=("actors_fenced", "external_operations_reconciled"), authorization="cancel"))
        rows.append(_rule("run", state, "FAIL_UNRECOVERABLE", "FAILED", guard=("failure_classified", "actors_fenced", "external_operations_reconciled")))
    return rows


def _phase_rules() -> list[TransitionRule]:
    return [
        _rule("phase", "PLANNED", "START", "ACTIVE"),
        _rule("phase", "ACTIVE", "START_VERIFICATION", "VERIFYING"),
        _rule("phase", "VERIFYING", "AWAIT_ACCEPTANCE", "AWAITING_ACCEPTANCE", guard=("mode_staged",), gates=("PHASE_GATE",)),
        _rule("phase", "VERIFYING", "ACCEPT", "ACCEPTED", guard=("mode_auto",), gates=("PHASE_GATE",)),
        _rule("phase", "AWAITING_ACCEPTANCE", "ACCEPT", "ACCEPTED", guard=("mode_staged",), gates=("PHASE_GATE",), authorization="phase_accept"),
        _rule("phase", "AWAITING_ACCEPTANCE", "REJECT", "ACTIVE", guard=("phase_rejected", "repair_decision_recorded")),
        _rule("phase", "ACCEPTED", "MARK_INTEGRATED", "INTEGRATED", gates=("DEV_INTEGRATION_RESULT_GATE",)),
        _rule("phase", "ACCEPTED", "MARK_HOTFIX_INTEGRATED", "INTEGRATED", gates=("HOTFIX_RECONCILIATION_RESULT_GATE",)),
        _rule("phase", "ACTIVE", "BLOCK", "BLOCKED"),
        _rule("phase", "VERIFYING", "BLOCK", "BLOCKED"),
        _rule("phase", "ACTIVE", "CANCEL", "CANCELLED", guard=("actors_fenced",)),
        _rule("phase", "VERIFYING", "CANCEL", "CANCELLED", guard=("actors_fenced",)),
    ]


def _task_rules() -> list[TransitionRule]:
    return [
        _rule("task", "PLANNED", "MAKE_READY", "READY"),
        _rule("task", "READY", "ACQUIRE_LEASE", "LEASED"),
        _rule("task", "LEASED", "START", "RUNNING"),
        _rule("task", "RUNNING", "COLLECT_CANDIDATE", "CANDIDATE", guard=("structured_result_valid",)),
        _rule("task", "CANDIDATE", "START_VERIFICATION", "VERIFYING"),
        _rule("task", "VERIFYING", "VERIFY", "VERIFIED", gates=("TASK_GATE",)),
        _rule("task", "VERIFIED", "MARK_INTEGRATED", "INTEGRATED", gates=("PHASE_GATE",)),
        _rule("task", "RUNNING", "RETRYABLE_FAILURE", "RETRYABLE_FAILURE", guard=("retry_allowed",)),
        _rule("task", "VERIFYING", "RETRYABLE_FAILURE", "RETRYABLE_FAILURE", guard=("retry_allowed",)),
        _rule("task", "RETRYABLE_FAILURE", "REQUEUE", "READY", guard=("retry_allowed", "lease_fenced")),
        _rule("task", "RUNNING", "BLOCK", "BLOCKED"),
        _rule("task", "VERIFYING", "BLOCK", "BLOCKED"),
        _rule("task", "RUNNING", "CANCEL", "CANCELLED", guard=("actors_fenced",)),
        _rule("task", "VERIFYING", "CANCEL", "CANCELLED", guard=("actors_fenced",)),
        _rule("task", "READY", "SKIP", "SKIPPED", guard=("optional_task", "mandatory_coverage_preserved"), authorization="skip_optional"),
        _rule("task", "BLOCKED", "SKIP", "SKIPPED", guard=("optional_task", "mandatory_coverage_preserved"), authorization="skip_optional"),
        _rule("task", "LEASED", "LEASE_LOST", "READY", guard=("lease_fenced", "external_operations_reconciled")),
        _rule("task", "RUNNING", "LEASE_LOST", "READY", guard=("lease_fenced", "external_operations_reconciled")),
    ]


def _attempt_rules() -> list[TransitionRule]:
    return [
        _rule("attempt", "CREATED", "DISPATCH", "DISPATCHED"),
        _rule("attempt", "DISPATCHED", "START", "RUNNING"),
        _rule("attempt", "RUNNING", "COLLECT", "COLLECTING"),
        _rule("attempt", "COLLECTING", "SUCCEED", "SUCCEEDED", guard=("structured_result_valid",)),
        _rule("attempt", "COLLECTING", "FAIL", "FAILED"),
        _rule("attempt", "RUNNING", "TIME_OUT", "TIMED_OUT"),
        _rule("attempt", "COLLECTING", "TIME_OUT", "TIMED_OUT"),
        _rule("attempt", "DISPATCHED", "CANCEL", "CANCELLED", guard=("actors_fenced",)),
        _rule("attempt", "RUNNING", "CANCEL", "CANCELLED", guard=("actors_fenced",)),
        _rule("attempt", "COLLECTING", "CANCEL", "CANCELLED", guard=("actors_fenced",)),
        _rule("attempt", "DISPATCHED", "LOSE", "LOST", guard=("lease_fenced",)),
        _rule("attempt", "RUNNING", "LOSE", "LOST", guard=("lease_fenced",)),
        _rule("attempt", "COLLECTING", "LOSE", "LOST", guard=("lease_fenced",)),
    ]


TRANSITION_RULES = tuple(_run_rules() + _phase_rules() + _task_rules() + _attempt_rules())


class TransitionTable:
    def __init__(self, rules: Iterable[TransitionRule] = TRANSITION_RULES) -> None:
        self.version = TRANSITION_TABLE_VERSION
        self.rules = tuple(rules)
        self._index: dict[tuple[str, str, str], TransitionRule] = {}
        for rule in self.rules:
            key = (rule.machine, rule.from_state, rule.event)
            if key in self._index:
                raise TransitionError(f"duplicate transition-table row: {key}")
            if rule.machine not in {"run", "phase", "task", "attempt"}:
                raise TransitionError(f"unknown transition machine: {rule.machine}")
            for guard in rule.guard:
                if guard not in GUARDS:
                    raise TransitionError(f"unknown transition guard: {guard}")
            self._index[key] = rule

    def rule_for(self, machine: str, from_state: str, event: str) -> TransitionRule:
        try:
            return self._index[(machine, from_state, event)]
        except KeyError as exc:
            raise TransitionError(
                f"transition omitted from {self.version}: {machine} {from_state} --{event}--> ?"
            ) from exc

    def validate(
        self,
        *,
        machine: str,
        from_state: str,
        event: str,
        context: Mapping[str, Any],
    ) -> tuple[TransitionRule, str]:
        rule = self.rule_for(machine, from_state, event)
        failed = [guard for guard in rule.guard if not GUARDS[guard](context)]
        if failed:
            raise TransitionError(
                f"transition guard failed for {event}: {', '.join(failed)}"
            )
        target = rule.to_state
        if target == RESUME_STATE:
            target = str(context.get("resume_state", ""))
            allowed = {
                "run": RUN_STATES,
                "phase": PHASE_STATES,
                "task": TASK_STATES,
                "attempt": ATTEMPT_STATES,
            }[machine]
            if target not in allowed or target in TERMINAL_RUN_STATES:
                raise TransitionError(f"invalid recorded resume state: {target!r}")
        return rule, target


DEFAULT_TRANSITION_TABLE = TransitionTable()


def transition_table_document() -> dict[str, Any]:
    return {
        "schema_version": TRANSITION_TABLE_VERSION,
        "rows": [
            {
                "machine": row.machine,
                "from_state": row.from_state,
                "event": row.event,
                "guard": list(row.guard),
                "required_gate": list(row.required_gates),
                "required_authorization": row.required_authorization,
                "to_state": row.to_state,
            }
            for row in TRANSITION_RULES
        ],
    }
