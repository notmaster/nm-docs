"""Data-driven evidence-backed V6 gate evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .errors import ContractError, EvidenceError
from .evidence import (
    BOUND_DIGEST_PATTERN,
    EVIDENCE_SCHEMA_VERSION,
    REQUIRED_RECEIPT_FIELDS,
    SHA256_PATTERN,
)
from .models import GateObservation
from .util import (
    canonical_json,
    reject_unknown_keys,
    require_keys,
    sha256_bytes,
    utc_now,
)


GATE_SCHEMA_VERSION = "nm-v6/gate-decision-v1"
GATE_VERSION = "nm-v6/gates-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

GATE_DECISION_FIELDS = frozenset(
    {
        "schema_version",
        "gate_id",
        "gate_type",
        "gate_version",
        "run_id",
        "subject_ids",
        "spec_hash",
        "config_hash",
        "source_commit",
        "candidate_commit",
        "target_commit",
        "release_source_kind",
        "release_source_commit",
        "release_source_tree",
        "hotfix_reconciliation_gate_id",
        "artifact_digest",
        "environment_id",
        "environment_fingerprint",
        "prerequisite_decision_ids",
        "evidence_ids",
        "prerequisite_evidence",
        "mandatory_acceptance_ids",
        "acceptance_evidence",
        "authorization_id",
        "evaluator",
        "evaluator_version",
        "result",
        "reason",
        "timestamp",
        "run_revision",
        "evaluated_prerequisites",
        "decision_digest",
    }
)

_EVIDENCE_BINDING_FIELDS = (
    "source_commit",
    "candidate_commit",
    "release_source_kind",
    "release_source_commit",
    "release_source_tree",
    "hotfix_reconciliation_gate_id",
    "artifact_digest",
    "environment_id",
    "environment_fingerprint",
)

GATE_REQUIRED_BINDINGS: dict[str, tuple[str, ...]] = {
    "TASK_GATE": ("candidate_commit",),
    "PHASE_GATE": ("candidate_commit",),
    "DEV_INTEGRATION_GATE": ("candidate_commit", "target_commit"),
    "DEV_INTEGRATION_RESULT_GATE": ("candidate_commit", "target_commit"),
    "HOTFIX_STABLE_GATE": ("candidate_commit", "target_commit"),
    "HOTFIX_STABLE_RESULT_GATE": (
        "source_commit",
        "candidate_commit",
        "target_commit",
    ),
    "HOTFIX_RECONCILIATION_GATE": ("candidate_commit", "target_commit"),
    "HOTFIX_RECONCILIATION_RESULT_GATE": (
        "source_commit",
        "candidate_commit",
        "target_commit",
    ),
    "RELEASE_GATE": (
        "source_commit",
        "target_commit",
        "release_source_kind",
        "release_source_commit",
        "release_source_tree",
        "artifact_digest",
    ),
    "RELEASE_RESULT_GATE": (
        "source_commit",
        "candidate_commit",
        "release_source_kind",
        "release_source_commit",
        "release_source_tree",
        "artifact_digest",
    ),
    "DEPLOY_GATE": (
        "artifact_digest",
        "environment_id",
        "environment_fingerprint",
    ),
    "POST_DEPLOY_GATE": (
        "artifact_digest",
        "environment_id",
        "environment_fingerprint",
    ),
    "ROLLBACK_GATE": (
        "artifact_digest",
        "environment_id",
        "environment_fingerprint",
    ),
    "POST_ROLLBACK_GATE": (
        "artifact_digest",
        "environment_id",
        "environment_fingerprint",
    ),
}


@dataclass(frozen=True)
class GateDefinition:
    prerequisites: tuple[str, ...]
    authorization_required: bool = False
    not_applicable_allowed: bool = False


GATE_DEFINITIONS: dict[str, GateDefinition] = {
    "SPEC_GATE": GateDefinition(("schema_valid", "ids_unique", "stage_annotations_valid", "mandatory_traceability_complete", "canonical_spec_hash_valid", "trusted_confirmation_valid")),
    "PLAN_GATE": GateDefinition(("task_dag_valid", "mandatory_acceptance_covered", "path_bounds_declared", "actions_declared", "dependencies_declared", "write_sets_declared")),
    "TASK_GATE": GateDefinition(("candidate_diff_allowed", "candidate_commit_identified", "task_acceptance_rerun_passed", "no_prohibited_mutation")),
    "PHASE_GATE": GateDefinition(("mandatory_phase_tasks_verified", "skips_permitted", "phase_verification_passed")),
    "DEV_INTEGRATION_GATE": GateDefinition(("target_is_dev", "candidate_lineage_allowed", "expected_target_unchanged", "simulated_result_tree_valid", "merge_proposal_valid", "full_verification_passed"), authorization_required=True),
    "DEV_INTEGRATION_RESULT_GATE": GateDefinition(("observed_local_ref_matches", "observed_remote_ref_matches", "result_tree_matches", "push_receipt_valid", "post_update_checks_passed")),
    "HOTFIX_STABLE_GATE": GateDefinition(("trusted_hotfix_authorization_present", "hotfix_base_matches_stable", "simulated_result_tree_valid", "merge_proposal_valid", "independent_verification_passed", "rollback_ref_recorded", "expected_target_unchanged"), authorization_required=True),
    "HOTFIX_STABLE_RESULT_GATE": GateDefinition(("observed_local_ref_matches", "observed_remote_ref_matches", "authorized_cas_result_matches", "push_receipt_valid", "result_tree_matches", "post_update_checks_passed")),
    "HOTFIX_RECONCILIATION_GATE": GateDefinition(("exact_hotfix_effect_present", "expected_dev_unchanged", "affected_verification_passed", "merge_proposal_valid"), authorization_required=True),
    "HOTFIX_RECONCILIATION_RESULT_GATE": GateDefinition(("observed_local_ref_matches", "observed_remote_ref_matches", "authorized_cas_result_matches", "push_receipt_valid", "exact_hotfix_effect_present", "result_tree_matches", "post_update_checks_passed")),
    "RELEASE_GATE": GateDefinition(("release_source_fixed", "release_acceptance_covered", "immutable_artifact_valid", "stable_result_tree_valid", "merge_proposal_valid", "release_metadata_valid", "idempotency_present", "observe_reconcile_ready", "rollback_target_recorded", "hotfix_reconciliation_valid_or_not_applicable"), authorization_required=True, not_applicable_allowed=True),
    "RELEASE_RESULT_GATE": GateDefinition(("stable_ref_observed", "source_binding_observed", "tag_observed", "tag_target_matches_stable", "published_release_observed", "release_metadata_matches", "release_effect_observed", "publish_effect_observed", "artifact_digest_matches", "partial_unknown_reconciled"), not_applicable_allowed=True),
    "DEPLOY_GATE": GateDefinition(("deploy_acceptance_covered", "artifact_fixed", "environment_confirmed", "credentials_are_references", "preflight_passed", "idempotency_present", "observe_reconcile_ready", "rollback_ready"), authorization_required=True, not_applicable_allowed=True),
    "POST_DEPLOY_GATE": GateDefinition(("health_passed", "smoke_passed", "project_observations_passed", "artifact_environment_binding_valid"), not_applicable_allowed=True),
    "ROLLBACK_GATE": GateDefinition(("rollback_target_exists", "environment_confirmed", "rollback_action_available", "post_rollback_verification_available"), authorization_required=True),
    "POST_ROLLBACK_GATE": GateDefinition(("observed_environment_equals_rollback_target", "post_rollback_verification_passed", "branch_cleanup_resolved", "terminal_resources_closed", "no_remote_cleanup_effect")),
    "COMPLETION_GATE": GateDefinition(("mandatory_acceptance_complete", "all_phases_integrated", "release_resolved", "deployment_resolved", "no_mandatory_work_remaining", "no_rollback_responsibility", "branch_cleanup_resolved", "terminal_resources_closed", "no_remote_cleanup_effect")),
}

NOT_APPLICABLE_PREREQUISITES = (
    "spec_explicitly_not_applicable",
    "stage_traceability_valid",
    "not_applicable_decision_valid",
)


class GateEvaluator:
    """Evaluate immutable observations without writing workflow state."""

    def __init__(
        self,
        evidence_resolver: Callable[[str], Mapping[str, Any] | None] | None = None,
        *,
        evidence_validator: Callable[[Mapping[str, Any]], bool | None] | None = None,
        evaluator_version: str = "nm-v6-core/gates-v1",
    ) -> None:
        self._evidence_resolver = evidence_resolver
        self._evidence_validator = evidence_validator
        self.evaluator_version = evaluator_version

    def evaluate(
        self,
        observation: GateObservation,
        *,
        gate_id: str,
        spec_hash: str,
        config_hash: str,
        run_revision: int,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        definition = GATE_DEFINITIONS.get(observation.gate_type)
        if definition is None:
            raise ContractError(f"unknown V6 gate type: {observation.gate_type!r}")
        if not isinstance(gate_id, str) or not gate_id:
            raise ContractError("gate_id must be nonempty")
        if (
            isinstance(run_revision, bool)
            or not isinstance(run_revision, int)
            or run_revision < 0
        ):
            raise ContractError("gate_id must be nonempty and run_revision nonnegative")
        if not _SHA256.fullmatch(spec_hash) or not _SHA256.fullmatch(config_hash):
            raise ContractError("gate Spec/config hashes must be lowercase SHA-256 digests")
        if (
            not observation.subject_ids
            or not all(
                isinstance(subject_id, str) and subject_id
                for subject_id in observation.subject_ids
            )
            or len(observation.subject_ids) != len(set(observation.subject_ids))
        ):
            raise ContractError("gate subject_ids must be nonempty and unique")
        if not isinstance(observation.evaluator, str) or not observation.evaluator:
            raise ContractError("gate evaluator identity must be nonempty")
        if observation.authorization_id is not None and (
            not isinstance(observation.authorization_id, str)
            or not observation.authorization_id
        ):
            raise ContractError("gate authorization_id must be nonempty or null")
        facts = dict(observation.context)
        if context:
            facts.update(context)
        requested_not_applicable = facts.get("not_applicable") is True
        failures: list[str] = []
        if requested_not_applicable:
            if not definition.not_applicable_allowed:
                failures.append("not_applicable is forbidden for this gate")
                prerequisite_names = definition.prerequisites
            else:
                prerequisite_names = NOT_APPLICABLE_PREREQUISITES
        else:
            prerequisite_names = definition.prerequisites
        for prerequisite in prerequisite_names:
            if facts.get(prerequisite) is not True:
                failures.append(f"missing or false prerequisite: {prerequisite}")

        evidence_ids = tuple(observation.evidence_ids)
        if not all(isinstance(item, str) and item for item in evidence_ids):
            raise ContractError("gate evidence_ids must contain nonempty strings")
        if len(evidence_ids) != len(set(evidence_ids)):
            failures.append("gate evidence_ids must be unique")
        prerequisite_evidence = _normalize_prerequisite_evidence(
            facts.get("prerequisite_evidence"),
            prerequisite_names=prerequisite_names,
            evidence_ids=evidence_ids,
            failures=failures,
        )

        if (
            definition.authorization_required
            and not requested_not_applicable
            and not observation.authorization_id
        ):
            failures.append("trusted authorization is required")
        if not evidence_ids:
            failures.append("a passed gate must cite evidence")
        if self._evidence_resolver is None or self._evidence_validator is None:
            failures.append(
                "a passed gate requires the canonical resolver and core evidence validator"
            )

        run_id = facts.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            failures.append("a passed gate must bind a persisted run_id")
        _validate_decision_binding_completeness(
            observation.gate_type,
            facts,
            requested_not_applicable=requested_not_applicable,
            failures=failures,
        )

        evidence_contract = {
            "gate_type": observation.gate_type,
            "result": (
                "not_applicable" if requested_not_applicable else "passed"
            ),
            "run_id": run_id,
            "spec_hash": spec_hash,
            "config_hash": config_hash,
            "source_commit": facts.get("source_commit"),
            "candidate_commit": facts.get("candidate_commit"),
            "release_source_kind": facts.get("release_source_kind"),
            "release_source_commit": facts.get("release_source_commit"),
            "release_source_tree": facts.get("release_source_tree"),
            "hotfix_reconciliation_gate_id": facts.get(
                "hotfix_reconciliation_gate_id"
            ),
            "artifact_digest": facts.get("artifact_digest"),
            "environment_id": facts.get("environment_id"),
            "environment_fingerprint": facts.get("environment_fingerprint"),
            "evidence_ids": list(evidence_ids),
            "evaluated_prerequisites": list(prerequisite_names),
            "prerequisite_evidence": prerequisite_evidence,
            "mandatory_acceptance_ids": facts.get("mandatory_acceptance_ids", []),
            "acceptance_evidence": facts.get("acceptance_evidence", {}),
        }
        failures.extend(
            _gate_evidence_binding_failures(
                evidence_contract,
                self._evidence_resolver,
                self._evidence_validator,
            )
        )
        failures = list(dict.fromkeys(failures))

        mandatory_acceptance_ids = facts.get("mandatory_acceptance_ids", [])
        if not isinstance(mandatory_acceptance_ids, (list, tuple)):
            mandatory_acceptance_ids = []
        acceptance_evidence = facts.get("acceptance_evidence", {})
        if not isinstance(acceptance_evidence, Mapping):
            acceptance_evidence = {}

        result = "failed"
        if not failures:
            result = "not_applicable" if requested_not_applicable else "passed"
        reason = "; ".join(failures) if failures else str(
            facts.get("reason", "all gate prerequisites and evidence are valid")
        )
        decision = {
            "schema_version": GATE_SCHEMA_VERSION,
            "gate_id": gate_id,
            "gate_type": observation.gate_type,
            "gate_version": GATE_VERSION,
            "run_id": facts.get("run_id"),
            "subject_ids": list(observation.subject_ids),
            "spec_hash": spec_hash,
            "config_hash": config_hash,
            "source_commit": facts.get("source_commit"),
            "candidate_commit": facts.get("candidate_commit"),
            "target_commit": facts.get("target_commit"),
            "release_source_kind": facts.get("release_source_kind"),
            "release_source_commit": facts.get("release_source_commit"),
            "release_source_tree": facts.get("release_source_tree"),
            "hotfix_reconciliation_gate_id": facts.get(
                "hotfix_reconciliation_gate_id"
            ),
            "artifact_digest": facts.get("artifact_digest"),
            "environment_id": facts.get("environment_id"),
            "environment_fingerprint": facts.get("environment_fingerprint"),
            "prerequisite_decision_ids": list(
                facts.get("prerequisite_decision_ids", [])
            ),
            "evidence_ids": list(evidence_ids),
            "prerequisite_evidence": prerequisite_evidence,
            "mandatory_acceptance_ids": list(mandatory_acceptance_ids),
            "acceptance_evidence": dict(acceptance_evidence),
            "authorization_id": observation.authorization_id,
            "evaluator": observation.evaluator,
            "evaluator_version": self.evaluator_version,
            "result": result,
            "reason": reason,
            "timestamp": str(facts.get("timestamp", utc_now())),
            "run_revision": run_revision,
            "evaluated_prerequisites": list(prerequisite_names),
        }
        decision["decision_digest"] = sha256_bytes(canonical_json(decision))
        return decision


def _normalize_prerequisite_evidence(
    raw: Any,
    *,
    prerequisite_names: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    failures: list[str],
    require_complete: bool = True,
) -> dict[str, list[str]]:
    if not isinstance(raw, Mapping):
        failures.append("prerequisite_evidence must be an object")
        return {}
    required = set(prerequisite_names)
    cited = set(evidence_ids)
    normalized: dict[str, list[str]] = {}
    for prerequisite, value in raw.items():
        if not isinstance(prerequisite, str) or prerequisite not in required:
            failures.append(f"unknown prerequisite_evidence key: {prerequisite!r}")
            continue
        if (
            not isinstance(value, (list, tuple))
            or not value
            or not all(isinstance(item, str) and item for item in value)
            or len(value) != len(set(value))
        ):
            failures.append(
                f"prerequisite_evidence for {prerequisite} must be a nonempty "
                "unique evidence ID array"
            )
            continue
        identifiers = list(value)
        unknown = sorted(set(identifiers) - cited)
        if unknown:
            failures.append(
                f"prerequisite_evidence for {prerequisite} cites unlisted evidence: "
                + ", ".join(unknown)
            )
            continue
        normalized[prerequisite] = identifiers
    if require_complete:
        for prerequisite in prerequisite_names:
            if prerequisite not in normalized:
                failures.append(f"prerequisite lacks cited evidence: {prerequisite}")
    # Gates may carry upstream receipts solely to preserve an unbroken
    # evidence chain.  They need not restate this gate's prerequisites, but
    # every listed receipt is still resolved, fully validated, and binding-
    # checked below.
    return {
        prerequisite: normalized[prerequisite]
        for prerequisite in prerequisite_names
        if prerequisite in normalized
    }


def _validate_full_evidence_receipt(
    receipt: Mapping[str, Any] | None,
    *,
    evidence_id: str,
) -> None:
    if not isinstance(receipt, Mapping):
        raise EvidenceError("persisted evidence resolver did not return a receipt")
    required = set(REQUIRED_RECEIPT_FIELDS) | {"schema_version"}
    missing = sorted(required - set(receipt))
    if missing:
        raise EvidenceError(
            "persisted evidence receipt is incomplete: " + ", ".join(missing)
        )
    if receipt["schema_version"] != EVIDENCE_SCHEMA_VERSION:
        raise EvidenceError("unsupported persisted evidence receipt version")
    if receipt["evidence_id"] != evidence_id:
        raise EvidenceError("persisted evidence receipt ID mismatch")
    if receipt["result"] not in {
        "passed",
        "failed",
        "partial",
        "unknown",
        "not_applicable",
    }:
        raise EvidenceError("persisted evidence receipt has an invalid result")
    for field in ("spec_hash", "config_hash", "argv_digest"):
        if not isinstance(receipt[field], str) or not SHA256_PATTERN.fullmatch(
            receipt[field]
        ):
            raise EvidenceError(f"persisted evidence {field} is invalid")
    for field in ("stdout_digest", "stderr_digest"):
        if not isinstance(receipt[field], str) or not SHA256_PATTERN.fullmatch(
            receipt[field]
        ):
            raise EvidenceError(f"persisted evidence {field} is invalid")
    if not isinstance(receipt["subject_ids"], list) or not receipt["subject_ids"]:
        raise EvidenceError("persisted evidence subject_ids are invalid")
    if not isinstance(receipt["assertions"], Mapping) or not all(
        isinstance(name, str)
        and bool(name)
        and isinstance(value, bool)
        for name, value in receipt["assertions"].items()
    ):
        raise EvidenceError("persisted evidence assertions are invalid")
    if not all(
        isinstance(item, str) and item for item in receipt["subject_ids"]
    ):
        raise EvidenceError("persisted evidence subject_ids are invalid")
    for field in (
        "evidence_type",
        "producer",
        "run_id",
        "working_directory",
        "started_at",
        "finished_at",
        "producer_version",
        "evaluator_version",
        "redaction_version",
    ):
        if not isinstance(receipt[field], str) or not receipt[field]:
            raise EvidenceError(f"persisted evidence {field} is invalid")
    for field in _EVIDENCE_BINDING_FIELDS + (
        "operation_id",
        "attempt_id",
        "command_action_id",
    ):
        if receipt[field] is not None and (
            not isinstance(receipt[field], str) or not receipt[field]
        ):
            raise EvidenceError(f"persisted evidence {field} is invalid")
    release_source_kind = receipt["release_source_kind"]
    if release_source_kind not in {None, "dev", "hotfix_stable"}:
        raise EvidenceError("persisted evidence release_source_kind is invalid")
    if release_source_kind is not None:
        for field in (
            "release_source_commit",
            "release_source_tree",
            "artifact_digest",
        ):
            if not receipt[field]:
                raise EvidenceError(f"release evidence requires {field}")
    if (
        release_source_kind == "hotfix_stable"
        and not receipt["hotfix_reconciliation_gate_id"]
    ):
        raise EvidenceError("hotfix release evidence requires reconciliation")
    if receipt["artifact_digest"] is not None and not BOUND_DIGEST_PATTERN.fullmatch(
        receipt["artifact_digest"]
    ):
        raise EvidenceError("persisted evidence artifact_digest is invalid")
    if receipt["environment_id"] is not None and (
        not receipt["environment_fingerprint"] or not receipt["artifact_digest"]
    ):
        raise EvidenceError("environment evidence lacks artifact/fingerprint binding")
    if not isinstance(receipt["tool_versions"], dict):
        raise EvidenceError("persisted evidence tool_versions is invalid")
    if isinstance(receipt["exit_code"], bool) or not isinstance(
        receipt["exit_code"], int
    ):
        raise EvidenceError("persisted evidence exit_code is invalid")
    canonical_json(dict(receipt))


def validate_gate_evidence_bindings(
    decision: Mapping[str, Any],
    evidence_resolver: Callable[[str], Mapping[str, Any] | None] | None,
    evidence_validator: Callable[[Mapping[str, Any]], bool | None] | None = None,
) -> None:
    """Revalidate successful gate evidence from persisted receipts.

    Reducers call this at the transactional persistence/transition boundary so a
    caller cannot bypass :class:`GateEvaluator` with a hand-built decision.
    """

    failures = _gate_evidence_binding_failures(
        decision,
        evidence_resolver,
        evidence_validator,
    )
    if failures:
        raise EvidenceError("; ".join(failures))


def _gate_evidence_binding_failures(
    decision: Mapping[str, Any],
    evidence_resolver: Callable[[str], Mapping[str, Any] | None] | None,
    evidence_validator: Callable[[Mapping[str, Any]], bool | None] | None,
) -> list[str]:
    if decision.get("result") not in {"passed", "not_applicable"}:
        return []
    required = {
        "result",
        "run_id",
        "spec_hash",
        "config_hash",
        "evidence_ids",
        "evaluated_prerequisites",
        "prerequisite_evidence",
        *_EVIDENCE_BINDING_FIELDS,
    }
    missing = sorted(required - set(decision))
    if missing:
        return ["gate evidence contract missing fields: " + ", ".join(missing)]
    evidence_ids_raw = decision["evidence_ids"]
    prerequisites_raw = decision["evaluated_prerequisites"]
    if not isinstance(evidence_ids_raw, (list, tuple)) or not all(
        isinstance(item, str) and item for item in evidence_ids_raw
    ):
        return ["gate evidence_ids are invalid"]
    if not isinstance(prerequisites_raw, (list, tuple)) or not all(
        isinstance(item, str) and item for item in prerequisites_raw
    ):
        return ["gate evaluated_prerequisites are invalid"]
    evidence_ids = tuple(evidence_ids_raw)
    prerequisites = tuple(prerequisites_raw)
    failures: list[str] = []
    prerequisite_evidence = _normalize_prerequisite_evidence(
        decision["prerequisite_evidence"],
        prerequisite_names=prerequisites,
        evidence_ids=evidence_ids,
        failures=failures,
    )
    binding_evidence = {
        evidence_id
        for identifiers in prerequisite_evidence.values()
        for evidence_id in identifiers
    }
    resolved: dict[str, Mapping[str, Any]] = {}
    for evidence_id in evidence_ids:
        receipt: Mapping[str, Any] | None = None
        if evidence_resolver is not None:
            try:
                receipt = evidence_resolver(evidence_id)
                _validate_full_evidence_receipt(receipt, evidence_id=evidence_id)
                if evidence_validator is not None:
                    validator_result = evidence_validator(receipt)
                    if validator_result is False:
                        raise EvidenceError("receipt validator rejected evidence")
            except Exception:  # fail closed at the persisted receipt boundary
                receipt = None
        if receipt is None:
            failures.append(f"invalid evidence: {evidence_id}")
            continue
        resolved[evidence_id] = receipt
        expected_results = (
            {"passed", "not_applicable"}
            if decision["result"] == "not_applicable"
            else {"passed"}
        )
        if receipt["result"] not in expected_results:
            failures.append(f"evidence result is not gate-satisfying: {evidence_id}")
        if receipt["run_id"] != decision["run_id"]:
            failures.append(f"evidence run binding mismatch: {evidence_id}")
        if receipt["spec_hash"] != decision["spec_hash"]:
            failures.append(f"evidence Spec binding mismatch: {evidence_id}")
        if receipt["config_hash"] != decision["config_hash"]:
            failures.append(f"evidence config binding mismatch: {evidence_id}")
        for field in _EVIDENCE_BINDING_FIELDS:
            expected = decision.get(field)
            if (
                evidence_id in binding_evidence
                and expected is not None
                and receipt.get(field) != expected
            ):
                failures.append(f"evidence {field} binding mismatch: {evidence_id}")
    for prerequisite, identifiers in prerequisite_evidence.items():
        for evidence_id in identifiers:
            receipt = resolved.get(evidence_id)
            if receipt is not None and receipt["assertions"].get(prerequisite) is not True:
                failures.append(
                    f"evidence {evidence_id} has no passing core assertion for prerequisite: "
                    f"{prerequisite}"
                )
    if decision.get("gate_type") == "COMPLETION_GATE":
        mandatory = decision.get("mandatory_acceptance_ids")
        if (
            not isinstance(mandatory, (list, tuple))
            or not mandatory
            or not all(
                isinstance(item, str)
                and re.fullmatch(r"(?:V6-)?AC-[0-9]{3}", item)
                for item in mandatory
            )
            or len(mandatory) != len(set(mandatory))
        ):
            failures.append(
                "COMPLETION_GATE requires unique mandatory Acceptance IDs"
            )
        else:
            acceptance_evidence = _normalize_acceptance_evidence(
                decision.get("acceptance_evidence"),
                acceptance_ids=tuple(mandatory),
                evidence_ids=evidence_ids,
                failures=failures,
            )
            for acceptance_id, identifiers in acceptance_evidence.items():
                assertion = f"acceptance:{acceptance_id}"
                for evidence_id in identifiers:
                    receipt = resolved.get(evidence_id)
                    if (
                        receipt is not None
                        and receipt["assertions"].get(assertion) is not True
                    ):
                        failures.append(
                            f"evidence {evidence_id} has no passing core assertion "
                            f"for mandatory Acceptance criterion: {acceptance_id}"
                        )
    return list(dict.fromkeys(failures))


def _normalize_acceptance_evidence(
    raw: Any,
    *,
    acceptance_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    failures: list[str],
) -> dict[str, list[str]]:
    if not isinstance(raw, Mapping):
        failures.append("acceptance_evidence must be an object")
        return {}
    accepted = set(acceptance_ids)
    cited = set(evidence_ids)
    normalized: dict[str, list[str]] = {}
    for acceptance_id, value in raw.items():
        if acceptance_id not in accepted:
            failures.append(
                f"unknown acceptance_evidence key: {acceptance_id!r}"
            )
            continue
        if (
            not isinstance(value, (list, tuple))
            or not value
            or not all(isinstance(item, str) and item for item in value)
            or len(value) != len(set(value))
        ):
            failures.append(
                f"acceptance_evidence for {acceptance_id} must be a nonempty "
                "unique evidence ID array"
            )
            continue
        identifiers = list(value)
        if set(identifiers) - cited:
            failures.append(
                f"acceptance_evidence for {acceptance_id} cites unlisted evidence"
            )
            continue
        normalized[acceptance_id] = identifiers
    for acceptance_id in acceptance_ids:
        if acceptance_id not in normalized:
            failures.append(
                f"mandatory Acceptance criterion lacks evidence: {acceptance_id}"
            )
    return normalized


def _validate_decision_binding_completeness(
    gate_type: str,
    facts: Mapping[str, Any],
    *,
    requested_not_applicable: bool,
    failures: list[str],
) -> None:
    if not requested_not_applicable:
        for field in GATE_REQUIRED_BINDINGS.get(gate_type, ()):
            if not isinstance(facts.get(field), str) or not facts[field]:
                failures.append(f"{gate_type} requires {field}")
    if gate_type in {"RELEASE_GATE", "RELEASE_RESULT_GATE"} and not requested_not_applicable:
        if facts.get("release_source_kind") not in {"dev", "hotfix_stable"}:
            failures.append("RELEASE_GATE release_source_kind is invalid")
        if (
            facts.get("source_commit")
            and facts.get("release_source_commit")
            and facts["source_commit"] != facts["release_source_commit"]
        ):
            failures.append(
                f"{gate_type} source_commit must equal release_source_commit"
            )
        if (
            facts.get("release_source_kind") == "hotfix_stable"
            and not facts.get("hotfix_reconciliation_gate_id")
        ):
            failures.append(
                f"{gate_type} hotfix source requires hotfix_reconciliation_gate_id"
            )
    if facts.get("release_source_kind") is not None:
        for field in (
            "release_source_commit",
            "release_source_tree",
            "artifact_digest",
        ):
            if not facts.get(field):
                failures.append(f"release binding requires {field}")
    environment_bound = facts.get("environment_id") is not None or facts.get(
        "environment_fingerprint"
    ) is not None
    if environment_bound:
        if not facts.get("environment_id"):
            failures.append("environment binding requires environment_id")
        if not facts.get("environment_fingerprint"):
            failures.append("environment binding requires environment_fingerprint")
        if not facts.get("artifact_digest"):
            failures.append("environment binding requires artifact_digest")


def validate_gate_decision(decision: Mapping[str, Any]) -> None:
    if not isinstance(decision, Mapping):
        raise ContractError("gate decision must be an object")
    require_keys(decision, GATE_DECISION_FIELDS, subject="gate decision")
    reject_unknown_keys(decision, GATE_DECISION_FIELDS, subject="gate decision")
    if decision["schema_version"] != GATE_SCHEMA_VERSION:
        raise ContractError("unsupported gate decision schema")
    if decision["gate_version"] != GATE_VERSION:
        raise ContractError("unsupported gate definition version")
    if decision["gate_type"] not in GATE_DEFINITIONS:
        raise ContractError("unknown gate decision type")
    if decision["result"] not in {"passed", "failed", "not_applicable"}:
        raise ContractError("invalid gate result")
    if not isinstance(decision["gate_id"], str) or not decision["gate_id"]:
        raise ContractError("gate_id must be nonempty")
    if decision["run_id"] is not None and (
        not isinstance(decision["run_id"], str) or not decision["run_id"]
    ):
        raise ContractError("gate run_id must be a nonempty string or null")
    for field in ("spec_hash", "config_hash"):
        if not isinstance(decision[field], str) or not _SHA256.fullmatch(
            decision[field]
        ):
            raise ContractError(f"gate {field} must be a lowercase SHA-256 digest")
    if (
        not isinstance(decision["subject_ids"], list)
        or not decision["subject_ids"]
        or not all(
            isinstance(item, str) and item for item in decision["subject_ids"]
        )
        or len(decision["subject_ids"]) != len(set(decision["subject_ids"]))
    ):
        raise ContractError("gate subject_ids must be nonempty and unique")
    for field in (
        "source_commit",
        "candidate_commit",
        "target_commit",
        "release_source_commit",
        "release_source_tree",
        "hotfix_reconciliation_gate_id",
        "artifact_digest",
        "environment_id",
        "environment_fingerprint",
        "authorization_id",
    ):
        if decision[field] is not None and (
            not isinstance(decision[field], str) or not decision[field]
        ):
            raise ContractError(f"gate {field} must be a nonempty string or null")
    if decision["release_source_kind"] not in {None, "dev", "hotfix_stable"}:
        raise ContractError("gate release_source_kind is invalid")
    if decision["artifact_digest"] is not None and not BOUND_DIGEST_PATTERN.fullmatch(
        decision["artifact_digest"]
    ):
        raise ContractError("gate artifact_digest must be SHA-256 when present")
    for field in ("prerequisite_decision_ids", "evidence_ids"):
        if (
            not isinstance(decision[field], list)
            or not all(isinstance(item, str) and item for item in decision[field])
            or len(decision[field]) != len(set(decision[field]))
        ):
            raise ContractError(f"gate {field} must contain unique nonempty strings")
    if not isinstance(decision["evaluated_prerequisites"], list) or not all(
        isinstance(item, str) and item
        for item in decision["evaluated_prerequisites"]
    ):
        raise ContractError("evaluated_prerequisites must be a string array")
    evaluated = tuple(decision["evaluated_prerequisites"])
    if len(evaluated) != len(set(evaluated)):
        raise ContractError("evaluated_prerequisites contains duplicates")
    expected_prerequisites = (
        NOT_APPLICABLE_PREREQUISITES
        if decision["result"] == "not_applicable"
        else GATE_DEFINITIONS[str(decision["gate_type"])].prerequisites
    )
    if decision["result"] in {"passed", "not_applicable"} and evaluated != tuple(
        expected_prerequisites
    ):
        raise ContractError("successful gate evaluated the wrong prerequisites")
    mapping_failures: list[str] = []
    normalized = _normalize_prerequisite_evidence(
        decision["prerequisite_evidence"],
        prerequisite_names=evaluated,
        evidence_ids=tuple(decision["evidence_ids"]),
        failures=mapping_failures,
        require_complete=decision["result"] in {"passed", "not_applicable"},
    )
    if mapping_failures or normalized != decision["prerequisite_evidence"]:
        raise ContractError(
            "invalid gate prerequisite_evidence: " + "; ".join(mapping_failures)
        )
    mandatory = decision["mandatory_acceptance_ids"]
    acceptance_mapping = decision["acceptance_evidence"]
    if decision["gate_type"] == "COMPLETION_GATE":
        acceptance_failures: list[str] = []
        if (
            not isinstance(mandatory, list)
            or not mandatory
            or not all(
                isinstance(item, str)
                and re.fullmatch(r"(?:V6-)?AC-[0-9]{3}", item)
                for item in mandatory
            )
            or len(mandatory) != len(set(mandatory))
        ):
            acceptance_failures.append(
                "COMPLETION_GATE mandatory_acceptance_ids are invalid"
            )
        else:
            normalized_acceptance = _normalize_acceptance_evidence(
                acceptance_mapping,
                acceptance_ids=tuple(mandatory),
                evidence_ids=tuple(decision["evidence_ids"]),
                failures=acceptance_failures,
            )
            if normalized_acceptance != acceptance_mapping:
                acceptance_failures.append(
                    "acceptance_evidence is not canonical"
                )
        if acceptance_failures:
            raise ContractError("; ".join(acceptance_failures))
    elif mandatory != [] or acceptance_mapping != {}:
        raise ContractError(
            "non-completion gate cannot claim mandatory Acceptance coverage"
        )
    if decision["result"] in {"passed", "not_applicable"}:
        if not decision["run_id"]:
            raise ContractError("successful gate lacks run_id")
        if not decision["evidence_ids"]:
            raise ContractError("successful gate lacks evidence")
    if (
        decision["result"] in {"passed", "not_applicable"}
        and GATE_DEFINITIONS[str(decision["gate_type"])].authorization_required
        and decision["result"] != "not_applicable"
        and not decision["authorization_id"]
    ):
        raise ContractError("passed mutation gate lacks trusted authorization")
    binding_failures: list[str] = []
    _validate_decision_binding_completeness(
        str(decision["gate_type"]),
        decision,
        requested_not_applicable=decision["result"] == "not_applicable",
        failures=binding_failures,
    )
    if decision["result"] in {"passed", "not_applicable"} and binding_failures:
        raise ContractError("invalid gate bindings: " + "; ".join(binding_failures))
    if isinstance(decision["run_revision"], bool) or not isinstance(
        decision["run_revision"], int
    ) or decision["run_revision"] < 0:
        raise ContractError("gate run_revision must be a nonnegative integer")
    for field in ("evaluator", "evaluator_version", "reason", "timestamp"):
        if not isinstance(decision[field], str) or not decision[field]:
            raise ContractError(f"gate {field} must be nonempty")
    material = dict(decision)
    supplied_digest = material.pop("decision_digest")
    if not isinstance(supplied_digest, str) or not _SHA256.fullmatch(supplied_digest):
        raise ContractError("gate decision_digest must be a lowercase SHA-256 digest")
    if sha256_bytes(canonical_json(material)) != supplied_digest:
        raise ContractError("gate decision digest mismatch")


def required_prerequisites(gate_type: str) -> tuple[str, ...]:
    try:
        return GATE_DEFINITIONS[gate_type].prerequisites
    except KeyError as exc:
        raise ContractError(f"unknown V6 gate type: {gate_type!r}") from exc


def required_bindings(gate_type: str) -> tuple[str, ...]:
    if gate_type not in GATE_DEFINITIONS:
        raise ContractError(f"unknown V6 gate type: {gate_type!r}")
    return GATE_REQUIRED_BINDINGS.get(gate_type, ())
