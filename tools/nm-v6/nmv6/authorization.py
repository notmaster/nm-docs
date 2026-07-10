"""Trusted-control-plane record validation.

This module never creates an approval signature.  It accepts only detached
signatures made outside the agent capability boundary and verifies them against
administrator-controlled public keys.  Persistence and replay protection are
owned by :mod:`nmv6.reducer` in one SQLite transaction.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .errors import AuthorizationError
from .util import canonical_json, sha256_bytes, sha256_file


AUTHORIZATION_SCHEMA_VERSION = "nm-v6/authorization-v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

NONPROTECTED_REF_FIELDS = frozenset(
    {
        "grant_id",
        "action",
        "remote",
        "ref",
        "expected_sha",
        "force",
        "one_time",
        "expires_at",
    }
)

REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "spec_confirmation": frozenset(
        {
            "record_type",
            "confirmation_id",
            "spec_id",
            "version",
            "spec_hash",
            "decision",
            "administrator_identity",
            "issued_at",
            "nonce",
            "authenticator_id",
            "authenticator_signature",
        }
    ),
    "implementation_authorization": frozenset(
        {
            "record_type",
            "authorization_id",
            "spec_id",
            "version",
            "spec_hash",
            "implementation_scope",
            "administrator_identity",
            "issued_at",
            "expires_at",
            "nonce",
            "authenticator_id",
            "authenticator_signature",
        }
    ),
    "grant": frozenset(
        {
            "record_type",
            "grant_id",
            "run_id",
            "spec_hash",
            "config_hash",
            "allowed_actions",
            "allowed_environments",
            "allowed_protected_refs",
            "created_by",
            "created_at",
            "expires_at",
            "request_digest",
            "nonce",
            "grant_revision",
            "authenticator_id",
            "authenticator_signature",
        }
    ),
    "approval": frozenset(
        {
            "record_type",
            "approval_id",
            "run_id",
            "spec_hash",
            "config_hash",
            "allowed_actions",
            "allowed_environments",
            "allowed_protected_refs",
            "created_by",
            "created_at",
            "expires_at",
            "request_digest",
            "nonce",
            "grant_revision",
            "authenticator_id",
            "authenticator_signature",
        }
    ),
    "revocation": frozenset(
        {
            "record_type",
            "revocation_id",
            "target_authorization_id",
            "run_id",
            "issued_at",
            "nonce",
            "authenticator_id",
            "authenticator_signature",
        }
    ),
}

OPTIONAL_FIELDS: dict[str, frozenset[str]] = {
    "grant": frozenset({"one_time", "nonprotected_ref"}),
    "approval": frozenset({"one_time"}),
}


@dataclass(frozen=True)
class VerifiedAuthorization:
    authorization_id: str
    record_type: str
    run_id: str | None
    nonce: str
    authenticator_id: str
    issued_at: str
    expires_at: str | None
    request_digest: str | None
    target_authorization_id: str | None
    record_digest: str
    record: dict[str, Any]


def parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AuthorizationError(f"{field} must be an RFC3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AuthorizationError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise AuthorizationError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def signed_payload(record: Mapping[str, Any]) -> bytes:
    """Canonical bytes covered by an administrator signature."""

    return canonical_json(
        {key: value for key, value in record.items() if key != "authenticator_signature"}
    )


def record_identifier(record: Mapping[str, Any]) -> str:
    record_type = record.get("record_type")
    fields = {
        "spec_confirmation": "confirmation_id",
        "implementation_authorization": "authorization_id",
        "grant": "grant_id",
        "approval": "approval_id",
        "revocation": "revocation_id",
    }
    field = fields.get(str(record_type))
    if field is None or not isinstance(record.get(field), str) or not record[field]:
        raise AuthorizationError(f"invalid authorization identifier for {record_type!r}")
    return str(record[field])


def validate_authorization_record(
    record: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> VerifiedAuthorization:
    """Validate shape and time bounds, excluding cryptographic verification."""

    if not isinstance(record, Mapping):
        raise AuthorizationError("authorization record must be an object")
    record_type = str(record.get("record_type", ""))
    required = REQUIRED_FIELDS.get(record_type)
    if required is None:
        raise AuthorizationError(f"unsupported authorization record type: {record_type!r}")
    missing = sorted(required - set(record))
    if missing:
        raise AuthorizationError(
            f"{record_type} missing required fields: {', '.join(missing)}"
        )
    unknown = sorted(set(record) - required - OPTIONAL_FIELDS.get(record_type, frozenset()))
    if unknown:
        raise AuthorizationError(
            f"{record_type} contains unknown fields: {', '.join(unknown)}"
        )
    for field in ("nonce", "authenticator_id"):
        if not isinstance(record[field], str) or not record[field]:
            raise AuthorizationError(f"{field} must be a nonempty string")
    signature = record["authenticator_signature"]
    if not isinstance(signature, str) or not signature:
        raise AuthorizationError("authenticator_signature must be nonempty base64")
    try:
        base64.b64decode(signature, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AuthorizationError("authenticator_signature must be valid base64") from exc

    issued_field = "created_at" if record_type in {"grant", "approval"} else "issued_at"
    issued = parse_timestamp(record[issued_field], field=issued_field)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if issued > current:
        raise AuthorizationError("authorization issue time is in the future")
    expires_at = record.get("expires_at")
    if expires_at is not None:
        expiry = parse_timestamp(expires_at, field="expires_at")
        if expiry <= issued:
            raise AuthorizationError("authorization expiry must follow its issue time")
        if expiry <= current:
            raise AuthorizationError("authorization is expired")

    if record_type == "spec_confirmation":
        if record["decision"] != "confirmed":
            raise AuthorizationError("Spec confirmation decision must be 'confirmed'")
        if not isinstance(record["version"], int) or record["version"] < 1:
            raise AuthorizationError("Spec confirmation version must be positive")
    for field in ("spec_hash", "config_hash"):
        if field in record and not (
            isinstance(record[field], str) and SHA256_PATTERN.fullmatch(record[field])
        ):
            raise AuthorizationError(f"{field} must be a lowercase SHA-256 digest")
    if record_type in {"grant", "approval"}:
        if not isinstance(record["grant_revision"], int) or record["grant_revision"] < 0:
            raise AuthorizationError("grant_revision must be a nonnegative integer")
        for field in (
            "allowed_actions",
            "allowed_environments",
            "allowed_protected_refs",
        ):
            values = record[field]
            if not isinstance(values, list) or not all(
                isinstance(item, str) and item for item in values
            ):
                raise AuthorizationError(f"{field} must be a string array")
            if len(values) != len(set(values)):
                raise AuthorizationError(f"{field} must not contain duplicates")
        digest = record["request_digest"]
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            raise AuthorizationError("request_digest must be a lowercase SHA-256 digest")
        nonprotected_ref = record.get("nonprotected_ref")
        if nonprotected_ref is not None:
            if not isinstance(nonprotected_ref, Mapping):
                raise AuthorizationError("nonprotected_ref must be an object")
            missing_scope = sorted(NONPROTECTED_REF_FIELDS - set(nonprotected_ref))
            unknown_scope = sorted(set(nonprotected_ref) - NONPROTECTED_REF_FIELDS)
            if missing_scope or unknown_scope:
                details = []
                if missing_scope:
                    details.append(f"missing: {', '.join(missing_scope)}")
                if unknown_scope:
                    details.append(f"unknown: {', '.join(unknown_scope)}")
                raise AuthorizationError(
                    "nonprotected_ref fields are not exact (" + "; ".join(details) + ")"
                )
            for field in ("grant_id", "remote", "ref"):
                if not isinstance(nonprotected_ref[field], str) or not nonprotected_ref[field]:
                    raise AuthorizationError(
                        f"nonprotected_ref {field} must be a nonempty string"
                    )
            if nonprotected_ref["action"] not in {"push_backup", "delete_remote"}:
                raise AuthorizationError("nonprotected_ref action is unsupported")
            if not str(nonprotected_ref["ref"]).startswith("refs/heads/"):
                raise AuthorizationError("nonprotected_ref ref must be an exact branch ref")
            expected_sha = nonprotected_ref["expected_sha"]
            if not isinstance(expected_sha, str) or not GIT_OBJECT_PATTERN.fullmatch(
                expected_sha
            ):
                raise AuthorizationError(
                    "nonprotected_ref expected_sha must be an exact Git object ID"
                )
            if nonprotected_ref["force"] is not False:
                raise AuthorizationError("nonprotected_ref force must be false")
            if nonprotected_ref["one_time"] is not True or record.get("one_time") is not True:
                raise AuthorizationError("nonprotected_ref authorization must be one-time")
            parse_timestamp(
                nonprotected_ref["expires_at"], field="nonprotected_ref expires_at"
            )
            if nonprotected_ref["expires_at"] != record.get("expires_at"):
                raise AuthorizationError(
                    "nonprotected_ref expiry must equal the authorization expiry"
                )
            if record["allowed_actions"] != [nonprotected_ref["action"]]:
                raise AuthorizationError(
                    "nonprotected_ref authorization must allow only its exact action"
                )
            if record["allowed_environments"] or record["allowed_protected_refs"]:
                raise AuthorizationError(
                    "nonprotected_ref authorization cannot carry unrelated scope"
                )
    if record_type == "revocation" and not record["target_authorization_id"]:
        raise AuthorizationError("revocation target must be nonempty")

    normalized = dict(record)
    payload_digest = sha256_bytes(signed_payload(normalized))
    return VerifiedAuthorization(
        authorization_id=record_identifier(normalized),
        record_type=record_type,
        run_id=str(normalized["run_id"]) if normalized.get("run_id") else None,
        nonce=str(normalized["nonce"]),
        authenticator_id=str(normalized["authenticator_id"]),
        issued_at=str(normalized[issued_field]),
        expires_at=str(expires_at) if expires_at is not None else None,
        request_digest=(
            str(normalized["request_digest"])
            if normalized.get("request_digest") is not None
            else None
        ),
        target_authorization_id=(
            str(normalized["target_authorization_id"])
            if normalized.get("target_authorization_id")
            else None
        ),
        record_digest=payload_digest,
        record=normalized,
    )


class OpenSSLSignatureVerifier:
    """Verify detached administrator signatures with pinned public keys."""

    def __init__(
        self,
        public_keys: Mapping[str, str | Path],
        *,
        openssl_binary: str = "openssl",
    ) -> None:
        if not public_keys:
            raise AuthorizationError("at least one trusted authenticator is required")
        executable = shutil.which(openssl_binary)
        if executable is None:
            raise AuthorizationError(f"OpenSSL executable is unavailable: {openssl_binary}")
        self._openssl = executable
        self._keys = {name: Path(path).resolve() for name, path in public_keys.items()}
        self._key_digests: dict[str, str] = {}
        for name, path in self._keys.items():
            if not name or not path.is_file():
                raise AuthorizationError(f"trusted public key is unavailable for {name!r}")
            self._key_digests[name] = sha256_file(path)

    def verify(
        self,
        record: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> VerifiedAuthorization:
        verified = validate_authorization_record(record, now=now)
        key = self._keys.get(verified.authenticator_id)
        if key is None:
            raise AuthorizationError(
                f"untrusted authenticator: {verified.authenticator_id!r}"
            )
        if not key.is_file() or sha256_file(key) != self._key_digests[verified.authenticator_id]:
            raise AuthorizationError("trusted authenticator public key changed after pinning")
        try:
            signature = base64.b64decode(
                str(record["authenticator_signature"]), validate=True
            )
        except (ValueError, binascii.Error) as exc:
            raise AuthorizationError("invalid base64 signature") from exc
        with tempfile.TemporaryDirectory(prefix="nm-v6-auth-verify-") as directory:
            root = Path(directory)
            payload_path = root / "payload.json"
            signature_path = root / "signature.bin"
            payload_path.write_bytes(signed_payload(record))
            signature_path.write_bytes(signature)
            result = subprocess.run(
                [
                    self._openssl,
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(key),
                    "-signature",
                    str(signature_path),
                    str(payload_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=15,
            )
        if result.returncode != 0:
            raise AuthorizationError("administrator signature verification failed")
        return verified


def authorization_scope_allows(
    record: Mapping[str, Any],
    *,
    run_id: str,
    spec_hash: str,
    config_hash: str,
    action: str,
    environment: str | None = None,
    protected_ref: str | None = None,
    expected_revision: int | None = None,
) -> bool:
    """Check an exact scope without broadening absent fields."""

    if record.get("record_type") not in {"grant", "approval"}:
        return False
    if record.get("run_id") != run_id:
        return False
    if record.get("spec_hash") != spec_hash or record.get("config_hash") != config_hash:
        return False
    if action not in record.get("allowed_actions", []):
        return False
    if environment is not None and environment not in record.get(
        "allowed_environments", []
    ):
        return False
    if protected_ref is not None and protected_ref not in record.get(
        "allowed_protected_refs", []
    ):
        return False
    if expected_revision is not None and record.get("grant_revision") != expected_revision:
        return False
    return True


def authorization_request_digest(request: Mapping[str, Any]) -> str:
    """Digest a challenge request while excluding any displayed helper fields."""

    return sha256_bytes(canonical_json(dict(request)))
