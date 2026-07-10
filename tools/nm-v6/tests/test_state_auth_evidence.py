from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from nmv6.audit import export_audit, verify_audit_chain
from nmv6.authorization import (
    REQUIRED_FIELDS,
    OpenSSLSignatureVerifier,
    signed_payload,
    validate_authorization_record,
)
from nmv6.errors import AuthorizationError, ContractError, EvidenceError, TransitionError
from nmv6.evidence import (
    EVIDENCE_SCHEMA_VERSION,
    REQUIRED_RECEIPT_FIELDS,
    EvidenceStore,
    REDACTION_MARKER,
    REDACTION_VERSION,
)
from nmv6.failpoints import FailpointError
from nmv6.gates import (
    GATE_DECISION_FIELDS,
    GATE_DEFINITIONS,
    GateEvaluator,
    required_bindings,
    required_prerequisites,
    validate_gate_decision,
    validate_gate_evidence_bindings,
)
from nmv6.models import GateObservation, OperationObservation, TransitionProposal
from nmv6.outbox import NotificationIntent
from nmv6.reducer import Reducer
from nmv6.store import Store
from nmv6.transitions import DEFAULT_TRANSITION_TABLE, transition_table_document
from nmv6.util import canonical_json, sha256_bytes, sha256_file, utc_now


def later(seconds: int = 600) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def earlier(seconds: int = 600) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def base_receipt(run_id: str, evidence_id: str = "EVID-run-001") -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "command_result",
        "producer": "nm-v6-core/gate-executor",
        "run_id": run_id,
        "subject_ids": ["TASK-001"],
        "assertions": {},
        "spec_hash": "a" * 64,
        "config_hash": "b" * 64,
        "source_commit": None,
        "candidate_commit": "candidate-commit",
        "release_source_kind": None,
        "release_source_commit": None,
        "release_source_tree": None,
        "hotfix_reconciliation_gate_id": None,
        "artifact_digest": None,
        "environment_id": None,
        "environment_fingerprint": None,
        "operation_id": None,
        "attempt_id": "ATTEMPT-run-001",
        "command_action_id": "task_verify",
        "argv_digest": "c" * 64,
        "working_directory": ".",
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "exit_code": 0,
        "result": "passed",
        "stdout_digest": None,
        "stderr_digest": None,
        "tool_versions": {"python": sys.version.split()[0]},
        "producer_version": "test-core-v1",
        "evaluator_version": "test-evaluator-v1",
        "redaction_version": "placeholder",
    }


def complete_gate_receipt(
    run_id: str,
    evidence_id: str,
    **bindings: object,
) -> dict[str, object]:
    receipt = base_receipt(run_id, evidence_id)
    receipt.update(
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "stdout_digest": "d" * 64,
            "stderr_digest": "e" * 64,
            "redaction_version": REDACTION_VERSION,
            **bindings,
        }
    )
    return receipt


def gate_context(
    gate_type: str,
    evidence_id: str,
    *,
    run_id: str,
    **bindings: object,
) -> dict[str, object]:
    prerequisites = required_prerequisites(gate_type)
    defaults: dict[str, object] = {
        "source_commit": "release-commit",
        "candidate_commit": "candidate-commit",
        "target_commit": "target-commit",
        "release_source_kind": "dev",
        "release_source_commit": "release-commit",
        "release_source_tree": "release-tree",
        "artifact_digest": "f" * 64,
        "environment_id": "production",
        "environment_fingerprint": "production-fingerprint",
    }
    required_values = {
        field: defaults[field] for field in required_bindings(gate_type)
    }
    result = {
        "run_id": run_id,
        **{prerequisite: True for prerequisite in prerequisites},
        "prerequisite_evidence": {
            prerequisite: [evidence_id] for prerequisite in prerequisites
        },
        **required_values,
        **bindings,
    }
    if gate_type == "COMPLETION_GATE":
        result["mandatory_acceptance_ids"] = ["V6-AC-001"]
        result["acceptance_evidence"] = {"V6-AC-001": [evidence_id]}
    return result


def canonical_traceability(
    *mandatory_acceptance_ids: str,
) -> dict[str, object]:
    acceptance = [
        {
            "acceptance_id": acceptance_id,
            "requirement_ids": ["REQ-001"],
            "mandatory": True,
            "required_by_stage": "completion",
        }
        for acceptance_id in mandatory_acceptance_ids
    ]
    return {
        "goals": [{"goal_id": "GOAL-001"}],
        "requirements": [
            {"requirement_id": "REQ-001", "goal_ids": ["GOAL-001"]}
        ],
        "acceptance_criteria": acceptance,
        "phases": [{"phase_id": "PHASE-001", "depends_on": []}],
        "tasks": [
            {
                "task_id": "TASK-001",
                "phase_id": "PHASE-001",
                "acceptance_ids": list(mandatory_acceptance_ids),
                "enabling_requirement_ids": [],
                "dependencies": [],
                "optional": False,
            }
        ],
        "acceptance_actions": {},
    }


class CoreFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="nm-v6-core-test-")
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "state.sqlite3")
        self.evidence = EvidenceStore(self.root / "evidence")
        self.reducer = Reducer(self.store, evidence_store=self.evidence)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def create_run(self, run_id: str = "run-test") -> dict[str, object]:
        return self.reducer.create_run(
            run_id=run_id,
            spec_hash="a" * 64,
            config_hash="b" * 64,
            idempotency_key=f"create:{run_id}",
        )


class StoreReducerTests(CoreFixture):
    def test_sqlite_pragmas_cas_idempotency_tamper_and_rebuild(self) -> None:
        created = self.create_run()
        replay = self.create_run()
        self.assertEqual(created["event_id"], replay["event_id"])
        self.assertEqual(1, len(self.store.list_events()))

        drafted = self.reducer.transition(
            TransitionProposal(
                run_id="run-test",
                expected_revision=0,
                event="DRAFT_SPEC",
                actor="planner",
                idempotency_key="draft",
                payload={"discovery_complete": True},
            )
        )
        self.assertEqual("SPEC_DRAFT", drafted["state"])
        with self.assertRaises(TransitionError):
            self.reducer.transition(
                TransitionProposal(
                    run_id="run-test",
                    expected_revision=0,
                    event="SUBMIT_SPEC_REVIEW",
                    actor="planner",
                    idempotency_key="stale",
                )
            )
        with self.assertRaises(TransitionError):
            DEFAULT_TRANSITION_TABLE.rule_for("run", "READY", "COMPLETE_RUN")

        self.reducer.transition(
            TransitionProposal(
                run_id="run-test",
                expected_revision=1,
                event="SUBMIT_SPEC_REVIEW",
                actor="planner",
                idempotency_key="review",
            )
        )
        queued = self.reducer.enqueue_notification(
            run_id="run-test",
            expected_revision=2,
            intent=NotificationIntent(
                route="fake-feishu",
                severity="progress",
                payload={"message": "review started"},
            ),
            idempotency_key="notify",
        )
        outbox = self.store.list_outbox()
        self.assertEqual(1, len(outbox))
        notification_id = outbox[0]["notification_id"]
        failed = self.reducer.record_notification_attempt(
            run_id="run-test",
            expected_revision=3,
            notification_id=notification_id,
            succeeded=False,
            error="injected outage",
            idempotency_key="notify-attempt",
        )
        replayed_failure = self.reducer.record_notification_attempt(
            run_id="run-test",
            expected_revision=3,
            notification_id=notification_id,
            succeeded=False,
            error="injected outage",
            idempotency_key="notify-attempt",
        )
        self.assertEqual(failed["event_id"], replayed_failure["event_id"])
        self.assertEqual("SPEC_REVIEW", self.store.get_run("run-test")["state"])
        self.assertEqual("retry", self.store.list_outbox()[0]["status"])
        self.assertEqual(1, self.store.list_outbox()[0]["attempt_count"])
        self.assertEqual(queued["revision"] + 1, self.store.get_run("run-test")["revision"])

        before = self.store.get_run("run-test")
        before_outbox = self.store.list_outbox()
        rebuilt = self.store.rebuild_materialized_views()
        self.assertEqual(len(self.store.list_events()), rebuilt["events_replayed"])
        self.assertEqual(before, self.store.get_run("run-test"))
        self.assertEqual(before_outbox, self.store.list_outbox())
        verify_audit_chain(self.store.list_audit())
        self.store.integrity_check()

        first_export = self.root / "audit-before-restart.json"
        second_export = self.root / "audit-after-restart.json"
        export_audit(self.store.list_audit(), first_export)
        restarted = Store(self.store.path)
        try:
            export_audit(restarted.list_audit(), second_export)
        finally:
            restarted.close()
        self.assertEqual(first_export.read_bytes(), second_export.read_bytes())

        direct = sqlite3.connect(self.store.path)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                direct.execute("UPDATE events SET actor = 'tamper' WHERE sequence = 1")
            with self.assertRaises(sqlite3.DatabaseError):
                direct.execute("DELETE FROM audit_records WHERE sequence = 1")
        finally:
            direct.close()

    def test_v1_to_v2_migration_backup_is_atomic_and_crash_retryable(self) -> None:
        database = self.root / "legacy-v1.sqlite3"
        migration_root = TOOLS_ROOT / "nmv6" / "migrations"
        initial_migration = migration_root / "0001_initial.sql"
        fencing_migration = migration_root / "0002_lease_fencing_and_write_sets.sql"
        legacy_payload = {"fixture": "v1", "preserved": ["run", "configuration"]}
        created_at = utc_now()

        legacy = sqlite3.connect(database)
        try:
            legacy.executescript(initial_migration.read_text(encoding="utf-8"))
            legacy.execute(
                "INSERT INTO schema_migrations(version, name, digest, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (1, "initial", sha256_file(initial_migration), created_at),
            )
            legacy.execute("PRAGMA user_version = 1")
            legacy.execute(
                "INSERT INTO run_registry(run_id, created_at) VALUES (?, ?)",
                ("legacy-run", created_at),
            )
            legacy.execute(
                "INSERT INTO runs(run_id, revision, state, resume_state, mode, run_kind, "
                "spec_hash, config_hash, payload_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-run",
                    7,
                    "READY",
                    None,
                    "staged",
                    "normal",
                    "a" * 64,
                    "b" * 64,
                    canonical_json(legacy_payload).decode("utf-8"),
                    created_at,
                ),
            )
            legacy.commit()
        finally:
            legacy.close()

        class FailingV2Store(Store):
            @staticmethod
            def _sql_statements(text: str):
                for statement in Store._sql_statements(text):
                    yield statement
                    if "CREATE TABLE lease_fencing_counters" in statement:
                        yield "SELECT * FROM injected_missing_migration_table;"

        interrupted = FailingV2Store(database, initialize=False)
        try:
            with self.assertRaisesRegex(
                sqlite3.OperationalError, "injected_missing_migration_table"
            ):
                interrupted.initialize()
        finally:
            interrupted.close()

        backup = database.with_name(f"{database.name}.pre-v2.backup")
        self.assertTrue(backup.is_file())
        failed = sqlite3.connect(database)
        try:
            self.assertEqual(1, failed.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(
                [1],
                [row[0] for row in failed.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )],
            )
            self.assertIsNone(
                failed.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'lease_fencing_counters'"
                ).fetchone()
            )
            self.assertNotIn(
                "write_set_json",
                {row[1] for row in failed.execute("PRAGMA table_info(leases)")},
            )
            self.assertEqual(
                canonical_json(legacy_payload).decode("utf-8"),
                failed.execute(
                    "SELECT payload_json FROM runs WHERE run_id = 'legacy-run'"
                ).fetchone()[0],
            )
        finally:
            failed.close()

        migrated = Store(database)
        try:
            self.assertEqual(2, migrated._current_migration())
            self.assertEqual(2, migrated._connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0])
            self.assertEqual(legacy_payload, migrated.get_run("legacy-run")["payload"])
            columns = {
                row[1]: row
                for row in migrated._connection.execute("PRAGMA table_info(leases)")
            }
            self.assertIn("write_set_json", columns)
            self.assertEqual(1, columns["write_set_json"][3])
            self.assertEqual("'[]'", columns["write_set_json"][4])
            self.assertIsNotNone(
                migrated._connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'lease_fencing_counters'"
                ).fetchone()
            )
            fencing_columns = {
                row[1]: row
                for row in migrated._connection.execute(
                    "PRAGMA table_info(lease_fencing_counters)"
                )
            }
            self.assertEqual(
                {"resource_id", "last_fencing_token"}, set(fencing_columns)
            )
            self.assertEqual(1, fencing_columns["resource_id"][5])
            self.assertEqual(1, fencing_columns["last_fencing_token"][3])
            self.assertIsNotNone(
                migrated._connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'trigger' "
                    "AND name = 'lease_fencing_counters_no_delete'"
                ).fetchone()
            )
            self.assertEqual(
                [sha256_file(initial_migration), sha256_file(fencing_migration)],
                [
                    row[0]
                    for row in migrated._connection.execute(
                        "SELECT digest FROM schema_migrations ORDER BY version"
                    )
                ],
            )
        finally:
            migrated.close()

        readable_backup = sqlite3.connect(backup)
        try:
            self.assertEqual(
                "ok", readable_backup.execute("PRAGMA integrity_check").fetchone()[0]
            )
            self.assertEqual(
                1, readable_backup.execute("PRAGMA user_version").fetchone()[0]
            )
            self.assertEqual(
                [1],
                [row[0] for row in readable_backup.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )],
            )
            self.assertEqual(
                canonical_json(legacy_payload).decode("utf-8"),
                readable_backup.execute(
                    "SELECT payload_json FROM runs WHERE run_id = 'legacy-run'"
                ).fetchone()[0],
            )
        finally:
            readable_backup.close()

    def test_lease_fencing_and_two_controller_exclusion(self) -> None:
        self.create_run()
        acquired = self.reducer.acquire_lease(
            run_id="run-test",
            expected_revision=0,
            resource_id="TASK-001",
            owner="controller-a",
            lease_seconds=60,
            idempotency_key="lease-a",
        )
        second_store = Store(self.store.path)
        try:
            second_reducer = Reducer(second_store, evidence_store=self.evidence)
            with self.assertRaises(TransitionError):
                second_reducer.acquire_lease(
                    run_id="run-test",
                    expected_revision=1,
                    resource_id="TASK-001",
                    owner="controller-b",
                    lease_seconds=60,
                    idempotency_key="lease-b",
                )
        finally:
            second_store.close()
        with self.assertRaises(TransitionError):
            self.reducer.release_lease(
                run_id="run-test",
                expected_revision=1,
                resource_id="TASK-001",
                owner="controller-a",
                fencing_token=acquired["fencing_token"] + 1,
                idempotency_key="bad-release",
            )
        self.reducer.release_lease(
            run_id="run-test",
            expected_revision=1,
            resource_id="TASK-001",
            owner="controller-a",
            fencing_token=acquired["fencing_token"],
            idempotency_key="release",
        )
        self.assertIsNone(self.store.get_lease("TASK-001"))

        reacquired = self.reducer.acquire_lease(
            run_id="run-test",
            expected_revision=2,
            resource_id="TASK-001",
            owner="controller-b",
            lease_seconds=60,
            idempotency_key="lease-after-release",
        )
        self.assertGreater(
            reacquired["fencing_token"], acquired["fencing_token"]
        )

    def test_persisted_write_conflicts_and_pause_fence_all_child_writes(self) -> None:
        self.create_run()
        with self.assertRaisesRegex(ContractError, "must begin in PLANNED"):
            self.reducer.create_entity(
                run_id="run-test",
                expected_revision=0,
                machine="task",
                entity_id="TASK-forged",
                initial_state="SKIPPED",
                idempotency_key="forged-skip",
            )
        self.reducer.create_entity(
            run_id="run-test",
            expected_revision=0,
            machine="task",
            entity_id="TASK-001",
            initial_state="PLANNED",
            idempotency_key="task-one",
        )
        first = self.reducer.acquire_lease(
            run_id="run-test",
            expected_revision=1,
            resource_id="TASK-001",
            owner="controller-a",
            lease_seconds=60,
            write_set=("src/**",),
            idempotency_key="lease-write-one",
        )
        with self.assertRaisesRegex(TransitionError, "write set conflicts"):
            self.reducer.acquire_lease(
                run_id="run-test",
                expected_revision=2,
                resource_id="TASK-002",
                owner="controller-b",
                lease_seconds=60,
                write_set=("src/generated/**",),
                idempotency_key="lease-write-two",
            )
        paused = self.reducer.transition(
            TransitionProposal(
                run_id="run-test",
                expected_revision=2,
                event="REQUEST_PAUSE",
                actor="controller",
                idempotency_key="pause-with-lease",
                payload={"safe_pause_point": True, "actors_fenced": True},
            )
        )
        self.assertEqual("PAUSED", paused["state"])
        self.assertIsNone(self.store.get_lease("TASK-001"))
        with self.assertRaisesRegex(TransitionError, "fenced while run is PAUSED"):
            self.reducer.transition(
                TransitionProposal(
                    run_id="run-test",
                    expected_revision=3,
                    event="MAKE_READY",
                    actor="late-worker",
                    idempotency_key="late-task-write",
                ),
                machine="task",
                entity_id="TASK-001",
            )
        with self.assertRaisesRegex(TransitionError, "fenced while run is PAUSED"):
            self.reducer.acquire_lease(
                run_id="run-test",
                expected_revision=3,
                resource_id="TASK-001",
                owner="late-worker",
                lease_seconds=60,
                write_set=("src/**",),
                idempotency_key="late-lease",
            )
        self.assertEqual(1, first["fencing_token"])

    def test_transition_document_is_versioned_and_unique(self) -> None:
        document = transition_table_document()
        self.assertEqual("nm-v6/transitions-v1", document["schema_version"])
        keys = {
            (row["machine"], row["from_state"], row["event"])
            for row in document["rows"]
        }
        self.assertEqual(len(keys), len(document["rows"]))
        ready_complete = [
            row
            for row in document["rows"]
            if row["machine"] == "run"
            and row["from_state"] == "READY"
            and row["to_state"] == "COMPLETED"
        ]
        self.assertEqual([], ready_complete)


class EvidenceGateTests(CoreFixture):
    def test_task_gate_is_bound_to_exact_entity_and_candidate(self) -> None:
        self.create_run()
        for entity_id in ("TASK-001", "TASK-002"):
            run = self.store.get_run("run-test")
            assert run is not None
            self.reducer.create_entity(
                run_id="run-test",
                expected_revision=int(run["revision"]),
                machine="task",
                entity_id=entity_id,
                initial_state="PLANNED",
                idempotency_key=f"create:{entity_id}",
            )
            for event, payload in (
                ("MAKE_READY", {}),
                ("ACQUIRE_LEASE", {}),
                ("START", {}),
                (
                    "COLLECT_CANDIDATE",
                    {
                        "structured_result_valid": True,
                        "state_patch": {"candidate_commit": "candidate-commit"},
                    },
                ),
                ("START_VERIFICATION", {}),
            ):
                run = self.store.get_run("run-test")
                assert run is not None
                self.reducer.transition(
                    TransitionProposal(
                        run_id="run-test",
                        expected_revision=int(run["revision"]),
                        event=event,
                        actor="task-test",
                        idempotency_key=f"{entity_id}:{event}",
                        payload=payload,
                    ),
                    machine="task",
                    entity_id=entity_id,
                )

        evidence_id = "EVID-task-subject-001"
        prerequisites = required_prerequisites("TASK_GATE")
        receipt_input = complete_gate_receipt(
            "run-test",
            evidence_id,
            subject_ids=list(prerequisites),
            assertions={name: True for name in prerequisites},
        )
        receipt = self.evidence.persist(receipt_input, b"passed", b"")
        run = self.store.get_run("run-test")
        assert run is not None
        self.reducer.record_evidence(
            run_id="run-test",
            expected_revision=int(run["revision"]),
            receipt=receipt,
            idempotency_key="task-subject-evidence",
        )
        run = self.store.get_run("run-test")
        assert run is not None
        decision = GateEvaluator(
            self.store.get_evidence,
            evidence_validator=self.evidence.validate,
        ).evaluate(
            GateObservation(
                gate_type="TASK_GATE",
                subject_ids=("run-test", "TASK-001"),
                context=gate_context(
                    "TASK_GATE", evidence_id, run_id="run-test"
                ),
                evidence_ids=(evidence_id,),
                evaluator="task-subject-test",
            ),
            gate_id="GATE-task-subject-001",
            spec_hash="a" * 64,
            config_hash="b" * 64,
            run_revision=int(run["revision"]),
        )
        self.reducer.record_gate(
            run_id="run-test",
            expected_revision=int(run["revision"]),
            decision=decision,
            idempotency_key="task-subject-gate",
        )
        run = self.store.get_run("run-test")
        assert run is not None
        with self.assertRaisesRegex(TransitionError, "target task"):
            self.reducer.transition(
                TransitionProposal(
                    run_id="run-test",
                    expected_revision=int(run["revision"]),
                    event="VERIFY",
                    actor="task-test",
                    idempotency_key="cross-task-gate",
                    gate_ids=("GATE-task-subject-001",),
                ),
                machine="task",
                entity_id="TASK-002",
            )

        stale_evidence_id = "EVID-task-candidate-stale-001"
        stale_receipt_input = complete_gate_receipt(
            "run-test",
            stale_evidence_id,
            subject_ids=list(prerequisites),
            assertions={name: True for name in prerequisites},
            candidate_commit="other-candidate",
        )
        stale_receipt = self.evidence.persist(
            stale_receipt_input, b"passed", b""
        )
        self.reducer.record_evidence(
            run_id="run-test",
            expected_revision=int(run["revision"]),
            receipt=stale_receipt,
            idempotency_key="task-candidate-stale-evidence",
        )
        run = self.store.get_run("run-test")
        assert run is not None
        stale_decision = GateEvaluator(
            self.store.get_evidence,
            evidence_validator=self.evidence.validate,
        ).evaluate(
            GateObservation(
                gate_type="TASK_GATE",
                subject_ids=("run-test", "TASK-001"),
                context=gate_context(
                    "TASK_GATE",
                    stale_evidence_id,
                    run_id="run-test",
                    candidate_commit="other-candidate",
                ),
                evidence_ids=(stale_evidence_id,),
                evaluator="task-candidate-stale-test",
            ),
            gate_id="GATE-task-candidate-stale-001",
            spec_hash="a" * 64,
            config_hash="b" * 64,
            run_revision=int(run["revision"]),
        )
        self.reducer.record_gate(
            run_id="run-test",
            expected_revision=int(run["revision"]),
            decision=stale_decision,
            idempotency_key="task-candidate-stale-gate",
        )
        run = self.store.get_run("run-test")
        assert run is not None
        with self.assertRaisesRegex(TransitionError, "candidate binding is stale"):
            self.reducer.transition(
                TransitionProposal(
                    run_id="run-test",
                    expected_revision=int(run["revision"]),
                    event="VERIFY",
                    actor="task-test",
                    idempotency_key="stale-candidate-gate",
                    gate_ids=("GATE-task-candidate-stale-001",),
                ),
                machine="task",
                entity_id="TASK-001",
            )
        self.reducer.transition(
            TransitionProposal(
                run_id="run-test",
                expected_revision=int(run["revision"]),
                event="VERIFY",
                actor="task-test",
                idempotency_key="correct-task-gate",
                gate_ids=("GATE-task-subject-001",),
            ),
            machine="task",
            entity_id="TASK-001",
        )

    def test_reducer_rejects_completion_gate_omitting_canonical_acceptance(
        self,
    ) -> None:
        run_id = "run-canonical-completion"
        self.reducer.create_run(
            run_id=run_id,
            spec_hash="a" * 64,
            config_hash="b" * 64,
            idempotency_key="create:canonical-completion",
            payload={
                "traceability": canonical_traceability(
                    "AC-001", "AC-002"
                )
            },
        )
        with self.assertRaisesRegex(
            ContractError, "only change through amend_run_inputs"
        ):
            self.reducer.transition(
                TransitionProposal(
                    run_id=run_id,
                    expected_revision=0,
                    event="DRAFT_SPEC",
                    actor="malicious-controller",
                    idempotency_key="replace-canonical-traceability",
                    payload={
                        "discovery_complete": True,
                        "state_patch": {
                            "traceability": canonical_traceability("AC-001")
                        },
                    },
                )
            )
        evidence_id = "EVID-canonical-completion-001"
        prerequisites = required_prerequisites("COMPLETION_GATE")
        receipt_input = complete_gate_receipt(
            run_id,
            evidence_id,
            subject_ids=[
                *prerequisites,
                "acceptance:AC-001",
                "acceptance:AC-002",
                "acceptance:AC-003",
            ],
            assertions={
                **{name: True for name in prerequisites},
                "acceptance:AC-001": True,
                "acceptance:AC-002": True,
                "acceptance:AC-003": True,
            },
        )
        receipt = self.evidence.persist(receipt_input, b"passed", b"")
        self.reducer.record_evidence(
            run_id=run_id,
            expected_revision=0,
            receipt=receipt,
            idempotency_key="canonical-completion-evidence",
        )
        facts = gate_context(
            "COMPLETION_GATE", evidence_id, run_id=run_id
        )
        facts["mandatory_acceptance_ids"] = ["AC-001"]
        facts["acceptance_evidence"] = {"AC-001": [evidence_id]}
        decision = GateEvaluator(
            self.store.get_evidence,
            evidence_validator=self.evidence.validate,
        ).evaluate(
            GateObservation(
                gate_type="COMPLETION_GATE",
                subject_ids=(run_id,),
                context=facts,
                evidence_ids=(evidence_id,),
                evaluator="canonical-completion-test",
            ),
            gate_id="GATE-canonical-completion-001",
            spec_hash="a" * 64,
            config_hash="b" * 64,
            run_revision=1,
        )
        self.assertEqual("passed", decision["result"])
        with self.assertRaisesRegex(
            TransitionError, "canonical persisted traceability"
        ):
            self.reducer.record_gate(
                run_id=run_id,
                expected_revision=1,
                decision=decision,
                idempotency_key="canonical-completion-gate",
            )
        self.assertIsNone(self.store.get_gate("GATE-canonical-completion-001"))

        expanded_facts = dict(facts)
        expanded_facts["mandatory_acceptance_ids"] = [
            "AC-001",
            "AC-002",
            "AC-003",
        ]
        expanded_facts["acceptance_evidence"] = {
            acceptance_id: [evidence_id]
            for acceptance_id in ("AC-001", "AC-002", "AC-003")
        }
        expanded = GateEvaluator(
            self.store.get_evidence,
            evidence_validator=self.evidence.validate,
        ).evaluate(
            GateObservation(
                gate_type="COMPLETION_GATE",
                subject_ids=(run_id,),
                context=expanded_facts,
                evidence_ids=(evidence_id,),
                evaluator="canonical-completion-test",
            ),
            gate_id="GATE-canonical-completion-expanded",
            spec_hash="a" * 64,
            config_hash="b" * 64,
            run_revision=1,
        )
        self.assertEqual("passed", expanded["result"])
        with self.assertRaisesRegex(
            TransitionError, "canonical persisted traceability"
        ):
            self.reducer.record_gate(
                run_id=run_id,
                expected_revision=1,
                decision=expanded,
                idempotency_key="canonical-completion-expanded-gate",
            )

    def test_completion_gate_fails_closed_for_missing_or_invalid_traceability(
        self,
    ) -> None:
        cases: tuple[tuple[str, Mapping[str, object] | None], ...] = (
            ("missing", None),
            ("invalid", {"traceability": {"goals": []}}),
        )
        for case, payload in cases:
            with self.subTest(case=case):
                run_id = f"run-{case}-traceability"
                self.reducer.create_run(
                    run_id=run_id,
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    idempotency_key=f"create:{case}-traceability",
                    payload=payload,
                )
                evidence_id = f"EVID-{case}-traceability-001"
                prerequisites = required_prerequisites("COMPLETION_GATE")
                receipt_input = complete_gate_receipt(
                    run_id,
                    evidence_id,
                    subject_ids=[*prerequisites, "acceptance:AC-001"],
                    assertions={
                        **{name: True for name in prerequisites},
                        "acceptance:AC-001": True,
                    },
                )
                receipt = self.evidence.persist(receipt_input, b"passed", b"")
                self.reducer.record_evidence(
                    run_id=run_id,
                    expected_revision=0,
                    receipt=receipt,
                    idempotency_key=f"{case}-traceability-evidence",
                )
                facts = gate_context(
                    "COMPLETION_GATE",
                    evidence_id,
                    run_id=run_id,
                )
                facts["mandatory_acceptance_ids"] = ["AC-001"]
                facts["acceptance_evidence"] = {"AC-001": [evidence_id]}
                decision = GateEvaluator(
                    self.store.get_evidence,
                    evidence_validator=self.evidence.validate,
                ).evaluate(
                    GateObservation(
                        gate_type="COMPLETION_GATE",
                        subject_ids=(run_id,),
                        context=facts,
                        evidence_ids=(evidence_id,),
                        evaluator=f"{case}-traceability-test",
                    ),
                    gate_id=f"GATE-{case}-traceability-001",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    run_revision=1,
                )
                with self.assertRaisesRegex(TransitionError, "valid canonical"):
                    self.reducer.record_gate(
                        run_id=run_id,
                        expected_revision=1,
                        decision=decision,
                        idempotency_key=f"{case}-traceability-gate",
                    )

    def test_reducer_rechecks_persisted_prerequisite_evidence(self) -> None:
        self.create_run()
        evidence_id = "EVID-unrelated-001"
        receipt_input = base_receipt("run-test", evidence_id)
        receipt_input["subject_ids"] = ["unrelated-observation"]
        receipt = self.evidence.persist(receipt_input, b"unrelated", b"")
        self.reducer.record_evidence(
            run_id="run-test",
            expected_revision=0,
            receipt=receipt,
            idempotency_key="unrelated-evidence",
        )
        facts = gate_context("PLAN_GATE", evidence_id, run_id="run-test")
        failed = GateEvaluator(
            self.store.get_evidence,
            evidence_validator=self.evidence.validate,
        ).evaluate(
            GateObservation(
                gate_type="PLAN_GATE",
                subject_ids=("run-test",),
                context=facts,
                evidence_ids=(evidence_id,),
                evaluator="test-evaluator",
            ),
            gate_id="GATE-crafted-unrelated",
            spec_hash="a" * 64,
            config_hash="b" * 64,
            run_revision=1,
        )
        self.assertEqual("failed", failed["result"])
        crafted = dict(failed)
        crafted["result"] = "passed"
        crafted["reason"] = "caller tried to promote unrelated evidence"
        material = dict(crafted)
        material.pop("decision_digest")
        crafted["decision_digest"] = sha256_bytes(canonical_json(material))
        validate_gate_decision(crafted)
        with self.assertRaisesRegex(EvidenceError, "no passing core assertion"):
            self.reducer.record_gate(
                run_id="run-test",
                expected_revision=1,
                decision=crafted,
                idempotency_key="crafted-gate",
            )
        self.assertIsNone(self.store.get_gate("GATE-crafted-unrelated"))

    def test_redacted_atomic_blobs_receipt_validation_and_orphans(self) -> None:
        self.create_run()
        secret = b"fake-production-secret"
        receipt_input = base_receipt("run-test")
        receipt_input["subject_ids"] = list(required_prerequisites("PLAN_GATE"))
        receipt_input["assertions"] = {
            name: True for name in required_prerequisites("PLAN_GATE")
        }
        receipt = self.evidence.persist(
            receipt_input,
            b"tests passed; token=" + secret,
            b"warning: " + secret,
            secret_values=(secret,),
        )
        self.assertNotIn(secret, self.evidence.read_blob(receipt["stdout_digest"]))
        self.assertIn(REDACTION_MARKER, self.evidence.read_blob(receipt["stderr_digest"]))
        recorded = self.reducer.record_evidence(
            run_id="run-test",
            expected_revision=0,
            receipt=receipt,
            idempotency_key="evidence-1",
        )
        self.assertEqual(receipt, self.store.get_evidence(receipt["evidence_id"]))
        self.assertEqual(1, recorded["revision"])

        plan_facts = gate_context(
            "PLAN_GATE",
            str(receipt["evidence_id"]),
            run_id="run-test",
        )
        decision = GateEvaluator(
            self.store.get_evidence,
            evidence_validator=self.evidence.validate,
        ).evaluate(
            GateObservation(
                gate_type="PLAN_GATE",
                subject_ids=("run-test",),
                context=plan_facts,
                evidence_ids=(str(receipt["evidence_id"]),),
                evaluator="test-evaluator",
            ),
            gate_id="GATE-run-test-001",
            spec_hash="a" * 64,
            config_hash="b" * 64,
            run_revision=1,
        )
        gate_result = self.reducer.record_gate(
            run_id="run-test",
            expected_revision=1,
            decision=decision,
            idempotency_key="gate-plan-1",
        )
        self.assertEqual("passed", gate_result["result"])
        self.assertEqual(decision, self.store.get_gate(decision["gate_id"]))

        missing = dict(receipt)
        missing.pop("artifact_digest")
        with self.assertRaises(EvidenceError):
            self.evidence.validate(missing)
        wrong = dict(receipt)
        wrong["stdout_digest"] = "0" * 64
        with self.assertRaises(EvidenceError):
            self.evidence.validate(wrong)

        separate = EvidenceStore(self.root / "unredactable")
        with self.assertRaises(EvidenceError):
            separate.persist(
                base_receipt("run-test", "EVID-run-002"),
                b"encoded-secret-is-unsafe",
                b"",
                forbidden_patterns=(b"encoded-secret",),
            )
        self.assertEqual([], list(separate.blob_root.glob("*/*")))

        orphan_receipt = self.evidence.persist(
            base_receipt("run-test", "EVID-run-003"), b"orphan", b"orphan-error"
        )
        quarantined = self.evidence.quarantine_orphans(
            self.store.referenced_evidence_digests()
        )
        self.assertTrue(quarantined)
        self.assertFalse(
            self.evidence.blob_path(orphan_receipt["stdout_digest"]).exists()
        )
        self.evidence.validate(receipt)

    def test_blob_failpoint_leaves_only_quarantinable_orphan(self) -> None:
        store = EvidenceStore(self.root / "crash-evidence")
        old_point = os.environ.get("NM_V6_FAILPOINT")
        old_action = os.environ.get("NM_V6_FAILPOINT_ACTION")
        os.environ["NM_V6_FAILPOINT"] = "evidence.after_blob_rename"
        os.environ["NM_V6_FAILPOINT_ACTION"] = "raise"
        try:
            with self.assertRaises(FailpointError):
                store.persist(base_receipt("run-test"), b"one", b"two")
        finally:
            if old_point is None:
                os.environ.pop("NM_V6_FAILPOINT", None)
            else:
                os.environ["NM_V6_FAILPOINT"] = old_point
            if old_action is None:
                os.environ.pop("NM_V6_FAILPOINT_ACTION", None)
            else:
                os.environ["NM_V6_FAILPOINT_ACTION"] = old_action
        blobs = [path for path in store.blob_root.glob("*/*") if path.is_file()]
        self.assertEqual(1, len(blobs))
        quarantined = store.quarantine_orphans(set())
        self.assertEqual(1, len(quarantined))

    def test_receipt_failpoint_rolls_back_database_reference(self) -> None:
        self.create_run()
        receipt = self.evidence.persist(
            base_receipt("run-test", "EVID-run-099"), b"stdout", b"stderr"
        )
        old_point = os.environ.get("NM_V6_FAILPOINT")
        old_action = os.environ.get("NM_V6_FAILPOINT_ACTION")
        os.environ["NM_V6_FAILPOINT"] = "evidence.after_receipt_insert"
        os.environ["NM_V6_FAILPOINT_ACTION"] = "raise"
        try:
            with self.assertRaises(FailpointError):
                self.reducer.record_evidence(
                    run_id="run-test",
                    expected_revision=0,
                    receipt=receipt,
                    idempotency_key="receipt-crash",
                )
        finally:
            if old_point is None:
                os.environ.pop("NM_V6_FAILPOINT", None)
            else:
                os.environ["NM_V6_FAILPOINT"] = old_point
            if old_action is None:
                os.environ.pop("NM_V6_FAILPOINT_ACTION", None)
            else:
                os.environ["NM_V6_FAILPOINT_ACTION"] = old_action
        self.assertIsNone(self.store.get_evidence("EVID-run-099"))
        self.assertEqual(0, self.store.get_run("run-test")["revision"])
        quarantined = self.evidence.quarantine_orphans(set())
        self.assertTrue(quarantined)

    def test_every_gate_prerequisite_fails_closed(self) -> None:
        receipt = complete_gate_receipt(
            "run-gates",
            "EVID-valid-001",
            subject_ids=sorted(
                {
                    prerequisite
                    for definition in GATE_DEFINITIONS.values()
                    for prerequisite in definition.prerequisites
                }
            ),
            source_commit="release-commit",
            release_source_kind="dev",
            release_source_commit="release-commit",
            release_source_tree="release-tree",
            artifact_digest="f" * 64,
            environment_id="production",
            environment_fingerprint="production-fingerprint",
            assertions={
                **{
                    prerequisite: True
                    for definition in GATE_DEFINITIONS.values()
                    for prerequisite in definition.prerequisites
                },
                "acceptance:V6-AC-001": True,
            },
        )
        self.evidence.validate(receipt, check_blobs=False)
        evaluator = GateEvaluator(
            lambda evidence_id: (
                receipt if evidence_id == receipt["evidence_id"] else None
            ),
            evidence_validator=lambda value: self.evidence.validate(
                value, check_blobs=False
            ),
        )
        for gate_type, definition in GATE_DEFINITIONS.items():
            with self.subTest(gate=gate_type):
                facts = gate_context(
                    gate_type,
                    "EVID-valid-001",
                    run_id="run-gates",
                )
                if gate_type == "RELEASE_GATE":
                    facts.update(
                        {
                            "source_commit": "release-commit",
                            "release_source_kind": "dev",
                            "release_source_commit": "release-commit",
                            "release_source_tree": "release-tree",
                            "artifact_digest": "f" * 64,
                        }
                    )
                observation = GateObservation(
                    gate_type=gate_type,
                    subject_ids=("TASK-001",),
                    context=facts,
                    evidence_ids=("EVID-valid-001",),
                    evaluator="test-evaluator",
                    authorization_id=("AUTH-run-001" if definition.authorization_required else None),
                )
                decision = evaluator.evaluate(
                    observation,
                    gate_id=f"GATE-{gate_type}",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    run_revision=3,
                )
                self.assertEqual("passed", decision["result"])
                validate_gate_decision(decision)
                self.assertEqual(definition.prerequisites, required_prerequisites(gate_type))
                for prerequisite in definition.prerequisites:
                    broken = dict(facts)
                    broken.pop(prerequisite)
                    failed = evaluator.evaluate(
                        GateObservation(
                            gate_type=gate_type,
                            subject_ids=("TASK-001",),
                            context=broken,
                            evidence_ids=("EVID-valid-001",),
                            evaluator="test-evaluator",
                            authorization_id=(
                                "AUTH-run-001"
                                if definition.authorization_required
                                else None
                            ),
                        ),
                        gate_id=f"GATE-{gate_type}-{prerequisite}",
                        spec_hash="a" * 64,
                        config_hash="b" * 64,
                        run_revision=3,
                    )
                    self.assertEqual("failed", failed["result"])
                    self.assertIn(prerequisite, failed["reason"])

                    uncited = dict(facts)
                    uncited["prerequisite_evidence"] = dict(
                        facts["prerequisite_evidence"]
                    )
                    uncited["prerequisite_evidence"].pop(prerequisite)
                    unsupported = evaluator.evaluate(
                        GateObservation(
                            gate_type=gate_type,
                            subject_ids=("TASK-001",),
                            context=uncited,
                            evidence_ids=("EVID-valid-001",),
                            evaluator="test-evaluator",
                            authorization_id=(
                                "AUTH-run-001"
                                if definition.authorization_required
                                else None
                            ),
                        ),
                        gate_id=f"GATE-{gate_type}-{prerequisite}-uncited",
                        spec_hash="a" * 64,
                        config_hash="b" * 64,
                        run_revision=3,
                    )
                    self.assertEqual("failed", unsupported["result"])
                    self.assertIn(
                        f"prerequisite lacks cited evidence: {prerequisite}",
                        unsupported["reason"],
                    )
                    validate_gate_decision(unsupported)

    def test_release_gate_requires_bound_source_artifact_and_related_receipts(self) -> None:
        evidence_id = "EVID-release-001"
        matching = complete_gate_receipt(
            "run-release",
            evidence_id,
            subject_ids=list(required_prerequisites("RELEASE_GATE")),
            source_commit="release-commit",
            candidate_commit=None,
            release_source_kind="dev",
            release_source_commit="release-commit",
            release_source_tree="release-tree",
            artifact_digest="f" * 64,
            assertions={
                prerequisite: True
                for prerequisite in required_prerequisites("RELEASE_GATE")
            },
        )
        unrelated = dict(
            matching,
            subject_ids=["unrelated-release-observation"],
            assertions={},
        )
        for receipt in (matching, unrelated):
            self.evidence.validate(receipt, check_blobs=False)

        facts = gate_context(
            "RELEASE_GATE",
            evidence_id,
            run_id="run-release",
            source_commit="release-commit",
            release_source_kind="dev",
            release_source_commit="release-commit",
            release_source_tree="release-tree",
            artifact_digest="f" * 64,
        )

        def evaluate(
            receipt: dict[str, object],
            context: dict[str, object],
            gate_id: str,
        ) -> dict[str, object]:
            return GateEvaluator(
                lambda requested: receipt if requested == evidence_id else None,
                evidence_validator=lambda value: self.evidence.validate(
                    value, check_blobs=False
                ),
            ).evaluate(
                GateObservation(
                    gate_type="RELEASE_GATE",
                    subject_ids=("release",),
                    context=context,
                    evidence_ids=(evidence_id,),
                    evaluator="test-evaluator",
                    authorization_id="AUTH-release-001",
                ),
                gate_id=gate_id,
                spec_hash="a" * 64,
                config_hash="b" * 64,
                run_revision=4,
            )

        passed = evaluate(matching, facts, "GATE-release-valid")
        self.assertEqual("passed", passed["result"])
        validate_gate_decision(passed)
        validate_gate_evidence_bindings(
            passed,
            lambda requested: matching if requested == evidence_id else None,
            lambda value: self.evidence.validate(value, check_blobs=False),
        )
        with self.assertRaisesRegex(EvidenceError, "no passing core assertion"):
            validate_gate_evidence_bindings(
                passed,
                lambda requested: unrelated if requested == evidence_id else None,
                lambda value: self.evidence.validate(value, check_blobs=False),
            )

        for missing in ("source_commit", "release_source_commit", "artifact_digest"):
            with self.subTest(missing=missing):
                incomplete = dict(facts)
                incomplete.pop(missing)
                failed = evaluate(
                    matching,
                    incomplete,
                    f"GATE-release-missing-{missing}",
                )
                self.assertEqual("failed", failed["result"])
                self.assertIn(f"RELEASE_GATE requires {missing}", failed["reason"])

        unrelated_decision = evaluate(
            unrelated,
            facts,
            "GATE-release-unrelated",
        )
        self.assertEqual("failed", unrelated_decision["result"])
        self.assertIn("no passing core assertion", unrelated_decision["reason"])

        mismatched = dict(matching, artifact_digest="9" * 64)
        binding_mismatch = evaluate(
            mismatched,
            facts,
            "GATE-release-binding-mismatch",
        )
        self.assertEqual("failed", binding_mismatch["result"])
        self.assertIn("artifact_digest binding mismatch", binding_mismatch["reason"])

        for field, value, expected_reason in (
            ("result", "failed", "result is not gate-satisfying"),
            ("run_id", "other-run", "run binding mismatch"),
            ("spec_hash", "1" * 64, "Spec binding mismatch"),
            ("config_hash", "2" * 64, "config binding mismatch"),
            ("source_commit", "other-commit", "source_commit binding mismatch"),
            (
                "release_source_commit",
                "other-commit",
                "release_source_commit binding mismatch",
            ),
            (
                "release_source_tree",
                "other-tree",
                "release_source_tree binding mismatch",
            ),
        ):
            with self.subTest(receipt_binding=field):
                altered = dict(matching, **{field: value})
                self.evidence.validate(altered, check_blobs=False)
                failed = evaluate(
                    altered,
                    facts,
                    f"GATE-release-wrong-{field}",
                )
                self.assertEqual("failed", failed["result"])
                self.assertIn(expected_reason, failed["reason"])

        deploy_evidence_id = "EVID-deploy-001"
        deploy_receipt = complete_gate_receipt(
            "run-deploy",
            deploy_evidence_id,
            subject_ids=list(required_prerequisites("DEPLOY_GATE")),
            candidate_commit="candidate-commit",
            artifact_digest="f" * 64,
            environment_id="production",
            environment_fingerprint="production-fingerprint",
            assertions={
                name: True for name in required_prerequisites("DEPLOY_GATE")
            },
        )
        self.evidence.validate(deploy_receipt, check_blobs=False)
        deploy_facts = gate_context(
            "DEPLOY_GATE",
            deploy_evidence_id,
            run_id="run-deploy",
            candidate_commit="candidate-commit",
            artifact_digest="f" * 64,
            environment_id="production",
            environment_fingerprint="production-fingerprint",
        )

        def evaluate_deploy(receipt: dict[str, object]) -> dict[str, object]:
            return GateEvaluator(
                lambda requested: (
                    receipt if requested == deploy_evidence_id else None
                ),
                evidence_validator=lambda value: self.evidence.validate(
                    value, check_blobs=False
                ),
            ).evaluate(
                GateObservation(
                    gate_type="DEPLOY_GATE",
                    subject_ids=("production",),
                    context=deploy_facts,
                    evidence_ids=(deploy_evidence_id,),
                    evaluator="test-evaluator",
                    authorization_id="AUTH-deploy-001",
                ),
                gate_id="GATE-deploy-binding",
                spec_hash="a" * 64,
                config_hash="b" * 64,
                run_revision=5,
            )

        self.assertEqual("passed", evaluate_deploy(deploy_receipt)["result"])
        for field, value in (
            ("candidate_commit", "other-candidate"),
            ("artifact_digest", "9" * 64),
            ("environment_id", "staging"),
            ("environment_fingerprint", "staging-fingerprint"),
        ):
            with self.subTest(deploy_binding=field):
                altered = dict(deploy_receipt, **{field: value})
                self.evidence.validate(altered, check_blobs=False)
                failed = evaluate_deploy(altered)
                self.assertEqual("failed", failed["result"])
                self.assertIn(f"{field} binding mismatch", failed["reason"])

        no_resolver = GateEvaluator().evaluate(
            GateObservation(
                gate_type="RELEASE_GATE",
                subject_ids=("release",),
                context=facts,
                evidence_ids=(evidence_id,),
                evaluator="test-evaluator",
                authorization_id="AUTH-release-001",
            ),
            gate_id="GATE-release-no-resolver",
            spec_hash="a" * 64,
            config_hash="b" * 64,
            run_revision=4,
        )
        self.assertEqual("failed", no_resolver["result"])
        self.assertIn("invalid evidence", no_resolver["reason"])

    def test_completion_gate_requires_each_mandatory_acceptance_assertion(self) -> None:
        evidence_id = "EVID-completion-001"
        prerequisites = required_prerequisites("COMPLETION_GATE")
        receipt = complete_gate_receipt(
            "run-completion",
            evidence_id,
            subject_ids=[*prerequisites, "acceptance:V6-AC-001"],
            assertions={
                **{name: True for name in prerequisites},
                "acceptance:V6-AC-001": True,
            },
        )
        facts = gate_context(
            "COMPLETION_GATE", evidence_id, run_id="run-completion"
        )
        facts["mandatory_acceptance_ids"] = ["V6-AC-001", "V6-AC-002"]
        facts["acceptance_evidence"] = {
            "V6-AC-001": [evidence_id],
            "V6-AC-002": [evidence_id],
        }
        decision = GateEvaluator(
            lambda requested: receipt if requested == evidence_id else None,
            evidence_validator=lambda value: self.evidence.validate(
                value, check_blobs=False
            ),
        ).evaluate(
            GateObservation(
                gate_type="COMPLETION_GATE",
                subject_ids=("run-completion",),
                context=facts,
                evidence_ids=(evidence_id,),
                evaluator="completion-test-evaluator",
            ),
            gate_id="GATE-completion-missing-ac",
            spec_hash="a" * 64,
            config_hash="b" * 64,
            run_revision=1,
        )
        self.assertEqual("failed", decision["result"])
        self.assertIn("V6-AC-002", decision["reason"])


class SchemaRuntimeAlignmentTests(CoreFixture):
    def load_schema(self, name: str) -> dict[str, object]:
        return json.loads((TOOLS_ROOT / "schemas" / name).read_text(encoding="utf-8"))

    def assert_schema_shape(
        self, schema: dict[str, object], instance: dict[str, object]
    ) -> None:
        required = set(schema.get("required", []))
        properties = dict(schema.get("properties", {}))
        self.assertTrue(required <= set(instance), required - set(instance))
        if schema.get("additionalProperties") is False:
            self.assertTrue(set(instance) <= set(properties), set(instance) - set(properties))
        for field, definition in properties.items():
            if field not in instance or not isinstance(definition, dict):
                continue
            if "const" in definition:
                self.assertEqual(definition["const"], instance[field], field)
            if "enum" in definition:
                self.assertIn(instance[field], definition["enum"], field)

    def test_schema_required_fields_and_versions_match_runtime_outputs(self) -> None:
        issued_at = utc_now()
        expires_at = later()
        signature = base64.b64encode(b"schema-alignment-signature").decode("ascii")
        authorization_examples: dict[str, tuple[str, dict[str, object]]] = {
            "spec_confirmation": (
                "confirmation-v1.schema.json",
                {
                    "record_type": "spec_confirmation",
                    "confirmation_id": "AUTH-run-schema-001",
                    "spec_id": "SPEC-PROJECT-001",
                    "version": 1,
                    "spec_hash": "a" * 64,
                    "decision": "confirmed",
                    "administrator_identity": "administrator",
                    "issued_at": issued_at,
                    "nonce": "schema-confirmation-nonce",
                    "authenticator_id": "admin-key",
                    "authenticator_signature": signature,
                },
            ),
            "implementation_authorization": (
                "implementation-authorization-v1.schema.json",
                {
                    "record_type": "implementation_authorization",
                    "authorization_id": "AUTH-run-schema-002",
                    "spec_id": "SPEC-PROJECT-001",
                    "version": 1,
                    "spec_hash": "a" * 64,
                    "implementation_scope": {"task": "implement-v6"},
                    "administrator_identity": "administrator",
                    "issued_at": issued_at,
                    "expires_at": expires_at,
                    "nonce": "schema-implementation-nonce",
                    "authenticator_id": "admin-key",
                    "authenticator_signature": signature,
                },
            ),
            "grant": (
                "grant-v1.schema.json",
                {
                    "record_type": "grant",
                    "grant_id": "AUTH-run-schema-003",
                    "run_id": "run-schema",
                    "spec_hash": "a" * 64,
                    "config_hash": "b" * 64,
                    "allowed_actions": ["deploy"],
                    "allowed_environments": ["production"],
                    "allowed_protected_refs": ["refs/heads/dev"],
                    "created_by": "administrator",
                    "created_at": issued_at,
                    "expires_at": expires_at,
                    "request_digest": "c" * 64,
                    "nonce": "schema-grant-nonce",
                    "grant_revision": 1,
                    "authenticator_id": "admin-key",
                    "authenticator_signature": signature,
                    "one_time": False,
                },
            ),
            "approval": (
                "approval-v1.schema.json",
                {
                    "record_type": "approval",
                    "approval_id": "AUTH-run-schema-004",
                    "run_id": "run-schema",
                    "spec_hash": "a" * 64,
                    "config_hash": "b" * 64,
                    "allowed_actions": ["integrate_dev"],
                    "allowed_environments": [],
                    "allowed_protected_refs": ["refs/heads/dev"],
                    "created_by": "administrator",
                    "created_at": issued_at,
                    "expires_at": expires_at,
                    "request_digest": "d" * 64,
                    "nonce": "schema-approval-nonce",
                    "grant_revision": 1,
                    "authenticator_id": "admin-key",
                    "authenticator_signature": signature,
                    "one_time": True,
                },
            ),
            "revocation": (
                "revocation-v1.schema.json",
                {
                    "record_type": "revocation",
                    "revocation_id": "AUTH-run-schema-005",
                    "target_authorization_id": "AUTH-run-schema-003",
                    "run_id": "run-schema",
                    "issued_at": issued_at,
                    "nonce": "schema-revocation-nonce",
                    "authenticator_id": "admin-key",
                    "authenticator_signature": signature,
                },
            ),
        }
        for record_type, (schema_name, example) in authorization_examples.items():
            with self.subTest(record_type=record_type):
                schema = self.load_schema(schema_name)
                self.assertEqual(set(schema["required"]), set(REQUIRED_FIELDS[record_type]))
                self.assert_schema_shape(schema, example)
                self.assertEqual(
                    record_type, validate_authorization_record(example).record_type
                )

        self.create_run("run-schema")
        request_result = self.reducer.create_authorization_request(
            run_id="run-schema",
            expected_revision=0,
            request_id="AUTH-REQUEST-SCHEMA-001",
            request_type="grant",
            scope={"allowed_actions": ["deploy"]},
            expires_at=expires_at,
            idempotency_key="schema-auth-request",
            nonce="schema-auth-request-nonce",
        )
        request_schema = self.load_schema("authorization-request-v1.schema.json")
        self.assert_schema_shape(request_schema, request_result["request"])

        schema_receipt = base_receipt("run-schema", "EVID-run-schema-001")
        schema_receipt["subject_ids"] = list(required_prerequisites("PLAN_GATE"))
        schema_receipt["assertions"] = {
            name: True for name in required_prerequisites("PLAN_GATE")
        }
        receipt = self.evidence.persist(schema_receipt, b"ok", b"")
        evidence_schema = self.load_schema("evidence-receipt-v1.schema.json")
        self.assertEqual(
            set(evidence_schema["required"]),
            set(REQUIRED_RECEIPT_FIELDS) | {"schema_version"},
        )
        self.assertEqual(EVIDENCE_SCHEMA_VERSION, receipt["schema_version"])
        self.assert_schema_shape(evidence_schema, receipt)
        self.evidence.validate(receipt)

        plan_facts = gate_context(
            "PLAN_GATE",
            "EVID-run-schema-001",
            run_id="run-schema",
        )
        decision = GateEvaluator(
            lambda evidence_id: (
                receipt if evidence_id == receipt["evidence_id"] else None
            ),
            evidence_validator=self.evidence.validate,
        ).evaluate(
            GateObservation(
                gate_type="PLAN_GATE",
                subject_ids=("run-schema",),
                context=plan_facts,
                evidence_ids=("EVID-run-schema-001",),
                evaluator="schema-test",
            ),
            gate_id="GATE-run-schema-001",
            spec_hash="a" * 64,
            config_hash="b" * 64,
            run_revision=1,
        )
        gate_schema = self.load_schema("gate-receipt-v1.schema.json")
        self.assertEqual(set(gate_schema["required"]), set(GATE_DECISION_FIELDS))
        self.assert_schema_shape(gate_schema, decision)
        validate_gate_decision(decision)
        unknown = dict(decision, caller_claim=True)
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            validate_gate_decision(unknown)

        transition_document = transition_table_document()
        transition_schema = self.load_schema("transition-table-v1.schema.json")
        self.assert_schema_shape(transition_schema, transition_document)
        transition_row_schema = transition_schema["$defs"]["transition"]
        for row in transition_document["rows"]:
            self.assert_schema_shape(transition_row_schema, row)

        audit_path = self.root / "schema-audit-export.json"
        audit_document = export_audit(self.store.list_audit(), audit_path)
        audit_schema = self.load_schema("audit-export-v1.schema.json")
        self.assert_schema_shape(audit_schema, audit_document)
        audit_record_schema = audit_schema["$defs"]["record"]
        for record in audit_document["records"]:
            self.assert_schema_shape(audit_record_schema, record)
        self.assertEqual(audit_document, json.loads(audit_path.read_text(encoding="utf-8")))


class AuthorizationTests(CoreFixture):
    def setUp(self) -> None:
        super().setUp()
        self.private_key = self.root / "admin-private.pem"
        self.public_key = self.root / "admin-public.pem"
        subprocess.run(
            ["openssl", "genrsa", "-out", str(self.private_key), "2048"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "openssl",
                "rsa",
                "-in",
                str(self.private_key),
                "-pubout",
                "-out",
                str(self.public_key),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.verifier = OpenSSLSignatureVerifier({"admin-key": self.public_key})

    def sign(self, record: dict[str, object]) -> dict[str, object]:
        unsigned = dict(record)
        unsigned.pop("authenticator_signature", None)
        payload = self.root / "payload-to-sign.json"
        signature = self.root / "signature.bin"
        payload.write_bytes(signed_payload(unsigned))
        subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(self.private_key),
                "-out",
                str(signature),
                str(payload),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        unsigned["authenticator_signature"] = base64.b64encode(
            signature.read_bytes()
        ).decode("ascii")
        return unsigned

    def create_grant(
        self, run_id: str = "run-auth", *, one_time: bool = False
    ) -> tuple[dict[str, object], int]:
        self.create_run(run_id)
        requested = self.reducer.create_authorization_request(
            run_id=run_id,
            expected_revision=0,
            request_id="AUTH-REQUEST-001",
            request_type="grant",
            scope={
                "run_id": run_id,
                "spec_hash": "a" * 64,
                "config_hash": "b" * 64,
                "allowed_actions": [
                    "credential_probe",
                    "deploy",
                    "mode_set_auto",
                    "mode_set_staged",
                    "cancel",
                ],
                "allowed_environments": ["production"],
                "allowed_protected_refs": [],
            },
            expires_at=later(),
            idempotency_key="request-grant",
            nonce="grant-nonce-001",
        )
        challenge = requested["request"]
        record = self.sign(
            {
                "record_type": "grant",
                "grant_id": "AUTH-run-auth-001",
                "run_id": run_id,
                "spec_hash": "a" * 64,
                "config_hash": "b" * 64,
                "allowed_actions": [
                    "credential_probe",
                    "deploy",
                    "mode_set_auto",
                    "mode_set_staged",
                    "cancel",
                ],
                "allowed_environments": ["production"],
                "allowed_protected_refs": [],
                "created_by": "administrator",
                "created_at": utc_now(),
                "expires_at": later(),
                "request_digest": challenge["request_digest"],
                "nonce": challenge["nonce"],
                "grant_revision": challenge["expected_revision"],
                "authenticator_id": "admin-key",
                "one_time": one_time,
            }
        )
        imported = self.reducer.import_authorization(
            record,
            self.verifier,
            expected_revision=1,
            idempotency_key="import-grant",
        )
        return record, imported["revision"]

    def test_mode_change_requires_plan_and_consumes_one_time_approval(self) -> None:
        _grant, revision = self.create_grant(one_time=True)
        with self.assertRaisesRegex(TransitionError, "passed PLAN_GATE"):
            self.reducer.set_mode(
                run_id="run-auth",
                expected_revision=revision,
                mode="auto",
                authorization_id="AUTH-run-auth-001",
                idempotency_key="premature-mode",
            )
        # State entry is covered by lifecycle tests; this fixture isolates the
        # transactional one-time-consumption boundary.
        with self.store._write_transaction() as connection:
            connection.execute(
                "UPDATE runs SET state = 'READY' WHERE run_id = 'run-auth'"
            )
        changed = self.reducer.set_mode(
            run_id="run-auth",
            expected_revision=revision,
            mode="auto",
            authorization_id="AUTH-run-auth-001",
            idempotency_key="approved-mode",
        )
        self.assertEqual("auto", changed["mode"])
        with self.assertRaisesRegex(AuthorizationError, "already consumed"):
            self.reducer.set_mode(
                run_id="run-auth",
                expected_revision=int(changed["revision"]),
                mode="staged",
                authorization_id="AUTH-run-auth-001",
                idempotency_key="reused-mode-approval",
            )

    def test_nonprotected_ref_authorization_rejects_unknown_or_expanded_scope(
        self,
    ) -> None:
        expires_at = later()
        exact_scope: dict[str, object] = {
            "grant_id": "backup-review-branch",
            "action": "push_backup",
            "remote": "origin",
            "ref": "refs/heads/review/exact",
            "expected_sha": "c" * 40,
            "force": False,
            "one_time": True,
            "expires_at": expires_at,
        }
        base: dict[str, object] = {
            "record_type": "grant",
            "grant_id": "AUTH-git-shape-001",
            "run_id": "run-git-shape",
            "spec_hash": "a" * 64,
            "config_hash": "b" * 64,
            "allowed_actions": ["push_backup"],
            "allowed_environments": [],
            "allowed_protected_refs": [],
            "created_by": "administrator",
            "created_at": utc_now(),
            "expires_at": expires_at,
            "request_digest": "d" * 64,
            "nonce": "git-shape-nonce",
            "grant_revision": 1,
            "authenticator_id": "admin-key",
            "one_time": True,
            "nonprotected_ref": exact_scope,
        }
        self.verifier.verify(self.sign(base))

        unknown_top_level = {**base, "caller_claim": True}
        with self.assertRaisesRegex(AuthorizationError, "unknown fields"):
            self.verifier.verify(self.sign(unknown_top_level))

        unknown_nested = {
            **base,
            "nonprotected_ref": {**exact_scope, "environment": "production"},
        }
        with self.assertRaisesRegex(AuthorizationError, "fields are not exact"):
            self.verifier.verify(self.sign(unknown_nested))

        expanded_action = {
            **base,
            "allowed_actions": ["push_backup", "delete_remote"],
        }
        with self.assertRaisesRegex(AuthorizationError, "only its exact action"):
            self.verifier.verify(self.sign(expanded_action))

    def test_signature_scope_replay_expiry_and_revocation(self) -> None:
        grant, revision = self.create_grant()
        self.assertEqual(2, revision)
        with self.assertRaises(TransitionError):
            self.reducer.import_authorization(
                grant,
                self.verifier,
                idempotency_key="import-grant",
            )
        tampered = dict(grant)
        tampered["allowed_actions"] = ["deploy", "release"]
        with self.assertRaises(AuthorizationError):
            self.verifier.verify(tampered)
        with self.assertRaises(AuthorizationError):
            self.reducer.import_authorization(
                grant,
                self.verifier,
                idempotency_key="replayed-nonce",
            )

        expired = dict(grant)
        expired.update(
            {
                "grant_id": "AUTH-run-auth-002",
                "nonce": "expired-nonce",
                "created_at": earlier(1200),
                "expires_at": earlier(600),
            }
        )
        expired = self.sign(expired)
        with self.assertRaises(AuthorizationError):
            self.verifier.verify(expired)

        premature_mutations = (
            ("integrate_dev", "protected_ref", "INTEGRATING_DEV"),
            ("release", "release", "RELEASING"),
            ("publish", "publish", "RELEASING"),
            ("deploy", "deploy", "DEPLOYING"),
            ("rollback", "rollback", "ROLLING_BACK"),
        )
        for index, (action, kind, state) in enumerate(
            premature_mutations, start=1
        ):
            with self.subTest(premature_mutation=action), self.assertRaisesRegex(
                TransitionError, f"requires run state {state}"
            ):
                self.reducer.start_operation(
                    run_id="run-auth",
                    expected_revision=revision,
                    operation_id=f"OP-run-auth-bypass-{index:03d}",
                    action_id=action,
                    operation_kind=kind,
                    idempotency_key=f"{action}-before-gate",
                    authorization_id="AUTH-run-auth-001",
                    scope={
                        "environment_id": "production",
                        "protected_ref": "dev",
                    },
                )

        started = self.reducer.start_operation(
            run_id="run-auth",
            expected_revision=revision,
            operation_id="OP-run-auth-001",
            action_id="credential_probe",
            operation_kind="agent",
            idempotency_key="credential-probe-idempotency-001",
            authorization_id="AUTH-run-auth-001",
            scope={"environment_id": "production"},
        )
        self.assertEqual("started", started["status"])
        observed = self.reducer.record_operation_observation(
            OperationObservation(
                operation_id="OP-run-auth-001",
                action_id="credential_probe",
                status="succeeded",
                effect_id="fake-deploy-001",
                result={"environment_id": "production"},
            ),
            run_id="run-auth",
            expected_revision=3,
            idempotency_key="observe-deploy-001",
        )
        self.assertEqual("completed", observed["status"])

        revocation = self.sign(
            {
                "record_type": "revocation",
                "revocation_id": "AUTH-run-auth-002",
                "target_authorization_id": "AUTH-run-auth-001",
                "run_id": "run-auth",
                "issued_at": utc_now(),
                "nonce": "revoke-nonce-001",
                "authenticator_id": "admin-key",
            }
        )
        revoked = self.reducer.import_authorization(
            revocation,
            self.verifier,
            expected_revision=4,
            idempotency_key="revoke-grant",
        )
        self.assertEqual(5, revoked["revision"])
        with self.assertRaises(AuthorizationError):
            self.reducer.start_operation(
                run_id="run-auth",
                expected_revision=5,
                operation_id="OP-run-auth-002",
                action_id="credential_probe",
                operation_kind="agent",
                idempotency_key="credential-probe-idempotency-002",
                authorization_id="AUTH-run-auth-001",
                scope={"environment_id": "production"},
            )
        self.assertIsNone(self.store.get_operation("OP-run-auth-002"))

    def test_revoke_start_race_has_one_serial_order(self) -> None:
        _grant, revision = self.create_grant("run-auth")
        revocation = self.sign(
            {
                "record_type": "revocation",
                "revocation_id": "AUTH-run-auth-099",
                "target_authorization_id": "AUTH-run-auth-001",
                "run_id": "run-auth",
                "issued_at": utc_now(),
                "nonce": "race-revoke-nonce",
                "authenticator_id": "admin-key",
            }
        )
        barrier = threading.Barrier(2)
        outcomes: dict[str, object] = {}

        def start() -> None:
            local = Store(self.store.path)
            try:
                reducer = Reducer(local, evidence_store=self.evidence)
                barrier.wait()
                try:
                    outcomes["start"] = reducer.start_operation(
                        run_id="run-auth",
                        expected_revision=revision,
                        operation_id="OP-run-auth-race-001",
                        action_id="credential_probe",
                        operation_kind="agent",
                        idempotency_key="credential-probe-race",
                        authorization_id="AUTH-run-auth-001",
                        scope={"environment_id": "production"},
                    )
                except Exception as exc:  # assertion inspects the exact safe outcome
                    outcomes["start"] = exc
            finally:
                local.close()

        def revoke() -> None:
            local = Store(self.store.path)
            try:
                reducer = Reducer(local, evidence_store=self.evidence)
                barrier.wait()
                try:
                    outcomes["revoke"] = reducer.import_authorization(
                        revocation,
                        self.verifier,
                        idempotency_key="revoke-race",
                    )
                except Exception as exc:  # assertion inspects the exact safe outcome
                    outcomes["revoke"] = exc
            finally:
                local.close()

        threads = [threading.Thread(target=start), threading.Thread(target=revoke)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertIsInstance(outcomes["revoke"], dict)
        self.assertTrue(self.store.authorization_is_revoked("AUTH-run-auth-001"))
        operation = self.store.get_operation("OP-run-auth-race-001")
        if isinstance(outcomes["start"], dict):
            self.assertIsNotNone(operation)
            self.assertEqual("started", operation["status"])
        else:
            self.assertIsNone(operation)
            self.assertIsInstance(
                outcomes["start"], (AuthorizationError, TransitionError)
            )

    def test_cancelled_run_invalidates_old_and_pending_grants_but_allows_revocation(
        self,
    ) -> None:
        _grant, revision = self.create_grant()
        pending_request = self.reducer.create_authorization_request(
            run_id="run-auth",
            expected_revision=revision,
            request_id="AUTH-REQUEST-TERMINAL-002",
            request_type="grant",
            scope={
                "run_id": "run-auth",
                "spec_hash": "a" * 64,
                "config_hash": "b" * 64,
                "allowed_actions": ["deploy"],
                "allowed_environments": ["production"],
                "allowed_protected_refs": [],
            },
            expires_at=later(),
            idempotency_key="request-pending-terminal-grant",
            nonce="pending-terminal-grant-nonce",
        )["request"]
        pending_grant = self.sign(
            {
                "record_type": "grant",
                "grant_id": "AUTH-run-auth-777",
                "run_id": "run-auth",
                "spec_hash": "a" * 64,
                "config_hash": "b" * 64,
                "allowed_actions": ["deploy"],
                "allowed_environments": ["production"],
                "allowed_protected_refs": [],
                "created_by": "administrator",
                "created_at": utc_now(),
                "expires_at": later(),
                "request_digest": pending_request["request_digest"],
                "nonce": pending_request["nonce"],
                "grant_revision": pending_request["expected_revision"],
                "authenticator_id": "admin-key",
                "one_time": False,
            }
        )
        cancelled = self.reducer.transition(
            TransitionProposal(
                run_id="run-auth",
                expected_revision=3,
                event="CANCEL",
                actor="trusted-control-plane",
                idempotency_key="cancel-terminal-run",
                payload={
                    "actors_fenced": True,
                    "external_operations_reconciled": True,
                },
                authorization_id="AUTH-run-auth-001",
            )
        )
        self.assertEqual("CANCELLED", cancelled["state"])
        self.assertEqual(4, cancelled["run_revision"])

        with self.assertRaisesRegex(AuthorizationError, "terminal state CANCELLED"):
            self.reducer.start_operation(
                run_id="run-auth",
                expected_revision=4,
                operation_id="OP-run-auth-terminal-001",
                action_id="deploy",
                operation_kind="deploy",
                idempotency_key="deploy-after-cancel",
                authorization_id="AUTH-run-auth-001",
                scope={"environment_id": "production"},
            )
        with self.assertRaisesRegex(AuthorizationError, "terminal state CANCELLED"):
            self.reducer.import_authorization(
                pending_grant,
                self.verifier,
                expected_revision=4,
                idempotency_key="import-after-cancel",
            )
        self.assertIsNone(self.store.get_operation("OP-run-auth-terminal-001"))
        self.assertIsNone(self.store.get_authorization("AUTH-run-auth-777"))

        revocation = self.sign(
            {
                "record_type": "revocation",
                "revocation_id": "AUTH-run-auth-778",
                "target_authorization_id": "AUTH-run-auth-001",
                "run_id": "run-auth",
                "issued_at": utc_now(),
                "nonce": "terminal-revocation-nonce",
                "authenticator_id": "admin-key",
            }
        )
        revoked = self.reducer.import_authorization(
            revocation,
            self.verifier,
            expected_revision=4,
            idempotency_key="revoke-after-cancel",
        )
        self.assertEqual(5, revoked["revision"])
        self.assertTrue(self.store.authorization_is_revoked("AUTH-run-auth-001"))

    def test_all_terminal_states_reject_old_grant_operations_and_mode_change(self) -> None:
        _grant, revision = self.create_grant()
        for index, state in enumerate(("COMPLETED", "FAILED", "ROLLED_BACK"), start=1):
            # Inject only the materialized terminal fixture to isolate the entry-point
            # guard; legitimate paths into each state are tested by transition suites.
            with self.store._write_transaction() as connection:
                connection.execute(
                    "UPDATE runs SET state = ? WHERE run_id = ?",
                    (state, "run-auth"),
                )
            with self.subTest(state=state, action="operation"):
                with self.assertRaisesRegex(AuthorizationError, f"terminal state {state}"):
                    self.reducer.start_operation(
                        run_id="run-auth",
                        expected_revision=revision,
                        operation_id=f"OP-run-auth-terminal-{index:03d}",
                        action_id="deploy",
                        operation_kind="deploy",
                        idempotency_key=f"deploy-terminal-{index}",
                        authorization_id="AUTH-run-auth-001",
                        scope={"environment_id": "production"},
                    )
            with self.subTest(state=state, action="mode"):
                with self.assertRaisesRegex(AuthorizationError, f"terminal state {state}"):
                    self.reducer.set_mode(
                        run_id="run-auth",
                        expected_revision=revision,
                        mode="auto",
                        authorization_id="AUTH-run-auth-001",
                        idempotency_key=f"mode-terminal-{index}",
                    )
        self.assertEqual("staged", self.store.get_run("run-auth")["mode"])
        high_impact_events = [
            event
            for event in self.store.list_events("run-auth")
            if event["event_type"] in {"EXTERNAL_OPERATION_STARTED", "MODE_CHANGED"}
        ]
        self.assertEqual([], high_impact_events)


if __name__ == "__main__":
    unittest.main()
