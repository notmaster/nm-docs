"""Versioned in-process proposal and observation records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TransitionProposal:
    run_id: str
    expected_revision: int
    event: str
    actor: str
    idempotency_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    gate_ids: tuple[str, ...] = ()
    authorization_id: str | None = None
    fencing_token: int | None = None


@dataclass(frozen=True)
class GateObservation:
    gate_type: str
    subject_ids: tuple[str, ...]
    context: dict[str, Any]
    evidence_ids: tuple[str, ...]
    evaluator: str
    authorization_id: str | None = None


@dataclass(frozen=True)
class OperationObservation:
    operation_id: str
    action_id: str
    status: str
    effect_id: str | None
    result: dict[str, Any]


@dataclass(frozen=True)
class AdapterResult:
    protocol_version: str
    operation_id: str
    attempt_id: str
    status: str
    session_id: str | None
    candidate_commit: str | None
    changed_paths: tuple[str, ...]
    observations: tuple[dict[str, Any], ...]
    requested_followups: tuple[dict[str, Any], ...]
    usage: dict[str, Any]
    diagnostics: dict[str, Any]
