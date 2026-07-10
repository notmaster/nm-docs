from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from unittest.mock import patch


TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from nmv6.actions import (  # noqa: E402
    ACTION_RESULT_SCHEMA,
    ActionDefinition,
    ActionExecutor,
    SecretValue,
    validate_action_registry,
)
from nmv6.controller import (  # noqa: E402
    FailureClass,
    RetryPolicy,
    WorkflowController,
    decide_retry,
)
from nmv6.delivery import DeliveryController, EnvironmentTarget, ReleaseSource  # noqa: E402
from nmv6.errors import (  # noqa: E402
    ActionError,
    ContractError,
    GitPolicyError,
    RecoveryError,
    TransitionError,
)
from nmv6.failpoints import FailpointError  # noqa: E402
from nmv6.git_controller import (  # noqa: E402
    CanonicalCleanupSnapshot,
    CleanupFacts,
    GitController,
    MergeReceipt,
)
from nmv6.merge_review import (  # noqa: E402
    OBSERVATION_SCHEMA_VERSION,
    deterministic_fake_merge_review,
    seal_merge_review_observation,
)
from nmv6.recovery import RecoveryController  # noqa: E402
from nmv6.scheduler import Lease, Scheduler, TaskDefinition, TaskGraph  # noqa: E402
from nmv6.workspace import (  # noqa: E402
    IsolatedCommand,
    Workspace,
    WorkspaceManager,
    detect_isolation_backend,
)


class TestIsolationBackend:
    """A test-only backend; production detection never selects this class."""

    name = "test-isolation"

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


class FakeRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []
        self.operations: dict[str, dict[str, Any]] = {}

    def begin_operation(
        self,
        *,
        operation_id: str,
        action_id: str,
        idempotency_key: str,
        grant_id: str | None,
        grant_revision: int | None,
    ) -> Mapping[str, Any]:
        self.events.append(("begin", operation_id, action_id))
        existing = self.operations.get(operation_id)
        if existing is not None:
            if existing["idempotency_key"] != idempotency_key:
                raise TransitionError("idempotency conflict")
            return {**existing, "_replayed": True}
        value = {
            "operation_id": operation_id,
            "action_id": action_id,
            "idempotency_key": idempotency_key,
            "grant_id": grant_id,
            "grant_revision": grant_revision,
            "status": "started",
        }
        self.operations[operation_id] = value
        return {**value, "_replayed": False}

    def finish_operation(
        self,
        *,
        operation_id: str,
        status: str,
        result: Mapping[str, Any] | None,
        error: str | None,
    ) -> Mapping[str, Any]:
        action = str(result.get("action_id", "unknown")) if result else "unknown"
        self.events.append(("finish", operation_id, action))
        value = self.operations.setdefault(operation_id, {"operation_id": operation_id})
        value.update({"status": status, "result": dict(result or {}), "error": error})
        return value

    def get_operation(self, operation_id: str) -> Mapping[str, Any] | None:
        return self.operations.get(operation_id)


class FakeLeaseAuthority:
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
        if task_id in self.current and not self.current[task_id].expired():
            raise TransitionError("already leased")
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
        lease = Lease(
            task_id,
            owner,
            current.attempt_id,
            fencing_token,
            (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat(),
            expected_revision + 1,
        )
        self.current[task_id] = lease
        return lease

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


class FixtureProtectedAuthority:
    """Explicit test boundary; production Git uses the SQLite-backed resolver."""

    def require_proposal(
        self,
        proposal: Any,
        *,
        action: str,
        protected_ref: str,
        required_gate_type: str,
    ) -> None:
        if not proposal.gate_ids or not proposal.authorization_id:
            raise GitPolicyError("fixture proposal lacks gate or authorization")
        if not action or not protected_ref or not required_gate_type:
            raise GitPolicyError("fixture authority request is incomplete")

    def require_hotfix_creation(
        self,
        *,
        branch: str,
        stable_commit: str,
        protected_ref: str,
        authorization_id: str,
    ) -> None:
        if not all((branch, stable_commit, protected_ref, authorization_id)):
            raise GitPolicyError("fixture hotfix authority request is incomplete")


class FixtureCleanupAuthority:
    """Test-only canonical cleanup authority for Git mechanics fixtures."""

    _CLOSED = (
        "review_responsibility_closed",
        "backup_retention_absent",
        "dependent_work_closed",
        "release_responsibility_closed",
        "rollback_responsibility_closed",
        "audit_retention_absent",
        "explicit_retention_absent",
    )

    def snapshot(
        self, *, run_id: str | None, branch: str, head: str
    ) -> CanonicalCleanupSnapshot:
        del branch, head
        return CanonicalCleanupSnapshot(
            run_id=run_id,
            input_revision=0 if run_id is not None else None,
            responsibility_evidence_id="EVID-fixture-cleanup-001",
            responsibility_assertions=tuple((name, True) for name in self._CLOSED),
        )

    def record(
        self,
        *,
        run_id: str,
        input_revision: int,
        record: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        del run_id, input_revision, record, idempotency_key
        return {}


def action_mapping(
    action_id: str,
    kind: str,
    argv: list[str],
    *,
    core_env: list[str] | None = None,
    secret_refs: list[str] | None = None,
    observe: str | None = None,
    reconcile: str | None = None,
) -> dict[str, Any]:
    if kind == "external_mutation":
        idempotency: Any = {
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
        "argv": argv,
        "cwd": ".",
        "timeout_seconds": 10,
        "accepted_exit_codes": [0],
        "env_allowlist": [],
        "core_injected_env": core_env or [],
        "secret_refs": secret_refs or [],
        "result_schema": ACTION_RESULT_SCHEMA,
        "idempotency": idempotency,
        "observe_action_id": observe,
        "reconcile_action_id": reconcile,
    }


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def create_git_fixture(root: Path) -> tuple[Path, Path, GitController, str]:
    remote = root / "remote.git"
    seed = root / "seed"
    checkout = root / "checkout"
    git("init", "--bare", str(remote), cwd=root)
    seed.mkdir()
    git("init", "-b", "main", cwd=seed)
    git("config", "user.name", "Test", cwd=seed)
    git("config", "user.email", "test@example.invalid", cwd=seed)
    (seed / "base.txt").write_text("base\n", encoding="utf-8")
    git("add", "base.txt", cwd=seed)
    git("commit", "-m", "base", cwd=seed)
    base = git("rev-parse", "HEAD", cwd=seed)
    git("remote", "add", "origin", str(remote), cwd=seed)
    git("push", "origin", "main", cwd=seed)
    git("branch", "dev", cwd=seed)
    git("push", "origin", "dev", cwd=seed)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
    git("clone", str(remote), str(checkout), cwd=root)
    git("config", "user.name", "Test", cwd=checkout)
    git("config", "user.email", "test@example.invalid", cwd=checkout)
    return remote, checkout, GitController(
        checkout,
        protected_authority=FixtureProtectedAuthority(),
        cleanup_authority=FixtureCleanupAuthority(),
    ), base


class ActionAndWorkspaceTests(unittest.TestCase):
    def test_action_is_persisted_before_minimal_secret_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = (
                "import json,os;"
                "t='2026-01-01T00:00:00Z';"
                "print(json.dumps({'protocol_version':'nm-v6/action-result-v1',"
                "'action_id':'deploy','operation_id':os.environ.get('NM_V6_OPERATION_ID'),"
                "'status':'succeeded','effect_id':'effect-1','artifact_digest':None,"
                "'environment_id':None,'environment_fingerprint':None,"
                "'observed_state':{'ambient_credentials_absent':all("
                "os.environ.get(name) is None for name in "
                "('DELIVERY_TOKEN','AWS_SECRET_ACCESS_KEY','SSH_AUTH_SOCK')),"
                "'secret_present':os.environ.get('DEPLOY_TOKEN') is not None},"
                "'started_at':t,'finished_at':t,'diagnostics':{},'redactions':[]}))"
            )
            definition = ActionDefinition.from_mapping(
                action_mapping(
                    "deploy",
                    "external_mutation",
                    [sys.executable, "-c", code],
                    core_env=["NM_V6_OPERATION_ID"],
                    secret_refs=["deploy-token"],
                    observe="observe",
                    reconcile="reconcile",
                )
            )
            recorder = FakeRecorder()
            executor = ActionExecutor(
                isolation_backend=TestIsolationBackend(),
                environment={
                    "PATH": os.environ["PATH"],
                    "DELIVERY_TOKEN": "do-not-leak",
                    "AWS_SECRET_ACCESS_KEY": "do-not-leak",
                    "SSH_AUTH_SOCK": "/tmp/do-not-inherit",
                },
                secret_resolver=lambda reference: SecretValue(
                    reference, "DEPLOY_TOKEN", "fake-secret-value"
                ),
            )
            result = executor.execute(
                definition,
                workspace=root,
                operation_id="OP-test-001",
                recorder=recorder,
                grant_id="AUTH-test-001",
                grant_revision=1,
            )
            self.assertEqual(result.status, "succeeded")
            self.assertTrue(result.observed_state["ambient_credentials_absent"])
            self.assertTrue(result.observed_state["secret_present"])
            self.assertEqual(recorder.events[0], ("begin", "OP-test-001", "deploy"))
            self.assertEqual(recorder.operations["OP-test-001"]["status"], "partial")

    def test_action_contract_rejects_shell_interpolation_and_secret_output(self) -> None:
        valid = action_mapping("verify", "pure", ["verify"])
        valid["env_allowlist"] = [
            "PATH",
            "LANG",
            "LC_ALL",
            "TZ",
            "TERM",
            "NO_COLOR",
            "CI",
        ]
        ActionDefinition.from_mapping(valid)
        for environment_name in (
            "DELIVERY_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "SSH_AUTH_SOCK",
        ):
            with self.subTest(sensitive_environment=environment_name):
                invalid_environment = action_mapping("verify", "pure", ["verify"])
                invalid_environment["env_allowlist"] = [environment_name]
                with self.assertRaisesRegex(ContractError, "secret_refs"):
                    ActionDefinition.from_mapping(invalid_environment)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = (
                "import json,os;"
                "t='2026-01-01T00:00:00Z';"
                "names=('DELIVERY_TOKEN','AWS_SECRET_ACCESS_KEY','SSH_AUTH_SOCK');"
                "print(json.dumps({'protocol_version':'nm-v6/action-result-v1',"
                "'action_id':'verify','operation_id':None,'status':'succeeded',"
                "'effect_id':None,'artifact_digest':None,'environment_id':None,"
                "'environment_fingerprint':None,'observed_state':{"
                "'inherited':[name for name in names if name in os.environ]},"
                "'started_at':t,'finished_at':t,'diagnostics':{},'redactions':[]}))"
            )
            definition = ActionDefinition.from_mapping(
                action_mapping("verify", "pure", [sys.executable, "-c", code])
            )
            executor = ActionExecutor(
                isolation_backend=TestIsolationBackend(),
                environment={
                    "PATH": os.environ["PATH"],
                    "DELIVERY_TOKEN": "ambient",
                    "AWS_SECRET_ACCESS_KEY": "ambient",
                    "SSH_AUTH_SOCK": "/tmp/ambient-agent",
                },
            )
            result = executor.execute(definition, workspace=root, operation_id=None)
            self.assertEqual([], result.observed_state["inherited"])
            for environment_name in (
                "DELIVERY_TOKEN",
                "AWS_SECRET_ACCESS_KEY",
                "SSH_AUTH_SOCK",
            ):
                with self.subTest(tampered_definition=environment_name):
                    tampered = replace(
                        definition,
                        env_allowlist=(environment_name,),
                    )
                    with self.assertRaisesRegex(
                        ActionError,
                        "cannot inherit sensitive or unsupported",
                    ):
                        executor.execute(tampered, workspace=root, operation_id=None)

        invalid = action_mapping("build", "pure", ["echo", "$(unsafe)"])
        with self.assertRaises(ContractError):
            ActionDefinition.from_mapping(invalid)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = (
                "import json,os;"
                "t='2026-01-01T00:00:00Z';"
                "print(os.environ['TOKEN']);"
                "print(json.dumps({'protocol_version':'nm-v6/action-result-v1',"
                "'action_id':'observe','operation_id':None,'status':'succeeded',"
                "'effect_id':None,'artifact_digest':None,'environment_id':None,"
                "'environment_fingerprint':None,'observed_state':{},'started_at':t,"
                "'finished_at':t,'diagnostics':{},'redactions':[]}))"
            )
            definition = ActionDefinition.from_mapping(
                action_mapping(
                    "observe",
                    "external_observe",
                    [sys.executable, "-c", code],
                    secret_refs=["token"],
                )
            )
            executor = ActionExecutor(
                isolation_backend=TestIsolationBackend(),
                secret_resolver=lambda reference: SecretValue(reference, "TOKEN", "secret-value"),
            )
            with self.assertRaises(ActionError):
                executor.execute(definition, workspace=root, operation_id=None)

    def test_workspace_is_standalone_clone_without_remote(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            git("init", "-b", "main", cwd=source)
            git("config", "user.name", "Test", cwd=source)
            git("config", "user.email", "test@example.invalid", cwd=source)
            (source / "README.md").write_text("fixture\n", encoding="utf-8")
            git("add", "README.md", cwd=source)
            git("commit", "-m", "fixture", cwd=source)
            commit = git("rev-parse", "HEAD", cwd=source)
            manager = WorkspaceManager(
                source,
                root / "workspaces",
                isolation_backend=TestIsolationBackend(),
            )
            workspace = manager.create("attempt-1", commit=commit, branch="feature/work")
            self.assertEqual(git("rev-parse", "HEAD", cwd=workspace.path), commit)
            self.assertEqual(git("remote", cwd=workspace.path), "")
            self.assertFalse((workspace.path / ".git" / "objects" / "info" / "alternates").exists())
            manager.dispose(workspace)
            self.assertFalse(workspace.path.exists())

    def test_detected_os_sandbox_cannot_read_sibling_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            secret = root / "fake-secret"
            secret.write_text("must-not-be-readable", encoding="utf-8")
            backend = detect_isolation_backend(denied_read_roots=(secret,))
            if backend is None:
                self.skipTest("supported OS sandbox backend is unavailable (production fails closed)")
            isolated = backend.wrap(
                ["/bin/cat", str(secret)],
                workspace=workspace,
                cwd=workspace,
                allow_network=False,
            )
            result = subprocess.run(
                list(isolated.argv),
                cwd=isolated.cwd,
                env={"PATH": "/usr/bin:/bin", "LANG": "C"},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("must-not-be-readable", result.stdout + result.stderr)


class SchedulerTests(unittest.TestCase):
    def test_dag_lease_fencing_and_write_conflicts(self) -> None:
        graph = TaskGraph(
            (
                TaskDefinition("TASK-001", write_set=("src/a",)),
                TaskDefinition("TASK-002", dependencies=("TASK-001",), write_set=("src/b",)),
                TaskDefinition("TASK-003", write_set=("docs/**",)),
                TaskDefinition("TASK-004", write_set=("src/a/generated",)),
            )
        )
        authority = FakeLeaseAuthority()
        scheduler = Scheduler(graph, authority, max_workers=3, lease_seconds=30)
        selected = scheduler.select(completed=(), active={})
        self.assertEqual(tuple(task.task_id for task in selected), ("TASK-001", "TASK-003"))
        lease = scheduler.acquire(
            "TASK-001", owner="worker-1", attempt_id="ATTEMPT-run-001", expected_revision=1
        )
        Scheduler.validate_result(
            task_id="TASK-001",
            owner="worker-1",
            fencing_token=lease.fencing_token,
            lease=lease,
        )
        with self.assertRaises(TransitionError):
            Scheduler.validate_result(
                task_id="TASK-001",
                owner="worker-1",
                fencing_token=lease.fencing_token + 1,
                lease=lease,
            )
        paths = scheduler.assert_actual_diff_isolated(
            "TASK-001", ["src/a/module.py"], {"TASK-003": ["docs/index.md"]}
        )
        self.assertEqual(paths, ("src/a/module.py",))
        with self.assertRaises(TransitionError):
            scheduler.assert_actual_diff_isolated(
                "TASK-001", ["src/a/module.py"], {"TASK-004": ["src/a/module.py"]}
            )

    def test_cycle_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            TaskGraph(
                (
                    TaskDefinition("TASK-001", dependencies=("TASK-002",)),
                    TaskDefinition("TASK-002", dependencies=("TASK-001",)),
                )
            )


class GitControllerTests(unittest.TestCase):
    def test_merge_review_request_derives_routes_and_git_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, base = create_git_fixture(root)
            controller.create_work_branch("feature/review-facts")
            git("switch", "feature/review-facts", cwd=checkout)
            (checkout / "feature.txt").write_text("feature\n", encoding="utf-8")
            git("add", "feature.txt", cwd=checkout)
            git("commit", "-m", "feature fact", cwd=checkout)
            git("switch", "-c", "feature/review-side", base, cwd=checkout)
            (checkout / "side.txt").write_text("side\n", encoding="utf-8")
            git("add", "side.txt", cwd=checkout)
            git("commit", "-m", "side fact", cwd=checkout)
            git("switch", "feature/review-facts", cwd=checkout)
            git("merge", "--no-ff", "feature/review-side", "-m", "merge side", cwd=checkout)
            (checkout / "fixup.txt").write_text("fixup\n", encoding="utf-8")
            git("add", "fixup.txt", cwd=checkout)
            git("commit", "-m", "fixup! feature fact", cwd=checkout)
            source = git("rev-parse", "HEAD", cwd=checkout)
            source_tree = git("rev-parse", "HEAD^{tree}", cwd=checkout)
            git("switch", "main", cwd=checkout)

            policy = {
                "review_id": "REVIEW-git-facts-001",
                "run_id": "RUN-git-facts",
                "spec_hash": "a" * 64,
                "config_hash": "b" * 64,
                "purpose": "review-current-git-facts",
                "sharing_status": "local",
                "single_logical_change": True,
                "disposable": True,
                "audit_boundary_required": False,
                "rollback_boundary_required": False,
                "allowed_strategies": (
                    "merge_commit",
                    "fast_forward",
                    "squash",
                ),
                "future_gate_id": "GATE-git-facts",
                "authorization_id": "AUTH-git-facts",
                "rollback_ref": "refs/nm-v6/rollback/git-facts",
            }
            work = controller.build_merge_review_request(
                source_ref="refs/heads/feature/review-facts",
                target_branch="dev",
                **policy,
            )
            self.assertEqual(work["route"], "work_to_dev")
            self.assertEqual(work["source_commit"], source)
            self.assertEqual(work["source_tree"], source_tree)
            self.assertEqual(work["topology"]["merge_base"], base)
            self.assertEqual(work["topology"]["source_only_commits"], 4)
            self.assertEqual(work["topology"]["target_only_commits"], 0)
            self.assertTrue(work["topology"]["target_is_ancestor"])
            self.assertFalse(work["topology"]["source_is_ancestor"])
            self.assertEqual(work["commit_quality"]["merge_commit_count"], 1)
            self.assertEqual(work["commit_quality"]["fixup_commit_count"], 1)
            self.assertFalse(work["commit_quality"]["commits_suitable"])
            self.assertEqual(
                work["allowed_strategies"],
                ["fast_forward", "squash", "merge_commit"],
            )
            for strategy in ("fast_forward", "squash", "merge_commit"):
                self.assertTrue(work["strategy_results"][strategy]["valid"])

            git("branch", "hotfix/review-routes", base, cwd=checkout)
            routes = (
                (
                    "refs/heads/dev",
                    "main",
                    "dev_to_stable",
                    True,
                    "REVIEW-route-dev-002",
                ),
                (
                    "refs/heads/hotfix/review-routes",
                    "main",
                    "hotfix_to_stable",
                    True,
                    "REVIEW-route-hotfix-stable-003",
                ),
                (
                    "refs/heads/hotfix/review-routes",
                    "dev",
                    "hotfix_to_dev",
                    False,
                    "REVIEW-route-hotfix-dev-004",
                ),
            )
            for source_ref, target, route, exact_tree, review_id in routes:
                with self.subTest(route=route):
                    request = controller.build_merge_review_request(
                        source_ref=source_ref,
                        target_branch=target,
                        **{**policy, "review_id": review_id},
                    )
                    self.assertEqual(request["route"], route)
                    self.assertIs(request["exact_source_tree_required"], exact_tree)
                    if exact_tree:
                        for result in request["strategy_results"].values():
                            if result["valid"]:
                                self.assertEqual(
                                    result["expected_result_tree"], request["source_tree"]
                                )

    def test_merge_review_helper_executes_all_three_strategy_choices(self) -> None:
        cases = (
            ("fast_forward", ("feature commit",), False),
            ("squash", ("first commit", "fixup! first commit"), False),
            ("merge_commit", ("audited commit",), True),
        )
        for strategy, subjects, audit_boundary in cases:
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, checkout, controller, _ = create_git_fixture(root)
                branch = f"feature/review-{strategy}"
                controller.create_work_branch(branch)
                git("switch", branch, cwd=checkout)
                for index, subject in enumerate(subjects):
                    path = checkout / f"change-{index}.txt"
                    path.write_text(f"{strategy}-{index}\n", encoding="utf-8")
                    git("add", path.name, cwd=checkout)
                    git("commit", "-m", subject, cwd=checkout)
                git("switch", "main", cwd=checkout)
                policy = {
                    "review_id": f"REVIEW-execute-{strategy}-001",
                    "run_id": f"RUN-execute-{strategy}",
                    "spec_hash": "c" * 64,
                    "config_hash": "d" * 64,
                    "purpose": f"execute-reviewed-{strategy}",
                    "sharing_status": "local",
                    "single_logical_change": True,
                    "disposable": strategy == "squash",
                    "audit_boundary_required": audit_boundary,
                    "rollback_boundary_required": False,
                    "allowed_strategies": (
                        "fast_forward",
                        "squash",
                        "merge_commit",
                    ),
                    "future_gate_id": f"GATE-execute-{strategy}",
                    "authorization_id": f"AUTH-execute-{strategy}",
                    "rollback_ref": f"refs/nm-v6/rollback/{strategy}",
                }
                request = controller.build_merge_review_request(
                    source_ref=f"refs/heads/{branch}",
                    target_branch="dev",
                    **policy,
                )
                observation = deterministic_fake_merge_review(request)
                self.assertEqual(observation["strategy"], strategy)
                proposal = controller.build_merge_proposal_from_review(
                    request=request,
                    observation=observation,
                    **policy,
                )
                self.assertEqual(proposal.strategy, strategy)
                receipt = controller.execute_proposal(proposal)
                self.assertEqual(receipt.result_tree, proposal.expected_result_tree)

    def test_merge_review_helper_rejects_disabled_moved_and_stale_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, _ = create_git_fixture(root)
            controller.create_work_branch("feature/review-negative")
            git("switch", "feature/review-negative", cwd=checkout)
            (checkout / "negative.txt").write_text("negative\n", encoding="utf-8")
            git("add", "negative.txt", cwd=checkout)
            git("commit", "-m", "negative fixture", cwd=checkout)
            git("switch", "main", cwd=checkout)
            policy = {
                "review_id": "REVIEW-negative-001",
                "run_id": "RUN-negative",
                "spec_hash": "e" * 64,
                "config_hash": "f" * 64,
                "purpose": "reject-substituted-review",
                "sharing_status": "local",
                "single_logical_change": True,
                "disposable": False,
                "audit_boundary_required": False,
                "rollback_boundary_required": False,
                "allowed_strategies": ("fast_forward",),
                "future_gate_id": "GATE-negative",
                "authorization_id": "AUTH-negative",
                "rollback_ref": "refs/nm-v6/rollback/negative",
            }
            request = controller.build_merge_review_request(
                source_ref="refs/heads/feature/review-negative",
                target_branch="dev",
                **policy,
            )
            disabled = seal_merge_review_observation(
                {
                    "schema_version": OBSERVATION_SCHEMA_VERSION,
                    "review_id": request["review_id"],
                    "request_digest": request["request_digest"],
                    "route": request["route"],
                    "source_commit": request["source_commit"],
                    "target_commit": request["target_commit"],
                    "candidate_tree": request["source_tree"],
                    "decision": "propose",
                    "strategy": "squash",
                    "rationale": "attempt a disabled strategy",
                    "expected_result_tree": request["strategy_results"]["squash"][
                        "expected_result_tree"
                    ],
                    "risk_flags": [],
                }
            )
            with self.assertRaisesRegex(GitPolicyError, "evidence is invalid"):
                controller.build_merge_proposal_from_review(
                    request=request,
                    observation=disabled,
                    **policy,
                )

            observation = deterministic_fake_merge_review(request)
            wrong_tree = seal_merge_review_observation(
                {
                    **{
                        key: value
                        for key, value in observation.items()
                        if key != "observation_digest"
                    },
                    "expected_result_tree": request["target_tree"],
                }
            )
            with self.assertRaisesRegex(GitPolicyError, "evidence is invalid"):
                controller.build_merge_proposal_from_review(
                    request=request,
                    observation=wrong_tree,
                    **policy,
                )

            with self.assertRaisesRegex(GitPolicyError, "core policy"):
                controller.build_merge_proposal_from_review(
                    request=request,
                    observation=observation,
                    **{**policy, "sharing_status": "published"},
                )

            git("switch", "feature/review-negative", cwd=checkout)
            (checkout / "moved.txt").write_text("moved\n", encoding="utf-8")
            git("add", "moved.txt", cwd=checkout)
            git("commit", "-m", "move source", cwd=checkout)
            git("switch", "main", cwd=checkout)
            with self.assertRaisesRegex(GitPolicyError, "core policy"):
                controller.build_merge_proposal_from_review(
                    request=request,
                    observation=observation,
                    **policy,
                )

    def test_merge_review_helper_reports_conflicts_and_rejects_cannot_propose(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, _ = create_git_fixture(root)
            controller.create_work_branch("feature/review-conflict")
            git("switch", "feature/review-conflict", cwd=checkout)
            (checkout / "base.txt").write_text("source\n", encoding="utf-8")
            git("add", "base.txt", cwd=checkout)
            git("commit", "-m", "source conflict", cwd=checkout)
            git("switch", "dev", cwd=checkout)
            (checkout / "base.txt").write_text("target\n", encoding="utf-8")
            git("add", "base.txt", cwd=checkout)
            git("commit", "-m", "target conflict", cwd=checkout)
            git("switch", "main", cwd=checkout)
            policy = {
                "review_id": "REVIEW-conflict-001",
                "run_id": "RUN-conflict",
                "spec_hash": "1" * 64,
                "config_hash": "2" * 64,
                "purpose": "detect-merge-conflict",
                "sharing_status": "local",
                "single_logical_change": True,
                "disposable": True,
                "audit_boundary_required": False,
                "rollback_boundary_required": False,
                "allowed_strategies": (
                    "fast_forward",
                    "squash",
                    "merge_commit",
                ),
                "future_gate_id": "GATE-conflict",
                "authorization_id": "AUTH-conflict",
                "rollback_ref": "refs/nm-v6/rollback/conflict",
            }
            request = controller.build_merge_review_request(
                source_ref="refs/heads/feature/review-conflict",
                target_branch="dev",
                **policy,
            )
            self.assertEqual(
                request["strategy_results"]["fast_forward"],
                {"valid": False, "conflict": False, "expected_result_tree": None},
            )
            for strategy in ("squash", "merge_commit"):
                self.assertEqual(
                    request["strategy_results"][strategy],
                    {"valid": False, "conflict": True, "expected_result_tree": None},
                )
            observation = deterministic_fake_merge_review(request)
            self.assertEqual(observation["decision"], "cannot_propose")
            with self.assertRaisesRegex(GitPolicyError, "cannot propose"):
                controller.build_merge_proposal_from_review(
                    request=request,
                    observation=observation,
                    **policy,
                )

    def test_protected_routes_require_canonical_authority_and_stable_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, _ = create_git_fixture(root)
            controller.create_work_branch("feature/no-direct-stable")
            git("switch", "feature/no-direct-stable", cwd=checkout)
            (checkout / "feature.txt").write_text("candidate\n", encoding="utf-8")
            git("add", "feature.txt", cwd=checkout)
            git("commit", "-m", "candidate", cwd=checkout)
            git("switch", "main", cwd=checkout)
            with self.assertRaisesRegex(GitPolicyError, "stable accepts only"):
                controller.build_merge_proposal(
                    source_ref="refs/heads/feature/no-direct-stable",
                    target_branch="main",
                    strategy="fast_forward",
                    purpose="forbidden-direct-stable",
                    sharing_status="local",
                    rationale="prove stable source enforcement",
                    rollback_ref="refs/nm-v6/rollback/main",
                    gate_ids=("GATE-unrelated",),
                    authorization_id="AUTH-unrelated",
                )

            proposal = controller.build_merge_proposal(
                source_ref="refs/heads/feature/no-direct-stable",
                target_branch="dev",
                strategy="fast_forward",
                purpose="authorized-dev-only",
                sharing_status="local",
                rationale="prove resolver is mandatory",
                rollback_ref="refs/nm-v6/rollback/dev",
                gate_ids=("GATE-dev",),
                authorization_id="AUTH-dev",
            )
            without_authority = GitController(checkout)
            with self.assertRaisesRegex(GitPolicyError, "canonical gate/authorization"):
                without_authority.execute_proposal(proposal)

    def test_exact_dev_merge_cas_push_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote = root / "remote.git"
            seed = root / "seed"
            checkout = root / "checkout"
            git("init", "--bare", str(remote), cwd=root)
            seed.mkdir()
            git("init", "-b", "main", cwd=seed)
            git("config", "user.name", "Test", cwd=seed)
            git("config", "user.email", "test@example.invalid", cwd=seed)
            (seed / "base.txt").write_text("base\n", encoding="utf-8")
            git("add", "base.txt", cwd=seed)
            git("commit", "-m", "base", cwd=seed)
            git("remote", "add", "origin", str(remote), cwd=seed)
            git("push", "origin", "main", cwd=seed)
            git("branch", "dev", cwd=seed)
            git("push", "origin", "dev", cwd=seed)
            git("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
            git("clone", str(remote), str(checkout), cwd=root)
            git("config", "user.name", "Test", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)

            controller = GitController(
                checkout,
                protected_authority=FixtureProtectedAuthority(),
                cleanup_authority=FixtureCleanupAuthority(),
            )
            base = controller.create_work_branch("feature/change")
            self.assertEqual(base, controller.remote_head("dev"))
            git("switch", "feature/change", cwd=checkout)
            (checkout / "feature.txt").write_text("change\n", encoding="utf-8")
            git("add", "feature.txt", cwd=checkout)
            git("commit", "-m", "feature", cwd=checkout)
            source = git("rev-parse", "HEAD", cwd=checkout)
            git("switch", "main", cwd=checkout)
            proposal = controller.build_merge_proposal(
                source_ref="refs/heads/feature/change",
                target_branch="dev",
                strategy="fast_forward",
                purpose="phase-integration",
                sharing_status="local",
                rationale="linear verified candidate",
                rollback_ref="refs/nm-v6/rollback/dev-before",
                gate_ids=("GATE-run-001",),
                authorization_id="AUTH-run-001",
            )
            receipt = controller.execute_proposal(proposal)
            self.assertEqual(receipt.target_after, source)
            push = controller.push_protected_cas(
                "dev",
                expected_remote=base,
                new_commit=receipt.target_after,
                proposal=proposal,
            )
            self.assertEqual(push.observed_after, source)
            main = git("rev-parse", "refs/heads/main", cwd=checkout)
            with self.assertRaises(GitPolicyError):
                controller.push_protected_cas(
                    "dev",
                    expected_remote=source,
                    new_commit=main,
                    proposal=proposal,
                )
            cleanup_facts = CleanupFacts(
                branch="feature/change",
                expected_head=source,
                integration_receipt=receipt,
                ancestry_proven=True,
            )
            decision = controller.evaluate_cleanup(cleanup_facts)
            self.assertEqual(decision.result, "delete_local")
            cleanup_receipt = controller.delete_local_branch(
                decision, current_facts=cleanup_facts
            )
            self.assertEqual(cleanup_receipt.result, "deleted")
            self.assertNotEqual(
                cleanup_receipt.prior_decision_at, ""
            )
            self.assertIsNone(controller.try_resolve_commit("refs/heads/feature/change"))

    def test_merge_strategies_produce_expected_trees_and_enforce_guards(self) -> None:
        for strategy in ("fast_forward", "squash", "merge_commit"):
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, checkout, controller, _ = create_git_fixture(root)
                controller.create_work_branch(f"feature/{strategy}")
                git("switch", f"feature/{strategy}", cwd=checkout)
                (checkout / f"{strategy}.txt").write_text(f"{strategy}\n", encoding="utf-8")
                git("add", f"{strategy}.txt", cwd=checkout)
                git("commit", "-m", strategy, cwd=checkout)
                git("switch", "main", cwd=checkout)
                proposal = controller.build_merge_proposal(
                    source_ref=f"refs/heads/feature/{strategy}",
                    target_branch="dev",
                    strategy=strategy,
                    purpose="strategy-fixture",
                    sharing_status="local",
                    rationale="verify exact result tree",
                    rollback_ref=f"refs/nm-v6/rollback/{strategy}",
                    gate_ids=("GATE-strategy",),
                    authorization_id="AUTH-strategy",
                )
                with self.assertRaises(GitPolicyError):
                    GitController(checkout).execute_proposal(proposal)
                receipt = controller.execute_proposal(proposal)
                self.assertEqual(receipt.result_tree, proposal.expected_result_tree)
                self.assertEqual(
                    controller.tree_of(receipt.target_after), proposal.expected_result_tree
                )
                if strategy == "squash":
                    self.assertEqual(
                        git(
                            "rev-list",
                            "--parents",
                            "-n",
                            "1",
                            receipt.target_after,
                            cwd=checkout,
                        ).count(" "),
                        1,
                    )
                if strategy == "merge_commit":
                    self.assertEqual(
                        git(
                            "rev-list",
                            "--parents",
                            "-n",
                            "1",
                            receipt.target_after,
                            cwd=checkout,
                        ).count(" "),
                        2,
                    )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, _ = create_git_fixture(root)
            controller.create_work_branch("feature/moved-target")
            git("switch", "feature/moved-target", cwd=checkout)
            (checkout / "source.txt").write_text("source\n", encoding="utf-8")
            git("add", "source.txt", cwd=checkout)
            git("commit", "-m", "source", cwd=checkout)
            git("switch", "dev", cwd=checkout)
            proposal = controller.build_merge_proposal(
                source_ref="refs/heads/feature/moved-target",
                target_branch="dev",
                strategy="fast_forward",
                purpose="moved-target",
                sharing_status="local",
                rationale="target CAS fixture",
                rollback_ref="refs/nm-v6/rollback/moved-target",
                gate_ids=("GATE-moved",),
                authorization_id="AUTH-moved",
            )
            (checkout / "target.txt").write_text("target moved\n", encoding="utf-8")
            git("add", "target.txt", cwd=checkout)
            git("commit", "-m", "move target", cwd=checkout)
            git("switch", "main", cwd=checkout)
            with self.assertRaises(GitPolicyError):
                controller.execute_proposal(proposal)

    def test_hotfix_uses_exact_stable_and_reconciles_into_dev(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, base = create_git_fixture(root)
            git("switch", "dev", cwd=checkout)
            (checkout / "dev-only.txt").write_text("dev\n", encoding="utf-8")
            git("add", "dev-only.txt", cwd=checkout)
            git("commit", "-m", "dev-only", cwd=checkout)
            dev_before = git("rev-parse", "HEAD", cwd=checkout)
            git("push", "origin", "dev", cwd=checkout)
            git("switch", "main", cwd=checkout)
            (checkout / "stable-only.txt").write_text("stable\n", encoding="utf-8")
            git("add", "stable-only.txt", cwd=checkout)
            git("commit", "-m", "stable-only", cwd=checkout)
            stable_before = git("rev-parse", "HEAD", cwd=checkout)
            git("push", "origin", "main", cwd=checkout)
            self.assertNotEqual(base, stable_before)
            self.assertNotEqual(dev_before, stable_before)

            with self.assertRaises(GitPolicyError):
                controller.create_hotfix_branch(
                    "hotfix/unauthorized", authorization_id=""
                )
            with self.assertRaises(GitPolicyError):
                controller.create_work_branch("main")
            hotfix_base = controller.create_hotfix_branch(
                "hotfix/security",
                authorization_id="AUTH-hotfix-create",
                expected_remote_stable=stable_before,
            )
            self.assertEqual(hotfix_base, stable_before)
            git("switch", "hotfix/security", cwd=checkout)
            (checkout / "hotfix.txt").write_text("fixed\n", encoding="utf-8")
            git("add", "hotfix.txt", cwd=checkout)
            git("commit", "-m", "hotfix", cwd=checkout)
            hotfix = git("rev-parse", "HEAD", cwd=checkout)
            git("switch", "--detach", hotfix, cwd=checkout)
            stable_proposal = controller.build_merge_proposal(
                source_ref="refs/heads/hotfix/security",
                target_branch="main",
                strategy="fast_forward",
                purpose="hotfix-stable",
                sharing_status="local",
                rationale="authorized exact-stable hotfix",
                rollback_ref="refs/nm-v6/rollback/main-before-hotfix",
                gate_ids=("GATE-hotfix-stable",),
                authorization_id="AUTH-hotfix-stable",
            )
            stable_receipt = controller.execute_proposal(stable_proposal)
            controller.push_protected_cas(
                "main",
                expected_remote=stable_before,
                new_commit=stable_receipt.target_after,
                proposal=stable_proposal,
            )
            self.assertEqual(stable_receipt.target_after, hotfix)

            reconcile = controller.build_merge_proposal(
                source_ref="refs/heads/hotfix/security",
                target_branch="dev",
                strategy="merge_commit",
                purpose="hotfix-dev-reconciliation",
                sharing_status="local",
                rationale="preserve dev and stable hotfix histories",
                rollback_ref="refs/nm-v6/rollback/dev-before-hotfix",
                gate_ids=("GATE-hotfix-reconcile",),
                authorization_id="AUTH-hotfix-reconcile",
            )
            reconciled = controller.execute_proposal(reconcile)
            controller.push_protected_cas(
                "dev",
                expected_remote=dev_before,
                new_commit=reconciled.target_after,
                proposal=reconcile,
            )
            self.assertEqual(
                git("show", f"{reconciled.target_after}:hotfix.txt", cwd=checkout), "fixed"
            )
            self.assertEqual(
                git("show", f"{reconciled.target_after}:dev-only.txt", cwd=checkout), "dev"
            )

    def test_cleanup_retention_matrix_and_squash_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, base = create_git_fixture(root)
            controller.fetch_dev()
            git("branch", "feature/cleanup", base, cwd=checkout)
            head = git("rev-parse", "refs/heads/feature/cleanup", cwd=checkout)
            receipt = MergeReceipt(
                "fast_forward",
                head,
                base,
                head,
                controller.tree_of(head),
                "refs/nm-v6/rollback/dev",
                "AUTH-cleanup",
                "2026-01-01T00:00:00Z",
            )
            for field in (
                "under_review",
                "dependent_work",
                "rollback_responsibility",
                "live_lease",
                "live_session",
                "dependent_workspace",
            ):
                with self.subTest(field=field):
                    facts = {
                        "branch": "feature/cleanup",
                        "expected_head": head,
                        "integration_receipt": receipt,
                        "ancestry_proven": True,
                        field: True,
                    }
                    self.assertEqual(
                        controller.evaluate_cleanup(CleanupFacts(**facts)).result, "retain"
                    )
            self.assertEqual(
                controller.evaluate_cleanup(
                    CleanupFacts("feature/cleanup", head, None, ancestry_proven=True)
                ).result,
                "retain",
            )
            for branch in ("main", "dev"):
                branch_head = controller.resolve_commit(f"refs/heads/{branch}")
                self.assertEqual(
                    controller.evaluate_cleanup(
                        CleanupFacts(branch, branch_head, receipt, ancestry_proven=True)
                    ).result,
                    "retain",
                )
            git("branch", "hotfix/retain", head, cwd=checkout)
            self.assertEqual(
                controller.evaluate_cleanup(
                    CleanupFacts("hotfix/retain", head, receipt, ancestry_proven=True)
                ).result,
                "retain",
            )

            squash = MergeReceipt(
                "squash",
                head,
                base,
                head,
                controller.tree_of(head),
                "refs/nm-v6/rollback/dev",
                "AUTH-squash",
                "2026-01-01T00:00:00Z",
            )
            self.assertEqual(
                controller.evaluate_cleanup(
                    CleanupFacts("feature/cleanup", head, squash)
                ).result,
                "retain",
            )
            self.assertEqual(
                controller.evaluate_cleanup(
                    CleanupFacts(
                        "feature/cleanup",
                        head,
                        squash,
                        patch_or_tree_equivalent=True,
                    )
                ).result,
                "delete_local",
            )

            git("branch", "feature/linked", head, cwd=checkout)
            linked = root / "linked-worktree"
            git("worktree", "add", str(linked), "feature/linked", cwd=checkout)
            self.assertEqual(
                controller.evaluate_cleanup(
                    CleanupFacts(
                        "feature/linked", head, receipt, ancestry_proven=True
                    )
                ).result,
                "retain",
            )
            git("worktree", "remove", str(linked), cwd=checkout)


FAKE_ACTION_SCRIPT = r'''from __future__ import annotations
import json
import os
import sys
from pathlib import Path

action = sys.argv[1]
operation_id = os.environ.get("NM_V6_OPERATION_ID")
state_path = Path("external-state.json")
state = json.loads(state_path.read_text()) if state_path.exists() else {"deployed_version": "v1"}
observed = {}
effect = None
artifact = None
environment = None
fingerprint = None
result_status = "succeeded"
if action == "identity":
    environment = "project-production"
    fingerprint = "fingerprint-1"
    observed = {"deployed_version": state["deployed_version"]}
elif action == "preflight":
    observed = {"ready": True}
elif action == "deploy":
    state = {"deployed_version": "v2", "artifact_digest": os.environ["NM_V6_ARTIFACT_DIGEST"], "deployment_count": state.get("deployment_count", 0) + 1}
    state_path.write_text(json.dumps(state))
    if Path("force-partial").exists():
        result_status = "partial"
    effect = "deployment-1"
    artifact = state["artifact_digest"]
    environment = "project-production"
    fingerprint = "fingerprint-1"
elif action == "rollback":
    state = {"deployed_version": os.environ["NM_V6_ROLLBACK_TARGET"]}
    state_path.write_text(json.dumps(state))
    effect = "rollback-1"
    environment = "project-production"
    fingerprint = "fingerprint-1"
    if Path("force-rollback-partial").exists():
        result_status = "partial"
elif action == "observe":
    force_unknown = Path("force-unknown").exists() or Path(
        "force-unknown-" + (operation_id or "missing")
    ).exists()
    if force_unknown and not Path("reconciled").exists():
        classification = "unknown"
    else:
        classification = "completed" if state_path.exists() else "not_started"
    observed = {"classification": classification, **state}
    artifact = state.get("artifact_digest")
    environment = "project-production"
    fingerprint = "fingerprint-1"
elif action == "reconcile":
    force_reconcile_unknown = Path("force-reconcile-unknown").exists() or Path(
        "force-reconcile-unknown-" + (operation_id or "missing")
    ).exists()
    if force_reconcile_unknown:
        classification = "unknown"
    else:
        Path("reconciled").write_text("yes")
        classification = "completed" if state_path.exists() else "not_started"
    observed = {"classification": classification, **state}
    artifact = state.get("artifact_digest")
    environment = "project-production"
    fingerprint = "fingerprint-1"
elif action == "health":
    observed = {"healthy": not Path("force-unhealthy").exists(), **state}
    environment = "project-production"
    fingerprint = "fingerprint-1"
elif action == "post_rollback":
    observed = {"healthy": not Path("force-post-rollback-failure").exists(), **state}
    environment = "project-production"
    fingerprint = "fingerprint-1"
else:
    raise SystemExit(2)
timestamp = "2026-01-01T00:00:00Z"
print(json.dumps({
    "protocol_version": "nm-v6/action-result-v1",
    "action_id": action,
    "operation_id": operation_id,
    "status": result_status,
    "effect_id": effect,
    "artifact_digest": artifact,
    "environment_id": environment,
    "environment_fingerprint": fingerprint,
    "observed_state": observed,
    "started_at": timestamp,
    "finished_at": timestamp,
    "diagnostics": {},
    "redactions": [],
}))
'''


def create_delivery_fixture(
    root: Path,
) -> tuple[
    Workspace,
    Mapping[str, ActionDefinition],
    FakeRecorder,
    RecoveryController,
    DeliveryController,
    EnvironmentTarget,
]:
    (root / "fake_action.py").write_text(FAKE_ACTION_SCRIPT, encoding="utf-8")
    argv = lambda action: [sys.executable, "fake_action.py", action]
    definitions = validate_action_registry(
        {
            "identity": action_mapping("identity", "external_observe", argv("identity")),
            "preflight": action_mapping("preflight", "pure", argv("preflight")),
            "deploy": action_mapping(
                "deploy",
                "external_mutation",
                argv("deploy"),
                core_env=[
                    "NM_V6_OPERATION_ID",
                    "NM_V6_ARTIFACT_DIGEST",
                    "NM_V6_ENVIRONMENT_ID",
                    "NM_V6_ENVIRONMENT_FINGERPRINT",
                ],
                observe="observe",
                reconcile="reconcile",
            ),
            "rollback": action_mapping(
                "rollback",
                "external_mutation",
                argv("rollback"),
                core_env=[
                    "NM_V6_OPERATION_ID",
                    "NM_V6_ROLLBACK_TARGET",
                    "NM_V6_ENVIRONMENT_ID",
                    "NM_V6_ENVIRONMENT_FINGERPRINT",
                ],
                observe="observe",
                reconcile="reconcile",
            ),
            "observe": action_mapping(
                "observe",
                "external_observe",
                argv("observe"),
                core_env=["NM_V6_OPERATION_ID"],
            ),
            "reconcile": action_mapping(
                "reconcile",
                "external_observe",
                argv("reconcile"),
                core_env=["NM_V6_OPERATION_ID"],
            ),
            "health": action_mapping("health", "external_observe", argv("health")),
            "post_rollback": action_mapping(
                "post_rollback", "external_observe", argv("post_rollback")
            ),
        }
    )
    workspace = Workspace("delivery", root, "fixture", None)
    recorder = FakeRecorder()
    executor = ActionExecutor(isolation_backend=TestIsolationBackend())
    recovery = RecoveryController(definitions, executor, recorder)
    delivery = DeliveryController(definitions, executor, recovery)
    target = EnvironmentTarget(
        environment_id="production",
        expected_identity="project-production",
        expected_fingerprint="fingerprint-1",
        identity_probe_action="identity",
        preflight_action="preflight",
        deploy_action="deploy",
        health_action="health",
        rollback_action="rollback",
        post_rollback_verify_action="post_rollback",
    )
    return workspace, definitions, recorder, recovery, delivery, target


class DeliveryAndControllerTests(unittest.TestCase):
    def test_interrupted_mutation_is_persisted_then_reconciled_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fake_action.py").write_text(FAKE_ACTION_SCRIPT, encoding="utf-8")
            argv = lambda action: [sys.executable, "fake_action.py", action]
            definitions = validate_action_registry(
                {
                    "deploy": action_mapping(
                        "deploy",
                        "external_mutation",
                        argv("deploy"),
                        core_env=[
                            "NM_V6_OPERATION_ID",
                            "NM_V6_ARTIFACT_DIGEST",
                            "NM_V6_ENVIRONMENT_ID",
                            "NM_V6_ENVIRONMENT_FINGERPRINT",
                        ],
                        observe="observe",
                        reconcile="reconcile",
                    ),
                    "observe": action_mapping(
                        "observe",
                        "external_observe",
                        argv("observe"),
                        core_env=["NM_V6_OPERATION_ID"],
                    ),
                    "reconcile": action_mapping(
                        "reconcile",
                        "external_observe",
                        argv("reconcile"),
                        core_env=["NM_V6_OPERATION_ID"],
                    ),
                }
            )
            recorder = FakeRecorder()
            executor = ActionExecutor(isolation_backend=TestIsolationBackend())
            recovery = RecoveryController(definitions, executor, recorder)
            workspace = Workspace("crash", root, "fixture", None)
            kwargs = {
                "workspace": workspace,
                "operation_id": "OP-run-009",
                "grant_id": "AUTH-run-009",
                "grant_revision": 1,
                "core_env": {
                    "NM_V6_ARTIFACT_DIGEST": "a" * 64,
                    "NM_V6_ENVIRONMENT_ID": "project-production",
                    "NM_V6_ENVIRONMENT_FINGERPRINT": "fingerprint-1",
                },
                "allow_network": True,
            }
            with patch.dict(
                os.environ,
                {"NM_V6_FAILPOINT": "action.before_invoke", "NM_V6_FAILPOINT_ACTION": "raise"},
            ):
                with self.assertRaises(FailpointError):
                    recovery.execute_mutation("deploy", **kwargs)
            self.assertEqual(recorder.operations["OP-run-009"]["status"], "started")
            self.assertFalse((root / "external-state.json").exists())
            not_started = recovery.observe_reconcile(
                "deploy", workspace=workspace, operation_id="OP-run-009", allow_network=True
            )
            self.assertTrue(not_started.safe_to_retry)
            retry_kwargs = {**kwargs, "operation_id": "OP-run-010"}
            recovery.execute_mutation("deploy", **retry_kwargs)
            reconciled = recovery.observe_reconcile(
                "deploy", workspace=workspace, operation_id="OP-run-010", allow_network=True
            )
            self.assertEqual(reconciled.classification, "completed")
            with self.assertRaises(ActionError):
                recovery.execute_mutation("deploy", **retry_kwargs)
            state = json.loads((root / "external-state.json").read_text())
            self.assertEqual(state["deployment_count"], 1)

    def test_build_binds_source_and_release_source_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = (
                "import json,os;"
                "t='2026-01-01T00:00:00Z';"
                "print(json.dumps({'protocol_version':'nm-v6/action-result-v1',"
                "'action_id':'build','operation_id':None,'status':'succeeded',"
                "'effect_id':None,'artifact_digest':'" + "b" * 64 + "',"
                "'environment_id':None,'environment_fingerprint':None,"
                "'observed_state':{'source':os.environ['NM_V6_SOURCE_COMMIT']},"
                "'started_at':t,'finished_at':t,'diagnostics':{},'redactions':[]}))"
            )
            definition = ActionDefinition.from_mapping(
                action_mapping(
                    "build",
                    "pure",
                    [sys.executable, "-c", code],
                    core_env=["NM_V6_SOURCE_COMMIT"],
                )
            )
            executor = ActionExecutor(isolation_backend=TestIsolationBackend())
            recovery = RecoveryController({}, executor, FakeRecorder())
            delivery = DeliveryController({"build": definition}, executor, recovery)
            workspace = Workspace("release", root, "fixture", None)
            result = delivery.build(
                workspace=workspace, action_id="build", source_commit="c" * 40
            )
            self.assertEqual(result.observed_state["source"], "c" * 40)
            normal = ReleaseSource("dev", "c" * 40, "d" * 40, "s", "cfg")
            delivery._verify_release_source(
                normal, stable_commit="e" * 40, stable_tree="d" * 40
            )
            with self.assertRaises(ContractError):
                delivery._verify_release_source(
                    normal, stable_commit="e" * 40, stable_tree="f" * 40
                )
            hotfix = ReleaseSource(
                "hotfix_stable", "a" * 40, "b" * 40, "s", "cfg", "GATE-run-001"
            )
            delivery._verify_release_source(
                hotfix, stable_commit="a" * 40, stable_tree="b" * 40
            )

    def test_environment_bound_deploy_and_verified_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fake_action.py").write_text(FAKE_ACTION_SCRIPT, encoding="utf-8")
            argv = lambda action: [sys.executable, "fake_action.py", action]
            definitions = validate_action_registry(
                {
                    "identity": action_mapping("identity", "external_observe", argv("identity")),
                    "preflight": action_mapping("preflight", "pure", argv("preflight")),
                    "deploy": action_mapping(
                        "deploy",
                        "external_mutation",
                        argv("deploy"),
                        core_env=[
                            "NM_V6_OPERATION_ID",
                            "NM_V6_ARTIFACT_DIGEST",
                            "NM_V6_ENVIRONMENT_ID",
                            "NM_V6_ENVIRONMENT_FINGERPRINT",
                        ],
                        observe="observe",
                        reconcile="reconcile",
                    ),
                    "rollback": action_mapping(
                        "rollback",
                        "external_mutation",
                        argv("rollback"),
                        core_env=[
                            "NM_V6_OPERATION_ID",
                            "NM_V6_ROLLBACK_TARGET",
                            "NM_V6_ENVIRONMENT_ID",
                            "NM_V6_ENVIRONMENT_FINGERPRINT",
                        ],
                        observe="observe",
                        reconcile="reconcile",
                    ),
                    "observe": action_mapping(
                        "observe",
                        "external_observe",
                        argv("observe"),
                        core_env=["NM_V6_OPERATION_ID"],
                    ),
                    "reconcile": action_mapping(
                        "reconcile",
                        "external_observe",
                        argv("reconcile"),
                        core_env=["NM_V6_OPERATION_ID"],
                    ),
                    "health": action_mapping("health", "external_observe", argv("health")),
                    "post_rollback": action_mapping(
                        "post_rollback", "external_observe", argv("post_rollback")
                    ),
                }
            )
            workspace = Workspace("delivery", root, "fixture", None)
            recorder = FakeRecorder()
            executor = ActionExecutor(isolation_backend=TestIsolationBackend())
            recovery = RecoveryController(definitions, executor, recorder)
            delivery = DeliveryController(definitions, executor, recovery)
            target = EnvironmentTarget(
                environment_id="production",
                expected_identity="project-production",
                expected_fingerprint="fingerprint-1",
                identity_probe_action="identity",
                preflight_action="preflight",
                deploy_action="deploy",
                health_action="health",
                rollback_action="rollback",
                post_rollback_verify_action="post_rollback",
            )
            receipt = delivery.deploy(
                workspace=workspace,
                target=target,
                artifact_digest="a" * 64,
                deploy_operation_id="OP-run-001",
                grant_id="AUTH-run-001",
                grant_revision=1,
            )
            self.assertEqual(receipt.state, "POST_DEPLOY_VERIFIED")
            self.assertEqual(receipt.artifact_digest, "a" * 64)
            rollback = delivery.rollback(
                workspace=workspace,
                target=target,
                rollback_target="v1",
                operation_id="OP-run-002",
                grant_id="AUTH-run-001",
                grant_revision=1,
            )
            self.assertEqual(rollback.state, "ROLLED_BACK")
            self.assertEqual(
                json.loads((root / "external-state.json").read_text())["deployed_version"],
                "v1",
            )

    def test_environment_mismatch_and_unhealthy_deploy_require_attention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, _, _, _, delivery, target = create_delivery_fixture(root)
            mismatched = replace(target, expected_identity="another-production")
            with self.assertRaises(ActionError):
                delivery.confirm_environment(workspace=workspace, target=mismatched)

            (root / "force-unhealthy").write_text("yes", encoding="utf-8")
            receipt = delivery.deploy(
                workspace=workspace,
                target=target,
                artifact_digest="a" * 64,
                deploy_operation_id="OP-run-unhealthy-001",
                grant_id="AUTH-run-unhealthy-001",
                grant_revision=1,
                rollback_operation_id=None,
                rollback_authorized=False,
            )
            self.assertEqual(receipt.state, "ATTENTION_REQUIRED")
            self.assertIsNone(receipt.rollback)
            self.assertEqual(
                json.loads((root / "external-state.json").read_text())["deployed_version"],
                "v2",
            )

    def test_partial_unknown_operation_is_observed_and_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, _, recorder, recovery, _, _ = create_delivery_fixture(root)
            (root / "force-partial").write_text("yes", encoding="utf-8")
            (root / "force-unknown").write_text("yes", encoding="utf-8")
            with self.assertRaises(RecoveryError):
                recovery.execute_mutation(
                    "deploy",
                    workspace=workspace,
                    operation_id="OP-run-partial-001",
                    grant_id="AUTH-run-partial-001",
                    grant_revision=1,
                    core_env={
                        "NM_V6_ARTIFACT_DIGEST": "a" * 64,
                        "NM_V6_ENVIRONMENT_ID": "project-production",
                        "NM_V6_ENVIRONMENT_FINGERPRINT": "fingerprint-1",
                    },
                    allow_network=True,
                )
            self.assertEqual(recorder.operations["OP-run-partial-001"]["status"], "partial")
            result = recovery.observe_reconcile(
                "deploy",
                workspace=workspace,
                operation_id="OP-run-partial-001",
                allow_network=True,
            )
            self.assertEqual(result.observation.observed_state["classification"], "unknown")
            self.assertEqual(result.classification, "completed")
            self.assertIsNotNone(result.reconciliation)
            self.assertTrue((root / "reconciled").exists())

    def test_retry_and_pause_fail_closed(self) -> None:
        decision = decide_retry(
            FailureClass.TRANSIENT_INFRASTRUCTURE,
            attempts=0,
            policy=RetryPolicy(),
            failure_fingerprint="same",
            previous_fingerprint="same",
            input_changed=False,
        )
        self.assertTrue(decision.retry)

        class Store:
            @staticmethod
            def get_run(run_id: str) -> Mapping[str, Any]:
                return {"run_id": run_id, "state": "DEPLOYING", "revision": 1}

        controller = WorkflowController(object(), Store())
        proposal = controller.pause_proposal(
            run_id="run",
            expected_revision=1,
            current_state="DEPLOYING",
            reason="pause",
            active_operations=({"operation_id": "OP-run-001"},),
            reconcile=lambda operation: "unknown",
        )
        self.assertEqual(proposal.event, "REQUIRE_ATTENTION")
        self.assertEqual(proposal.payload["resume_state"], "DEPLOYING")


if __name__ == "__main__":
    unittest.main()
