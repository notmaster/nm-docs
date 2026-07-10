"""Append-only audit-chain helpers.

The database owns persistence.  This module deliberately contains only
canonicalization, verification, and export helpers so no second writer can
emerge beside :class:`nmv6.reducer.Reducer`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import TransitionError
from .util import atomic_write, canonical_json, sha256_bytes


GENESIS_DIGEST = "0" * 64
AUDIT_EXPORT_VERSION = "nm-v6/audit-export-v1"


@dataclass(frozen=True)
class AuditRecord:
    sequence: int
    event_id: str
    event_type: str
    actor: str
    run_id: str | None
    run_revision: int | None
    previous_digest: str
    event_digest: str
    audit_digest: str
    payload: dict[str, Any]
    created_at: str


def audit_material(
    *,
    sequence: int,
    event_id: str,
    event_type: str,
    actor: str,
    run_id: str | None,
    run_revision: int | None,
    previous_digest: str,
    event_digest: str,
    payload: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    """Return the exact mapping committed by the audit digest."""

    return {
        "actor": actor,
        "created_at": created_at,
        "event_digest": event_digest,
        "event_id": event_id,
        "event_type": event_type,
        "payload": dict(payload),
        "previous_digest": previous_digest,
        "run_id": run_id,
        "run_revision": run_revision,
        "sequence": sequence,
    }


def calculate_audit_digest(**fields: Any) -> str:
    return sha256_bytes(canonical_json(audit_material(**fields)))


def _mapping(row: Mapping[str, Any] | AuditRecord) -> Mapping[str, Any]:
    if isinstance(row, AuditRecord):
        return row.__dict__
    return row


def verify_audit_chain(rows: Iterable[Mapping[str, Any] | AuditRecord]) -> str:
    """Verify ordering, linkage, and every content digest.

    Returns the final digest, or the all-zero genesis digest for an empty
    chain.  Any mismatch is a high-impact state-integrity failure.
    """

    previous = GENESIS_DIGEST
    expected_sequence = 1
    for raw in rows:
        row = _mapping(raw)
        sequence = int(row["sequence"])
        if sequence != expected_sequence:
            raise TransitionError(
                f"audit sequence discontinuity: expected {expected_sequence}, got {sequence}"
            )
        if row["previous_digest"] != previous:
            raise TransitionError(f"audit chain mismatch at sequence {sequence}")
        payload = row.get("payload")
        if payload is None:
            payload = json.loads(str(row["payload_json"]))
        actual = calculate_audit_digest(
            sequence=sequence,
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            actor=str(row["actor"]),
            run_id=row.get("run_id"),
            run_revision=row.get("run_revision"),
            previous_digest=str(row["previous_digest"]),
            event_digest=str(row["event_digest"]),
            payload=payload,
            created_at=str(row["created_at"]),
        )
        if actual != row["audit_digest"]:
            raise TransitionError(f"audit digest mismatch at sequence {sequence}")
        previous = actual
        expected_sequence += 1
    return previous


def export_audit(rows: Iterable[Mapping[str, Any] | AuditRecord], path: Path) -> dict[str, Any]:
    """Write a deterministic, restart-stable audit export."""

    normalized: list[dict[str, Any]] = []
    for raw in rows:
        row = _mapping(raw)
        payload = row.get("payload")
        if payload is None:
            payload = json.loads(str(row["payload_json"]))
        normalized.append(
            {
                "sequence": int(row["sequence"]),
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "run_id": row.get("run_id"),
                "run_revision": row.get("run_revision"),
                "previous_digest": row["previous_digest"],
                "event_digest": row["event_digest"],
                "audit_digest": row["audit_digest"],
                "payload": payload,
                "created_at": row["created_at"],
            }
        )
    final_digest = verify_audit_chain(normalized)
    document = {
        "schema_version": AUDIT_EXPORT_VERSION,
        "record_count": len(normalized),
        "final_digest": final_digest,
        "records": normalized,
    }
    atomic_write(path, canonical_json(document) + b"\n")
    return document
