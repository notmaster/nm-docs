from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable


REPOSITORY = Path(__file__).resolve().parents[3]
TOOLS = REPOSITORY / "tools/nm-v6"
sys.path.insert(0, str(TOOLS))

from nmv6.authorization import signed_payload  # noqa: E402
from nmv6.adapters import FakeAdapter, MemoryBackend  # noqa: E402
from nmv6.evidence import EvidenceStore  # noqa: E402
from nmv6.errors import ContractError, RecoveryError, TransitionError  # noqa: E402
from nmv6.merge_review import seal_merge_review_observation  # noqa: E402
from nmv6.git_controller import MergeReceipt  # noqa: E402
from nmv6.reducer import Reducer  # noqa: E402
from nmv6.runtime import ConfiguredRuntimeEngine  # noqa: E402
from nmv6.scheduler import (  # noqa: E402
    ReducerLeaseAuthority,
    Scheduler,
    TaskDefinition,
    TaskGraph,
)
from nmv6.store import Store  # noqa: E402
from nmv6.supply_chain import collect_project_runtime_versions  # noqa: E402
from nmv6.template_sync import initialize_project  # noqa: E402


class GeneratedNormalRuntimeTests(unittest.TestCase):
    def _git(self, target: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=target,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def _sign(
        self, root: Path, private_key: Path, name: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        payload = root / f"{name}.payload"
        signature = root / f"{name}.signature"
        payload.write_bytes(signed_payload(record))
        subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(private_key),
                "-out",
                str(signature),
                str(payload),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            **record,
            "authenticator_signature": base64.b64encode(
                signature.read_bytes()
            ).decode("ascii"),
        }

    def _engine_fixture(
        self, root: Path, *, run_id: str
    ) -> tuple[Path, ConfiguredRuntimeEngine, Store]:
        target = root / "project"
        initialize_project(
            target,
            source_root=REPOSITORY,
            project_name="Runtime Engine Fixture",
            package_name="runtime-engine-fixture",
        )
        remote = root / "remote.git"
        subprocess.run(
            ["git", "clone", "--bare", "--no-local", str(target), str(remote)],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
        head = self._git(target, "rev-parse", "HEAD")
        self._git(remote, "update-ref", "refs/heads/dev", head)
        self._git(remote, "update-ref", "refs/heads/main", head)
        self._git(target, "remote", "add", "origin", str(remote))
        project = json.loads(
            (target / "project.json").read_text(encoding="utf-8")
        )
        store = Store(target / ".nm/runtime/v6/state.sqlite3")
        reducer = Reducer(
            store,
            evidence_store=EvidenceStore(target / ".nm/runtime/v6/evidence"),
        )
        traceability = json.loads(
            (target / "0a-docs/0a-spec/traceability.json").read_text(
                encoding="utf-8"
            )
        )
        version_baseline = collect_project_runtime_versions(target, project)
        reducer.create_run(
            run_id=run_id,
            spec_hash="a" * 64,
            config_hash="b" * 64,
            mode="auto",
            run_kind="normal",
            idempotency_key=f"create:{run_id}",
            payload={
                "traceability": traceability,
                "version_baseline": version_baseline,
            },
        )
        return (
            target,
            ConfiguredRuntimeEngine(
                target,
                project,
                reducer,
                store,
                run_id=run_id,
                version_baseline=version_baseline,
            ),
            store,
        )

    def _run_task_batch_fixture(
        self,
        root: Path,
        *,
        run_id: str,
        max_workers: int,
        barrier_required: bool = False,
        declared_overlap: bool = False,
        actual_overlap: bool = False,
        crash_after_batch_gate: bool = False,
    ) -> tuple[Path, ConfiguredRuntimeEngine, Store, str, int]:
        target, engine, store = self._engine_fixture(root, run_id=run_id)
        engine.project["scheduler"]["max_workers"] = max_workers
        phase = dict(engine._phases()[0])
        source_task = dict(engine._tasks()[0])
        first = {
            **source_task,
            "id": "TASK-001",
            "phase_id": str(phase["id"]),
            "depends_on": [],
            "write_set": ["src/**" if declared_overlap else "src/a/**"],
        }
        second = {
            **source_task,
            "id": "TASK-002",
            "phase_id": str(phase["id"]),
            "depends_on": [],
            "write_set": ["src/**" if declared_overlap else "src/b/**"],
        }
        engine.traceability["tasks"] = [first, second]
        graph = engine._task_graph()
        scheduler = Scheduler(
            graph,
            ReducerLeaseAuthority(engine.reducer, run_id=run_id),
            max_workers=max_workers,
            lease_seconds=120,
        )
        branch, candidate = engine._ensure_candidate_branch()
        barrier = threading.Barrier(2) if barrier_required else None
        lock = threading.Lock()
        active = 0
        maximum_active = 0

        def candidate_result(
            request: dict[str, Any], session_id: str
        ) -> dict[str, Any]:
            nonlocal active, maximum_active
            attempt_id = str(request["attempt_id"])
            task_number = 1 if "t001" in attempt_id else 2
            workspace = Path(str(request["workspace"]))
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                if barrier is not None:
                    barrier.wait(timeout=5)
                changed = (
                    workspace / "src/shared.txt"
                    if actual_overlap
                    else workspace / f"src/{'a' if task_number == 1 else 'b'}/task.txt"
                )
                changed.parent.mkdir(parents=True, exist_ok=True)
                changed.write_text(f"task-{task_number}\n", encoding="utf-8")
                relative = changed.relative_to(workspace).as_posix()
                self._git(workspace, "add", relative)
                self._git(
                    workspace,
                    "-c",
                    "user.name=NM V6 Test",
                    "-c",
                    "user.email=nm-v6-test@example.invalid",
                    "commit",
                    "-m",
                    f"test: concurrent task {task_number}",
                )
                return {
                    "protocol_version": "nm-v6/adapter-result-v1",
                    "operation_id": request["operation_id"],
                    "attempt_id": request["attempt_id"],
                    "status": "succeeded",
                    "session_id": session_id,
                    "candidate_commit": self._git(workspace, "rev-parse", "HEAD"),
                    "changed_paths": [relative],
                    "observations": [],
                    "requested_followups": [],
                    "usage": {},
                    "adapter_diagnostics": {"fixture": "concurrent-batch"},
                }
            finally:
                with lock:
                    active -= 1

        backend = MemoryBackend(candidate_result)
        completed: set[str] = set()
        accepted_paths: dict[str, tuple[str, ...]] = {}
        task_map = {"TASK-001": first, "TASK-002": second}
        global_index = {"TASK-001": 1, "TASK-002": 2}
        with mock.patch(
            "nmv6.runtime.create_adapter",
            side_effect=lambda *_args, **_kwargs: FakeAdapter(backend=backend),
        ):
            def drive_once() -> None:
                nonlocal candidate
                outcome = engine._drive_task_batch(
                    scope_id=f"test:{phase['id']}",
                    scheduler=scheduler,
                    graph=graph,
                    tasks=task_map,
                    phases={str(phase["id"]): phase},
                    global_index=global_index,
                    completed_tasks=completed,
                    accepted_paths=accepted_paths,
                    branch=branch,
                    candidate=candidate,
                    provider="fake",
                )
                if outcome is None:
                    self.fail("Task batch did not select ready work")
                candidate, paths, _evidence, _gates = outcome
                accepted_paths.update(paths)

            try:
                if crash_after_batch_gate:
                    fired = False

                    def fail_after_first_batch_gate(name: str) -> None:
                        nonlocal fired
                        if name == "runtime.after_task_batch_gate" and not fired:
                            fired = True
                            raise RuntimeError("injected Task batch Gate interruption")

                    with mock.patch(
                        "nmv6.runtime.checkpoint",
                        side_effect=fail_after_first_batch_gate,
                    ):
                        with self.assertRaisesRegex(
                            RuntimeError, "Task batch Gate interruption"
                        ):
                            drive_once()
                while completed != set(task_map):
                    drive_once()
            except TransitionError:
                if not actual_overlap:
                    raise
                candidate = engine.git.resolve_commit(f"refs/heads/{branch}")
        return target, engine, store, candidate, maximum_active

    def test_max_workers_two_runs_one_real_overlapping_task_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target, engine, store, candidate, maximum_active = (
                self._run_task_batch_fixture(
                    Path(directory),
                    run_id="run-concurrent-task-batch",
                    max_workers=2,
                    barrier_required=True,
                )
            )
            try:
                self.assertEqual(2, maximum_active)
                self.assertEqual(
                    "task-1",
                    self._git(target, "show", f"{candidate}:src/a/task.txt"),
                )
                self.assertEqual(
                    "task-2",
                    self._git(target, "show", f"{candidate}:src/b/task.txt"),
                )
                events = store.list_events(run_id=engine.run_id)
                self.assertEqual(
                    2,
                    sum(event["event_type"] == "ADAPTER_REQUESTED" for event in events),
                )
                planned = [
                    event["payload"]["record"]
                    for event in events
                    if event["event_type"] == "TASK_BATCH_PLANNED"
                ]
                self.assertEqual(
                    [["TASK-001", "TASK-002"]],
                    [record["ordered_task_ids"] for record in planned],
                )
                attempts = store.list_entities(
                    engine.run_id, machine="attempt"
                )
                task_attempts = [
                    attempt
                    for attempt in attempts
                    if attempt.get("payload", {}).get("task_id")
                    in {"TASK-001", "TASK-002"}
                ]
                self.assertEqual(2, len(task_attempts))
                for attempt in task_attempts:
                    self.assertFalse(
                        Path(attempt["payload"]["workspace_path"]).exists()
                    )
                imported = [
                    event["payload"]["record"]
                    for event in events
                    if event["event_type"] == "TASK_RESULT_IMPORTED"
                ]
                self.assertEqual(2, len(imported))
                for record in imported:
                    self.assertEqual(
                        "",
                        self._git(
                            target,
                            "for-each-ref",
                            "--format=%(refname)",
                            record["import_ref"],
                        ),
                    )
                    subprocess.run(
                        [
                            "git",
                            "merge-base",
                            "--is-ancestor",
                            record["result_commit"],
                            candidate,
                        ],
                        cwd=target,
                        check=True,
                    )
            finally:
                store.close()

    def test_single_and_multi_worker_task_batches_have_equivalent_trees(self) -> None:
        results: list[str] = []
        tree_entries: list[list[str]] = []
        stores: list[Store] = []
        try:
            for workers in (1, 2):
                directory = tempfile.TemporaryDirectory()
                self.addCleanup(directory.cleanup)
                target, engine, store, candidate, _maximum = (
                    self._run_task_batch_fixture(
                        Path(directory.name),
                        run_id=f"run-task-batch-equivalence-{workers}",
                        max_workers=workers,
                    )
                )
                stores.append(store)
                results.append(engine.git.tree_of(candidate))
                tree_entries.append(
                    [
                        line
                        for line in self._git(
                            target, "ls-tree", "-r", candidate
                        ).splitlines()
                        if not line.endswith("\t.nm-template-state.json")
                    ]
                )
                self.assertEqual(
                    "task-1",
                    self._git(target, "show", f"{candidate}:src/a/task.txt"),
                )
                self.assertEqual(
                    "task-2",
                    self._git(target, "show", f"{candidate}:src/b/task.txt"),
                )
            self.assertEqual(tree_entries[0], tree_entries[1])
        finally:
            for store in stores:
                store.close()

    def test_declared_overlap_is_split_into_serial_task_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _target, engine, store, _candidate, maximum_active = (
                self._run_task_batch_fixture(
                    Path(directory),
                    run_id="run-declared-overlap-batches",
                    max_workers=2,
                    declared_overlap=True,
                )
            )
            try:
                self.assertEqual(1, maximum_active)
                planned = [
                    event["payload"]["record"]["ordered_task_ids"]
                    for event in store.list_events(run_id=engine.run_id)
                    if event["event_type"] == "TASK_BATCH_PLANNED"
                ]
                self.assertEqual([["TASK-001"], ["TASK-002"]], planned)
            finally:
                store.close()

    def test_actual_overlap_blocks_before_candidate_ref_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _target, engine, store, candidate, maximum_active = (
                self._run_task_batch_fixture(
                    Path(directory),
                    run_id="run-actual-overlap-batch",
                    max_workers=2,
                    barrier_required=True,
                    actual_overlap=True,
                )
            )
            try:
                self.assertEqual(2, maximum_active)
                blocked = [
                    event["payload"]["record"]
                    for event in store.list_events(run_id=engine.run_id)
                    if event["event_type"] == "TASK_BATCH_BLOCKED"
                ]
                self.assertEqual(1, len(blocked))
                self.assertEqual("actual_write_overlap", blocked[0]["reason"])
                self.assertTrue(blocked[0]["candidate_ref_unchanged"])
                self.assertEqual(blocked[0]["base_commit"], candidate)
                self.assertIsNotNone(
                    store.get_evidence(blocked[0]["evidence_id"])
                )
                self.assertEqual(
                    "ATTENTION_REQUIRED", store.get_run(engine.run_id)["state"]
                )
                for task_id in ("TASK-001", "TASK-002"):
                    self.assertIsNone(store.get_lease(task_id))
                    self.assertEqual(
                        "BLOCKED",
                        store.get_entity_state(
                            "task", engine._entity_id(task_id)
                        )["state"],
                    )
                self.assertFalse(
                    any(
                        event["event_type"] == "CANDIDATE_BRANCH_ADVANCED"
                        for event in store.list_events(run_id=engine.run_id)
                    )
                )
            finally:
                store.close()

    def test_task_batch_recovers_gate_before_candidate_cas_without_redispatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target, engine, store, candidate, maximum_active = (
                self._run_task_batch_fixture(
                    Path(directory),
                    run_id="run-task-batch-gate-recovery",
                    max_workers=2,
                    barrier_required=True,
                    crash_after_batch_gate=True,
                )
            )
            try:
                self.assertEqual(2, maximum_active)
                self.assertEqual(
                    "task-1",
                    self._git(target, "show", f"{candidate}:src/a/task.txt"),
                )
                self.assertEqual(
                    "task-2",
                    self._git(target, "show", f"{candidate}:src/b/task.txt"),
                )
                events = store.list_events(run_id=engine.run_id)
                for event_type in (
                    "ADAPTER_REQUESTED",
                    "ADAPTER_SESSION_RECORDED",
                    "ADAPTER_RESULT_RECORDED",
                    "CANDIDATE_BRANCH_ADVANCED",
                ):
                    self.assertEqual(
                        2,
                        sum(event["event_type"] == event_type for event in events),
                        msg=event_type,
                    )
            finally:
                store.close()

    def test_expired_batch_result_is_fenced_before_new_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, engine, store = self._engine_fixture(
                root, run_id="run-expired-batch-result"
            )
            try:
                phase = dict(engine._phases()[0])
                task = {
                    **dict(engine._tasks()[0]),
                    "id": "TASK-001",
                    "phase_id": phase["id"],
                    "depends_on": [],
                    "write_set": ["src/a/**"],
                }
                engine.traceability["tasks"] = [task]
                graph = engine._task_graph()
                definition = graph.tasks["TASK-001"]
                scheduler = Scheduler(
                    graph,
                    ReducerLeaseAuthority(engine.reducer, run_id=engine.run_id),
                    max_workers=1,
                    lease_seconds=1,
                )
                branch, base = engine._ensure_candidate_branch()
                batch = engine._task_batch_plan(
                    scope_id=f"test:{phase['id']}",
                    branch=branch,
                    base_commit=base,
                    definitions=(definition,),
                )
                backend = MemoryBackend()
                with mock.patch(
                    "nmv6.runtime.create_adapter",
                    side_effect=lambda *_args, **_kwargs: FakeAdapter(
                        backend=backend
                    ),
                ):
                    first = engine._prepare_batch_attempt(
                        batch=batch,
                        scheduler=scheduler,
                        definition=definition,
                        task=task,
                        phase=phase,
                        task_index=1,
                        branch=branch,
                        provider="fake",
                    )
                    assert first is not None
                    engine._start_collect_task_batch(
                        scheduler=scheduler,
                        contexts=(first,),
                        provider="fake",
                    )
                    time.sleep(1.05)
                    replacement = engine._prepare_batch_attempt(
                        batch=batch,
                        scheduler=scheduler,
                        definition=definition,
                        task=task,
                        phase=phase,
                        task_index=1,
                        branch=branch,
                        provider="fake",
                    )
                assert replacement is not None
                self.assertNotEqual(first.attempt_id, replacement.attempt_id)
                self.assertGreater(
                    replacement.lease.fencing_token,
                    first.lease.fencing_token,
                )
                self.assertEqual(
                    "LOST",
                    store.get_entity_state("attempt", first.attempt_id)["state"],
                )
                self.assertEqual(
                    base,
                    engine.git.resolve_commit(f"refs/heads/{branch}"),
                )
                self.assertFalse(
                    any(
                        event["event_type"] == "CANDIDATE_BRANCH_ADVANCED"
                        for event in store.list_events(run_id=engine.run_id)
                    )
                )
                self.assertEqual(
                    1,
                    sum(
                        event["event_type"] == "ADAPTER_ATTEMPT_STALE"
                        for event in store.list_events(run_id=engine.run_id)
                    ),
                )
                engine._dispose_workspace(
                    replacement.manager,
                    replacement.workspace,
                    replacement.root,
                )
            finally:
                store.close()

    def _delivery_cli_fixture(
        self,
        root: Path,
        *,
        run_id: str,
        delivery_stages: dict[str, Any],
        include_rollback_authorization: bool = True,
        expected_identity: str | None = None,
        markers: tuple[str, ...] = (),
    ) -> tuple[Path, Callable[..., dict[str, Any]]]:
        """Create one signed generated-project run for delivery state tests."""

        target = root / "project"
        initialize_project(
            target,
            source_root=REPOSITORY,
            project_name=f"Delivery Runtime {run_id}",
            package_name=run_id,
        )
        private_key = root / "admin-private.pem"
        public_key = target / "0c-workflow/fixtures/fake-admin-public.pem"
        subprocess.run(
            ["openssl", "genrsa", "-out", str(private_key), "2048"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "openssl",
                "rsa",
                "-in",
                str(private_key),
                "-pubout",
                "-out",
                str(public_key),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        project_path = target / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["adapters"]["configured"] = ["fake"]
        configured = project["delivery"]["environments"]
        base_environment = copy.deepcopy(configured["production"])
        for logical_name in delivery_stages["environments"]:
            configured.setdefault(logical_name, copy.deepcopy(base_environment))
        if expected_identity is not None:
            for logical_name in delivery_stages["environments"]:
                configured[logical_name]["expected_identity"] = expected_identity
        project_path.write_text(
            json.dumps(project, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        traceability_path = target / "0a-docs/0a-spec/traceability.json"
        traceability = json.loads(traceability_path.read_text(encoding="utf-8"))
        traceability["required_delivery_stages"] = copy.deepcopy(delivery_stages)
        traceability_path.write_text(
            json.dumps(traceability, indent=2) + "\n", encoding="utf-8"
        )
        for marker in markers:
            (target / marker).write_text("fixture\n", encoding="utf-8")
        self._git(
            target,
            "add",
            "project.json",
            str(public_key.relative_to(target)),
            str(traceability_path.relative_to(target)),
            *markers,
        )
        self._git(
            target,
            "-c",
            "user.name=NM V6 Test",
            "-c",
            "user.email=nm-v6-test@example.invalid",
            "commit",
            "-m",
            f"test: configure delivery fixture {run_id}",
        )
        remote = root / "remote.git"
        subprocess.run(
            ["git", "clone", "--bare", "--no-local", str(target), str(remote)],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
        head = self._git(target, "rev-parse", "HEAD")
        self._git(remote, "update-ref", "refs/heads/dev", head)
        self._git(remote, "update-ref", "refs/heads/main", head)
        self._git(target, "remote", "add", "origin", str(remote))

        def invoke(*arguments: str) -> dict[str, Any]:
            completed = subprocess.run(
                [sys.executable, str(TOOLS / "nm_v6.py"), *arguments],
                cwd=target,
                env={**os.environ, "NM_V6_PYTHON": sys.executable},
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
            if completed.returncode != 0:
                self.fail(
                    f"delivery fixture command failed ({completed.returncode}): "
                    + " ".join(arguments)
                    + "\n"
                    + completed.stderr
                )
            return json.loads(completed.stdout)

        planned = invoke("plan", "--target", str(target), "--run-id", run_id)
        self.assertEqual("SPEC_REVIEW", planned["state"])
        expiry = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        confirmation_request = invoke(
            "spec",
            "confirmation",
            "request",
            "--target",
            str(target),
            "--run-id",
            run_id,
            "--expires-at",
            expiry,
        )["request"]
        confirmation = self._sign(
            root,
            private_key,
            f"{run_id}-confirmation",
            {
                "record_type": "spec_confirmation",
                "confirmation_id": f"AUTH-{run_id}-confirmation",
                "spec_id": "SPEC-EXAMPLE-V1",
                "version": 1,
                "spec_hash": confirmation_request["spec_hash"],
                "decision": "confirmed",
                "administrator_identity": "fixture-administrator",
                "issued_at": datetime.now(UTC).isoformat(),
                "nonce": confirmation_request["nonce"],
                "authenticator_id": "fixture-admin",
            },
        )
        confirmation_path = root / f"{run_id}-confirmation.json"
        confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")
        invoke(
            "spec",
            "confirm",
            "--target",
            str(target),
            "--run-id",
            run_id,
            "--record",
            str(confirmation_path),
        )
        for expected in ("SPEC_CONFIRMED", "PLANNING", "READY"):
            self.assertEqual(
                expected,
                invoke(
                    "run", "--target", str(target), "--run-id", run_id, "--once"
                )["state"],
            )

        with Store(target / ".nm/runtime/v6/state.sqlite3") as state:
            current = state.get_run(run_id)
            assert current is not None
            actions = ["mode_set_auto", "integrate_dev", "cancel"]
            if delivery_stages["release"] == "required":
                actions.extend(("release", "publish"))
            if delivery_stages["deploy"] == "required":
                actions.append("deploy")
                if include_rollback_authorization:
                    actions.append("rollback")
            authorized_environments = sorted(
                {
                    project["delivery"]["environments"][logical_name][
                        "expected_identity"
                    ]
                    for logical_name in delivery_stages["environments"]
                }
            )
            scope = {
                "run_id": run_id,
                "spec_hash": current["spec_hash"],
                "config_hash": current["config_hash"],
                "allowed_actions": actions,
                "allowed_environments": authorized_environments,
                "allowed_protected_refs": ["dev", "main"],
            }
        scope_path = root / f"{run_id}-scope.json"
        scope_path.write_text(json.dumps(scope), encoding="utf-8")
        grant_request = invoke(
            "authorize",
            "request",
            "--target",
            str(target),
            "--run-id",
            run_id,
            "--scope",
            str(scope_path),
            "--expires-at",
            expiry,
        )["request"]
        grant = self._sign(
            root,
            private_key,
            f"{run_id}-grant",
            {
                "record_type": "grant",
                "grant_id": f"AUTH-{run_id}-grant",
                **scope,
                "created_by": "fixture-administrator",
                "created_at": datetime.now(UTC).isoformat(),
                "expires_at": expiry,
                "request_digest": grant_request["request_digest"],
                "nonce": grant_request["nonce"],
                "grant_revision": grant_request["expected_revision"],
                "authenticator_id": "fixture-admin",
                "one_time": False,
            },
        )
        grant_path = root / f"{run_id}-grant.json"
        grant_path.write_text(json.dumps(grant), encoding="utf-8")
        invoke(
            "authorize",
            "approve",
            "--target",
            str(target),
            "--run-id",
            run_id,
            "--record",
            str(grant_path),
        )
        invoke(
            "mode",
            "set",
            "auto",
            "--target",
            str(target),
            "--run-id",
            run_id,
            "--grant-id",
            grant["grant_id"],
        )
        return target, invoke

    def _drive_delivery_fixture(
        self,
        invoke: Callable[..., dict[str, Any]],
        *,
        target: Path,
        run_id: str,
        terminal_states: set[str],
    ) -> list[str]:
        states: list[str] = []
        for _ in range(40):
            state = invoke(
                "run", "--target", str(target), "--run-id", run_id, "--once"
            )["state"]
            states.append(str(state))
            if state in terminal_states:
                return states
        self.fail(f"delivery fixture did not terminate: {states}")

    def test_merge_reviewer_failures_precede_gate_operation_and_ref_mutation(
        self,
    ) -> None:
        for failure in ("moved_target", "disabled_strategy"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target, engine, store = self._engine_fixture(
                    root, run_id=f"run-review-{failure}"
                )
                try:
                    dev = engine.git.fetch_dev(reconcile_local=True)
                    branch = f"task/review-{failure}"
                    self._git(target, "branch", branch, dev)
                    operation_id = engine._id("OP", 401)
                    gate_id = engine._gate_id("DEV_INTEGRATION_GATE", offset=1)
                    arguments = {
                        "review_scope": "work-to-dev-p001",
                        "expected_route": "work_to_dev",
                        "protected_operation_id": operation_id,
                        "source_ref": f"refs/heads/{branch}",
                        "target_branch": "dev",
                        "purpose": "negative-review-fixture",
                        "sharing_status": "local",
                        "single_logical_change": True,
                        "disposable": True,
                        "audit_boundary_required": False,
                        "rollback_boundary_required": False,
                        "future_gate_id": gate_id,
                        "authorization_id": "AUTH-review-negative",
                        "rollback_ref": "refs/nm-v6/rollback/review-negative",
                    }
                    if failure == "moved_target":
                        context = mock.patch.object(
                            engine.git, "remote_head", return_value="f" * 40
                        )
                    else:
                        engine.project["git"]["merge_strategies"] = [
                            "fast_forward"
                        ]

                        def disabled_result(
                            request: dict[str, Any], session_id: str
                        ) -> dict[str, Any]:
                            result = dict(
                                MemoryBackend._merge_review_result(
                                    request, session_id
                                )
                            )
                            observation = dict(result["observations"][0])
                            review_document = json.loads(
                                next(
                                    entry["content"]
                                    for entry in request["context_manifest"][
                                        "entries"
                                    ]
                                    if entry["source"]
                                    == "nm-v6://merge-review/request-v1"
                                )
                            )
                            observation.pop("observation_digest")
                            observation.update(
                                {
                                    "strategy": "squash",
                                    "rationale": "inject disabled strategy",
                                    "expected_result_tree": review_document[
                                        "strategy_results"
                                    ]["squash"]["expected_result_tree"],
                                }
                            )
                            result["observations"] = [
                                seal_merge_review_observation(observation)
                            ]
                            return result

                        adapter = FakeAdapter(
                            backend=MemoryBackend(result_factory=disabled_result)
                        )
                        context = mock.patch(
                            "nmv6.runtime.create_adapter", return_value=adapter
                        )
                    with context:
                        reviewed = engine._drive_merge_review(
                            store.get_run(engine.run_id), **arguments
                        )
                    self.assertIsNone(reviewed)
                    self.assertEqual(
                        "ATTENTION_REQUIRED",
                        store.get_run(engine.run_id)["state"],
                    )
                    self.assertIsNone(store.get_gate(gate_id))
                    self.assertIsNone(store.get_operation(operation_id))
                    self.assertEqual(dev, engine.git.resolve_commit("refs/heads/dev"))
                    self.assertEqual(dev, engine.git.remote_head("dev"))
                    self.assertFalse(
                        any(
                            event["event_type"] == "MERGE_PROPOSED"
                            for event in store.list_events(run_id=engine.run_id)
                        )
                    )
                finally:
                    store.close()

    def test_cleanup_reviewer_window_allows_only_its_own_lifecycle(self) -> None:
        for polluted in (False, True):
            with self.subTest(polluted=polluted), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_id = f"run-cleanup-window-{'polluted' if polluted else 'clean'}"
                target, engine, store = self._engine_fixture(root, run_id=run_id)
                try:
                    engine.project["adapters"]["configured"] = ["fake"]
                    dev = engine.git.fetch_dev(reconcile_local=True)
                    branch = f"task/cleanup-window-{'polluted' if polluted else 'clean'}"
                    self._git(target, "branch", branch, dev)
                    receipt = MergeReceipt(
                        strategy="fast_forward",
                        source_commit=dev,
                        target_before=dev,
                        target_after=dev,
                        result_tree=engine.git.tree_of(dev),
                        rollback_ref=f"refs/nm-v6/rollback/{run_id}",
                        authorization_id=f"AUTH-{run_id}",
                        executed_at=datetime.now(UTC).isoformat(),
                    )

                    def inject_unrelated(name: str) -> None:
                        if name != "runtime.after_cleanup_reviewer_result_record":
                            return
                        engine.reducer.record_domain_event(
                            run_id=run_id,
                            expected_revision=engine._revision(),
                            event_type="CANDIDATE_BRANCH_BOUND",
                            payload={"injected": True},
                            idempotency_key=f"inject-cleanup-window:{run_id}",
                            actor="test-injector",
                        )

                    checkpoint_context = (
                        mock.patch(
                            "nmv6.runtime.checkpoint",
                            side_effect=inject_unrelated,
                        )
                        if polluted
                        else mock.patch("nmv6.runtime.checkpoint")
                    )
                    with checkpoint_context:
                        reviewed = engine._drive_cleanup_review(
                            store.get_run(run_id),
                            review_scope="cleanup-window",
                            branch=branch,
                            target_branch="dev",
                            receipt_id=f"RECEIPT-{run_id}",
                            integration_receipt=receipt,
                        )
                    if polluted:
                        self.assertIsNone(reviewed)
                        self.assertEqual(
                            "ATTENTION_REQUIRED", store.get_run(run_id)["state"]
                        )
                        self.assertFalse(
                            any(
                                event["event_type"] == "BRANCH_CLEANUP_DECIDED"
                                for event in store.list_events(run_id=run_id)
                            )
                        )
                    else:
                        self.assertIsNotNone(reviewed)
                        assert reviewed is not None
                        decision, provenance = reviewed
                        self.assertEqual("request_administrator", decision.result)
                        self.assertEqual("reviewer_provenance", provenance["record_kind"])
                        self.assertEqual(
                            "SUCCEEDED",
                            store.get_entity_state(
                                "attempt",
                                f"ATTEMPT-runtime-{engine.identity}-cleanup-window-001",
                            )["state"],
                        )
                        self.assertEqual(
                            2,
                            sum(
                                event["event_type"] == "BRANCH_CLEANUP_DECIDED"
                                for event in store.list_events(run_id=run_id)
                            ),
                        )
                        self.assertTrue(engine.git.try_resolve_commit(branch))
                finally:
                    store.close()

    def test_cleanup_reviewer_recovers_core_and_provenance_boundaries(self) -> None:
        for failpoint in (
            "runtime.after_cleanup_core_decision",
            "runtime.after_cleanup_review_provenance",
        ):
            with self.subTest(failpoint=failpoint), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_id = "run-" + failpoint.removeprefix("runtime.").replace("_", "-")
                target, engine, store = self._engine_fixture(root, run_id=run_id)
                try:
                    engine.project["adapters"]["configured"] = ["fake"]
                    dev = engine.git.fetch_dev(reconcile_local=True)
                    branch = f"task/{run_id}"
                    self._git(target, "branch", branch, dev)
                    receipt = MergeReceipt(
                        strategy="fast_forward",
                        source_commit=dev,
                        target_before=dev,
                        target_after=dev,
                        result_tree=engine.git.tree_of(dev),
                        rollback_ref=f"refs/nm-v6/rollback/{run_id}",
                        authorization_id=f"AUTH-{run_id}",
                        executed_at=datetime.now(UTC).isoformat(),
                    )
                    arguments = {
                        "review_scope": "cleanup-recovery",
                        "branch": branch,
                        "target_branch": "dev",
                        "receipt_id": f"RECEIPT-{run_id}",
                        "integration_receipt": receipt,
                    }

                    def interrupt(name: str) -> None:
                        if name == failpoint:
                            raise RuntimeError(f"injected {failpoint}")

                    with mock.patch(
                        "nmv6.runtime.checkpoint", side_effect=interrupt
                    ):
                        with self.assertRaisesRegex(RuntimeError, "injected"):
                            engine._drive_cleanup_review(
                                store.get_run(run_id), **arguments
                            )
                    with mock.patch("nmv6.runtime.checkpoint"):
                        recovered = engine._drive_cleanup_review(
                            store.get_run(run_id), **arguments
                        )
                    self.assertIsNotNone(recovered)
                    assert recovered is not None
                    self.assertEqual("request_administrator", recovered[0].result)
                    events = store.list_events(run_id=run_id)
                    self.assertEqual(
                        2,
                        sum(
                            event["event_type"] == "BRANCH_CLEANUP_DECIDED"
                            for event in events
                        ),
                    )
                    for event_type in (
                        "ADAPTER_REQUESTED",
                        "ADAPTER_SESSION_RECORDED",
                        "ADAPTER_RESULT_RECORDED",
                    ):
                        self.assertEqual(
                            1,
                            sum(event["event_type"] == event_type for event in events),
                        )
                    self.assertEqual("DISCOVERING", store.get_run(run_id)["state"])
                    self.assertTrue(engine.git.try_resolve_commit(branch))
                finally:
                    store.close()

    def test_completion_terminal_snapshot_rejects_live_resources_and_remote_delete_consumption(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "run-terminal-resource-rejection"
            _target, engine, store = self._engine_fixture(root, run_id=run_id)
            try:
                workspace = root / "live-controller-workspace"
                workspace.mkdir()
                attempt_id = "ATTEMPT-terminal-resource-live-001"
                engine._ensure_entity(
                    "attempt",
                    attempt_id,
                    initial_state="CREATED",
                    payload={
                        "role": "cleanup_reviewer",
                        "session_id": "SESSION-live-terminal-resource",
                        "workspace_path": str(workspace),
                    },
                )
                snapshot = engine._terminal_resource_snapshot()
                self.assertEqual([attempt_id], snapshot["active_attempt_ids"])
                self.assertEqual(
                    ["SESSION-live-terminal-resource"],
                    snapshot["live_session_ids"],
                )
                self.assertEqual(
                    [str(workspace.resolve())], snapshot["live_workspace_paths"]
                )

                request_digest = "4" * 64
                authorization_id = "AUTH-terminal-delete-001"
                now = datetime.now(UTC).isoformat()
                delete_scope = {
                    "nonprotected_ref": {
                        "grant_id": "GRANT-terminal-delete-001",
                        "action": "delete_remote",
                        "remote": "origin",
                        "ref": "refs/heads/task/terminal-delete",
                        "expected_sha": "5" * 40,
                        "force": False,
                        "one_time": True,
                        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    }
                }
                record = {
                    "record_type": "grant",
                    "grant_id": authorization_id,
                    "run_id": run_id,
                    **delete_scope,
                }
                with store._write_transaction() as connection:
                    connection.execute(
                        "INSERT INTO authorization_requests("
                        "request_id, run_id, request_type, nonce, request_digest, "
                        "expected_revision, scope_json, expires_at, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            "REQUEST-terminal-delete-001",
                            run_id,
                            "grant",
                            "nonce-terminal-delete-request",
                            request_digest,
                            engine._revision(),
                            json.dumps(delete_scope),
                            delete_scope["nonprotected_ref"]["expires_at"],
                            now,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO authorization_records("
                        "authorization_id, record_type, run_id, request_digest, nonce, "
                        "authenticator_id, record_digest, record_json, issued_at, "
                        "expires_at, target_authorization_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            authorization_id,
                            "grant",
                            run_id,
                            request_digest,
                            "nonce-terminal-delete-record",
                            "fixture-admin",
                            "6" * 64,
                            json.dumps(record),
                            now,
                            delete_scope["nonprotected_ref"]["expires_at"],
                            None,
                            now,
                        ),
                    )
                unconsumed = engine._terminal_resource_snapshot()
                self.assertEqual(
                    [authorization_id], unconsumed["remote_delete_authorization_ids"]
                )
                self.assertEqual(
                    [], unconsumed["remote_delete_authorization_consumptions"]
                )
                with store._write_transaction() as connection:
                    connection.execute(
                        "INSERT INTO authorization_uses(authorization_id, operation_id, used_at) "
                        "VALUES (?, ?, ?)",
                        (
                            authorization_id,
                            "git-nonprotected:GRANT-terminal-delete-001",
                            now,
                        ),
                    )
                consumed = engine._terminal_resource_snapshot()
                self.assertEqual(
                    ["git-nonprotected:GRANT-terminal-delete-001"],
                    consumed["remote_delete_authorization_consumptions"],
                )
            finally:
                store.close()

    def test_delivery_not_applicable_decisions_use_real_gates_and_complete(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "run-delivery-not-applicable"
            contract = {
                "release": "not_applicable",
                "deploy": "not_applicable",
                "environments": [],
            }
            target, invoke = self._delivery_cli_fixture(
                root,
                run_id=run_id,
                delivery_stages=contract,
            )
            states = self._drive_delivery_fixture(
                invoke,
                target=target,
                run_id=run_id,
                terminal_states={"COMPLETED"},
            )
            self.assertIn("RELEASE_READY", states)
            self.assertIn("RELEASE_VERIFIED", states)
            self.assertIn("DEPLOY_READY", states)
            self.assertEqual("COMPLETED", states[-1])
            identity = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                run = store.get_run(run_id)
                assert run is not None
                self.assertEqual(
                    contract,
                    run["payload"]["traceability"][
                        "required_delivery_stages"
                    ],
                )
                self.assertEqual(
                    "not_applicable",
                    store.get_gate(f"GATE-runtime-{identity}-600")["result"],
                )
                self.assertEqual(
                    "not_applicable",
                    store.get_gate(f"GATE-runtime-{identity}-700")["result"],
                )
                self.assertEqual(
                    "passed",
                    store.get_gate(f"GATE-runtime-{identity}-800")["result"],
                )
                events = store.list_events(run_id=run_id)
                transition_events = [
                    str(event["payload"]["rule"]["event"])
                    for event in events
                    if event["event_type"] == "STATE_TRANSITION"
                ]
                self.assertIn(
                    "SKIP_RELEASE_NOT_APPLICABLE", transition_events
                )
                self.assertIn(
                    "SKIP_DEPLOY_NOT_APPLICABLE", transition_events
                )
                self.assertIsNone(
                    store.get_operation(f"OP-runtime-{identity}-603")
                )
                self.assertIsNone(
                    store.get_operation(f"OP-runtime-{identity}-604")
                )
                self.assertIsNone(
                    store.get_operation(
                        f"OP-runtime-{identity}-env-000-703"
                    )
                )

    def test_successful_rollback_closes_resources_and_final_branch_cleanup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "run-rollback-success-terminal"
            target, invoke = self._delivery_cli_fixture(
                root,
                run_id=run_id,
                delivery_stages={
                    "release": "required",
                    "deploy": "required",
                    "environments": ["production"],
                },
                include_rollback_authorization=True,
                markers=("force-unhealthy",),
            )
            states = self._drive_delivery_fixture(
                invoke,
                target=target,
                run_id=run_id,
                terminal_states={"ROLLED_BACK", "ATTENTION_REQUIRED"},
            )
            self.assertEqual("ROLLED_BACK", states[-1])
            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                run = store.get_run(run_id)
                assert run is not None
                resolution = run["payload"]["runtime_terminal_resolution"]
                self.assertEqual("deleted", resolution["cleanup_result"])
                self.assertFalse(
                    any(
                        resolution["resources"][field]
                        for field in (
                            "live_lease_ids",
                            "active_attempt_ids",
                            "live_session_ids",
                            "live_workspace_paths",
                            "nonterminal_operation_ids",
                            "missing_cleanup_scopes",
                            "remote_delete_authorization_consumptions",
                        )
                    )
                )
                gate_event = next(
                    event
                    for event in store.list_events(run_id=run_id)
                    if event["event_type"] == "GATE_DECIDED"
                    and event["payload"]["gate_type"] == "POST_ROLLBACK_GATE"
                )
                gate = store.get_gate(gate_event["payload"]["gate_id"])
                assert gate is not None
                for prerequisite in (
                    "branch_cleanup_resolved",
                    "terminal_resources_closed",
                    "no_remote_cleanup_effect",
                ):
                    self.assertIn(prerequisite, gate["evaluated_prerequisites"])
                    self.assertTrue(gate["prerequisite_evidence"][prerequisite])
                branch = resolution["branch"]
                self.assertNotEqual(
                    0,
                    subprocess.run(
                        ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
                        cwd=target,
                        text=True,
                        capture_output=True,
                        check=False,
                    ).returncode,
                )

    def test_consumed_remote_delete_grant_blocks_terminal_cleanup_proof(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "run-terminal-remote-delete-consumed"
            target, invoke = self._delivery_cli_fixture(
                root,
                run_id=run_id,
                delivery_stages={
                    "release": "required",
                    "deploy": "required",
                    "environments": ["production"],
                },
            )
            for _ in range(40):
                state = invoke(
                    "run", "--target", str(target), "--run-id", run_id, "--once"
                )["state"]
                if state == "POST_DEPLOY_VERIFYING":
                    break
            else:
                self.fail("remote-delete fixture did not reach POST_DEPLOY_VERIFYING")
            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                run = store.get_run(run_id)
                assert run is not None
                branch = run["payload"]["runtime_candidate_branch"]
                now = datetime.now(UTC).isoformat()
                expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
                request_digest = "7" * 64
                authorization_id = "AUTH-terminal-consumed-delete-001"
                nonprotected_ref = {
                    "grant_id": "GRANT-terminal-consumed-delete-001",
                    "action": "delete_remote",
                    "remote": "origin",
                    "ref": f"refs/heads/{branch}",
                    "expected_sha": run["payload"]["runtime_candidate_commit"],
                    "force": False,
                    "one_time": True,
                    "expires_at": expires_at,
                }
                with store._write_transaction() as connection:
                    connection.execute(
                        "INSERT INTO authorization_requests("
                        "request_id, run_id, request_type, nonce, request_digest, "
                        "expected_revision, scope_json, expires_at, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            "REQUEST-terminal-consumed-delete-001",
                            run_id,
                            "grant",
                            "nonce-terminal-consumed-delete-request",
                            request_digest,
                            int(run["revision"]),
                            json.dumps({"nonprotected_ref": nonprotected_ref}),
                            expires_at,
                            now,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO authorization_records("
                        "authorization_id, record_type, run_id, request_digest, nonce, "
                        "authenticator_id, record_digest, record_json, issued_at, "
                        "expires_at, target_authorization_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            authorization_id,
                            "grant",
                            run_id,
                            request_digest,
                            "nonce-terminal-consumed-delete-record",
                            "fixture-admin",
                            "8" * 64,
                            json.dumps(
                                {
                                    "record_type": "grant",
                                    "grant_id": authorization_id,
                                    "run_id": run_id,
                                    "nonprotected_ref": nonprotected_ref,
                                }
                            ),
                            now,
                            expires_at,
                            None,
                            now,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO authorization_uses(authorization_id, operation_id, used_at) "
                        "VALUES (?, ?, ?)",
                        (
                            authorization_id,
                            "git-nonprotected:GRANT-terminal-consumed-delete-001",
                            now,
                        ),
                    )
            failed = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS / "nm_v6.py"),
                    "run",
                    "--target",
                    str(target),
                    "--run-id",
                    run_id,
                    "--once",
                ],
                cwd=target,
                env={**os.environ, "NM_V6_PYTHON": sys.executable},
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
            self.assertNotEqual(0, failed.returncode)
            self.assertIn("terminal resources remain live", failed.stderr)
            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                run = store.get_run(run_id)
                assert run is not None
                self.assertEqual("POST_DEPLOY_VERIFYING", run["state"])
                self.assertEqual(
                    run["payload"]["runtime_candidate_commit"],
                    self._git(target, "rev-parse", f"refs/heads/{branch}"),
                )

    def test_multiple_delivery_environments_are_ordered_and_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "run-multiple-delivery-environments"
            target, invoke = self._delivery_cli_fixture(
                root,
                run_id=run_id,
                delivery_stages={
                    "release": "required",
                    "deploy": "required",
                    "environments": ["staging", "production"],
                },
            )
            states = self._drive_delivery_fixture(
                invoke,
                target=target,
                run_id=run_id,
                terminal_states={"COMPLETED"},
            )
            self.assertEqual(2, states.count("DEPLOYING"))
            self.assertEqual(2, states.count("POST_DEPLOY_VERIFYING"))
            self.assertEqual("COMPLETED", states[-1])
            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                run = store.get_run(run_id)
                assert run is not None
                completed = run["payload"]["runtime_delivery_completed"]
                self.assertEqual(
                    ["staging", "production"],
                    [item["logical_key"] for item in completed],
                )
                self.assertEqual(
                    [0, 1],
                    [item["environment_index"] for item in completed],
                )
                operation_ids = [
                    item["deploy_operation_id"] for item in completed
                ]
                effect_ids = [item["deploy_effect_id"] for item in completed]
                deploy_gate_ids = [item["deploy_gate_id"] for item in completed]
                post_gate_ids = [
                    item["post_deploy_gate_id"] for item in completed
                ]
                self.assertEqual(2, len(set(operation_ids)))
                self.assertEqual(2, len(set(effect_ids)))
                self.assertEqual(2, len(set(deploy_gate_ids)))
                self.assertEqual(2, len(set(post_gate_ids)))
                for index, operation_id in enumerate(operation_ids):
                    self.assertIn(f"-env-{index:03d}-703", operation_id)
                    operation = store.get_operation(operation_id)
                    assert operation is not None
                    self.assertEqual(index, operation["scope"]["environment_index"])
                    self.assertEqual(
                        completed[index]["logical_key"],
                        operation["scope"]["environment_key"],
                    )
                events = store.list_events(run_id=run_id)
                continuations = [
                    event
                    for event in events
                    if event["event_type"] == "STATE_TRANSITION"
                    and event["payload"]["rule"]["event"]
                    == "CONTINUE_DEPLOYMENT"
                ]
                self.assertEqual(1, len(continuations))
                self.assertEqual(
                    1,
                    continuations[0]["payload"]["request"]["proposal"][
                        "payload"
                    ]["next_environment_index"],
                )

    def test_environment_mismatch_persists_evidence_and_requires_attention(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "run-delivery-environment-mismatch"
            target, invoke = self._delivery_cli_fixture(
                root,
                run_id=run_id,
                delivery_stages={
                    "release": "required",
                    "deploy": "required",
                    "environments": ["production"],
                },
                expected_identity="substituted-production",
            )
            states = self._drive_delivery_fixture(
                invoke,
                target=target,
                run_id=run_id,
                terminal_states={"ATTENTION_REQUIRED"},
            )
            self.assertEqual("ATTENTION_REQUIRED", states[-1])
            self.assertNotIn("DEPLOYING", states)
            identity = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                run = store.get_run(run_id)
                assert run is not None
                attention = run["payload"]["runtime_attention"]
                self.assertIn("environment identity", attention["reason"])
                self.assertTrue(attention["evidence_ids"])
                receipt = store.get_evidence(attention["evidence_ids"][0])
                assert receipt is not None
                self.assertIn("environment-mismatch", receipt["subject_ids"])
                self.assertIsNone(
                    store.get_operation(
                        f"OP-runtime-{identity}-env-000-703"
                    )
                )

    def test_rollback_authorization_and_verification_failures_require_attention(
        self,
    ) -> None:
        cases = (
            (
                "missing-authorization",
                False,
                ("force-unhealthy",),
                "authorization",
            ),
            (
                "mutation-failure",
                True,
                ("force-unhealthy", "force-rollback-failure"),
                "mutation",
            ),
            (
                "post-verification-failure",
                True,
                ("force-unhealthy", "force-post-rollback-failure"),
                "verification",
            ),
        )
        for case, include_rollback, markers, failure_stage in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_id = f"run-rollback-{case}"
                target, invoke = self._delivery_cli_fixture(
                    root,
                    run_id=run_id,
                    delivery_stages={
                        "release": "required",
                        "deploy": "required",
                        "environments": ["production"],
                    },
                    include_rollback_authorization=include_rollback,
                    markers=markers,
                )
                states = self._drive_delivery_fixture(
                    invoke,
                    target=target,
                    run_id=run_id,
                    terminal_states={"ATTENTION_REQUIRED"},
                )
                self.assertEqual("ATTENTION_REQUIRED", states[-1])
                if failure_stage != "authorization":
                    self.assertIn("ROLLBACK_REQUIRED", states)
                with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                    run = store.get_run(run_id)
                    assert run is not None
                    attention = run["payload"]["runtime_attention"]
                    self.assertTrue(attention["evidence_ids"])
                    self.assertTrue(
                        all(
                            store.get_evidence(evidence_id) is not None
                            for evidence_id in attention["evidence_ids"]
                        )
                    )
                    if failure_stage == "mutation":
                        self.assertIn("ROLLING_BACK", states)
                        self.assertNotIn("POST_ROLLBACK_VERIFYING", states)
                        self.assertIn("rollback failed", attention["reason"])
                        operation_id = (
                            f"OP-runtime-"
                            f"{hashlib.sha256(run_id.encode()).hexdigest()[:16]}"
                            "-env-000-723"
                        )
                        rollback_operation = store.get_operation(operation_id)
                        assert rollback_operation is not None
                        self.assertEqual("failed", rollback_operation["status"])
                    elif failure_stage == "verification":
                        self.assertIn("ROLLING_BACK", states)
                        self.assertIn("POST_ROLLBACK_VERIFYING", states)
                        self.assertIn("post-rollback", attention["reason"])
                        rollback_operation = store.get_operation(
                            run["payload"]["runtime_rollback_operation"]
                        )
                        assert rollback_operation is not None
                        self.assertEqual("completed", rollback_operation["status"])
                    else:
                        self.assertNotIn("ROLLING_BACK", states)
                        self.assertIn(
                            "without authorized rollback", attention["reason"]
                        )
                    self.assertNotIn(run["state"], {"COMPLETED", "ROLLED_BACK"})

    def test_candidate_branch_rejects_unowned_preexisting_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, engine, store = self._engine_fixture(
                root, run_id="run-candidate-injection"
            )
            try:
                injected = target / "injected.txt"
                injected.write_text("unowned\n", encoding="utf-8")
                self._git(target, "add", "injected.txt")
                self._git(
                    target,
                    "-c",
                    "user.name=NM V6 Test",
                    "-c",
                    "user.email=nm-v6-test@example.invalid",
                    "commit",
                    "-m",
                    "test: unowned candidate injection",
                )
                injected_commit = self._git(target, "rev-parse", "HEAD")
                self._git(
                    target,
                    "update-ref",
                    f"refs/heads/{engine._candidate_branch()}",
                    injected_commit,
                )
                with self.assertRaisesRegex(
                    RecoveryError, "pre-exists without controller-owned provenance"
                ):
                    engine._ensure_candidate_branch()
            finally:
                store.close()

    def test_failed_task_verification_does_not_advance_candidate_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, engine, store = self._engine_fixture(
                root, run_id="run-candidate-verification"
            )
            try:
                branch, base = engine._ensure_candidate_branch()
                phase = engine._phases()[0]
                task = engine._tasks()[0]
                definition = TaskDefinition(
                    str(task["id"]),
                    dependencies=(),
                    write_set=tuple(task["write_set"]),
                )
                graph = TaskGraph((definition,))
                scheduler = Scheduler(
                    graph,
                    ReducerLeaseAuthority(engine.reducer, run_id=engine.run_id),
                    max_workers=1,
                    lease_seconds=120,
                )
                task_entity_id = engine._entity_id(str(task["id"]))
                engine._ensure_entity(
                    "task",
                    task_entity_id,
                    initial_state="PLANNED",
                    payload={
                        "traceability_id": task["id"],
                        "phase_id": phase["id"],
                        "write_set": list(definition.write_set),
                    },
                )
                engine._entity_transition(
                    "task", task_entity_id, "MAKE_READY"
                )

                def candidate_result(
                    request: dict[str, Any], session_id: str
                ) -> dict[str, Any]:
                    workspace = Path(request["workspace"])
                    changed = workspace / "src/candidate.txt"
                    changed.parent.mkdir(parents=True, exist_ok=True)
                    changed.write_text("candidate\n", encoding="utf-8")
                    self._git(workspace, "add", "src/candidate.txt")
                    self._git(
                        workspace,
                        "-c",
                        "user.name=NM V6 Test",
                        "-c",
                        "user.email=nm-v6-test@example.invalid",
                        "commit",
                        "-m",
                        "test: adapter candidate",
                    )
                    return {
                        "protocol_version": "nm-v6/adapter-result-v1",
                        "operation_id": request["operation_id"],
                        "attempt_id": request["attempt_id"],
                        "status": "succeeded",
                        "session_id": session_id,
                        "candidate_commit": self._git(workspace, "rev-parse", "HEAD"),
                        "changed_paths": ["src/candidate.txt"],
                        "observations": [],
                        "requested_followups": [],
                        "usage": {},
                        "adapter_diagnostics": {"fixture": "candidate"},
                    }

                adapter = FakeAdapter(
                    backend=MemoryBackend(candidate_result)
                )
                with mock.patch(
                    "nmv6.runtime.create_adapter", return_value=adapter
                ), mock.patch.object(
                    engine,
                    "_execute",
                    side_effect=ContractError("forced verification failure"),
                ):
                    with self.assertRaisesRegex(
                        ContractError, "forced verification failure"
                    ):
                        engine._drive_task_attempt(
                            scheduler=scheduler,
                            definition=definition,
                            task=task,
                            phase=phase,
                            task_index=1,
                            branch=branch,
                            candidate=base,
                            accepted_paths={},
                            provider="fake",
                        )
                self.assertEqual(
                    base,
                    self._git(target, "rev-parse", f"refs/heads/{branch}"),
                )
                self.assertIsNone(
                    store.get_gate(engine._gate_id("TASK_GATE", offset=1))
                )
            finally:
                store.close()

    def test_expired_adapter_result_is_fenced_and_retried_with_new_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _target, engine, store = self._engine_fixture(
                root, run_id="run-expired-adapter-result"
            )
            try:
                branch, base = engine._ensure_candidate_branch()
                phase = engine._phases()[0]
                task = engine._tasks()[0]
                definition = TaskDefinition(
                    str(task["id"]),
                    dependencies=(),
                    write_set=tuple(task["write_set"]),
                )
                scheduler = Scheduler(
                    TaskGraph((definition,)),
                    ReducerLeaseAuthority(engine.reducer, run_id=engine.run_id),
                    max_workers=1,
                    lease_seconds=2,
                )
                task_entity_id = engine._entity_id(str(task["id"]))
                engine._ensure_entity(
                    "task",
                    task_entity_id,
                    initial_state="PLANNED",
                    payload={
                        "traceability_id": task["id"],
                        "phase_id": phase["id"],
                        "write_set": list(definition.write_set),
                    },
                )
                engine._entity_transition(
                    "task", task_entity_id, "MAKE_READY"
                )
                adapter = FakeAdapter(backend=MemoryBackend())

                def interrupt_after_result(name: str) -> None:
                    if name == "runtime.after_adapter_result_record":
                        raise RuntimeError("injected result-boundary interruption")

                with mock.patch(
                    "nmv6.runtime.create_adapter", return_value=adapter
                ), mock.patch(
                    "nmv6.runtime.checkpoint",
                    side_effect=interrupt_after_result,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "result-boundary interruption"
                    ):
                        engine._drive_task_attempt(
                            scheduler=scheduler,
                            definition=definition,
                            task=task,
                            phase=phase,
                            task_index=1,
                            branch=branch,
                            candidate=base,
                            accepted_paths={},
                            provider="fake",
                        )
                old_attempt, _old_operation = engine._attempt_identifiers(1, 0)
                self.assertEqual(
                    "RUNNING",
                    store.get_entity_state("attempt", old_attempt)["state"],
                )
                time.sleep(2.1)
                with mock.patch(
                    "nmv6.runtime.create_adapter", return_value=adapter
                ):
                    outcome = engine._drive_task_attempt(
                        scheduler=scheduler,
                        definition=definition,
                        task=task,
                        phase=phase,
                        task_index=1,
                        branch=branch,
                        candidate=base,
                        accepted_paths={},
                        provider="fake",
                    )
                self.assertIsNotNone(outcome)
                new_attempt, _new_operation = engine._attempt_identifiers(1, 1)
                old_entity = store.get_entity_state("attempt", old_attempt)
                new_entity = store.get_entity_state("attempt", new_attempt)
                self.assertEqual("LOST", old_entity["state"])
                self.assertEqual("SUCCEEDED", new_entity["state"])
                self.assertEqual(1, old_entity["payload"]["fencing_token"])
                self.assertEqual(2, new_entity["payload"]["fencing_token"])
                events = store.list_events(run_id=engine.run_id)
                self.assertEqual(
                    2,
                    sum(
                        event["event_type"] == "ADAPTER_REQUESTED"
                        for event in events
                    ),
                )
                self.assertEqual(
                    1,
                    sum(
                        event["event_type"] == "ADAPTER_ATTEMPT_STALE"
                        for event in events
                    ),
                )
            finally:
                store.close()

    def test_runtime_version_provider_schema_and_core_drift_fail_before_effects(
        self,
    ) -> None:
        for drift_kind in ("provider", "schema", "core"):
            with self.subTest(drift=drift_kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / "project"
                initialize_project(
                    target,
                    source_root=REPOSITORY,
                    project_name=f"Version Drift {drift_kind}",
                    package_name=f"version-drift-{drift_kind}",
                )
                remote = root / "remote.git"
                subprocess.run(
                    [
                        "git",
                        "clone",
                        "--bare",
                        "--no-local",
                        str(target),
                        str(remote),
                    ],
                    cwd=root,
                    check=True,
                    text=True,
                    capture_output=True,
                )
                head = self._git(target, "rev-parse", "HEAD")
                self._git(remote, "update-ref", "refs/heads/dev", head)
                self._git(remote, "update-ref", "refs/heads/main", head)
                self._git(target, "remote", "add", "origin", str(remote))
                tool_copy = root / "nm-v6-tool"
                shutil.copytree(
                    TOOLS,
                    tool_copy,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                run_id = f"run-version-drift-{drift_kind}"

                def tool(*arguments: str) -> subprocess.CompletedProcess[str]:
                    return subprocess.run(
                        [sys.executable, str(tool_copy / "nm_v6.py"), *arguments],
                        cwd=target,
                        env={**os.environ, "NM_V6_PYTHON": sys.executable},
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=120,
                    )

                planned = tool(
                    "plan", "--target", str(target), "--run-id", run_id
                )
                self.assertEqual(0, planned.returncode, msg=planned.stderr)
                with Store(target / ".nm/runtime/v6/state.sqlite3") as state:
                    before_events = len(state.list_events(run_id=run_id))
                    before_evidence = len(state.list_evidence(run_id))
                    baseline = state.get_run(run_id)["payload"]["version_baseline"]
                self.assertEqual(
                    "nm-v6/version-record-v1", baseline["schema_version"]
                )
                remote_before = {
                    branch: self._git(
                        remote, "rev-parse", f"refs/heads/{branch}"
                    )
                    for branch in ("dev", "main")
                }
                if drift_kind == "provider":
                    adapter_path = tool_copy / "nmv6/adapters.py"
                    source = adapter_path.read_text(encoding="utf-8")
                    changed = source.replace(
                        'adapter_version="nm-v6/fake-adapter-v1"',
                        'adapter_version="nm-v6/fake-adapter-v2"',
                        1,
                    )
                    self.assertNotEqual(source, changed)
                    adapter_path.write_text(changed, encoding="utf-8")
                elif drift_kind == "core":
                    init_path = tool_copy / "nmv6/__init__.py"
                    source = init_path.read_text(encoding="utf-8")
                    changed = source.replace(
                        '__version__ = "6.0.0-rc.1"',
                        '__version__ = "6.0.0-rc.9"',
                        1,
                    )
                    self.assertNotEqual(source, changed)
                    init_path.write_text(changed, encoding="utf-8")
                else:
                    (target / "0c-workflow/schemas/drift.schema.json").write_text(
                        json.dumps(
                            {
                                "$schema": "https://json-schema.org/draft/2020-12/schema",
                                "$id": "https://notmaster.dev/nm-v6/schemas/drift.schema.json",
                                "title": "Injected schema version drift",
                                "type": "object",
                                "required": [],
                                "properties": {},
                                "additionalProperties": False,
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                shutil.rmtree(
                    tool_copy / "nmv6/__pycache__", ignore_errors=True
                )
                failed = tool(
                    "run",
                    "--target",
                    str(target),
                    "--run-id",
                    run_id,
                    "--once",
                )
                self.assertNotEqual(0, failed.returncode)
                self.assertIn("version baseline drifted", failed.stderr)
                with Store(target / ".nm/runtime/v6/state.sqlite3") as state:
                    self.assertEqual(
                        before_events, len(state.list_events(run_id=run_id))
                    )
                    self.assertEqual(
                        before_evidence, len(state.list_evidence(run_id))
                    )
                self.assertEqual(
                    remote_before,
                    {
                        branch: self._git(
                            remote, "rev-parse", f"refs/heads/{branch}"
                        )
                        for branch in ("dev", "main")
                    },
                )
                self.assertFalse(
                    (target / ".nm-v6-fake-provider.json").exists()
                )
                self.assertFalse(
                    (target / ".nm/runtime/v6/adapter-sessions").exists()
                )

    def test_signed_plan_and_grant_drive_ordinary_run_to_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            initialize_project(
                target,
                source_root=REPOSITORY,
                project_name="Ordinary Runtime Fixture",
                package_name="ordinary-runtime-fixture",
            )
            private_key = root / "admin-private.pem"
            public_key = target / "0c-workflow/fixtures/fake-admin-public.pem"
            subprocess.run(
                ["openssl", "genrsa", "-out", str(private_key), "2048"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "openssl",
                    "rsa",
                    "-in",
                    str(private_key),
                    "-pubout",
                    "-out",
                    str(public_key),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            project_path = target / "project.json"
            project = json.loads(project_path.read_text(encoding="utf-8"))
            project["adapters"]["configured"] = ["fake"]
            project["git"]["merge_strategies"] = ["squash"]
            project_path.write_text(
                json.dumps(project, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            traceability_path = target / "0a-docs/0a-spec/traceability.json"
            traceability = json.loads(traceability_path.read_text(encoding="utf-8"))
            traceability["phases"].append(
                {
                    "id": "PHASE-002",
                    "title": "Second example phase",
                    "depends_on": ["PHASE-001"],
                }
            )
            traceability["tasks"].append(
                {
                    "id": "TASK-002",
                    "phase_id": "PHASE-002",
                    "acceptance_ids": ["AC-001"],
                    "enabling_requirement_ids": [],
                    "depends_on": ["TASK-001"],
                    "write_set": ["docs/**"],
                    "optional": False,
                }
            )
            traceability_path.write_text(
                json.dumps(traceability, indent=2) + "\n", encoding="utf-8"
            )
            self._git(
                target,
                "add",
                "project.json",
                str(public_key.relative_to(target)),
                str(traceability_path.relative_to(target)),
            )
            self._git(
                target,
                "-c",
                "user.name=NM V6 Test",
                "-c",
                "user.email=nm-v6-test@example.invalid",
                "commit",
                "-m",
                "test: configure signed ordinary runtime fixture",
            )
            remote = root / "remote.git"
            subprocess.run(
                ["git", "clone", "--bare", "--no-local", str(target), str(remote)],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            )
            head = self._git(target, "rev-parse", "HEAD")
            self._git(remote, "update-ref", "refs/heads/dev", head)
            self._git(remote, "update-ref", "refs/heads/main", head)
            self._git(target, "remote", "add", "origin", str(remote))

            run_id = "run-ordinary-runtime"

            def invoke(*arguments: str) -> dict[str, Any]:
                completed = subprocess.run(
                    [sys.executable, str(TOOLS / "nm_v6.py"), *arguments],
                    cwd=target,
                    env={**os.environ, "NM_V6_PYTHON": sys.executable},
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
                if completed.returncode != 0:
                    with Store(target / ".nm/runtime/v6/state.sqlite3") as failed_store:
                        failed_run = failed_store.get_run(run_id)
                        failed_events = failed_store.list_events(run_id=run_id)[-3:]
                    self.fail(
                        completed.stderr
                        + "\nrun="
                        + repr(failed_run)
                        + "\nevents="
                        + repr(failed_events)
                    )
                return json.loads(completed.stdout)

            planned = invoke(
                "plan", "--target", str(target), "--run-id", run_id
            )
            self.assertEqual("SPEC_REVIEW", planned["state"])
            expiry = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
            confirmation_request = invoke(
                "spec",
                "confirmation",
                "request",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--expires-at",
                expiry,
            )["request"]
            confirmation = self._sign(
                root,
                private_key,
                "confirmation",
                {
                    "record_type": "spec_confirmation",
                    "confirmation_id": "AUTH-ordinary-confirm-001",
                    "spec_id": "SPEC-EXAMPLE-V1",
                    "version": 1,
                    "spec_hash": confirmation_request["spec_hash"],
                    "decision": "confirmed",
                    "administrator_identity": "fixture-administrator",
                    "issued_at": datetime.now(UTC).isoformat(),
                    "nonce": confirmation_request["nonce"],
                    "authenticator_id": "fixture-admin",
                },
            )
            confirmation_path = root / "confirmation.json"
            confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")
            invoke(
                "spec",
                "confirm",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--record",
                str(confirmation_path),
            )
            for expected in ("SPEC_CONFIRMED", "PLANNING", "READY"):
                result = invoke(
                    "run",
                    "--target",
                    str(target),
                    "--run-id",
                    run_id,
                    "--once",
                )
                self.assertEqual(expected, result["state"])

            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                current = store.get_run(run_id)
                self.assertIsNotNone(current)
                scope = {
                    "run_id": run_id,
                    "spec_hash": current["spec_hash"],
                    "config_hash": current["config_hash"],
                    "allowed_actions": [
                        "mode_set_auto",
                        "integrate_dev",
                        "release",
                        "publish",
                        "deploy",
                        "rollback",
                        "cancel",
                    ],
                    "allowed_environments": ["project-production"],
                    "allowed_protected_refs": ["dev", "main"],
                }
            scope_path = root / "scope.json"
            scope_path.write_text(json.dumps(scope), encoding="utf-8")
            grant_request = invoke(
                "authorize",
                "request",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--scope",
                str(scope_path),
                "--expires-at",
                expiry,
            )["request"]
            grant = self._sign(
                root,
                private_key,
                "grant",
                {
                    "record_type": "grant",
                    "grant_id": "AUTH-ordinary-grant-002",
                    **scope,
                    "created_by": "fixture-administrator",
                    "created_at": datetime.now(UTC).isoformat(),
                    "expires_at": expiry,
                    "request_digest": grant_request["request_digest"],
                    "nonce": grant_request["nonce"],
                    "grant_revision": grant_request["expected_revision"],
                    "authenticator_id": "fixture-admin",
                    "one_time": False,
                },
            )
            grant_path = root / "grant.json"
            grant_path.write_text(json.dumps(grant), encoding="utf-8")
            invoke(
                "authorize",
                "approve",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--record",
                str(grant_path),
            )
            invoke(
                "mode",
                "set",
                "auto",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--grant-id",
                grant["grant_id"],
            )
            def crash_once(failpoint: str) -> None:
                crashed = subprocess.run(
                    [
                        sys.executable,
                        str(TOOLS / "nm_v6.py"),
                        "run",
                        "--target",
                        str(target),
                        "--run-id",
                        run_id,
                        "--once",
                    ],
                    cwd=target,
                    env={
                        **os.environ,
                        "NM_V6_PYTHON": sys.executable,
                        "NM_V6_FAILPOINT": failpoint,
                        "NM_V6_FAILPOINT_ACTION": "sigkill",
                    },
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
                self.assertNotEqual(0, crashed.returncode)

            def run_once_expect_failure() -> subprocess.CompletedProcess[str]:
                failed = subprocess.run(
                    [
                        sys.executable,
                        str(TOOLS / "nm_v6.py"),
                        "run",
                        "--target",
                        str(target),
                        "--run-id",
                        run_id,
                        "--once",
                    ],
                    cwd=target,
                    env={**os.environ, "NM_V6_PYTHON": sys.executable},
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
                self.assertNotEqual(0, failed.returncode)
                return failed

            def task_evidence_blob(task_id: str) -> Path:
                with Store(target / ".nm/runtime/v6/state.sqlite3") as state:
                    receipt = next(
                        item
                        for item in state.list_evidence(run_id)
                        if task_id in item.get("subject_ids", [])
                        and item.get("attempt_id") is not None
                    )
                return EvidenceStore(
                    target / ".nm/runtime/v6/evidence"
                ).blob_path(str(receipt["stdout_digest"]))

            advanced = invoke(
                "run",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--once",
            )
            self.assertEqual("IMPLEMENTING", advanced["state"])
            crash_once("runtime.after_adapter_session_start")
            self.assertEqual(
                "IMPLEMENTING",
                invoke(
                    "status", "--target", str(target), "--run-id", run_id, "--json"
                )["state"],
            )
            crash_once("runtime.after_adapter_result_record")
            self.assertEqual(
                "IMPLEMENTING",
                invoke(
                    "status", "--target", str(target), "--run-id", run_id, "--json"
                )["state"],
            )
            advanced = invoke(
                "run",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--once",
            )
            self.assertEqual("PHASE_VERIFYING", advanced["state"])
            crash_once("runtime.after_merge_reviewer_result_record")
            self.assertEqual(
                "PHASE_VERIFYING",
                invoke(
                    "status", "--target", str(target), "--run-id", run_id, "--json"
                )["state"],
            )
            crash_once("runtime.after_merge_proposed_record")
            self.assertEqual(
                "PHASE_VERIFYING",
                invoke(
                    "status", "--target", str(target), "--run-id", run_id, "--json"
                )["state"],
            )
            advanced = invoke(
                "run",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--once",
            )
            self.assertEqual("INTEGRATING_DEV", advanced["state"])

            first_task_blob = task_evidence_blob("TASK-001")
            first_task_bytes = first_task_blob.read_bytes()
            dev_before_missing_evidence = self._git(
                remote, "rev-parse", "refs/heads/dev"
            )
            first_task_blob.unlink()
            missing_task = run_once_expect_failure()
            self.assertIn("evidence", missing_task.stderr.lower())
            self.assertEqual(
                dev_before_missing_evidence,
                self._git(remote, "rev-parse", "refs/heads/dev"),
            )
            first_task_blob.write_bytes(first_task_bytes)
            crash_once("git.after_protected_push")
            self.assertEqual(
                "INTEGRATING_DEV",
                invoke(
                    "status", "--target", str(target), "--run-id", run_id, "--json"
                )["state"],
            )
            advanced = invoke(
                "run", "--target", str(target), "--run-id", run_id, "--once"
            )
            self.assertEqual("INTEGRATION_VERIFYING", advanced["state"])
            crash_once("runtime.after_cleanup_reviewer_session_record")
            self.assertEqual(
                "INTEGRATION_VERIFYING",
                invoke(
                    "status", "--target", str(target), "--run-id", run_id, "--json"
                )["state"],
            )
            for expected in (
                "IMPLEMENTING",
                "PHASE_VERIFYING",
                "INTEGRATING_DEV",
                "INTEGRATION_VERIFYING",
                "RELEASE_READY",
                "RELEASING",
            ):
                advanced = invoke(
                    "run", "--target", str(target), "--run-id", run_id, "--once"
                )
                self.assertEqual(expected, advanced["state"])
            crash_once("runtime.after_release_publish")
            self.assertEqual(
                "RELEASING",
                invoke(
                    "status", "--target", str(target), "--run-id", run_id, "--json"
                )["state"],
            )
            for expected in ("RELEASE_VERIFIED", "DEPLOY_READY", "DEPLOYING"):
                advanced = invoke(
                    "run", "--target", str(target), "--run-id", run_id, "--once"
                )
                self.assertEqual(expected, advanced["state"])
            crash_once("runtime.after_deploy_observation")
            self.assertEqual(
                "DEPLOYING",
                invoke(
                    "status", "--target", str(target), "--run-id", run_id, "--json"
                )["state"],
            )
            deployed = invoke(
                "run",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--once",
            )
            self.assertEqual("POST_DEPLOY_VERIFYING", deployed["state"])
            with Store(target / ".nm/runtime/v6/state.sqlite3") as state:
                terminal_payload = state.get_run(run_id)["payload"]
                terminal_branch = terminal_payload["runtime_candidate_branch"]
                terminal_head = terminal_payload["runtime_candidate_commit"]
            self._git(
                target,
                "push",
                "origin",
                f"{terminal_head}:refs/heads/{terminal_branch}",
            )
            crash_once("runtime.before_cleanup_local_delete")
            self.assertEqual(
                terminal_head,
                self._git(target, "rev-parse", f"refs/heads/{terminal_branch}"),
            )
            crash_once("runtime.after_cleanup_local_delete")
            self.assertNotEqual(
                0,
                subprocess.run(
                    [
                        "git",
                        "rev-parse",
                        "--verify",
                        f"refs/heads/{terminal_branch}",
                    ],
                    cwd=target,
                    text=True,
                    capture_output=True,
                    check=False,
                ).returncode,
            )
            self.assertEqual(
                terminal_head,
                self._git(
                    remote, "rev-parse", f"refs/heads/{terminal_branch}"
                ),
            )
            completion_blob = task_evidence_blob("TASK-001")
            completion_bytes = completion_blob.read_bytes()
            completion_blob.unlink()
            missing_completion = run_once_expect_failure()
            self.assertIn("evidence", missing_completion.stderr.lower())
            completion_blob.write_bytes(completion_bytes)
            completed = invoke(
                "run", "--target", str(target), "--run-id", run_id
            )
            self.assertEqual("COMPLETED", completed["state"])
            self.assertNotEqual(
                self._git(remote, "rev-parse", "refs/heads/dev"),
                self._git(remote, "rev-parse", "refs/heads/main"),
            )
            self.assertEqual(
                self._git(remote, "rev-parse", "refs/heads/dev^{tree}"),
                self._git(remote, "rev-parse", "refs/heads/main^{tree}"),
            )
            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                events = store.list_events(run_id=run_id)
                persisted_baseline = store.get_run(run_id)["payload"][
                    "version_baseline"
                ]
                runtime_evidence = store.list_evidence(run_id)
                self.assertTrue(runtime_evidence)
                self.assertTrue(
                    all(
                        receipt["tool_versions"] == persisted_baseline
                        and receipt["evaluator_version"]
                        == persisted_baseline["evaluator"]
                        for receipt in runtime_evidence
                    )
                )
                self.assertEqual(
                    9,
                    sum(
                        event["event_type"] == "ADAPTER_REQUESTED"
                        for event in events
                    ),
                )
                self.assertEqual(
                    9,
                    sum(
                        event["event_type"] == "ADAPTER_SESSION_RECORDED"
                        for event in events
                    ),
                )
                self.assertEqual(
                    9,
                    sum(
                        event["event_type"] == "ADAPTER_RESULT_RECORDED"
                        for event in events
                    ),
                )
                self.assertEqual(
                    "INTEGRATED",
                    store.get_entity_state(
                        "task",
                        f"{__import__('hashlib').sha256(run_id.encode()).hexdigest()[:16]}.TASK-001",
                    )["state"],
                )
                reviewer_requests = [
                    event["payload"]["record"]
                    for event in events
                    if event["event_type"] == "ADAPTER_REQUESTED"
                    and event["payload"].get("record", {}).get("role")
                    == "merge_reviewer"
                ]
                self.assertEqual(
                    ["work_to_dev", "work_to_dev", "dev_to_stable"],
                    [record["route"] for record in reviewer_requests],
                )
                merge_records = [
                    event["payload"]["record"]
                    for event in events
                    if event["event_type"] == "MERGE_PROPOSED"
                ]
                self.assertEqual(
                    ["work_to_dev", "work_to_dev", "dev_to_stable"],
                    [record["route"] for record in merge_records],
                )
                cleanup_records = [
                    event["payload"]["record"]
                    for event in events
                    if event["event_type"] == "BRANCH_CLEANUP_DECIDED"
                    and event["payload"].get("record", {}).get("record_kind")
                    == "reviewer_provenance"
                ]
                self.assertEqual(
                    [
                        "cleanup-work-to-dev-p001",
                        "cleanup-work-to-dev-p002",
                        "cleanup-dev-to-stable",
                        "cleanup-work-final",
                    ],
                    [record["review_scope"] for record in cleanup_records],
                )
                self.assertEqual(
                    ["retain", "retain", "retain", "delete_local"],
                    [record["core_decision"]["result"] for record in cleanup_records],
                )
                candidate_branch = store.get_run(run_id)["payload"][
                    "runtime_candidate_branch"
                ]
                self.assertIsNone(
                    subprocess.run(
                        [
                            "git",
                            "rev-parse",
                            "--verify",
                            f"refs/heads/{candidate_branch}",
                        ],
                        cwd=target,
                        text=True,
                        capture_output=True,
                        check=False,
                    ).stdout.strip()
                    or None
                )
                for request in reviewer_requests:
                    attempt_id = request["attempt_id"]
                    self.assertEqual(
                        "SUCCEEDED",
                        store.get_entity_state("attempt", attempt_id)["state"],
                    )
                    self.assertEqual(
                        1,
                        sum(
                            event["event_type"] == "ADAPTER_SESSION_RECORDED"
                            and event["payload"].get("record", {}).get(
                                "attempt_id"
                            )
                            == attempt_id
                            for event in events
                        ),
                    )
                    self.assertEqual(
                        1,
                        sum(
                            event["event_type"] == "ADAPTER_RESULT_RECORDED"
                            and event["payload"].get("record", {}).get(
                                "attempt_id"
                            )
                            == attempt_id
                            for event in events
                        ),
                    )
            self.assertEqual(
                9,
                len(
                    list(
                        (
                            target / ".nm/runtime/v6/adapter-sessions"
                        ).glob("SESSION-*")
                    )
                ),
            )
            with Store(target / ".nm/runtime/v6/state.sqlite3") as state:
                session_records = [
                    event["payload"]["record"]
                    for event in state.list_events(run_id=run_id)
                    if event["event_type"] == "ADAPTER_SESSION_RECORDED"
                ]
            self.assertEqual(9, len(session_records))
            for record in session_records:
                session_root = (
                    target
                    / ".nm/runtime/v6/adapter-sessions"
                    / record["session_id"]
                )
                self.assertTrue((session_root / "session.json").is_file())
                self.assertTrue((session_root / "result.json").is_file())
            drifted_traceability = json.loads(
                traceability_path.read_text(encoding="utf-8")
            )
            drifted_traceability["goals"][0]["statement"] += " Drifted."
            traceability_path.write_text(
                json.dumps(drifted_traceability, indent=2) + "\n",
                encoding="utf-8",
            )
            drifted = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS / "nm_v6.py"),
                    "run",
                    "--target",
                    str(target),
                    "--run-id",
                    run_id,
                    "--once",
                ],
                cwd=target,
                env={**os.environ, "NM_V6_PYTHON": sys.executable},
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
            self.assertNotEqual(0, drifted.returncode)
            self.assertIn("traceability inputs changed", drifted.stderr)


if __name__ == "__main__":
    unittest.main()
