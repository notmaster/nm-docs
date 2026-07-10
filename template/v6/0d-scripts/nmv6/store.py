"""Single SQLite runtime authority for NM V6.

All SQL mutation helpers are private.  The public mutation surface is the
domain-aware :class:`nmv6.reducer.Reducer`; public methods here are read-only
except explicit initialization, integrity verification, and projection rebuild.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .audit import GENESIS_DIGEST, calculate_audit_digest, verify_audit_chain
from .errors import RecoveryError, TransitionError
from .failpoints import checkpoint
from .outbox import NotificationIntent, notification_identity, validate_intent
from .util import canonical_json, sha256_bytes, sha256_file, utc_now


EVENT_GENESIS_DIGEST = "0" * 64
MIGRATION_PATTERN = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql$")


class Store:
    """Own one configured SQLite connection and its deterministic schema."""

    def __init__(
        self,
        path: str | Path,
        *,
        busy_timeout_ms: int = 5000,
        initialize: bool = True,
    ) -> None:
        if busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be positive")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout_ms = busy_timeout_ms
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=busy_timeout_ms / 1000,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._configure_connection()
        if initialize:
            self.initialize()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _configure_connection(self) -> None:
        connection = self._connection
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise RecoveryError(f"SQLite refused WAL mode: {mode!r}")

    def initialize(self) -> None:
        with self._lock:
            self._apply_migrations()
            self.integrity_check()

    def _migration_files(self) -> list[tuple[int, str, Path]]:
        root = Path(__file__).with_name("migrations")
        result: list[tuple[int, str, Path]] = []
        for path in sorted(root.glob("*.sql")):
            match = MIGRATION_PATTERN.match(path.name)
            if match is None:
                raise RecoveryError(f"invalid migration filename: {path.name}")
            result.append((int(match.group("version")), match.group("name"), path))
        if not result:
            raise RecoveryError("NM V6 has no SQLite migrations")
        versions = [version for version, _, _ in result]
        if versions != list(range(1, len(versions) + 1)):
            raise RecoveryError(f"SQLite migrations are not contiguous: {versions}")
        return result

    @staticmethod
    def _sql_statements(text: str) -> Iterator[str]:
        buffer = ""
        for line in text.splitlines(keepends=True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                statement = buffer.strip()
                buffer = ""
                if statement:
                    yield statement
        if buffer.strip():
            raise RecoveryError("incomplete SQL migration statement")

    def _current_migration(self) -> int:
        table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if table is None:
            return 0
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()
        return int(row["version"])

    def _backup_before_migration(self, current: int, target: int) -> Path:
        backup = self.path.with_name(f"{self.path.name}.pre-v{target}.backup")
        temporary = backup.with_suffix(backup.suffix + ".tmp")
        temporary.unlink(missing_ok=True)
        target_connection = sqlite3.connect(temporary)
        try:
            self._connection.backup(target_connection)
            target_connection.execute("PRAGMA synchronous = FULL")
            target_connection.commit()
        finally:
            target_connection.close()
        temporary.replace(backup)
        if current > 0 and backup.stat().st_size == 0:
            raise RecoveryError("SQLite migration backup is empty")
        return backup

    def _apply_migrations(self) -> None:
        migrations = self._migration_files()
        current = self._current_migration()
        if current > len(migrations):
            raise RecoveryError(
                f"database schema version {current} is newer than this core ({len(migrations)})"
            )
        for version, name, path in migrations:
            if version <= current:
                row = self._connection.execute(
                    "SELECT digest FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone()
                if row is None or row["digest"] != sha256_file(path):
                    raise RecoveryError(f"applied migration digest drift: {path.name}")
                continue
            if current > 0 or int(
                self._connection.execute("PRAGMA page_count").fetchone()[0]
            ) > 0:
                self._backup_before_migration(current, version)
            digest = sha256_file(path)
            self._connection.execute("BEGIN EXCLUSIVE")
            try:
                for statement in self._sql_statements(path.read_text(encoding="utf-8")):
                    self._connection.execute(statement)
                self._connection.execute(
                    "INSERT INTO schema_migrations(version, name, digest, applied_at) VALUES (?, ?, ?, ?)",
                    (version, name, digest, utc_now()),
                )
                self._connection.execute(f"PRAGMA user_version = {version}")
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise
            current = version

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Private reducer transaction with deterministic crash boundaries."""

        with self._lock:
            checkpoint("state.before_begin")
            self._connection.execute("BEGIN IMMEDIATE")
            checkpoint("state.after_begin")
            try:
                yield self._connection
                checkpoint("state.before_commit")
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise
            checkpoint("state.after_commit")

    def integrity_check(self) -> None:
        with self._lock:
            foreign_keys = self._connection.execute("PRAGMA foreign_keys").fetchone()[0]
            synchronous = self._connection.execute("PRAGMA synchronous").fetchone()[0]
            journal = self._connection.execute("PRAGMA journal_mode").fetchone()[0]
            if foreign_keys != 1 or synchronous != 2 or str(journal).lower() != "wal":
                raise RecoveryError("SQLite safety pragmas are not active")
            rows = [row[0] for row in self._connection.execute("PRAGMA integrity_check")]
            if rows != ["ok"]:
                raise RecoveryError(f"SQLite integrity check failed: {rows}")
            if self._current_migration() > 0:
                self._verify_event_chain()
                verify_audit_chain(self.list_audit())

    def _verify_event_chain(self) -> str:
        previous = EVENT_GENESIS_DIGEST
        expected_sequence = 1
        rows = self._connection.execute("SELECT * FROM events ORDER BY sequence")
        for row in rows:
            sequence = int(row["sequence"])
            if sequence != expected_sequence or row["previous_digest"] != previous:
                raise RecoveryError(f"event-chain discontinuity at sequence {sequence}")
            material = {
                "actor": row["actor"],
                "created_at": row["created_at"],
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "idempotency_key": row["idempotency_key"],
                "payload": json.loads(row["payload_json"]),
                "previous_digest": row["previous_digest"],
                "request_digest": row["request_digest"],
                "run_id": row["run_id"],
                "run_revision": row["run_revision"],
                "sequence": sequence,
            }
            actual = sha256_bytes(canonical_json(material))
            if actual != row["event_digest"]:
                raise RecoveryError(f"event digest mismatch at sequence {sequence}")
            previous = actual
            expected_sequence += 1
        return previous

    # ---- read-only public API -------------------------------------------------

    @staticmethod
    def _json_row(row: sqlite3.Row | None, fields: Sequence[str]) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for field in fields:
            if field in result and result[field] is not None:
                result[field.removesuffix("_json")] = json.loads(result.pop(field))
        return result

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._json_row(row, ("payload_json",))

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT runs.* FROM runs JOIN run_registry USING(run_id) "
                "ORDER BY run_registry.created_at, runs.run_id"
            ).fetchall()
        return [self._json_row(row, ("payload_json",)) or {} for row in rows]

    def latest_run(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT runs.* FROM runs JOIN run_registry USING(run_id) "
                "ORDER BY run_registry.created_at DESC, runs.run_id DESC LIMIT 1"
            ).fetchone()
        return self._json_row(row, ("payload_json",))

    def get_entity_state(self, machine: str, entity_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM entity_states WHERE machine = ? AND entity_id = ?",
                (machine, entity_id),
            ).fetchone()
        return self._json_row(row, ("payload_json",))

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._json_row(row, ("payload_json",))

    def list_events(self, run_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events"
        parameters: tuple[Any, ...] = ()
        if run_id is not None:
            sql += " WHERE run_id = ?"
            parameters = (run_id,)
        sql += " ORDER BY sequence"
        with self._lock:
            rows = self._connection.execute(sql, parameters).fetchall()
        return [self._json_row(row, ("payload_json",)) or {} for row in rows]

    def get_gate(self, gate_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM gate_decisions WHERE gate_id = ?", (gate_id,)
            ).fetchone()
        result = self._json_row(row, ("decision_json",))
        return result.get("decision") if result else None

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM evidence_receipts WHERE evidence_id = ?", (evidence_id,)
            ).fetchone()
        result = self._json_row(row, ("receipt_json",))
        return result.get("receipt") if result else None

    def list_evidence(self, run_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT receipt_json FROM evidence_receipts"
        params: tuple[Any, ...] = ()
        if run_id is not None:
            sql += " WHERE run_id = ?"
            params = (run_id,)
        sql += " ORDER BY created_at, evidence_id"
        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()
        return [json.loads(row["receipt_json"]) for row in rows]

    def referenced_evidence_digests(self) -> set[str]:
        result: set[str] = set()
        for receipt in self.list_evidence():
            for field in ("stdout_digest", "stderr_digest"):
                value = receipt.get(field)
                if value:
                    result.add(str(value))
        return result

    def get_authorization(self, authorization_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM authorization_records WHERE authorization_id = ?",
                (authorization_id,),
            ).fetchone()
        return json.loads(row["record_json"]) if row else None

    def list_authorizations(self, run_id: str) -> list[dict[str, Any]]:
        """Return canonical signed records for one run in journal order."""

        with self._lock:
            rows = self._connection.execute(
                "SELECT record_json FROM authorization_records "
                "WHERE run_id = ? ORDER BY created_at, authorization_id",
                (run_id,),
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def list_entities(
        self, run_id: str, *, machine: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM entity_states WHERE run_id = ?"
        parameters: tuple[Any, ...] = (run_id,)
        if machine is not None:
            sql += " AND machine = ?"
            parameters = (run_id, machine)
        sql += " ORDER BY machine, entity_id"
        with self._lock:
            rows = self._connection.execute(sql, parameters).fetchall()
        return [self._json_row(row, ("payload_json",)) or {} for row in rows]

    def get_authorization_request(self, request_digest: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM authorization_requests WHERE request_digest = ?",
                (request_digest,),
            ).fetchone()
        return self._json_row(row, ("scope_json",))

    def authorization_is_revoked(self, authorization_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM authorization_records WHERE record_type = 'revocation' "
                "AND target_authorization_id = ? LIMIT 1",
                (authorization_id,),
            ).fetchone()
        return row is not None

    def get_operation(self, operation_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM external_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return self._json_row(row, ("scope_json", "result_json"))

    def get_lease(self, resource_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM leases WHERE resource_id = ?", (resource_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_audit(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_records ORDER BY sequence"
            ).fetchall()
        return [self._json_row(row, ("payload_json",)) or {} for row in rows]

    def list_outbox(self, *, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM notification_outbox"
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY created_at, notification_id"
        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()
        return [self._json_row(row, ("payload_json",)) or {} for row in rows]

    # ---- private reducer helpers --------------------------------------------

    def _idempotency_result(
        self,
        connection: sqlite3.Connection,
        *,
        scope: str,
        idempotency_key: str,
        request_digest: str,
        replay_allowed: bool = True,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT request_digest, result_json FROM idempotency_records "
            "WHERE scope = ? AND idempotency_key = ?",
            (scope, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["request_digest"] != request_digest:
            raise TransitionError(
                f"idempotency key reused with a different request: {scope}/{idempotency_key}"
            )
        if not replay_allowed:
            raise TransitionError(
                f"duplicate non-idempotent request: {scope}/{idempotency_key}"
            )
        return json.loads(row["result_json"])

    def _record_event(
        self,
        connection: sqlite3.Connection,
        *,
        scope: str,
        run_id: str | None,
        run_revision: int | None,
        event_type: str,
        actor: str,
        idempotency_key: str,
        request_digest: str,
        payload: Mapping[str, Any],
        result: Mapping[str, Any],
        outbox: Iterable[NotificationIntent | Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events"
            ).fetchone()[0]
        )
        previous_row = connection.execute(
            "SELECT event_digest FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_digest = previous_row[0] if previous_row else EVENT_GENESIS_DIGEST
        event_id = f"EVT-{uuid.uuid4().hex}"
        created_at = utc_now()
        material = {
            "actor": actor,
            "created_at": created_at,
            "event_id": event_id,
            "event_type": event_type,
            "idempotency_key": idempotency_key,
            "payload": dict(payload),
            "previous_digest": previous_digest,
            "request_digest": request_digest,
            "run_id": run_id,
            "run_revision": run_revision,
            "sequence": sequence,
        }
        event_digest = sha256_bytes(canonical_json(material))
        connection.execute(
            "INSERT INTO events(sequence, event_id, run_id, run_revision, event_type, actor, "
            "idempotency_key, request_digest, payload_json, previous_digest, event_digest, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sequence,
                event_id,
                run_id,
                run_revision,
                event_type,
                actor,
                idempotency_key,
                request_digest,
                canonical_json(dict(payload)).decode("utf-8"),
                previous_digest,
                event_digest,
                created_at,
            ),
        )
        checkpoint("state.after_event_insert")

        audit_sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM audit_records"
            ).fetchone()[0]
        )
        audit_previous_row = connection.execute(
            "SELECT audit_digest FROM audit_records ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        audit_previous = audit_previous_row[0] if audit_previous_row else GENESIS_DIGEST
        audit_digest = calculate_audit_digest(
            sequence=audit_sequence,
            event_id=event_id,
            event_type=event_type,
            actor=actor,
            run_id=run_id,
            run_revision=run_revision,
            previous_digest=audit_previous,
            event_digest=event_digest,
            payload=dict(payload),
            created_at=created_at,
        )
        connection.execute(
            "INSERT INTO audit_records(sequence, event_id, event_type, actor, run_id, run_revision, "
            "previous_digest, event_digest, audit_digest, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                audit_sequence,
                event_id,
                event_type,
                actor,
                run_id,
                run_revision,
                audit_previous,
                event_digest,
                audit_digest,
                canonical_json(dict(payload)).decode("utf-8"),
                created_at,
            ),
        )

        normalized_result = dict(result)
        normalized_result.update(
            {
                "event_id": event_id,
                "event_sequence": sequence,
                "event_digest": event_digest,
                "event_created_at": created_at,
            }
        )
        connection.execute(
            "INSERT INTO idempotency_records(scope, idempotency_key, request_digest, event_id, "
            "result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                scope,
                idempotency_key,
                request_digest,
                event_id,
                canonical_json(normalized_result).decode("utf-8"),
                created_at,
            ),
        )
        for raw_intent in outbox:
            intent = validate_intent(raw_intent)
            notification_id = intent.notification_id or notification_identity(
                event_id=event_id, route=intent.route, severity=intent.severity
            )
            connection.execute(
                "INSERT INTO notification_outbox(notification_id, run_id, event_id, route, severity, "
                "payload_json, status, attempt_count, next_attempt_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)",
                (
                    notification_id,
                    run_id,
                    event_id,
                    intent.route,
                    intent.severity,
                    canonical_json(intent.payload).decode("utf-8"),
                    created_at,
                    created_at,
                    created_at,
                ),
            )
        checkpoint("state.after_audit_outbox_insert")
        return normalized_result

    def _cas_run_revision(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        expected_revision: int,
        new_revision: int,
        updated_at: str,
    ) -> None:
        cursor = connection.execute(
            "UPDATE runs SET revision = ?, updated_at = ? WHERE run_id = ? AND revision = ?",
            (new_revision, updated_at, run_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise TransitionError(
                f"stale run revision for {run_id}: expected {expected_revision}"
            )

    def _apply_projection(
        self, connection: sqlite3.Connection, projection: Mapping[str, Any]
    ) -> None:
        kind = projection.get("kind")
        if kind == "run_create":
            connection.execute(
                "INSERT OR REPLACE INTO runs(run_id, revision, state, resume_state, mode, run_kind, "
                "spec_hash, config_hash, payload_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    projection["run_id"],
                    projection["revision"],
                    projection["state"],
                    projection.get("resume_state"),
                    projection["mode"],
                    projection["run_kind"],
                    projection["spec_hash"],
                    projection["config_hash"],
                    canonical_json(projection.get("payload", {})).decode("utf-8"),
                    projection["updated_at"],
                ),
            )
        elif kind == "transition":
            machine = projection["machine"]
            if machine == "run":
                cursor = connection.execute(
                    "UPDATE runs SET revision = ?, state = ?, resume_state = ?, payload_json = ?, "
                    "updated_at = ? WHERE run_id = ? AND revision = ?",
                    (
                        projection["revision"],
                        projection["state"],
                        projection.get("resume_state"),
                        canonical_json(projection.get("payload", {})).decode("utf-8"),
                        projection["updated_at"],
                        projection["run_id"],
                        projection["previous_revision"],
                    ),
                )
            else:
                cursor = connection.execute(
                    "UPDATE entity_states SET revision = ?, state = ?, resume_state = ?, payload_json = ?, "
                    "updated_at = ? WHERE machine = ? AND entity_id = ? AND revision = ?",
                    (
                        projection["revision"],
                        projection["state"],
                        projection.get("resume_state"),
                        canonical_json(projection.get("payload", {})).decode("utf-8"),
                        projection["updated_at"],
                        machine,
                        projection["entity_id"],
                        projection["previous_revision"],
                    ),
                )
            if cursor.rowcount != 1:
                raise TransitionError("projection compare-and-swap failed")
            for lease in projection.get("fenced_leases", []):
                deleted = connection.execute(
                    "DELETE FROM leases WHERE resource_id = ? AND owner = ? "
                    "AND fencing_token = ? AND run_id = ?",
                    (
                        lease["resource_id"],
                        lease["owner"],
                        lease["fencing_token"],
                        projection["run_id"],
                    ),
                )
                if deleted.rowcount != 1:
                    raise TransitionError("lease fencing projection is stale")
        elif kind == "entity_create":
            connection.execute(
                "INSERT INTO entity_states(machine, entity_id, run_id, revision, state, resume_state, "
                "payload_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    projection["machine"],
                    projection["entity_id"],
                    projection["run_id"],
                    projection["revision"],
                    projection["state"],
                    projection.get("resume_state"),
                    canonical_json(projection.get("payload", {})).decode("utf-8"),
                    projection["updated_at"],
                ),
            )
        elif kind == "operation_start":
            connection.execute(
                "INSERT INTO external_operations(operation_id, run_id, action_id, operation_kind, "
                "idempotency_key, status, effect_id, authorization_id, grant_revision, fencing_token, "
                "scope_json, result_json, started_at, updated_at) VALUES (?, ?, ?, ?, ?, 'started', "
                "NULL, ?, ?, ?, ?, ?, ?, ?)",
                (
                    projection["operation_id"],
                    projection["run_id"],
                    projection["action_id"],
                    projection["operation_kind"],
                    projection["operation_idempotency_key"],
                    projection.get("authorization_id"),
                    projection.get("grant_revision"),
                    projection.get("fencing_token"),
                    canonical_json(projection.get("scope", {})).decode("utf-8"),
                    canonical_json({}).decode("utf-8"),
                    projection["started_at"],
                    projection["started_at"],
                ),
            )
        elif kind == "run_control":
            current = connection.execute(
                "SELECT state, resume_state, payload_json FROM runs "
                "WHERE run_id = ? AND revision = ?",
                (projection["run_id"], projection["previous_revision"]),
            ).fetchone()
            if current is None:
                raise TransitionError("run control compare-and-swap failed")
            cursor = connection.execute(
                "UPDATE runs SET revision = ?, state = ?, resume_state = ?, mode = ?, "
                "spec_hash = ?, config_hash = ?, payload_json = ?, updated_at = ? "
                "WHERE run_id = ? AND revision = ?",
                (
                    projection["revision"],
                    projection.get("state", current["state"]),
                    projection.get("resume_state", current["resume_state"]),
                    projection["mode"],
                    projection["spec_hash"],
                    projection["config_hash"],
                    canonical_json(
                        projection.get("payload", json.loads(current["payload_json"]))
                    ).decode("utf-8"),
                    projection["updated_at"],
                    projection["run_id"],
                    projection["previous_revision"],
                ),
            )
            if cursor.rowcount != 1:
                raise TransitionError("run control compare-and-swap failed")
        elif kind == "operation_observation":
            cursor = connection.execute(
                "UPDATE external_operations SET status = ?, effect_id = ?, result_json = ?, updated_at = ? "
                "WHERE operation_id = ? AND status IN ('started', 'partial', 'unknown')",
                (
                    projection["status"],
                    projection.get("effect_id"),
                    canonical_json(projection.get("result", {})).decode("utf-8"),
                    projection["updated_at"],
                    projection["operation_id"],
                ),
            )
            if cursor.rowcount != 1:
                raise TransitionError("external operation observation is stale")
        elif kind == "operation_restart":
            cursor = connection.execute(
                "UPDATE external_operations SET status = 'started', result_json = ?, "
                "updated_at = ? WHERE operation_id = ? AND status = 'not_started'",
                (
                    canonical_json({}).decode("utf-8"),
                    projection["updated_at"],
                    projection["operation_id"],
                ),
            )
            if cursor.rowcount != 1:
                raise TransitionError("external operation retry is stale")
        elif kind == "lease_upsert":
            connection.execute(
                "INSERT INTO lease_fencing_counters(resource_id, last_fencing_token) "
                "VALUES (?, ?) ON CONFLICT(resource_id) DO UPDATE SET "
                "last_fencing_token = MAX(last_fencing_token, excluded.last_fencing_token)",
                (projection["resource_id"], projection["fencing_token"]),
            )
            connection.execute(
                "INSERT INTO leases(resource_id, run_id, owner, attempt_id, fencing_token, acquired_at, "
                "heartbeat_at, expires_at, write_set_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(resource_id) DO UPDATE SET run_id=excluded.run_id, owner=excluded.owner, "
                "attempt_id=excluded.attempt_id, fencing_token=excluded.fencing_token, "
                "acquired_at=excluded.acquired_at, heartbeat_at=excluded.heartbeat_at, "
                "expires_at=excluded.expires_at, write_set_json=excluded.write_set_json",
                (
                    projection["resource_id"],
                    projection["run_id"],
                    projection["owner"],
                    projection.get("attempt_id"),
                    projection["fencing_token"],
                    projection["acquired_at"],
                    projection["heartbeat_at"],
                    projection["expires_at"],
                    canonical_json(projection.get("write_set", [])).decode("utf-8"),
                ),
            )
        elif kind == "lease_delete":
            cursor = connection.execute(
                "DELETE FROM leases WHERE resource_id = ? AND owner = ? AND fencing_token = ?",
                (
                    projection["resource_id"],
                    projection["owner"],
                    projection["fencing_token"],
                ),
            )
            if cursor.rowcount != 1:
                raise TransitionError("lease release is stale")
        elif kind == "notification_attempt":
            cursor = connection.execute(
                "UPDATE notification_outbox SET status = ?, attempt_count = ?, next_attempt_at = ?, "
                "delivered_at = ?, last_error = ?, updated_at = ? WHERE notification_id = ? "
                "AND attempt_count = ?",
                (
                    projection["status"],
                    projection["attempt_count"],
                    projection["next_attempt_at"],
                    projection.get("delivered_at"),
                    projection.get("last_error"),
                    projection["updated_at"],
                    projection["notification_id"],
                    projection["previous_attempt_count"],
                ),
            )
            if cursor.rowcount != 1:
                raise TransitionError("notification attempt is stale")
        elif kind in {None, "immutable_record", "authorization", "evidence", "gate", "notification"}:
            return
        else:
            raise RecoveryError(f"unknown materialized projection kind: {kind!r}")

    def rebuild_materialized_views(self) -> dict[str, Any]:
        """Delete disposable views and deterministically replay canonical events."""

        with self._write_transaction() as connection:
            connection.execute("DELETE FROM entity_states")
            connection.execute("DELETE FROM leases")
            # Rebuild must derive the monotonic counter from canonical lease
            # acquisition/heartbeat events.  The no-delete trigger protects
            # normal runtime writes; controlled replay temporarily clears it.
            connection.execute("DROP TRIGGER lease_fencing_counters_no_delete")
            connection.execute("DELETE FROM lease_fencing_counters")
            connection.execute(
                "CREATE TRIGGER lease_fencing_counters_no_delete "
                "BEFORE DELETE ON lease_fencing_counters BEGIN "
                "SELECT RAISE(ABORT, 'lease fencing counters are monotonic'); END"
            )
            connection.execute("DELETE FROM external_operations")
            connection.execute("DELETE FROM notification_outbox")
            connection.execute("DELETE FROM runs")
            count = 0
            rows = connection.execute(
                "SELECT event_id, run_id, run_revision, created_at, payload_json "
                "FROM events ORDER BY sequence"
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                projection = payload.get("projection")
                if projection:
                    self._apply_projection(connection, projection)
                if row["run_id"] is not None and row["run_revision"] is not None:
                    connection.execute(
                        "UPDATE runs SET revision = ?, updated_at = ? WHERE run_id = ? AND revision < ?",
                        (
                            row["run_revision"],
                            row["created_at"],
                            row["run_id"],
                            row["run_revision"],
                        ),
                    )
                for raw_intent in payload.get("outbox", []):
                    intent = validate_intent(raw_intent)
                    notification_id = intent.notification_id or notification_identity(
                        event_id=row["event_id"], route=intent.route, severity=intent.severity
                    )
                    connection.execute(
                        "INSERT INTO notification_outbox(notification_id, run_id, event_id, route, severity, "
                        "payload_json, status, attempt_count, next_attempt_at, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)",
                        (
                            notification_id,
                            row["run_id"],
                            row["event_id"],
                            intent.route,
                            intent.severity,
                            canonical_json(intent.payload).decode("utf-8"),
                            row["created_at"],
                            row["created_at"],
                            row["created_at"],
                        ),
                    )
                count += 1
        return {"events_replayed": count, "runs": len(self.list_runs())}
