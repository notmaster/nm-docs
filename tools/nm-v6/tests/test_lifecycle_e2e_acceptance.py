from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence


TOOL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = TOOL_ROOT.parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from nmv6.actions import ACTION_RESULT_SCHEMA, ActionDefinition, ActionExecutor  # noqa: E402
from nmv6.authorization import validate_authorization_record  # noqa: E402
from nmv6.controller import WorkflowController  # noqa: E402
from nmv6.errors import (  # noqa: E402
    ActionError,
    AuthorizationError,
    ContractError,
    GitPolicyError,
    TransitionError,
)
from nmv6.evidence import EvidenceStore  # noqa: E402
from nmv6.gates import (  # noqa: E402
    GATE_DEFINITIONS,
    GateEvaluator,
    required_bindings,
)
from nmv6.git_controller import GitController  # noqa: E402
from nmv6.models import GateObservation, OperationObservation, TransitionProposal  # noqa: E402
from nmv6.reducer import Reducer, required_mutation_scope_fields  # noqa: E402
from nmv6.scheduler import Lease, Scheduler, TaskDefinition, TaskGraph  # noqa: E402
from nmv6.specs import canonical_spec_hash  # noqa: E402
from nmv6.store import Store  # noqa: E402
from nmv6.runtime import compose_runtime  # noqa: E402
from nmv6.template_sync import initialize_project  # noqa: E402
from nmv6.util import canonical_json, sha256_bytes, utc_now  # noqa: E402
from nmv6.workspace import IsolatedCommand  # noqa: E402


SPEC_TEMPLATE = """---
spec_id: SPEC-LIFECYCLE-E2E
document_title: Lifecycle E2E
version: 1
workflow: v6
language: en
normative: true
admin_mirror: lifecycle-e2e.zh-CN.md
status: confirmed
implementation_authorized: true
---
# Fixture

{body}
"""


def lifecycle_traceability() -> dict[str, object]:
    return {
        "goals": [{"goal_id": "GOAL-001"}],
        "requirements": [
            {"requirement_id": "REQ-001", "goal_ids": ["GOAL-001"]}
        ],
        "acceptance_criteria": [
            {
                "acceptance_id": "AC-001",
                "requirement_ids": ["REQ-001"],
                "mandatory": True,
                "required_by_stage": "completion",
            }
        ],
        "phases": [{"phase_id": "PHASE-001", "depends_on": []}],
        "tasks": [
            {
                "task_id": "TASK-001",
                "phase_id": "PHASE-001",
                "acceptance_ids": ["AC-001"],
                "enabling_requirement_ids": [],
                "dependencies": [],
                "optional": False,
            }
        ],
        "acceptance_actions": {},
        "required_delivery_stages": {
            "release": "required",
            "deploy": "required",
            "environments": ["production"],
        },
    }


class FixtureVerifier:
    """A fake trusted boundary used only by disposable acceptance fixtures."""

    @staticmethod
    def verify(record: Mapping[str, Any], *, now: datetime | None = None) -> Any:
        return validate_authorization_record(record, now=now)


class FixtureLeaseAuthority:
    def __init__(self) -> None:
        self.current: dict[str, Lease] = {}
        self.token = 0

    def acquire(
        self,
        *,
        task_id: str,
        owner: str,
        attempt_id: str,
        expected_revision: int,
        lease_seconds: int,
        write_set: tuple[str, ...],
    ) -> Lease:
        if task_id in self.current:
            raise TransitionError("task is already leased")
        self.token += 1
        lease = Lease(
            task_id,
            owner,
            attempt_id,
            self.token,
            (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat(),
            expected_revision + 1,
        )
        self.current[task_id] = lease
        return lease

    def heartbeat(
        self,
        *,
        task_id: str,
        owner: str,
        fencing_token: int,
        expected_revision: int,
        lease_seconds: int,
    ) -> Lease:
        current = self.current[task_id]
        if current.owner != owner or current.fencing_token != fencing_token:
            raise TransitionError("stale lease")
        return current

    def release(
        self,
        *,
        task_id: str,
        owner: str,
        fencing_token: int,
        expected_revision: int,
    ) -> None:
        del expected_revision
        current = self.current[task_id]
        if current.owner != owner or current.fencing_token != fencing_token:
            raise TransitionError("stale lease")
        del self.current[task_id]


class TestIsolationBackend:
    name = "lifecycle-test-isolation"

    def wrap(
        self,
        argv: Sequence[str],
        *,
        workspace: Path,
        cwd: Path,
        allow_network: bool = False,
    ) -> IsolatedCommand:
        del workspace, allow_network
        return IsolatedCommand(tuple(argv), cwd)


class DetachedFailureLauncher:
    """Launch a child that owns no in-memory parent controller state."""

    def __init__(self, database: Path, receipt_root: Path) -> None:
        self.database = database
        self.receipt_root = receipt_root
        self.processes: list[subprocess.Popen[bytes]] = []

    def launch(self, run_id: str) -> Mapping[str, Any]:
        controller_id = f"controller-{run_id}"
        receipt = self.receipt_root / f"{controller_id}.json"
        receipt.write_text(
            json.dumps({"controller_id": controller_id, "run_id": run_id}),
            encoding="utf-8",
        )
        code = """
import sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from nmv6.models import TransitionProposal
from nmv6.reducer import Reducer
from nmv6.store import Store
time.sleep(0.15)
store = Store(Path(sys.argv[2]))
try:
    run = store.get_run(sys.argv[3])
    Reducer(store).transition(TransitionProposal(
        run_id=sys.argv[3], expected_revision=int(run['revision']),
        event='FAIL_UNRECOVERABLE', actor='detached-controller',
        idempotency_key='detached-terminal-failure',
        payload={'failure_classified': True, 'actors_fenced': True,
                 'external_operations_reconciled': True}))
finally:
    store.close()
"""
        self.processes.append(
            subprocess.Popen(
                [sys.executable, "-c", code, str(TOOL_ROOT), str(self.database), run_id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        )
        return {"controller_id": controller_id, "receipt": str(receipt)}


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


class LifecycleE2EAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "state.sqlite3"
        self.evidence_store = EvidenceStore(self.root / "evidence")
        self.store = Store(self.database)
        self.reducer = Reducer(self.store, evidence_store=self.evidence_store)
        self.verifier = FixtureVerifier()
        self.sequence = 0

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def _next(self) -> int:
        self.sequence += 1
        return self.sequence

    def _run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        self.assertIsNotNone(run)
        return dict(run or {})

    def _create_run(
        self,
        run_id: str,
        *,
        mode: str = "staged",
        spec_hash: str | None = None,
        config_hash: str | None = None,
    ) -> None:
        self.reducer.create_run(
            run_id=run_id,
            spec_hash=spec_hash or "a" * 64,
            config_hash=config_hash or "b" * 64,
            mode=mode,
            idempotency_key=f"create:{run_id}",
            payload={
                "normal_run": True,
                "all_phases_done": True,
                "release_required": True,
                "deploy_required": True,
                "traceability": lifecycle_traceability(),
            },
        )

    def _transition(
        self,
        run_id: str,
        event: str,
        *,
        payload: Mapping[str, Any] | None = None,
        gate_ids: Sequence[str] = (),
        authorization_id: str | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id)
        return self.reducer.transition(
            TransitionProposal(
                run_id=run_id,
                expected_revision=int(run["revision"]),
                event=event,
                actor="lifecycle-e2e",
                idempotency_key=f"transition:{run_id}:{event}:{self._next()}",
                payload=dict(payload or {}),
                gate_ids=tuple(gate_ids),
                authorization_id=authorization_id,
            )
        )

    def _confirmation(self, run_id: str) -> str:
        run = self._run(run_id)
        requested = self.reducer.create_authorization_request(
            run_id=run_id,
            expected_revision=int(run["revision"]),
            request_id=f"AUTHREQ-confirm-{self._next()}",
            request_type="spec_confirmation",
            scope={"spec_hash": run["spec_hash"], "decision": "confirmed"},
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            idempotency_key=f"request-confirm:{run_id}:{self.sequence}",
            nonce=f"confirm-nonce-{self.sequence}",
        )["request"]
        confirmation_id = f"AUTH-{run_id}-confirm-{self._next()}"
        record = {
            "record_type": "spec_confirmation",
            "confirmation_id": confirmation_id,
            "spec_id": "SPEC-LIFECYCLE-E2E",
            "version": 1,
            "spec_hash": run["spec_hash"],
            "decision": "confirmed",
            "administrator_identity": "fixture-administrator",
            "issued_at": utc_now(),
            "nonce": requested["nonce"],
            "authenticator_id": "fixture-key",
            "authenticator_signature": base64.b64encode(b"fixture").decode("ascii"),
        }
        self.reducer.import_authorization(
            record,
            self.verifier,
            expected_revision=int(requested["expected_revision"]),
            idempotency_key=f"import-confirm:{run_id}:{self.sequence}",
        )
        return confirmation_id

    def _grant(
        self,
        run_id: str,
        *,
        actions: Sequence[str],
        environments: Sequence[str] = (),
        protected_refs: Sequence[str] = (),
    ) -> str:
        run = self._run(run_id)
        scope = {
            "run_id": run_id,
            "spec_hash": run["spec_hash"],
            "config_hash": run["config_hash"],
            "allowed_actions": list(actions),
            "allowed_environments": list(environments),
            "allowed_protected_refs": list(protected_refs),
        }
        requested = self.reducer.create_authorization_request(
            run_id=run_id,
            expected_revision=int(run["revision"]),
            request_id=f"AUTHREQ-grant-{self._next()}",
            request_type="grant",
            scope=scope,
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            idempotency_key=f"request-grant:{run_id}:{self.sequence}",
            nonce=f"grant-nonce-{self.sequence}",
        )["request"]
        grant_id = f"AUTH-{run_id}-grant-{self._next()}"
        record = {
            "record_type": "grant",
            "grant_id": grant_id,
            **scope,
            "created_by": "fixture-administrator",
            "created_at": utc_now(),
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "request_digest": requested["request_digest"],
            "nonce": requested["nonce"],
            "grant_revision": requested["expected_revision"],
            "authenticator_id": "fixture-key",
            "authenticator_signature": base64.b64encode(b"fixture").decode("ascii"),
            "one_time": False,
        }
        self.reducer.import_authorization(
            record,
            self.verifier,
            expected_revision=int(requested["expected_revision"]),
            idempotency_key=f"import-grant:{run_id}:{self.sequence}",
        )
        return grant_id

    def _revoke(self, run_id: str, grant_id: str) -> str:
        run = self._run(run_id)
        revocation_id = f"AUTH-{run_id}-revoke-{self._next()}"
        record = {
            "record_type": "revocation",
            "revocation_id": revocation_id,
            "target_authorization_id": grant_id,
            "run_id": run_id,
            "issued_at": utc_now(),
            "nonce": f"revoke-nonce-{self.sequence}",
            "authenticator_id": "fixture-key",
            "authenticator_signature": base64.b64encode(b"fixture").decode("ascii"),
        }
        self.reducer.import_authorization(
            record,
            self.verifier,
            expected_revision=int(run["revision"]),
            idempotency_key=f"revoke:{run_id}:{self.sequence}",
        )
        return revocation_id

    def _evidence(
        self,
        run_id: str,
        subject: str | Sequence[str],
        *,
        bindings: Mapping[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        run = self._run(run_id)
        number = self._next()
        evidence_id = f"EVID-{run_id}-{number:03d}"
        timestamp = utc_now()
        subjects = [subject] if isinstance(subject, str) else list(subject)
        bound = dict(bindings or {})
        receipt = self.evidence_store.persist(
            {
                "evidence_id": evidence_id,
                "evidence_type": "deterministic_acceptance",
                "producer": "core-gate-executor",
                "run_id": run_id,
                "subject_ids": subjects,
                "assertions": {name: True for name in subjects},
                "spec_hash": run["spec_hash"],
                "config_hash": run["config_hash"],
                "source_commit": bound.get("source_commit"),
                "candidate_commit": bound.get("candidate_commit"),
                "release_source_kind": bound.get("release_source_kind"),
                "release_source_commit": bound.get("release_source_commit"),
                "release_source_tree": bound.get("release_source_tree"),
                "hotfix_reconciliation_gate_id": bound.get(
                    "hotfix_reconciliation_gate_id"
                ),
                "artifact_digest": bound.get("artifact_digest"),
                "environment_id": bound.get("environment_id"),
                "environment_fingerprint": bound.get("environment_fingerprint"),
                "operation_id": None,
                "attempt_id": None,
                "command_action_id": "fixture-verify",
                "argv_digest": "c" * 64,
                "working_directory": ".",
                "started_at": timestamp,
                "finished_at": timestamp,
                "exit_code": 0,
                "result": "passed",
                "tool_versions": {"fixture": "1"},
                "producer_version": "fixture/1",
                "evaluator_version": "fixture/1",
            },
            f"passed {','.join(subjects)}\n".encode(),
            b"",
        )
        self.reducer.record_evidence(
            run_id=run_id,
            expected_revision=int(run["revision"]),
            receipt=receipt,
            idempotency_key=f"evidence:{evidence_id}",
        )
        return evidence_id, receipt

    def _gate(
        self,
        run_id: str,
        gate_type: str,
        *,
        authorization_id: str | None = None,
        fail_prerequisite: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        prerequisites = GATE_DEFINITIONS[gate_type].prerequisites
        defaults: dict[str, Any] = {
            "source_commit": "a" * 40,
            "candidate_commit": "c" * 40,
            "target_commit": "d" * 40,
            "release_source_kind": "dev",
            "release_source_commit": "a" * 40,
            "release_source_tree": "b" * 40,
            "artifact_digest": "f" * 64,
            "environment_id": "production",
            "environment_fingerprint": "production-fingerprint",
        }
        bindings = {
            field: defaults[field] for field in required_bindings(gate_type)
        }
        evidence_subjects = list(prerequisites)
        if gate_type == "COMPLETION_GATE":
            evidence_subjects.append("acceptance:AC-001")
        evidence_id, _ = self._evidence(
            run_id, evidence_subjects, bindings=bindings
        )
        run = self._run(run_id)
        facts = {name: True for name in prerequisites}
        facts["run_id"] = run_id
        facts.update(bindings)
        facts["prerequisite_evidence"] = {
            name: [evidence_id] for name in prerequisites
        }
        if gate_type == "COMPLETION_GATE":
            facts["mandatory_acceptance_ids"] = ["AC-001"]
            facts["acceptance_evidence"] = {"AC-001": [evidence_id]}
        if fail_prerequisite:
            facts[fail_prerequisite] = False
        gate_id = f"GATE-{run_id}-{self._next():03d}"
        decision = GateEvaluator(
            self.store.get_evidence,
            evidence_validator=self.evidence_store.validate,
        ).evaluate(
            GateObservation(
                gate_type=gate_type,
                subject_ids=(run_id,),
                context=facts,
                evidence_ids=(evidence_id,),
                evaluator="deterministic-fixture",
                authorization_id=authorization_id,
            ),
            gate_id=gate_id,
            spec_hash=str(run["spec_hash"]),
            config_hash=str(run["config_hash"]),
            run_revision=int(run["revision"]),
        )
        self.reducer.record_gate(
            run_id=run_id,
            expected_revision=int(run["revision"]),
            decision=decision,
            idempotency_key=f"gate:{gate_id}",
        )
        return gate_id, decision

    def _advance_through_plan(self, run_id: str, *, mode: str) -> str:
        self._create_run(run_id, mode=mode)
        self._transition(run_id, "DRAFT_SPEC", payload={"discovery_complete": True})
        self._transition(run_id, "SUBMIT_SPEC_REVIEW")
        self._transition(run_id, "REQUEST_SPEC_CONFIRMATION")
        confirmation_id = self._confirmation(run_id)
        spec_gate, decision = self._gate(
            run_id, "SPEC_GATE", authorization_id=confirmation_id
        )
        self.assertEqual("passed", decision["result"])
        self._transition(
            run_id,
            "CONFIRM_SPEC",
            gate_ids=(spec_gate,),
            authorization_id=confirmation_id,
        )
        self._transition(run_id, "START_PLANNING")
        plan_gate, _ = self._gate(run_id, "PLAN_GATE")
        self._transition(run_id, "PLAN_READY", gate_ids=(plan_gate,))
        return confirmation_id

    def _start_operation(
        self,
        run_id: str,
        action: str,
        kind: str,
        grant_id: str,
        *,
        gate_id: str | None = None,
        scope: Mapping[str, Any] | None = None,
        suffix: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        run = self._run(run_id)
        operation_number = suffix if suffix is not None else self._next()
        operation_id = f"OP-{run_id}-{operation_number:03d}"
        complete_scope = self._complete_mutation_scope(
            action, gate_id, dict(scope or {})
        )
        result = self.reducer.start_operation(
            run_id=run_id,
            expected_revision=int(run["revision"]),
            operation_id=operation_id,
            action_id=action,
            operation_kind=kind,
            idempotency_key=f"operation:{operation_id}",
            authorization_id=grant_id,
            gate_id=gate_id,
            scope=complete_scope,
        )
        return operation_id, result

    def _complete_mutation_scope(
        self,
        action: str,
        gate_id: str | None,
        scope: Mapping[str, Any],
    ) -> dict[str, Any]:
        completed = dict(scope)
        if gate_id is None:
            return completed
        try:
            required = required_mutation_scope_fields(action)
        except ContractError:
            return completed
        decision = self.store.get_gate(gate_id)
        if not isinstance(decision, Mapping):
            return completed
        for field in required:
            if field != "protected_ref" and field not in completed:
                completed[field] = decision.get(field)
        return completed

    def _prepare_mutation_operation(
        self,
        run_id: str,
        action: str,
        kind: str,
        scope: Mapping[str, Any],
        *,
        start_operation: bool = True,
    ) -> tuple[str, str, str]:
        """Enter the real gated lifecycle stage before starting one mutation."""

        self._advance_through_plan(run_id, mode="auto")
        grant_id = self._grant(
            run_id,
            actions=(
                "integrate_dev",
                "release",
                "publish",
                "deploy",
                "rollback",
                "cancel",
            ),
            environments=("production",),
            protected_refs=("dev", "main"),
        )
        self._transition(run_id, "START_IMPLEMENTATION")
        self._transition(run_id, "START_PHASE_VERIFICATION")
        phase_gate, _ = self._gate(run_id, "PHASE_GATE")
        dev_gate, _ = self._gate(
            run_id, "DEV_INTEGRATION_GATE", authorization_id=grant_id
        )
        self._transition(
            run_id,
            "START_DEV_INTEGRATION",
            payload={"protected_ref": "dev"},
            gate_ids=(phase_gate, dev_gate),
            authorization_id=grant_id,
        )
        if action == "integrate_dev":
            if not start_operation:
                return grant_id, dev_gate, ""
            operation_id, _ = self._start_operation(
                run_id,
                action,
                kind,
                grant_id,
                gate_id=dev_gate,
                scope=scope,
            )
            return grant_id, dev_gate, operation_id

        integration_operation, _ = self._start_operation(
            run_id,
            "integrate_dev",
            "protected_ref",
            grant_id,
            gate_id=dev_gate,
            scope={"protected_ref": "dev"},
        )
        self._observe(
            run_id,
            integration_operation,
            "integrate_dev",
            "succeeded",
            effect_id=f"dev-{run_id}",
            result={"protected_ref": "dev"},
        )
        self._transition(
            run_id,
            "DEV_INTEGRATION_APPLIED",
            payload={"protected_ref": "dev"},
            gate_ids=(dev_gate,),
            authorization_id=grant_id,
        )
        integration_result_gate, _ = self._gate(
            run_id, "DEV_INTEGRATION_RESULT_GATE"
        )
        self._transition(
            run_id,
            "ALL_PHASES_INTEGRATED",
            payload={"all_phases_done": True},
            gate_ids=(integration_result_gate,),
        )
        release_gate, _ = self._gate(
            run_id, "RELEASE_GATE", authorization_id=grant_id
        )
        self._transition(
            run_id,
            "START_RELEASE",
            payload={"release_required": True, "protected_ref": "main"},
            gate_ids=(release_gate,),
            authorization_id=grant_id,
        )
        if action in {"release", "publish"}:
            if not start_operation:
                return grant_id, release_gate, ""
            operation_id, _ = self._start_operation(
                run_id,
                action,
                kind,
                grant_id,
                gate_id=release_gate,
                scope=scope,
            )
            return grant_id, release_gate, operation_id

        release_operation, _ = self._start_operation(
            run_id,
            "release",
            "release",
            grant_id,
            gate_id=release_gate,
            scope={"protected_ref": "main"},
        )
        self._observe(
            run_id,
            release_operation,
            "release",
            "succeeded",
            effect_id=f"release-{run_id}",
            result={"artifact_digest": "d" * 64},
        )
        release_result_gate, _ = self._gate(run_id, "RELEASE_RESULT_GATE")
        self._transition(
            run_id, "RELEASE_OBSERVED", gate_ids=(release_result_gate,)
        )
        self._transition(run_id, "PREPARE_DEPLOYMENT")
        deploy_gate, _ = self._gate(
            run_id, "DEPLOY_GATE", authorization_id=grant_id
        )
        self._transition(
            run_id,
            "START_DEPLOYMENT",
            payload={
                "deploy_required": True,
                "environment_id": "production",
                "environment_index": 0,
                "environment_key": "production",
            },
            gate_ids=(deploy_gate,),
            authorization_id=grant_id,
        )
        if action == "deploy":
            if not start_operation:
                return grant_id, deploy_gate, ""
            operation_id, _ = self._start_operation(
                run_id,
                action,
                kind,
                grant_id,
                gate_id=deploy_gate,
                scope=scope,
            )
            return grant_id, deploy_gate, operation_id

        deploy_operation, _ = self._start_operation(
            run_id,
            "deploy",
            "deploy",
            grant_id,
            gate_id=deploy_gate,
            scope={"environment_id": "production"},
        )
        self._observe(
            run_id,
            deploy_operation,
            "deploy",
            "succeeded",
            effect_id=f"deploy-{run_id}",
            result={"environment_id": "production"},
        )
        self._transition(
            run_id,
            "DEPLOYMENT_REQUIRES_ROLLBACK",
            payload={"external_operations_reconciled": True},
        )
        rollback_gate, _ = self._gate(
            run_id, "ROLLBACK_GATE", authorization_id=grant_id
        )
        self._transition(
            run_id,
            "START_ROLLBACK",
            payload={"environment_id": "production"},
            gate_ids=(rollback_gate,),
            authorization_id=grant_id,
        )
        if not start_operation:
            return grant_id, rollback_gate, ""
        operation_id, _ = self._start_operation(
            run_id,
            action,
            kind,
            grant_id,
            gate_id=rollback_gate,
            scope=scope,
        )
        return grant_id, rollback_gate, operation_id

    def _observe(
        self,
        run_id: str,
        operation_id: str,
        action: str,
        status: str,
        *,
        effect_id: str | None,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._run(run_id)
        return self.reducer.record_operation_observation(
            OperationObservation(
                operation_id=operation_id,
                action_id=action,
                status=status,
                effect_id=effect_id,
                result=dict(result or {}),
            ),
            run_id=run_id,
            expected_revision=int(run["revision"]),
            idempotency_key=(
                f"observe:{operation_id}:{status}:{effect_id or 'none'}:{self._next()}"
            ),
        )

    def test_ac002_amendment_invalidates_confirmation_evidence_and_authorization(
        self,
    ) -> None:
        for changed_field in ("spec", "config"):
            with self.subTest(changed_field=changed_field):
                run_id = f"run-ac002-{changed_field}"
                original_spec = canonical_spec_hash(
                    SPEC_TEMPLATE.format(body="Requirement: original behavior.")
                )
                amended_spec = canonical_spec_hash(
                    SPEC_TEMPLATE.format(body="Requirement: amended behavior.")
                )
                self.assertNotEqual(original_spec, amended_spec)
                original_config = sha256_bytes(b"config-v1")
                amended_config = sha256_bytes(b"config-v2")
                self._create_run(
                    run_id,
                    spec_hash=original_spec,
                    config_hash=original_config,
                )
                self._transition(
                    run_id, "DRAFT_SPEC", payload={"discovery_complete": True}
                )
                self._transition(run_id, "SUBMIT_SPEC_REVIEW")
                self._transition(run_id, "REQUEST_SPEC_CONFIRMATION")
                confirmation_id = self._confirmation(run_id)
                spec_gate, _ = self._gate(
                    run_id, "SPEC_GATE", authorization_id=confirmation_id
                )
                self._transition(
                    run_id,
                    "CONFIRM_SPEC",
                    gate_ids=(spec_gate,),
                    authorization_id=confirmation_id,
                )
                old_evidence_id, old_receipt = self._evidence(run_id, "AC-002")
                old_grant = self._grant(
                    run_id,
                    actions=("deploy",),
                    environments=("production",),
                )
                before = self._run(run_id)
                result = self.reducer.amend_run_inputs(
                    run_id=run_id,
                    expected_revision=int(before["revision"]),
                    spec_hash=(amended_spec if changed_field == "spec" else original_spec),
                    config_hash=(
                        amended_config if changed_field == "config" else original_config
                    ),
                    impact_analysis={
                        "reason": f"{changed_field} semantics changed",
                        "affected_subject_ids": ["AC-002"],
                    },
                    idempotency_key=f"amend:{run_id}",
                )
                self.assertEqual("SPEC_DRAFT", result["state"])
                self.assertIn(old_evidence_id, result["invalidated_evidence_ids"])
                self.assertIn(spec_gate, result["invalidated_gate_ids"])
                self.assertIn(confirmation_id, result["invalidated_authorization_ids"])
                self.assertIn(old_grant, result["invalidated_authorization_ids"])

                current = self._run(run_id)
                with self.assertRaisesRegex(
                    TransitionError, "evidence Spec/config binding is stale"
                ):
                    self.reducer.record_evidence(
                        run_id=run_id,
                        expected_revision=int(current["revision"]),
                        receipt=old_receipt,
                        idempotency_key=f"reuse-old-evidence:{run_id}",
                    )
                with self.assertRaisesRegex(TransitionError, "requires run state"):
                    self.reducer.start_operation(
                        run_id=run_id,
                        expected_revision=int(current["revision"]),
                        operation_id=f"OP-{run_id}-999",
                        action_id="deploy",
                        operation_kind="deploy",
                        idempotency_key=f"stale-operation:{run_id}",
                        authorization_id=old_grant,
                        scope={"environment_id": "production"},
                    )

                self._transition(run_id, "SUBMIT_SPEC_REVIEW")
                self._transition(run_id, "REQUEST_SPEC_CONFIRMATION")
                current = self._run(run_id)
                with self.assertRaisesRegex(TransitionError, "gate binding is stale"):
                    self.reducer.transition(
                        TransitionProposal(
                            run_id=run_id,
                            expected_revision=int(current["revision"]),
                            event="CONFIRM_SPEC",
                            actor="lifecycle-e2e",
                            idempotency_key=f"stale-confirm:{run_id}",
                            gate_ids=(spec_gate,),
                            authorization_id=confirmation_id,
                        )
                    )
                snapshot = self._run(run_id)
                self.store.rebuild_materialized_views()
                self.assertEqual(snapshot, self._run(run_id))

    def _auto_to_deploying(
        self,
        run_id: str,
        *,
        inject_failed_gate: bool = False,
    ) -> tuple[str, dict[str, str], int]:
        self._advance_through_plan(run_id, mode="auto")
        grant_id = self._grant(
            run_id,
            actions=("integrate_dev", "release", "deploy", "rollback", "cancel"),
            environments=("production",),
            protected_refs=("dev", "main"),
        )
        prompt_count = 0
        targets = {"dev": "dev-before", "main": "main-before", "production": "v1"}

        self._transition(run_id, "START_IMPLEMENTATION")
        self._transition(run_id, "START_PHASE_VERIFICATION")
        phase_gate, _ = self._gate(run_id, "PHASE_GATE")
        if inject_failed_gate:
            failed_gate, decision = self._gate(
                run_id,
                "DEV_INTEGRATION_GATE",
                authorization_id=grant_id,
                fail_prerequisite="target_is_dev",
            )
            self.assertEqual("failed", decision["result"])
            before = dict(targets)
            with self.assertRaisesRegex(TransitionError, "gate did not pass"):
                self._transition(
                    run_id,
                    "START_DEV_INTEGRATION",
                    payload={"protected_ref": "dev"},
                    gate_ids=(phase_gate, failed_gate),
                    authorization_id=grant_id,
                )
            self.assertEqual(before, targets)
            current = self._run(run_id)
            with self.assertRaisesRegex(TransitionError, "requires run state"):
                self.reducer.start_operation(
                    run_id=run_id,
                    expected_revision=int(current["revision"]),
                    operation_id=f"OP-{run_id}-900",
                    action_id="integrate_dev",
                    operation_kind="protected_ref",
                    idempotency_key=f"operation:{run_id}:out-of-scope",
                    authorization_id=grant_id,
                    scope={"protected_ref": "rogue"},
                )
            self.assertEqual(before, targets)

        dev_gate, _ = self._gate(
            run_id, "DEV_INTEGRATION_GATE", authorization_id=grant_id
        )
        self._transition(
            run_id,
            "START_DEV_INTEGRATION",
            payload={"protected_ref": "dev"},
            gate_ids=(phase_gate, dev_gate),
            authorization_id=grant_id,
        )
        operation_id, _ = self._start_operation(
            run_id,
            "integrate_dev",
            "protected_ref",
            grant_id,
            gate_id=dev_gate,
            scope={"protected_ref": "dev"},
            suffix=101,
        )
        targets["dev"] = "dev-integrated"
        self._observe(
            run_id,
            operation_id,
            "integrate_dev",
            "succeeded",
            effect_id="dev-integrated",
            result={"protected_ref": "dev", "observed_sha": targets["dev"]},
        )
        self._transition(
            run_id,
            "DEV_INTEGRATION_APPLIED",
            payload={"protected_ref": "dev"},
            gate_ids=(dev_gate,),
            authorization_id=grant_id,
        )
        result_gate, _ = self._gate(run_id, "DEV_INTEGRATION_RESULT_GATE")
        self._transition(
            run_id,
            "ALL_PHASES_INTEGRATED",
            payload={"all_phases_done": True},
            gate_ids=(result_gate,),
        )

        release_gate, _ = self._gate(
            run_id, "RELEASE_GATE", authorization_id=grant_id
        )
        self._transition(
            run_id,
            "START_RELEASE",
            payload={"release_required": True, "protected_ref": "main"},
            gate_ids=(release_gate,),
            authorization_id=grant_id,
        )
        release_operation, _ = self._start_operation(
            run_id,
            "release",
            "release",
            grant_id,
            gate_id=release_gate,
            scope={"protected_ref": "main"},
            suffix=102,
        )
        targets["main"] = targets["dev"]
        self._observe(
            run_id,
            release_operation,
            "release",
            "succeeded",
            effect_id="release-v2",
            result={"stable": targets["main"], "artifact_digest": "d" * 64},
        )
        release_result_gate, _ = self._gate(run_id, "RELEASE_RESULT_GATE")
        self._transition(
            run_id, "RELEASE_OBSERVED", gate_ids=(release_result_gate,)
        )
        self._transition(run_id, "PREPARE_DEPLOYMENT")

        deploy_gate, _ = self._gate(
            run_id, "DEPLOY_GATE", authorization_id=grant_id
        )
        self._transition(
            run_id,
            "START_DEPLOYMENT",
            payload={
                "deploy_required": True,
                "environment_id": "production",
                "environment_index": 0,
                "environment_key": "production",
            },
            gate_ids=(deploy_gate,),
            authorization_id=grant_id,
        )
        deploy_operation, _ = self._start_operation(
            run_id,
            "deploy",
            "deploy",
            grant_id,
            gate_id=deploy_gate,
            scope={"environment_id": "production"},
            suffix=103,
        )
        return grant_id, {**targets, "deploy_operation": deploy_operation}, prompt_count

    def _finish_auto_delivery(
        self,
        run_id: str,
        grant_id: str,
        targets: dict[str, str],
        *,
        partial_then_rollback: bool,
    ) -> str:
        deploy_operation = targets["deploy_operation"]
        targets["production"] = "v2-partial" if partial_then_rollback else "v2"
        if partial_then_rollback:
            self._observe(
                run_id,
                deploy_operation,
                "deploy",
                "partial",
                effect_id="deployment-v2",
                result={"environment_id": "production", "classification": "partial"},
            )
            self._observe(
                run_id,
                deploy_operation,
                "deploy",
                "succeeded",
                effect_id="deployment-v2",
                result={
                    "environment_id": "production",
                    "classification": "completed_after_reconcile",
                },
            )
            self._transition(
                run_id,
                "DEPLOYMENT_REQUIRES_ROLLBACK",
                payload={"external_operations_reconciled": True},
            )
            rollback_gate, _ = self._gate(
                run_id, "ROLLBACK_GATE", authorization_id=grant_id
            )
            self._transition(
                run_id,
                "START_ROLLBACK",
                payload={"environment_id": "production"},
                gate_ids=(rollback_gate,),
                authorization_id=grant_id,
            )
            rollback_operation, _ = self._start_operation(
                run_id,
                "rollback",
                "rollback",
                grant_id,
                gate_id=rollback_gate,
                scope={"environment_id": "production"},
                suffix=104,
            )
            targets["production"] = "v1"
            self._observe(
                run_id,
                rollback_operation,
                "rollback",
                "succeeded",
                effect_id="rollback-v1",
                result={"environment_id": "production", "deployed_version": "v1"},
            )
            self._transition(run_id, "ROLLBACK_OBSERVED")
            post_rollback_gate, _ = self._gate(run_id, "POST_ROLLBACK_GATE")
            self._transition(
                run_id, "ROLLBACK_VERIFIED", gate_ids=(post_rollback_gate,)
            )
            return str(self._run(run_id)["state"])

        self._observe(
            run_id,
            deploy_operation,
            "deploy",
            "succeeded",
            effect_id="deployment-v2",
            result={"environment_id": "production", "deployed_version": "v2"},
        )
        self._transition(run_id, "DEPLOYMENT_OBSERVED")
        post_deploy_gate, _ = self._gate(run_id, "POST_DEPLOY_GATE")
        completion_gate, _ = self._gate(run_id, "COMPLETION_GATE")
        self._transition(
            run_id,
            "COMPLETE_RUN",
            payload={
                "state_patch": {
                    "runtime_delivery_completed": [
                        {"logical_key": "production", "environment_index": 0}
                    ]
                }
            },
            gate_ids=(post_deploy_gate, completion_gate),
        )
        return str(self._run(run_id)["state"])

    def test_ac010_auto_delivery_continues_without_prompt_and_fails_closed(
        self,
    ) -> None:
        run_id = "run-ac010"
        grant_id, targets, prompt_count = self._auto_to_deploying(
            run_id, inject_failed_gate=True
        )
        state = self._finish_auto_delivery(
            run_id, grant_id, targets, partial_then_rollback=False
        )
        self.assertEqual("COMPLETED", state)
        self.assertEqual(0, prompt_count)
        self.assertEqual("dev-integrated", targets["dev"])
        self.assertEqual(targets["dev"], targets["main"])
        self.assertEqual("v2", targets["production"])
        event_types = [
            event["event_type"] for event in self.store.list_events(run_id=run_id)
        ]
        self.assertEqual(3, event_types.count("EXTERNAL_OPERATION_STARTED"))

    @staticmethod
    def _logical_task_run(max_workers: int) -> dict[str, Any]:
        tasks = (
            TaskDefinition("TASK-001", write_set=("src/a.txt",)),
            TaskDefinition("TASK-002", write_set=("src/b.txt",)),
            TaskDefinition(
                "TASK-003",
                dependencies=("TASK-001", "TASK-002"),
                write_set=("dist/result.json",),
            ),
        )
        authority = FixtureLeaseAuthority()
        scheduler = Scheduler(
            TaskGraph(tasks), authority, max_workers=max_workers, lease_seconds=60
        )
        completed: set[str] = set()
        logical_tree: dict[str, str] = {}
        acceptance: set[str] = set()
        max_batch = 0
        revision = 0
        while len(completed) < len(tasks):
            selected = scheduler.select(completed=completed, active={})
            if not selected:
                raise AssertionError("logical task fixture deadlocked")
            max_batch = max(max_batch, len(selected))
            leases: list[Lease] = []
            for index, task in enumerate(selected):
                lease = scheduler.acquire(
                    task.task_id,
                    owner=f"worker-{index + 1}",
                    attempt_id=f"ATTEMPT-fixture-{revision + index + 1:03d}",
                    expected_revision=revision,
                )
                leases.append(lease)
            for task, lease in zip(selected, leases, strict=True):
                if task.task_id == "TASK-001":
                    logical_tree["src/a.txt"] = "A\n"
                    acceptance.add("AC-A")
                elif task.task_id == "TASK-002":
                    logical_tree["src/b.txt"] = "B\n"
                    acceptance.add("AC-B")
                else:
                    logical_tree["dist/result.json"] = json.dumps(
                        {"inputs": sorted(logical_tree)}, sort_keys=True
                    )
                    acceptance.add("AC-C")
                completed.add(task.task_id)
                scheduler.release(lease, expected_revision=revision)
                revision += 1
        return {
            "tree_digest": sha256_bytes(canonical_json(logical_tree)),
            "acceptance": tuple(sorted(acceptance)),
            "completed": tuple(sorted(completed)),
            "max_batch": max_batch,
        }

    def test_ac014_single_and_multi_worker_have_equivalent_logical_results(
        self,
    ) -> None:
        single = self._logical_task_run(1)
        multiple = self._logical_task_run(3)
        self.assertEqual(single["tree_digest"], multiple["tree_digest"])
        self.assertEqual(single["acceptance"], multiple["acceptance"])
        self.assertEqual(("AC-A", "AC-B", "AC-C"), single["acceptance"])
        self.assertEqual(1, single["max_batch"])
        self.assertGreaterEqual(multiple["max_batch"], 2)

    def test_ac018_detached_restart_and_persistent_pause_resume(self) -> None:
        detached_run = "run-ac018-detached"
        self._create_run(detached_run)
        controller = WorkflowController(self.reducer, run_id=detached_run)
        launcher = DetachedFailureLauncher(self.database, self.root)
        receipt = controller.run_detached(detached_run, launcher)
        self.assertTrue(Path(str(receipt["receipt"])).is_file())

        self.store.close()
        terminal: dict[str, Any] | None = None
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            probe = Store(self.database)
            try:
                candidate = probe.get_run(detached_run)
                if candidate and candidate["state"] == "FAILED":
                    terminal = candidate
                    break
            finally:
                probe.close()
            time.sleep(0.05)
        self.assertIsNotNone(terminal, "detached controller did not reach terminal state")
        self.assertEqual("FAILED", terminal["state"] if terminal else None)
        for process in launcher.processes:
            process.wait(timeout=5)

        self.store = Store(self.database)
        self.reducer = Reducer(self.store, evidence_store=self.evidence_store)
        paused_run = "run-ac018-paused"
        self._create_run(paused_run)
        self._transition(
            paused_run, "DRAFT_SPEC", payload={"discovery_complete": True}
        )
        scheduler = Scheduler(
            TaskGraph((TaskDefinition("TASK-PAUSE", write_set=("src/**",)),)),
            FixtureLeaseAuthority(),
            max_workers=1,
        )
        first = WorkflowController(
            self.reducer, run_id=paused_run, scheduler=scheduler
        )
        first.handle_cli(
            "pause", {"run_id": paused_run, "reason": "restart fixture"}
        )
        paused = self._run(paused_run)
        self.assertEqual("PAUSED", paused["state"])
        self.assertEqual("SPEC_DRAFT", paused["resume_state"])

        self.store.close()
        self.store = Store(self.database)
        self.reducer = Reducer(self.store, evidence_store=self.evidence_store)
        restarted = WorkflowController(
            self.reducer, run_id=paused_run, scheduler=scheduler
        )
        self.assertEqual(
            (), restarted.select_tasks(completed=(), active={}, run_id=paused_run)
        )
        restarted.handle_cli("resume", {"run_id": paused_run})
        resumed = self._run(paused_run)
        self.assertEqual("SPEC_DRAFT", resumed["state"])
        self.assertIsNone(resumed["resume_state"])
        ready = restarted.select_tasks(completed=(), active={}, run_id=paused_run)
        self.assertEqual(("TASK-PAUSE",), tuple(task.task_id for task in ready))

    def test_ac040_representative_end_to_end_scenario_matrix(self) -> None:
        scenario_results: dict[str, Any] = {}

        staged_run = "run-ac040-staged"
        self._advance_through_plan(staged_run, mode="staged")
        self._transition(staged_run, "START_IMPLEMENTATION")
        self._transition(staged_run, "START_PHASE_VERIFICATION")
        phase_gate, _ = self._gate(staged_run, "PHASE_GATE")
        self._transition(
            staged_run, "AWAIT_PHASE_ACCEPTANCE", gate_ids=(phase_gate,)
        )
        foreground = WorkflowController(self.reducer, run_id=staged_run)
        steps = foreground.run_foreground(
            staged_run, lambda run: run["state"] != "PHASE_AWAITING_ACCEPTANCE"
        )
        self.assertEqual(0, steps)
        self.assertEqual("PHASE_AWAITING_ACCEPTANCE", self._run(staged_run)["state"])
        self.assertFalse(
            any(
                event["event_type"] == "EXTERNAL_OPERATION_STARTED"
                for event in self.store.list_events(run_id=staged_run)
            )
        )
        scenario_results["staged_single_foreground"] = "awaiting_approval"

        background_result = self.root / "auto-background-result.json"
        background_code = """
import json,sys
sys.path.insert(0, sys.argv[1])
from test_lifecycle_e2e_acceptance import LifecycleE2EAcceptanceTests
result = LifecycleE2EAcceptanceTests._logical_task_run(3)
result['mode'] = 'auto'
result['controller'] = 'background'
open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(result, sort_keys=True))
"""
        background_process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                background_code,
                str(Path(__file__).resolve().parent),
                str(background_result),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not background_result.is_file():
            time.sleep(0.05)
        self.assertTrue(background_result.is_file())
        background_process.wait(timeout=5)
        background = json.loads(background_result.read_text(encoding="utf-8"))
        self.assertEqual("auto", background["mode"])
        self.assertEqual("background", background["controller"])
        self.assertGreaterEqual(background["max_batch"], 2)
        self.assertEqual(["AC-A", "AC-B", "AC-C"], background["acceptance"])
        scenario_results["auto_multi_agent_background"] = background["tree_digest"]

        crash_run = "run-ac040-crash"
        crash_grant, crash_gate, operation_id = self._prepare_mutation_operation(
            crash_run,
            "deploy",
            "deploy",
            {"environment_id": "production"},
        )
        start_event = next(
            event
            for event in self.store.list_events(run_id=crash_run)
            if event["event_type"] == "EXTERNAL_OPERATION_STARTED"
            and event["payload"]["request"]["operation_id"] == operation_id
        )
        start_request = start_event["payload"]["request"]
        self.store.close()
        self.store = Store(self.database)
        self.reducer = Reducer(self.store, evidence_store=self.evidence_store)
        replayed = self.reducer.start_operation(
            run_id=crash_run,
            expected_revision=int(start_request["expected_revision"]),
            operation_id=operation_id,
            action_id="deploy",
            operation_kind="deploy",
            idempotency_key=f"operation:{operation_id}",
            authorization_id=crash_grant,
            gate_id=crash_gate,
            scope=start_request["scope"],
        )
        self.assertEqual(start_event["event_id"], replayed["event_id"])
        self._observe(
            crash_run,
            operation_id,
            "deploy",
            "succeeded",
            effect_id="crash-resumed-effect",
        )
        self.assertEqual(
            1,
            sum(
                event["event_type"] == "EXTERNAL_OPERATION_STARTED"
                and event["payload"]["request"]["operation_id"] == operation_id
                for event in self.store.list_events(run_id=crash_run)
            ),
        )
        scenario_results["crash_resume"] = "one_effect"

        false_success_run = "run-ac040-false-success"
        self._create_run(false_success_run)
        revision_before = int(self._run(false_success_run)["revision"])
        false_success = ActionDefinition.from_mapping(
            {
                "schema_version": "nm-v6/action-v1",
                "action_id": "false_success",
                "kind": "pure",
                "argv": [sys.executable, "-c", "pass"],
                "cwd": ".",
                "timeout_seconds": 10,
                "accepted_exit_codes": [0],
                "env_allowlist": [],
                "core_injected_env": [],
                "secret_refs": [],
                "result_schema": ACTION_RESULT_SCHEMA,
                "idempotency": "not_applicable",
                "observe_action_id": None,
                "reconcile_action_id": None,
            }
        )
        with self.assertRaises(ActionError):
            ActionExecutor(isolation_backend=TestIsolationBackend()).execute(
                false_success,
                workspace=self.root,
                operation_id=None,
            )
        self.assertEqual(
            revision_before, int(self._run(false_success_run)["revision"])
        )
        scenario_results["false_worker_success"] = "no_progress"

        repository = self.root / "conflict-repository"
        repository.mkdir()
        _git(repository, "init", "-b", "main")
        _git(repository, "config", "user.name", "Lifecycle Test")
        _git(repository, "config", "user.email", "lifecycle@example.invalid")
        (repository / "conflict.txt").write_text("base\n", encoding="utf-8")
        _git(repository, "add", "conflict.txt")
        _git(repository, "commit", "-m", "base")
        _git(repository, "branch", "dev")
        _git(repository, "switch", "dev")
        (repository / "conflict.txt").write_text("dev\n", encoding="utf-8")
        _git(repository, "commit", "-am", "dev change")
        dev_before = _git(repository, "rev-parse", "refs/heads/dev")
        _git(repository, "switch", "main")
        _git(repository, "switch", "-c", "feature/conflict")
        (repository / "conflict.txt").write_text("feature\n", encoding="utf-8")
        _git(repository, "commit", "-am", "feature change")
        _git(repository, "switch", "main")
        git_controller = GitController(repository)
        with self.assertRaisesRegex(GitPolicyError, "conflict"):
            git_controller.build_merge_proposal(
                source_ref="refs/heads/feature/conflict",
                target_branch="dev",
                strategy="merge_commit",
                purpose="conflict-fixture",
                sharing_status="local",
                rationale="exercise fail-closed conflict handling",
                rollback_ref="refs/nm-v6/rollback/dev-conflict",
                gate_ids=("GATE-conflict",),
                authorization_id="AUTH-conflict",
            )
        self.assertEqual(dev_before, _git(repository, "rev-parse", "refs/heads/dev"))
        scenario_results["merge_conflict"] = "target_unchanged"

        delivery_run = "run-ac040-partial-delivery"
        rollback_grant, targets, _ = self._auto_to_deploying(delivery_run)
        outcome = self._finish_auto_delivery(
            delivery_run,
            rollback_grant,
            targets,
            partial_then_rollback=True,
        )
        self.assertEqual("ROLLED_BACK", outcome)
        self.assertEqual("v1", targets["production"])
        self.assertNotEqual("COMPLETED", self._run(delivery_run)["state"])
        scenario_results["partial_deployment"] = "reconciled"
        scenario_results["rollback"] = outcome

        self.assertEqual(
            {
                "auto_multi_agent_background",
                "crash_resume",
                "false_worker_success",
                "merge_conflict",
                "partial_deployment",
                "rollback",
                "staged_single_foreground",
            },
            set(scenario_results),
        )

    def test_ac054_pause_cancel_and_revoke_fence_every_external_mutation(
        self,
    ) -> None:
        mutations = {
            "integrate_dev": ("protected_ref", {"protected_ref": "dev"}),
            "release": ("release", {"protected_ref": "main"}),
            "publish": ("publish", {"protected_ref": "main"}),
            "deploy": ("deploy", {"environment_id": "production"}),
            "rollback": ("rollback", {"environment_id": "production"}),
        }
        for action, (kind, scope) in mutations.items():
            for control in ("pause", "cancel", "revoke"):
                with self.subTest(action=action, control=control):
                    run_id = f"run-ac054-{action}-{control}"
                    grant_id, gate_id, operation_id = (
                        self._prepare_mutation_operation(
                            run_id, action, kind, scope
                        )
                    )
                    current = self._run(run_id)
                    premature_payload = {
                        "safe_pause_point": True,
                        "actors_fenced": True,
                        "external_operations_reconciled": True,
                    }
                    with self.assertRaisesRegex(
                        TransitionError, "requires reconciled external operations"
                    ):
                        self.reducer.transition(
                            TransitionProposal(
                                run_id=run_id,
                                expected_revision=int(current["revision"]),
                                event="REQUEST_PAUSE",
                                actor="malicious-controller",
                                idempotency_key=f"premature-pause:{run_id}",
                                payload=premature_payload,
                            )
                        )
                    with self.assertRaisesRegex(
                        TransitionError, "requires reconciled external operations"
                    ):
                        self.reducer.transition(
                            TransitionProposal(
                                run_id=run_id,
                                expected_revision=int(current["revision"]),
                                event="CANCEL",
                                actor="malicious-controller",
                                idempotency_key=f"premature-cancel:{run_id}",
                                payload=premature_payload,
                                authorization_id=grant_id,
                            )
                        )
                    self.assertNotIn(
                        self._run(run_id)["state"], {"PAUSED", "CANCELLED"}
                    )

                    if control == "revoke":
                        self._revoke(run_id, grant_id)
                        self.assertTrue(self.store.authorization_is_revoked(grant_id))
                        with self.assertRaisesRegex(AuthorizationError, "revoked"):
                            self.reducer.start_operation(
                                run_id=run_id,
                                expected_revision=int(self._run(run_id)["revision"]),
                                operation_id=f"OP-{run_id}-998",
                                action_id=action,
                                operation_kind=kind,
                                idempotency_key=f"operation:{run_id}:fenced",
                                authorization_id=grant_id,
                                gate_id=gate_id,
                                scope=self._complete_mutation_scope(
                                    action, gate_id, scope
                                ),
                            )
                        controller = WorkflowController(
                            self.reducer,
                            run_id=run_id,
                            operation_reconciler=lambda operation: {
                                "classification": "completed",
                                "effect_id": f"effect-{run_id}",
                                "result": {"reconciled": True},
                            },
                        )
                        reconciled = controller.handle_cli(
                            "reconcile", {"run_id": run_id}
                        )
                        self.assertEqual("reconciled", reconciled["result"])
                        controller.handle_cli("pause", {"run_id": run_id})
                        self.assertEqual("PAUSED", self._run(run_id)["state"])
                        continue

                    unknown_controller = WorkflowController(
                        self.reducer,
                        run_id=run_id,
                        operation_reconciler=lambda operation: {
                            "classification": "unknown",
                            "effect_id": f"effect-{run_id}",
                            "result": {"reconciled": False},
                        },
                    )
                    arguments: dict[str, Any] = {"run_id": run_id}
                    if control == "cancel":
                        arguments["grant_id"] = grant_id
                    unknown_controller.handle_cli(control, arguments)
                    self.assertEqual(
                        "ATTENTION_REQUIRED", self._run(run_id)["state"]
                    )
                    with self.assertRaisesRegex(TransitionError, "fenced"):
                        self.reducer.start_operation(
                            run_id=run_id,
                            expected_revision=int(self._run(run_id)["revision"]),
                            operation_id=f"OP-{run_id}-998",
                            action_id=action,
                            operation_kind=kind,
                            idempotency_key=f"operation:{run_id}:fenced",
                            authorization_id=grant_id,
                            gate_id=gate_id,
                            scope=self._complete_mutation_scope(
                                action, gate_id, scope
                            ),
                        )

                    completed_controller = WorkflowController(
                        self.reducer,
                        run_id=run_id,
                        operation_reconciler=lambda operation: {
                            "classification": "completed",
                            "effect_id": f"effect-{run_id}",
                            "result": {"reconciled": True},
                        },
                    )
                    reconciled = completed_controller.handle_cli(
                        "reconcile", {"run_id": run_id}
                    )
                    self.assertEqual("reconciled", reconciled["result"])
                    self.assertEqual(
                        "completed", self.store.get_operation(operation_id)["status"]
                    )
                    if control == "pause":
                        completed_controller.handle_cli("resume", {"run_id": run_id})
                        completed_controller.handle_cli("pause", {"run_id": run_id})
                        self.assertEqual("PAUSED", self._run(run_id)["state"])
                    else:
                        completed_controller.handle_cli(
                            "cancel", {"run_id": run_id, "grant_id": grant_id}
                        )
                        self.assertEqual("CANCELLED", self._run(run_id)["state"])

    def test_sensitive_operation_scope_requires_every_gate_and_auth_binding(
        self,
    ) -> None:
        mutations = {
            "integrate_dev": ("protected_ref", {"protected_ref": "dev"}),
            "release": ("release", {"protected_ref": "main"}),
            "publish": ("publish", {"protected_ref": "main"}),
            "deploy": ("deploy", {"environment_id": "production"}),
            "rollback": ("rollback", {"environment_id": "production"}),
        }
        for action, (kind, partial_scope) in mutations.items():
            with self.subTest(action=action):
                run_id = f"run-scope-{action}"
                grant_id, gate_id, _ = self._prepare_mutation_operation(
                    run_id,
                    action,
                    kind,
                    partial_scope,
                    start_operation=False,
                )
                complete_scope = self._complete_mutation_scope(
                    action, gate_id, partial_scope
                )
                for index, field in enumerate(
                    required_mutation_scope_fields(action), start=1
                ):
                    with self.subTest(action=action, missing=field):
                        incomplete = dict(complete_scope)
                        incomplete.pop(field)
                        run = self._run(run_id)
                        with self.assertRaisesRegex(
                            TransitionError,
                            rf"missing required fields:.*{field}",
                        ):
                            self.reducer.start_operation(
                                run_id=run_id,
                                expected_revision=int(run["revision"]),
                                operation_id=f"OP-{run_id}-{index:03d}",
                                action_id=action,
                                operation_kind=kind,
                                idempotency_key=(
                                    f"operation:{run_id}:missing:{field}"
                                ),
                                authorization_id=grant_id,
                                gate_id=gate_id,
                                scope=incomplete,
                            )
                operation_id, result = self._start_operation(
                    run_id,
                    action,
                    kind,
                    grant_id,
                    gate_id=gate_id,
                    scope=complete_scope,
                    suffix=999,
                )
                self.assertEqual("started", result["status"])
                persisted_scope = self.store.get_operation(operation_id)["scope"]
                self.assertEqual(gate_id, persisted_scope["gate_id"])
                for field, value in complete_scope.items():
                    self.assertEqual(value, persisted_scope[field])

    def test_sensitive_operation_revalidates_gate_evidence_blobs_before_start(
        self,
    ) -> None:
        mutations = {
            "integrate_dev": ("protected_ref", {"protected_ref": "dev"}),
            "release": ("release", {"protected_ref": "main"}),
            "deploy": ("deploy", {"environment_id": "production"}),
            "rollback": ("rollback", {"environment_id": "production"}),
        }
        for action, (kind, partial_scope) in mutations.items():
            for damage_index, damage in enumerate(("deleted", "corrupt"), start=1):
                with self.subTest(action=action, damage=damage):
                    run_id = f"run-gate-evidence-{action}-{damage}"
                    grant_id, gate_id, _ = self._prepare_mutation_operation(
                        run_id,
                        action,
                        kind,
                        partial_scope,
                        start_operation=False,
                    )
                    gate = self.store.get_gate(gate_id)
                    self.assertIsInstance(gate, Mapping)
                    evidence_id = str(gate["evidence_ids"][0])
                    receipt = self.store.get_evidence(evidence_id)
                    self.assertIsInstance(receipt, Mapping)
                    blob = self.evidence_store.blob_path(
                        str(receipt["stdout_digest"])
                    )
                    original = blob.read_bytes()
                    if damage == "deleted":
                        blob.unlink()
                    else:
                        blob.write_bytes(b"corrupt-gate-evidence")
                    before_run = self._run(run_id)
                    before_events = len(self.store.list_events(run_id=run_id))
                    operation_id = f"OP-{run_id}-{damage_index:03d}"
                    try:
                        with self.assertRaisesRegex(
                            TransitionError, "gate evidence is invalid"
                        ):
                            self.reducer.start_operation(
                                run_id=run_id,
                                expected_revision=int(before_run["revision"]),
                                operation_id=operation_id,
                                action_id=action,
                                operation_kind=kind,
                                idempotency_key=f"operation:{operation_id}",
                                authorization_id=grant_id,
                                gate_id=gate_id,
                                scope=self._complete_mutation_scope(
                                    action, gate_id, partial_scope
                                ),
                            )
                    finally:
                        blob.parent.mkdir(parents=True, exist_ok=True)
                        blob.write_bytes(original)
                    self.assertIsNone(self.store.get_operation(operation_id))
                    self.assertEqual(before_run, self._run(run_id))
                    self.assertEqual(
                        before_events, len(self.store.list_events(run_id=run_id))
                    )

    def test_sensitive_operation_restart_revalidates_gate_evidence_blob(
        self,
    ) -> None:
        run_id = "run-gate-evidence-deploy-restart"
        grant_id, gate_id, operation_id = self._prepare_mutation_operation(
            run_id,
            "deploy",
            "deploy",
            {"environment_id": "production"},
        )
        self._observe(
            run_id,
            operation_id,
            "deploy",
            "not_started",
            effect_id=None,
            result={"classification": "not_started"},
        )
        gate = self.store.get_gate(gate_id)
        self.assertIsInstance(gate, Mapping)
        receipt = self.store.get_evidence(str(gate["evidence_ids"][0]))
        self.assertIsInstance(receipt, Mapping)
        blob = self.evidence_store.blob_path(str(receipt["stdout_digest"]))
        original = blob.read_bytes()
        blob.write_bytes(b"corrupt-gate-evidence")
        authorization = self.store.get_authorization(grant_id)
        self.assertIsInstance(authorization, Mapping)
        before_run = self._run(run_id)
        before_events = len(self.store.list_events(run_id=run_id))
        try:
            with self.assertRaisesRegex(
                TransitionError, "gate evidence is invalid"
            ):
                self.reducer.restart_operation(
                    run_id=run_id,
                    expected_revision=int(before_run["revision"]),
                    operation_id=operation_id,
                    authorization_id=grant_id,
                    grant_revision=int(authorization["grant_revision"]),
                    idempotency_key=f"restart:{operation_id}",
                )
        finally:
            blob.write_bytes(original)
        self.assertEqual("not_started", self.store.get_operation(operation_id)["status"])
        self.assertEqual(before_run, self._run(run_id))
        self.assertEqual(before_events, len(self.store.list_events(run_id=run_id)))

    def test_generated_cli_uses_configured_dispatcher_and_durable_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            initialize_project(
                target,
                source_root=REPOSITORY,
                project_name="Runtime CLI Fixture",
                package_name="runtime-cli-fixture",
            )
            environment = {**os.environ, "NM_V6_PYTHON": sys.executable}
            entrypoint = target / "0d-scripts/nm-v6.py"

            def invoke(*arguments: str) -> tuple[subprocess.CompletedProcess[str], Any]:
                result = subprocess.run(
                    [
                        str(target / "0d-scripts/python311.sh"),
                        str(entrypoint),
                        *arguments,
                    ],
                    cwd=target,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                parsed = json.loads(result.stdout) if result.stdout.strip() else None
                return result, parsed

            planned, plan = invoke(
                "plan",
                "--target",
                str(target),
                "--run-id",
                "run-generated-runtime",
            )
            self.assertEqual(0, planned.returncode, msg=planned.stderr)
            self.assertEqual("SPEC_REVIEW", plan["state"])

            once, waiting = invoke(
                "run",
                "--target",
                str(target),
                "--run-id",
                "run-generated-runtime",
                "--once",
            )
            self.assertEqual(0, once.returncode, msg=once.stderr)
            self.assertEqual("waiting_for_input", waiting["result"])
            self.assertEqual(
                "trusted_spec_confirmation_request", waiting["waiting_for"]
            )
            self.assertNotIn("waiting_for_dispatcher", once.stdout)

            detached, launch = invoke(
                "run",
                "--target",
                str(target),
                "--run-id",
                "run-generated-runtime",
                "--detach",
            )
            self.assertEqual(0, detached.returncode, msg=detached.stderr)
            self.assertEqual("scheduled", launch["status"])
            self.assertNotIn("pid", launch)
            controller_id = launch["controller_id"]
            record_path = (
                target
                / ".nm/runtime/v6/controllers"
                / f"{controller_id}.json"
            )
            deadline = time.monotonic() + 10
            record: dict[str, Any] = {}
            while time.monotonic() < deadline:
                if record_path.is_file():
                    value = json.loads(record_path.read_text(encoding="utf-8"))
                    if value.get("status") == "waiting_for_input":
                        record = value
                        break
                time.sleep(0.05)
            self.assertEqual("waiting_for_input", record.get("status"))
            self.assertEqual("SPEC_REVIEW", record.get("state"))
            self.assertFalse(record.get("authoritative", True))
            self.assertEqual(
                "SQLite run/events", record.get("canonical_runtime_truth")
            )
            self.assertGreater(record.get("canonical_event_sequence", 0), 0)
            record_path.unlink()
            status, canonical = invoke(
                "status",
                "--target",
                str(target),
                "--run-id",
                "run-generated-runtime",
                "--json",
            )
            self.assertEqual(0, status.returncode, msg=status.stderr)
            self.assertEqual("SPEC_REVIEW", canonical["state"])
            record_path.write_text(
                json.dumps(
                    {
                        "controller_id": controller_id,
                        "run_id": "tampered",
                        "status": "running",
                        "authoritative": True,
                    }
                ),
                encoding="utf-8",
            )
            relaunched, second_launch = invoke(
                "run",
                "--target",
                str(target),
                "--run-id",
                "run-generated-runtime",
                "--detach",
            )
            self.assertEqual(0, relaunched.returncode, msg=relaunched.stderr)
            self.assertNotEqual(controller_id, second_launch["controller_id"])
            second_path = (
                target
                / ".nm/runtime/v6/controllers"
                / f"{second_launch['controller_id']}.json"
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if second_path.is_file():
                    second_record = json.loads(second_path.read_text(encoding="utf-8"))
                    if second_record.get("status") == "waiting_for_input":
                        break
                time.sleep(0.05)
            else:
                self.fail("relaunched durable child did not reach canonical wait state")

            generated_store = Store(target / ".nm/runtime/v6/state.sqlite3")
            try:
                generated_reducer = Reducer(generated_store)
                runtime = compose_runtime(
                    target,
                    generated_store,
                    generated_reducer,
                    "run-generated-runtime",
                )
                self.assertIsNotNone(runtime.controller.signature_verifier)
                self.assertEqual(
                    "waiting_for_input",
                    runtime.handle(
                        "run",
                        {
                            "run_id": "run-generated-runtime",
                            "once": True,
                            "detach": False,
                            "child": False,
                        },
                    )["result"],
                )
            finally:
                generated_store.close()
            project_path = target / "project.json"
            changed_project = json.loads(project_path.read_text(encoding="utf-8"))
            changed_project["scheduler"]["lease_seconds"] += 1
            project_path.write_text(
                json.dumps(changed_project, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            drifted, _ = invoke(
                "run",
                "--target",
                str(target),
                "--run-id",
                "run-generated-runtime",
                "--once",
            )
            self.assertNotEqual(0, drifted.returncode)
            self.assertIn("inputs changed", drifted.stderr)

    def test_generated_self_test_executes_actions_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            initialize_project(
                target,
                source_root=REPOSITORY,
                project_name="Runtime Self Test Fixture",
                package_name="runtime-self-test-fixture",
            )
            environment = {**os.environ, "NM_V6_PYTHON": sys.executable}
            command = [
                str(target / "0d-scripts/python311.sh"),
                str(target / "0d-scripts/nm-v6.py"),
                "self-test",
                "--target",
                str(target),
            ]
            result = subprocess.run(
                command,
                cwd=target,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=90,
            )
            self.assertEqual(0, result.returncode, msg=result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual("passed", report["result"])
            self.assertEqual("ROLLED_BACK", report["state"])
            self.assertEqual(2, report["scheduler"]["selected_parallel"])
            self.assertTrue(report["git"]["stable_equals_dev"])
            self.assertEqual(
                {"release": True, "publish": True, "deploy": True},
                report["partial_unknown_reconciliation"],
            )
            self.assertTrue(report["rollback"]["verified"])
            self.assertEqual(
                {"completed"}, set(report["persisted_operations"].values())
            )
            project = json.loads((target / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(project["action_definitions"]), set(report["actions_executed"])
            )

            fake_action = target / "0d-scripts/fake-action.py"
            fake_action.rename(target / "0d-scripts/fake-action.py.unavailable")
            _git(target, "add", "-A")
            _git(target, "commit", "-m", "test: make fake actions unavailable")
            failed = subprocess.run(
                command,
                cwd=target,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=90,
            )
            self.assertNotEqual(0, failed.returncode)
            self.assertIn("ERROR:", failed.stderr)


if __name__ == "__main__":
    unittest.main()
