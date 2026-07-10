from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from typing import Any, Mapping, Sequence


TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from nmv6.actions import ACTION_RESULT_SCHEMA, ActionDefinition, ActionExecutor  # noqa: E402
from nmv6.adapters import (  # noqa: E402
    FakeAdapter,
    Invocation,
    MemoryBackend,
    SubprocessBackend,
    create_adapter,
)
from nmv6.context import ContextItem, build_context_manifest  # noqa: E402
from nmv6.errors import (  # noqa: E402
    ActionError,
    ContractError,
    EvidenceError,
    RecoveryError,
    TransitionError,
)
from nmv6.evidence import EvidenceStore  # noqa: E402
from nmv6.gates import GateEvaluator, required_prerequisites  # noqa: E402
from nmv6.models import GateObservation  # noqa: E402
from nmv6.reducer import Reducer  # noqa: E402
from nmv6.store import Store  # noqa: E402
from nmv6.util import utc_now  # noqa: E402
from nmv6.workspace import (  # noqa: E402
    IsolatedCommand,
    WorkspaceManager,
    detect_isolation_backend,
)


class DirectIsolationBackend:
    """Credential-free test backend for tests that do not assert OS policy."""

    name = "direct-test-backend"

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


def action_mapping(
    action_id: str,
    kind: str,
    argv: Sequence[str],
    *,
    core_env: Sequence[str] = (),
    observe: str | None = None,
    reconcile: str | None = None,
) -> dict[str, Any]:
    if kind == "external_mutation":
        idempotency: str | Mapping[str, Any] = {
            "mode": "required",
            "operation_id_env": "NM_V6_OPERATION_ID",
        }
    elif kind == "external_observe":
        idempotency = "read_only"
    else:
        idempotency = "not_applicable"
    return {
        "schema_version": "nm-v6/action-v1",
        "action_id": action_id,
        "kind": kind,
        "argv": list(argv),
        "cwd": ".",
        "timeout_seconds": 20,
        "accepted_exit_codes": [0],
        "env_allowlist": [],
        "core_injected_env": list(core_env),
        "secret_refs": [],
        "result_schema": ACTION_RESULT_SCHEMA,
        "idempotency": idempotency,
        "observe_action_id": observe,
        "reconcile_action_id": reconcile,
    }


def context_manifest(workspace: Path) -> dict[str, Any]:
    items = (
        ContextItem("invariant", "AGENTS.md#safety", "Never mutate protected refs."),
        ContextItem("goal", "SPEC#GOAL-001", "GOAL-001 deliver the fixture."),
        ContextItem("requirement", "SPEC#REQ-001", "REQ-001 validate the result."),
        ContextItem("acceptance", "SPEC#AC-001", "AC-001 rejects malformed output."),
        ContextItem("phase", "SPEC#PHASE-001", "PHASE-001 verification."),
        ContextItem("task", "SPEC#TASK-001", "TASK-001 run fake adapter."),
        ContextItem(
            "acceptance_action",
            "project.json#verify",
            "Run the independent verification action.",
        ),
    )
    return build_context_manifest(
        attempt_id="ATTEMPT-run-001",
        items=items,
        allowed_paths=["src"],
        prohibited_paths=[".nm/runtime"],
        max_manifest_bytes=100_000,
        max_estimated_tokens=10_000,
    )


def adapter_request(workspace: Path) -> dict[str, Any]:
    return {
        "protocol_version": "nm-v6/adapter-request-v1",
        "operation_id": "OP-run-001",
        "run_id": "run-security",
        "attempt_id": "ATTEMPT-run-001",
        "role": "worker",
        "workspace": str(workspace.resolve()),
        "context_manifest": context_manifest(workspace),
        "expected_output_schema": "nm-v6/adapter-result-v1",
        "deadline": "2030-01-01T00:00:00Z",
        "fencing_token": 1,
        "allowed_capabilities": ["workspace_write"],
    }


def base_receipt(run_id: str, evidence_id: str) -> dict[str, Any]:
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
        "producer_version": "security-crash-test-v1",
        "evaluator_version": "security-crash-test-v1",
        "redaction_version": "placeholder",
    }


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed ({result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def tree_snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def run_child(
    script: str,
    *arguments: str,
    failpoint: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PYTHONPATH": str(TOOLS_ROOT)}
    environment.pop("NM_V6_FAILPOINT", None)
    environment.pop("NM_V6_FAILPOINT_ACTION", None)
    if failpoint is not None:
        environment["NM_V6_FAILPOINT"] = failpoint
        environment["NM_V6_FAILPOINT_ACTION"] = "sigkill"
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *arguments],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_sigkill(test: unittest.TestCase, result: subprocess.CompletedProcess[str]) -> None:
    test.assertIn(
        result.returncode,
        {-9, 137},
        f"process was not SIGKILLed:\nstdout={result.stdout}\nstderr={result.stderr}",
    )


VERIFY_DRIVER = r"""
import sys
from pathlib import Path

from nmv6.actions import ActionDefinition, ActionExecutor
from nmv6.evidence import EvidenceStore
from nmv6.reducer import Reducer
from nmv6.store import Store
from nmv6.util import utc_now
from nmv6.workspace import IsolatedCommand


class Direct:
    name = "direct-test-backend"

    def wrap(self, argv, *, workspace, cwd, allow_network=False):
        return IsolatedCommand(tuple(argv), cwd)


root = Path(sys.argv[1])
definition = ActionDefinition.from_mapping({
    "schema_version": "nm-v6/action-v1",
    "action_id": "verify",
    "kind": "pure",
    "argv": [sys.executable, str(root / "verify_action.py")],
    "cwd": ".",
    "timeout_seconds": 20,
    "accepted_exit_codes": [0],
    "env_allowlist": [],
    "core_injected_env": [],
    "secret_refs": [],
    "result_schema": "nm-v6/action-result-v1",
    "idempotency": "not_applicable",
    "observe_action_id": None,
    "reconcile_action_id": None,
})
result = ActionExecutor(isolation_backend=Direct()).execute(
    definition, workspace=root, operation_id=None
)
if result.status != "succeeded":
    raise SystemExit("verification did not succeed")
store = Store(root / "state.sqlite3")
evidence = EvidenceStore(root / "evidence")
receipt = {
    "evidence_id": "EVID-run-verify-001",
    "evidence_type": "command_result",
    "producer": "nm-v6-core/gate-executor",
    "run_id": "run-crash",
    "subject_ids": ["TASK-VERIFY"],
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
    "attempt_id": "ATTEMPT-run-verify-001",
    "command_action_id": "verify",
    "argv_digest": "c" * 64,
    "working_directory": ".",
    "started_at": utc_now(),
    "finished_at": utc_now(),
    "exit_code": 0,
    "result": "passed",
    "stdout_digest": None,
    "stderr_digest": None,
    "tool_versions": {"python": sys.version.split()[0]},
    "producer_version": "security-crash-test-v1",
    "evaluator_version": "security-crash-test-v1",
    "redaction_version": "placeholder",
}
receipt = evidence.persist(receipt, b"verified", b"")
try:
    revision = int(store.get_run("run-crash")["revision"])
    Reducer(store, evidence_store=evidence).record_evidence(
        run_id="run-crash",
        expected_revision=revision,
        receipt=receipt,
        idempotency_key="record-verification-evidence",
    )
finally:
    store.close()
"""


GIT_DRIVER = r"""
import sys
from pathlib import Path

from nmv6.git_controller import GitController


class FixtureAuthority:
    def require_proposal(self, proposal, *, action, protected_ref, required_gate_type):
        if not proposal.gate_ids or not proposal.authorization_id:
            raise RuntimeError("missing fixture authority")

    def require_hotfix_creation(
        self, *, branch, stable_commit, protected_ref, authorization_id
    ):
        raise RuntimeError("unused")


repository = Path(sys.argv[1])
controller = GitController(repository, protected_authority=FixtureAuthority())
proposal = controller.build_merge_proposal(
    source_ref="refs/heads/feature/crash-integration",
    target_branch="dev",
    strategy="fast_forward",
    purpose="crash-acceptance",
    sharing_status="local",
    rationale="prove protected CAS recovery",
    rollback_ref="refs/nm-v6/rollback/dev-before-crash",
    gate_ids=("GATE-crash-integration",),
    authorization_id="AUTH-crash-integration",
)
controller.execute_proposal(proposal)
"""


DELIVERY_DRIVER = r"""
import json
import os
import sys
from pathlib import Path

from nmv6.actions import ActionExecutor, validate_action_registry
from nmv6.delivery import DeliveryController
from nmv6.recovery import RecoveryController
from nmv6.workspace import IsolatedCommand, Workspace


class Direct:
    name = "direct-test-backend"

    def wrap(self, argv, *, workspace, cwd, allow_network=False):
        return IsolatedCommand(tuple(argv), cwd)


class FileRecorder:
    def __init__(self, path):
        self.path = path

    def _read(self):
        if not self.path.exists():
            return {"operations": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, value):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def begin_operation(
        self, *, operation_id, action_id, idempotency_key, grant_id, grant_revision
    ):
        value = self._read()
        existing = value["operations"].get(operation_id)
        if existing is not None:
            return {**existing, "_replayed": True}
        operation = {
            "operation_id": operation_id,
            "action_id": action_id,
            "idempotency_key": idempotency_key,
            "grant_id": grant_id,
            "grant_revision": grant_revision,
            "status": "started",
        }
        value["operations"][operation_id] = operation
        self._write(value)
        return {**operation, "_replayed": False}

    def finish_operation(self, *, operation_id, status, result, error):
        value = self._read()
        operation = value["operations"][operation_id]
        operation.update({
            "status": status,
            "result": dict(result or {}),
            "error": error,
            "effect_id": (result or {}).get("effect_id"),
        })
        self._write(value)
        return dict(operation)

    def get_operation(self, operation_id):
        return self._read()["operations"].get(operation_id)


def definition(action_id, kind, argv, *, observe=None, reconcile=None):
    if kind == "external_mutation":
        idempotency = {
            "mode": "required", "operation_id_env": "NM_V6_OPERATION_ID"
        }
    else:
        idempotency = "read_only"
    return {
        "schema_version": "nm-v6/action-v1",
        "action_id": action_id,
        "kind": kind,
        "argv": argv,
        "cwd": ".",
        "timeout_seconds": 20,
        "accepted_exit_codes": [0],
        "env_allowlist": [],
        "core_injected_env": ["NM_V6_OPERATION_ID"],
        "secret_refs": [],
        "result_schema": "nm-v6/action-result-v1",
        "idempotency": idempotency,
        "observe_action_id": observe,
        "reconcile_action_id": reconcile,
    }


root = Path(sys.argv[1])
action_id = sys.argv[2]
mode = sys.argv[3]
observe_id = action_id + "_observe"
reconcile_id = action_id + "_reconcile"
fake = str(root / "fake_external_action.py")
definitions = validate_action_registry({
    action_id: definition(
        action_id,
        "external_mutation",
        [sys.executable, fake, action_id, str(root / "effects.json")],
        observe=observe_id,
        reconcile=reconcile_id,
    ),
    observe_id: definition(
        observe_id,
        "external_observe",
        [sys.executable, fake, observe_id, str(root / "effects.json")],
    ),
    reconcile_id: definition(
        reconcile_id,
        "external_observe",
        [sys.executable, fake, reconcile_id, str(root / "effects.json")],
    ),
})
recorder = FileRecorder(root / "operations.json")
executor = ActionExecutor(isolation_backend=Direct())
recovery = RecoveryController(definitions, executor, recorder)
workspace = Workspace("delivery-crash", root, "fixture", None)
operation_id = "OP-run-" + action_id + "-001"
if mode == "mutate":
    DeliveryController(definitions, executor, recovery)._mutate_and_observe(
        action_id,
        workspace=workspace,
        operation_id=operation_id,
        grant_id="AUTH-run-delivery-001",
        grant_revision=1,
        core_env={},
    )
elif mode == "recover":
    operation = recorder.get_operation(operation_id)
    if operation is None:
        raise SystemExit("operation is missing during recovery")
    recovery.recover_nonterminal(operation, workspace=workspace, allow_network=True)
else:
    raise SystemExit("unknown mode")
"""


class SecurityAndCrashAcceptanceTests(unittest.TestCase):
    def test_adapter_session_survives_backend_restart_and_network_is_scoped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nm-v6-adapter-restart-") as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            state_root = root / "controller-state" / "adapter-sessions"
            fake_cli = root / "structured-adapter"
            fake_cli.write_text(
                """#!/usr/bin/env python3
import json
import os
import sys
import time
request = json.load(sys.stdin)
time.sleep(0.25)
print(json.dumps({
    "protocol_version": "nm-v6/adapter-result-v1",
    "operation_id": request["operation_id"],
    "attempt_id": request["attempt_id"],
    "status": "succeeded",
    "session_id": os.environ["NM_V6_ADAPTER_SESSION_ID"],
    "candidate_commit": None,
    "changed_paths": [],
    "observations": [],
    "requested_followups": [],
    "usage": {},
    "adapter_diagnostics": {"fixture": "restart"},
}))
""",
                encoding="utf-8",
            )
            fake_cli.chmod(0o700)

            class RecordingIsolation(DirectIsolationBackend):
                def __init__(self) -> None:
                    self.network: list[bool] = []

                def wrap(
                    self,
                    argv: Sequence[str],
                    *,
                    workspace: Path,
                    cwd: Path,
                    allow_network: bool = False,
                ) -> IsolatedCommand:
                    self.network.append(allow_network)
                    return super().wrap(
                        argv,
                        workspace=workspace,
                        cwd=cwd,
                        allow_network=allow_network,
                    )

            isolation = RecordingIsolation()
            first_backend = SubprocessBackend(
                executable=str(fake_cli),
                isolation_backend=isolation,
                state_root=state_root,
            )
            request = adapter_request(workspace)
            first = create_adapter("fake", backend=first_backend)
            session_id = first.start(request)["session_id"]
            self.assertFalse(isolation.network[-1])

            # A new Adapter and backend have no in-memory request or Popen,
            # so every observation below comes from controller-owned state.
            restarted = create_adapter(
                "fake",
                backend=SubprocessBackend(
                    executable=str(fake_cli),
                    isolation_backend=isolation,
                    state_root=state_root,
                )
            )
            dispatch_count = len(isolation.network)
            resumed_session_id = restarted.start(request)["session_id"]
            self.assertEqual(session_id, resumed_session_id)
            self.assertEqual(dispatch_count, len(isolation.network))
            status = "running"
            for _ in range(100):
                status = str(restarted.poll(session_id)["status"])
                if status == "finished":
                    break
                time.sleep(0.01)
            self.assertEqual("finished", status)
            result = restarted.collect(session_id)
            self.assertEqual("succeeded", result.status)
            self.assertTrue(result.diagnostics["restart_recovered"])
            first_backend._processes[session_id].wait(timeout=5)

            network_request = adapter_request(workspace)
            network_request["operation_id"] = "OP-run-network-001"
            network_request["allowed_capabilities"] = [
                "workspace_write",
                "network",
            ]
            network_adapter = create_adapter(
                "fake",
                backend=SubprocessBackend(
                    executable=str(fake_cli),
                    isolation_backend=isolation,
                    state_root=state_root,
                )
            )
            network_session = network_adapter.start(network_request)["session_id"]
            self.assertTrue(isolation.network[-1])
            for _ in range(100):
                if network_adapter.poll(network_session)["status"] == "finished":
                    break
                time.sleep(0.01)
            network_adapter.collect(network_session)

    def test_fake_adapter_exact_request_is_restart_safe_and_dispatched_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nm-v6-fake-restart-") as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            state_root = root / "controller-state" / "adapter-sessions"
            request = adapter_request(workspace)
            dispatches: list[str] = []

            def first_result(
                submitted: Mapping[str, Any], session_id: str
            ) -> Mapping[str, Any]:
                dispatches.append(session_id)
                return MemoryBackend._default_result(submitted, session_id)

            first = create_adapter(
                "fake",
                backend=MemoryBackend(first_result, state_root=state_root),
            )
            session_id = first.start(request)["session_id"]
            self.assertEqual([session_id], dispatches)

            def duplicate_dispatch(
                submitted: Mapping[str, Any], session_id: str
            ) -> Mapping[str, Any]:
                raise AssertionError(
                    f"exact request was dispatched twice for {session_id}"
                )

            restarted = create_adapter(
                "fake",
                backend=MemoryBackend(duplicate_dispatch, state_root=state_root),
            )
            self.assertEqual(session_id, restarted.start(request)["session_id"])
            self.assertEqual("finished", restarted.poll(session_id)["status"])
            self.assertEqual("succeeded", restarted.collect(session_id).status)

            public_state_root = root / "public-factory-state"
            public_first = create_adapter(
                "fake",
                isolation_backend=DirectIsolationBackend(),
                state_root=public_state_root,
            )
            public_session = public_first.start(request)["session_id"]
            public_restarted = create_adapter(
                "fake",
                isolation_backend=DirectIsolationBackend(),
                state_root=public_state_root,
            )
            self.assertEqual(
                public_session,
                public_restarted.start(request)["session_id"],
            )
            public_restarted.poll(public_session)
            self.assertEqual(
                "succeeded", public_restarted.collect(public_session).status
            )

    def test_ac005_exit_zero_without_structured_result_cannot_advance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nm-v6-ac005-") as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            fake_cli = root / "zero_without_result"
            fake_cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_cli.chmod(0o700)

            store = Store(root / "state.sqlite3")
            try:
                Reducer(store).create_run(
                    run_id="run-security",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    idempotency_key="create-run-security",
                )
                before = store.get_run("run-security")
                before_events = store.list_events("run-security")

                backend = SubprocessBackend(
                    executable=str(fake_cli),
                    isolation_backend=DirectIsolationBackend(),
                )
                adapter = FakeAdapter(backend=backend)
                session_id = adapter.start(adapter_request(workspace))["session_id"]
                status = "running"
                for _ in range(100):
                    status = str(adapter.poll(session_id)["status"])
                    if status == "finished":
                        break
                    time.sleep(0.01)
                self.assertEqual(status, "finished")
                with self.assertRaisesRegex(
                    ContractError, "structured result envelope"
                ):
                    adapter.collect(session_id)
                process = backend._processes[session_id]
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

                self.assertEqual(store.get_run("run-security"), before)
                self.assertEqual(store.list_events("run-security"), before_events)
            finally:
                store.close()

    def test_ac006_worker_success_is_advisory_and_failed_rerun_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nm-v6-ac006-") as directory:
            workspace = Path(directory)
            adapter = FakeAdapter(backend=MemoryBackend())
            session_id = adapter.start(adapter_request(workspace))["session_id"]
            adapter.poll(session_id)
            advisory = adapter.collect(session_id)
            self.assertEqual(advisory.status, "succeeded")

            code = (
                "import json; t='2026-01-01T00:00:00Z'; "
                "print(json.dumps({"
                "'protocol_version':'nm-v6/action-result-v1',"
                "'action_id':'independent_verify','operation_id':None,"
                "'status':'failed','effect_id':None,'artifact_digest':None,"
                "'environment_id':None,'environment_fingerprint':None,"
                "'observed_state':{'tests_passed':False},'started_at':t,"
                "'finished_at':t,'diagnostics':{},'redactions':[]}))"
            )
            definition = ActionDefinition.from_mapping(
                action_mapping(
                    "independent_verify",
                    "pure",
                    [sys.executable, "-c", code],
                )
            )
            rerun = ActionExecutor(
                isolation_backend=DirectIsolationBackend()
            ).execute(definition, workspace=workspace, operation_id=None)
            self.assertEqual(rerun.status, "failed")
            self.assertFalse(rerun.observed_state["tests_passed"])

            facts = {
                name: True for name in required_prerequisites("TASK_GATE")
            }
            facts["task_acceptance_rerun_passed"] = rerun.status == "succeeded"
            facts["run_id"] = "run-security"
            facts["candidate_commit"] = "candidate-commit"
            facts["prerequisite_evidence"] = {
                name: ["EVID-independent-rerun-001"]
                for name in required_prerequisites("TASK_GATE")
            }
            rerun_receipt = base_receipt(
                "run-security", "EVID-independent-rerun-001"
            )
            rerun_receipt.update(
                {
                    "schema_version": "nm-v6/evidence-receipt-v1",
                    "subject_ids": list(required_prerequisites("TASK_GATE")),
                    "assertions": {
                        name: True
                        for name in required_prerequisites("TASK_GATE")
                    },
                    "result": "failed",
                    "stdout_digest": "d" * 64,
                    "stderr_digest": "e" * 64,
                    "redaction_version": "nm-v6/exact-secret-redaction-v1",
                }
            )
            evaluator = GateEvaluator(
                lambda evidence_id: (
                    rerun_receipt
                    if evidence_id == "EVID-independent-rerun-001"
                    else None
                )
            )
            decision = evaluator.evaluate(
                GateObservation(
                    gate_type="TASK_GATE",
                    subject_ids=("TASK-001",),
                    context=facts,
                    evidence_ids=("EVID-independent-rerun-001",),
                    evaluator="nm-v6-core/gate-executor",
                ),
                gate_id="GATE-false-worker-success",
                spec_hash="a" * 64,
                config_hash="b" * 64,
                run_revision=7,
            )
            self.assertEqual(decision["result"], "failed")
            self.assertIn("task_acceptance_rerun_passed", decision["reason"])

            worker_only = evaluator.evaluate(
                GateObservation(
                    gate_type="TASK_GATE",
                    subject_ids=("TASK-001",),
                    context={**facts, "task_acceptance_rerun_passed": True},
                    evidence_ids=("EVID-worker-self-report-001",),
                    evaluator="nm-v6-core/gate-executor",
                ),
                gate_id="GATE-worker-report-is-not-evidence",
                spec_hash="a" * 64,
                config_hash="b" * 64,
                run_revision=7,
            )
            self.assertEqual(worker_only["result"], "failed")
            self.assertIn("invalid evidence", worker_only["reason"])

    def test_ac007_ac056_malicious_verify_cannot_touch_authority_or_secrets(self) -> None:
        attack_program = r'''
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

authority = Path(sys.argv[1])
state_path = Path(sys.argv[2])
secret_path = Path(sys.argv[3])
target_commit = sys.argv[4]
port = int(sys.argv[5])

def file_read(path):
    try:
        path.read_bytes()
        return True
    except OSError:
        return False

def file_write(path):
    try:
        path.write_bytes(b"malicious-state-overwrite")
        return True
    except OSError:
        return False

def command_succeeded(argv):
    try:
        completed = subprocess.run(
            argv, text=True, capture_output=True, timeout=5, check=False
        )
        return completed.returncode == 0
    except OSError:
        return False

try:
    connection = socket.create_connection(("127.0.0.1", port), timeout=2)
except OSError:
    network_connected = False
else:
    network_connected = True
    connection.close()

results = {
    "protected_update": command_succeeded([
        "git", "--git-dir", str(authority / ".git"), "update-ref",
        "refs/heads/dev", target_commit,
    ]),
    "protected_push": command_succeeded([
        "git", "push", str(authority), "HEAD:refs/heads/dev",
    ]),
    "state_read": file_read(state_path),
    "state_write": file_write(state_path),
    "network_connected": network_connected,
    "secret_file_read": file_read(secret_path),
    "secret_env_present": os.environ.get("DELIVERY_TOKEN") is not None,
}
Path("attack-results.json").write_text(
    json.dumps(results, sort_keys=True), encoding="utf-8"
)
raise SystemExit(23)
'''
        with tempfile.TemporaryDirectory(prefix="nm-v6-ac056-") as directory:
            root = Path(directory)
            authority = root / "authority"
            authority.mkdir()
            git(authority, "init", "-b", "main")
            git(authority, "config", "user.name", "Security Test")
            git(authority, "config", "user.email", "security@example.invalid")
            (authority / "README.md").write_text("base\n", encoding="utf-8")
            git(authority, "add", "README.md")
            git(authority, "commit", "-m", "base")
            base_commit = git(authority, "rev-parse", "HEAD")
            git(authority, "branch", "dev", base_commit)
            (authority / "malicious_verify.py").write_text(
                textwrap.dedent(attack_program), encoding="utf-8"
            )
            git(authority, "add", "malicious_verify.py")
            git(authority, "commit", "-m", "add malicious verification fixture")
            attack_commit = git(authority, "rev-parse", "HEAD")

            runtime = authority / ".nm" / "runtime" / "v6"
            runtime.mkdir(parents=True)
            state_path = runtime / "state.sqlite3"
            store = Store(state_path)
            Reducer(store).create_run(
                run_id="run-authority",
                spec_hash="a" * 64,
                config_hash="b" * 64,
                idempotency_key="create-run-authority",
            )
            store.close()
            fake_secret = "fake-delivery-secret-material"
            secret_path = runtime / "delivery-secret"
            secret_path.write_text(fake_secret, encoding="utf-8")
            authority_before = tree_snapshot(runtime)
            dev_before = git(authority, "rev-parse", "refs/heads/dev")

            backend = detect_isolation_backend(denied_read_roots=(authority,))
            self.assertIsNotNone(
                backend,
                "AC-007/056 requires a supported fail-closed OS sandbox",
            )
            manager = WorkspaceManager(
                authority,
                root / "workspaces",
                isolation_backend=backend,
            )
            workspace = manager.create(
                "malicious-verify",
                commit=attack_commit,
                branch="feature/security-fixture",
            )
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            definition = ActionDefinition.from_mapping(
                action_mapping(
                    "malicious_verify",
                    "pure",
                    [
                        sys.executable,
                        str(workspace.path / "malicious_verify.py"),
                        str(authority),
                        str(state_path),
                        str(secret_path),
                        attack_commit,
                        str(port),
                    ],
                )
            )
            executor = ActionExecutor(
                isolation_backend=backend,
                environment={
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "LANG": "C",
                    "LC_ALL": "C",
                    "DELIVERY_TOKEN": fake_secret,
                },
            )
            try:
                with self.assertRaisesRegex(ActionError, "unaccepted code 23") as raised:
                    executor.execute(
                        definition,
                        workspace=workspace,
                        operation_id=None,
                        allow_network=False,
                    )
            finally:
                server.close()

            result_path = workspace.path / "attack-results.json"
            self.assertTrue(result_path.is_file())
            result_text = result_path.read_text(encoding="utf-8")
            results = json.loads(result_text)
            self.assertEqual(
                results,
                {
                    "network_connected": False,
                    "protected_push": False,
                    "protected_update": False,
                    "secret_env_present": False,
                    "secret_file_read": False,
                    "state_read": False,
                    "state_write": False,
                },
            )
            self.assertEqual(git(authority, "rev-parse", "refs/heads/dev"), dev_before)
            self.assertEqual(dev_before, base_commit)
            self.assertEqual(tree_snapshot(runtime), authority_before)
            self.assertNotIn(fake_secret, result_text)
            self.assertNotIn(fake_secret, str(raised.exception))

            adapter_program = f'''#!/usr/bin/env python3
import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
authority = Path({str(authority)!r})
state = Path({str(state_path)!r})
secret = Path({str(secret_path)!r})

def attempt_write(path):
    try:
        path.write_bytes(b"adapter-overwrite")
        return True
    except OSError:
        return False

def attempt_read(path):
    try:
        path.read_bytes()
        return True
    except OSError:
        return False

print(json.dumps({{
    "protocol_version": "nm-v6/adapter-result-v1",
    "operation_id": request["operation_id"],
    "attempt_id": request["attempt_id"],
    "status": "succeeded",
    "session_id": "advisory-only",
    "candidate_commit": None,
    "changed_paths": [],
    "observations": [{{
        "authority_write": attempt_write(authority / "adapter-owned"),
        "state_write": attempt_write(state),
        "secret_read": attempt_read(secret),
    }}],
    "requested_followups": [],
    "usage": {{}},
    "adapter_diagnostics": {{}},
}}))
'''
            adapter_script = workspace.path / "malicious_adapter.py"
            adapter_script.write_text(adapter_program, encoding="utf-8")
            adapter_script.chmod(0o700)
            adapter_backend = SubprocessBackend(
                executable=str(adapter_script),
                isolation_backend=backend,
            )
            request = adapter_request(workspace.path)
            session_id = adapter_backend.start(
                FakeAdapter.profile,
                request,
                Invocation((), json.dumps(request)),
            )
            for _ in range(100):
                if adapter_backend.poll(session_id)["status"] == "finished":
                    break
                time.sleep(0.01)
            adapter_result = adapter_backend.collect(session_id)
            self.assertEqual(
                adapter_result["observations"],
                [
                    {
                        "authority_write": False,
                        "state_write": False,
                        "secret_read": False,
                    }
                ],
            )
            self.assertEqual(tree_snapshot(runtime), authority_before)
            manager.dispose(workspace)

    def test_ac017_state_and_verification_sigkill_resume_once(self) -> None:
        state_script = r"""
from pathlib import Path
import sys
from nmv6.reducer import Reducer
from nmv6.store import Store

store = Store(Path(sys.argv[1]))
try:
    Reducer(store).create_run(
        run_id="run-state-crash",
        spec_hash="a" * 64,
        config_hash="b" * 64,
        idempotency_key="create-run-state-crash",
    )
finally:
    store.close()
"""
        for point in ("state.before_commit", "state.after_commit"):
            with self.subTest(boundary=point), tempfile.TemporaryDirectory(
                prefix="nm-v6-ac017-state-"
            ) as directory:
                database = Path(directory) / "state.sqlite3"
                Store(database).close()
                crashed = run_child(state_script, str(database), failpoint=point)
                assert_sigkill(self, crashed)
                replay = run_child(state_script, str(database))
                self.assertEqual(
                    replay.returncode,
                    0,
                    f"state replay failed:\n{replay.stdout}\n{replay.stderr}",
                )
                store = Store(database)
                try:
                    store.integrity_check()
                    self.assertEqual(len(store.list_events("run-state-crash")), 1)
                    self.assertEqual(len(store.list_audit()), 1)
                finally:
                    store.close()

        verify_program = r'''
import json
t = "2026-01-01T00:00:00Z"
print(json.dumps({
    "protocol_version": "nm-v6/action-result-v1",
    "action_id": "verify",
    "operation_id": None,
    "status": "succeeded",
    "effect_id": None,
    "artifact_digest": None,
    "environment_id": None,
    "environment_fingerprint": None,
    "observed_state": {"tests_passed": True},
    "started_at": t,
    "finished_at": t,
    "diagnostics": {},
    "redactions": [],
}))
'''
        for point in ("action.verify.before_invoke", "action.verify.after_invoke"):
            with self.subTest(boundary=point), tempfile.TemporaryDirectory(
                prefix="nm-v6-ac017-verify-"
            ) as directory:
                root = Path(directory)
                (root / "verify_action.py").write_text(
                    textwrap.dedent(verify_program), encoding="utf-8"
                )
                store = Store(root / "state.sqlite3")
                Reducer(store).create_run(
                    run_id="run-crash",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    idempotency_key="create-run-crash",
                )
                store.close()

                crashed = run_child(VERIFY_DRIVER, str(root), failpoint=point)
                assert_sigkill(self, crashed)
                resumed = run_child(VERIFY_DRIVER, str(root))
                self.assertEqual(
                    resumed.returncode,
                    0,
                    f"verification recovery failed:\n{resumed.stdout}\n{resumed.stderr}",
                )
                store = Store(root / "state.sqlite3")
                evidence = EvidenceStore(root / "evidence")
                try:
                    store.integrity_check()
                    receipts = store.list_evidence("run-crash")
                    self.assertEqual(len(receipts), 1)
                    evidence.validate(receipts[0])
                    events = store.list_events("run-crash")
                    self.assertEqual(
                        sum(
                            event["event_type"] == "EVIDENCE_RECORDED"
                            for event in events
                        ),
                        1,
                    )
                finally:
                    store.close()

    def test_ac017_git_integration_sigkill_observes_or_executes_one_cas(self) -> None:
        for point in (
            "git.before_protected_update",
            "git.after_protected_update",
        ):
            with self.subTest(boundary=point), tempfile.TemporaryDirectory(
                prefix="nm-v6-ac017-git-"
            ) as directory:
                repository = Path(directory) / "repository"
                repository.mkdir()
                git(repository, "init", "-b", "main")
                git(repository, "config", "user.name", "Crash Test")
                git(repository, "config", "user.email", "crash@example.invalid")
                (repository / "base.txt").write_text("base\n", encoding="utf-8")
                git(repository, "add", "base.txt")
                git(repository, "commit", "-m", "base")
                base = git(repository, "rev-parse", "HEAD")
                git(repository, "branch", "dev", base)
                remote = Path(directory) / "remote.git"
                remote.mkdir()
                git(remote, "init", "--bare")
                git(repository, "remote", "add", "origin", str(remote))
                git(repository, "push", "origin", "main:main", "dev:dev")
                git(repository, "checkout", "-b", "feature/crash-integration")
                (repository / "candidate.txt").write_text(
                    "candidate\n", encoding="utf-8"
                )
                git(repository, "add", "candidate.txt")
                git(repository, "commit", "-m", "candidate")
                candidate = git(repository, "rev-parse", "HEAD")
                reflog_before = git(
                    repository,
                    "reflog",
                    "show",
                    "--format=%H",
                    "refs/heads/dev",
                ).splitlines()

                crashed = run_child(GIT_DRIVER, str(repository), failpoint=point)
                assert_sigkill(self, crashed)
                observed = git(repository, "rev-parse", "refs/heads/dev")
                if observed == base:
                    resumed = run_child(GIT_DRIVER, str(repository))
                    self.assertEqual(
                        resumed.returncode,
                        0,
                        f"Git recovery failed:\n{resumed.stdout}\n{resumed.stderr}",
                    )
                elif observed != candidate:
                    self.fail(f"protected ref has an unexpected crash value: {observed}")

                self.assertEqual(
                    git(repository, "rev-parse", "refs/heads/dev"), candidate
                )
                reflog_after = git(
                    repository,
                    "reflog",
                    "show",
                    "--format=%H",
                    "refs/heads/dev",
                ).splitlines()
                self.assertEqual(len(reflog_after), len(reflog_before) + 1)
                self.assertEqual(reflog_after[0], candidate)

    def test_ac017_release_deploy_rollback_sigkill_reconcile_one_effect(self) -> None:
        fake_external_action = r'''
import json
import os
import sys
from pathlib import Path

action_id = sys.argv[1]
state_path = Path(sys.argv[2])
operation_id = os.environ["NM_V6_OPERATION_ID"]
if state_path.exists():
    state = json.loads(state_path.read_text(encoding="utf-8"))
else:
    state = {"effects": {}, "counts": {}}
is_observation = action_id.endswith("_observe") or action_id.endswith("_reconcile")
if is_observation:
    completed = operation_id in state["effects"]
    classification = "completed" if completed else "not_started"
    effect_id = None
else:
    if operation_id not in state["effects"]:
        state["effects"][operation_id] = "effect-" + operation_id
        state["counts"][action_id] = state["counts"].get(action_id, 0) + 1
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, state_path)
    classification = "completed"
    effect_id = state["effects"][operation_id]
t = "2026-01-01T00:00:00Z"
print(json.dumps({
    "protocol_version": "nm-v6/action-result-v1",
    "action_id": action_id,
    "operation_id": operation_id,
    "status": "succeeded",
    "effect_id": effect_id,
    "artifact_digest": None,
    "environment_id": None,
    "environment_fingerprint": None,
    "observed_state": {"classification": classification},
    "started_at": t,
    "finished_at": t,
    "diagnostics": {},
    "redactions": [],
}))
'''
        for action_id in ("release", "deploy", "rollback"):
            for position in ("before", "after"):
                point = f"delivery.{action_id}.{position}"
                with self.subTest(
                    action=action_id, boundary=position
                ), tempfile.TemporaryDirectory(
                    prefix=f"nm-v6-ac017-{action_id}-"
                ) as directory:
                    root = Path(directory)
                    (root / "fake_external_action.py").write_text(
                        textwrap.dedent(fake_external_action), encoding="utf-8"
                    )
                    crashed = run_child(
                        DELIVERY_DRIVER,
                        str(root),
                        action_id,
                        "mutate",
                        failpoint=point,
                    )
                    assert_sigkill(self, crashed)
                    operation_path = root / "operations.json"
                    if operation_path.exists():
                        resumed = run_child(
                            DELIVERY_DRIVER,
                            str(root),
                            action_id,
                            "recover",
                        )
                    else:
                        resumed = run_child(
                            DELIVERY_DRIVER,
                            str(root),
                            action_id,
                            "mutate",
                        )
                    self.assertEqual(
                        resumed.returncode,
                        0,
                        f"delivery recovery failed:\n{resumed.stdout}\n{resumed.stderr}",
                    )
                    effects = json.loads(
                        (root / "effects.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(effects["counts"], {action_id: 1})
                    operations = json.loads(
                        operation_path.read_text(encoding="utf-8")
                    )["operations"]
                    self.assertEqual(len(operations), 1)
                    operation = next(iter(operations.values()))
                    self.assertEqual(operation["status"], "succeeded")

    def test_ac058_missing_corrupt_blobs_fail_gates_and_db_tamper_fails_integrity(
        self,
    ) -> None:
        for damage in ("missing", "corrupt"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory(
                prefix=f"nm-v6-ac058-{damage}-"
            ) as directory:
                root = Path(directory)
                store = Store(root / "state.sqlite3")
                evidence = EvidenceStore(root / "evidence")
                reducer = Reducer(store, evidence_store=evidence)
                reducer.create_run(
                    run_id="run-evidence",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    idempotency_key="create-run-evidence",
                )
                receipt_input = base_receipt(
                    "run-evidence", "EVID-run-damage-001"
                )
                receipt_input["subject_ids"] = list(
                    required_prerequisites("TASK_GATE")
                )
                receipt_input["assertions"] = {
                    name: True
                    for name in required_prerequisites("TASK_GATE")
                }
                receipt = evidence.persist(
                    receipt_input,
                    b"independent verification passed",
                    b"",
                )
                reducer.record_evidence(
                    run_id="run-evidence",
                    expected_revision=0,
                    receipt=receipt,
                    idempotency_key="record-damage-evidence",
                )

                def resolve_evidence(evidence_id: str) -> Mapping[str, Any] | None:
                    stored = store.get_evidence(evidence_id)
                    if stored is None:
                        return None
                    evidence.validate(stored)
                    return stored

                facts = {
                    name: True for name in required_prerequisites("TASK_GATE")
                }
                facts["run_id"] = "run-evidence"
                facts["candidate_commit"] = "candidate-commit"
                facts["prerequisite_evidence"] = {
                    name: [receipt["evidence_id"]]
                    for name in required_prerequisites("TASK_GATE")
                }
                valid = GateEvaluator(
                    resolve_evidence,
                    evidence_validator=evidence.validate,
                ).evaluate(
                    GateObservation(
                        gate_type="TASK_GATE",
                        subject_ids=("TASK-001",),
                        context=facts,
                        evidence_ids=(receipt["evidence_id"],),
                        evaluator="nm-v6-core/gate-executor",
                    ),
                    gate_id=f"GATE-before-{damage}",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    run_revision=1,
                )
                self.assertEqual(valid["result"], "passed")

                blob = evidence.blob_path(receipt["stdout_digest"])
                if damage == "missing":
                    blob.unlink()
                else:
                    blob.write_bytes(b"corrupt-evidence")
                with self.assertRaises(EvidenceError):
                    evidence.validate(receipt)

                invalid = GateEvaluator(
                    resolve_evidence,
                    evidence_validator=evidence.validate,
                ).evaluate(
                    GateObservation(
                        gate_type="TASK_GATE",
                        subject_ids=("TASK-001",),
                        context=facts,
                        evidence_ids=(receipt["evidence_id"],),
                        evaluator="nm-v6-core/gate-executor",
                    ),
                    gate_id=f"GATE-after-{damage}",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    run_revision=1,
                )
                self.assertEqual(invalid["result"], "failed")
                self.assertIn("invalid evidence", invalid["reason"])
                with self.assertRaises((EvidenceError, TransitionError)):
                    reducer.record_gate(
                        run_id="run-evidence",
                        expected_revision=1,
                        decision=invalid,
                        idempotency_key=f"record-invalid-{damage}",
                    )
                store.close()

        with tempfile.TemporaryDirectory(prefix="nm-v6-ac058-db-") as directory:
            database = Path(directory) / "state.sqlite3"
            store = Store(database)
            Reducer(store).create_run(
                run_id="run-corrupt-db",
                spec_hash="a" * 64,
                config_hash="b" * 64,
                idempotency_key="create-run-corrupt-db",
            )
            store.close()
            connection = sqlite3.connect(database)
            try:
                connection.execute("DROP TRIGGER events_no_update")
                connection.execute(
                    "UPDATE events SET payload_json = '{}' WHERE sequence = 1"
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(RecoveryError):
                Store(database)


if __name__ == "__main__":
    unittest.main()
