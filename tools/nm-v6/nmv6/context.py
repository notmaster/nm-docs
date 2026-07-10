"""Content-addressed, budgeted context manifests and audited additions."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .contracts import contract_digest, validate_context_manifest
from .errors import ContractError
from .util import canonical_json, ensure_relative_path, sha256_bytes, utc_now


CONTEXT_KINDS = {
    "invariant",
    "goal",
    "requirement",
    "acceptance",
    "phase",
    "task",
    "dependency",
    "interface",
    "decision",
    "acceptance_action",
    "reference",
}
REQUIRED_CONTEXT_KINDS = {
    "invariant",
    "goal",
    "requirement",
    "acceptance",
    "phase",
    "task",
    "acceptance_action",
}
SECRET_MARKER_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:ghp_|github_pat_|sk-|xox[bp]-)[A-Za-z0-9_-]+|"
    r"open-apis/bot/v2/hook/[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContextItem:
    kind: str
    source: str
    content: str
    entry_id: str | None = None


def estimate_tokens(content: str | bytes) -> int:
    """Return the deterministic conservative byte/4 estimate used by V6."""

    data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    return max(1, (len(data) + 3) // 4)


def _coerce_item(value: ContextItem | Mapping[str, Any], *, index: int) -> ContextItem:
    if isinstance(value, ContextItem):
        item = value
    elif isinstance(value, Mapping):
        allowed = {"kind", "source", "content", "entry_id"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ContractError(f"context item has unknown fields: {', '.join(unknown)}")
        try:
            item = ContextItem(
                kind=value["kind"],
                source=value["source"],
                content=value["content"],
                entry_id=value.get("entry_id"),
            )
        except KeyError as exc:
            raise ContractError(f"context item missing field: {exc.args[0]}") from exc
    else:
        raise ContractError("context items must be ContextItem values or objects")
    if item.kind not in CONTEXT_KINDS:
        raise ContractError(f"unsupported context kind: {item.kind!r}")
    if not isinstance(item.source, str) or not item.source:
        raise ContractError("context item source must be a nonempty string")
    if not isinstance(item.content, str) or not item.content:
        raise ContractError("context item content must be nonempty UTF-8 text")
    if SECRET_MARKER_RE.search(item.content):
        raise ContractError(f"context item {item.source!r} contains credential material")
    entry_id = item.entry_id
    if entry_id is not None and (not isinstance(entry_id, str) or not entry_id):
        raise ContractError("context entry_id must be a nonempty string")
    return item


def _entry(item: ContextItem, *, index: int, include_content: bool) -> dict[str, Any]:
    content_bytes = item.content.encode("utf-8")
    digest = sha256_bytes(content_bytes)
    entry_id = item.entry_id or f"CTX-{item.kind.upper()}-{digest[:16]}-{index:03d}"
    result: dict[str, Any] = {
        "entry_id": entry_id,
        "kind": item.kind,
        "source": item.source,
        "digest": f"sha256:{digest}",
        "byte_size": len(content_bytes),
        "estimated_tokens": estimate_tokens(content_bytes),
    }
    if include_content:
        result["content"] = item.content
    return result


def _with_digest(manifest: dict[str, Any]) -> dict[str, Any]:
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest["manifest_digest"] = "sha256:" + sha256_bytes(canonical_json(unsigned))
    return manifest


def _check_budget(
    manifest: Mapping[str, Any],
    *,
    max_manifest_bytes: int,
    max_estimated_tokens: int,
) -> None:
    if isinstance(max_manifest_bytes, bool) or not isinstance(max_manifest_bytes, int) or max_manifest_bytes <= 0:
        raise ContractError("max_manifest_bytes must be a positive integer")
    if isinstance(max_estimated_tokens, bool) or not isinstance(max_estimated_tokens, int) or max_estimated_tokens <= 0:
        raise ContractError("max_estimated_tokens must be a positive integer")
    encoded_size = len(canonical_json(manifest))
    if encoded_size > max_manifest_bytes:
        raise ContractError(
            f"context manifest exceeds byte budget: {encoded_size} > {max_manifest_bytes}"
        )
    token_count = manifest["totals"]["estimated_tokens"]
    if token_count > max_estimated_tokens:
        raise ContractError(
            f"context manifest exceeds token budget: {token_count} > {max_estimated_tokens}"
        )


def build_context_manifest(
    *,
    attempt_id: str,
    items: Sequence[ContextItem | Mapping[str, Any]],
    on_demand_items: Sequence[ContextItem | Mapping[str, Any]] = (),
    allowed_paths: Iterable[str],
    prohibited_paths: Iterable[str],
    expected_result_schema: str = "nm-v6/adapter-result-v1",
    max_manifest_bytes: int,
    max_estimated_tokens: int,
) -> dict[str, Any]:
    """Build and validate one minimal Attempt context manifest."""

    coerced = [_coerce_item(value, index=index) for index, value in enumerate(items, start=1)]
    kinds = {item.kind for item in coerced}
    missing_kinds = sorted(REQUIRED_CONTEXT_KINDS - kinds)
    if missing_kinds:
        raise ContractError(
            "context is missing required slices: " + ", ".join(missing_kinds)
        )
    included = [_entry(item, index=index, include_content=True) for index, item in enumerate(coerced, start=1)]
    references = [
        _entry(_coerce_item(value, index=index), index=index, include_content=False)
        for index, value in enumerate(on_demand_items, start=1)
    ]
    included_ids = {entry["entry_id"] for entry in included}
    reference_ids = {entry["entry_id"] for entry in references}
    if len(included_ids) != len(included) or len(reference_ids) != len(references):
        raise ContractError("context entry identifiers must be unique")
    if included_ids & reference_ids:
        raise ContractError("included and on-demand context identifiers overlap")

    allowed = [ensure_relative_path(path, field="allowed path") for path in allowed_paths]
    prohibited = [ensure_relative_path(path, field="prohibited path") for path in prohibited_paths]
    manifest = {
        "schema_version": "nm-v6/context-manifest-v1",
        "attempt_id": attempt_id,
        "entries": included,
        "on_demand": references,
        "allowed_paths": sorted(set(allowed)),
        "prohibited_paths": sorted(set(prohibited)),
        "expected_result_schema": expected_result_schema,
        "totals": {
            "byte_size": sum(entry["byte_size"] for entry in included),
            "estimated_tokens": sum(entry["estimated_tokens"] for entry in included),
        },
    }
    _with_digest(manifest)
    validate_context_manifest(manifest)
    _check_budget(
        manifest,
        max_manifest_bytes=max_manifest_bytes,
        max_estimated_tokens=max_estimated_tokens,
    )
    return manifest


def propose_on_demand_addition(
    manifest: Mapping[str, Any],
    *,
    entry_id: str,
    content: str,
    reason: str,
    requested_by: str,
    max_manifest_bytes: int,
    max_estimated_tokens: int,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create an auditable proposal plus the deterministic resulting manifest.

    The caller must persist/authorize the audit proposal before treating the
    returned manifest as active.  This function performs no state write.
    """

    validated = validate_context_manifest(manifest)
    if not isinstance(content, str) or not content:
        raise ContractError("on-demand content must be nonempty text")
    if SECRET_MARKER_RE.search(content):
        raise ContractError("on-demand context contains credential material")
    if not isinstance(reason, str) or not reason.strip():
        raise ContractError("on-demand context requires a reason")
    if not isinstance(requested_by, str) or not requested_by:
        raise ContractError("on-demand context requires an actor")
    matches = [entry for entry in validated["on_demand"] if entry["entry_id"] == entry_id]
    if len(matches) != 1:
        raise ContractError(f"unknown or ambiguous on-demand context entry: {entry_id}")
    reference = matches[0]
    encoded = content.encode("utf-8")
    if reference["byte_size"] != len(encoded):
        raise ContractError("on-demand content byte size differs from its reference")
    if reference["digest"].removeprefix("sha256:") != sha256_bytes(encoded):
        raise ContractError("on-demand content digest differs from its reference")
    if reference["estimated_tokens"] != estimate_tokens(encoded):
        raise ContractError("on-demand content token estimate differs from its reference")

    updated = copy.deepcopy(validated)
    updated["on_demand"] = [
        entry for entry in updated["on_demand"] if entry["entry_id"] != entry_id
    ]
    materialized = dict(reference)
    materialized["content"] = content
    updated["entries"].append(materialized)
    updated["totals"] = {
        "byte_size": updated["totals"]["byte_size"] + reference["byte_size"],
        "estimated_tokens": updated["totals"]["estimated_tokens"]
        + reference["estimated_tokens"],
    }
    _with_digest(updated)
    validate_context_manifest(updated)
    _check_budget(
        updated,
        max_manifest_bytes=max_manifest_bytes,
        max_estimated_tokens=max_estimated_tokens,
    )
    event_time = timestamp or utc_now()
    audit_event = {
        "event_type": "context_on_demand_requested",
        "actor": requested_by,
        "timestamp": event_time,
        "attempt_id": validated["attempt_id"],
        "entry_id": entry_id,
        "entry_digest": reference["digest"],
        "reason": reason.strip(),
        "manifest_digest_before": validated["manifest_digest"],
        "manifest_digest_after": updated["manifest_digest"],
    }
    proposal = {
        "schema_version": "nm-v6/context-addition-proposal-v1",
        "proposal_id": contract_digest(audit_event),
        "attempt_id": validated["attempt_id"],
        "entry_id": entry_id,
        "reason": reason.strip(),
        "requested_by": requested_by,
        "requested_at": event_time,
        "manifest_digest_before": validated["manifest_digest"],
        "manifest_digest_after": updated["manifest_digest"],
        "new_totals": dict(updated["totals"]),
        "audit_event": audit_event,
        "updated_manifest": updated,
    }
    return proposal


def apply_on_demand_proposal(
    current_manifest: Mapping[str, Any], proposal: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the proposed manifest only when it is bound to current state."""

    current = validate_context_manifest(current_manifest)
    if proposal.get("schema_version") != "nm-v6/context-addition-proposal-v1":
        raise ContractError("unsupported context addition proposal version")
    if proposal.get("manifest_digest_before") != current["manifest_digest"]:
        raise ContractError("context addition proposal is stale")
    updated = validate_context_manifest(
        proposal.get("updated_manifest") if isinstance(proposal, Mapping) else {}
    )
    if proposal.get("manifest_digest_after") != updated["manifest_digest"]:
        raise ContractError("context addition proposal result digest is invalid")
    return updated
