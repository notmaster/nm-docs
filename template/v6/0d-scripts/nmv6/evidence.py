"""Crash-safe redacted content-addressed evidence storage."""

from __future__ import annotations

import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .errors import EvidenceError
from .failpoints import checkpoint
from .util import canonical_json, sha256_bytes, sha256_file, utc_now


EVIDENCE_SCHEMA_VERSION = "nm-v6/evidence-receipt-v1"
REDACTION_VERSION = "nm-v6/exact-secret-redaction-v1"
REDACTION_MARKER = b"[REDACTED]"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BOUND_DIGEST_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")

REQUIRED_RECEIPT_FIELDS = frozenset(
    {
        "evidence_id",
        "evidence_type",
        "producer",
        "run_id",
        "subject_ids",
        "assertions",
        "spec_hash",
        "config_hash",
        "source_commit",
        "candidate_commit",
        "release_source_kind",
        "release_source_commit",
        "release_source_tree",
        "hotfix_reconciliation_gate_id",
        "artifact_digest",
        "environment_id",
        "environment_fingerprint",
        "operation_id",
        "attempt_id",
        "command_action_id",
        "argv_digest",
        "working_directory",
        "started_at",
        "finished_at",
        "exit_code",
        "result",
        "stdout_digest",
        "stderr_digest",
        "tool_versions",
        "producer_version",
        "evaluator_version",
        "redaction_version",
    }
)


def _bytes(value: str | bytes, *, field: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise EvidenceError(f"{field} must contain only str or bytes values")


def redact_output(
    data: bytes,
    *,
    secret_values: Iterable[str | bytes] = (),
    forbidden_patterns: Iterable[str | bytes] = (),
) -> bytes:
    """Redact exact secret bytes entirely in memory before disk persistence."""

    if not isinstance(data, bytes):
        raise EvidenceError("evidence output must be bytes")
    denied = [_bytes(value, field="forbidden_patterns") for value in forbidden_patterns]
    if any(not pattern for pattern in denied):
        raise EvidenceError("forbidden redaction patterns must be nonempty")
    for pattern in denied:
        if pattern in data:
            raise EvidenceError("output matched a declared unredactable secret pattern")
    secrets = sorted(
        {_bytes(value, field="secret_values") for value in secret_values},
        key=len,
        reverse=True,
    )
    if any(not secret for secret in secrets):
        raise EvidenceError("empty secret values cannot be redacted reliably")
    result = data
    for secret in secrets:
        result = result.replace(secret, REDACTION_MARKER)
    if any(secret in result for secret in secrets):
        raise EvidenceError("secret bytes remain after redaction")
    return result


class EvidenceStore:
    """Persist only successfully redacted bytes, never raw action output."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.blob_root = self.root / "blobs" / "sha256"
        self.quarantine_root = self.root / "quarantine"
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self.quarantine_root.mkdir(parents=True, exist_ok=True)

    def blob_path(self, digest: str) -> Path:
        if not SHA256_PATTERN.fullmatch(digest):
            raise EvidenceError(f"invalid evidence SHA-256 digest: {digest!r}")
        return self.blob_root / digest[:2] / digest

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            if os.name == "posix":
                raise EvidenceError(f"cannot fsync evidence directory {path}: {exc}") from exc
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _persist_blob(self, data: bytes) -> str:
        digest = sha256_bytes(data)
        destination = self.blob_path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".nm-v6-evidence-", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            checkpoint("evidence.before_blob_write")
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                checkpoint("evidence.after_blob_write")
                os.fsync(stream.fileno())
                checkpoint("evidence.after_blob_fsync")
            if destination.exists():
                if sha256_file(destination) != digest:
                    raise EvidenceError(f"existing evidence blob is corrupt: {destination}")
                temporary.unlink(missing_ok=True)
            else:
                checkpoint("evidence.before_blob_rename")
                os.replace(temporary, destination)
                checkpoint("evidence.after_blob_rename")
                self._fsync_directory(destination.parent)
                checkpoint("evidence.after_directory_fsync")
            if sha256_file(destination) != digest:
                raise EvidenceError("persisted evidence digest mismatch")
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def persist(
        self,
        receipt: Mapping[str, Any],
        stdout: bytes,
        stderr: bytes,
        *,
        secret_values: Iterable[str | bytes] = (),
        forbidden_patterns: Iterable[str | bytes] = (),
    ) -> dict[str, Any]:
        """Redact both streams first, then durably persist and bind digests."""

        # Both operations complete before either byte stream reaches disk.
        secrets = tuple(secret_values)
        denied = tuple(forbidden_patterns)
        redacted_stdout = redact_output(
            stdout, secret_values=secrets, forbidden_patterns=denied
        )
        redacted_stderr = redact_output(
            stderr, secret_values=secrets, forbidden_patterns=denied
        )
        stdout_digest = self._persist_blob(redacted_stdout)
        stderr_digest = self._persist_blob(redacted_stderr)
        result = dict(receipt)
        result.setdefault("schema_version", EVIDENCE_SCHEMA_VERSION)
        result["stdout_digest"] = stdout_digest
        result["stderr_digest"] = stderr_digest
        result["redaction_version"] = REDACTION_VERSION
        result.setdefault("collected_at", utc_now())
        self.validate(result)
        return result

    def read_blob(self, digest: str) -> bytes:
        path = self.blob_path(digest)
        if not path.is_file():
            raise EvidenceError(f"evidence blob is missing: {digest}")
        data = path.read_bytes()
        if sha256_bytes(data) != digest:
            raise EvidenceError(f"evidence blob digest mismatch: {digest}")
        return data

    def validate(self, receipt: Mapping[str, Any], *, check_blobs: bool = True) -> None:
        if not isinstance(receipt, Mapping):
            raise EvidenceError("evidence receipt must be an object")
        missing = sorted(REQUIRED_RECEIPT_FIELDS - set(receipt))
        if missing:
            raise EvidenceError(f"evidence receipt missing fields: {', '.join(missing)}")
        if receipt.get("schema_version", EVIDENCE_SCHEMA_VERSION) != EVIDENCE_SCHEMA_VERSION:
            raise EvidenceError("unsupported evidence schema version")
        for field in (
            "evidence_id",
            "evidence_type",
            "producer",
            "run_id",
            "spec_hash",
            "config_hash",
            "working_directory",
            "started_at",
            "finished_at",
            "result",
            "producer_version",
            "evaluator_version",
        ):
            if not isinstance(receipt[field], str) or not receipt[field]:
                raise EvidenceError(f"evidence field {field} must be nonempty")
        producer = str(receipt["producer"]).lower()
        if producer.startswith("agent") or producer.startswith("worker"):
            raise EvidenceError("agent self-report cannot be core-produced evidence")
        if not isinstance(receipt["subject_ids"], list) or not receipt["subject_ids"] or not all(
            isinstance(item, str) and item for item in receipt["subject_ids"]
        ):
            raise EvidenceError("subject_ids must be a nonempty-string array")
        if len(receipt["subject_ids"]) != len(set(receipt["subject_ids"])):
            raise EvidenceError("subject_ids must be unique")
        assertions = receipt["assertions"]
        if not isinstance(assertions, Mapping) or not all(
            isinstance(name, str)
            and bool(name)
            and isinstance(value, bool)
            for name, value in assertions.items()
        ):
            raise EvidenceError("assertions must map nonempty names to booleans")
        if not isinstance(receipt["tool_versions"], dict):
            raise EvidenceError("tool_versions must be an object")
        if receipt["redaction_version"] != REDACTION_VERSION:
            raise EvidenceError("unknown evidence redaction version")
        for field in ("spec_hash", "config_hash", "argv_digest"):
            value = receipt[field]
            if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
                raise EvidenceError(f"{field} must be a lowercase SHA-256 digest")
        timestamps: list[datetime] = []
        for field in ("started_at", "finished_at"):
            value = str(receipt[field])
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise EvidenceError(f"{field} must be an RFC3339 timestamp") from exc
            if parsed.tzinfo is None:
                raise EvidenceError(f"{field} must include a timezone")
            timestamps.append(parsed.astimezone(UTC))
        if timestamps[1] < timestamps[0]:
            raise EvidenceError("evidence finished_at precedes started_at")
        if receipt["result"] not in {
            "passed",
            "failed",
            "partial",
            "unknown",
            "not_applicable",
        }:
            raise EvidenceError("invalid evidence result")
        for field in ("stdout_digest", "stderr_digest"):
            digest = receipt[field]
            if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
                raise EvidenceError(f"{field} must bind stored redacted bytes")
            if check_blobs:
                self.read_blob(digest)
        for field in (
            "source_commit",
            "candidate_commit",
            "release_source_kind",
            "release_source_commit",
            "release_source_tree",
            "hotfix_reconciliation_gate_id",
            "artifact_digest",
            "environment_id",
            "environment_fingerprint",
            "operation_id",
            "attempt_id",
            "command_action_id",
        ):
            if receipt[field] is not None and not isinstance(receipt[field], str):
                raise EvidenceError(f"{field} must be a string or null")
            if isinstance(receipt[field], str) and not receipt[field]:
                raise EvidenceError(f"{field} cannot be an empty string")
        release_source_kind = receipt["release_source_kind"]
        if release_source_kind not in {None, "dev", "hotfix_stable"}:
            raise EvidenceError("invalid release_source_kind")
        if release_source_kind is not None:
            for field in (
                "release_source_commit",
                "release_source_tree",
                "artifact_digest",
            ):
                if not receipt[field]:
                    raise EvidenceError(f"release evidence requires {field}")
        if release_source_kind == "hotfix_stable" and not receipt[
            "hotfix_reconciliation_gate_id"
        ]:
            raise EvidenceError(
                "hotfix release evidence requires a reconciliation result gate"
            )
        if receipt["artifact_digest"] is not None and not BOUND_DIGEST_PATTERN.fullmatch(
            str(receipt["artifact_digest"])
        ):
            raise EvidenceError("artifact_digest must be SHA-256 when present")
        if receipt["environment_id"] is not None:
            if not receipt["environment_fingerprint"] or not receipt["artifact_digest"]:
                raise EvidenceError(
                    "environment evidence requires fingerprint and artifact binding"
                )
        if not isinstance(receipt["exit_code"], int):
            raise EvidenceError("exit_code must be an integer")
        canonical_json(dict(receipt))

    def receipt_digest(self, receipt: Mapping[str, Any]) -> str:
        self.validate(receipt)
        return sha256_bytes(canonical_json(dict(receipt)))

    def quarantine_orphans(
        self,
        referenced_digests: Iterable[str],
        *,
        grace_seconds: float = 0,
        now: float | None = None,
    ) -> list[Path]:
        """Quarantine, never bless, unreferenced digest blobs after grace."""

        if grace_seconds < 0:
            raise EvidenceError("orphan grace period cannot be negative")
        referenced = set(referenced_digests)
        current = time.time() if now is None else now
        quarantined: list[Path] = []
        for path in sorted(self.blob_root.glob("[0-9a-f][0-9a-f]/*")):
            if not path.is_file() or not SHA256_PATTERN.fullmatch(path.name):
                continue
            if path.name in referenced or current - path.stat().st_mtime < grace_seconds:
                continue
            if sha256_file(path) != path.name:
                suffix = "corrupt"
            else:
                suffix = "orphan"
            target = self.quarantine_root / f"{path.name}.{suffix}"
            counter = 1
            while target.exists():
                target = self.quarantine_root / f"{path.name}.{suffix}.{counter}"
                counter += 1
            os.replace(path, target)
            self._fsync_directory(path.parent)
            self._fsync_directory(self.quarantine_root)
            quarantined.append(target)
        for temporary in sorted(self.blob_root.glob("[0-9a-f][0-9a-f]/.nm-v6-evidence-*")):
            if current - temporary.stat().st_mtime < grace_seconds:
                continue
            target = self.quarantine_root / f"{temporary.name}.{int(current)}.temporary"
            os.replace(temporary, target)
            self._fsync_directory(temporary.parent)
            self._fsync_directory(self.quarantine_root)
            quarantined.append(target)
        return quarantined

    def validate_all(self, receipts: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        referenced: set[str] = set()
        for receipt in receipts:
            self.validate(receipt)
            referenced.add(str(receipt["stdout_digest"]))
            referenced.add(str(receipt["stderr_digest"]))
        blob_count = sum(
            1 for path in self.blob_root.glob("[0-9a-f][0-9a-f]/*") if path.is_file()
        )
        return {"receipts": len(receipts), "referenced_blobs": len(referenced), "blobs": blob_count}
