"""Provider-neutral merge-review contracts and deterministic fake decisions."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .context import ContextItem
from .contracts import (
    adapter_result_to_dict,
    validate_adapter_request,
    validate_adapter_result,
    validate_context_manifest,
)
from .errors import ContractError
from .util import canonical_json, reject_unknown_keys, require_keys, sha256_bytes


REQUEST_SCHEMA_VERSION = "nm-v6/merge-review-request-v1"
OBSERVATION_SCHEMA_VERSION = "nm-v6/merge-review-observation-v1"
MERGE_ROUTES = (
    "work_to_dev",
    "dev_to_stable",
    "hotfix_to_stable",
    "hotfix_to_dev",
)
MERGE_STRATEGIES = ("fast_forward", "squash", "merge_commit")
_ROUTE_KINDS = {
    "work_to_dev": ("work_branch", "dev"),
    "dev_to_stable": ("dev", "stable"),
    "hotfix_to_stable": ("hotfix", "stable"),
    "hotfix_to_dev": ("hotfix", "dev"),
}
_SHARED_STATUSES = frozenset(
    {"shared", "published", "protected", "retained", "retained-hotfix"}
)
_HEX_OBJECT = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_ID = re.compile(r"^REVIEW-[A-Za-z0-9._-]+-[0-9]{3}$")
_RISK_FLAG = re.compile(r"^[a-z][a-z0-9_]*$")
MERGE_REVIEW_CONTEXT_SOURCE = "nm-v6://merge-review/request-v1"

REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "review_id",
        "run_id",
        "spec_hash",
        "config_hash",
        "route",
        "source_kind",
        "target_kind",
        "source_ref",
        "source_commit",
        "source_tree",
        "target_ref",
        "target_commit",
        "target_tree",
        "purpose",
        "sharing_status",
        "topology",
        "commit_quality",
        "audit_boundary_required",
        "rollback_boundary_required",
        "rollback_ref",
        "allowed_strategies",
        "strategy_results",
        "exact_source_tree_required",
        "future_gate_id",
        "authorization_id",
        "request_digest",
    }
)
TOPOLOGY_FIELDS = frozenset(
    {
        "merge_base",
        "target_is_ancestor",
        "source_is_ancestor",
        "source_only_commits",
        "target_only_commits",
    }
)
COMMIT_QUALITY_FIELDS = frozenset(
    {
        "commit_count",
        "merge_commit_count",
        "fixup_commit_count",
        "commits_suitable",
        "single_logical_change",
        "disposable",
    }
)
STRATEGY_RESULT_FIELDS = frozenset(
    {"valid", "conflict", "expected_result_tree"}
)
OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "review_id",
        "request_digest",
        "route",
        "source_commit",
        "target_commit",
        "candidate_tree",
        "decision",
        "strategy",
        "rationale",
        "expected_result_tree",
        "risk_flags",
        "observation_digest",
    }
)


def _mapping(value: Any, *, subject: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{subject} must be an object")
    return dict(value)


def _nonempty(value: Any, *, subject: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{subject} must be a nonempty string")
    return value


def _object_id(value: Any, *, subject: str) -> str:
    result = _nonempty(value, subject=subject)
    if _HEX_OBJECT.fullmatch(result) is None:
        raise ContractError(f"{subject} must be a full lowercase Git object ID")
    return result


def _sha256(value: Any, *, subject: str) -> str:
    result = _nonempty(value, subject=subject)
    if _SHA256.fullmatch(result) is None:
        raise ContractError(f"{subject} must be a lowercase SHA-256 digest")
    return result


def _boolean(value: Any, *, subject: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{subject} must be boolean")
    return value


def _nonnegative_int(value: Any, *, subject: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{subject} must be a nonnegative integer")
    return value


def _digest_without(document: Mapping[str, Any], field: str) -> str:
    unsigned = {key: value for key, value in document.items() if key != field}
    return sha256_bytes(canonical_json(unsigned))


def canonical_merge_review_request_digest(request: Mapping[str, Any]) -> str:
    """Return the canonical digest of a sealed or unsealed request."""

    return _digest_without(_mapping(request, subject="merge review request"), "request_digest")


def canonical_merge_review_observation_digest(
    observation: Mapping[str, Any],
) -> str:
    """Return the canonical digest of a sealed or unsealed observation."""

    return _digest_without(
        _mapping(observation, subject="merge review observation"),
        "observation_digest",
    )


def _validate_request_document(
    request: Mapping[str, Any], *, require_digest: bool
) -> dict[str, Any]:
    value = _mapping(request, subject="merge review request")
    expected_fields = REQUEST_FIELDS if require_digest else REQUEST_FIELDS - {"request_digest"}
    require_keys(value, expected_fields, subject="merge review request")
    reject_unknown_keys(value, expected_fields, subject="merge review request")
    if value["schema_version"] != REQUEST_SCHEMA_VERSION:
        raise ContractError("unsupported merge review request schema_version")
    review_id = _nonempty(value["review_id"], subject="review_id")
    if _REVIEW_ID.fullmatch(review_id) is None:
        raise ContractError("merge review request has an invalid review_id")
    _nonempty(value["run_id"], subject="run_id")
    _sha256(value["spec_hash"], subject="spec_hash")
    _sha256(value["config_hash"], subject="config_hash")

    route = value["route"]
    if route not in MERGE_ROUTES:
        raise ContractError(f"unsupported merge review route: {route!r}")
    source_kind = value["source_kind"]
    target_kind = value["target_kind"]
    if (source_kind, target_kind) != _ROUTE_KINDS[route]:
        raise ContractError("merge review source/target kinds do not match the route")
    for field in ("source_ref", "target_ref"):
        ref = _nonempty(value[field], subject=field)
        if not ref.startswith("refs/heads/"):
            raise ContractError(f"{field} must be an exact local branch ref")
    source_commit = _object_id(value["source_commit"], subject="source_commit")
    target_commit = _object_id(value["target_commit"], subject="target_commit")
    source_tree = _object_id(value["source_tree"], subject="source_tree")
    target_tree = _object_id(value["target_tree"], subject="target_tree")
    _nonempty(value["purpose"], subject="purpose")
    _nonempty(value["sharing_status"], subject="sharing_status")
    _boolean(value["audit_boundary_required"], subject="audit_boundary_required")
    _boolean(value["rollback_boundary_required"], subject="rollback_boundary_required")
    _nonempty(value["rollback_ref"], subject="rollback_ref")
    _nonempty(value["future_gate_id"], subject="future_gate_id")
    _nonempty(value["authorization_id"], subject="authorization_id")

    topology = _mapping(value["topology"], subject="topology")
    require_keys(topology, TOPOLOGY_FIELDS, subject="topology")
    reject_unknown_keys(topology, TOPOLOGY_FIELDS, subject="topology")
    merge_base = _object_id(topology["merge_base"], subject="topology.merge_base")
    target_is_ancestor = _boolean(
        topology["target_is_ancestor"], subject="topology.target_is_ancestor"
    )
    source_is_ancestor = _boolean(
        topology["source_is_ancestor"], subject="topology.source_is_ancestor"
    )
    source_only = _nonnegative_int(
        topology["source_only_commits"], subject="topology.source_only_commits"
    )
    target_only = _nonnegative_int(
        topology["target_only_commits"], subject="topology.target_only_commits"
    )
    if source_commit == target_commit:
        if not target_is_ancestor or not source_is_ancestor:
            raise ContractError("identical commits must be mutual ancestors")
        if merge_base != source_commit or source_only or target_only:
            raise ContractError("identical commits have inconsistent topology")
        if source_tree != target_tree:
            raise ContractError("identical commits must have identical trees")
    else:
        if target_is_ancestor and source_is_ancestor:
            raise ContractError("distinct commits cannot be mutual ancestors")
        if target_is_ancestor and (merge_base != target_commit or target_only != 0):
            raise ContractError("target-ancestor topology is inconsistent")
        if source_is_ancestor and (merge_base != source_commit or source_only != 0):
            raise ContractError("source-ancestor topology is inconsistent")
        if not target_is_ancestor and not source_is_ancestor and merge_base in {
            source_commit,
            target_commit,
        }:
            raise ContractError("divergent topology has an impossible merge base")

    quality = _mapping(value["commit_quality"], subject="commit_quality")
    require_keys(quality, COMMIT_QUALITY_FIELDS, subject="commit_quality")
    reject_unknown_keys(quality, COMMIT_QUALITY_FIELDS, subject="commit_quality")
    commit_count = _nonnegative_int(
        quality["commit_count"], subject="commit_quality.commit_count"
    )
    merge_count = _nonnegative_int(
        quality["merge_commit_count"], subject="commit_quality.merge_commit_count"
    )
    fixup_count = _nonnegative_int(
        quality["fixup_commit_count"], subject="commit_quality.fixup_commit_count"
    )
    if commit_count != source_only:
        raise ContractError("commit quality count differs from source-only topology")
    if merge_count > commit_count or fixup_count > commit_count:
        raise ContractError("commit quality subtype count exceeds commit_count")
    for field in ("commits_suitable", "single_logical_change", "disposable"):
        _boolean(quality[field], subject=f"commit_quality.{field}")

    allowed = value["allowed_strategies"]
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(strategy not in MERGE_STRATEGIES for strategy in allowed)
        or len(allowed) != len(set(allowed))
    ):
        raise ContractError("allowed_strategies must be a unique nonempty allowed set")
    canonical_allowed = [strategy for strategy in MERGE_STRATEGIES if strategy in allowed]
    if allowed != canonical_allowed:
        raise ContractError("allowed_strategies must use canonical strategy order")

    results = _mapping(value["strategy_results"], subject="strategy_results")
    if set(results) != set(MERGE_STRATEGIES):
        raise ContractError("strategy_results must describe every merge strategy")
    normalized_results: dict[str, dict[str, Any]] = {}
    for strategy in MERGE_STRATEGIES:
        result = _mapping(results[strategy], subject=f"strategy_results.{strategy}")
        require_keys(result, STRATEGY_RESULT_FIELDS, subject=f"strategy_results.{strategy}")
        reject_unknown_keys(
            result, STRATEGY_RESULT_FIELDS, subject=f"strategy_results.{strategy}"
        )
        valid = _boolean(result["valid"], subject=f"strategy_results.{strategy}.valid")
        conflict = _boolean(
            result["conflict"], subject=f"strategy_results.{strategy}.conflict"
        )
        expected_tree = result["expected_result_tree"]
        if valid:
            if conflict:
                raise ContractError(f"valid {strategy} result cannot report a conflict")
            expected_tree = _object_id(
                expected_tree,
                subject=f"strategy_results.{strategy}.expected_result_tree",
            )
        elif expected_tree is not None:
            raise ContractError(f"invalid {strategy} result must not claim a result tree")
        normalized_results[strategy] = {
            "valid": valid,
            "conflict": conflict,
            "expected_result_tree": expected_tree,
        }
    fast_forward = normalized_results["fast_forward"]
    if fast_forward["valid"] != target_is_ancestor:
        raise ContractError("fast_forward validity differs from target ancestry")
    if fast_forward["valid"] and fast_forward["expected_result_tree"] != source_tree:
        raise ContractError("fast_forward result tree must equal the source tree")
    squash = normalized_results["squash"]
    merge_commit = normalized_results["merge_commit"]
    if squash != merge_commit:
        raise ContractError("squash and merge_commit simulations must have identical trees")

    exact_tree = _boolean(
        value["exact_source_tree_required"], subject="exact_source_tree_required"
    )
    if route in {"dev_to_stable", "hotfix_to_stable"} and not exact_tree:
        raise ContractError(f"{route} requires the exact verified source tree")
    if exact_tree:
        for strategy, result in normalized_results.items():
            if result["valid"] and result["expected_result_tree"] != source_tree:
                raise ContractError(
                    f"valid {strategy} result violates the exact-source-tree requirement"
                )

    if require_digest:
        request_digest = _sha256(value["request_digest"], subject="request_digest")
        if request_digest != canonical_merge_review_request_digest(value):
            raise ContractError("merge review request digest mismatch")
    return value


def seal_merge_review_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate request facts and attach their canonical digest."""

    value = _validate_request_document(request, require_digest=False)
    sealed = {**value, "request_digest": canonical_merge_review_request_digest(value)}
    return validate_merge_review_request(sealed)


def validate_merge_review_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one exact, canonically digested merge-review request."""

    return _validate_request_document(request, require_digest=True)


def merge_review_context_item(request: Mapping[str, Any]) -> ContextItem:
    """Build the sole canonical merge-review slice for an adapter context."""

    value = validate_merge_review_request(request)
    return ContextItem(
        "decision",
        MERGE_REVIEW_CONTEXT_SOURCE,
        canonical_json(value).decode("utf-8"),
        entry_id=f"CTX-MERGE-REVIEW-{value['request_digest'][:16]}",
    )


def validate_merge_review_context(
    manifest: Mapping[str, Any], request: Mapping[str, Any]
) -> dict[str, Any]:
    """Require one byte-exact merge-review request in a validated context."""

    value = validate_merge_review_request(request)
    validated_manifest = validate_context_manifest(manifest)
    matching = [
        entry
        for entry in validated_manifest["entries"]
        if entry.get("source") == MERGE_REVIEW_CONTEXT_SOURCE
    ]
    if len(matching) != 1:
        raise ContractError("merge reviewer context requires exactly one request entry")
    entry = matching[0]
    expected_content = canonical_json(value).decode("utf-8")
    if entry.get("kind") != "decision" or entry.get("content") != expected_content:
        raise ContractError("merge reviewer context request entry is stale or malformed")
    return dict(entry)


def _validate_observation_document(
    observation: Mapping[str, Any], *, require_digest: bool
) -> dict[str, Any]:
    value = _mapping(observation, subject="merge review observation")
    expected_fields = (
        OBSERVATION_FIELDS
        if require_digest
        else OBSERVATION_FIELDS - {"observation_digest"}
    )
    require_keys(value, expected_fields, subject="merge review observation")
    reject_unknown_keys(value, expected_fields, subject="merge review observation")
    if value["schema_version"] != OBSERVATION_SCHEMA_VERSION:
        raise ContractError("unsupported merge review observation schema_version")
    review_id = _nonempty(value["review_id"], subject="review_id")
    if _REVIEW_ID.fullmatch(review_id) is None:
        raise ContractError("merge review observation has an invalid review_id")
    _sha256(value["request_digest"], subject="request_digest")
    if value["route"] not in MERGE_ROUTES:
        raise ContractError("merge review observation has an unsupported route")
    _object_id(value["source_commit"], subject="source_commit")
    _object_id(value["target_commit"], subject="target_commit")
    _object_id(value["candidate_tree"], subject="candidate_tree")
    decision = value["decision"]
    if decision not in {"propose", "cannot_propose"}:
        raise ContractError("merge review observation has an unsupported decision")
    _nonempty(value["rationale"], subject="rationale")
    if decision == "propose":
        if value["strategy"] not in MERGE_STRATEGIES:
            raise ContractError("proposed merge strategy is unsupported")
        _object_id(value["expected_result_tree"], subject="expected_result_tree")
    elif value["strategy"] is not None or value["expected_result_tree"] is not None:
        raise ContractError("cannot_propose must not claim a strategy or result tree")
    flags = value["risk_flags"]
    if (
        not isinstance(flags, list)
        or not all(isinstance(flag, str) and _RISK_FLAG.fullmatch(flag) for flag in flags)
        or len(flags) != len(set(flags))
        or flags != sorted(flags)
    ):
        raise ContractError("risk_flags must be unique canonical lowercase identifiers")
    if require_digest:
        observation_digest = _sha256(
            value["observation_digest"], subject="observation_digest"
        )
        if observation_digest != canonical_merge_review_observation_digest(value):
            raise ContractError("merge review observation digest mismatch")
    return value


def seal_merge_review_observation(
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an observation shape and attach its canonical digest."""

    value = _validate_observation_document(observation, require_digest=False)
    sealed = {
        **value,
        "observation_digest": canonical_merge_review_observation_digest(value),
    }
    return validate_merge_review_observation(sealed)


def validate_merge_review_observation(
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one canonically digested reviewer observation."""

    return _validate_observation_document(observation, require_digest=True)


def _viable_strategies(request: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        strategy
        for strategy in request["allowed_strategies"]
        if request["strategy_results"][strategy]["valid"] is True
    )


def validate_merge_review_observations(
    request: Mapping[str, Any], observations: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Bind exactly one reviewer observation to an exact request and policy."""

    validated_request = validate_merge_review_request(request)
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise ContractError("merge review observations must be an array")
    if len(observations) != 1:
        raise ContractError("merge review requires exactly one observation")
    observation = validate_merge_review_observation(observations[0])
    bindings = {
        "review_id": validated_request["review_id"],
        "request_digest": validated_request["request_digest"],
        "route": validated_request["route"],
        "source_commit": validated_request["source_commit"],
        "target_commit": validated_request["target_commit"],
        "candidate_tree": validated_request["source_tree"],
    }
    for field, expected in bindings.items():
        if observation[field] != expected:
            raise ContractError(f"merge review observation has stale {field}")
    viable = _viable_strategies(validated_request)
    if observation["decision"] == "cannot_propose":
        if viable:
            raise ContractError("reviewer refused despite an allowed valid strategy")
        return observation
    strategy = observation["strategy"]
    if strategy not in validated_request["allowed_strategies"]:
        raise ContractError("reviewer selected a disabled merge strategy")
    strategy_result = validated_request["strategy_results"][strategy]
    if strategy_result["valid"] is not True:
        raise ContractError("reviewer selected a topologically invalid merge strategy")
    if observation["expected_result_tree"] != strategy_result["expected_result_tree"]:
        raise ContractError("reviewer expected result tree differs from core simulation")
    if (
        validated_request["exact_source_tree_required"] is True
        and observation["expected_result_tree"] != validated_request["source_tree"]
    ):
        raise ContractError("reviewer proposal violates the exact-source-tree requirement")
    return observation


def validate_merge_reviewer_adapter_result(
    result: Mapping[str, Any],
    *,
    adapter_request: Mapping[str, Any],
    review_request: Mapping[str, Any],
    expected_session_id: str,
) -> dict[str, Any]:
    """Validate the read-only adapter envelope and its sole review observation."""

    request_envelope = validate_adapter_request(adapter_request)
    if request_envelope["role"] != "merge_reviewer":
        raise ContractError("merge reviewer adapter request has the wrong role")
    if request_envelope["allowed_capabilities"] != []:
        raise ContractError("merge reviewer adapter request must grant zero capabilities")
    validate_merge_review_context(request_envelope["context_manifest"], review_request)
    session_id = _nonempty(expected_session_id, subject="expected_session_id")
    normalized = adapter_result_to_dict(
        validate_adapter_result(result, request=request_envelope)
    )
    if normalized["status"] != "succeeded":
        raise ContractError("merge reviewer adapter result did not succeed")
    if normalized["session_id"] != session_id:
        raise ContractError("merge reviewer adapter result has a stale session_id")
    if normalized["candidate_commit"] is not None:
        raise ContractError("merge reviewer must not return a candidate commit")
    if normalized["changed_paths"]:
        raise ContractError("merge reviewer must not report changed paths")
    if normalized["requested_followups"]:
        raise ContractError("merge reviewer must not request follow-up work")
    observation = validate_merge_review_observations(
        review_request, normalized["observations"]
    )
    normalized["observations"] = [observation]
    return normalized


def deterministic_fake_merge_review(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one deterministic fake reviewer decision for acceptance tests."""

    value = validate_merge_review_request(request)
    viable = set(_viable_strategies(value))
    quality = value["commit_quality"]
    boundary = (
        value["audit_boundary_required"]
        or value["rollback_boundary_required"]
        or value["sharing_status"] in _SHARED_STATUSES
    )
    noisy_disposable = (
        quality["single_logical_change"]
        and quality["disposable"]
        and (
            quality["fixup_commit_count"] > 0
            or quality["commit_count"] > 1
            or not quality["commits_suitable"]
        )
    )
    strategy: str | None
    if (
        value["source_commit"] == value["target_commit"]
        and "fast_forward" in viable
    ):
        strategy = "fast_forward"
        rationale = "preserve an unchanged target without creating an empty boundary"
    elif value["route"] == "hotfix_to_stable" and "fast_forward" in viable:
        strategy = "fast_forward"
        rationale = "preserve the exact verified hotfix effect on its stable base"
    elif boundary and "merge_commit" in viable:
        strategy = "merge_commit"
        rationale = "preserve shared history and an explicit audit or rollback boundary"
    elif noisy_disposable and "squash" in viable:
        strategy = "squash"
        rationale = "collapse one disposable logical change with noisy intermediate commits"
    elif quality["commits_suitable"] and "fast_forward" in viable:
        strategy = "fast_forward"
        rationale = "preserve a suitable linear history without an unnecessary boundary"
    elif "merge_commit" in viable:
        strategy = "merge_commit"
        rationale = "preserve topology through the remaining valid integration strategy"
    elif "squash" in viable:
        strategy = "squash"
        rationale = "use the remaining valid single-tree integration strategy"
    elif "fast_forward" in viable:
        strategy = "fast_forward"
        rationale = "use the remaining valid linear integration strategy"
    else:
        strategy = None
        rationale = "no configured strategy has a valid conflict-free simulated result"

    risk_flags = []
    if value["audit_boundary_required"]:
        risk_flags.append("audit_boundary")
    if value["rollback_boundary_required"]:
        risk_flags.append("rollback_boundary")
    if not viable:
        risk_flags.append("no_valid_strategy")
    if any(
        value["strategy_results"][candidate]["conflict"]
        for candidate in value["allowed_strategies"]
    ):
        risk_flags.append("simulated_conflict")
    observation = seal_merge_review_observation(
        {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "review_id": value["review_id"],
            "request_digest": value["request_digest"],
            "route": value["route"],
            "source_commit": value["source_commit"],
            "target_commit": value["target_commit"],
            "candidate_tree": value["source_tree"],
            "decision": "propose" if strategy is not None else "cannot_propose",
            "strategy": strategy,
            "rationale": rationale,
            "expected_result_tree": (
                value["strategy_results"][strategy]["expected_result_tree"]
                if strategy is not None
                else None
            ),
            "risk_flags": sorted(risk_flags),
        }
    )
    return validate_merge_review_observations(value, [observation])
