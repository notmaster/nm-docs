"""Provider-neutral branch-cleanup review contracts.

The reviewer receives only facts already computed by the deterministic core.
This module validates their shape and binding; it does not inspect Git, the
runtime store, worktrees, leases, sessions, or workspaces.  A later runtime
integration must recompute those facts before acting on an observation.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping, Sequence

from .context import (
    REQUIRED_CONTEXT_KINDS,
    ContextItem,
    build_context_manifest,
)
from .contracts import (
    adapter_result_to_dict,
    validate_adapter_request,
    validate_adapter_result,
    validate_context_manifest,
)
from .errors import ContractError
from .util import canonical_json, reject_unknown_keys, require_keys, sha256_bytes


REQUEST_SCHEMA_VERSION = "nm-v6/cleanup-review-request-v1"
OBSERVATION_SCHEMA_VERSION = "nm-v6/cleanup-review-observation-v1"
INTEGRATION_RECEIPT_SCHEMA_VERSION = "nm-v6/cleanup-integration-receipt-v1"
INTEGRATION_PROOF_SCHEMA_VERSION = "nm-v6/cleanup-integration-proof-v1"
CLEANUP_FACTS_SCHEMA_VERSION = "nm-v6/cleanup-facts-v1"

CLEANUP_DECISIONS = ("delete_local", "retain", "request_administrator")
MERGE_STRATEGIES = ("fast_forward", "squash", "merge_commit")
REMOTE_BRANCH_STATUSES = ("absent", "present", "unknown")
CLEANUP_REVIEW_CONTEXT_SOURCE = "nm-v6://cleanup-review/request-v1"

_HEX_OBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_ID = re.compile(r"^CLEANUP-REVIEW-[A-Za-z0-9._-]+-[0-9]{3}$")
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_BRANCH = re.compile(
    r"^(?!/)(?!.*(?:\.\.|//|@\{|\\|\s))(?!.*\.$)[A-Za-z0-9._/-]+$"
)

REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "review_id",
        "run_id",
        "spec_hash",
        "config_hash",
        "input_revision",
        "branch",
        "branch_head",
        "integration_receipt",
        "integration_proof",
        "cleanup_facts",
        "request_digest",
    }
)
INTEGRATION_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "strategy",
        "source_commit",
        "target_ref",
        "target_before",
        "target_after",
        "result_tree",
        "rollback_ref",
        "authorization_id",
        "executed_at",
        "receipt_digest",
    }
)
INTEGRATION_PROOF_FIELDS = frozenset(
    {
        "schema_version",
        "proof_kind",
        "strategy",
        "source_head",
        "target_commit",
        "current_target_head",
        "target_tree",
        "target_contains_integration_result",
        "ancestry_proven",
        "patch_equivalent",
        "tree_equivalent",
        "proof_digest",
    }
)
CLEANUP_FACTS_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "input_revision",
        "branch",
        "expected_head",
        "observed_head",
        "authority_available",
        "responsibility_evidence_id",
        "is_protected",
        "retained_pattern",
        "remote_branch_status",
        "remote_head",
        "checked_out",
        "linked_worktree_paths",
        "responsibilities",
        "blockers",
        "facts_digest",
    }
)
RESPONSIBILITY_FIELDS = frozenset(
    {
        "review_responsibility_closed",
        "backup_retention_absent",
        "dependent_work_closed",
        "release_responsibility_closed",
        "rollback_responsibility_closed",
        "audit_retention_absent",
        "explicit_retention_absent",
    }
)
BLOCKER_FIELDS = frozenset(
    {"live_lease_ids", "live_session_ids", "dependent_workspace_paths"}
)
OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "review_id",
        "request_digest",
        "run_id",
        "spec_hash",
        "config_hash",
        "input_revision",
        "branch",
        "branch_head",
        "integration_receipt_digest",
        "facts_digest",
        "decision",
        "rationale",
        "risk_flags",
        "observation_digest",
    }
)

RISK_FLAGS = frozenset(
    {
        "branch_missing",
        "branch_moved",
        "protected_branch",
        "retained_pattern",
        "remote_branch_present",
        "remote_status_unknown",
        "branch_checked_out",
        "linked_worktree",
        "review_open",
        "backup_retention",
        "dependent_work",
        "release_responsibility",
        "rollback_responsibility",
        "audit_retention",
        "explicit_retention",
        "live_lease",
        "live_session",
        "dependent_workspace",
        "integration_source_mismatch",
        "integration_proof_incomplete",
        "cleanup_authority_unavailable",
        "responsibility_evidence_missing",
    }
)
_NONBLOCKING_RISKS = frozenset({"remote_branch_present"})
_ADMINISTRATOR_RISKS = frozenset(
    {
        "branch_missing",
        "branch_moved",
        "remote_status_unknown",
        "integration_source_mismatch",
        "cleanup_authority_unavailable",
        "responsibility_evidence_missing",
    }
)
_RESPONSIBILITY_RISKS = {
    "review_responsibility_closed": "review_open",
    "backup_retention_absent": "backup_retention",
    "dependent_work_closed": "dependent_work",
    "release_responsibility_closed": "release_responsibility",
    "rollback_responsibility_closed": "rollback_responsibility",
    "audit_retention_absent": "audit_retention",
    "explicit_retention_absent": "explicit_retention",
}
_BLOCKER_RISKS = {
    "live_lease_ids": "live_lease",
    "live_session_ids": "live_session",
    "dependent_workspace_paths": "dependent_workspace",
}


def _mapping(value: Any, *, subject: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{subject} must be an object")
    return dict(value)


def _nonempty(value: Any, *, subject: str) -> str:
    if not isinstance(value, str) or not value or not value.strip():
        raise ContractError(f"{subject} must be a nonempty string")
    return value


def _sha256(value: Any, *, subject: str) -> str:
    result = _nonempty(value, subject=subject)
    if _SHA256.fullmatch(result) is None:
        raise ContractError(f"{subject} must be a lowercase SHA-256 digest")
    return result


def _object_id(value: Any, *, subject: str) -> str:
    result = _nonempty(value, subject=subject)
    if _HEX_OBJECT.fullmatch(result) is None:
        raise ContractError(f"{subject} must be a full lowercase Git object ID")
    return result


def _branch(value: Any, *, subject: str) -> str:
    result = _nonempty(value, subject=subject)
    if _BRANCH.fullmatch(result) is None:
        raise ContractError(f"{subject} must be a canonical branch name")
    return result


def _boolean(value: Any, *, subject: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{subject} must be boolean")
    return value


def _revision(value: Any, *, subject: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{subject} must be a nonnegative integer")
    return value


def _timestamp(value: Any, *, subject: str) -> str:
    result = _nonempty(value, subject=subject)
    if _RFC3339.fullmatch(result) is None:
        raise ContractError(f"{subject} must be an RFC3339 timestamp")
    normalized = result[:-1] + "+00:00" if result.endswith("Z") else result
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ContractError(f"{subject} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{subject} must include a timezone")
    return result


def _canonical_string_list(value: Any, *, subject: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
        or value != sorted(value)
    ):
        raise ContractError(f"{subject} must be a sorted unique string array")
    return list(value)


def _digest_without(document: Mapping[str, Any], field: str) -> str:
    return sha256_bytes(
        canonical_json({key: value for key, value in document.items() if key != field})
    )


def canonical_cleanup_integration_receipt_digest(
    receipt: Mapping[str, Any],
) -> str:
    return _digest_without(
        _mapping(receipt, subject="cleanup integration receipt"), "receipt_digest"
    )


def canonical_cleanup_integration_proof_digest(proof: Mapping[str, Any]) -> str:
    return _digest_without(
        _mapping(proof, subject="cleanup integration proof"), "proof_digest"
    )


def canonical_cleanup_facts_digest(facts: Mapping[str, Any]) -> str:
    return _digest_without(_mapping(facts, subject="cleanup facts"), "facts_digest")


def canonical_cleanup_review_request_digest(request: Mapping[str, Any]) -> str:
    return _digest_without(
        _mapping(request, subject="cleanup review request"), "request_digest"
    )


def canonical_cleanup_review_observation_digest(
    observation: Mapping[str, Any],
) -> str:
    return _digest_without(
        _mapping(observation, subject="cleanup review observation"),
        "observation_digest",
    )


def _validate_integration_receipt(
    receipt: Mapping[str, Any], *, require_digest: bool
) -> dict[str, Any]:
    value = _mapping(receipt, subject="cleanup integration receipt")
    fields = (
        INTEGRATION_RECEIPT_FIELDS
        if require_digest
        else INTEGRATION_RECEIPT_FIELDS - {"receipt_digest"}
    )
    require_keys(value, fields, subject="cleanup integration receipt")
    reject_unknown_keys(value, fields, subject="cleanup integration receipt")
    if value["schema_version"] != INTEGRATION_RECEIPT_SCHEMA_VERSION:
        raise ContractError("unsupported cleanup integration receipt schema_version")
    _nonempty(value["receipt_id"], subject="integration_receipt.receipt_id")
    if value["strategy"] not in MERGE_STRATEGIES:
        raise ContractError("cleanup integration receipt has an invalid strategy")
    _object_id(value["source_commit"], subject="integration_receipt.source_commit")
    target_ref = _nonempty(value["target_ref"], subject="integration_receipt.target_ref")
    prefix = "refs/heads/"
    if not target_ref.startswith(prefix) or _BRANCH.fullmatch(
        target_ref.removeprefix(prefix)
    ) is None:
        raise ContractError("cleanup integration target_ref must be an exact branch ref")
    for field in ("target_before", "target_after", "result_tree"):
        _object_id(value[field], subject=f"integration_receipt.{field}")
    if value["strategy"] == "fast_forward" and (
        value["target_after"] != value["source_commit"]
    ):
        raise ContractError(
            "fast-forward cleanup receipt target_after must equal source_commit"
        )
    _nonempty(value["rollback_ref"], subject="integration_receipt.rollback_ref")
    _nonempty(value["authorization_id"], subject="integration_receipt.authorization_id")
    _timestamp(value["executed_at"], subject="integration_receipt.executed_at")
    if require_digest:
        digest = _sha256(value["receipt_digest"], subject="integration_receipt.receipt_digest")
        if digest != canonical_cleanup_integration_receipt_digest(value):
            raise ContractError("cleanup integration receipt digest mismatch")
    return value


def seal_cleanup_integration_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = _validate_integration_receipt(receipt, require_digest=False)
    return validate_cleanup_integration_receipt(
        {**value, "receipt_digest": canonical_cleanup_integration_receipt_digest(value)}
    )


def validate_cleanup_integration_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    return _validate_integration_receipt(receipt, require_digest=True)


def _validate_integration_proof(
    proof: Mapping[str, Any], *, require_digest: bool
) -> dict[str, Any]:
    value = _mapping(proof, subject="cleanup integration proof")
    fields = (
        INTEGRATION_PROOF_FIELDS
        if require_digest
        else INTEGRATION_PROOF_FIELDS - {"proof_digest"}
    )
    require_keys(value, fields, subject="cleanup integration proof")
    reject_unknown_keys(value, fields, subject="cleanup integration proof")
    if value["schema_version"] != INTEGRATION_PROOF_SCHEMA_VERSION:
        raise ContractError("unsupported cleanup integration proof schema_version")
    strategy = value["strategy"]
    if strategy not in MERGE_STRATEGIES:
        raise ContractError("cleanup integration proof has an invalid strategy")
    expected_kind = "patch_tree_equivalence" if strategy == "squash" else "graph_ancestry"
    if value["proof_kind"] != expected_kind:
        raise ContractError("cleanup integration proof kind differs from its strategy")
    for field in (
        "source_head",
        "target_commit",
        "current_target_head",
        "target_tree",
    ):
        _object_id(value[field], subject=f"integration_proof.{field}")
    for field in (
        "target_contains_integration_result",
        "ancestry_proven",
        "patch_equivalent",
        "tree_equivalent",
    ):
        _boolean(value[field], subject=f"integration_proof.{field}")
    if require_digest:
        digest = _sha256(value["proof_digest"], subject="integration_proof.proof_digest")
        if digest != canonical_cleanup_integration_proof_digest(value):
            raise ContractError("cleanup integration proof digest mismatch")
    return value


def seal_cleanup_integration_proof(proof: Mapping[str, Any]) -> dict[str, Any]:
    value = _validate_integration_proof(proof, require_digest=False)
    return validate_cleanup_integration_proof(
        {**value, "proof_digest": canonical_cleanup_integration_proof_digest(value)}
    )


def validate_cleanup_integration_proof(proof: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_integration_proof(proof, require_digest=True)


def _validate_cleanup_facts(
    facts: Mapping[str, Any], *, require_digest: bool
) -> dict[str, Any]:
    value = _mapping(facts, subject="cleanup facts")
    fields = (
        CLEANUP_FACTS_FIELDS
        if require_digest
        else CLEANUP_FACTS_FIELDS - {"facts_digest"}
    )
    require_keys(value, fields, subject="cleanup facts")
    reject_unknown_keys(value, fields, subject="cleanup facts")
    if value["schema_version"] != CLEANUP_FACTS_SCHEMA_VERSION:
        raise ContractError("unsupported cleanup facts schema_version")
    _nonempty(value["run_id"], subject="cleanup_facts.run_id")
    _revision(value["input_revision"], subject="cleanup_facts.input_revision")
    _branch(value["branch"], subject="cleanup_facts.branch")
    _object_id(value["expected_head"], subject="cleanup_facts.expected_head")
    if value["observed_head"] is not None:
        _object_id(value["observed_head"], subject="cleanup_facts.observed_head")
    for field in (
        "authority_available",
        "is_protected",
        "retained_pattern",
        "checked_out",
    ):
        _boolean(value[field], subject=f"cleanup_facts.{field}")
    if value["responsibility_evidence_id"] is not None:
        _nonempty(
            value["responsibility_evidence_id"],
            subject="cleanup_facts.responsibility_evidence_id",
        )
    if value["remote_branch_status"] not in REMOTE_BRANCH_STATUSES:
        raise ContractError("cleanup facts has an invalid remote branch status")
    if value["remote_branch_status"] == "present":
        _object_id(value["remote_head"], subject="cleanup_facts.remote_head")
    elif value["remote_head"] is not None:
        raise ContractError(
            "cleanup facts remote_head must be null unless the remote branch is present"
        )
    _canonical_string_list(
        value["linked_worktree_paths"],
        subject="cleanup_facts.linked_worktree_paths",
    )
    responsibilities = _mapping(
        value["responsibilities"], subject="cleanup_facts.responsibilities"
    )
    require_keys(
        responsibilities,
        RESPONSIBILITY_FIELDS,
        subject="cleanup_facts.responsibilities",
    )
    reject_unknown_keys(
        responsibilities,
        RESPONSIBILITY_FIELDS,
        subject="cleanup_facts.responsibilities",
    )
    for field in RESPONSIBILITY_FIELDS:
        _boolean(
            responsibilities[field],
            subject=f"cleanup_facts.responsibilities.{field}",
        )
    blockers = _mapping(value["blockers"], subject="cleanup_facts.blockers")
    require_keys(blockers, BLOCKER_FIELDS, subject="cleanup_facts.blockers")
    reject_unknown_keys(blockers, BLOCKER_FIELDS, subject="cleanup_facts.blockers")
    for field in BLOCKER_FIELDS:
        _canonical_string_list(
            blockers[field], subject=f"cleanup_facts.blockers.{field}"
        )
    if require_digest:
        digest = _sha256(value["facts_digest"], subject="cleanup_facts.facts_digest")
        if digest != canonical_cleanup_facts_digest(value):
            raise ContractError("cleanup facts digest mismatch")
    return {
        **value,
        "responsibilities": responsibilities,
        "blockers": blockers,
    }


def seal_cleanup_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    value = _validate_cleanup_facts(facts, require_digest=False)
    return validate_cleanup_facts(
        {**value, "facts_digest": canonical_cleanup_facts_digest(value)}
    )


def validate_cleanup_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_cleanup_facts(facts, require_digest=True)


def _validate_request_document(
    request: Mapping[str, Any], *, require_digest: bool
) -> dict[str, Any]:
    value = _mapping(request, subject="cleanup review request")
    fields = REQUEST_FIELDS if require_digest else REQUEST_FIELDS - {"request_digest"}
    require_keys(value, fields, subject="cleanup review request")
    reject_unknown_keys(value, fields, subject="cleanup review request")
    if value["schema_version"] != REQUEST_SCHEMA_VERSION:
        raise ContractError("unsupported cleanup review request schema_version")
    review_id = _nonempty(value["review_id"], subject="cleanup review review_id")
    if _REVIEW_ID.fullmatch(review_id) is None:
        raise ContractError("cleanup review request has an invalid review_id")
    run_id = _nonempty(value["run_id"], subject="cleanup review run_id")
    _sha256(value["spec_hash"], subject="cleanup review spec_hash")
    _sha256(value["config_hash"], subject="cleanup review config_hash")
    input_revision = _revision(
        value["input_revision"], subject="cleanup review input_revision"
    )
    branch = _branch(value["branch"], subject="cleanup review branch")
    branch_head = _object_id(value["branch_head"], subject="cleanup review branch_head")
    receipt = validate_cleanup_integration_receipt(value["integration_receipt"])
    proof = validate_cleanup_integration_proof(value["integration_proof"])
    facts = validate_cleanup_facts(value["cleanup_facts"])

    if proof["strategy"] != receipt["strategy"]:
        raise ContractError("cleanup integration proof strategy differs from the receipt")
    if proof["source_head"] != branch_head:
        raise ContractError("cleanup integration proof is for another source head")
    if (
        proof["target_commit"] != receipt["target_after"]
        or proof["target_tree"] != receipt["result_tree"]
    ):
        raise ContractError("cleanup integration proof is for another integration result")
    if (
        facts["run_id"] != run_id
        or facts["input_revision"] != input_revision
        or facts["branch"] != branch
        or facts["expected_head"] != branch_head
    ):
        raise ContractError("cleanup facts are stale for the review subject")
    if require_digest:
        digest = _sha256(value["request_digest"], subject="cleanup review request_digest")
        if digest != canonical_cleanup_review_request_digest(value):
            raise ContractError("cleanup review request digest mismatch")
    return {
        **value,
        "integration_receipt": receipt,
        "integration_proof": proof,
        "cleanup_facts": facts,
    }


def seal_cleanup_review_request(request: Mapping[str, Any]) -> dict[str, Any]:
    value = _validate_request_document(request, require_digest=False)
    return validate_cleanup_review_request(
        {**value, "request_digest": canonical_cleanup_review_request_digest(value)}
    )


def validate_cleanup_review_request(request: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_request_document(request, require_digest=True)


def cleanup_review_context_item(request: Mapping[str, Any]) -> ContextItem:
    """Return the sole content-addressed cleanup request context slice."""

    value = validate_cleanup_review_request(request)
    return ContextItem(
        "decision",
        CLEANUP_REVIEW_CONTEXT_SOURCE,
        canonical_json(value).decode("utf-8"),
        entry_id=f"CTX-CLEANUP-REVIEW-{value['request_digest'][:16]}",
    )


def build_cleanup_review_context_manifest(
    *,
    request: Mapping[str, Any],
    attempt_id: str,
    required_items: Sequence[ContextItem | Mapping[str, Any]],
    on_demand_items: Sequence[ContextItem | Mapping[str, Any]] = (),
    prohibited_paths: Sequence[str] = (".nm/runtime",),
    max_manifest_bytes: int,
    max_estimated_tokens: int,
) -> dict[str, Any]:
    """Build a read-only manifest with all seven mandatory generic slices."""

    manifest = build_context_manifest(
        attempt_id=attempt_id,
        items=(*required_items, cleanup_review_context_item(request)),
        on_demand_items=on_demand_items,
        allowed_paths=(),
        prohibited_paths=prohibited_paths,
        max_manifest_bytes=max_manifest_bytes,
        max_estimated_tokens=max_estimated_tokens,
    )
    validate_cleanup_review_context(manifest, request)
    return manifest


def validate_cleanup_review_context(
    manifest: Mapping[str, Any], request: Mapping[str, Any]
) -> dict[str, Any]:
    """Require generic minimum context plus one exact cleanup request."""

    value = validate_cleanup_review_request(request)
    validated_manifest = validate_context_manifest(manifest)
    included_kinds = {
        str(entry.get("kind")) for entry in validated_manifest["entries"]
    }
    missing = sorted(REQUIRED_CONTEXT_KINDS - included_kinds)
    if missing:
        raise ContractError(
            "cleanup reviewer context is missing required slices: "
            + ", ".join(missing)
        )
    if validated_manifest["allowed_paths"]:
        raise ContractError("cleanup reviewer context must grant no workspace paths")
    matches = [
        entry
        for entry in (
            *validated_manifest["entries"],
            *validated_manifest["on_demand"],
        )
        if entry.get("source") == CLEANUP_REVIEW_CONTEXT_SOURCE
    ]
    if len(matches) != 1 or matches[0] not in validated_manifest["entries"]:
        raise ContractError(
            "cleanup reviewer context requires exactly one included request entry"
        )
    entry = matches[0]
    expected_content = canonical_json(value).decode("utf-8")
    if entry.get("kind") != "decision" or entry.get("content") != expected_content:
        raise ContractError("cleanup reviewer context request entry is stale or malformed")
    return dict(entry)


def _integration_proof_complete(request: Mapping[str, Any]) -> bool:
    proof = request["integration_proof"]
    if proof["target_contains_integration_result"] is not True:
        return False
    if proof["strategy"] == "squash":
        return proof["patch_equivalent"] is True and proof["tree_equivalent"] is True
    return proof["ancestry_proven"] is True


def _risk_flags(validated_request: Mapping[str, Any]) -> tuple[str, ...]:
    facts = validated_request["cleanup_facts"]
    receipt = validated_request["integration_receipt"]
    flags: set[str] = set()
    observed_head = facts["observed_head"]
    if observed_head is None:
        flags.add("branch_missing")
    elif observed_head != validated_request["branch_head"]:
        flags.add("branch_moved")
    if facts["authority_available"] is not True:
        flags.add("cleanup_authority_unavailable")
    if facts["responsibility_evidence_id"] is None:
        flags.add("responsibility_evidence_missing")
    if facts["is_protected"]:
        flags.add("protected_branch")
    if facts["retained_pattern"]:
        flags.add("retained_pattern")
    if facts["remote_branch_status"] == "present":
        flags.add("remote_branch_present")
    elif facts["remote_branch_status"] == "unknown":
        flags.add("remote_status_unknown")
    if facts["checked_out"]:
        flags.add("branch_checked_out")
    if facts["linked_worktree_paths"]:
        flags.add("linked_worktree")
    for field, flag in _RESPONSIBILITY_RISKS.items():
        if facts["responsibilities"][field] is not True:
            flags.add(flag)
    for field, flag in _BLOCKER_RISKS.items():
        if facts["blockers"][field]:
            flags.add(flag)
    if receipt["source_commit"] != validated_request["branch_head"]:
        flags.add("integration_source_mismatch")
    if not _integration_proof_complete(validated_request):
        flags.add("integration_proof_incomplete")
    return tuple(sorted(flags))


def cleanup_review_risk_flags(request: Mapping[str, Any]) -> tuple[str, ...]:
    """Return only core-derived risk flags for a sealed request."""

    return _risk_flags(validate_cleanup_review_request(request))


def cleanup_review_delete_eligible(request: Mapping[str, Any]) -> bool:
    """Return whether current request facts permit a local deletion proposal."""

    flags = set(cleanup_review_risk_flags(request))
    return not (flags - _NONBLOCKING_RISKS)


def _validate_observation_document(
    observation: Mapping[str, Any], *, require_digest: bool
) -> dict[str, Any]:
    value = _mapping(observation, subject="cleanup review observation")
    fields = (
        OBSERVATION_FIELDS
        if require_digest
        else OBSERVATION_FIELDS - {"observation_digest"}
    )
    require_keys(value, fields, subject="cleanup review observation")
    reject_unknown_keys(value, fields, subject="cleanup review observation")
    if value["schema_version"] != OBSERVATION_SCHEMA_VERSION:
        raise ContractError("unsupported cleanup review observation schema_version")
    review_id = _nonempty(value["review_id"], subject="cleanup observation review_id")
    if _REVIEW_ID.fullmatch(review_id) is None:
        raise ContractError("cleanup review observation has an invalid review_id")
    for field in (
        "request_digest",
        "spec_hash",
        "config_hash",
        "integration_receipt_digest",
        "facts_digest",
    ):
        _sha256(value[field], subject=f"cleanup observation {field}")
    _nonempty(value["run_id"], subject="cleanup observation run_id")
    _revision(value["input_revision"], subject="cleanup observation input_revision")
    _branch(value["branch"], subject="cleanup observation branch")
    _object_id(value["branch_head"], subject="cleanup observation branch_head")
    if value["decision"] not in CLEANUP_DECISIONS:
        raise ContractError("cleanup review observation has an invalid decision")
    _nonempty(value["rationale"], subject="cleanup observation rationale")
    flags = value["risk_flags"]
    if (
        not isinstance(flags, list)
        or any(flag not in RISK_FLAGS for flag in flags)
        or len(flags) != len(set(flags))
        or flags != sorted(flags)
    ):
        raise ContractError("cleanup review risk_flags are not canonical")
    if require_digest:
        digest = _sha256(
            value["observation_digest"],
            subject="cleanup review observation_digest",
        )
        if digest != canonical_cleanup_review_observation_digest(value):
            raise ContractError("cleanup review observation digest mismatch")
    return value


def seal_cleanup_review_observation(
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    value = _validate_observation_document(observation, require_digest=False)
    return validate_cleanup_review_observation(
        {
            **value,
            "observation_digest": canonical_cleanup_review_observation_digest(value),
        }
    )


def validate_cleanup_review_observation(
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    return _validate_observation_document(observation, require_digest=True)


def validate_cleanup_review_observations(
    request: Mapping[str, Any], observations: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Bind exactly one reviewer observation to immutable core facts."""

    validated_request = validate_cleanup_review_request(request)
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise ContractError("cleanup review observations must be an array")
    if len(observations) != 1:
        raise ContractError("cleanup review requires exactly one observation")
    observation = validate_cleanup_review_observation(observations[0])
    bindings = {
        "review_id": validated_request["review_id"],
        "request_digest": validated_request["request_digest"],
        "run_id": validated_request["run_id"],
        "spec_hash": validated_request["spec_hash"],
        "config_hash": validated_request["config_hash"],
        "input_revision": validated_request["input_revision"],
        "branch": validated_request["branch"],
        "branch_head": validated_request["branch_head"],
        "integration_receipt_digest": validated_request["integration_receipt"][
            "receipt_digest"
        ],
        "facts_digest": validated_request["cleanup_facts"]["facts_digest"],
    }
    for field, expected in bindings.items():
        if observation[field] != expected:
            raise ContractError(f"cleanup review observation has stale {field}")
    expected_flags = list(_risk_flags(validated_request))
    if observation["risk_flags"] != expected_flags:
        raise ContractError("cleanup review observation omitted or invented core risk flags")
    if observation["decision"] == "delete_local" and (
        set(expected_flags) - _NONBLOCKING_RISKS
    ):
        raise ContractError("cleanup reviewer cannot delete a blocked local branch")
    return observation


def validate_cleanup_reviewer_adapter_result(
    result: Mapping[str, Any],
    *,
    adapter_request: Mapping[str, Any],
    review_request: Mapping[str, Any],
    expected_session_id: str,
) -> dict[str, Any]:
    """Validate a zero-capability cleanup reviewer adapter envelope."""

    request_envelope = validate_adapter_request(adapter_request)
    if request_envelope["role"] != "cleanup_reviewer":
        raise ContractError("cleanup reviewer adapter request has the wrong role")
    if request_envelope["allowed_capabilities"] != []:
        raise ContractError("cleanup reviewer adapter request must grant zero capabilities")
    validate_cleanup_review_context(
        request_envelope["context_manifest"], review_request
    )
    session_id = _nonempty(expected_session_id, subject="expected_session_id")
    normalized = adapter_result_to_dict(
        validate_adapter_result(result, request=request_envelope)
    )
    if normalized["status"] != "succeeded":
        raise ContractError("cleanup reviewer adapter result did not succeed")
    if normalized["session_id"] != session_id:
        raise ContractError("cleanup reviewer adapter result has a stale session_id")
    if normalized["candidate_commit"] is not None:
        raise ContractError("cleanup reviewer must not return a candidate commit")
    if normalized["changed_paths"]:
        raise ContractError("cleanup reviewer must not report changed paths")
    if normalized["requested_followups"]:
        raise ContractError("cleanup reviewer must not request follow-up work")
    observation = validate_cleanup_review_observations(
        review_request, normalized["observations"]
    )
    normalized["observations"] = [observation]
    return normalized


def deterministic_fake_cleanup_review(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return one deterministic, conservative decision over core facts."""

    value = validate_cleanup_review_request(request)
    flags = list(_risk_flags(value))
    blocking = set(flags) - _NONBLOCKING_RISKS
    if not blocking:
        decision = "delete_local"
        rationale = "core facts prove exact integration and no local cleanup blocker"
    elif blocking & _ADMINISTRATOR_RISKS:
        decision = "request_administrator"
        rationale = "core facts are stale, incomplete, or require an administrator decision"
    else:
        decision = "retain"
        rationale = "core facts record an active retention or responsibility blocker"
    observation = seal_cleanup_review_observation(
        {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "review_id": value["review_id"],
            "request_digest": value["request_digest"],
            "run_id": value["run_id"],
            "spec_hash": value["spec_hash"],
            "config_hash": value["config_hash"],
            "input_revision": value["input_revision"],
            "branch": value["branch"],
            "branch_head": value["branch_head"],
            "integration_receipt_digest": value["integration_receipt"][
                "receipt_digest"
            ],
            "facts_digest": value["cleanup_facts"]["facts_digest"],
            "decision": decision,
            "rationale": rationale,
            "risk_flags": flags,
        }
    )
    return validate_cleanup_review_observations(value, [observation])
