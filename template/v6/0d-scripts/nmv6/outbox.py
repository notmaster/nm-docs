"""Pure notification-outbox contracts and retry calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from .errors import ContractError
from .util import canonical_json, sha256_bytes


OUTBOX_SCHEMA_VERSION = "nm-v6/notification-outbox-v1"
VALID_SEVERITIES = frozenset({"progress", "attention"})
VALID_STATUSES = frozenset({"pending", "delivering", "delivered", "retry"})


@dataclass(frozen=True)
class NotificationIntent:
    route: str
    severity: str
    payload: dict[str, Any]
    notification_id: str | None = None


def notification_identity(*, event_id: str, route: str, severity: str) -> str:
    """Return the stable delivery idempotency identity."""

    if not event_id or not route:
        raise ContractError("notification event_id and route must be nonempty")
    if severity not in VALID_SEVERITIES:
        raise ContractError(f"unsupported notification severity: {severity!r}")
    material = {
        "event_id": event_id,
        "route": route,
        "schema_version": OUTBOX_SCHEMA_VERSION,
        "severity": severity,
    }
    return "NOTIFY-" + sha256_bytes(canonical_json(material))[:32]


def validate_intent(intent: NotificationIntent | Mapping[str, Any]) -> NotificationIntent:
    if isinstance(intent, NotificationIntent):
        value = intent
    else:
        value = NotificationIntent(
            route=str(intent.get("route", "")),
            severity=str(intent.get("severity", "")),
            payload=dict(intent.get("payload", {})),
            notification_id=(
                str(intent["notification_id"]) if intent.get("notification_id") else None
            ),
        )
    if not value.route:
        raise ContractError("notification route must be nonempty")
    if value.severity not in VALID_SEVERITIES:
        raise ContractError(f"unsupported notification severity: {value.severity!r}")
    if not isinstance(value.payload, dict):
        raise ContractError("notification payload must be an object")
    canonical_json(value.payload)
    return value


def retry_at(
    *,
    attempt_count: int,
    now: datetime | None = None,
    base_seconds: int = 5,
    maximum_seconds: int = 3600,
) -> str:
    """Calculate deterministic bounded exponential backoff."""

    if attempt_count < 1:
        raise ContractError("attempt_count must be positive")
    if base_seconds < 1 or maximum_seconds < base_seconds:
        raise ContractError("invalid outbox backoff bounds")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    delay = min(maximum_seconds, base_seconds * (2 ** min(attempt_count - 1, 20)))
    return (current.astimezone(UTC) + timedelta(seconds=delay)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
