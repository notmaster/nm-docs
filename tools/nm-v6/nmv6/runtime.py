"""Concrete generated-project runtime composition and credential-free self-test."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .actions import ActionExecutor, ActionResult, SecretValue, validate_action_registry
from .adapters import create_adapter
from .authorization import (
    OpenSSLSignatureVerifier,
    authorization_scope_allows,
    validate_authorization_record,
)
from .context import ContextItem, build_context_manifest
from .cleanup_review import (
    build_cleanup_review_context_manifest,
    seal_cleanup_facts,
    seal_cleanup_review_request,
    validate_cleanup_review_observations,
    validate_cleanup_review_request,
    validate_cleanup_reviewer_adapter_result,
)
from .contracts import (
    adapter_result_to_dict,
    validate_adapter_request,
    validate_adapter_result,
    validate_project_config,
    validate_version_record,
)
from .controller import WorkflowController
from .delivery import DeliveryController, EnvironmentTarget, ReleaseSource
from .errors import (
    ActionError,
    ContractError,
    GitPolicyError,
    NmV6Error,
    RecoveryError,
    TransitionError,
)
from .evidence import EvidenceStore
from .failpoints import checkpoint
from .gates import GATE_DEFINITIONS, GateEvaluator, required_bindings
from .git_controller import (
    CleanupDecision,
    CleanupFacts,
    GitController,
    MergeProposal,
    MergeReceipt,
    StoreProtectedMutationAuthority,
)
from .merge_review import (
    merge_review_context_item,
    validate_merge_review_request,
    validate_merge_reviewer_adapter_result,
)
from .models import GateObservation, OperationObservation, TransitionProposal
from .reducer import Reducer
from .recovery import RecoveryController, ReducerOperationRecorder
from .scheduler import (
    Lease,
    ReducerLeaseAuthority,
    Scheduler,
    TaskDefinition,
    TaskGraph,
    actual_paths_overlap,
)
from .supply_chain import collect_project_runtime_versions, detect_version_drift
from .util import (
    atomic_write,
    canonical_json,
    dump_json,
    load_json,
    run_command,
    safe_environment,
    sha256_bytes,
    utc_now,
)
from .workspace import Workspace, WorkspaceManager, temporary_workspace_root


CONTROLLER_RECORD_SCHEMA = "nm-v6/controller-process-v1"
DISPATCH_RESULT_SCHEMA = "nm-v6/runtime-dispatch-v1"
_TERMINAL_STATES = frozenset({"COMPLETED", "ROLLED_BACK", "FAILED", "CANCELLED"})


class ConfiguredDispatcher:
    """Drive deterministic edges and delegate configured lifecycle work."""

    def __init__(
        self,
        reducer: Any,
        store: Any,
        *,
        run_id: str,
        configured_step: Callable[[Mapping[str, Any]], bool | None] | None = None,
    ) -> None:
        self.reducer = reducer
        self.store = store
        self.run_id = run_id
        self.configured_step = configured_step
        self.last_result: dict[str, Any] = {
            "schema_version": DISPATCH_RESULT_SCHEMA,
            "result": "waiting_for_input",
            "run_id": run_id,
            "waiting_for": "initial_state",
        }

    def __call__(self, run: Mapping[str, Any]) -> bool:
        state = str(run["state"])
        revision = int(run["revision"])
        if state in _TERMINAL_STATES:
            self.last_result = self._result("terminal", run)
            return False
        if self.configured_step is not None:
            handled = self.configured_step(run)
            if handled is not None:
                configured_result = getattr(
                    self.configured_step, "last_result", None
                )
                if isinstance(configured_result, Mapping):
                    self.last_result = dict(configured_result)
                return bool(handled)
        if state == "SPEC_CONFIRMED":
            return self._transition(run, "START_PLANNING")
        if state == "READY" and run.get("run_kind") == "normal":
            return self._transition(run, "START_IMPLEMENTATION")
        if state == "RELEASE_VERIFIED":
            return self._transition(run, "PREPARE_DEPLOYMENT")

        waiting = {
            "DISCOVERING": "discovery_decision",
            "SPEC_DRAFT": "spec_review_submission",
            "SPEC_REVIEW": "trusted_spec_confirmation_request",
            "SPEC_AWAITING_CONFIRMATION": "signed_spec_confirmation",
            "PLANNING": "plan_gate",
            "READY": "trusted_hotfix_authorization",
            "IMPLEMENTING": "worker_or_task_result",
            "PHASE_VERIFYING": "phase_gate",
            "PHASE_AWAITING_ACCEPTANCE": "phase_approval",
            "INTEGRATING_DEV": "dev_integration_result",
            "INTEGRATION_VERIFYING": "dev_integration_result_gate",
            "HOTFIX_IMPLEMENTING": "hotfix_worker_result",
            "HOTFIX_VERIFYING": "hotfix_stable_gate",
            "HOTFIX_INTEGRATING_STABLE": "hotfix_stable_result",
            "HOTFIX_STABLE_VERIFYING": "hotfix_reconciliation_gate",
            "HOTFIX_RECONCILING_DEV": "hotfix_dev_result",
            "HOTFIX_DEV_VERIFYING": "hotfix_reconciliation_result_gate",
            "RELEASE_READY": "release_gate_and_authorization",
            "RELEASING": "release_result_gate",
            "DEPLOY_READY": "deploy_gate_and_authorization",
            "DEPLOYING": "deployment_observation",
            "POST_DEPLOY_VERIFYING": "post_deploy_and_completion_gates",
            "ROLLBACK_REQUIRED": "rollback_gate_and_authorization",
            "ROLLING_BACK": "rollback_observation",
            "POST_ROLLBACK_VERIFYING": "post_rollback_gate",
            "PAUSED": "resume_request",
            "ATTENTION_REQUIRED": "administrator_resolution",
        }.get(state)
        if waiting is None:
            raise ContractError(f"configured dispatcher does not recognize state {state!r}")
        self.last_result = {
            **self._result("waiting_for_input", run),
            "waiting_for": waiting,
            "revision": revision,
        }
        return False

    def _transition(self, run: Mapping[str, Any], event: str) -> bool:
        result = self.reducer.transition(
            TransitionProposal(
                run_id=self.run_id,
                expected_revision=int(run["revision"]),
                event=event,
                actor="nm-v6-configured-dispatcher",
                idempotency_key=f"runtime-dispatch:{self.run_id}:{event}:{run['revision']}",
            )
        )
        latest = self.store.get_run(self.run_id)
        self.last_result = {
            **self._result("driven", latest or run),
            "event": event,
            "from_state": run["state"],
            "state": result["state"],
        }
        return True

    def _result(self, result: str, run: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": DISPATCH_RESULT_SCHEMA,
            "result": result,
            "run_id": self.run_id,
            "state": run["state"],
            "revision": int(run["revision"]),
        }


class DurableChildLauncher:
    """Journal controller identity, then launch an external one-shot supervisor.

    JSON files are explicitly disposable projections.  Launch deduplication,
    expiry recovery, and status reconstruction read only the SQLite journal.
    """

    def __init__(self, target: Path, reducer: Any, store: Any, *, run_id: str) -> None:
        self.target = target.resolve()
        self.reducer = reducer
        self.store = store
        self.run_id = run_id
        self.root = self.target / ".nm/runtime/v6/controllers"
        self.root.mkdir(parents=True, exist_ok=True)

    def launch(self, run_id: str) -> Mapping[str, Any]:
        if run_id != self.run_id:
            raise ContractError("durable launcher cannot cross its configured run scope")
        for record in reversed(self._canonical_records()):
            if record.get("status") in {"scheduled", "running"} and not self._expired(record):
                self._write_projection(record)
                return record
        controller_id = f"controller-{uuid.uuid4().hex}"
        expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        requested = {
            "schema_version": CONTROLLER_RECORD_SCHEMA,
            "controller_id": controller_id,
            "run_id": run_id,
            "status": "scheduled",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "expires_at": expires_at,
            "command_digest": "",
            "state": None,
            "revision": None,
            "result": None,
        }
        entrypoint = self.target / "0d-scripts/nm-v6.py"
        if not entrypoint.is_file():
            raise ContractError("generated project has no vendored NM V6 CLI entrypoint")
        command = [
            sys.executable,
            str(entrypoint),
            "run",
            "--target",
            str(self.target),
            "--run-id",
            run_id,
            "--child",
        ]
        requested["command_digest"] = sha256_bytes(canonical_json(command[1:]))
        record = self._record_status(
            "CONTROLLER_LAUNCH_REQUESTED",
            requested,
            idempotency_key=f"controller-launch:{controller_id}",
        )
        environment = safe_environment(
            injected={"NM_V6_CONTROLLER_ID": controller_id}, source=os.environ
        )
        stdout_path = self.root / f"{controller_id}.stdout.log"
        stderr_path = self.root / f"{controller_id}.stderr.log"
        try:
            with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
                subprocess.Popen(
                    command,
                    cwd=self.target,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    close_fds=True,
                    start_new_session=True,
                )
        except OSError:
            self.mark(
                controller_id,
                status="failed",
                run=self.store.get_run(self.run_id),
                result={"result": "launch_failed"},
            )
            raise
        return dict(record)

    def mark(
        self,
        controller_id: str,
        *,
        status: str,
        run: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self._canonical_record(controller_id)
        record.update(
            {
                "status": status,
                "updated_at": utc_now(),
                "state": run.get("state") if isinstance(run, Mapping) else record.get("state"),
                "revision": (
                    int(run["revision"])
                    if isinstance(run, Mapping) and "revision" in run
                    else record.get("revision")
                ),
                "result": dict(result) if isinstance(result, Mapping) else result,
            }
        )
        return self._record_status(
            "CONTROLLER_STATUS_RECORDED",
            record,
            idempotency_key=(
                f"controller-status:{controller_id}:{status}:"
                f"{self.store.get_run(self.run_id)['revision']}"
            ),
        )

    def read(self, controller_id: str) -> dict[str, Any]:
        record = self._canonical_record(controller_id)
        self._write_projection(record)
        return record

    def _canonical_record(self, controller_id: str) -> dict[str, Any]:
        matches = [
            record
            for record in self._canonical_records()
            if record.get("controller_id") == controller_id
        ]
        if not matches:
            raise ContractError(f"unknown durable controller identity: {controller_id}")
        return matches[-1]

    def _canonical_records(self) -> tuple[dict[str, Any], ...]:
        records: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for event in self.store.list_events(run_id=self.run_id):
            if event.get("event_type") not in {
                "CONTROLLER_LAUNCH_REQUESTED",
                "CONTROLLER_STATUS_RECORDED",
            }:
                continue
            payload = event.get("payload", {})
            raw = payload.get("record") if isinstance(payload, Mapping) else None
            if not isinstance(raw, Mapping):
                raise ContractError("canonical controller event is malformed")
            controller_id = raw.get("controller_id")
            if not isinstance(controller_id, str):
                raise ContractError("canonical controller event lacks identity")
            value = dict(raw)
            value.update(
                {
                    "authoritative": False,
                    "canonical_runtime_truth": "SQLite run/events",
                    "canonical_event_sequence": int(event["sequence"]),
                    "canonical_run_revision": int(event["run_revision"]),
                }
            )
            if controller_id not in records:
                order.append(controller_id)
            records[controller_id] = value
        return tuple(records[controller_id] for controller_id in order)

    def _record_status(
        self,
        event_type: str,
        record: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        run = self.store.get_run(self.run_id)
        if not isinstance(run, Mapping):
            raise ContractError(f"unknown run for durable controller: {self.run_id}")
        canonical = {
            key: value
            for key, value in dict(record).items()
            if key
            not in {
                "authoritative",
                "canonical_runtime_truth",
                "canonical_event_sequence",
                "canonical_run_revision",
            }
        }
        result = self.reducer.record_domain_event(
            run_id=self.run_id,
            expected_revision=int(run["revision"]),
            event_type=event_type,
            payload=canonical,
            idempotency_key=idempotency_key,
            actor="nm-v6-durable-launcher",
        )
        projected = {
            **canonical,
            "authoritative": False,
            "canonical_runtime_truth": "SQLite run/events",
            "canonical_event_sequence": int(result["event_sequence"]),
            "canonical_run_revision": int(result["revision"]),
        }
        self._write_projection(projected)
        return projected

    def _write_projection(self, record: Mapping[str, Any]) -> None:
        controller_id = record.get("controller_id")
        if not isinstance(controller_id, str) or not controller_id.startswith("controller-"):
            raise ContractError("invalid durable controller identity")
        atomic_write(self.root / f"{controller_id}.json", dump_json(dict(record)))

    @staticmethod
    def _expired(record: Mapping[str, Any]) -> bool:
        value = record.get("expires_at")
        if not isinstance(value, str):
            return True
        try:
            expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return True
        return expiry.astimezone(UTC) <= datetime.now(UTC)


def _persisted_operation_workspace(
    target: Path,
    operation: Mapping[str, Any],
    *,
    run_id: str,
    expected_commit: str | None = None,
) -> tuple[WorkspaceManager, Workspace, Path] | None:
    """Reopen only a controller-created standalone Operation workspace.

    Operation scope is durable recovery input, not a trusted filesystem
    capability.  Bind the recorded path back to the controller naming scheme,
    exact source commit, standalone Git metadata, and credential-free clone
    invariant before any observe or verification action executes there.
    """

    scope = operation.get("scope", {})
    if not isinstance(scope, Mapping):
        raise RecoveryError("persisted operation scope is malformed")
    persisted = scope.get("workspace_path")
    if persisted is None:
        return None
    if not isinstance(persisted, str) or not persisted:
        raise RecoveryError("persisted Operation workspace path is malformed")
    recorded_root = scope.get("workspace_root")
    recorded_id = scope.get("workspace_id")
    source_commit = scope.get("source_commit")
    if not all(
        isinstance(value, str) and value
        for value in (recorded_root, recorded_id, source_commit)
    ):
        raise RecoveryError("persisted Operation workspace binding is incomplete")
    raw_path = Path(persisted)
    raw_root = Path(str(recorded_root))
    if not raw_path.is_absolute() or not raw_root.is_absolute():
        raise RecoveryError("persisted Operation workspace must be absolute")
    try:
        path = raw_path.resolve(strict=True)
        root = raw_root.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError("persisted Operation workspace is unavailable") from exc
    if (
        path != Path(os.path.abspath(raw_path))
        or root != Path(os.path.abspath(raw_root))
        or not path.is_dir()
        or path.is_symlink()
        or not root.is_dir()
        or root.is_symlink()
        or path.parent != root
        or path.name != recorded_id
    ):
        raise RecoveryError("persisted Operation workspace path binding is invalid")
    try:
        root.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError as exc:
        raise RecoveryError("persisted Operation workspace root is not temporary") from exc
    action_id = operation.get("action_id")
    label = {
        "release": "release",
        "publish": "release",
        "deploy": "deploy",
        "rollback": "rollback",
    }.get(str(action_id))
    if label is None:
        raise RecoveryError("operation action has no persisted workspace contract")
    if action_id in {"deploy", "rollback"} and "environment_index" in scope:
        environment_index = scope.get("environment_index")
        if (
            isinstance(environment_index, bool)
            or not isinstance(environment_index, int)
            or environment_index < 0
        ):
            raise RecoveryError(
                "persisted delivery Operation environment index is invalid"
            )
        label = f"{label}-{environment_index:03d}"
    identity = sha256_bytes(run_id.encode("utf-8"))[:16]
    if not re.fullmatch(
        rf"runtime-{re.escape(identity)}-{re.escape(label)}-[0-9a-f]{{8}}",
        str(recorded_id),
    ) or not root.name.startswith(f"nm-v6-runtime-{label}-"):
        raise RecoveryError("persisted Operation workspace identity is invalid")
    if expected_commit is not None and source_commit != expected_commit:
        raise RecoveryError("persisted Operation workspace source binding changed")
    head = run_command(("git", "rev-parse", "--verify", "HEAD^{commit}"), cwd=path).stdout.strip()
    git_dir = Path(
        run_command(("git", "rev-parse", "--absolute-git-dir"), cwd=path).stdout.strip()
    ).resolve()
    remotes = run_command(("git", "remote"), cwd=path).stdout.splitlines()
    if head != source_commit or git_dir != path / ".git" or remotes:
        raise RecoveryError("persisted Operation workspace Git binding is invalid")
    manager = WorkspaceManager(target, root)
    return manager, Workspace(str(recorded_id), path, str(source_commit), None), root


class RuntimeOperationReconciler:
    """Compose project actions with reducer-backed observed-state reconciliation."""

    def __init__(self, target: Path, project: Mapping[str, Any], reducer: Any, store: Any, run_id: str) -> None:
        self.target = target.resolve()
        self.project = project
        self.definitions = validate_action_registry(project["action_definitions"])
        self.reducer = reducer
        self.store = store
        self.run_id = run_id

    def __call__(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        action_id = operation.get("action_id")
        if operation.get("operation_kind") == "protected_ref" and action_id in {
            "integrate_dev",
            "hotfix_stable",
            "hotfix_reconcile_dev",
            "release",
        }:
            return self._reconcile_protected_ref(operation)
        if not isinstance(action_id, str) or action_id not in self.definitions:
            raise RecoveryError("persisted operation names an unknown configured action")
        workspace, manager, temporary_root, disposable = self._workspace(operation)
        try:
            recorder = ReducerOperationRecorder(
                self.reducer,
                self.store,
                run_id=self.run_id,
                expected_revision=lambda: int(self.store.get_run(self.run_id)["revision"]),
                scope=dict(operation.get("scope", {})),
            )
            executor = ActionExecutor(
                isolation_backend=manager.isolation_backend,
                secret_resolver=_ProjectSecretResolver(self.target, self.project),
            )
            recovery = RecoveryController(self.definitions, executor, recorder)
            result = recovery.recover_nonterminal(
                operation, workspace=workspace, allow_network=True
            )
            observation = result.reconciliation or result.observation
            return {
                "classification": result.classification,
                "effect_id": observation.effect_id or operation.get("effect_id"),
                "result": observation.as_dict(),
                "persisted": True,
            }
        finally:
            if disposable:
                manager.dispose(workspace)
                shutil.rmtree(temporary_root, ignore_errors=True)

    def _reconcile_protected_ref(
        self, operation: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        scope = operation.get("scope", {})
        if not isinstance(scope, Mapping):
            raise RecoveryError("protected-ref Operation scope is malformed")
        branch = scope.get("protected_ref")
        source_commit = scope.get("source_commit")
        target_commit = scope.get("target_commit")
        if not all(
            isinstance(value, str) and value
            for value in (branch, source_commit, target_commit)
        ):
            raise RecoveryError("protected-ref Operation lacks exact ref bindings")
        reviewed_digest = scope.get("reviewed_proposal_digest")
        if not isinstance(reviewed_digest, str) or re.fullmatch(
            r"[0-9a-f]{64}", reviewed_digest
        ) is None:
            raise RecoveryError(
                "protected-ref Operation lacks its reviewed proposal digest"
            )
        proposal_events = [
            event
            for event in self.store.list_events(run_id=self.run_id)
            if event.get("event_type") == "MERGE_PROPOSED"
            and event.get("payload", {}).get("record", {}).get("operation_id")
            == operation.get("operation_id")
        ]
        if len(proposal_events) != 1:
            raise RecoveryError(
                "protected-ref Operation lacks one canonical reviewed proposal"
            )
        reviewed_record = proposal_events[0].get("payload", {}).get("record")
        if not isinstance(reviewed_record, Mapping):
            raise RecoveryError("canonical reviewed proposal record is malformed")
        unsigned_review = {
            key: value
            for key, value in reviewed_record.items()
            if key != "reviewed_proposal_digest"
        }
        if (
            reviewed_record.get("reviewed_proposal_digest") != reviewed_digest
            or sha256_bytes(canonical_json(unsigned_review)) != reviewed_digest
            or reviewed_record.get("merge_proposal")
            != scope.get("merge_proposal")
        ):
            raise RecoveryError(
                "protected-ref Operation reviewed proposal provenance drifted"
            )
        git_config = self.project["git"]
        git = GitController(
            self.target,
            remote=str(git_config["remote"]),
            stable_branch=str(git_config["stable_branch"]),
            integration_branch=str(git_config["integration_branch"]),
            work_branch_prefixes=tuple(git_config["work_branch_prefixes"]),
            hotfix_prefix=str(git_config["hotfix_prefix"]),
            protected_authority=StoreProtectedMutationAuthority(self.store),
        )
        local = git.resolve_commit(f"refs/heads/{branch}")
        remote = git.remote_head(str(branch))
        proposal_raw = scope.get("merge_proposal")
        proposal: MergeProposal | None = None
        if isinstance(proposal_raw, Mapping):
            try:
                proposal = MergeProposal(
                    source_ref=str(proposal_raw["source_ref"]),
                    source_commit=str(proposal_raw["source_commit"]),
                    target_ref=str(proposal_raw["target_ref"]),
                    target_commit=str(proposal_raw["target_commit"]),
                    purpose=str(proposal_raw["purpose"]),
                    sharing_status=str(proposal_raw["sharing_status"]),
                    strategy=str(proposal_raw["strategy"]),
                    rationale=str(proposal_raw["rationale"]),
                    candidate_tree=str(proposal_raw["candidate_tree"]),
                    expected_result_tree=str(
                        proposal_raw["expected_result_tree"]
                    ),
                    rollback_ref=str(proposal_raw["rollback_ref"]),
                    gate_ids=tuple(map(str, proposal_raw["gate_ids"])),
                    authorization_id=str(proposal_raw["authorization_id"]),
                )
            except (KeyError, TypeError, ValueError, ContractError) as exc:
                raise RecoveryError(
                    "protected-ref Operation merge proposal is malformed"
                ) from exc
            expected_digest = scope.get("merge_proposal_digest")
            if expected_digest != sha256_bytes(canonical_json(dict(proposal_raw))):
                raise RecoveryError("protected-ref merge proposal digest mismatch")

        def valid_result(commit: str) -> bool:
            if proposal is None:
                return commit == source_commit
            if git.tree_of(commit) != proposal.expected_result_tree:
                return False
            if proposal.strategy == "fast_forward":
                return commit == proposal.source_commit
            parents = run_command(
                ("git", "rev-list", "--parents", "-n", "1", commit),
                cwd=self.target,
            ).stdout.split()
            expected_parents = [proposal.target_commit]
            if proposal.strategy == "merge_commit":
                expected_parents.append(proposal.source_commit)
            return parents[1:] == expected_parents

        result_commit: str | None = None
        if local == remote and valid_result(local):
            result_commit = local
        elif proposal is not None and valid_result(local) and remote == target_commit:
            push = git.push_protected_cas(
                str(branch),
                expected_remote=str(target_commit),
                new_commit=local,
                proposal=proposal,
            )
            remote = push.observed_after
            result_commit = local
        elif proposal is not None and local == target_commit and valid_result(remote):
            run_command(
                (
                    "git",
                    "update-ref",
                    f"refs/heads/{branch}",
                    remote,
                    str(target_commit),
                ),
                cwd=self.target,
            )
            local = remote
            result_commit = remote

        if result_commit is not None and local == result_commit and remote == result_commit:
            classification = "completed"
            result = {
                "target_before": target_commit,
                "target_after": result_commit,
                "result_tree": git.tree_of(result_commit),
                "remote_after": remote,
                "classification": classification,
            }
            effect_id = f"git-{branch}-{operation['operation_id']}-{result_commit}"
        elif local == target_commit and remote == target_commit:
            classification = "not_started"
            result = {
                "target_before": target_commit,
                "target_after": target_commit,
                "remote_after": remote,
                "classification": classification,
            }
            effect_id = None
        else:
            classification = "unknown"
            result = {
                "expected_before": target_commit,
                "expected_after": source_commit,
                "local": local,
                "remote": remote,
                "classification": classification,
            }
            effect_id = operation.get("effect_id")
        return {
            "classification": classification,
            "effect_id": effect_id,
            "result": result,
            "persisted": False,
        }

    def _workspace(
        self, operation: Mapping[str, Any]
    ) -> tuple[Workspace, WorkspaceManager, Path, bool]:
        scope = operation.get("scope", {})
        if not isinstance(scope, Mapping):
            raise RecoveryError("persisted operation scope is malformed")
        reopened = _persisted_operation_workspace(
            self.target,
            operation,
            run_id=self.run_id,
        )
        if reopened is not None:
            manager, workspace, root = reopened
            return workspace, manager, root, False
        source = scope.get("source_commit")
        if not isinstance(source, str) or not source:
            source = run_command(("git", "rev-parse", "HEAD"), cwd=self.target).stdout.strip()
        root = temporary_workspace_root(prefix="nm-v6-reconcile-")
        manager = WorkspaceManager(self.target, root)
        workspace = manager.create(f"reconcile-{uuid.uuid4().hex[:12]}", commit=source)
        return workspace, manager, root, True


class _ProjectSecretResolver:
    """Resolve named project secrets only at the action boundary.

    The generated credential-free fixture uses ``fake`` references.  Ordinary
    projects may use an environment reference, but the value is never copied
    into evidence, adapter context, controller projections, or logs.  File and
    keychain providers intentionally remain fail-closed until a project-owned
    trusted resolver is configured.
    """

    def __init__(self, target: Path, project: Mapping[str, Any]) -> None:
        self.target = target.resolve()
        raw = project.get("secret_references")
        if not isinstance(raw, Mapping):
            raise ContractError("project has no secret reference registry")
        self.references = raw

    def __call__(self, reference: str) -> SecretValue:
        raw = self.references.get(reference)
        if not isinstance(raw, Mapping):
            raise ContractError(f"unknown project secret reference: {reference}")
        provider = raw.get("provider")
        env_name = "NM_V6_SECRET_" + re.sub(
            r"[^A-Za-z0-9_]", "_", reference.upper()
        )
        if provider == "fake":
            locator = raw.get("reference", raw.get("fake_id", reference))
            if not isinstance(locator, str) or not locator:
                raise ContractError("fake secret reference has no fixture identifier")
            return SecretValue(reference, env_name, f"fixture-only-{locator}")
        if provider == "environment":
            locator = raw.get("env")
            if not isinstance(locator, str) or not locator:
                raise ContractError("environment secret reference has no variable name")
            value = os.environ.get(locator)
            if value is None or not value:
                raise ContractError(
                    f"required environment secret reference is unavailable: {reference}"
                )
            return SecretValue(reference, env_name, value)
        raise ContractError(
            f"secret provider {provider!r} requires a trusted project resolver"
        )


@dataclass
class _BatchAttemptContext:
    definition: TaskDefinition
    task: Mapping[str, Any]
    phase: Mapping[str, Any]
    task_index: int
    task_entity_id: str
    attempt_id: str
    operation_id: str
    lease: Lease | None
    binding: dict[str, Any]
    request: dict[str, Any]
    manager: WorkspaceManager
    workspace: Workspace
    root: Path
    adapter: Any | None = None
    session_id: str | None = None


class _TaskBatchAttention(TransitionError):
    """A fully reconciled Task batch stopped before candidate integration."""


class ConfiguredRuntimeEngine:
    """Execute an ordinary normal run through the configured deterministic core.

    Each invocation handles one canonical run state.  Pure or advisory work may
    be repeated after a crash; every protected/external effect is preceded by a
    persisted gate and authorization and is recorded through the reducer.
    """

    _GATE_NUMBERS = {
        "SPEC_GATE": 1,
        "PLAN_GATE": 2,
        "TASK_GATE": 100,
        "PHASE_GATE": 300,
        "DEV_INTEGRATION_GATE": 400,
        "DEV_INTEGRATION_RESULT_GATE": 500,
        "HOTFIX_STABLE_GATE": 520,
        "HOTFIX_STABLE_RESULT_GATE": 530,
        "HOTFIX_RECONCILIATION_GATE": 540,
        "HOTFIX_RECONCILIATION_RESULT_GATE": 550,
        "RELEASE_GATE": 600,
        "RELEASE_RESULT_GATE": 610,
        "DEPLOY_GATE": 700,
        "POST_DEPLOY_GATE": 710,
        "ROLLBACK_GATE": 720,
        "POST_ROLLBACK_GATE": 730,
        "COMPLETION_GATE": 800,
    }

    def __init__(
        self,
        target: Path,
        project: Mapping[str, Any],
        reducer: Any,
        store: Any,
        *,
        run_id: str,
        version_baseline: Mapping[str, Any],
    ) -> None:
        self.target = target.resolve()
        self.project = project
        self.reducer = reducer
        self.store = store
        self.run_id = run_id
        self.version_baseline = validate_version_record(version_baseline)
        self.definitions = validate_action_registry(project["action_definitions"])
        self.evidence_store = getattr(reducer, "evidence_store", None) or EvidenceStore(
            self.target / ".nm/runtime/v6/evidence"
        )
        git_config = project["git"]
        self.git = GitController(
            self.target,
            remote=str(git_config["remote"]),
            stable_branch=str(git_config["stable_branch"]),
            integration_branch=str(git_config["integration_branch"]),
            work_branch_prefixes=tuple(git_config["work_branch_prefixes"]),
            hotfix_prefix=str(git_config["hotfix_prefix"]),
            protected_authority=StoreProtectedMutationAuthority(store),
            cleanup_store=store,
        )
        persisted_run = store.get_run(run_id)
        persisted_payload = (
            persisted_run.get("payload", {})
            if isinstance(persisted_run, Mapping)
            else {}
        )
        persisted_traceability = (
            persisted_payload.get("traceability")
            if isinstance(persisted_payload, Mapping)
            else None
        )
        if not isinstance(persisted_traceability, Mapping):
            raise ContractError(
                "configured runtime requires persisted canonical traceability"
            )
        from .specs import validate_traceability

        validate_traceability(persisted_traceability)
        self.traceability = dict(persisted_traceability)
        self.identity = sha256_bytes(run_id.encode("utf-8"))[:16]
        self.last_result: dict[str, Any] = self._result(
            "waiting_for_input", self._current(), waiting_for="runtime_state"
        )

    def __call__(self, run: Mapping[str, Any]) -> bool | None:
        handlers: dict[str, Callable[[Mapping[str, Any]], bool]] = {
            "SPEC_AWAITING_CONFIRMATION": self._confirm_spec,
            "PLANNING": self._plan,
            "READY": self._start_hotfix,
            "IMPLEMENTING": self._implement_phase,
            "PHASE_VERIFYING": self._verify_phase,
            "PHASE_AWAITING_ACCEPTANCE": self._await_phase_acceptance,
            "INTEGRATING_DEV": self._integrate_dev,
            "INTEGRATION_VERIFYING": self._verify_dev_integration,
            "HOTFIX_IMPLEMENTING": self._implement_hotfix,
            "HOTFIX_VERIFYING": self._prepare_hotfix_stable,
            "HOTFIX_INTEGRATING_STABLE": self._apply_hotfix_stable,
            "HOTFIX_STABLE_VERIFYING": self._prepare_hotfix_dev_reconciliation,
            "HOTFIX_RECONCILING_DEV": self._apply_hotfix_dev_reconciliation,
            "HOTFIX_DEV_VERIFYING": self._verify_hotfix_dev_reconciliation,
            "RELEASE_READY": self._prepare_release,
            "RELEASING": self._release,
            "DEPLOY_READY": self._prepare_deployment,
            "DEPLOYING": self._deploy,
            "POST_DEPLOY_VERIFYING": self._complete,
            "ROLLBACK_REQUIRED": self._prepare_rollback,
            "ROLLING_BACK": self._rollback,
            "POST_ROLLBACK_VERIFYING": self._verify_rollback,
        }
        handler = handlers.get(str(run["state"]))
        if handler is None:
            return None
        return handler(run)

    # -- Spec and plan -----------------------------------------------------

    def _confirm_spec(self, run: Mapping[str, Any]) -> bool:
        from .specs import (
            canonical_spec_hash,
            validate_confirmation_binding,
            validate_spec,
            validate_traceability,
        )

        confirmation = self._confirmation(run)
        if confirmation is None:
            return self._wait(run, "signed_spec_confirmation")
        parsed = validate_spec(
            self.target / str(self.project["spec"]["document"]),
            traceability=self.traceability,
        )
        report = validate_traceability(self.traceability)
        validate_confirmation_binding(parsed, confirmation)
        if canonical_spec_hash(parsed) != run["spec_hash"]:
            raise ContractError("canonical Spec differs from the planned run")
        assertions = {
            "schema_valid": True,
            "ids_unique": len(
                set(
                    (*report.goal_ids, *report.requirement_ids, *report.acceptance_ids,
                     *report.phase_ids, *report.task_ids)
                )
            )
            == sum(
                len(values)
                for values in (
                    report.goal_ids,
                    report.requirement_ids,
                    report.acceptance_ids,
                    report.phase_ids,
                    report.task_ids,
                )
            ),
            "stage_annotations_valid": True,
            "mandatory_traceability_complete": set(
                report.mandatory_acceptance_ids
            ).issubset(report.covered_acceptance_ids),
            "canonical_spec_hash_valid": parsed.spec_hash == run["spec_hash"],
            "trusted_confirmation_valid": True,
        }
        evidence_id = self._evidence(
            1,
            "spec-contract",
            {
                "spec_id": parsed.metadata["spec_id"],
                "version": parsed.metadata["version"],
                "traceability": report.__dict__,
                "confirmation_id": self._authorization_id(confirmation),
            },
            assertions=assertions,
        )
        gate_id = self._gate(
            "SPEC_GATE",
            (evidence_id,),
            authorization_id=self._authorization_id(confirmation),
        )
        return self._transition(
            run,
            "CONFIRM_SPEC",
            gate_ids=(gate_id,),
            authorization_id=self._authorization_id(confirmation),
        )

    def _plan(self, run: Mapping[str, Any]) -> bool:
        from .specs import validate_traceability

        report = validate_traceability(self.traceability)
        release_decision, deploy_decision, delivery_order = self._delivery_contract()
        graph = self._task_graph()
        graph.topological_order()
        acceptance_actions = self.traceability.get("acceptance_actions")
        if not isinstance(acceptance_actions, Mapping):
            raise ContractError("traceability acceptance_actions must be an object")
        missing_actions = sorted(
            {
                action_id
                for action_id in acceptance_actions.values()
                if not isinstance(action_id, str) or action_id not in self.definitions
            },
            key=str,
        )
        if missing_actions:
            raise ContractError(
                "traceability acceptance action is not configured: "
                + ", ".join(map(str, missing_actions))
            )
        assertions = {
            "task_dag_valid": tuple(graph.topological_order()) == report.task_ids
            or set(graph.topological_order()) == set(report.task_ids),
            "mandatory_acceptance_covered": set(
                report.mandatory_acceptance_ids
            ).issubset(report.covered_acceptance_ids),
            "path_bounds_declared": all(task.write_set for task in graph.tasks.values()),
            "actions_declared": not missing_actions,
            "dependencies_declared": all(
                isinstance(item.get("depends_on", []), list)
                for item in self._tasks()
            ),
            "write_sets_declared": all(
                isinstance(item.get("write_set"), list) and item["write_set"]
                for item in self._tasks()
            ),
        }
        evidence_id = self._evidence(
            2,
            "plan-contract",
            {
                "task_order": graph.topological_order(),
                "phases": report.phase_ids,
                "mandatory_acceptance": report.mandatory_acceptance_ids,
                "delivery": {
                    "release": release_decision,
                    "deploy": deploy_decision,
                    "environments": list(delivery_order),
                },
            },
            assertions=assertions,
        )
        gate_id = self._gate("PLAN_GATE", (evidence_id,))
        return self._transition(
            run,
            "PLAN_READY",
            gate_ids=(gate_id,),
            state_patch={
                "runtime_completed_tasks": [],
                "runtime_completed_phases": [],
                "runtime_delivery_order": list(delivery_order),
                "runtime_delivery_completed": [],
            },
        )

    # -- common canonical helpers ----------------------------------------

    def _result(
        self,
        result: str,
        run: Mapping[str, Any],
        *,
        waiting_for: str | None = None,
        event: str | None = None,
    ) -> dict[str, Any]:
        value = {
            "schema_version": DISPATCH_RESULT_SCHEMA,
            "result": result,
            "run_id": self.run_id,
            "state": run["state"],
            "revision": int(run["revision"]),
        }
        if waiting_for is not None:
            value["waiting_for"] = waiting_for
        if event is not None:
            value["event"] = event
        return value

    def _wait(self, run: Mapping[str, Any], reason: str) -> bool:
        self.last_result = self._result(
            "waiting_for_input", run, waiting_for=reason
        )
        return False

    def _record_domain_once(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        for event in self.store.list_events(run_id=self.run_id):
            if event.get("idempotency_key") != idempotency_key:
                continue
            if event.get("event_type") != event_type:
                raise ContractError(
                    f"persisted domain event type differs on replay: {idempotency_key}"
                )
            record = event.get("payload", {}).get("record")
            if record != dict(payload):
                raise ContractError(
                    f"persisted {event_type} event differs on replay"
                )
            return dict(record)
        self.reducer.record_domain_event(
            run_id=self.run_id,
            expected_revision=self._revision(),
            event_type=event_type,
            payload=dict(payload),
            idempotency_key=idempotency_key,
            actor="nm-v6-configured-runtime",
        )
        return dict(payload)

    def _domain_record(
        self,
        event_type: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        matches = [
            event
            for event in self.store.list_events(run_id=self.run_id)
            if event.get("idempotency_key") == idempotency_key
        ]
        if not matches:
            return None
        if len(matches) != 1 or matches[0].get("event_type") != event_type:
            raise ContractError(
                f"canonical domain event binding is ambiguous: {idempotency_key}"
            )
        record = matches[0].get("payload", {}).get("record")
        if not isinstance(record, Mapping):
            raise ContractError(
                f"canonical domain event record is malformed: {idempotency_key}"
            )
        return dict(record)

    def _reconcile_operation(self, operation_id: str) -> Mapping[str, Any] | None:
        operation = self.store.get_operation(operation_id)
        if not isinstance(operation, Mapping):
            return None
        if operation.get("status") not in {"started", "partial", "unknown"}:
            return operation
        observed = RuntimeOperationReconciler(
            self.target, self.project, self.reducer, self.store, self.run_id
        )(operation)
        if observed.get("persisted") is not True:
            classification = str(observed.get("classification"))
            self.reducer.record_operation_observation(
                OperationObservation(
                    operation_id=operation_id,
                    action_id=str(operation["action_id"]),
                    status=(
                        "succeeded"
                        if classification == "completed"
                        else classification
                    ),
                    effect_id=(
                        str(observed["effect_id"])
                        if observed.get("effect_id") is not None
                        else None
                    ),
                    result=dict(observed.get("result", {})),
                ),
                run_id=self.run_id,
                expected_revision=self._revision(),
                idempotency_key=(
                    f"configured-runtime:reconcile:{operation_id}:"
                    f"{classification}"
                ),
                actor="nm-v6-configured-runtime",
            )
        current = self.store.get_operation(operation_id)
        return current if isinstance(current, Mapping) else None

    def _transition(
        self,
        run: Mapping[str, Any],
        event: str,
        *,
        payload: Mapping[str, Any] | None = None,
        state_patch: Mapping[str, Any] | None = None,
        gate_ids: Sequence[str] = (),
        authorization_id: str | None = None,
    ) -> bool:
        body = dict(payload or {})
        if state_patch:
            body["state_patch"] = dict(state_patch)
        expected_revision = self._revision()
        self.reducer.transition(
            TransitionProposal(
                run_id=self.run_id,
                expected_revision=expected_revision,
                event=event,
                actor="nm-v6-configured-runtime",
                idempotency_key=(
                    f"configured-runtime:{self.run_id}:{event}:{run['state']}:"
                    f"{expected_revision}"
                ),
                payload=body,
                gate_ids=tuple(gate_ids),
                authorization_id=authorization_id,
            )
        )
        latest = self._current()
        self.last_result = self._result("driven", latest, event=event)
        return True

    def _current(self) -> dict[str, Any]:
        run = self.store.get_run(self.run_id)
        if not isinstance(run, Mapping):
            raise ContractError(f"unknown configured run: {self.run_id}")
        return dict(run)

    def _revision(self) -> int:
        return int(self._current()["revision"])

    @staticmethod
    def _payload(run: Mapping[str, Any]) -> dict[str, Any]:
        payload = run.get("payload", {})
        return dict(payload) if isinstance(payload, Mapping) else {}

    def _tasks(self) -> list[Mapping[str, Any]]:
        tasks = self.traceability.get("tasks")
        if not isinstance(tasks, list) or not all(
            isinstance(item, Mapping) for item in tasks
        ):
            raise ContractError("traceability tasks must be an object array")
        return list(tasks)

    def _phases(self) -> list[Mapping[str, Any]]:
        phases = self.traceability.get("phases")
        if not isinstance(phases, list) or not all(
            isinstance(item, Mapping) for item in phases
        ):
            raise ContractError("traceability phases must be an object array")
        return list(phases)

    def _task_graph(self) -> TaskGraph:
        return TaskGraph(
            TaskDefinition(
                str(item["id"]),
                dependencies=tuple(item.get("depends_on", [])),
                write_set=tuple(item.get("write_set", [])),
                optional=bool(item.get("optional", False)),
            )
            for item in self._tasks()
        )

    def _confirmation(self, run: Mapping[str, Any]) -> Mapping[str, Any] | None:
        for record in reversed(self.store.list_authorizations(self.run_id)):
            if (
                record.get("record_type") == "spec_confirmation"
                and record.get("spec_hash") == run["spec_hash"]
                and record.get("decision") == "confirmed"
                and not self.store.authorization_is_revoked(
                    self._authorization_id(record)
                )
            ):
                validate_authorization_record(record)
                return record
        return None

    @staticmethod
    def _authorization_id(record: Mapping[str, Any]) -> str:
        for field in ("confirmation_id", "grant_id", "approval_id"):
            value = record.get(field)
            if isinstance(value, str) and value:
                return value
        raise ContractError("authorization record has no canonical identifier")

    def _authorization(
        self,
        action: str,
        *,
        environment: str | None = None,
        protected_ref: str | None = None,
    ) -> Mapping[str, Any] | None:
        run = self._current()
        expected_type = "grant" if run.get("mode") == "auto" else "approval"
        for record in reversed(self.store.list_authorizations(self.run_id)):
            if record.get("record_type") != expected_type:
                continue
            authorization_id = self._authorization_id(record)
            if self.store.authorization_is_revoked(authorization_id):
                continue
            try:
                validate_authorization_record(record)
            except Exception:
                continue
            if authorization_scope_allows(
                record,
                run_id=self.run_id,
                spec_hash=str(run["spec_hash"]),
                config_hash=str(run["config_hash"]),
                action=action,
                environment=environment,
                protected_ref=protected_ref,
            ):
                return record
        return None

    def _id(self, prefix: str, number: int, *, scope: str | None = None) -> str:
        if not 0 <= number <= 999:
            raise ContractError("configured runtime identifier sequence overflow")
        if scope is not None and (
            not scope or re.fullmatch(r"[A-Za-z0-9._-]+", scope) is None
        ):
            raise ContractError("configured runtime identifier scope is invalid")
        scoped = f"-{scope}" if scope else ""
        return f"{prefix}-runtime-{self.identity}{scoped}-{number:03d}"

    def _gate_id(
        self, gate_type: str, *, offset: int = 0, scope: str | None = None
    ) -> str:
        return self._id(
            "GATE", self._GATE_NUMBERS[gate_type] + offset, scope=scope
        )

    def _entity_id(self, traceability_id: str) -> str:
        return f"{self.identity}.{traceability_id}"

    def _ensure_entity(
        self,
        machine: str,
        entity_id: str,
        *,
        initial_state: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        existing = self.store.get_entity_state(machine, entity_id)
        if isinstance(existing, Mapping):
            if existing.get("run_id") != self.run_id:
                raise ContractError(f"{machine} entity belongs to another run")
            return dict(existing)
        self.reducer.create_entity(
            run_id=self.run_id,
            expected_revision=self._revision(),
            machine=machine,
            entity_id=entity_id,
            initial_state=initial_state,
            payload=dict(payload),
            idempotency_key=f"configured-runtime:entity:{machine}:{entity_id}",
            actor="nm-v6-configured-runtime",
        )
        value = self.store.get_entity_state(machine, entity_id)
        if not isinstance(value, Mapping):
            raise ContractError(f"created {machine} entity is unavailable")
        return dict(value)

    def _entity_transition(
        self,
        machine: str,
        entity_id: str,
        event: str,
        *,
        payload: Mapping[str, Any] | None = None,
        gate_ids: Sequence[str] = (),
        authorization_id: str | None = None,
        fencing_token: int | None = None,
    ) -> dict[str, Any]:
        entity = self.store.get_entity_state(machine, entity_id)
        if not isinstance(entity, Mapping):
            raise ContractError(f"unknown configured {machine} entity: {entity_id}")
        body = dict(payload or {})
        return self.reducer.transition(
            TransitionProposal(
                run_id=self.run_id,
                expected_revision=self._revision(),
                event=event,
                actor="nm-v6-configured-runtime",
                idempotency_key=(
                    f"configured-runtime:entity:{machine}:{entity_id}:{event}:"
                    f"{int(entity['revision'])}"
                ),
                payload=body,
                gate_ids=tuple(gate_ids),
                authorization_id=authorization_id,
                fencing_token=fencing_token,
            ),
            machine=machine,
            entity_id=entity_id,
        )

    def _evidence(
        self,
        number: int,
        label: str,
        observation: Mapping[str, Any],
        *,
        assertions: Mapping[str, bool],
        source_commit: str | None = None,
        candidate_commit: str | None = None,
        release_source_kind: str | None = None,
        release_source_commit: str | None = None,
        release_source_tree: str | None = None,
        hotfix_reconciliation_gate_id: str | None = None,
        artifact_digest: str | None = None,
        environment_id: str | None = None,
        environment_fingerprint: str | None = None,
        operation_id: str | None = None,
        attempt_id: str | None = None,
        subject_ids: Sequence[str] = (),
        scope: str | None = None,
    ) -> str:
        evidence_id = self._id("EVID", number, scope=scope)
        existing = self.store.get_evidence(evidence_id)
        subjects = list(dict.fromkeys([label, *subject_ids]))
        expected_stdout_digest = sha256_bytes(canonical_json(dict(observation)))
        expected_stderr_digest = sha256_bytes(b"")
        bindings = {
            "source_commit": source_commit,
            "candidate_commit": candidate_commit,
            "release_source_kind": release_source_kind,
            "release_source_commit": release_source_commit,
            "release_source_tree": release_source_tree,
            "hotfix_reconciliation_gate_id": hotfix_reconciliation_gate_id,
            "artifact_digest": artifact_digest,
            "environment_id": environment_id,
            "environment_fingerprint": environment_fingerprint,
            "operation_id": operation_id,
            "attempt_id": attempt_id,
        }
        if isinstance(existing, Mapping):
            self.evidence_store.validate(existing)
            expected = {
                "run_id": self.run_id,
                "spec_hash": self._current()["spec_hash"],
                "config_hash": self._current()["config_hash"],
                **bindings,
            }
            if any(existing.get(field) != value for field, value in expected.items()):
                raise ContractError(f"persisted runtime evidence drifted: {evidence_id}")
            if (
                existing.get("subject_ids") != subjects
                or existing.get("stdout_digest") != expected_stdout_digest
                or existing.get("stderr_digest") != expected_stderr_digest
                or existing.get("tool_versions") != self.version_baseline
                or existing.get("evaluator_version")
                != self.version_baseline["evaluator"]
            ):
                raise ContractError(
                    f"persisted runtime evidence observation drifted: {evidence_id}"
                )
            if any(
                existing.get("assertions", {}).get(name) is not value
                for name, value in assertions.items()
            ):
                raise ContractError(
                    f"persisted runtime evidence assertions drifted: {evidence_id}"
                )
            return evidence_id
        run = self._current()
        timestamp = utc_now()
        receipt = self.evidence_store.persist(
            {
                "evidence_id": evidence_id,
                "evidence_type": "configured_runtime_observation",
                "producer": "nm-v6-configured-runtime-core",
                "run_id": self.run_id,
                "subject_ids": subjects,
                "assertions": dict(assertions),
                "spec_hash": run["spec_hash"],
                "config_hash": run["config_hash"],
                **bindings,
                "command_action_id": label,
                "argv_digest": sha256_bytes(label.encode("utf-8")),
                "working_directory": ".",
                "started_at": timestamp,
                "finished_at": timestamp,
                "exit_code": 0 if all(assertions.values()) else 1,
                "result": "passed" if all(assertions.values()) else "failed",
                "tool_versions": dict(self.version_baseline),
                "producer_version": "nm-v6/configured-runtime-v1",
                "evaluator_version": self.version_baseline["evaluator"],
            },
            canonical_json(dict(observation)),
            b"",
        )
        self.reducer.record_evidence(
            run_id=self.run_id,
            expected_revision=self._revision(),
            receipt=receipt,
            idempotency_key=f"configured-runtime:evidence:{evidence_id}",
            actor="nm-v6-configured-runtime",
        )
        return evidence_id

    def _gate(
        self,
        gate_type: str,
        evidence_ids: Sequence[str],
        *,
        offset: int = 0,
        authorization_id: str | None = None,
        bindings: Mapping[str, Any] | None = None,
        mandatory_acceptance_ids: Sequence[str] = (),
        acceptance_evidence: Mapping[str, Sequence[str]] | None = None,
        not_applicable: bool = False,
        subject_ids: Sequence[str] = (),
        scope: str | None = None,
    ) -> str:
        gate_id = self._gate_id(gate_type, offset=offset, scope=scope)
        expected_subjects = list(tuple(subject_ids) or (self.run_id,))
        expected_acceptance_evidence = {
            key: list(value) for key, value in (acceptance_evidence or {}).items()
        }
        existing = self.store.get_gate(gate_id)
        if isinstance(existing, Mapping):
            if (
                existing.get("gate_type") != gate_type
                or existing.get("run_id") != self.run_id
                or existing.get("result")
                not in ({"not_applicable"} if not_applicable else {"passed"})
                or existing.get("authorization_id") != authorization_id
                or existing.get("subject_ids") != expected_subjects
                or existing.get("evidence_ids") != list(evidence_ids)
                or existing.get("mandatory_acceptance_ids")
                != list(mandatory_acceptance_ids)
                or existing.get("acceptance_evidence")
                != expected_acceptance_evidence
                or any(
                    existing.get(field) != value
                    for field, value in dict(bindings or {}).items()
                )
            ):
                raise ContractError(f"persisted runtime gate drifted: {gate_id}")
            return gate_id
        receipts: dict[str, Mapping[str, Any]] = {}
        for evidence_id in evidence_ids:
            receipt = self.store.get_evidence(evidence_id)
            if not isinstance(receipt, Mapping):
                raise ContractError(f"runtime gate evidence is unavailable: {evidence_id}")
            self.evidence_store.validate(receipt)
            receipts[evidence_id] = receipt
        prerequisite_names = (
            ("spec_explicitly_not_applicable", "stage_traceability_valid", "not_applicable_decision_valid")
            if not_applicable
            else GATE_DEFINITIONS[gate_type].prerequisites
        )
        prerequisite_evidence: dict[str, list[str]] = {}
        for prerequisite in prerequisite_names:
            supporting = [
                evidence_id
                for evidence_id, receipt in receipts.items()
                if receipt.get("assertions", {}).get(prerequisite) is True
            ]
            if not supporting:
                raise ContractError(
                    f"no core evidence supports {gate_type} prerequisite {prerequisite}"
                )
            prerequisite_evidence[prerequisite] = supporting
        facts: dict[str, Any] = {
            prerequisite: True for prerequisite in prerequisite_names
        }
        facts.update(
            {
                "run_id": self.run_id,
                "not_applicable": not_applicable,
                "prerequisite_evidence": prerequisite_evidence,
                "mandatory_acceptance_ids": list(mandatory_acceptance_ids),
                "acceptance_evidence": {
                    key: list(value)
                    for key, value in expected_acceptance_evidence.items()
                },
            }
        )
        facts.update(dict(bindings or {}))
        run = self._current()
        decision = GateEvaluator(
            self.store.get_evidence,
            evidence_validator=self.evidence_store.validate,
            evaluator_version=str(self.version_baseline["evaluator"]),
        ).evaluate(
            GateObservation(
                gate_type=gate_type,
                subject_ids=tuple(expected_subjects),
                context=facts,
                evidence_ids=tuple(evidence_ids),
                evaluator="nm-v6-configured-runtime",
                authorization_id=authorization_id,
            ),
            gate_id=gate_id,
            spec_hash=str(run["spec_hash"]),
            config_hash=str(run["config_hash"]),
            run_revision=int(run["revision"]),
        )
        expected = "not_applicable" if not_applicable else "passed"
        if decision["result"] != expected:
            raise ContractError(
                f"configured runtime gate failed: {gate_type}: {decision['reason']}"
            )
        self.reducer.record_gate(
            run_id=self.run_id,
            expected_revision=self._revision(),
            decision=decision,
            idempotency_key=f"configured-runtime:gate:{gate_id}",
            actor="nm-v6-configured-runtime",
        )
        return gate_id

    def _workspace(
        self, commit: str, label: str
    ) -> tuple[WorkspaceManager, Workspace, Path]:
        root = temporary_workspace_root(prefix=f"nm-v6-runtime-{label}-")
        manager = WorkspaceManager(self.target, root)
        workspace = manager.create(
            f"runtime-{self.identity}-{label}-{uuid.uuid4().hex[:8]}",
            commit=commit,
        )
        return manager, workspace, root

    def _operation_workspace(
        self,
        operation: Mapping[str, Any] | None,
        *,
        commit: str,
        label: str,
        allow_completed_rebuild: bool = False,
    ) -> tuple[WorkspaceManager, Workspace, Path]:
        if isinstance(operation, Mapping):
            try:
                reopened = _persisted_operation_workspace(
                    self.target,
                    operation,
                    run_id=self.run_id,
                    expected_commit=commit,
                )
            except RecoveryError:
                scope = operation.get("scope", {})
                path_was_recorded = (
                    isinstance(scope, Mapping)
                    and scope.get("workspace_path") is not None
                )
                if not (
                    allow_completed_rebuild
                    and operation.get("status") == "completed"
                    and path_was_recorded
                    and not Path(str(scope["workspace_path"])).exists()
                    and not Path(str(scope["workspace_path"])).is_symlink()
                ):
                    raise
                reopened = None
            if reopened is not None:
                return reopened
            if not (
                allow_completed_rebuild
                and operation.get("status") == "completed"
            ):
                raise RecoveryError(
                    "persisted Operation has no reusable workspace binding"
                )
        return self._workspace(commit, label)

    @staticmethod
    def _dispose_workspace(
        manager: WorkspaceManager, workspace: Workspace, root: Path
    ) -> None:
        manager.dispose(workspace)
        shutil.rmtree(root, ignore_errors=True)

    def _execute(
        self,
        executor: ActionExecutor,
        workspace: Workspace,
        action_id: str,
        *,
        core_env: Mapping[str, str] | None = None,
        allow_network: bool = False,
    ) -> ActionResult:
        result = executor.execute(
            self.definitions[action_id],
            workspace=workspace,
            operation_id=None,
            core_env=core_env,
            allow_network=allow_network,
        )
        if result.status != "succeeded":
            raise ContractError(f"configured action failed: {action_id}")
        return result

    def _adapter_provider(self) -> str | None:
        configured = self.project.get("adapters")
        if not isinstance(configured, Mapping):
            return None
        providers = configured.get("configured")
        if isinstance(providers, list):
            if len(providers) != 1:
                return None
            return str(providers[0])
        if len(configured) != 1:
            return None
        item = next(iter(configured.values()))
        return str(item.get("provider")) if isinstance(item, Mapping) else None

    def _candidate_branch(self) -> str:
        prefix = (
            self.git.hotfix_prefix
            if self._current().get("run_kind") == "hotfix"
            else "task/"
        )
        return f"{prefix}nm-v6-runtime-{self.identity}"

    def _ensure_candidate_branch(
        self, *, hotfix_authorization_id: str | None = None
    ) -> tuple[str, str]:
        branch = self._candidate_branch()
        ref = f"refs/heads/{branch}"
        run = self._current()
        hotfix = run.get("run_kind") == "hotfix"
        if hotfix:
            remote_base = self.git.fetch_stable(reconcile_local=True)
            base_ref = self.git.stable_branch
        else:
            remote_base = self.git.fetch_dev(reconcile_local=True)
            base_ref = self.git.integration_branch
        binding_key = f"configured-runtime:candidate-branch:{self.identity}"
        binding = self._domain_record(
            "CANDIDATE_BRANCH_BOUND", idempotency_key=binding_key
        )
        existing = self.git.try_resolve_commit(ref)
        if binding is None:
            if existing is not None:
                raise RecoveryError(
                    "candidate branch pre-exists without controller-owned provenance"
                )
            if hotfix and not hotfix_authorization_id:
                raise ContractError(
                    "hotfix branch creation requires trusted hotfix authorization"
                )
            binding = self._record_domain_once(
                "CANDIDATE_BRANCH_BOUND",
                {
                    "branch": branch,
                    "ref": ref,
                    "run_id": self.run_id,
                    "base_kind": "stable" if hotfix else "dev",
                    "base_ref": base_ref,
                    "base_commit": remote_base,
                    "authorization_id": hotfix_authorization_id,
                    "spec_hash": run["spec_hash"],
                    "config_hash": run["config_hash"],
                },
                idempotency_key=binding_key,
            )
            checkpoint("runtime.after_candidate_branch_binding")
            if hotfix:
                self.git.create_hotfix_branch(
                    branch,
                    authorization_id=str(hotfix_authorization_id),
                    expected_remote_stable=remote_base,
                )
            else:
                run_command(
                    ("git", "update-ref", ref, remote_base, "0" * 40),
                    cwd=self.target,
                )
            return branch, remote_base
        expected_binding = {
            "branch": branch,
            "ref": ref,
            "run_id": self.run_id,
            "base_kind": "stable" if hotfix else "dev",
            "base_ref": base_ref,
            "spec_hash": run["spec_hash"],
            "config_hash": run["config_hash"],
        }
        if any(binding.get(key) != value for key, value in expected_binding.items()):
            raise RecoveryError("candidate branch provenance binding drifted")
        initial = binding.get("base_commit")
        if not isinstance(initial, str) or not initial:
            raise RecoveryError("candidate branch provenance lacks its exact remote base")
        if hotfix and remote_base != initial:
            raise RecoveryError(
                "remote stable moved after the hotfix branch base was recorded"
            )
        if existing is None:
            if hotfix:
                authorization_id = binding.get("authorization_id")
                if not isinstance(authorization_id, str) or not authorization_id:
                    raise RecoveryError(
                        "hotfix branch provenance lacks its authorization"
                    )
                self.git.create_hotfix_branch(
                    branch,
                    authorization_id=authorization_id,
                    expected_remote_stable=initial,
                )
            else:
                run_command(
                    ("git", "update-ref", ref, initial, "0" * 40),
                    cwd=self.target,
                )
            existing = initial
        gated_progress: list[
            tuple[int, int, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]
        ] = []
        for index, task in enumerate(self._tasks(), start=1):
            gate = self.store.get_gate(
                self._gate_id("TASK_GATE", offset=index)
            )
            if not isinstance(gate, Mapping):
                continue
            if gate.get("result") != "passed":
                raise RecoveryError("candidate progress cites a non-passing TASK_GATE")
            candidate = gate.get("candidate_commit")
            if not isinstance(candidate, str) or not candidate:
                raise RecoveryError("candidate progress gate lacks its commit binding")
            receipts = []
            for evidence_id in gate.get("evidence_ids", []):
                receipt = self.store.get_evidence(str(evidence_id))
                if not isinstance(receipt, Mapping):
                    raise RecoveryError("candidate progress evidence is missing")
                self.evidence_store.validate(receipt)
                receipts.append(receipt)
            task_receipt = next(
                (
                    receipt
                    for receipt in reversed(receipts)
                    if str(task["id"]) in receipt.get("subject_ids", [])
                    and receipt.get("candidate_commit") == candidate
                ),
                None,
            )
            if (
                task_receipt is None
                or task_receipt.get("candidate_commit") != candidate
            ):
                raise RecoveryError("candidate progress evidence chain is invalid")
            run_revision = gate.get("run_revision")
            if isinstance(run_revision, bool) or not isinstance(run_revision, int):
                raise RecoveryError("candidate progress gate revision is invalid")
            gated_progress.append(
                (run_revision, index, task, gate, task_receipt)
            )
        gated_progress.sort(key=lambda item: (item[0], item[1]))
        integration_progress: list[
            tuple[int, Mapping[str, Any], Mapping[str, Any]]
        ] = []
        for event in self.store.list_events(run_id=self.run_id):
            if event.get("event_type") != "CANDIDATE_BRANCH_ADVANCED":
                continue
            record = event.get("payload", {}).get("record", {})
            if (
                not isinstance(record, Mapping)
                or record.get("reason") != "reviewed_dev_integration_result"
                or record.get("branch") != branch
                or record.get("run_id") != self.run_id
            ):
                continue
            gate = self.store.get_gate(str(record.get("gate_id", "")))
            if (
                not isinstance(gate, Mapping)
                or gate.get("gate_type") != "DEV_INTEGRATION_RESULT_GATE"
                or gate.get("result") != "passed"
                or gate.get("candidate_commit") != record.get("candidate_commit")
                or gate.get("target_commit") != record.get("candidate_commit")
            ):
                raise RecoveryError(
                    "candidate integration progress lacks its exact result gate"
                )
            integration_progress.append(
                (int(event["run_revision"]), record, gate)
            )
        progress = initial
        last: tuple[
            int, int, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]
        ] | None = None
        last_step: tuple[str, str, str] | None = None
        ordered_progress = [
            (item[0], 0, "task", item) for item in gated_progress
        ] + [
            (item[0], 1, "integration", item) for item in integration_progress
        ]
        ordered_progress.sort(key=lambda item: (item[0], item[1]))
        for _revision, _priority, kind, item in ordered_progress:
            if kind == "integration":
                _event_revision, record, _gate = item
                source = str(record.get("source_commit", ""))
                candidate = str(record.get("candidate_commit", ""))
                if source != progress or not candidate:
                    raise RecoveryError(
                        "candidate integration progress chain is invalid"
                    )
                progress = candidate
                last_step = (kind, source, candidate)
                continue
            _gate_revision, _index, _task, gate, task_receipt = item
            source = str(task_receipt.get("source_commit", ""))
            if source != progress:
                raise RecoveryError("candidate progress evidence chain is invalid")
            candidate = str(gate["candidate_commit"])
            progress = candidate
            last = item
            last_step = (kind, source, candidate)
        if existing != progress:
            if last_step is None:
                raise RecoveryError(
                    "candidate branch head differs from its canonical remote base"
                )
            if last_step[0] == "integration":
                if existing != last_step[1]:
                    raise RecoveryError(
                        "candidate branch is not the latest integration source"
                    )
                run_command(
                    (
                        "git",
                        "update-ref",
                        f"refs/heads/{branch}",
                        last_step[2],
                        last_step[1],
                    ),
                    cwd=self.target,
                )
                existing = last_step[2]
            elif last is None:
                raise RecoveryError("candidate Task progress is unavailable")
        if existing != progress:
            assert last is not None
            _revision, task_index, task, gate, task_receipt = last
            prior = str(task_receipt["source_commit"])
            if existing != prior:
                raise RecoveryError(
                    "candidate branch head is not the latest canonical progress"
                )
            attempt_id = task_receipt.get("attempt_id")
            if not isinstance(attempt_id, str) or not attempt_id:
                raise RecoveryError("gated candidate lacks its Attempt binding")
            try:
                progress_observation = json.loads(
                    self.evidence_store.read_blob(
                        str(task_receipt["stdout_digest"])
                    )
                )
            except (OSError, ValueError) as exc:
                raise RecoveryError(
                    "gated candidate progress observation is unavailable"
                ) from exc
            if progress_observation.get("batch_id") is not None:
                if (
                    progress_observation.get("integrated_candidate_commit")
                    != progress
                    or self.git.resolve_commit(progress) != progress
                ):
                    raise RecoveryError(
                        "gated batch candidate progress binding is invalid"
                    )
                run_command(
                    (
                        "git",
                        "update-ref",
                        f"refs/heads/{branch}",
                        progress,
                        prior,
                    ),
                    cwd=self.target,
                )
                existing = progress
                payload = None
            else:
                payload = None
            attempt = self.store.get_entity_state("attempt", attempt_id)
            if not isinstance(attempt, Mapping):
                raise RecoveryError("gated candidate Attempt is unavailable")
            if existing != progress:
                payload = attempt.get("payload", {})
                if not isinstance(payload, Mapping):
                    raise RecoveryError("gated candidate Attempt payload is malformed")
                manager, workspace, root = self._task_workspace(
                    payload, task_index=task_index
                )
                try:
                    observed = run_command(
                        (
                            "git",
                            "rev-parse",
                            "--verify",
                            f"{progress}^{{commit}}",
                        ),
                        cwd=workspace.path,
                    ).stdout.strip()
                    if observed != progress:
                        raise RecoveryError(
                            "gated candidate is unavailable in its Attempt workspace"
                        )
                    self._update_candidate_from_workspace(
                        branch=branch,
                        before=prior,
                        workspace=workspace,
                        candidate=progress,
                    )
                except BaseException:
                    # This workspace remains part of an unfinished Task catch-up.
                    raise
                existing = progress
        if last is not None:
            _revision, _task_index, task, gate, task_receipt = last
            attempt_id = str(task_receipt["attempt_id"])
            try:
                progress_observation = json.loads(
                    self.evidence_store.read_blob(
                        str(task_receipt["stdout_digest"])
                    )
                )
            except (OSError, ValueError) as exc:
                raise RecoveryError(
                    "candidate progress observation is unavailable"
                ) from exc
            progress_record = {
                "branch": branch,
                "run_id": self.run_id,
                "task_id": task["id"],
                "attempt_id": attempt_id,
                "gate_id": gate["gate_id"],
                "source_commit": task_receipt["source_commit"],
                "candidate_commit": gate["candidate_commit"],
            }
            if progress_observation.get("batch_id") is not None:
                progress_record.update(
                    {
                        "batch_id": progress_observation["batch_id"],
                        "task_result_commit": progress_observation[
                            "task_result_commit"
                        ],
                        "integration_evidence_id": task_receipt["evidence_id"],
                    }
                )
            self._record_domain_once(
                "CANDIDATE_BRANCH_ADVANCED",
                progress_record,
                idempotency_key=(
                    f"configured-runtime:candidate-progress:{attempt_id}"
                ),
            )
        if existing != progress:
            raise RecoveryError(
                "candidate branch head lacks latest canonical gated progress"
            )
        return branch, existing

    def _update_candidate_from_workspace(
        self,
        *,
        branch: str,
        before: str,
        workspace: Workspace,
        candidate: str,
    ) -> str:
        imported_ref = f"refs/nm-v6/import/{self.identity}/{uuid.uuid4().hex}"
        run_command(
            (
                "git",
                "fetch",
                "--no-tags",
                str(workspace.path),
                f"{candidate}:{imported_ref}",
            ),
            cwd=self.target,
        )
        imported = self.git.resolve_commit(imported_ref)
        run_command(
            (
                "git",
                "update-ref",
                f"refs/heads/{branch}",
                imported,
                before,
            ),
            cwd=self.target,
        )
        return imported

    def _context_manifest(
        self,
        *,
        task: Mapping[str, Any],
        phase: Mapping[str, Any],
        attempt_id: str,
    ) -> dict[str, Any]:
        goals = self.traceability.get("goals", [])
        requirements = self.traceability.get("requirements", [])
        acceptances = self.traceability.get("acceptance", [])
        acceptance_ids = set(task.get("acceptance_ids", []))
        selected_acceptances = [
            item for item in acceptances if item.get("id") in acceptance_ids
        ]
        requirement_ids = {
            requirement_id
            for item in selected_acceptances
            for requirement_id in item.get("requirement_ids", [])
        }
        selected_requirements = [
            item for item in requirements if item.get("id") in requirement_ids
        ]
        goal_ids = {
            goal_id
            for item in selected_requirements
            for goal_id in item.get("goal_ids", [])
        }
        selected_goals = [item for item in goals if item.get("id") in goal_ids]
        action_map = self.traceability.get("acceptance_actions", {})
        items = (
            ContextItem(
                "invariant",
                "AGENTS.md#safety",
                "Workers may modify only the disposable candidate and never protected refs or runtime authority.",
            ),
            ContextItem("goal", "traceability.json#goals", json.dumps(selected_goals, sort_keys=True)),
            ContextItem("requirement", "traceability.json#requirements", json.dumps(selected_requirements, sort_keys=True)),
            ContextItem("acceptance", "traceability.json#acceptance", json.dumps(selected_acceptances, sort_keys=True)),
            ContextItem("phase", f"traceability.json#{phase['id']}", json.dumps(dict(phase), sort_keys=True)),
            ContextItem("task", f"traceability.json#{task['id']}", json.dumps(dict(task), sort_keys=True)),
            ContextItem(
                "acceptance_action",
                "traceability.json#acceptance_actions",
                json.dumps(
                    {
                        identifier: action_map[identifier]
                        for identifier in sorted(acceptance_ids)
                    },
                    sort_keys=True,
                ),
            ),
        )
        return build_context_manifest(
            attempt_id=attempt_id,
            items=items,
            allowed_paths=task.get("write_set", []),
            prohibited_paths=(".nm/runtime",),
            max_manifest_bytes=int(self.project["context"]["max_manifest_bytes"]),
            max_estimated_tokens=int(
                self.project["context"]["max_estimated_tokens"]
            ),
        )

    def _attempt_identifiers(self, task_index: int, ordinal: int) -> tuple[str, str]:
        if not 1 <= task_index <= 999 or not 0 <= ordinal <= 999:
            raise ContractError("configured Task attempt sequence overflow")
        stem = f"runtime-{self.identity}-t{task_index:03d}r"
        return (
            f"ATTEMPT-{stem}-{ordinal:03d}",
            f"OP-{stem}-{ordinal:03d}",
        )

    def _attempt_lease(
        self,
        *,
        task_id: str,
        attempt_id: str,
        owner: str,
    ) -> Lease | None:
        raw = self.store.get_lease(task_id)
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise ContractError("persisted Task lease is malformed")
        if (
            raw.get("run_id") != self.run_id
            or raw.get("resource_id") != task_id
            or raw.get("attempt_id") != attempt_id
            or raw.get("owner") != owner
        ):
            raise TransitionError("active Task lease belongs to another attempt")
        token = raw.get("fencing_token")
        expires_at = raw.get("expires_at")
        if isinstance(token, bool) or not isinstance(token, int):
            raise ContractError("persisted Task lease fencing token is malformed")
        if not isinstance(expires_at, str) or not expires_at:
            raise ContractError("persisted Task lease expiry is malformed")
        return Lease(
            task_id,
            owner,
            attempt_id,
            token,
            expires_at,
            self._revision(),
        )

    def _task_workspace(
        self,
        binding: Mapping[str, Any],
        *,
        task_index: int,
    ) -> tuple[WorkspaceManager, Workspace, Path]:
        fields = (
            "workspace_path",
            "workspace_root",
            "workspace_id",
            "base_commit",
            "candidate_branch",
        )
        if not all(isinstance(binding.get(field), str) and binding.get(field) for field in fields):
            raise RecoveryError("persisted adapter workspace binding is incomplete")
        raw_path = Path(str(binding["workspace_path"]))
        raw_root = Path(str(binding["workspace_root"]))
        if not raw_path.is_absolute() or not raw_root.is_absolute():
            raise RecoveryError("persisted adapter workspace must be absolute")
        try:
            path = raw_path.resolve(strict=True)
            root = raw_root.resolve(strict=True)
        except OSError as exc:
            raise RecoveryError("persisted adapter workspace is unavailable") from exc
        if (
            path != Path(os.path.abspath(raw_path))
            or root != Path(os.path.abspath(raw_root))
            or not path.is_dir()
            or not root.is_dir()
            or path.is_symlink()
            or root.is_symlink()
            or path.parent != root
            or path.name != binding["workspace_id"]
        ):
            raise RecoveryError("persisted adapter workspace path binding is invalid")
        try:
            root.relative_to(Path(tempfile.gettempdir()).resolve())
        except ValueError as exc:
            raise RecoveryError("persisted adapter workspace root is not temporary") from exc
        label = f"task-{task_index:03d}"
        expected_id = re.compile(
            rf"runtime-{re.escape(self.identity)}-{re.escape(label)}-[0-9a-f]{{8}}"
        )
        if (
            expected_id.fullmatch(str(binding["workspace_id"])) is None
            or not root.name.startswith(f"nm-v6-runtime-{label}-")
            or binding["candidate_branch"] != self._candidate_branch()
        ):
            raise RecoveryError("persisted adapter workspace identity is invalid")
        git_dir = Path(
            run_command(
                ("git", "rev-parse", "--absolute-git-dir"), cwd=path
            ).stdout.strip()
        ).resolve()
        remotes = run_command(("git", "remote"), cwd=path).stdout.splitlines()
        base_commit = str(binding["base_commit"])
        resolved_base = run_command(
            ("git", "rev-parse", "--verify", f"{base_commit}^{{commit}}"),
            cwd=path,
        ).stdout.strip()
        if git_dir != path / ".git" or remotes or resolved_base != base_commit:
            raise RecoveryError("persisted adapter workspace Git binding is invalid")
        manager = WorkspaceManager(self.target, root)
        return (
            manager,
            Workspace(str(binding["workspace_id"]), path, base_commit, None),
            root,
        )

    def _adapter_for_attempt(
        self,
        provider: str,
        manager: WorkspaceManager,
    ) -> Any:
        return create_adapter(
            provider,
            isolation_backend=manager.isolation_backend,
            state_root=self.target / ".nm/runtime/v6/adapter-sessions",
        )

    def _attempt_binding(
        self,
        attempt: Mapping[str, Any],
        *,
        task_id: str,
        phase_id: str,
        provider: str,
        attempt_id: str,
        operation_id: str,
        owner: str,
        fencing_token: int,
        base_commit: str,
        candidate_branch: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = attempt.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ContractError("persisted adapter Attempt payload is malformed")
        expected = {
            "task_id": task_id,
            "phase_id": phase_id,
            "provider": provider,
            "attempt_id": attempt_id,
            "operation_id": operation_id,
            "lease_owner": owner,
            "fencing_token": fencing_token,
            "base_commit": base_commit,
            "candidate_branch": candidate_branch,
        }
        if any(payload.get(field) != value for field, value in expected.items()):
            raise ContractError("persisted adapter Attempt binding drifted")
        request = validate_adapter_request(payload.get("request"))
        request_digest = sha256_bytes(canonical_json(request))
        if (
            payload.get("request_digest") != request_digest
            or request.get("run_id") != self.run_id
            or request.get("attempt_id") != attempt_id
            or request.get("operation_id") != operation_id
            or request.get("fencing_token") != fencing_token
            or request.get("workspace") != payload.get("workspace_path")
        ):
            raise ContractError("persisted adapter request binding drifted")
        return dict(payload), request

    def _adapter_request_record(
        self,
        binding: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "task_id": binding["task_id"],
            "phase_id": binding["phase_id"],
            "provider": binding["provider"],
            "attempt_id": binding["attempt_id"],
            "operation_id": binding["operation_id"],
            "request_digest": binding["request_digest"],
            "request": dict(request),
            "workspace_path": binding["workspace_path"],
            "workspace_root": binding["workspace_root"],
            "workspace_id": binding["workspace_id"],
            "base_commit": binding["base_commit"],
            "candidate_branch": binding["candidate_branch"],
            "lease_owner": binding["lease_owner"],
            "fencing_token": binding["fencing_token"],
        }

    def _incomplete_task_batch(self, scope_id: str) -> dict[str, Any] | None:
        planned: list[dict[str, Any]] = []
        closed: set[str] = set()
        for event in self.store.list_events(run_id=self.run_id):
            event_type = event.get("event_type")
            record = event.get("payload", {}).get("record")
            if not isinstance(record, Mapping):
                continue
            if event_type == "TASK_BATCH_PLANNED" and record.get("scope_id") == scope_id:
                planned.append(dict(record))
            elif event_type in {"TASK_BATCH_COMPLETED", "TASK_BATCH_BLOCKED"}:
                batch_id = record.get("batch_id")
                if isinstance(batch_id, str):
                    closed.add(batch_id)
        active = [record for record in planned if record.get("batch_id") not in closed]
        if len(active) > 1:
            raise RecoveryError("multiple incomplete Task batches share one scope")
        return active[0] if active else None

    def _task_batch_plan(
        self,
        *,
        scope_id: str,
        branch: str,
        base_commit: str,
        definitions: Sequence[TaskDefinition],
    ) -> dict[str, Any]:
        existing = self._incomplete_task_batch(scope_id)
        if existing is not None:
            expected = [definition.task_id for definition in definitions]
            if (
                existing.get("candidate_branch") != branch
                or existing.get("base_commit") != base_commit
                or existing.get("ordered_task_ids") != expected
            ):
                raise RecoveryError("incomplete Task batch binding drifted")
            return existing
        count = sum(
            1
            for event in self.store.list_events(run_id=self.run_id)
            if event.get("event_type") == "TASK_BATCH_PLANNED"
        )
        batch_id = f"BATCH-runtime-{self.identity}-{count + 1:03d}"
        record = {
            "schema_version": "nm-v6/task-batch-v1",
            "batch_id": batch_id,
            "batch_scope": f"batch-{count + 1:03d}",
            "scope_id": scope_id,
            "run_kind": self._current().get("run_kind"),
            "candidate_branch": branch,
            "base_commit": base_commit,
            "base_tree": self.git.tree_of(base_commit),
            "ordered_task_ids": [definition.task_id for definition in definitions],
            "declared_write_sets": {
                definition.task_id: list(definition.write_set)
                for definition in definitions
            },
            "max_workers": int(self.project["scheduler"]["max_workers"]),
            "commit_timestamp": utc_now(),
        }
        return self._record_domain_once(
            "TASK_BATCH_PLANNED",
            record,
            idempotency_key=f"configured-runtime:task-batch:{batch_id}",
        )

    def _prepare_batch_attempt(
        self,
        *,
        batch: Mapping[str, Any],
        scheduler: Scheduler,
        definition: TaskDefinition,
        task: Mapping[str, Any],
        phase: Mapping[str, Any],
        task_index: int,
        branch: str,
        provider: str,
    ) -> _BatchAttemptContext | None:
        task_id = definition.task_id
        task_entity_id = self._entity_id(task_id)
        task_entity = self._ensure_entity(
            "task",
            task_entity_id,
            initial_state="PLANNED",
            payload={
                "traceability_id": task_id,
                "phase_id": phase["id"],
                "write_set": list(definition.write_set),
            },
        )
        if task_entity["state"] == "PLANNED":
            self._entity_transition("task", task_entity_id, "MAKE_READY")
            task_entity = self.store.get_entity_state("task", task_entity_id)
            assert isinstance(task_entity, Mapping)
        state = str(task_entity["state"])
        task_payload = task_entity.get("payload", {})
        if not isinstance(task_payload, Mapping):
            raise ContractError("configured Task payload is malformed")
        owner = f"configured-runtime-{self.identity}"
        base_commit = str(batch["base_commit"])
        if state in {"CANDIDATE", "VERIFYING", "VERIFIED"}:
            attempt_id = str(task_payload.get("active_attempt_id", ""))
            operation_id = str(task_payload.get("active_operation_id", ""))
            attempt = self.store.get_entity_state("attempt", attempt_id)
            if not isinstance(attempt, Mapping):
                raise RecoveryError("advanced batch Task lacks its Attempt")
            token = int(attempt.get("payload", {}).get("fencing_token", -1))
            binding, request = self._attempt_binding(
                attempt,
                task_id=task_id,
                phase_id=str(phase["id"]),
                provider=provider,
                attempt_id=attempt_id,
                operation_id=operation_id,
                owner=owner,
                fencing_token=token,
                base_commit=base_commit,
                candidate_branch=branch,
            )
            if binding.get("batch_id") != batch["batch_id"]:
                raise ContractError("advanced Attempt batch binding drifted")
            manager, workspace, root = self._task_workspace(
                binding, task_index=task_index
            )
            return _BatchAttemptContext(
                definition,
                task,
                phase,
                task_index,
                task_entity_id,
                attempt_id,
                operation_id,
                self._attempt_lease(
                    task_id=task_id, attempt_id=attempt_id, owner=owner
                ),
                binding,
                request,
                manager,
                workspace,
                root,
            )
        if state == "INTEGRATED":
            return None
        if state not in {"READY", "LEASED", "RUNNING"}:
            raise RecoveryError(
                f"Task batch cannot prepare {task_id} from state {state}"
            )
        if state == "READY":
            ordinal_raw = task_payload.get("attempt_ordinal", -1)
            if isinstance(ordinal_raw, bool) or not isinstance(ordinal_raw, int):
                raise ContractError("Task attempt ordinal is malformed")
            ordinal = ordinal_raw + 1
            attempt_id, operation_id = self._attempt_identifiers(task_index, ordinal)
            lease = scheduler.acquire(
                task_id,
                owner=owner,
                attempt_id=attempt_id,
                expected_revision=self._revision(),
            )
            self._entity_transition(
                "task",
                task_entity_id,
                "ACQUIRE_LEASE",
                payload={
                    "lease_resource_id": task_id,
                    "lease_owner": owner,
                    "state_patch": {
                        "active_attempt_id": attempt_id,
                        "active_operation_id": operation_id,
                        "attempt_ordinal": ordinal,
                        "attempt_base_commit": base_commit,
                        "candidate_branch": branch,
                        "batch_id": batch["batch_id"],
                    },
                },
                fencing_token=lease.fencing_token,
            )
            state = "LEASED"
        else:
            attempt_id = str(task_payload.get("active_attempt_id", ""))
            operation_id = str(task_payload.get("active_operation_id", ""))
            if (
                not attempt_id
                or not operation_id
                or task_payload.get("attempt_base_commit") != base_commit
                or task_payload.get("candidate_branch") != branch
                or task_payload.get("batch_id") != batch["batch_id"]
            ):
                raise ContractError("active batch Task binding is incomplete")
            lease = self._attempt_lease(
                task_id=task_id,
                attempt_id=attempt_id,
                owner=owner,
            )
            if lease is None:
                raise RecoveryError("active batch Task lease disappeared")
            if lease.expired():
                attempt = self.store.get_entity_state("attempt", attempt_id)
                if not isinstance(attempt, Mapping):
                    self._entity_transition(
                        "task",
                        task_entity_id,
                        "LEASE_LOST",
                        payload={
                            "lease_fenced": True,
                            "external_operations_reconciled": True,
                            "state_patch": {"active_attempt_id": None},
                        },
                    )
                    return self._prepare_batch_attempt(
                        batch=batch,
                        scheduler=scheduler,
                        definition=definition,
                        task=task,
                        phase=phase,
                        task_index=task_index,
                        branch=branch,
                        provider=provider,
                    )
                binding, _request = self._attempt_binding(
                    attempt,
                    task_id=task_id,
                    phase_id=str(phase["id"]),
                    provider=provider,
                    attempt_id=attempt_id,
                    operation_id=operation_id,
                    owner=owner,
                    fencing_token=lease.fencing_token,
                    base_commit=base_commit,
                    candidate_branch=branch,
                )
                manager, workspace, root = self._task_workspace(
                    binding, task_index=task_index
                )
                result_record = self._domain_record(
                    "ADAPTER_RESULT_RECORDED",
                    idempotency_key=(
                        f"configured-runtime:adapter-result:{attempt_id}"
                    ),
                )
                session_record = self._domain_record(
                    "ADAPTER_SESSION_RECORDED",
                    idempotency_key=(
                        f"configured-runtime:adapter-session:{attempt_id}"
                    ),
                )
                session_observation: Mapping[str, Any] | None = None
                reconciled = result_record is not None
                if not reconciled and session_record is not None:
                    adapter = self._adapter_for_attempt(provider, manager)
                    session_observation = adapter.cancel(
                        str(session_record["session_id"])
                    )
                    reconciled = session_observation.get("status") in {
                        "cancelled",
                        "finished",
                    }
                if not reconciled:
                    self._record_domain_once(
                        "ADAPTER_ATTEMPT_STALE",
                        {
                            "attempt_id": attempt_id,
                            "task_id": task_id,
                            "fencing_token": lease.fencing_token,
                            "classification": "unknown",
                            "session_observation": (
                                dict(session_observation)
                                if isinstance(session_observation, Mapping)
                                else None
                            ),
                        },
                        idempotency_key=(
                            f"configured-runtime:adapter-stale:{attempt_id}"
                        ),
                    )
                    raise RecoveryError(
                        "expired batch Attempt external outcome remains unknown"
                    )
                if attempt["state"] in {"DISPATCHED", "RUNNING", "COLLECTING"}:
                    self._entity_transition(
                        "attempt",
                        attempt_id,
                        "LOSE",
                        payload={"lease_fenced": True},
                    )
                self._entity_transition(
                    "task",
                    task_entity_id,
                    "LEASE_LOST",
                    payload={
                        "lease_fenced": True,
                        "external_operations_reconciled": True,
                        "state_patch": {"active_attempt_id": None},
                    },
                )
                self._record_domain_once(
                    "ADAPTER_ATTEMPT_STALE",
                    {
                        "attempt_id": attempt_id,
                        "task_id": task_id,
                        "fencing_token": lease.fencing_token,
                        "classification": "expired",
                        "session_observation": (
                            dict(session_observation)
                            if isinstance(session_observation, Mapping)
                            else None
                        ),
                    },
                    idempotency_key=(
                        f"configured-runtime:adapter-stale:{attempt_id}"
                    ),
                )
                self._dispose_workspace(manager, workspace, root)
                return self._prepare_batch_attempt(
                    batch=batch,
                    scheduler=scheduler,
                    definition=definition,
                    task=task,
                    phase=phase,
                    task_index=task_index,
                    branch=branch,
                    provider=provider,
                )
        if state == "LEASED":
            self._entity_transition(
                "task",
                task_entity_id,
                "START",
                payload={"lease_resource_id": task_id, "lease_owner": owner},
                fencing_token=lease.fencing_token,
            )

        attempt = self.store.get_entity_state("attempt", attempt_id)
        if not isinstance(attempt, Mapping):
            manager, workspace, root = self._workspace(
                base_commit, f"task-{task_index:03d}"
            )
            request = validate_adapter_request(
                {
                    "protocol_version": "nm-v6/adapter-request-v1",
                    "operation_id": operation_id,
                    "run_id": self.run_id,
                    "attempt_id": attempt_id,
                    "role": "worker",
                    "workspace": str(workspace.path),
                    "context_manifest": self._context_manifest(
                        task=task, phase=phase, attempt_id=attempt_id
                    ),
                    "expected_output_schema": "nm-v6/adapter-result-v1",
                    "deadline": (
                        datetime.now(UTC) + timedelta(hours=1)
                    ).isoformat(),
                    "fencing_token": lease.fencing_token,
                    "allowed_capabilities": ["workspace_write"],
                }
            )
            binding = {
                "task_id": task_id,
                "phase_id": str(phase["id"]),
                "provider": provider,
                "attempt_id": attempt_id,
                "operation_id": operation_id,
                "lease_owner": owner,
                "fencing_token": lease.fencing_token,
                "base_commit": base_commit,
                "candidate_branch": branch,
                "batch_id": batch["batch_id"],
                "workspace_path": str(workspace.path),
                "workspace_root": str(root),
                "workspace_id": workspace.workspace_id,
                "request_digest": sha256_bytes(canonical_json(request)),
                "request": request,
            }
            attempt = self._ensure_entity(
                "attempt", attempt_id, initial_state="CREATED", payload=binding
            )
        else:
            binding, request = self._attempt_binding(
                attempt,
                task_id=task_id,
                phase_id=str(phase["id"]),
                provider=provider,
                attempt_id=attempt_id,
                operation_id=operation_id,
                owner=owner,
                fencing_token=lease.fencing_token,
                base_commit=base_commit,
                candidate_branch=branch,
            )
            if binding.get("batch_id") != batch["batch_id"]:
                raise ContractError("persisted Attempt batch binding drifted")
            manager, workspace, root = self._task_workspace(
                binding, task_index=task_index
            )
        if attempt["state"] == "CREATED":
            self._entity_transition("attempt", attempt_id, "DISPATCH")
        self._record_domain_once(
            "ADAPTER_REQUESTED",
            self._adapter_request_record(binding, request),
            idempotency_key=f"configured-runtime:adapter-request:{attempt_id}",
        )
        return _BatchAttemptContext(
            definition,
            task,
            phase,
            task_index,
            task_entity_id,
            attempt_id,
            operation_id,
            lease,
            binding,
            request,
            manager,
            workspace,
            root,
        )

    @staticmethod
    def _poll_collect_adapter(
        adapter: Any, session_id: str, deadline_text: str
    ) -> dict[str, Any]:
        deadline = datetime.fromisoformat(deadline_text.replace("Z", "+00:00"))
        while True:
            observation = adapter.poll(session_id)
            if observation["status"] != "running":
                break
            if datetime.now(UTC) >= deadline:
                adapter.cancel(session_id)
                break
            time.sleep(0.05)
        return adapter.collect_dict(session_id)

    def _start_collect_task_batch(
        self,
        *,
        scheduler: Scheduler,
        contexts: Sequence[_BatchAttemptContext],
        provider: str,
    ) -> None:
        pending_start: dict[str, Future[dict[str, Any]]] = {}
        workers = max(1, min(len(contexts), int(self.project["scheduler"]["max_workers"])))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for context in contexts:
                result_record = self._domain_record(
                    "ADAPTER_RESULT_RECORDED",
                    idempotency_key=(
                        f"configured-runtime:adapter-result:{context.attempt_id}"
                    ),
                )
                if result_record is not None:
                    continue
                context.adapter = self._adapter_for_attempt(provider, context.manager)
                session_record = self._domain_record(
                    "ADAPTER_SESSION_RECORDED",
                    idempotency_key=(
                        f"configured-runtime:adapter-session:{context.attempt_id}"
                    ),
                )
                if session_record is None:
                    pending_start[context.attempt_id] = executor.submit(
                        context.adapter.start, context.request
                    )
                else:
                    context.session_id = str(session_record["session_id"])

            for context in sorted(contexts, key=lambda item: item.definition.task_id):
                future = pending_start.get(context.attempt_id)
                if future is not None:
                    session = future.result()
                    context.session_id = str(session["session_id"])
                    checkpoint("runtime.after_adapter_session_start")
                if context.session_id is None:
                    continue
                expected_session_record = {
                    "task_id": context.definition.task_id,
                    "provider": provider,
                    "attempt_id": context.attempt_id,
                    "operation_id": context.operation_id,
                    "request_digest": context.binding["request_digest"],
                    "session_id": context.session_id,
                    "lease_owner": context.lease.owner,
                    "fencing_token": context.lease.fencing_token,
                }
                self._record_domain_once(
                    "ADAPTER_SESSION_RECORDED",
                    expected_session_record,
                    idempotency_key=(
                        f"configured-runtime:adapter-session:{context.attempt_id}"
                    ),
                )
                attempt = self.store.get_entity_state("attempt", context.attempt_id)
                assert isinstance(attempt, Mapping)
                if attempt["state"] == "DISPATCHED":
                    self._entity_transition(
                        "attempt",
                        context.attempt_id,
                        "START",
                        payload={
                            "lease_resource_id": context.definition.task_id,
                            "lease_owner": context.lease.owner,
                            "state_patch": {
                                "session_id": context.session_id,
                                "request_digest": context.binding["request_digest"],
                            },
                        },
                        fencing_token=context.lease.fencing_token,
                    )

            pending_collect: dict[str, Future[dict[str, Any]]] = {}
            by_attempt = {context.attempt_id: context for context in contexts}
            for context in contexts:
                if self._domain_record(
                    "ADAPTER_RESULT_RECORDED",
                    idempotency_key=(
                        f"configured-runtime:adapter-result:{context.attempt_id}"
                    ),
                ) is not None:
                    continue
                if context.adapter is None or context.session_id is None:
                    raise RecoveryError("batch adapter session is unavailable")
                pending_collect[context.attempt_id] = executor.submit(
                    self._poll_collect_adapter,
                    context.adapter,
                    context.session_id,
                    str(context.request["deadline"]),
                )

            pending = set(pending_collect.values())
            heartbeat_seconds = int(
                self.project["scheduler"].get("heartbeat_seconds", 30)
            )
            while pending:
                done, pending = wait(
                    pending, timeout=max(0.1, heartbeat_seconds / 2)
                )
                if not done:
                    for context in contexts:
                        if context.attempt_id not in pending_collect:
                            continue
                        context.lease = scheduler.heartbeat(
                            context.lease, expected_revision=self._revision()
                        )

            for attempt_id in sorted(pending_collect, key=lambda value: by_attempt[value].definition.task_id):
                context = by_attempt[attempt_id]
                scheduler.validate_result(
                    task_id=context.definition.task_id,
                    owner=context.lease.owner,
                    fencing_token=context.lease.fencing_token,
                    lease=context.lease,
                )
                result = pending_collect[attempt_id].result()
                session_record = self._domain_record(
                    "ADAPTER_SESSION_RECORDED",
                    idempotency_key=(
                        f"configured-runtime:adapter-session:{context.attempt_id}"
                    ),
                )
                if session_record is None:
                    raise RecoveryError("batch result lacks its session record")
                self._record_domain_once(
                    "ADAPTER_RESULT_RECORDED",
                    {**session_record, "result": result},
                    idempotency_key=(
                        f"configured-runtime:adapter-result:{context.attempt_id}"
                    ),
                )
                checkpoint("runtime.after_adapter_result_record")

    def _task_batch_candidate_facts(
        self,
        *,
        batch: Mapping[str, Any],
        contexts: Sequence[_BatchAttemptContext],
        scheduler: Scheduler,
        accepted_paths: Mapping[str, Sequence[str]],
    ) -> dict[str, dict[str, Any]]:
        facts: dict[str, dict[str, Any]] = {}
        base_commit = str(batch["base_commit"])
        batch_ids = set(map(str, batch["ordered_task_ids"]))
        prior_paths = {
            task_id: paths
            for task_id, paths in accepted_paths.items()
            if task_id not in batch_ids
        }
        for context in sorted(contexts, key=lambda item: item.definition.task_id):
            result_record = self._domain_record(
                "ADAPTER_RESULT_RECORDED",
                idempotency_key=(
                    f"configured-runtime:adapter-result:{context.attempt_id}"
                ),
            )
            if result_record is None:
                raise RecoveryError("Task batch lacks a collected adapter result")
            result = adapter_result_to_dict(
                validate_adapter_result(
                    result_record.get("result"), request=context.request
                )
            )
            if result["status"] != "succeeded":
                raise RecoveryError(
                    f"Task batch member failed: {context.definition.task_id}"
                )
            value = result.get("candidate_commit")
            candidate_commit = (
                base_commit
                if value is None
                else run_command(
                    (
                        "git",
                        "rev-parse",
                        "--verify",
                        f"{value}^{{commit}}",
                    ),
                    cwd=context.workspace.path,
                ).stdout.strip()
            )
            ancestry = run_command(
                ("git", "merge-base", "--is-ancestor", base_commit, candidate_commit),
                cwd=context.workspace.path,
                check=False,
            )
            if ancestry.returncode != 0:
                raise RecoveryError("Task candidate is not based on the batch base")
            actual_paths = tuple(
                sorted(
                    path
                    for path in run_command(
                        (
                            "git",
                            "diff",
                            "--name-only",
                            "-z",
                            base_commit,
                            candidate_commit,
                            "--",
                        ),
                        cwd=context.workspace.path,
                    ).stdout.split("\0")
                    if path
                )
            )
            if tuple(sorted(result["changed_paths"])) != actual_paths:
                raise ContractError(
                    "adapter changed_paths differs from the batch-base Git diff"
                )
            facts[context.definition.task_id] = {
                "task_id": context.definition.task_id,
                "task_index": context.task_index,
                "attempt_id": context.attempt_id,
                "operation_id": context.operation_id,
                "base_commit": base_commit,
                "candidate_commit": candidate_commit,
                "candidate_tree": run_command(
                    ("git", "rev-parse", f"{candidate_commit}^{{tree}}"),
                    cwd=context.workspace.path,
                ).stdout.strip(),
                "actual_paths": list(actual_paths),
                "result": result,
            }
        ordered = list(map(str, batch["ordered_task_ids"]))
        conflicts: dict[str, list[str]] = {}
        for position, left_id in enumerate(ordered):
            for right_id in ordered[position + 1 :]:
                overlap = actual_paths_overlap(
                    facts[left_id]["actual_paths"], facts[right_id]["actual_paths"]
                )
                if overlap:
                    conflicts[f"{left_id}:{right_id}"] = list(overlap)
        if conflicts:
            candidate_unchanged = (
                self.git.resolve_commit(
                    f"refs/heads/{batch['candidate_branch']}"
                )
                == base_commit
            )
            evidence_id = self._evidence(
                190,
                "task-batch-overlap",
                {
                    "batch_id": batch["batch_id"],
                    "base_commit": base_commit,
                    "task_results": {
                        task_id: {
                            "candidate_commit": fact["candidate_commit"],
                            "actual_paths": list(fact["actual_paths"]),
                        }
                        for task_id, fact in facts.items()
                    },
                    "conflicts": conflicts,
                },
                assertions={
                    "all_adapter_results_reconciled": True,
                    "actual_paths_disjoint": False,
                    "candidate_ref_unchanged": candidate_unchanged,
                },
                source_commit=base_commit,
                candidate_commit=base_commit,
                subject_ids=(
                    f"batch:{batch['batch_id']}",
                    *map(str, batch["ordered_task_ids"]),
                ),
                scope=str(batch["batch_scope"]),
            )
            for context in contexts:
                attempt = self.store.get_entity_state("attempt", context.attempt_id)
                if isinstance(attempt, Mapping) and attempt["state"] == "RUNNING":
                    self._entity_transition(
                        "attempt",
                        context.attempt_id,
                        "COLLECT",
                        payload={
                            "lease_resource_id": context.definition.task_id,
                            "lease_owner": context.lease.owner,
                        },
                        fencing_token=context.lease.fencing_token,
                    )
                    attempt = self.store.get_entity_state(
                        "attempt", context.attempt_id
                    )
                if isinstance(attempt, Mapping) and attempt["state"] == "COLLECTING":
                    self._entity_transition(
                        "attempt",
                        context.attempt_id,
                        "SUCCEED",
                        payload={
                            "structured_result_valid": True,
                            "lease_resource_id": context.definition.task_id,
                            "lease_owner": context.lease.owner,
                            "state_patch": {
                                "candidate_commit": facts[
                                    context.definition.task_id
                                ]["candidate_commit"],
                                "changed_paths": list(
                                    facts[context.definition.task_id]["actual_paths"]
                                ),
                            },
                        },
                        fencing_token=context.lease.fencing_token,
                    )
                task_entity = self.store.get_entity_state(
                    "task", context.task_entity_id
                )
                if isinstance(task_entity, Mapping) and task_entity["state"] == "RUNNING":
                    self._entity_transition(
                        "task",
                        context.task_entity_id,
                        "BLOCK",
                        payload={
                            "lease_resource_id": context.definition.task_id,
                            "lease_owner": context.lease.owner,
                            "state_patch": {
                                "batch_block_evidence_id": evidence_id,
                                "batch_block_reason": "actual_write_overlap",
                            },
                        },
                        fencing_token=context.lease.fencing_token,
                    )
                scheduler.release(
                    context.lease, expected_revision=self._revision()
                )
            self._record_domain_once(
                "TASK_BATCH_BLOCKED",
                {
                    "schema_version": "nm-v6/task-batch-blocked-v1",
                    "batch_id": batch["batch_id"],
                    "base_commit": base_commit,
                    "reason": "actual_write_overlap",
                    "conflicts": conflicts,
                    "evidence_id": evidence_id,
                    "candidate_ref_unchanged": candidate_unchanged,
                },
                idempotency_key=(
                    f"configured-runtime:task-batch-blocked:{batch['batch_id']}"
                ),
            )
            for context in contexts:
                self._dispose_workspace(
                    context.manager, context.workspace, context.root
                )
            self._transition(
                self._current(),
                "REQUIRE_ATTENTION",
                payload={
                    "actors_fenced": True,
                    "external_operations_reconciled": True,
                    "reason": "actual Task write overlap",
                    "required_decision": "replan_conflicting_task_write_sets",
                    "evidence_ids": [evidence_id],
                    "conflicts": conflicts,
                },
                state_patch={
                    "runtime_attention": {
                        "reason": "actual Task write overlap",
                        "required_decision": "replan_conflicting_task_write_sets",
                        "evidence_ids": [evidence_id],
                        "conflicts": conflicts,
                    }
                },
            )
            raise _TaskBatchAttention(
                "actual Task write overlap detected before candidate integration: "
                + ", ".join(sorted(conflicts))
            )
        for context in contexts:
            scheduler.assert_actual_diff_isolated(
                context.definition.task_id,
                facts[context.definition.task_id]["actual_paths"],
                prior_paths,
            )
        return facts

    def _batch_commit_tree(
        self,
        *,
        tree: str,
        parent: str,
        task_result: str,
        batch: Mapping[str, Any],
        task_id: str,
    ) -> str:
        timestamp = str(batch["commit_timestamp"])
        environment = {
            **os.environ,
            "GIT_AUTHOR_NAME": "NM V6 Controller",
            "GIT_AUTHOR_EMAIL": "nm-v6@invalid.local",
            "GIT_COMMITTER_NAME": "NM V6 Controller",
            "GIT_COMMITTER_EMAIL": "nm-v6@invalid.local",
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
        }
        commit = run_command(
            (
                "git",
                "commit-tree",
                tree,
                "-p",
                parent,
                "-p",
                task_result,
                "-m",
                f"nm-v6: integrate {task_id} from {batch['batch_id']}",
            ),
            cwd=self.target,
            env=environment,
        ).stdout.strip()
        return self.git.resolve_commit(commit)

    def _task_batch_merge_plan(
        self,
        *,
        batch: Mapping[str, Any],
        contexts: Sequence[_BatchAttemptContext],
        facts: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        by_task = {context.definition.task_id: context for context in contexts}
        current = str(batch["base_commit"])
        steps: list[dict[str, Any]] = []
        for task_id in map(str, batch["ordered_task_ids"]):
            context = by_task[task_id]
            fact = facts[task_id]
            result_commit = str(fact["candidate_commit"])
            import_ref = (
                f"refs/nm-v6/import/{self.identity}/"
                f"{batch['batch_scope']}/t{context.task_index:03d}"
            )
            imported = self.git.try_resolve_commit(import_ref)
            if imported is None:
                run_command(
                    (
                        "git",
                        "fetch",
                        "--no-tags",
                        str(context.workspace.path),
                        f"{result_commit}:{import_ref}",
                    ),
                    cwd=self.target,
                )
                imported = self.git.resolve_commit(import_ref)
            if imported != result_commit:
                raise RecoveryError("Task result import ref drifted")
            self._record_domain_once(
                "TASK_RESULT_IMPORTED",
                {
                    "schema_version": "nm-v6/task-result-import-v1",
                    "batch_id": batch["batch_id"],
                    "task_id": task_id,
                    "attempt_id": fact["attempt_id"],
                    "base_commit": batch["base_commit"],
                    "result_commit": result_commit,
                    "result_tree": fact["candidate_tree"],
                    "actual_paths": list(fact["actual_paths"]),
                    "import_ref": import_ref,
                },
                idempotency_key=(
                    f"configured-runtime:task-result-import:"
                    f"{batch['batch_id']}:{task_id}"
                ),
            )
            merge_bases = tuple(
                value
                for value in run_command(
                    ("git", "merge-base", "--all", current, imported),
                    cwd=self.target,
                ).stdout.splitlines()
                if value
            )
            if merge_bases != (str(batch["base_commit"]),):
                raise RecoveryError("Task result has an unexpected batch merge base")
            if fact["actual_paths"]:
                result_tree = self.git.simulate_result_tree(
                    source_commit=imported,
                    target_commit=current,
                    strategy="merge_commit",
                )
                integrated_paths = tuple(
                    sorted(
                        path
                        for path in run_command(
                            (
                                "git",
                                "diff",
                                "--name-only",
                                "-z",
                                current,
                                result_tree,
                                "--",
                            ),
                            cwd=self.target,
                        ).stdout.split("\0")
                        if path
                    )
                )
                if integrated_paths != tuple(fact["actual_paths"]):
                    raise RecoveryError(
                        "batch merge tree does not apply the exact Task path set"
                    )
                for path in integrated_paths:
                    source_entry = run_command(
                        ("git", "ls-tree", str(fact["candidate_tree"]), "--", path),
                        cwd=self.target,
                    ).stdout
                    merged_entry = run_command(
                        ("git", "ls-tree", result_tree, "--", path),
                        cwd=self.target,
                    ).stdout
                    if source_entry != merged_entry:
                        raise RecoveryError(
                            "batch merge tree substituted Task path content"
                        )
                integrated_commit = self._batch_commit_tree(
                    tree=result_tree,
                    parent=current,
                    task_result=imported,
                    batch=batch,
                    task_id=task_id,
                )
            else:
                result_tree = self.git.tree_of(current)
                integrated_commit = current
            step = {
                "task_id": task_id,
                "task_index": fact["task_index"],
                "attempt_id": fact["attempt_id"],
                "batch_base_commit": batch["base_commit"],
                "task_result_commit": result_commit,
                "task_result_tree": fact["candidate_tree"],
                "actual_paths": list(fact["actual_paths"]),
                "previous_candidate_commit": current,
                "integrated_candidate_commit": integrated_commit,
                "integrated_candidate_tree": result_tree,
                "import_ref": import_ref,
            }
            steps.append(step)
            current = integrated_commit
        record = {
            "schema_version": "nm-v6/task-batch-merge-plan-v1",
            "batch_id": batch["batch_id"],
            "base_commit": batch["base_commit"],
            "candidate_branch": batch["candidate_branch"],
            "ordered_task_ids": list(batch["ordered_task_ids"]),
            "actual_paths_disjoint": True,
            "steps": steps,
            "steps_digest": sha256_bytes(canonical_json(steps)),
            "final_candidate_commit": current,
            "final_candidate_tree": self.git.tree_of(current),
        }
        return self._record_domain_once(
            "TASK_BATCH_MERGE_PLANNED",
            record,
            idempotency_key=(
                f"configured-runtime:task-batch-merge:{batch['batch_id']}"
            ),
        )

    def _drive_task_batch(
        self,
        *,
        scope_id: str,
        scheduler: Scheduler,
        graph: TaskGraph,
        tasks: Mapping[str, Mapping[str, Any]],
        phases: Mapping[str, Mapping[str, Any]],
        global_index: Mapping[str, int],
        completed_tasks: set[str],
        accepted_paths: Mapping[str, Sequence[str]],
        branch: str,
        candidate: str,
        provider: str,
    ) -> tuple[
        str,
        dict[str, tuple[str, ...]],
        dict[str, str],
        dict[str, str],
    ] | None:
        incomplete = self._incomplete_task_batch(scope_id)
        if incomplete is None:
            selected = scheduler.select(
                completed=completed_tasks,
                active={},
            )
            if not selected:
                return None
            batch = self._task_batch_plan(
                scope_id=scope_id,
                branch=branch,
                base_commit=candidate,
                definitions=selected,
            )
        else:
            batch = incomplete
            selected = tuple(
                graph.tasks[str(task_id)]
                for task_id in batch["ordered_task_ids"]
            )
            if batch.get("candidate_branch") != branch:
                raise RecoveryError("incomplete Task batch branch drifted")

        contexts: list[_BatchAttemptContext] = []
        for definition in selected:
            task = tasks[definition.task_id]
            phase = phases[str(task["phase_id"])]
            context = self._prepare_batch_attempt(
                batch=batch,
                scheduler=scheduler,
                definition=definition,
                task=task,
                phase=phase,
                task_index=int(global_index[definition.task_id]),
                branch=branch,
                provider=provider,
            )
            if context is not None:
                contexts.append(context)
        if contexts:
            self._start_collect_task_batch(
                scheduler=scheduler,
                contexts=contexts,
                provider=provider,
            )

        merge_record = self._domain_record(
            "TASK_BATCH_MERGE_PLANNED",
            idempotency_key=(
                f"configured-runtime:task-batch-merge:{batch['batch_id']}"
            ),
        )
        if merge_record is None:
            if len(contexts) != len(selected):
                raise RecoveryError(
                    "Task batch cannot rebuild its merge plan from disposed results"
                )
            facts = self._task_batch_candidate_facts(
                batch=batch,
                contexts=contexts,
                scheduler=scheduler,
                accepted_paths=accepted_paths,
            )
            merge_record = self._task_batch_merge_plan(
                batch=batch,
                contexts=contexts,
                facts=facts,
            )
        steps = {
            str(step["task_id"]): step for step in merge_record["steps"]
        }
        context_by_task = {
            context.definition.task_id: context for context in contexts
        }
        batch_paths: dict[str, tuple[str, ...]] = {}
        evidence: dict[str, str] = {}
        gates: dict[str, str] = {}
        branch_head = self.git.resolve_commit(f"refs/heads/{branch}")
        progress = str(batch["base_commit"])
        prior_accepted = {
            task_id: paths
            for task_id, paths in accepted_paths.items()
            if task_id not in set(map(str, batch["ordered_task_ids"]))
        }
        for task_id in map(str, batch["ordered_task_ids"]):
            step = steps[task_id]
            if task_id in completed_tasks:
                if progress != step["previous_candidate_commit"]:
                    raise RecoveryError(
                        "completed batch Tasks are not a canonical prefix"
                    )
                progress = str(step["integrated_candidate_commit"])
                batch_paths[task_id] = tuple(map(str, step["actual_paths"]))
                evidence[task_id] = self._id(
                    "EVID", 100 + int(step["task_index"])
                )
                gates[task_id] = self._gate_id(
                    "TASK_GATE", offset=int(step["task_index"])
                )
                continue
            context = context_by_task.get(task_id)
            if context is None:
                raise RecoveryError("active Task batch context is unavailable")
            if (
                progress != step["previous_candidate_commit"]
                or branch_head != step["previous_candidate_commit"]
            ):
                raise RecoveryError("Task batch candidate prefix drifted")
            outcome = self._drive_task_attempt(
                scheduler=scheduler,
                definition=context.definition,
                task=context.task,
                phase=context.phase,
                task_index=context.task_index,
                branch=branch,
                candidate=str(batch["base_commit"]),
                accepted_paths=prior_accepted,
                provider=provider,
                batch=batch,
                merge_step=step,
                dispose_workspace=False,
            )
            if outcome is None:
                return None
            progress, paths, evidence_id, gate_id = outcome
            branch_head = progress
            completed_tasks.add(task_id)
            batch_paths[task_id] = paths
            evidence[task_id] = evidence_id
            gates[task_id] = gate_id
        if branch_head != progress:
            raise RecoveryError("Task batch branch head differs from completed plan")
        completed_record = {
            "schema_version": "nm-v6/task-batch-completed-v1",
            "batch_id": batch["batch_id"],
            "base_commit": batch["base_commit"],
            "final_candidate_commit": progress,
            "final_candidate_tree": self.git.tree_of(progress),
            "ordered_task_ids": list(batch["ordered_task_ids"]),
            "merge_plan_digest": merge_record["steps_digest"],
        }
        self._record_domain_once(
            "TASK_BATCH_COMPLETED",
            completed_record,
            idempotency_key=(
                f"configured-runtime:task-batch-completed:{batch['batch_id']}"
            ),
        )
        for context in contexts:
            self._dispose_workspace(context.manager, context.workspace, context.root)
        for step in merge_record["steps"]:
            import_ref = str(step["import_ref"])
            imported = self.git.try_resolve_commit(import_ref)
            if imported is not None:
                run_command(
                    ("git", "update-ref", "-d", import_ref, imported),
                    cwd=self.target,
                )
        return progress, batch_paths, evidence, gates

    def _drive_task_attempt(
        self,
        *,
        scheduler: Scheduler,
        definition: TaskDefinition,
        task: Mapping[str, Any],
        phase: Mapping[str, Any],
        task_index: int,
        branch: str,
        candidate: str,
        accepted_paths: Mapping[str, Sequence[str]],
        provider: str,
        batch: Mapping[str, Any] | None = None,
        merge_step: Mapping[str, Any] | None = None,
        dispose_workspace: bool = True,
    ) -> tuple[str, tuple[str, ...], str, str] | None:
        task_id = definition.task_id
        task_entity_id = self._entity_id(task_id)
        owner = f"configured-runtime-{self.identity}"
        retry_budget = int(self.project["scheduler"]["retry_budget"])

        while True:
            task_entity = self.store.get_entity_state("task", task_entity_id)
            if not isinstance(task_entity, Mapping):
                raise ContractError(f"configured Task entity is unavailable: {task_id}")
            task_state = str(task_entity["state"])
            task_payload = task_entity.get("payload", {})
            if not isinstance(task_payload, Mapping):
                raise ContractError("configured Task payload is malformed")

            if task_state == "READY":
                ordinal_raw = task_payload.get("attempt_ordinal", -1)
                if isinstance(ordinal_raw, bool) or not isinstance(ordinal_raw, int):
                    raise ContractError("Task attempt ordinal is malformed")
                ordinal = ordinal_raw + 1
                attempt_id, operation_id = self._attempt_identifiers(
                    task_index, ordinal
                )
                current_candidate = self.git.resolve_commit(
                    f"refs/heads/{branch}"
                )
                if current_candidate != candidate:
                    raise RecoveryError("Task candidate branch changed before dispatch")
                lease = scheduler.acquire(
                    task_id,
                    owner=owner,
                    attempt_id=attempt_id,
                    expected_revision=self._revision(),
                )
                self._entity_transition(
                    "task",
                    task_entity_id,
                    "ACQUIRE_LEASE",
                    payload={
                        "lease_resource_id": task_id,
                        "lease_owner": owner,
                        "state_patch": {
                            "active_attempt_id": attempt_id,
                            "active_operation_id": operation_id,
                            "attempt_ordinal": ordinal,
                            "attempt_base_commit": candidate,
                            "candidate_branch": branch,
                        },
                    },
                    fencing_token=lease.fencing_token,
                )
                task_entity = self.store.get_entity_state("task", task_entity_id)
                assert isinstance(task_entity, Mapping)
                task_state = str(task_entity["state"])
                task_payload = task_entity["payload"]
            else:
                attempt_id = str(task_payload.get("active_attempt_id", ""))
                operation_id = str(task_payload.get("active_operation_id", ""))
                ordinal_raw = task_payload.get("attempt_ordinal")
                candidate_base = task_payload.get("attempt_base_commit")
                candidate_branch = task_payload.get("candidate_branch")
                if (
                    not attempt_id
                    or not operation_id
                    or isinstance(ordinal_raw, bool)
                    or not isinstance(ordinal_raw, int)
                    or not isinstance(candidate_base, str)
                    or not candidate_base
                    or candidate_branch != branch
                ):
                    raise ContractError("active Task attempt binding is incomplete")
                ordinal = ordinal_raw
                expected_attempt, expected_operation = self._attempt_identifiers(
                    task_index, ordinal
                )
                if (attempt_id, operation_id) != (
                    expected_attempt,
                    expected_operation,
                ):
                    raise ContractError("active Task attempt identifier drifted")
                candidate = str(candidate_base)

            lease = self._attempt_lease(
                task_id=task_id,
                attempt_id=attempt_id,
                owner=owner,
            )
            if task_state == "RETRYABLE_FAILURE":
                attempt = self.store.get_entity_state("attempt", attempt_id)
                if not isinstance(attempt, Mapping) or attempt.get("state") not in {
                    "FAILED",
                    "TIMED_OUT",
                    "LOST",
                }:
                    raise RecoveryError(
                        "retryable Task lacks a terminal prior Attempt"
                    )
                binding, _request = self._attempt_binding(
                    attempt,
                    task_id=task_id,
                    phase_id=str(phase["id"]),
                    provider=provider,
                    attempt_id=attempt_id,
                    operation_id=operation_id,
                    owner=owner,
                    fencing_token=int(attempt["payload"]["fencing_token"]),
                    base_commit=candidate,
                    candidate_branch=branch,
                )
                manager, workspace, root = self._task_workspace(
                    binding, task_index=task_index
                )
                if lease is not None and not lease.expired():
                    scheduler.release(lease, expected_revision=self._revision())
                self._entity_transition(
                    "task",
                    task_entity_id,
                    "REQUEUE",
                    payload={
                        "retry_allowed": ordinal < retry_budget,
                        "lease_fenced": True,
                        "state_patch": {"active_attempt_id": None},
                    },
                )
                self._dispose_workspace(manager, workspace, root)
                continue
            if task_state in {"LEASED", "RUNNING"}:
                if lease is None:
                    return None
                if lease.expired():
                    attempt = self.store.get_entity_state("attempt", attempt_id)
                    binding: dict[str, Any] | None = None
                    request: dict[str, Any] | None = None
                    manager: WorkspaceManager | None = None
                    workspace: Workspace | None = None
                    root: Path | None = None
                    if isinstance(attempt, Mapping):
                        binding, request = self._attempt_binding(
                            attempt,
                            task_id=task_id,
                            phase_id=str(phase["id"]),
                            provider=provider,
                            attempt_id=attempt_id,
                            operation_id=operation_id,
                            owner=owner,
                            fencing_token=lease.fencing_token,
                            base_commit=candidate,
                            candidate_branch=branch,
                        )
                        manager, workspace, root = self._task_workspace(
                            binding, task_index=task_index
                        )
                        session_record = self._domain_record(
                            "ADAPTER_SESSION_RECORDED",
                            idempotency_key=(
                                f"configured-runtime:adapter-session:{attempt_id}"
                            ),
                        )
                        result_record = self._domain_record(
                            "ADAPTER_RESULT_RECORDED",
                            idempotency_key=(
                                f"configured-runtime:adapter-result:{attempt_id}"
                            ),
                        )
                        external_reconciled = result_record is not None
                        session_observation: Mapping[str, Any] | None = None
                        if result_record is None and session_record is not None:
                            adapter = self._adapter_for_attempt(provider, manager)
                            session_id = str(session_record.get("session_id", ""))
                            session_observation = adapter.cancel(session_id)
                            external_reconciled = session_observation.get("status") in {
                                "cancelled",
                                "finished",
                            }
                        if not external_reconciled:
                            self._record_domain_once(
                                "ADAPTER_ATTEMPT_STALE",
                                {
                                    "attempt_id": attempt_id,
                                    "task_id": task_id,
                                    "fencing_token": lease.fencing_token,
                                    "classification": "unknown",
                                    "session_observation": (
                                        dict(session_observation)
                                        if isinstance(session_observation, Mapping)
                                        else None
                                    ),
                                },
                                idempotency_key=(
                                    f"configured-runtime:adapter-stale:{attempt_id}"
                                ),
                            )
                            return None
                    attempt = self.store.get_entity_state("attempt", attempt_id)
                    if isinstance(attempt, Mapping) and attempt.get("state") in {
                        "DISPATCHED",
                        "RUNNING",
                        "COLLECTING",
                    }:
                        self._entity_transition(
                            "attempt",
                            attempt_id,
                            "LOSE",
                            payload={"lease_fenced": True},
                        )
                    current_branch = self.git.resolve_commit(
                        f"refs/heads/{branch}"
                    )
                    if current_branch != candidate:
                        if binding is None or request is None or workspace is None:
                            raise RecoveryError(
                                "stale Task advanced candidate without recoverable binding"
                            )
                        result_record = self._domain_record(
                            "ADAPTER_RESULT_RECORDED",
                            idempotency_key=(
                                f"configured-runtime:adapter-result:{attempt_id}"
                            ),
                        )
                        if result_record is None:
                            raise RecoveryError(
                                "stale Task candidate branch changed without a result"
                            )
                        result = adapter_result_to_dict(
                            validate_adapter_result(
                                result_record.get("result"), request=request
                            )
                        )
                        value = result.get("candidate_commit")
                        stale_candidate = (
                            candidate
                            if value is None
                            else run_command(
                                (
                                    "git",
                                    "rev-parse",
                                    "--verify",
                                    f"{value}^{{commit}}",
                                ),
                                cwd=workspace.path,
                            ).stdout.strip()
                        )
                        if current_branch != stale_candidate:
                            raise RecoveryError(
                                "stale Task candidate branch has unrelated changes"
                            )
                        run_command(
                            (
                                "git",
                                "update-ref",
                                f"refs/heads/{branch}",
                                candidate,
                                stale_candidate,
                            ),
                            cwd=self.target,
                        )
                    self._entity_transition(
                        "task",
                        task_entity_id,
                        "LEASE_LOST",
                        payload={
                            "lease_fenced": True,
                            "external_operations_reconciled": True,
                            "state_patch": {"active_attempt_id": None},
                        },
                    )
                    self._record_domain_once(
                        "ADAPTER_ATTEMPT_STALE",
                        {
                            "attempt_id": attempt_id,
                            "task_id": task_id,
                            "fencing_token": lease.fencing_token,
                            "classification": "expired",
                            "session_observation": None,
                        },
                        idempotency_key=(
                            f"configured-runtime:adapter-stale:{attempt_id}"
                        ),
                    )
                    if manager is not None and workspace is not None and root is not None:
                        self._dispose_workspace(manager, workspace, root)
                    continue
                lease = scheduler.heartbeat(
                    lease, expected_revision=self._revision()
                )

            if task_state == "LEASED":
                assert lease is not None
                self._entity_transition(
                    "task",
                    task_entity_id,
                    "START",
                    payload={
                        "lease_resource_id": task_id,
                        "lease_owner": owner,
                    },
                    fencing_token=lease.fencing_token,
                )
                task_state = "RUNNING"

            attempt = self.store.get_entity_state("attempt", attempt_id)
            if not isinstance(attempt, Mapping):
                if task_state != "RUNNING" or lease is None:
                    raise RecoveryError("Task lost its canonical adapter Attempt")
                manager, workspace, root = self._workspace(
                    candidate, f"task-{task_index:03d}"
                )
                request = validate_adapter_request(
                    {
                        "protocol_version": "nm-v6/adapter-request-v1",
                        "operation_id": operation_id,
                        "run_id": self.run_id,
                        "attempt_id": attempt_id,
                        "role": "worker",
                        "workspace": str(workspace.path),
                        "context_manifest": self._context_manifest(
                            task=task,
                            phase=phase,
                            attempt_id=attempt_id,
                        ),
                        "expected_output_schema": "nm-v6/adapter-result-v1",
                        "deadline": (
                            datetime.now(UTC) + timedelta(hours=1)
                        ).isoformat(),
                        "fencing_token": lease.fencing_token,
                        "allowed_capabilities": ["workspace_write"],
                    }
                )
                binding = {
                    "task_id": task_id,
                    "phase_id": str(phase["id"]),
                    "provider": provider,
                    "attempt_id": attempt_id,
                    "operation_id": operation_id,
                    "lease_owner": owner,
                    "fencing_token": lease.fencing_token,
                    "base_commit": candidate,
                    "candidate_branch": branch,
                    "workspace_path": str(workspace.path),
                    "workspace_root": str(root),
                    "workspace_id": workspace.workspace_id,
                    "request_digest": sha256_bytes(canonical_json(request)),
                    "request": request,
                }
                attempt = self._ensure_entity(
                    "attempt",
                    attempt_id,
                    initial_state="CREATED",
                    payload=binding,
                )
            else:
                if lease is None and task_state == "RUNNING":
                    return None
                token = (
                    lease.fencing_token
                    if lease is not None
                    else int(attempt.get("payload", {}).get("fencing_token", -1))
                )
                binding, request = self._attempt_binding(
                    attempt,
                    task_id=task_id,
                    phase_id=str(phase["id"]),
                    provider=provider,
                    attempt_id=attempt_id,
                    operation_id=operation_id,
                    owner=owner,
                    fencing_token=token,
                    base_commit=candidate,
                    candidate_branch=branch,
                )
                manager, workspace, root = self._task_workspace(
                    binding, task_index=task_index
                )

            attempt_state = str(attempt["state"])
            if attempt_state == "CREATED":
                self._entity_transition("attempt", attempt_id, "DISPATCH")
                attempt_state = "DISPATCHED"
            request_record = self._adapter_request_record(binding, request)
            self._record_domain_once(
                "ADAPTER_REQUESTED",
                request_record,
                idempotency_key=(
                    f"configured-runtime:adapter-request:{attempt_id}"
                ),
            )

            result_record = self._domain_record(
                "ADAPTER_RESULT_RECORDED",
                idempotency_key=f"configured-runtime:adapter-result:{attempt_id}",
            )
            base_candidate = candidate
            if task_state == "RUNNING":
                assert lease is not None
                scheduler.validate_result(
                    task_id=task_id,
                    owner=owner,
                    fencing_token=lease.fencing_token,
                    lease=lease,
                )
                session_record = self._domain_record(
                    "ADAPTER_SESSION_RECORDED",
                    idempotency_key=(
                        f"configured-runtime:adapter-session:{attempt_id}"
                    ),
                )
                if result_record is None:
                    adapter = self._adapter_for_attempt(provider, manager)
                    session = adapter.start(request)
                    session_id = str(session["session_id"])
                    checkpoint("runtime.after_adapter_session_start")
                    expected_session_record = {
                        "task_id": task_id,
                        "provider": provider,
                        "attempt_id": attempt_id,
                        "operation_id": operation_id,
                        "request_digest": binding["request_digest"],
                        "session_id": session_id,
                        "lease_owner": owner,
                        "fencing_token": lease.fencing_token,
                    }
                    if session_record is not None and session_record != expected_session_record:
                        raise ContractError("persisted adapter session binding drifted")
                    session_record = self._record_domain_once(
                        "ADAPTER_SESSION_RECORDED",
                        expected_session_record,
                        idempotency_key=(
                            f"configured-runtime:adapter-session:{attempt_id}"
                        ),
                    )
                    attempt = self.store.get_entity_state("attempt", attempt_id)
                    assert isinstance(attempt, Mapping)
                    if attempt["state"] == "DISPATCHED":
                        self._entity_transition(
                            "attempt",
                            attempt_id,
                            "START",
                            payload={
                                "lease_resource_id": task_id,
                                "lease_owner": owner,
                                "state_patch": {
                                    "session_id": session_id,
                                    "request_digest": binding["request_digest"],
                                },
                            },
                            fencing_token=lease.fencing_token,
                        )
                    deadline = datetime.fromisoformat(
                        str(request["deadline"]).replace("Z", "+00:00")
                    )
                    heartbeat_seconds = int(
                        self.project["scheduler"]["heartbeat_seconds"]
                    )
                    next_heartbeat = time.monotonic() + heartbeat_seconds
                    while True:
                        observation = adapter.poll(session_id)
                        if observation["status"] != "running":
                            break
                        if datetime.now(UTC) >= deadline:
                            adapter.cancel(session_id)
                            break
                        if time.monotonic() >= next_heartbeat:
                            lease = scheduler.heartbeat(
                                lease, expected_revision=self._revision()
                            )
                            next_heartbeat = time.monotonic() + heartbeat_seconds
                        time.sleep(0.1)
                    scheduler.validate_result(
                        task_id=task_id,
                        owner=owner,
                        fencing_token=lease.fencing_token,
                        lease=lease,
                    )
                    result = adapter.collect_dict(session_id)
                    result_record = self._record_domain_once(
                        "ADAPTER_RESULT_RECORDED",
                        {
                            **expected_session_record,
                            "result": result,
                        },
                        idempotency_key=(
                            f"configured-runtime:adapter-result:{attempt_id}"
                        ),
                    )
                    checkpoint("runtime.after_adapter_result_record")
                else:
                    if session_record is None:
                        raise ContractError(
                            "adapter result lacks its canonical session record"
                        )
                    expected_fields = {
                        "task_id": task_id,
                        "provider": provider,
                        "attempt_id": attempt_id,
                        "operation_id": operation_id,
                        "request_digest": binding["request_digest"],
                        "session_id": session_record.get("session_id"),
                        "lease_owner": owner,
                        "fencing_token": lease.fencing_token,
                    }
                    if any(result_record.get(key) != value for key, value in expected_fields.items()):
                        raise ContractError("persisted adapter result binding drifted")
                    attempt = self.store.get_entity_state("attempt", attempt_id)
                    assert isinstance(attempt, Mapping)
                    if attempt["state"] == "DISPATCHED":
                        self._entity_transition(
                            "attempt",
                            attempt_id,
                            "START",
                            payload={
                                "lease_resource_id": task_id,
                                "lease_owner": owner,
                                "state_patch": {
                                    "session_id": session_record["session_id"],
                                    "request_digest": binding["request_digest"],
                                },
                            },
                            fencing_token=lease.fencing_token,
                        )

                result = adapter_result_to_dict(
                    validate_adapter_result(
                        result_record.get("result"), request=request
                    )
                )
                if result["status"] != "succeeded":
                    attempt = self.store.get_entity_state("attempt", attempt_id)
                    assert isinstance(attempt, Mapping)
                    if attempt["state"] == "RUNNING":
                        self._entity_transition(
                            "attempt",
                            attempt_id,
                            "COLLECT",
                            payload={
                                "lease_resource_id": task_id,
                                "lease_owner": owner,
                            },
                            fencing_token=lease.fencing_token,
                        )
                    attempt = self.store.get_entity_state("attempt", attempt_id)
                    assert isinstance(attempt, Mapping)
                    if attempt["state"] == "COLLECTING":
                        self._entity_transition(
                            "attempt",
                            attempt_id,
                            "FAIL",
                            payload={
                                "lease_resource_id": task_id,
                                "lease_owner": owner,
                                "state_patch": {
                                    "adapter_status": result["status"]
                                },
                            },
                            fencing_token=lease.fencing_token,
                        )
                    if ordinal >= retry_budget:
                        self._entity_transition(
                            "task",
                            task_entity_id,
                            "BLOCK",
                            payload={
                                "lease_resource_id": task_id,
                                "lease_owner": owner,
                            },
                            fencing_token=lease.fencing_token,
                        )
                        scheduler.release(lease, expected_revision=self._revision())
                        self._dispose_workspace(manager, workspace, root)
                        raise RecoveryError("configured adapter retry budget exhausted")
                    self._entity_transition(
                        "task",
                        task_entity_id,
                        "RETRYABLE_FAILURE",
                        payload={
                            "retry_allowed": True,
                            "lease_resource_id": task_id,
                            "lease_owner": owner,
                        },
                        fencing_token=lease.fencing_token,
                    )
                    scheduler.release(lease, expected_revision=self._revision())
                    self._entity_transition(
                        "task",
                        task_entity_id,
                        "REQUEUE",
                        payload={
                            "retry_allowed": True,
                            "lease_fenced": True,
                            "state_patch": {"active_attempt_id": None},
                        },
                    )
                    self._dispose_workspace(manager, workspace, root)
                    continue

                candidate_value = result.get("candidate_commit")
                task_candidate = (
                    candidate
                    if candidate_value is None
                    else run_command(
                        (
                            "git",
                            "rev-parse",
                            "--verify",
                            f"{candidate_value}^{{commit}}",
                        ),
                        cwd=workspace.path,
                    ).stdout.strip()
                )
                actual_paths = tuple(
                    sorted(
                        path
                        for path in run_command(
                            (
                                "git",
                                "diff",
                                "--name-only",
                                "-z",
                                candidate,
                                task_candidate,
                                "--",
                            ),
                            cwd=workspace.path,
                        ).stdout.split("\0")
                        if path
                    )
                )
                if tuple(sorted(result["changed_paths"])) != actual_paths:
                    raise ContractError(
                        "adapter changed_paths differs from the original-base Git diff"
                    )
                scheduler.assert_actual_diff_isolated(
                    task_id, actual_paths, accepted_paths
                )
                current_branch = self.git.resolve_commit(f"refs/heads/{branch}")
                allowed_branch_values = {candidate, task_candidate}
                if merge_step is not None:
                    allowed_branch_values.update(
                        {
                            str(merge_step["previous_candidate_commit"]),
                            str(merge_step["integrated_candidate_commit"]),
                        }
                    )
                if current_branch not in allowed_branch_values:
                    raise RecoveryError(
                        "candidate branch differs from both adapter base and result"
                    )
                verified_candidate = task_candidate
                attempt = self.store.get_entity_state("attempt", attempt_id)
                assert isinstance(attempt, Mapping)
                if attempt["state"] == "RUNNING":
                    self._entity_transition(
                        "attempt",
                        attempt_id,
                        "COLLECT",
                        payload={
                            "lease_resource_id": task_id,
                            "lease_owner": owner,
                        },
                        fencing_token=lease.fencing_token,
                    )
                attempt = self.store.get_entity_state("attempt", attempt_id)
                assert isinstance(attempt, Mapping)
                if attempt["state"] == "COLLECTING":
                    self._entity_transition(
                        "attempt",
                        attempt_id,
                        "SUCCEED",
                        payload={
                            "structured_result_valid": True,
                            "lease_resource_id": task_id,
                            "lease_owner": owner,
                            "state_patch": {
                                "candidate_commit": verified_candidate,
                                "changed_paths": list(actual_paths),
                            },
                        },
                        fencing_token=lease.fencing_token,
                    )
                task_entity = self.store.get_entity_state("task", task_entity_id)
                assert isinstance(task_entity, Mapping)
                if task_entity["state"] == "RUNNING":
                    self._entity_transition(
                        "task",
                        task_entity_id,
                        "COLLECT_CANDIDATE",
                        payload={
                            "structured_result_valid": True,
                            "candidate_commit": verified_candidate,
                            "state_patch": {
                                "candidate_commit": verified_candidate,
                                "changed_paths": list(actual_paths),
                            },
                            "lease_resource_id": task_id,
                            "lease_owner": owner,
                        },
                        fencing_token=lease.fencing_token,
                    )
                scheduler.release(lease, expected_revision=self._revision())
                task_state = "CANDIDATE"
            else:
                result_record = self._domain_record(
                    "ADAPTER_RESULT_RECORDED",
                    idempotency_key=(
                        f"configured-runtime:adapter-result:{attempt_id}"
                    ),
                )
                if result_record is None:
                    raise RecoveryError("advanced Task lacks canonical adapter result")
                result = adapter_result_to_dict(
                    validate_adapter_result(
                        result_record.get("result"), request=request
                    )
                )
                candidate_value = result.get("candidate_commit")
                task_candidate = (
                    candidate
                    if candidate_value is None
                    else run_command(
                        (
                            "git",
                            "rev-parse",
                            "--verify",
                            f"{candidate_value}^{{commit}}",
                        ),
                        cwd=workspace.path,
                    ).stdout.strip()
                )
                actual_paths = tuple(
                    sorted(
                        path
                        for path in run_command(
                            (
                                "git",
                                "diff",
                                "--name-only",
                                "-z",
                                candidate,
                                task_candidate,
                                "--",
                            ),
                            cwd=workspace.path,
                        ).stdout.split("\0")
                        if path
                    )
                )
                if (
                    result["status"] != "succeeded"
                    or tuple(sorted(result["changed_paths"])) != actual_paths
                ):
                    raise RecoveryError("advanced Task adapter result binding drifted")
                scheduler.assert_actual_diff_isolated(
                    task_id, actual_paths, accepted_paths
                )
                verified_candidate = task_candidate
                current_branch = self.git.resolve_commit(f"refs/heads/{branch}")
                allowed_branch_values = {base_candidate, verified_candidate}
                if merge_step is not None:
                    allowed_branch_values.update(
                        {
                            str(merge_step["previous_candidate_commit"]),
                            str(merge_step["integrated_candidate_commit"]),
                        }
                    )
                if current_branch not in allowed_branch_values:
                    raise RecoveryError(
                        "candidate branch differs from both adapter base and gated result"
                    )
                if lease is not None and not lease.expired():
                    scheduler.release(lease, expected_revision=self._revision())

            task_entity = self.store.get_entity_state("task", task_entity_id)
            assert isinstance(task_entity, Mapping)
            if task_entity["state"] == "CANDIDATE":
                self._entity_transition(
                    "task",
                    task_entity_id,
                    "START_VERIFICATION",
                    payload=(
                        {
                            "state_patch": {
                                "candidate_commit": merge_step[
                                    "integrated_candidate_commit"
                                ],
                                "task_result_commit": merge_step[
                                    "task_result_commit"
                                ],
                            }
                        }
                        if merge_step is not None
                        else None
                    ),
                )

            evidence_id = self._id("EVID", 100 + task_index)
            existing_evidence = self.store.get_evidence(evidence_id)
            acceptance_ids = [str(value) for value in task.get("acceptance_ids", [])]
            assertions = {
                "candidate_diff_allowed": True,
                "candidate_commit_identified": bool(verified_candidate),
                "task_acceptance_rerun_passed": True,
                "no_prohibited_mutation": not any(
                    path == ".nm/runtime" or path.startswith(".nm/runtime/")
                    for path in actual_paths
                ),
                **{f"acceptance:{identifier}": True for identifier in acceptance_ids},
            }
            if isinstance(existing_evidence, Mapping):
                self.evidence_store.validate(existing_evidence)
                try:
                    evidence_observation = json.loads(
                        self.evidence_store.read_blob(
                            str(existing_evidence["stdout_digest"])
                        )
                    )
                except (OSError, ValueError) as exc:
                    raise RecoveryError(
                        "persisted Task evidence observation is unavailable"
                    ) from exc
                if evidence_observation.get("changed_paths") != list(actual_paths):
                    raise RecoveryError("persisted Task evidence changed-path binding drifted")
            else:
                executor = ActionExecutor(
                    isolation_backend=manager.isolation_backend,
                    secret_resolver=_ProjectSecretResolver(self.target, self.project),
                )
                verification_results = [
                    self._execute(
                        executor,
                        workspace,
                        str(self.project["actions"]["task_verify"]),
                    )
                ]
                acceptance_results: dict[str, ActionResult] = {}
                acceptance_map = self.traceability.get("acceptance_actions", {})
                for acceptance_id in acceptance_ids:
                    action_id = acceptance_map.get(acceptance_id)
                    if not isinstance(action_id, str):
                        raise ContractError(
                            f"Task {task_id} has no acceptance action for {acceptance_id}"
                        )
                    if action_id == self.project["actions"]["task_verify"]:
                        acceptance_result = verification_results[0]
                    else:
                        acceptance_result = self._execute(
                            executor, workspace, action_id
                        )
                        verification_results.append(acceptance_result)
                    acceptance_results[acceptance_id] = acceptance_result
                assertions["task_acceptance_rerun_passed"] = all(
                    item.status == "succeeded" for item in verification_results
                )
                for acceptance_id, acceptance_result in acceptance_results.items():
                    assertions[f"acceptance:{acceptance_id}"] = (
                        acceptance_result.status == "succeeded"
                    )
                evidence_observation = {
                    "adapter_result": result,
                    "changed_paths": list(actual_paths),
                    "verification": [
                        item.as_dict() for item in verification_results
                    ],
                }
            evidence_id = self._evidence(
                100 + task_index,
                f"task-{task_id}",
                evidence_observation,
                assertions=assertions,
                source_commit=str(binding["base_commit"]),
                candidate_commit=verified_candidate,
                attempt_id=attempt_id,
                subject_ids=(task_id, *acceptance_ids),
            )
            gate_candidate = verified_candidate
            gate_evidence_ids = [evidence_id]
            integration_evidence_id: str | None = None
            if merge_step is not None:
                if batch is None:
                    raise ContractError("Task merge step lacks its batch binding")
                if (
                    merge_step.get("task_id") != task_id
                    or merge_step.get("attempt_id") != attempt_id
                    or merge_step.get("task_result_commit") != verified_candidate
                    or merge_step.get("actual_paths") != list(actual_paths)
                    or merge_step.get("batch_base_commit") != binding["base_commit"]
                ):
                    raise RecoveryError("Task batch merge step binding drifted")
                gate_candidate = str(merge_step["integrated_candidate_commit"])
                integration_evidence_id = self._evidence(
                    100 + task_index,
                    f"task-integration-{task_id}",
                    {
                        "batch_id": batch["batch_id"],
                        "task_result_evidence_id": evidence_id,
                        "task_result_commit": verified_candidate,
                        "task_result_tree": merge_step["task_result_tree"],
                        "changed_paths": list(actual_paths),
                        "previous_candidate_commit": merge_step[
                            "previous_candidate_commit"
                        ],
                        "integrated_candidate_commit": gate_candidate,
                        "integrated_candidate_tree": merge_step[
                            "integrated_candidate_tree"
                        ],
                    },
                    assertions={
                        **assertions,
                        "batch_actual_paths_disjoint": True,
                        "task_result_applied_exactly": True,
                    },
                    source_commit=str(merge_step["previous_candidate_commit"]),
                    candidate_commit=gate_candidate,
                    attempt_id=attempt_id,
                    subject_ids=(task_id, f"batch:{batch['batch_id']}"),
                    scope=f"{batch['batch_scope']}-merge",
                )
                gate_evidence_ids = [integration_evidence_id]
            gate_id = self._gate(
                "TASK_GATE",
                tuple(gate_evidence_ids),
                offset=task_index,
                bindings={"candidate_commit": gate_candidate},
                subject_ids=(self.run_id, task_entity_id),
            )
            if merge_step is not None:
                checkpoint("runtime.after_task_batch_gate")
            current_branch = self.git.resolve_commit(f"refs/heads/{branch}")
            progress_source = base_candidate
            if merge_step is not None:
                progress_source = str(merge_step["previous_candidate_commit"])
                if current_branch == progress_source and gate_candidate != progress_source:
                    run_command(
                        (
                            "git",
                            "update-ref",
                            f"refs/heads/{branch}",
                            gate_candidate,
                            progress_source,
                        ),
                        cwd=self.target,
                    )
                    current_branch = gate_candidate
                    checkpoint("runtime.after_adapter_candidate_import")
                elif current_branch != gate_candidate:
                    raise RecoveryError(
                        "candidate branch does not match the planned batch step"
                    )
                verified_candidate = gate_candidate
            elif current_branch == base_candidate and verified_candidate != base_candidate:
                verified_candidate = self._update_candidate_from_workspace(
                    branch=branch,
                    before=base_candidate,
                    workspace=workspace,
                    candidate=verified_candidate,
                )
                checkpoint("runtime.after_adapter_candidate_import")
            elif current_branch != verified_candidate:
                raise RecoveryError(
                    "candidate branch does not match the gated Task result"
                )
            self._record_domain_once(
                "CANDIDATE_BRANCH_ADVANCED",
                {
                    "branch": branch,
                    "run_id": self.run_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "gate_id": gate_id,
                    "source_commit": progress_source,
                    "candidate_commit": verified_candidate,
                    **(
                        {
                            "batch_id": batch["batch_id"],
                            "task_result_commit": merge_step[
                                "task_result_commit"
                            ],
                            "integration_evidence_id": integration_evidence_id,
                        }
                        if batch is not None and merge_step is not None
                        else {}
                    ),
                },
                idempotency_key=(
                    f"configured-runtime:candidate-progress:{attempt_id}"
                ),
            )
            task_entity = self.store.get_entity_state("task", task_entity_id)
            assert isinstance(task_entity, Mapping)
            if task_entity["state"] == "VERIFYING":
                self._entity_transition(
                    "task", task_entity_id, "VERIFY", gate_ids=(gate_id,)
                )
            if dispose_workspace:
                self._dispose_workspace(manager, workspace, root)
            return verified_candidate, actual_paths, evidence_id, gate_id

    # -- Hotfix implementation -------------------------------------------

    def _start_hotfix(self, run: Mapping[str, Any]) -> bool | None:
        if run.get("run_kind") != "hotfix":
            return None
        authorization = self._authorization(
            "hotfix", protected_ref=self.git.stable_branch
        )
        if authorization is None:
            return self._wait(run, "trusted_hotfix_authorization")
        authorization_id = self._authorization_id(authorization)
        branch, base = self._ensure_candidate_branch(
            hotfix_authorization_id=authorization_id
        )
        return self._transition(
            run,
            "START_HOTFIX",
            payload={"protected_ref": self.git.stable_branch},
            state_patch={
                "runtime_hotfix_authorization": authorization_id,
                "runtime_hotfix_branch": branch,
                "runtime_hotfix_base_commit": base,
                "runtime_hotfix_base_tree": self.git.tree_of(base),
                "runtime_candidate_branch": branch,
                "runtime_candidate_commit": base,
            },
            authorization_id=authorization_id,
        )

    def _implement_hotfix(self, run: Mapping[str, Any]) -> bool:
        provider = self._adapter_provider()
        if provider is None:
            return self._wait(run, "single_configured_adapter_provider")
        payload = self._payload(run)
        branch, candidate = self._ensure_candidate_branch()
        if branch != payload.get("runtime_hotfix_branch"):
            raise RecoveryError("hotfix branch differs from its persisted run binding")
        graph = self._task_graph()
        scheduler = Scheduler(
            graph,
            ReducerLeaseAuthority(self.reducer, run_id=self.run_id),
            max_workers=int(self.project["scheduler"]["max_workers"]),
            lease_seconds=int(self.project["scheduler"]["lease_seconds"]),
        )
        completed_tasks = set(payload.get("runtime_completed_tasks", []))
        accepted_paths: dict[str, Sequence[str]] = {}
        task_evidence: dict[str, str] = {}
        task_gates: dict[str, str] = {}
        tasks = {str(item["id"]): item for item in self._tasks()}
        phases = {str(item["id"]): item for item in self._phases()}
        global_index = {
            str(item["id"]): index
            for index, item in enumerate(self._tasks(), start=1)
        }
        for phase in self._phases():
            phase_entity_id = self._entity_id(str(phase["id"]))
            phase_entity = self._ensure_entity(
                "phase",
                phase_entity_id,
                initial_state="PLANNED",
                payload={"traceability_id": phase["id"]},
            )
            if phase_entity["state"] == "PLANNED":
                self._entity_transition("phase", phase_entity_id, "START")
        for task_id, task in tasks.items():
            index = global_index[task_id]
            entity = self.store.get_entity_state("task", self._entity_id(task_id))
            evidence_id = self._id("EVID", 100 + index)
            gate_id = self._gate_id("TASK_GATE", offset=index)
            evidence = self.store.get_evidence(evidence_id)
            gate = self.store.get_gate(gate_id)
            if (
                isinstance(entity, Mapping)
                and entity.get("state") in {"VERIFIED", "INTEGRATED"}
                and isinstance(evidence, Mapping)
                and isinstance(gate, Mapping)
                and gate.get("result") == "passed"
            ):
                self.evidence_store.validate(evidence)
                completed_tasks.add(task_id)
                task_evidence[task_id] = evidence_id
                task_gates[task_id] = gate_id
                try:
                    observation = json.loads(
                        self.evidence_store.read_blob(str(evidence["stdout_digest"]))
                    )
                except (OSError, ValueError):
                    observation = {}
                paths = observation.get("changed_paths", [])
                if isinstance(paths, list):
                    accepted_paths[task_id] = tuple(map(str, paths))
        while completed_tasks != set(tasks):
            try:
                batch_outcome = self._drive_task_batch(
                    scope_id="hotfix-implementation",
                    scheduler=scheduler,
                    graph=graph,
                    tasks=tasks,
                    phases=phases,
                    global_index=global_index,
                    completed_tasks=completed_tasks,
                    accepted_paths=accepted_paths,
                    branch=branch,
                    candidate=candidate,
                    provider=provider,
                )
            except _TaskBatchAttention:
                return True
            if batch_outcome is None:
                return self._wait(run, "active_adapter_attempt_reconciliation")
            candidate, paths_by_task, evidence_by_task, gates_by_task = batch_outcome
            accepted_paths.update(paths_by_task)
            task_evidence.update(evidence_by_task)
            task_gates.update(gates_by_task)

        phase_gates: dict[str, str] = {}
        for phase_index, phase in enumerate(self._phases(), start=1):
            phase_id = str(phase["id"])
            phase_entity_id = self._entity_id(phase_id)
            phase_entity = self.store.get_entity_state("phase", phase_entity_id)
            if not isinstance(phase_entity, Mapping):
                raise RecoveryError("hotfix Phase entity is unavailable")
            if phase_entity["state"] == "ACTIVE":
                self._entity_transition(
                    "phase",
                    phase_entity_id,
                    "START_VERIFICATION",
                    payload={"state_patch": {"candidate_commit": candidate}},
                )
            phase_tasks = [
                task for task in self._tasks() if task.get("phase_id") == phase_id
            ]
            phase_task_evidence = tuple(
                task_evidence[str(task["id"])] for task in phase_tasks
            )
            manager, workspace, root = self._workspace(
                candidate, f"hotfix-phase-{phase_index:03d}"
            )
            try:
                executor = ActionExecutor(isolation_backend=manager.isolation_backend)
                phase_result = self._execute(
                    executor,
                    workspace,
                    str(self.project["actions"]["phase_verify"]),
                )
                full_result = self._execute(
                    executor,
                    workspace,
                    str(self.project["actions"]["full_verify"]),
                )
            finally:
                self._dispose_workspace(manager, workspace, root)
            evidence_id = self._evidence(
                300 + phase_index,
                f"hotfix-phase-{phase_id}",
                {
                    "phase_result": phase_result.as_dict(),
                    "full_result": full_result.as_dict(),
                    "task_gates": {
                        str(task["id"]): task_gates[str(task["id"])]
                        for task in phase_tasks
                    },
                },
                assertions={
                    "mandatory_phase_tasks_verified": all(
                        str(task["id"]) in completed_tasks
                        for task in phase_tasks
                        if not task.get("optional", False)
                    ),
                    "skips_permitted": True,
                    "phase_verification_passed": phase_result.status == "succeeded"
                    and full_result.status == "succeeded",
                },
                source_commit=candidate,
                candidate_commit=candidate,
                subject_ids=(phase_id,),
            )
            phase_gate = self._gate(
                "PHASE_GATE",
                (evidence_id, *phase_task_evidence),
                offset=phase_index,
                bindings={"candidate_commit": candidate},
                subject_ids=(
                    self.run_id,
                    phase_entity_id,
                    *(self._entity_id(str(task["id"])) for task in phase_tasks),
                ),
            )
            phase_gates[phase_id] = phase_gate
            phase_entity = self.store.get_entity_state("phase", phase_entity_id)
            assert isinstance(phase_entity, Mapping)
            if phase_entity["state"] == "VERIFYING" and run.get("mode") == "auto":
                self._entity_transition(
                    "phase", phase_entity_id, "ACCEPT", gate_ids=(phase_gate,)
                )
            elif phase_entity["state"] == "VERIFYING":
                self._entity_transition(
                    "phase",
                    phase_entity_id,
                    "AWAIT_ACCEPTANCE",
                    gate_ids=(phase_gate,),
                )
            phase_entity = self.store.get_entity_state("phase", phase_entity_id)
            assert isinstance(phase_entity, Mapping)
            if phase_entity["state"] == "AWAITING_ACCEPTANCE":
                authorization = self._authorization("phase_accept")
                if authorization is None:
                    return self._wait(run, f"phase_acceptance:{phase_id}")
                self._entity_transition(
                    "phase",
                    phase_entity_id,
                    "ACCEPT",
                    gate_ids=(phase_gate,),
                    authorization_id=self._authorization_id(authorization),
                )
            for task in phase_tasks:
                task_entity_id = self._entity_id(str(task["id"]))
                task_entity = self.store.get_entity_state("task", task_entity_id)
                if isinstance(task_entity, Mapping) and task_entity["state"] == "VERIFIED":
                    self._entity_transition(
                        "task",
                        task_entity_id,
                        "MARK_INTEGRATED",
                        gate_ids=(phase_gate,),
                    )
        return self._transition(
            run,
            "START_HOTFIX_VERIFICATION",
            state_patch={
                "runtime_candidate_branch": branch,
                "runtime_candidate_commit": candidate,
                "runtime_hotfix_candidate_commit": candidate,
                "runtime_hotfix_candidate_tree": self.git.tree_of(candidate),
                "runtime_completed_tasks": sorted(completed_tasks),
                "runtime_task_evidence": task_evidence,
                "runtime_task_gates": task_gates,
                "runtime_hotfix_phase_gates": phase_gates,
            },
        )

    # -- Task, Phase, and dev integration --------------------------------

    def _implement_phase(self, run: Mapping[str, Any]) -> bool:
        provider = self._adapter_provider()
        if provider is None:
            return self._wait(run, "single_configured_adapter_provider")
        payload = self._payload(run)
        completed_phases = set(payload.get("runtime_completed_phases", []))
        completed_tasks = set(payload.get("runtime_completed_tasks", []))
        phase = next(
            (
                item
                for item in self._phases()
                if item["id"] not in completed_phases
                and set(item.get("depends_on", [])) <= completed_phases
            ),
            None,
        )
        if phase is None:
            raise ContractError("no schedulable Phase remains in IMPLEMENTING")
        phase_tasks = [
            item for item in self._tasks() if item.get("phase_id") == phase["id"]
        ]
        if not phase_tasks:
            raise ContractError(f"Phase {phase['id']} has no declared Tasks")
        phase_ids = {str(item["id"]) for item in phase_tasks}
        phase_graph = TaskGraph(
            TaskDefinition(
                str(item["id"]),
                dependencies=tuple(
                    dependency
                    for dependency in item.get("depends_on", [])
                    if dependency in phase_ids
                ),
                write_set=tuple(item.get("write_set", [])),
                optional=bool(item.get("optional", False)),
            )
            for item in phase_tasks
        )
        scheduler = Scheduler(
            phase_graph,
            ReducerLeaseAuthority(self.reducer, run_id=self.run_id),
            max_workers=int(self.project["scheduler"]["max_workers"]),
            lease_seconds=int(self.project["scheduler"]["lease_seconds"]),
        )
        branch, candidate = self._ensure_candidate_branch()
        phase_entity_id = self._entity_id(str(phase["id"]))
        phase_entity = self._ensure_entity(
            "phase",
            phase_entity_id,
            initial_state="PLANNED",
            payload={"traceability_id": phase["id"]},
        )
        if phase_entity["state"] == "PLANNED":
            self._entity_transition("phase", phase_entity_id, "START")
        accepted_paths: dict[str, Sequence[str]] = {}
        phase_completed = completed_tasks & phase_ids
        task_by_id = {str(item["id"]): item for item in phase_tasks}
        global_index = {
            str(item["id"]): index
            for index, item in enumerate(self._tasks(), start=1)
        }
        task_evidence: dict[str, str] = {}
        task_gates: dict[str, str] = {}
        for task_id in sorted(phase_ids):
            index = global_index[task_id]
            entity = self.store.get_entity_state(
                "task", self._entity_id(task_id)
            )
            evidence_id = self._id("EVID", 100 + index)
            gate_id = self._gate_id("TASK_GATE", offset=index)
            evidence = self.store.get_evidence(evidence_id)
            gate = self.store.get_gate(gate_id)
            if (
                isinstance(entity, Mapping)
                and entity.get("state") in {"VERIFIED", "INTEGRATED"}
                and isinstance(evidence, Mapping)
                and isinstance(gate, Mapping)
                and gate.get("result") == "passed"
            ):
                self.evidence_store.validate(evidence)
                phase_completed.add(task_id)
                completed_tasks.add(task_id)
                task_evidence[task_id] = evidence_id
                task_gates[task_id] = gate_id
                try:
                    observation = json.loads(
                        self.evidence_store.read_blob(
                            str(evidence["stdout_digest"])
                        )
                    )
                except (ValueError, OSError):
                    observation = {}
                paths = observation.get("changed_paths", [])
                if isinstance(paths, list):
                    accepted_paths[task_id] = tuple(
                        str(path) for path in paths
                    )
        while phase_completed != phase_ids:
            try:
                batch_outcome = self._drive_task_batch(
                    scope_id=f"phase:{phase['id']}",
                    scheduler=scheduler,
                    graph=phase_graph,
                    tasks=task_by_id,
                    phases={str(phase["id"]): phase},
                    global_index=global_index,
                    completed_tasks=phase_completed,
                    accepted_paths=accepted_paths,
                    branch=branch,
                    candidate=candidate,
                    provider=provider,
                )
            except _TaskBatchAttention:
                return True
            if batch_outcome is None:
                return self._wait(run, "active_adapter_attempt_reconciliation")
            candidate, paths_by_task, evidence_by_task, gates_by_task = batch_outcome
            accepted_paths.update(paths_by_task)
            task_evidence.update(evidence_by_task)
            task_gates.update(gates_by_task)
            completed_tasks.update(phase_completed)
        phase_entity = self.store.get_entity_state("phase", phase_entity_id)
        if isinstance(phase_entity, Mapping) and phase_entity["state"] == "ACTIVE":
            self._entity_transition(
                "phase",
                phase_entity_id,
                "START_VERIFICATION",
                payload={"state_patch": {"candidate_commit": candidate}},
            )
        return self._transition(
            run,
            "START_PHASE_VERIFICATION",
            state_patch={
                "runtime_active_phase": phase["id"],
                "runtime_candidate_branch": branch,
                "runtime_candidate_commit": candidate,
                "runtime_completed_tasks": sorted(completed_tasks),
                "runtime_task_evidence": task_evidence,
                "runtime_task_gates": task_gates,
            },
        )

    def _verify_phase(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        phase_id = payload.get("runtime_active_phase")
        candidate = payload.get("runtime_candidate_commit")
        branch = payload.get("runtime_candidate_branch")
        if not all(isinstance(value, str) and value for value in (phase_id, candidate, branch)):
            raise ContractError("Phase verification lacks its persisted candidate binding")
        phase_index = next(
            index
            for index, item in enumerate(self._phases(), start=1)
            if item["id"] == phase_id
        )
        manager, workspace, root = self._workspace(
            str(candidate), f"phase-{phase_index:03d}"
        )
        try:
            executor = ActionExecutor(
                isolation_backend=manager.isolation_backend,
                secret_resolver=_ProjectSecretResolver(self.target, self.project),
            )
            phase_result = self._execute(
                executor,
                workspace,
                str(self.project["actions"]["phase_verify"]),
            )
            full_result = self._execute(
                executor,
                workspace,
                str(self.project["actions"]["full_verify"]),
            )
        finally:
            self._dispose_workspace(manager, workspace, root)
        target_commit = self.git.fetch_dev(reconcile_local=True)
        authorization = self._authorization(
            "integrate_dev", protected_ref=self.git.integration_branch
        )
        assertions = {
            "mandatory_phase_tasks_verified": all(
                task["id"] in set(payload.get("runtime_completed_tasks", []))
                for task in self._tasks()
                if task.get("phase_id") == phase_id and not task.get("optional", False)
            ),
            "skips_permitted": True,
            "phase_verification_passed": phase_result.status == "succeeded",
            "target_is_dev": self.git.integration_branch == "dev",
            "candidate_lineage_allowed": self.git.is_ancestor(
                target_commit, str(candidate)
            ),
            "expected_target_unchanged": self.git.remote_head("dev")
            == target_commit,
            "simulated_result_tree_valid": self.git.simulate_result_tree(
                source_commit=str(candidate),
                target_commit=target_commit,
                strategy="fast_forward",
            )
            == self.git.tree_of(str(candidate)),
            "full_verification_passed": full_result.status == "succeeded",
        }
        evidence_id = self._id("EVID", 300 + phase_index)
        existing_phase_evidence = self.store.get_evidence(evidence_id)
        if isinstance(existing_phase_evidence, Mapping):
            self.evidence_store.validate(existing_phase_evidence)
            if (
                existing_phase_evidence.get("source_commit") != candidate
                or existing_phase_evidence.get("candidate_commit") != candidate
                or str(phase_id)
                not in existing_phase_evidence.get("subject_ids", [])
            ):
                raise RecoveryError("persisted Phase verification evidence drifted")
        else:
            evidence_id = self._evidence(
                300 + phase_index,
                f"phase-{phase_id}",
                {
                    "phase_result": phase_result.as_dict(),
                    "full_result": full_result.as_dict(),
                    "task_gates": payload.get("runtime_task_gates", {}),
                    "target_commit": target_commit,
                },
                assertions=assertions,
                source_commit=str(candidate),
                candidate_commit=str(candidate),
                subject_ids=(str(phase_id),),
            )
        phase_entity_id = self._entity_id(str(phase_id))
        phase_tasks = tuple(
            task
            for task in self._tasks()
            if task.get("phase_id") == phase_id
        )
        phase_task_entities = tuple(
            self._entity_id(str(task["id"])) for task in phase_tasks
        )
        task_evidence_map = payload.get("runtime_task_evidence", {})
        if not isinstance(task_evidence_map, Mapping):
            raise RecoveryError("Phase lacks its canonical Task evidence map")
        phase_task_evidence = tuple(
            str(task_evidence_map.get(str(task["id"]), ""))
            for task in phase_tasks
        )
        if any(not evidence for evidence in phase_task_evidence):
            raise RecoveryError("Phase is missing Task evidence")
        for task_evidence_id in phase_task_evidence:
            receipt = self.store.get_evidence(task_evidence_id)
            if not isinstance(receipt, Mapping):
                raise RecoveryError("Phase Task evidence receipt is missing")
            self.evidence_store.validate(receipt)
        phase_gate_evidence = (evidence_id, *phase_task_evidence)
        phase_gate = self._gate(
            "PHASE_GATE",
            phase_gate_evidence,
            offset=phase_index,
            bindings={"candidate_commit": candidate},
            subject_ids=(self.run_id, phase_entity_id, *phase_task_entities),
        )
        patch = {
            "runtime_phase_evidence": evidence_id,
            "runtime_phase_gate": phase_gate,
            "runtime_dev_target_commit": target_commit,
        }
        if run.get("mode") == "staged":
            self._entity_transition(
                "phase",
                phase_entity_id,
                "AWAIT_ACCEPTANCE",
                gate_ids=(phase_gate,),
            )
            return self._transition(
                run,
                "AWAIT_PHASE_ACCEPTANCE",
                gate_ids=(phase_gate,),
                state_patch=patch,
            )
        if authorization is None:
            return self._wait(run, "trusted_integrate_dev_grant")
        authorization_id = self._authorization_id(authorization)
        operation_id = self._id("OP", 400 + phase_index)
        review_scope = f"work-to-dev-p{phase_index:03d}"
        reviewed = self._drive_merge_review(
            run,
            review_scope=review_scope,
            expected_route="work_to_dev",
            protected_operation_id=operation_id,
            source_ref=f"refs/heads/{branch}",
            target_branch=self.git.integration_branch,
            purpose=f"run-{self.identity}-phase-integration",
            sharing_status="local",
            single_logical_change=len(phase_tasks) == 1,
            disposable=True,
            audit_boundary_required=False,
            rollback_boundary_required=False,
            future_gate_id=self._gate_id(
                "DEV_INTEGRATION_GATE", offset=phase_index
            ),
            authorization_id=authorization_id,
            rollback_ref=f"refs/nm-v6/rollback/{self.identity}/dev",
        )
        if reviewed is None:
            return True
        proposal, proposal_record, review_evidence = reviewed
        if (
            proposal.source_commit != candidate
            or proposal.target_commit != target_commit
        ):
            raise RecoveryError("reviewed dev proposal differs from Phase bindings")
        dev_gate = self._gate(
            "DEV_INTEGRATION_GATE",
            (*phase_gate_evidence, review_evidence),
            offset=phase_index,
            authorization_id=authorization_id,
            bindings={
                "candidate_commit": candidate,
                "target_commit": target_commit,
            },
        )
        patch["runtime_dev_gate"] = dev_gate
        patch["runtime_integrate_authorization"] = authorization_id
        patch["runtime_dev_operation"] = operation_id
        patch["runtime_dev_review_evidence"] = review_evidence
        patch["runtime_dev_reviewed_proposal_digest"] = proposal_record[
            "reviewed_proposal_digest"
        ]
        self._entity_transition(
            "phase",
            phase_entity_id,
            "ACCEPT",
            gate_ids=(phase_gate,),
        )
        return self._transition(
            run,
            "START_DEV_INTEGRATION",
            payload={"protected_ref": self.git.integration_branch},
            state_patch=patch,
            gate_ids=(phase_gate, dev_gate),
            authorization_id=authorization_id,
        )

    def _await_phase_acceptance(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        authorization = self._authorization(
            "integrate_dev", protected_ref=self.git.integration_branch
        )
        phase_authorization = self._authorization("phase_accept")
        if authorization is None or phase_authorization is None:
            return self._wait(run, "trusted_phase_integration_approval")
        authorization_id = self._authorization_id(authorization)
        phase_index = next(
            index
            for index, item in enumerate(self._phases(), start=1)
            if item["id"] == payload.get("runtime_active_phase")
        )
        evidence_id = str(payload["runtime_phase_evidence"])
        phase_id = str(payload["runtime_active_phase"])
        task_evidence_map = payload.get("runtime_task_evidence", {})
        if not isinstance(task_evidence_map, Mapping):
            raise RecoveryError("Phase lacks its canonical Task evidence map")
        phase_task_evidence = tuple(
            str(task_evidence_map.get(str(task["id"]), ""))
            for task in self._tasks()
            if task.get("phase_id") == phase_id
        )
        if any(not evidence for evidence in phase_task_evidence):
            raise RecoveryError("Phase is missing Task evidence")
        for task_evidence_id in phase_task_evidence:
            receipt = self.store.get_evidence(task_evidence_id)
            if not isinstance(receipt, Mapping):
                raise RecoveryError("Phase Task evidence receipt is missing")
            self.evidence_store.validate(receipt)
        operation_id = self._id("OP", 400 + phase_index)
        branch = str(payload.get("runtime_candidate_branch", ""))
        candidate = str(payload.get("runtime_candidate_commit", ""))
        target_commit = str(payload.get("runtime_dev_target_commit", ""))
        review_scope = f"work-to-dev-p{phase_index:03d}"
        reviewed = self._drive_merge_review(
            run,
            review_scope=review_scope,
            expected_route="work_to_dev",
            protected_operation_id=operation_id,
            source_ref=f"refs/heads/{branch}",
            target_branch=self.git.integration_branch,
            purpose=f"run-{self.identity}-phase-integration",
            sharing_status="local",
            single_logical_change=sum(
                1
                for task in self._tasks()
                if task.get("phase_id") == phase_id
            )
            == 1,
            disposable=True,
            audit_boundary_required=False,
            rollback_boundary_required=False,
            future_gate_id=self._gate_id(
                "DEV_INTEGRATION_GATE", offset=phase_index
            ),
            authorization_id=authorization_id,
            rollback_ref=f"refs/nm-v6/rollback/{self.identity}/dev",
        )
        if reviewed is None:
            return True
        proposal, proposal_record, review_evidence = reviewed
        if (
            proposal.source_commit != candidate
            or proposal.target_commit != target_commit
        ):
            raise RecoveryError("reviewed dev proposal differs from Phase bindings")
        dev_gate = self._gate(
            "DEV_INTEGRATION_GATE",
            (evidence_id, *phase_task_evidence, review_evidence),
            offset=phase_index,
            authorization_id=authorization_id,
            bindings={
                "candidate_commit": payload["runtime_candidate_commit"],
                "target_commit": payload["runtime_dev_target_commit"],
            },
        )
        self._entity_transition(
            "phase",
            self._entity_id(str(payload["runtime_active_phase"])),
            "ACCEPT",
            gate_ids=(str(payload["runtime_phase_gate"]),),
            authorization_id=self._authorization_id(phase_authorization),
        )
        return self._transition(
            run,
            "START_DEV_INTEGRATION",
            payload={"protected_ref": self.git.integration_branch},
            state_patch={
                "runtime_dev_gate": dev_gate,
                "runtime_integrate_authorization": authorization_id,
                "runtime_dev_operation": operation_id,
                "runtime_dev_review_evidence": review_evidence,
                "runtime_dev_reviewed_proposal_digest": proposal_record[
                    "reviewed_proposal_digest"
                ],
            },
            gate_ids=(str(payload["runtime_phase_gate"]), dev_gate),
            authorization_id=authorization_id,
        )

    def _integrate_dev(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        candidate = str(payload.get("runtime_candidate_commit", ""))
        branch = str(payload.get("runtime_candidate_branch", ""))
        target_commit = str(payload.get("runtime_dev_target_commit", ""))
        gate_id = str(payload.get("runtime_dev_gate", ""))
        authorization_id = str(
            payload.get("runtime_integrate_authorization", "")
        )
        if not all((candidate, branch, target_commit, gate_id, authorization_id)):
            raise ContractError("dev integration lacks persisted proposal bindings")
        phase_index = next(
            index
            for index, item in enumerate(self._phases(), start=1)
            if item["id"] == payload.get("runtime_active_phase")
        )
        operation_id = self._id("OP", 400 + phase_index)
        review_scope = f"work-to-dev-p{phase_index:03d}"
        policy = self._merge_review_policy(
            review_scope=review_scope,
            purpose=f"run-{self.identity}-phase-integration",
            sharing_status="local",
            single_logical_change=sum(
                1
                for task in self._tasks()
                if task.get("phase_id") == payload.get("runtime_active_phase")
            )
            == 1,
            disposable=True,
            audit_boundary_required=False,
            rollback_boundary_required=False,
            future_gate_id=gate_id,
            authorization_id=authorization_id,
            rollback_ref=f"refs/nm-v6/rollback/{self.identity}/dev",
        )
        raw_operation = self.store.get_operation(operation_id)
        try:
            proposal, proposal_record, review_evidence = (
                self._load_reviewed_merge_proposal(
                    review_scope=review_scope,
                    route="work_to_dev",
                    protected_operation_id=operation_id,
                    policy=policy,
                    require_current_git=not isinstance(raw_operation, Mapping),
                )
            )
        except NmV6Error as exc:
            return self._merge_review_attention(
                run,
                review_scope=review_scope,
                route="work_to_dev",
                protected_operation_id=operation_id,
                source_ref=f"refs/heads/{branch}",
                target_branch=self.git.integration_branch,
                attempt_id=f"ATTEMPT-runtime-{self.identity}-{review_scope}-001",
                error=exc,
            )
        if (
            proposal.source_commit != candidate
            or proposal.target_commit != target_commit
            or payload.get("runtime_dev_review_evidence") != review_evidence
            or payload.get("runtime_dev_reviewed_proposal_digest")
            != proposal_record["reviewed_proposal_digest"]
        ):
            raise RecoveryError("persisted dev review bindings drifted")
        if isinstance(raw_operation, Mapping):
            operation_scope = raw_operation.get("scope", {})
            if (
                not isinstance(operation_scope, Mapping)
                or operation_scope.get("reviewed_proposal_digest")
                != proposal_record["reviewed_proposal_digest"]
                or operation_scope.get("merge_proposal")
                != proposal_record["merge_proposal"]
                or operation_scope.get("merge_proposal_digest")
                != sha256_bytes(
                    canonical_json(proposal_record["merge_proposal"])
                )
            ):
                raise RecoveryError("dev Operation reviewed proposal binding drifted")
        operation = self._reconcile_operation(operation_id)
        if isinstance(operation, Mapping) and operation.get("status") == "completed":
            result = operation.get("result", {})
            result_commit = str(result.get("target_after", ""))
            result_tree = str(result.get("result_tree", ""))
            remote_after = self.git.remote_head(self.git.integration_branch)
            local_after = self.git.resolve_commit(
                f"refs/heads/{self.git.integration_branch}"
            )
            if (
                not result_commit
                or local_after != result_commit
                or remote_after != result_commit
                or self.git.tree_of(result_commit) != result_tree
                or result_tree != proposal.expected_result_tree
            ):
                raise RecoveryError(
                    "completed dev integration differs from observed protected refs"
                )
            self._record_domain_once(
                "PROTECTED_REF_PUSHED",
                {
                    "operation_id": operation_id,
                    "branch": self.git.integration_branch,
                    "before": proposal.target_commit,
                    "after": result_commit,
                    "observed_after": remote_after,
                },
                idempotency_key=(
                    f"configured-runtime:protected-push:{operation_id}"
                ),
            )
            return self._transition(
                run,
                "DEV_INTEGRATION_APPLIED",
                payload={"protected_ref": self.git.integration_branch},
                state_patch={
                    "runtime_dev_operation": operation_id,
                    "runtime_dev_result_commit": result_commit,
                    "runtime_dev_result_tree": result_tree,
                    "runtime_dev_remote_after": remote_after,
                },
                gate_ids=(gate_id,),
                authorization_id=authorization_id,
            )
        if isinstance(operation, Mapping) and operation.get("status") not in {
            "not_started"
        }:
            return self._wait(run, "dev_integration_operation_reconciliation")
        if self.git.remote_head("dev") != target_commit:
            return self._merge_review_attention(
                run,
                review_scope=review_scope,
                route="work_to_dev",
                protected_operation_id=operation_id,
                source_ref=f"refs/heads/{branch}",
                target_branch=self.git.integration_branch,
                attempt_id=f"ATTEMPT-runtime-{self.identity}-{review_scope}-001",
                error=GitPolicyError("remote dev moved after merge review"),
            )
        merge_proposal_document = proposal_record["merge_proposal"]
        merge_proposal_digest = sha256_bytes(
            canonical_json(merge_proposal_document)
        )
        if operation is None:
            self.reducer.start_operation(
                run_id=self.run_id,
                expected_revision=self._revision(),
                operation_id=operation_id,
                action_id="integrate_dev",
                operation_kind="protected_ref",
                idempotency_key=operation_id,
                authorization_id=authorization_id,
                gate_id=gate_id,
                scope={
                    "protected_ref": self.git.integration_branch,
                    "candidate_commit": candidate,
                    "source_commit": candidate,
                    "target_commit": target_commit,
                    "merge_proposal": merge_proposal_document,
                    "merge_proposal_digest": merge_proposal_digest,
                    "reviewed_proposal_digest": proposal_record[
                        "reviewed_proposal_digest"
                    ],
                    "gate_id": gate_id,
                },
            )
        else:
            authorization = self.store.get_authorization(authorization_id)
            self.reducer.restart_operation(
                run_id=self.run_id,
                expected_revision=self._revision(),
                operation_id=operation_id,
                authorization_id=authorization_id,
                grant_revision=int(authorization["grant_revision"]),
                idempotency_key=(
                    f"configured-runtime:restart:{operation_id}:{self._revision()}"
                ),
            )
        receipt = self.git.execute_proposal(proposal)
        push = self.git.push_protected_cas(
            self.git.integration_branch,
            expected_remote=receipt.target_before,
            new_commit=receipt.target_after,
            proposal=proposal,
        )
        self.reducer.record_operation_observation(
            OperationObservation(
                operation_id=operation_id,
                action_id="integrate_dev",
                status="succeeded",
                effect_id=f"git-dev-{operation_id}-{receipt.target_after}",
                result={
                    "target_before": receipt.target_before,
                    "target_after": receipt.target_after,
                    "result_tree": receipt.result_tree,
                    "remote_after": push.observed_after,
                    "reviewed_proposal_digest": proposal_record[
                        "reviewed_proposal_digest"
                    ],
                },
            ),
            run_id=self.run_id,
            expected_revision=self._revision(),
            idempotency_key=f"configured-runtime:observe:{operation_id}",
            actor="nm-v6-configured-runtime",
        )
        self._record_domain_once(
            "PROTECTED_REF_PUSHED",
            {
                "operation_id": operation_id,
                "branch": push.branch,
                "before": push.before,
                "after": push.after,
                "observed_after": push.observed_after,
            },
            idempotency_key=f"configured-runtime:protected-push:{operation_id}",
        )
        return self._transition(
            run,
            "DEV_INTEGRATION_APPLIED",
            payload={"protected_ref": self.git.integration_branch},
            state_patch={
                "runtime_dev_operation": operation_id,
                "runtime_dev_result_commit": receipt.target_after,
                "runtime_dev_result_tree": receipt.result_tree,
                "runtime_dev_remote_after": push.observed_after,
            },
            gate_ids=(gate_id,),
            authorization_id=authorization_id,
        )

    def _verify_dev_integration(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        candidate = str(payload.get("runtime_candidate_commit", ""))
        result_commit = str(payload.get("runtime_dev_result_commit", ""))
        result_tree = str(payload.get("runtime_dev_result_tree", ""))
        remote_after = self.git.remote_head(self.git.integration_branch)
        local_after = self.git.resolve_commit(
            f"refs/heads/{self.git.integration_branch}"
        )
        if not all((candidate, result_commit, result_tree)):
            raise ContractError("dev result verification lacks persisted bindings")
        phase_index = next(
            index
            for index, item in enumerate(self._phases(), start=1)
            if item["id"] == payload.get("runtime_active_phase")
        )
        result_gate = self._gate_id(
            "DEV_INTEGRATION_RESULT_GATE", offset=phase_index
        )
        persisted_gate = self.store.get_gate(result_gate)
        evidence_id = self._id("EVID", 500 + phase_index)
        if isinstance(persisted_gate, Mapping):
            if (
                persisted_gate.get("gate_type")
                != "DEV_INTEGRATION_RESULT_GATE"
                or persisted_gate.get("result") != "passed"
                or persisted_gate.get("candidate_commit") != result_commit
                or persisted_gate.get("target_commit") != result_commit
                or persisted_gate.get("evidence_ids") != [evidence_id]
                or local_after != result_commit
                or remote_after != result_commit
                or self.git.tree_of(result_commit) != result_tree
            ):
                raise RecoveryError("persisted dev result gate binding drifted")
            persisted_evidence = self.store.get_evidence(evidence_id)
            if not isinstance(persisted_evidence, Mapping):
                raise RecoveryError("persisted dev result evidence is missing")
            self.evidence_store.validate(persisted_evidence)
        else:
            manager, workspace, root = self._workspace(
                result_commit, f"dev-result-{phase_index:03d}"
            )
            try:
                executor = ActionExecutor(isolation_backend=manager.isolation_backend)
                post_result = self._execute(
                    executor,
                    workspace,
                    str(self.project["actions"]["full_verify"]),
                )
            finally:
                self._dispose_workspace(manager, workspace, root)
            assertions = {
                "observed_local_ref_matches": local_after == result_commit,
                "observed_remote_ref_matches": remote_after == result_commit,
                "result_tree_matches": self.git.tree_of(result_commit) == result_tree,
                "push_receipt_valid": payload.get("runtime_dev_remote_after")
                == result_commit,
                "post_update_checks_passed": post_result.status == "succeeded",
            }
            evidence_id = self._evidence(
                500 + phase_index,
                f"dev-integration-result-{phase_index}",
                {
                    "local_after": local_after,
                    "remote_after": remote_after,
                    "result_commit": result_commit,
                    "result_tree": result_tree,
                    "post_update": post_result.as_dict(),
                },
                assertions=assertions,
                source_commit=candidate,
                candidate_commit=result_commit,
                operation_id=str(payload.get("runtime_dev_operation")),
                subject_ids=(str(payload.get("runtime_active_phase")),),
            )
            result_gate = self._gate(
                "DEV_INTEGRATION_RESULT_GATE",
                (evidence_id,),
                offset=phase_index,
                bindings={
                    "candidate_commit": result_commit,
                    "target_commit": result_commit,
                },
                subject_ids=(
                    self.run_id,
                    self._entity_id(str(payload["runtime_active_phase"])),
                ),
            )
        completed_phases = set(payload.get("runtime_completed_phases", []))
        completed_phases.add(str(payload["runtime_active_phase"]))
        remaining = [
            item for item in self._phases() if item["id"] not in completed_phases
        ]
        branch = str(payload.get("runtime_candidate_branch", ""))
        operation_id = str(payload.get("runtime_dev_operation", ""))
        receipt_id, integration_receipt = self._protected_integration_receipt(
            operation_id
        )
        if (
            integration_receipt.source_commit != candidate
            or integration_receipt.target_after != result_commit
            or integration_receipt.result_tree != result_tree
        ):
            raise RecoveryError("dev cleanup receipt differs from result gate")
        cleanup_scope = f"cleanup-work-to-dev-p{phase_index:03d}"
        cleanup_evidence = self._cleanup_responsibility_evidence(
            review_scope=cleanup_scope,
            branch=branch,
            head=candidate,
            assertions={
                "review_responsibility_closed": True,
                "backup_retention_absent": True,
                "dependent_work_closed": not remaining,
                "release_responsibility_closed": False,
                "rollback_responsibility_closed": False,
                "audit_retention_absent": True,
                "explicit_retention_absent": True,
            },
            observation={
                "stage": "DEV_INTEGRATION_RESULT_GATE",
                "gate_id": result_gate,
                "operation_id": operation_id,
                "branch": branch,
                "branch_head": candidate,
                "integration_target": result_commit,
                "remaining_phase_ids": [str(item["id"]) for item in remaining],
            },
        )
        cleanup_review = self._drive_cleanup_review(
            run,
            review_scope=cleanup_scope,
            branch=branch,
            target_branch=self.git.integration_branch,
            receipt_id=receipt_id,
            integration_receipt=integration_receipt,
        )
        if cleanup_review is None:
            return True
        cleanup_decision, cleanup_provenance = cleanup_review
        if cleanup_decision.result != "retain":
            return self._transition(
                run,
                "REQUIRE_ATTENTION",
                payload={
                    "actors_fenced": True,
                    "external_operations_reconciled": True,
                    "reason": "work branch cleanup was not retained before delivery",
                    "required_decision": "inspect_cleanup_responsibility_evidence",
                },
                state_patch={
                    "runtime_attention_reason": (
                        "work branch cleanup was not retained before delivery"
                    ),
                    "runtime_attention_cleanup_scope": cleanup_scope,
                },
            )
        branch_ref = f"refs/heads/{branch}"
        branch_head = self.git.resolve_commit(branch_ref)
        if remaining and branch_head != result_commit:
            if branch_head != candidate:
                raise RecoveryError(
                    "candidate branch differs from reviewed dev integration lineage"
                )
            run_command(
                ("git", "update-ref", branch_ref, result_commit, candidate),
                cwd=self.target,
            )
        if remaining:
            self._record_domain_once(
                "CANDIDATE_BRANCH_ADVANCED",
                {
                    "branch": branch,
                    "run_id": self.run_id,
                    "source_commit": candidate,
                    "candidate_commit": result_commit,
                    "gate_id": result_gate,
                    "reason": "reviewed_dev_integration_result",
                },
                idempotency_key=(
                    f"configured-runtime:candidate-after-dev:{payload['runtime_dev_operation']}"
                ),
            )
        elif branch_head != candidate:
            raise RecoveryError(
                "final candidate branch no longer equals its integration source"
            )
        phase_gate = str(payload.get("runtime_phase_gate", ""))
        for task in self._tasks():
            if task.get("phase_id") != payload.get("runtime_active_phase"):
                continue
            task_entity_id = self._entity_id(str(task["id"]))
            entity = self.store.get_entity_state("task", task_entity_id)
            if isinstance(entity, Mapping) and entity["state"] == "VERIFIED":
                self._entity_transition(
                    "task",
                    task_entity_id,
                    "MARK_INTEGRATED",
                    gate_ids=(phase_gate,),
                )
        phase_entity_id = self._entity_id(
            str(payload["runtime_active_phase"])
        )
        phase_entity = self.store.get_entity_state("phase", phase_entity_id)
        if isinstance(phase_entity, Mapping) and phase_entity["state"] == "ACCEPTED":
            self._entity_transition(
                "phase",
                phase_entity_id,
                "MARK_INTEGRATED",
                gate_ids=(result_gate,),
            )
        patch = {
            "runtime_completed_phases": sorted(completed_phases),
            "runtime_last_dev_result_gate": result_gate,
            "runtime_verified_dev_commit": result_commit,
            "runtime_verified_dev_tree": result_tree,
            "runtime_last_cleanup_scope": cleanup_scope,
            "runtime_last_cleanup_evidence": cleanup_evidence,
            "runtime_last_cleanup_provenance_digest": cleanup_provenance[
                "provenance_digest"
            ],
        }
        if remaining:
            return self._transition(
                run,
                "CONTINUE_IMPLEMENTATION",
                payload={"more_phases": True},
                state_patch=patch,
                gate_ids=(result_gate,),
            )
        return self._transition(
            run,
            "ALL_PHASES_INTEGRATED",
            payload={"all_phases_done": True},
            state_patch=patch,
            gate_ids=(result_gate,),
        )

    # -- Cleanup reviewer -------------------------------------------------

    @staticmethod
    def _cleanup_request_at_revision(
        request: Mapping[str, Any], input_revision: int
    ) -> dict[str, Any]:
        """Re-seal revision-only cleanup drift after a strict review window."""

        current = validate_cleanup_review_request(request)
        facts = dict(current["cleanup_facts"])
        facts.pop("facts_digest", None)
        facts["input_revision"] = input_revision
        rebased_facts = seal_cleanup_facts(facts)
        rebased = dict(current)
        rebased.pop("request_digest", None)
        rebased["input_revision"] = input_revision
        rebased["cleanup_facts"] = rebased_facts
        return seal_cleanup_review_request(rebased)

    def _audit_cleanup_review_window(
        self,
        *,
        review_request: Mapping[str, Any],
        attempt_id: str,
        review_scope: str,
        end_revision: int,
    ) -> tuple[dict[str, Any], ...]:
        """Allow only the exact cleanup reviewer lifecycle after its snapshot."""

        request = validate_cleanup_review_request(review_request)
        start_revision = int(request["input_revision"])
        if end_revision <= start_revision:
            raise RecoveryError("cleanup review window did not record a reviewer lifecycle")
        events = tuple(
            event
            for event in self.store.list_events(run_id=self.run_id)
            if start_revision < int(event["run_revision"]) <= end_revision
        )
        revisions = [int(event["run_revision"]) for event in events]
        if revisions != list(range(start_revision + 1, end_revision + 1)):
            raise RecoveryError("cleanup review window has a revision discontinuity")
        expected_types = (
            "ENTITY_CREATED",
            "STATE_TRANSITION",
            "ADAPTER_REQUESTED",
            "ADAPTER_SESSION_RECORDED",
            "STATE_TRANSITION",
            "ADAPTER_RESULT_RECORDED",
            "STATE_TRANSITION",
            "STATE_TRANSITION",
        )
        if tuple(str(event["event_type"]) for event in events) != expected_types:
            raise RecoveryError(
                "cleanup review window contains an unrelated or reordered event"
            )
        create_request = events[0].get("payload", {}).get("request", {})
        create_payload = create_request.get("payload", {})
        if (
            create_request.get("machine") != "attempt"
            or create_request.get("entity_id") != attempt_id
            or create_request.get("initial_state") != "CREATED"
            or create_payload.get("role") != "cleanup_reviewer"
            or create_payload.get("review_scope") != review_scope
            or create_payload.get("review_request") != request
        ):
            raise RecoveryError("cleanup reviewer Attempt creation is not exact")
        expected_transitions = ("DISPATCH", "START", "COLLECT", "SUCCEED")
        for event, expected_transition in zip(
            (events[1], events[4], events[6], events[7]),
            expected_transitions,
            strict=True,
        ):
            transition = event.get("payload", {}).get("request", {})
            proposal = transition.get("proposal", {})
            if (
                transition.get("machine") != "attempt"
                or transition.get("entity_id") != attempt_id
                or proposal.get("event") != expected_transition
            ):
                raise RecoveryError("cleanup reviewer Attempt transition is not exact")
        for event in (events[2], events[3], events[5]):
            record = event.get("payload", {}).get("record", {})
            if (
                record.get("role") != "cleanup_reviewer"
                or record.get("review_scope") != review_scope
                or record.get("attempt_id") != attempt_id
                or record.get("review_request_digest")
                != request["request_digest"]
            ):
                raise RecoveryError("cleanup reviewer adapter event is not exact")
        return events

    def _revalidate_cleanup_review_window(
        self,
        *,
        review_request: Mapping[str, Any],
        observation: Mapping[str, Any],
        attempt_id: str,
        review_scope: str,
        review_end_revision: int,
        review_id: str,
        branch: str,
        target_branch: str,
        receipt_id: str,
        integration_receipt: MergeReceipt,
        caller_facts: CleanupFacts | None,
    ) -> CleanupFacts:
        """Recompute facts and reject every non-revision change since dispatch."""

        request = validate_cleanup_review_request(review_request)
        self._audit_cleanup_review_window(
            review_request=request,
            attempt_id=attempt_id,
            review_scope=review_scope,
            end_revision=review_end_revision,
        )
        current_request, core_facts = self.git._build_cleanup_review_material(
            review_id=review_id,
            run_id=self.run_id,
            spec_hash=str(self._current()["spec_hash"]),
            config_hash=str(self._current()["config_hash"]),
            branch=branch,
            target_branch=target_branch,
            receipt_id=receipt_id,
            integration_receipt=integration_receipt,
            caller_facts=caller_facts,
        )
        normalized = self._cleanup_request_at_revision(
            current_request, int(request["input_revision"])
        )
        if canonical_json(normalized) != canonical_json(request):
            raise GitPolicyError(
                "cleanup review facts changed outside the reviewer-only window"
            )
        validate_cleanup_review_observations(request, [observation])
        return core_facts

    def _cleanup_core_decision_at_revision(
        self,
        *,
        review_end_revision: int,
        branch: str,
        head: str,
    ) -> CleanupDecision | None:
        expected_revision = review_end_revision + 1
        matches: list[Mapping[str, Any]] = []
        for event in self.store.list_events(run_id=self.run_id):
            if (
                event.get("event_type") != "BRANCH_CLEANUP_DECIDED"
                or int(event.get("run_revision", -1)) != expected_revision
            ):
                continue
            record = event.get("payload", {}).get("record", {})
            if record.get("record_kind") != "decision":
                continue
            decision = record.get("decision", {})
            facts = record.get("facts", {})
            if (
                decision.get("branch") == branch
                and decision.get("head") == head
                and facts.get("canonical_snapshot", {}).get("input_revision")
                == review_end_revision
            ):
                matches.append(event)
        if not matches:
            return None
        if len(matches) != 1:
            raise RecoveryError("cleanup core decision boundary is ambiguous")
        event = matches[0]
        record = event["payload"]["record"]
        decision = record["decision"]
        facts = record["facts"]
        return CleanupDecision(
            result=str(decision["result"]),
            branch=str(decision["branch"]),
            head=str(decision["head"]),
            reasons=tuple(map(str, decision.get("reasons", []))),
            decided_at=str(decision["decided_at"]),
            facts_digest=str(record["facts_digest"]),
            run_id=self.run_id,
            input_revision=int(facts["canonical_snapshot"]["input_revision"]),
            decision_event_id=str(event["event_id"]),
        )

    def _cleanup_responsibility_evidence(
        self,
        *,
        review_scope: str,
        branch: str,
        head: str,
        assertions: Mapping[str, bool],
        observation: Mapping[str, Any],
        terminal_resource_proof_complete: bool = False,
    ) -> str:
        required = {
            "review_responsibility_closed",
            "backup_retention_absent",
            "dependent_work_closed",
            "release_responsibility_closed",
            "rollback_responsibility_closed",
            "audit_retention_absent",
            "explicit_retention_absent",
        }
        if set(assertions) != required:
            raise ContractError("cleanup responsibility assertions are incomplete")
        evidence_id = self._id("EVID", 496, scope=review_scope)
        run = self._current()
        all_assertions = {
            **dict(assertions),
            "terminal_resource_proof_complete": terminal_resource_proof_complete,
        }
        stdout = canonical_json(dict(observation))
        expected_stdout = sha256_bytes(stdout)
        expected_stderr = sha256_bytes(b"")
        existing = self.store.get_evidence(evidence_id)
        if isinstance(existing, Mapping):
            self.evidence_store.validate(existing)
            expected = {
                "evidence_type": "branch_cleanup_responsibility",
                "producer": "nm-v6-core/cleanup-evaluator",
                "run_id": self.run_id,
                "subject_ids": [f"branch:{branch}", f"branch-head:{head}"],
                "assertions": all_assertions,
                "spec_hash": run["spec_hash"],
                "config_hash": run["config_hash"],
                "source_commit": head,
                "candidate_commit": head,
                "command_action_id": "branch_cleanup_responsibility",
                "result": "passed",
                "exit_code": 0,
                "stdout_digest": expected_stdout,
                "stderr_digest": expected_stderr,
            }
            if any(existing.get(key) != value for key, value in expected.items()):
                raise RecoveryError("cleanup responsibility evidence drifted")
            return evidence_id
        timestamp = utc_now()
        receipt = self.evidence_store.persist(
            {
                "evidence_id": evidence_id,
                "evidence_type": "branch_cleanup_responsibility",
                "producer": "nm-v6-core/cleanup-evaluator",
                "run_id": self.run_id,
                "subject_ids": [f"branch:{branch}", f"branch-head:{head}"],
                "assertions": all_assertions,
                "spec_hash": run["spec_hash"],
                "config_hash": run["config_hash"],
                "source_commit": head,
                "candidate_commit": head,
                "release_source_kind": None,
                "release_source_commit": None,
                "release_source_tree": None,
                "hotfix_reconciliation_gate_id": None,
                "artifact_digest": None,
                "environment_id": None,
                "environment_fingerprint": None,
                "operation_id": None,
                "attempt_id": None,
                "command_action_id": "branch_cleanup_responsibility",
                "argv_digest": sha256_bytes(
                    f"cleanup-responsibility:{review_scope}".encode("utf-8")
                ),
                "working_directory": ".",
                "started_at": timestamp,
                "finished_at": timestamp,
                "exit_code": 0,
                "result": "passed",
                "tool_versions": dict(self.version_baseline),
                "producer_version": "nm-v6/configured-runtime-cleanup-v1",
                "evaluator_version": self.version_baseline["evaluator"],
            },
            stdout,
            b"",
        )
        self.reducer.record_evidence(
            run_id=self.run_id,
            expected_revision=self._revision(),
            receipt=receipt,
            idempotency_key=f"configured-runtime:evidence:{evidence_id}",
            actor="nm-v6-configured-runtime",
        )
        return evidence_id

    def _protected_integration_receipt(
        self, operation_id: str
    ) -> tuple[str, MergeReceipt]:
        operation = self.store.get_operation(operation_id)
        if not isinstance(operation, Mapping) or operation.get("status") != "completed":
            raise RecoveryError("cleanup integration Operation is not completed")
        proposal_events = [
            event
            for event in self.store.list_events(run_id=self.run_id)
            if event.get("event_type") == "MERGE_PROPOSED"
            and event.get("payload", {}).get("record", {}).get("operation_id")
            == operation_id
        ]
        push_events = [
            event
            for event in self.store.list_events(run_id=self.run_id)
            if event.get("event_type") == "PROTECTED_REF_PUSHED"
            and event.get("payload", {}).get("record", {}).get("operation_id")
            == operation_id
        ]
        if len(proposal_events) != 1 or len(push_events) != 1:
            raise RecoveryError(
                "cleanup integration lacks exact proposal/push provenance"
            )
        proposal_record = proposal_events[0]["payload"]["record"]
        proposal = proposal_record.get("merge_proposal", {})
        push = push_events[0]["payload"]["record"]
        result = operation.get("result", {})
        target_after = str(push.get("after", ""))
        result_tree = self.git.tree_of(target_after)
        if (
            push.get("observed_after") != target_after
            or result.get("target_after") != target_after
            or result.get("result_tree") != result_tree
            or proposal.get("source_commit") is None
            or proposal.get("strategy") is None
        ):
            raise RecoveryError("cleanup integration receipt provenance drifted")
        receipt_id = f"MERGE-RECEIPT-{operation_id}"
        return receipt_id, MergeReceipt(
            strategy=str(proposal["strategy"]),
            source_commit=str(proposal["source_commit"]),
            target_before=str(push["before"]),
            target_after=target_after,
            result_tree=result_tree,
            rollback_ref=str(proposal["rollback_ref"]),
            authorization_id=str(proposal["authorization_id"]),
            executed_at=str(push_events[0]["created_at"]),
        )

    @staticmethod
    def _runtime_payload_values(
        value: Any, names: frozenset[str]
    ) -> tuple[str, ...]:
        found: set[str] = set()

        def visit(current: Any) -> None:
            if isinstance(current, Mapping):
                for key, child in current.items():
                    if key in names and isinstance(child, str) and child:
                        found.add(child)
                    else:
                        visit(child)
            elif isinstance(current, (list, tuple)):
                for child in current:
                    visit(child)

        visit(value)
        return tuple(sorted(found))

    def _terminal_resource_snapshot(self) -> dict[str, Any]:
        active_attempt_states = {"CREATED", "DISPATCHED", "RUNNING", "COLLECTING"}
        terminal_operation_states = {
            "completed",
            "failed",
            "not_started",
            "cancelled",
        }
        session_names = frozenset(
            {"session_id", "provider_session_id", "adapter_session_id"}
        )
        workspace_names = frozenset(
            {"workspace", "workspace_path", "candidate_workspace", "disposable_workspace"}
        )
        live_leases: list[str] = []
        active_attempts: list[str] = []
        live_sessions: set[str] = set()
        live_workspaces: set[str] = set()
        nonterminal_operations: list[str] = []
        operation_documents: list[dict[str, Any]] = []
        remote_delete_authorizations: list[str] = []
        remote_delete_requests: list[str] = []
        remote_delete_consumptions: list[str] = []
        with self.store._lock:
            connection = self.store._connection
            for lease in connection.execute(
                "SELECT resource_id, expires_at FROM leases WHERE run_id = ? "
                "ORDER BY resource_id",
                (self.run_id,),
            ).fetchall():
                normalized = str(lease["expires_at"]).replace("Z", "+00:00")
                expiry = datetime.fromisoformat(normalized)
                if expiry.tzinfo is None:
                    raise RecoveryError("terminal lease expiry lacks a timezone")
                if expiry.astimezone(UTC) > datetime.now(UTC):
                    live_leases.append(str(lease["resource_id"]))
            for entity in connection.execute(
                "SELECT machine, entity_id, state, payload_json FROM entity_states "
                "WHERE run_id = ? ORDER BY machine, entity_id",
                (self.run_id,),
            ).fetchall():
                payload = json.loads(entity["payload_json"])
                if (
                    entity["machine"] == "attempt"
                    and entity["state"] in active_attempt_states
                ):
                    active_attempts.append(str(entity["entity_id"]))
                    live_sessions.update(
                        self._runtime_payload_values(payload, session_names)
                    )
                for raw_path in self._runtime_payload_values(
                    payload, workspace_names
                ):
                    path = Path(raw_path).expanduser()
                    if not path.is_absolute():
                        path = self.target / path
                    if path.exists() or path.is_symlink():
                        live_workspaces.add(str(path.resolve()))
            for operation in connection.execute(
                "SELECT operation_id, status, scope_json, result_json "
                "FROM external_operations WHERE run_id = ? ORDER BY operation_id",
                (self.run_id,),
            ).fetchall():
                scope = json.loads(operation["scope_json"])
                result = json.loads(operation["result_json"])
                document = {
                    "operation_id": str(operation["operation_id"]),
                    "status": str(operation["status"]),
                    "scope": scope,
                    "result": result,
                }
                operation_documents.append(document)
                if operation["status"] not in terminal_operation_states:
                    nonterminal_operations.append(str(operation["operation_id"]))
                    live_sessions.update(
                        self._runtime_payload_values(scope, session_names)
                    )
                    live_sessions.update(
                        self._runtime_payload_values(result, session_names)
                    )
                for raw_path in self._runtime_payload_values(
                    (scope, result), workspace_names
                ):
                    path = Path(raw_path).expanduser()
                    if not path.is_absolute():
                        path = self.target / path
                    if path.exists() or path.is_symlink():
                        live_workspaces.add(str(path.resolve()))
            for request in connection.execute(
                "SELECT request_id, scope_json FROM authorization_requests "
                "WHERE run_id = ? ORDER BY request_id",
                (self.run_id,),
            ).fetchall():
                scope = json.loads(request["scope_json"])
                if scope.get("nonprotected_ref", {}).get("action") == "delete_remote":
                    remote_delete_requests.append(str(request["request_id"]))
            for authorization in connection.execute(
                "SELECT authorization_id, record_json FROM authorization_records "
                "WHERE run_id = ? ORDER BY authorization_id",
                (self.run_id,),
            ).fetchall():
                record = json.loads(authorization["record_json"])
                if record.get("nonprotected_ref", {}).get("action") != "delete_remote":
                    continue
                authorization_id = str(authorization["authorization_id"])
                remote_delete_authorizations.append(authorization_id)
                uses = connection.execute(
                    "SELECT operation_id FROM authorization_uses "
                    "WHERE authorization_id = ? ORDER BY operation_id",
                    (authorization_id,),
                ).fetchall()
                remote_delete_consumptions.extend(
                    str(item["operation_id"]) for item in uses
                )
        events = self.store.list_events(run_id=self.run_id)
        proposal_by_operation = {
            str(event.get("payload", {}).get("record", {}).get("operation_id")): event[
                "payload"
            ]["record"]
            for event in events
            if event.get("event_type") == "MERGE_PROPOSED"
            and isinstance(event.get("payload", {}).get("record"), Mapping)
        }
        cleanup_scopes = {
            str(event.get("payload", {}).get("record", {}).get("review_scope"))
            for event in events
            if event.get("event_type") == "BRANCH_CLEANUP_DECIDED"
            and event.get("payload", {}).get("record", {}).get("record_kind")
            == "reviewer_provenance"
        }
        route_scopes = {
            "work_to_dev": lambda scope: "cleanup-" + str(scope),
            "hotfix_to_stable": lambda _scope: "cleanup-hotfix-to-stable",
            "hotfix_to_dev": lambda _scope: "cleanup-hotfix-to-dev",
            "dev_to_stable": lambda _scope: "cleanup-dev-to-stable",
        }
        required_cleanup_scopes: set[str] = set()
        protected_integrations: list[str] = []
        for event in events:
            if event.get("event_type") != "PROTECTED_REF_PUSHED":
                continue
            operation_id = str(
                event.get("payload", {}).get("record", {}).get("operation_id", "")
            )
            proposal = proposal_by_operation.get(operation_id)
            if not isinstance(proposal, Mapping):
                raise RecoveryError(
                    "terminal protected integration lacks merge provenance"
                )
            route = str(proposal.get("route", ""))
            mapper = route_scopes.get(route)
            if mapper is None:
                raise RecoveryError("terminal protected integration route is unknown")
            protected_integrations.append(operation_id)
            required_cleanup_scopes.add(mapper(proposal.get("review_scope")))
        missing_cleanup = sorted(required_cleanup_scopes - cleanup_scopes)
        remote_cleanup_operations = [
            item["operation_id"]
            for item in operation_documents
            if (
                "delete" in str(item["scope"]).lower()
                and "remote" in str(item["scope"]).lower()
            )
        ]
        return {
            "live_lease_ids": sorted(live_leases),
            "active_attempt_ids": sorted(active_attempts),
            "live_session_ids": sorted(live_sessions),
            "live_workspace_paths": sorted(live_workspaces),
            "nonterminal_operation_ids": sorted(nonterminal_operations),
            "protected_integration_operation_ids": sorted(protected_integrations),
            "required_cleanup_scopes": sorted(required_cleanup_scopes),
            "observed_cleanup_scopes": sorted(cleanup_scopes),
            "missing_cleanup_scopes": missing_cleanup,
            "remote_cleanup_operation_ids": sorted(remote_cleanup_operations),
            "remote_delete_authorization_request_ids": sorted(
                remote_delete_requests
            ),
            "remote_delete_authorization_ids": sorted(
                remote_delete_authorizations
            ),
            "remote_delete_authorization_consumptions": sorted(
                remote_delete_consumptions
            ),
        }

    def _cleanup_execution_record(
        self, *, branch: str, head: str
    ) -> dict[str, Any] | None:
        matches: list[dict[str, Any]] = []
        for event in self.store.list_events(run_id=self.run_id):
            record = event.get("payload", {}).get("record", {})
            receipt = record.get("receipt", {}) if isinstance(record, Mapping) else {}
            if (
                event.get("event_type") == "BRANCH_CLEANUP_DECIDED"
                and record.get("record_kind") == "execution_receipt"
                and receipt.get("branch") == branch
                and receipt.get("deleted_head") == head
            ):
                matches.append({"event_id": event["event_id"], **dict(record)})
        if not matches:
            return None
        if len(matches) != 1:
            raise RecoveryError("local cleanup execution receipt is ambiguous")
        if self.git.try_resolve_commit(f"refs/heads/{branch}") is not None:
            raise RecoveryError("deleted branch reappeared after cleanup receipt")
        return matches[0]

    def _final_branch_cleanup(
        self,
        run: Mapping[str, Any],
        *,
        terminal_stage: str,
        terminal_observation: Mapping[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        payload = self._payload(self._current())
        hotfix = str(run.get("run_kind")) == "hotfix"
        if hotfix:
            branch = str(payload.get("runtime_hotfix_branch", ""))
            head = str(payload.get("runtime_hotfix_candidate_commit", ""))
            operation_id = str(payload.get("runtime_hotfix_dev_operation", ""))
            target_branch = self.git.integration_branch
            cleanup_scope = "cleanup-hotfix-final"
        else:
            branch = str(payload.get("runtime_candidate_branch", ""))
            head = str(payload.get("runtime_candidate_commit", ""))
            operation_id = str(payload.get("runtime_dev_operation", ""))
            target_branch = self.git.integration_branch
            cleanup_scope = "cleanup-work-final"
        if not all((branch, head, operation_id)):
            raise RecoveryError("terminal branch cleanup lacks exact integration bindings")
        receipt_id, integration_receipt = self._protected_integration_receipt(
            operation_id
        )
        if integration_receipt.source_commit != head:
            raise RecoveryError("terminal cleanup source differs from integration receipt")
        pre_snapshot = self._terminal_resource_snapshot()
        pre_snapshot["observed_cleanup_scopes"] = [
            scope
            for scope in pre_snapshot["observed_cleanup_scopes"]
            if scope != cleanup_scope
        ]
        pre_closed = not any(
            pre_snapshot[field]
            for field in (
                "live_lease_ids",
                "active_attempt_ids",
                "live_session_ids",
                "live_workspace_paths",
                "nonterminal_operation_ids",
                "missing_cleanup_scopes",
                "remote_cleanup_operation_ids",
                "remote_delete_authorization_consumptions",
            )
        )
        if not pre_closed:
            raise RecoveryError("terminal resources remain live before branch cleanup")
        execution = None if hotfix else self._cleanup_execution_record(
            branch=branch, head=head
        )
        if execution is None:
            responsibility_evidence = self._cleanup_responsibility_evidence(
                review_scope=cleanup_scope,
                branch=branch,
                head=head,
                assertions={
                    "review_responsibility_closed": True,
                    "backup_retention_absent": True,
                    "dependent_work_closed": True,
                    "release_responsibility_closed": True,
                    "rollback_responsibility_closed": True,
                    "audit_retention_absent": True,
                    "explicit_retention_absent": not hotfix,
                },
                observation={
                    "terminal_stage": terminal_stage,
                    "terminal_observation": dict(terminal_observation),
                    "pre_cleanup_resources": pre_snapshot,
                    "branch": branch,
                    "branch_head": head,
                    "integration_operation_id": operation_id,
                },
                terminal_resource_proof_complete=True,
            )
            reviewed = self._drive_cleanup_review(
                run,
                review_scope=cleanup_scope,
                branch=branch,
                target_branch=target_branch,
                receipt_id=receipt_id,
                integration_receipt=integration_receipt,
            )
            if reviewed is None:
                raise RecoveryError("terminal cleanup reviewer required attention")
            decision, provenance = reviewed
            expected = "retain" if hotfix else "delete_local"
            if decision.result != expected:
                raise RecoveryError(
                    f"terminal cleanup returned {decision.result}, expected {expected}"
                )
            if not hotfix:
                _, current_facts = self.git._build_cleanup_review_material(
                    review_id=(
                        f"CLEANUP-REVIEW-{self.identity}-{cleanup_scope}-999"
                    ),
                    run_id=self.run_id,
                    spec_hash=str(self._current()["spec_hash"]),
                    config_hash=str(self._current()["config_hash"]),
                    branch=branch,
                    target_branch=target_branch,
                    receipt_id=receipt_id,
                    integration_receipt=integration_receipt,
                    caller_facts=None,
                )
                checkpoint("runtime.before_cleanup_local_delete")
                receipt = self.git.delete_local_branch(
                    decision, current_facts=current_facts
                )
                checkpoint("runtime.after_cleanup_local_delete")
                execution = self._cleanup_execution_record(
                    branch=receipt.branch, head=receipt.deleted_head
                )
                if not isinstance(execution, Mapping):
                    raise RecoveryError(
                        "local cleanup execution receipt was not persisted"
                    )
        else:
            responsibility_evidence = self._id(
                "EVID", 496, scope=cleanup_scope
            )
            provenance = self._domain_record(
                "BRANCH_CLEANUP_DECIDED",
                idempotency_key=(
                    f"configured-runtime:cleanup-review:{cleanup_scope}"
                ),
            )
            if not isinstance(provenance, Mapping):
                raise RecoveryError("local cleanup execution lacks reviewer provenance")
        post_snapshot = self._terminal_resource_snapshot()
        branch_resolved = (
            self.git.try_resolve_commit(f"refs/heads/{branch}") == head
            if hotfix
            else (
                execution is not None
                and self.git.try_resolve_commit(f"refs/heads/{branch}") is None
            )
        )
        terminal_closed = not any(
            post_snapshot[field]
            for field in (
                "live_lease_ids",
                "active_attempt_ids",
                "live_session_ids",
                "live_workspace_paths",
                "nonterminal_operation_ids",
                "missing_cleanup_scopes",
            )
        )
        no_remote_effect = not any(
            post_snapshot[field]
            for field in (
                "remote_cleanup_operation_ids",
                "remote_delete_authorization_consumptions",
            )
        )
        terminal_evidence = self._evidence(
            799,
            f"terminal-resources-{terminal_stage}",
            {
                "terminal_stage": terminal_stage,
                "terminal_observation": dict(terminal_observation),
                "branch": branch,
                "branch_head": head,
                "cleanup_scope": cleanup_scope,
                "responsibility_evidence_id": responsibility_evidence,
                "cleanup_provenance_digest": provenance["provenance_digest"],
                "cleanup_execution": execution,
                "resources": post_snapshot,
            },
            assertions={
                "branch_cleanup_resolved": branch_resolved,
                "terminal_resources_closed": terminal_closed,
                "no_remote_cleanup_effect": no_remote_effect,
            },
            source_commit=head,
            candidate_commit=head,
            artifact_digest=(
                str(payload["runtime_published_artifact"])
                if payload.get("runtime_published_artifact")
                else None
            ),
            environment_id=(
                str(payload["runtime_environment_id"])
                if terminal_stage == "rollback"
                and payload.get("runtime_environment_id")
                else None
            ),
            environment_fingerprint=(
                str(payload["runtime_environment_fingerprint"])
                if terminal_stage == "rollback"
                and payload.get("runtime_environment_fingerprint")
                else None
            ),
            subject_ids=("terminal-resources", f"branch:{branch}"),
            scope=terminal_stage,
        )
        if not (branch_resolved and terminal_closed and no_remote_effect):
            raise RecoveryError("terminal cleanup/resource proof did not close")
        return terminal_evidence, {
            "branch": branch,
            "branch_head": head,
            "cleanup_scope": cleanup_scope,
            "cleanup_result": "retain" if hotfix else "deleted",
            "terminal_evidence_id": terminal_evidence,
            "resources": post_snapshot,
        }

    def _load_cleanup_review_provenance(
        self,
        *,
        review_scope: str,
        review_id: str,
        attempt_id: str,
        adapter_operation_id: str,
        branch: str,
        target_branch: str,
        receipt_id: str,
        integration_receipt: MergeReceipt,
        caller_facts: CleanupFacts | None,
        provider: str,
    ) -> tuple[CleanupDecision, dict[str, Any]] | None:
        provenance = self._domain_record(
            "BRANCH_CLEANUP_DECIDED",
            idempotency_key=f"configured-runtime:cleanup-review:{review_scope}",
        )
        if provenance is None:
            return None
        required = {
            "record_kind",
            "review_scope",
            "branch",
            "target_branch",
            "receipt_id",
            "review_request",
            "cleanup_review_observation",
            "adapter_request",
            "adapter_request_digest",
            "adapter_session",
            "adapter_result",
            "attempt_provenance",
            "core_decision",
            "provenance_digest",
        }
        if set(provenance) != required:
            raise RecoveryError("cleanup reviewer provenance shape drifted")
        unsigned = {
            key: value
            for key, value in provenance.items()
            if key != "provenance_digest"
        }
        if provenance["provenance_digest"] != sha256_bytes(
            canonical_json(unsigned)
        ):
            raise RecoveryError("cleanup reviewer provenance digest drifted")
        if (
            provenance["record_kind"] != "reviewer_provenance"
            or provenance["review_scope"] != review_scope
            or provenance["branch"] != branch
            or provenance["target_branch"] != target_branch
            or provenance["receipt_id"] != receipt_id
        ):
            raise RecoveryError("cleanup reviewer provenance binding drifted")
        request = validate_cleanup_review_request(provenance["review_request"])
        if request["review_id"] != review_id:
            raise RecoveryError("cleanup reviewer request identity drifted")
        adapter_request = validate_adapter_request(provenance["adapter_request"])
        adapter_digest = sha256_bytes(canonical_json(adapter_request))
        if (
            provenance["adapter_request_digest"] != adapter_digest
            or adapter_request["attempt_id"] != attempt_id
            or adapter_request["operation_id"] != adapter_operation_id
            or adapter_request["role"] != "cleanup_reviewer"
            or adapter_request["allowed_capabilities"] != []
        ):
            raise RecoveryError("cleanup reviewer adapter request drifted")
        attempt = self.store.get_entity_state("attempt", attempt_id)
        if not isinstance(attempt, Mapping) or attempt.get("state") != "SUCCEEDED":
            raise RecoveryError("cleanup reviewer Attempt is not durably succeeded")
        binding = attempt.get("payload", {})
        if not isinstance(binding, Mapping):
            raise RecoveryError("cleanup reviewer Attempt provenance is malformed")
        expected_attempt = {
            "attempt_id": attempt_id,
            "state": "SUCCEEDED",
            "entity_revision": int(attempt["revision"]),
            "provider": provider,
            "operation_id": adapter_operation_id,
            "workspace_id": binding.get("workspace_id"),
        }
        if (
            provenance["attempt_provenance"] != expected_attempt
            or binding.get("review_request") != request
            or binding.get("adapter_request") != adapter_request
            or binding.get("review_scope") != review_scope
            or binding.get("branch") != branch
            or binding.get("target_branch") != target_branch
            or binding.get("receipt_id") != receipt_id
        ):
            raise RecoveryError("cleanup reviewer Attempt provenance drifted")
        common_record = {
            "role": "cleanup_reviewer",
            "review_scope": review_scope,
            "provider": provider,
            "attempt_id": attempt_id,
            "operation_id": adapter_operation_id,
            "review_request_digest": request["request_digest"],
        }
        requested = self._domain_record(
            "ADAPTER_REQUESTED",
            idempotency_key=f"configured-runtime:adapter-request:{attempt_id}",
        )
        session = self._domain_record(
            "ADAPTER_SESSION_RECORDED",
            idempotency_key=f"configured-runtime:adapter-session:{attempt_id}",
        )
        result = self._domain_record(
            "ADAPTER_RESULT_RECORDED",
            idempotency_key=f"configured-runtime:adapter-result:{attempt_id}",
        )
        expected_requested = {
            **common_record,
            "request_digest": adapter_digest,
            "request": adapter_request,
        }
        if requested != expected_requested or not isinstance(session, Mapping):
            raise RecoveryError("cleanup reviewer adapter request/session drifted")
        session_id = str(session.get("session_id", ""))
        if session != {**common_record, "session_id": session_id}:
            raise RecoveryError("cleanup reviewer adapter session drifted")
        if not isinstance(result, Mapping) or result != {
            **common_record,
            "session_id": session_id,
            "result": result.get("result"),
        }:
            raise RecoveryError("cleanup reviewer adapter result drifted")
        validated = validate_cleanup_reviewer_adapter_result(
            result["result"],
            adapter_request=adapter_request,
            review_request=request,
            expected_session_id=session_id,
        )
        observation = validated["observations"][0]
        if (
            provenance["adapter_session"] != session
            or provenance["adapter_result"] != result
            or provenance["cleanup_review_observation"] != observation
        ):
            raise RecoveryError("cleanup reviewer result provenance drifted")
        self._dispose_persisted_merge_review_workspace(attempt_id)
        review_end_revision = int(request["input_revision"]) + 8
        self._revalidate_cleanup_review_window(
            review_request=request,
            observation=observation,
            attempt_id=attempt_id,
            review_scope=review_scope,
            review_end_revision=review_end_revision,
            review_id=review_id,
            branch=branch,
            target_branch=target_branch,
            receipt_id=receipt_id,
            integration_receipt=integration_receipt,
            caller_facts=caller_facts,
        )
        decision = self._cleanup_core_decision_at_revision(
            review_end_revision=review_end_revision,
            branch=branch,
            head=str(request["branch_head"]),
        )
        if decision is None:
            raise RecoveryError("cleanup reviewer provenance lacks its core decision")
        expected_core = {
            "result": decision.result,
            "branch": decision.branch,
            "head": decision.head,
            "reasons": list(decision.reasons),
            "facts_digest": decision.facts_digest,
            "input_revision": decision.input_revision,
            "decision_event_id": decision.decision_event_id,
        }
        if (
            provenance["core_decision"] != expected_core
            or observation["decision"] != decision.result
        ):
            raise RecoveryError("cleanup reviewer core decision provenance drifted")
        provenance_events = [
            event
            for event in self.store.list_events(run_id=self.run_id)
            if event.get("idempotency_key")
            == f"configured-runtime:cleanup-review:{review_scope}"
        ]
        if (
            len(provenance_events) != 1
            or int(provenance_events[0]["run_revision"])
            != review_end_revision + 2
        ):
            raise RecoveryError("cleanup reviewer provenance boundary drifted")
        return decision, dict(provenance)

    def _drive_cleanup_review(
        self,
        run: Mapping[str, Any],
        *,
        review_scope: str,
        branch: str,
        target_branch: str,
        receipt_id: str,
        integration_receipt: MergeReceipt,
        caller_facts: CleanupFacts | None = None,
    ) -> tuple[CleanupDecision, dict[str, Any]] | None:
        """Run one zero-capability cleanup reviewer under a strict event window."""

        review_id = f"CLEANUP-REVIEW-{self.identity}-{review_scope}-001"
        attempt_id = f"ATTEMPT-runtime-{self.identity}-{review_scope}-001"
        adapter_operation_id = self._id("OP", 495, scope=review_scope)
        provider = self._adapter_provider()
        manager: WorkspaceManager | None = None
        workspace: Workspace | None = None
        root: Path | None = None
        try:
            if provider is None:
                raise ContractError("cleanup review requires one configured adapter")
            persisted = self._load_cleanup_review_provenance(
                review_scope=review_scope,
                review_id=review_id,
                attempt_id=attempt_id,
                adapter_operation_id=adapter_operation_id,
                branch=branch,
                target_branch=target_branch,
                receipt_id=receipt_id,
                integration_receipt=integration_receipt,
                caller_facts=caller_facts,
                provider=provider,
            )
            if persisted is not None:
                return persisted
            attempt = self.store.get_entity_state("attempt", attempt_id)
            if isinstance(attempt, Mapping):
                binding = attempt.get("payload", {})
                if not isinstance(binding, Mapping):
                    raise RecoveryError("cleanup reviewer Attempt payload is malformed")
                review_request = validate_cleanup_review_request(
                    binding.get("review_request")
                )
                adapter_request = validate_adapter_request(
                    binding.get("adapter_request")
                )
                raw_workspace = Path(str(binding.get("workspace_path", "")))
                if raw_workspace.exists() or raw_workspace.is_symlink():
                    manager, workspace, root = self._merge_review_workspace(binding)
                elif attempt.get("state") != "SUCCEEDED":
                    raise RecoveryError(
                        "active cleanup reviewer workspace is unavailable"
                    )
            else:
                review_request = self.git.build_cleanup_review_request(
                    review_id=review_id,
                    run_id=self.run_id,
                    spec_hash=str(self._current()["spec_hash"]),
                    config_hash=str(self._current()["config_hash"]),
                    branch=branch,
                    target_branch=target_branch,
                    receipt_id=receipt_id,
                    integration_receipt=integration_receipt,
                    caller_facts=caller_facts,
                )
                label = f"cleanup-review-{review_scope}"
                manager, workspace, root = self._workspace(
                    str(review_request["branch_head"]), label
                )
                context_manifest = build_cleanup_review_context_manifest(
                    request=review_request,
                    attempt_id=attempt_id,
                    required_items=(
                        ContextItem(
                            "invariant",
                            "AGENTS.md#branch-cleanup",
                            "Cleanup review is read-only and can never delete a remote ref.",
                        ),
                        ContextItem(
                            "goal",
                            "nm-v6://cleanup-review/goal",
                            "Choose one conservative local-branch cleanup outcome.",
                        ),
                        ContextItem(
                            "requirement",
                            "nm-v6://cleanup-review/requirement",
                            "Bind the decision to current Git and canonical Store facts.",
                        ),
                        ContextItem(
                            "acceptance",
                            "nm-v6://cleanup-review/acceptance",
                            "Return exactly one strict cleanup observation.",
                        ),
                        ContextItem(
                            "phase",
                            f"nm-v6://cleanup-review/phase/{review_scope}",
                            canonical_json({"review_scope": review_scope}).decode(
                                "utf-8"
                            ),
                        ),
                        ContextItem(
                            "task",
                            f"nm-v6://cleanup-review/task/{review_scope}",
                            "Review cleanup without changing the workspace.",
                        ),
                        ContextItem(
                            "acceptance_action",
                            "nm-v6://cleanup-review/acceptance-action",
                            "Return delete_local, retain, or request_administrator.",
                        ),
                    ),
                    max_manifest_bytes=int(
                        self.project["context"]["max_manifest_bytes"]
                    ),
                    max_estimated_tokens=int(
                        self.project["context"]["max_estimated_tokens"]
                    ),
                )
                adapter_request = validate_adapter_request(
                    {
                        "protocol_version": "nm-v6/adapter-request-v1",
                        "operation_id": adapter_operation_id,
                        "run_id": self.run_id,
                        "attempt_id": attempt_id,
                        "role": "cleanup_reviewer",
                        "workspace": str(workspace.path),
                        "context_manifest": context_manifest,
                        "expected_output_schema": "nm-v6/adapter-result-v1",
                        "deadline": (
                            datetime.now(UTC) + timedelta(hours=1)
                        ).isoformat(),
                        "fencing_token": 0,
                        "allowed_capabilities": [],
                    }
                )
                attempt = self._ensure_entity(
                    "attempt",
                    attempt_id,
                    initial_state="CREATED",
                    payload={
                        "role": "cleanup_reviewer",
                        "review_scope": review_scope,
                        "provider": provider,
                        "attempt_id": attempt_id,
                        "operation_id": adapter_operation_id,
                        "branch": branch,
                        "target_branch": target_branch,
                        "receipt_id": receipt_id,
                        "source_commit": review_request["branch_head"],
                        "workspace_path": str(workspace.path),
                        "workspace_root": str(root),
                        "workspace_id": workspace.workspace_id,
                        "workspace_label": label,
                        "review_request": review_request,
                        "review_request_digest": review_request["request_digest"],
                        "adapter_request": adapter_request,
                        "adapter_request_digest": sha256_bytes(
                            canonical_json(adapter_request)
                        ),
                    },
                )
            assert isinstance(attempt, Mapping)
            binding = attempt["payload"]
            if (
                binding.get("role") != "cleanup_reviewer"
                or binding.get("review_scope") != review_scope
                or binding.get("branch") != branch
                or binding.get("target_branch") != target_branch
                or binding.get("receipt_id") != receipt_id
                or binding.get("review_request") != review_request
                or binding.get("adapter_request") != adapter_request
            ):
                raise RecoveryError("cleanup reviewer Attempt binding drifted")
            adapter_request_digest = sha256_bytes(canonical_json(adapter_request))
            if attempt["state"] == "CREATED":
                self._entity_transition("attempt", attempt_id, "DISPATCH")
            common_record = {
                "role": "cleanup_reviewer",
                "review_scope": review_scope,
                "provider": provider,
                "attempt_id": attempt_id,
                "operation_id": adapter_operation_id,
                "review_request_digest": review_request["request_digest"],
            }
            requested_record = self._record_domain_once(
                "ADAPTER_REQUESTED",
                {
                    **common_record,
                    "request_digest": adapter_request_digest,
                    "request": adapter_request,
                },
                idempotency_key=f"configured-runtime:adapter-request:{attempt_id}",
            )
            session_record = self._domain_record(
                "ADAPTER_SESSION_RECORDED",
                idempotency_key=f"configured-runtime:adapter-session:{attempt_id}",
            )
            result_record = self._domain_record(
                "ADAPTER_RESULT_RECORDED",
                idempotency_key=f"configured-runtime:adapter-result:{attempt_id}",
            )
            expected_requested = {
                **common_record,
                "request_digest": adapter_request_digest,
                "request": adapter_request,
            }
            if requested_record != expected_requested:
                raise RecoveryError("cleanup reviewer adapter request drifted")
            adapter = (
                self._adapter_for_attempt(provider, manager)
                if manager is not None
                else None
            )
            if session_record is None:
                if adapter is None:
                    raise RecoveryError(
                        "cleanup reviewer session is missing after workspace disposal"
                    )
                session = adapter.start(adapter_request)
                session_record = self._record_domain_once(
                    "ADAPTER_SESSION_RECORDED",
                    {**common_record, "session_id": str(session["session_id"])},
                    idempotency_key=(
                        f"configured-runtime:adapter-session:{attempt_id}"
                    ),
                )
                checkpoint("runtime.after_cleanup_reviewer_session_record")
            session_id = str(session_record["session_id"])
            if session_record != {**common_record, "session_id": session_id}:
                raise RecoveryError("cleanup reviewer adapter session drifted")
            attempt = self.store.get_entity_state("attempt", attempt_id)
            assert isinstance(attempt, Mapping)
            if attempt["state"] == "DISPATCHED":
                self._entity_transition(
                    "attempt",
                    attempt_id,
                    "START",
                    payload={"state_patch": {"session_id": session_id}},
                )
            if result_record is None:
                if adapter is None:
                    raise RecoveryError(
                        "cleanup reviewer result is missing after workspace disposal"
                    )
                deadline = datetime.fromisoformat(
                    str(adapter_request["deadline"]).replace("Z", "+00:00")
                )
                while True:
                    status = adapter.poll(session_id)
                    if status["status"] != "running":
                        break
                    if datetime.now(UTC) >= deadline:
                        adapter.cancel(session_id)
                        break
                    time.sleep(0.1)
                result_record = self._record_domain_once(
                    "ADAPTER_RESULT_RECORDED",
                    {
                        **common_record,
                        "session_id": session_id,
                        "result": adapter.collect_dict(session_id),
                    },
                    idempotency_key=(
                        f"configured-runtime:adapter-result:{attempt_id}"
                    ),
                )
                checkpoint("runtime.after_cleanup_reviewer_result_record")
            if result_record != {
                **common_record,
                "session_id": session_id,
                "result": result_record.get("result"),
            }:
                raise RecoveryError("cleanup reviewer adapter result drifted")
            validated = validate_cleanup_reviewer_adapter_result(
                result_record["result"],
                adapter_request=adapter_request,
                review_request=review_request,
                expected_session_id=session_id,
            )
            if workspace is not None and (
                run_command(
                    ("git", "rev-parse", "--verify", "HEAD^{commit}"),
                    cwd=workspace.path,
                ).stdout.strip()
                != review_request["branch_head"]
                or run_command(("git", "remote"), cwd=workspace.path)
                .stdout.splitlines()
                or run_command(
                    ("git", "status", "--porcelain=v1", "--untracked-files=all"),
                    cwd=workspace.path,
                ).stdout
            ):
                raise RecoveryError(
                    "cleanup reviewer modified its read-only remote-free workspace"
                )
            attempt = self.store.get_entity_state("attempt", attempt_id)
            assert isinstance(attempt, Mapping)
            if attempt["state"] == "RUNNING":
                self._entity_transition("attempt", attempt_id, "COLLECT")
            attempt = self.store.get_entity_state("attempt", attempt_id)
            assert isinstance(attempt, Mapping)
            if attempt["state"] == "COLLECTING":
                self._entity_transition(
                    "attempt",
                    attempt_id,
                    "SUCCEED",
                    payload={
                        "structured_result_valid": True,
                        "state_patch": {
                            "observation_digest": validated["observations"][0][
                                "observation_digest"
                            ]
                        },
                    },
                )
            self._dispose_persisted_merge_review_workspace(attempt_id)
            review_end_revision = int(review_request["input_revision"]) + 8
            if self._revision() < review_end_revision:
                raise RecoveryError("cleanup reviewer lifecycle is incomplete")
            observation = validated["observations"][0]
            core_facts = self._revalidate_cleanup_review_window(
                review_request=review_request,
                observation=observation,
                attempt_id=attempt_id,
                review_scope=review_scope,
                review_end_revision=review_end_revision,
                review_id=review_id,
                branch=branch,
                target_branch=target_branch,
                receipt_id=receipt_id,
                integration_receipt=integration_receipt,
                caller_facts=caller_facts,
            )
            decision = self._cleanup_core_decision_at_revision(
                review_end_revision=review_end_revision,
                branch=branch,
                head=str(review_request["branch_head"]),
            )
            if decision is None:
                decision = self.git.evaluate_cleanup(core_facts)
                checkpoint("runtime.after_cleanup_core_decision")
            if observation["decision"] != decision.result:
                raise GitPolicyError(
                    "cleanup reviewer decision differs from deterministic core"
                )
            attempt = self.store.get_entity_state("attempt", attempt_id)
            assert isinstance(attempt, Mapping)
            unsigned_record = {
                "record_kind": "reviewer_provenance",
                "review_scope": review_scope,
                "branch": branch,
                "target_branch": target_branch,
                "receipt_id": receipt_id,
                "review_request": review_request,
                "cleanup_review_observation": observation,
                "adapter_request": adapter_request,
                "adapter_request_digest": adapter_request_digest,
                "adapter_session": session_record,
                "adapter_result": result_record,
                "attempt_provenance": {
                    "attempt_id": attempt_id,
                    "state": str(attempt["state"]),
                    "entity_revision": int(attempt["revision"]),
                    "provider": provider,
                    "operation_id": adapter_operation_id,
                    "workspace_id": binding["workspace_id"],
                },
                "core_decision": {
                    "result": decision.result,
                    "branch": decision.branch,
                    "head": decision.head,
                    "reasons": list(decision.reasons),
                    "facts_digest": decision.facts_digest,
                    "input_revision": decision.input_revision,
                    "decision_event_id": decision.decision_event_id,
                },
            }
            provenance = self._record_domain_once(
                "BRANCH_CLEANUP_DECIDED",
                {
                    **unsigned_record,
                    "provenance_digest": sha256_bytes(
                        canonical_json(unsigned_record)
                    ),
                },
                idempotency_key=(
                    f"configured-runtime:cleanup-review:{review_scope}"
                ),
            )
            checkpoint("runtime.after_cleanup_review_provenance")
            return decision, provenance
        except NmV6Error as exc:
            self._merge_review_attempt_failure(attempt_id)
            if (
                workspace is not None
                and manager is not None
                and root is not None
                and (workspace.path.exists() or workspace.path.is_symlink())
            ):
                try:
                    self._dispose_workspace(manager, workspace, root)
                except NmV6Error:
                    pass
            self._transition(
                run,
                "REQUIRE_ATTENTION",
                payload={
                    "actors_fenced": True,
                    "external_operations_reconciled": True,
                    "reason": f"cleanup review failed closed: {exc}",
                    "required_decision": "repair_cleanup_review_inputs_and_replan",
                },
                state_patch={
                    "runtime_attention_reason": f"cleanup review failed closed: {exc}",
                    "runtime_attention_cleanup_scope": review_scope,
                },
            )
            return None

    # -- Hotfix protected integration and reconciliation -----------------

    def _merge_review_policy(
        self,
        *,
        review_scope: str,
        purpose: str,
        sharing_status: str,
        single_logical_change: bool,
        disposable: bool,
        audit_boundary_required: bool,
        rollback_boundary_required: bool,
        future_gate_id: str,
        authorization_id: str,
        rollback_ref: str,
    ) -> dict[str, Any]:
        run = self._current()
        return {
            "review_id": f"REVIEW-runtime-{self.identity}-{review_scope}-001",
            "run_id": self.run_id,
            "spec_hash": str(run["spec_hash"]),
            "config_hash": str(run["config_hash"]),
            "purpose": purpose,
            "sharing_status": sharing_status,
            "single_logical_change": single_logical_change,
            "disposable": disposable,
            "audit_boundary_required": audit_boundary_required,
            "rollback_boundary_required": rollback_boundary_required,
            "allowed_strategies": tuple(self.project["git"]["merge_strategies"]),
            "future_gate_id": future_gate_id,
            "authorization_id": authorization_id,
            "rollback_ref": rollback_ref,
        }

    def _merge_review_workspace(
        self, binding: Mapping[str, Any]
    ) -> tuple[WorkspaceManager, Workspace, Path]:
        required = (
            "workspace_path",
            "workspace_root",
            "workspace_id",
            "workspace_label",
            "source_commit",
        )
        if not all(
            isinstance(binding.get(field), str) and binding.get(field)
            for field in required
        ):
            raise RecoveryError("merge reviewer workspace binding is incomplete")
        raw_path = Path(str(binding["workspace_path"]))
        raw_root = Path(str(binding["workspace_root"]))
        if not raw_path.is_absolute() or not raw_root.is_absolute():
            raise RecoveryError("merge reviewer workspace must be absolute")
        try:
            path = raw_path.resolve(strict=True)
            root = raw_root.resolve(strict=True)
        except OSError as exc:
            raise RecoveryError("merge reviewer workspace is unavailable") from exc
        label = str(binding["workspace_label"])
        if (
            path != Path(os.path.abspath(raw_path))
            or root != Path(os.path.abspath(raw_root))
            or path.parent != root
            or path.is_symlink()
            or root.is_symlink()
            or not path.is_dir()
            or not root.is_dir()
            or path.name != binding["workspace_id"]
            or not root.name.startswith(f"nm-v6-runtime-{label}-")
            or re.fullmatch(
                rf"runtime-{re.escape(self.identity)}-{re.escape(label)}-[0-9a-f]{{8}}",
                str(binding["workspace_id"]),
            )
            is None
        ):
            raise RecoveryError("merge reviewer workspace path binding is invalid")
        try:
            root.relative_to(Path(tempfile.gettempdir()).resolve())
        except ValueError as exc:
            raise RecoveryError("merge reviewer workspace root is not temporary") from exc
        head = run_command(
            ("git", "rev-parse", "--verify", "HEAD^{commit}"), cwd=path
        ).stdout.strip()
        git_dir = Path(
            run_command(
                ("git", "rev-parse", "--absolute-git-dir"), cwd=path
            ).stdout.strip()
        ).resolve()
        remotes = run_command(("git", "remote"), cwd=path).stdout.splitlines()
        dirty = run_command(
            ("git", "status", "--porcelain=v1", "--untracked-files=all"),
            cwd=path,
        ).stdout
        if (
            head != binding["source_commit"]
            or git_dir != path / ".git"
            or remotes
            or dirty
        ):
            raise RecoveryError(
                "merge reviewer workspace is not an unchanged remote-free clone"
            )
        manager = WorkspaceManager(self.target, root)
        return (
            manager,
            Workspace(str(binding["workspace_id"]), path, head, None),
            root,
        )

    def _merge_review_attempt_failure(self, attempt_id: str | None) -> None:
        if not attempt_id:
            return
        attempt = self.store.get_entity_state("attempt", attempt_id)
        if not isinstance(attempt, Mapping):
            return
        state = str(attempt["state"])
        if state == "DISPATCHED":
            self._entity_transition(
                "attempt",
                attempt_id,
                "CANCEL",
                payload={"actors_fenced": True},
            )
            return
        if state == "RUNNING":
            self._entity_transition("attempt", attempt_id, "COLLECT")
            state = "COLLECTING"
        if state == "COLLECTING":
            self._entity_transition("attempt", attempt_id, "FAIL")

    def _dispose_persisted_merge_review_workspace(self, attempt_id: str) -> None:
        attempt = self.store.get_entity_state("attempt", attempt_id)
        if not isinstance(attempt, Mapping):
            raise RecoveryError("merge reviewer Attempt is unavailable for disposal")
        binding = attempt.get("payload", {})
        if not isinstance(binding, Mapping):
            raise RecoveryError("merge reviewer workspace provenance is malformed")
        raw_path = Path(str(binding.get("workspace_path", "")))
        raw_root = Path(str(binding.get("workspace_root", "")))
        workspace_id = str(binding.get("workspace_id", ""))
        label = str(binding.get("workspace_label", ""))
        if (
            not raw_path.is_absolute()
            or not raw_root.is_absolute()
            or raw_path != Path(os.path.abspath(raw_path))
            or raw_root != Path(os.path.abspath(raw_root))
            or raw_path.parent != raw_root
            or raw_path.name != workspace_id
            or not raw_root.name.startswith(f"nm-v6-runtime-{label}-")
            or re.fullmatch(
                rf"runtime-{re.escape(self.identity)}-{re.escape(label)}-[0-9a-f]{{8}}",
                workspace_id,
            )
            is None
        ):
            raise RecoveryError("merge reviewer disposal binding is invalid")
        try:
            raw_root.relative_to(Path(tempfile.gettempdir()).resolve())
        except ValueError as exc:
            raise RecoveryError(
                "merge reviewer disposal root is not temporary"
            ) from exc
        if raw_path.exists() or raw_path.is_symlink():
            manager, workspace, root = self._merge_review_workspace(binding)
            self._dispose_workspace(manager, workspace, root)
            return
        if raw_root.is_symlink():
            raise RecoveryError("merge reviewer disposed root became a symlink")
        if raw_root.exists():
            if not raw_root.is_dir() or any(raw_root.iterdir()):
                raise RecoveryError(
                    "merge reviewer disposed root contains unrelated content"
                )
            raw_root.rmdir()

    def _merge_review_attention(
        self,
        run: Mapping[str, Any],
        *,
        review_scope: str,
        route: str,
        protected_operation_id: str,
        source_ref: str,
        target_branch: str,
        attempt_id: str | None,
        error: NmV6Error,
    ) -> bool:
        self._merge_review_attempt_failure(attempt_id)
        operation_absent = self.store.get_operation(protected_operation_id) is None
        evidence_id = self._evidence(
            489,
            f"merge-review-diagnostic-{review_scope}",
            {
                "route": route,
                "review_scope": review_scope,
                "source_ref": source_ref,
                "target_branch": target_branch,
                "attempt_id": attempt_id,
                "error_type": type(error).__name__,
                "reason": str(error),
                "protected_operation_id": protected_operation_id,
                "protected_operation_absent": operation_absent,
            },
            assertions={
                "merge_review_valid": False,
                "failure_diagnosed_before_protected_operation": operation_absent,
            },
            attempt_id=attempt_id,
            subject_ids=(f"merge-review:{route}",),
            scope=review_scope,
        )
        return self._transition(
            run,
            "REQUIRE_ATTENTION",
            payload={
                "actors_fenced": True,
                "external_operations_reconciled": True,
                "reason": f"merge review failed closed: {error}",
                "required_decision": "repair_merge_review_inputs_and_replan",
                "diagnostic_evidence_id": evidence_id,
            },
            state_patch={
                "runtime_attention_reason": f"merge review failed closed: {error}",
                "runtime_attention_evidence": evidence_id,
                "runtime_attention_route": route,
            },
        )

    def _merge_review_evidence(
        self,
        *,
        review_scope: str,
        route: str,
        record: Mapping[str, Any],
    ) -> str:
        attempt = record["attempt_provenance"]
        digest = str(record["reviewed_proposal_digest"])
        return self._evidence(
            490,
            f"merge-review-{review_scope}",
            {
                "route": route,
                "reviewed_proposal_digest": digest,
                "review_request_digest": record["merge_review_request"][
                    "request_digest"
                ],
                "observation_digest": record["merge_review_observation"][
                    "observation_digest"
                ],
                "adapter_request_digest": record["adapter_request_digest"],
                "adapter_session_id": record["adapter_session"]["session_id"],
                "attempt_provenance": attempt,
                "merge_proposal": record["merge_proposal"],
            },
            assertions={
                "merge_proposal_valid": True,
                "reviewed_proposal_digest_bound": digest
                == sha256_bytes(
                    canonical_json(
                        {
                            key: value
                            for key, value in record.items()
                            if key != "reviewed_proposal_digest"
                        }
                    )
                ),
                "merge_reviewer_attempt_succeeded": attempt["state"]
                == "SUCCEEDED",
                "merge_reviewer_zero_capabilities": record["adapter_request"][
                    "allowed_capabilities"
                ]
                == [],
            },
            source_commit=(
                str(record["merge_review_request"]["source_commit"])
                if route == "dev_to_stable"
                else None
            ),
            candidate_commit=(
                None
                if route == "dev_to_stable"
                else str(record["merge_review_request"]["source_commit"])
            ),
            attempt_id=str(attempt["attempt_id"]),
            subject_ids=(f"merge-review:{route}", digest),
            scope=review_scope,
        )

    def _load_reviewed_merge_proposal(
        self,
        *,
        review_scope: str,
        route: str,
        protected_operation_id: str,
        policy: Mapping[str, Any],
        require_current_git: bool,
    ) -> tuple[MergeProposal, dict[str, Any], str]:
        record = self._domain_record(
            "MERGE_PROPOSED",
            idempotency_key=(
                f"configured-runtime:merge-proposal:{protected_operation_id}"
            ),
        )
        if not isinstance(record, Mapping):
            raise RecoveryError("reviewed merge proposal is unavailable")
        required_fields = {
            "operation_id",
            "review_scope",
            "route",
            "merge_review_request",
            "merge_review_observation",
            "adapter_request",
            "adapter_request_digest",
            "adapter_session",
            "adapter_result",
            "attempt_provenance",
            "merge_proposal",
            "reviewed_proposal_digest",
        }
        if set(record) != required_fields:
            raise RecoveryError("reviewed merge proposal record shape drifted")
        unsigned = {
            key: value
            for key, value in record.items()
            if key != "reviewed_proposal_digest"
        }
        if record["reviewed_proposal_digest"] != sha256_bytes(
            canonical_json(unsigned)
        ):
            raise RecoveryError("reviewed merge proposal digest drifted")
        if (
            record["operation_id"] != protected_operation_id
            or record["review_scope"] != review_scope
            or record["route"] != route
        ):
            raise RecoveryError("reviewed merge proposal route binding drifted")
        review_request = validate_merge_review_request(
            record["merge_review_request"]
        )
        if review_request["route"] != route:
            raise RecoveryError("merge review request route drifted")
        adapter_request = validate_adapter_request(record["adapter_request"])
        adapter_request_digest = sha256_bytes(canonical_json(adapter_request))
        if record["adapter_request_digest"] != adapter_request_digest:
            raise RecoveryError("merge reviewer adapter request digest drifted")
        attempt_id = str(adapter_request["attempt_id"])
        attempt = self.store.get_entity_state("attempt", attempt_id)
        if not isinstance(attempt, Mapping) or attempt.get("state") != "SUCCEEDED":
            raise RecoveryError("merge reviewer Attempt is not durably succeeded")
        attempt_payload = attempt.get("payload", {})
        if not isinstance(attempt_payload, Mapping):
            raise RecoveryError("merge reviewer Attempt payload is malformed")
        if (
            attempt_payload.get("review_request") != review_request
            or attempt_payload.get("adapter_request") != adapter_request
            or attempt_payload.get("adapter_request_digest")
            != adapter_request_digest
            or attempt_payload.get("protected_operation_id")
            != protected_operation_id
        ):
            raise RecoveryError("merge reviewer Attempt provenance drifted")
        expected_provenance = {
            "attempt_id": attempt_id,
            "state": "SUCCEEDED",
            "entity_revision": int(attempt["revision"]),
            "provider": attempt_payload["provider"],
            "operation_id": adapter_request["operation_id"],
            "protected_operation_id": protected_operation_id,
            "workspace_id": attempt_payload["workspace_id"],
            "source_commit": review_request["source_commit"],
            "adapter_request_digest": adapter_request_digest,
        }
        if record["attempt_provenance"] != expected_provenance:
            raise RecoveryError("merge reviewer Attempt record drifted")
        session = self._domain_record(
            "ADAPTER_SESSION_RECORDED",
            idempotency_key=f"configured-runtime:adapter-session:{attempt_id}",
        )
        result = self._domain_record(
            "ADAPTER_RESULT_RECORDED",
            idempotency_key=f"configured-runtime:adapter-result:{attempt_id}",
        )
        requested = self._domain_record(
            "ADAPTER_REQUESTED",
            idempotency_key=f"configured-runtime:adapter-request:{attempt_id}",
        )
        if (
            not isinstance(session, Mapping)
            or not isinstance(result, Mapping)
            or not isinstance(requested, Mapping)
            or record["adapter_session"] != session
            or record["adapter_result"] != result
            or requested.get("request") != adapter_request
            or requested.get("request_digest") != adapter_request_digest
        ):
            raise RecoveryError("merge reviewer adapter event provenance drifted")
        validated_result = validate_merge_reviewer_adapter_result(
            result["result"],
            adapter_request=adapter_request,
            review_request=review_request,
            expected_session_id=str(session["session_id"]),
        )
        observation = validated_result["observations"][0]
        if record["merge_review_observation"] != observation:
            raise RecoveryError("merge reviewer observation record drifted")
        if require_current_git:
            proposal = self.git.build_merge_proposal_from_review(
                request=review_request,
                observation=observation,
                **dict(policy),
            )
        else:
            raw = record["merge_proposal"]
            if not isinstance(raw, Mapping):
                raise RecoveryError("reviewed merge proposal document is malformed")
            try:
                proposal = MergeProposal(
                    source_ref=str(raw["source_ref"]),
                    source_commit=str(raw["source_commit"]),
                    target_ref=str(raw["target_ref"]),
                    target_commit=str(raw["target_commit"]),
                    purpose=str(raw["purpose"]),
                    sharing_status=str(raw["sharing_status"]),
                    strategy=str(raw["strategy"]),
                    rationale=str(raw["rationale"]),
                    candidate_tree=str(raw["candidate_tree"]),
                    expected_result_tree=str(raw["expected_result_tree"]),
                    rollback_ref=str(raw["rollback_ref"]),
                    gate_ids=tuple(map(str, raw["gate_ids"])),
                    authorization_id=str(raw["authorization_id"]),
                )
            except (KeyError, TypeError, ValueError, ContractError) as exc:
                raise RecoveryError("reviewed merge proposal is malformed") from exc
            if (
                proposal.source_ref != review_request["source_ref"]
                or proposal.source_commit != review_request["source_commit"]
                or proposal.target_ref != review_request["target_ref"]
                or proposal.target_commit != review_request["target_commit"]
                or proposal.candidate_tree != review_request["source_tree"]
                or proposal.strategy != observation["strategy"]
                or proposal.rationale != observation["rationale"]
                or proposal.expected_result_tree
                != observation["expected_result_tree"]
                or proposal.purpose != policy["purpose"]
                or proposal.sharing_status != policy["sharing_status"]
                or proposal.rollback_ref != policy["rollback_ref"]
                or proposal.gate_ids != (policy["future_gate_id"],)
                or proposal.authorization_id != policy["authorization_id"]
            ):
                raise RecoveryError("reviewed merge proposal content drifted")
        if record["merge_proposal"] != self._merge_proposal_document(proposal):
            raise RecoveryError("reviewed merge proposal substitution detected")
        evidence_id = self._merge_review_evidence(
            review_scope=review_scope,
            route=route,
            record=record,
        )
        return proposal, dict(record), evidence_id

    def _drive_merge_review(
        self,
        run: Mapping[str, Any],
        *,
        review_scope: str,
        expected_route: str,
        protected_operation_id: str,
        source_ref: str,
        target_branch: str,
        purpose: str,
        sharing_status: str,
        single_logical_change: bool,
        disposable: bool,
        audit_boundary_required: bool,
        rollback_boundary_required: bool,
        future_gate_id: str,
        authorization_id: str,
        rollback_ref: str,
    ) -> tuple[MergeProposal, dict[str, Any], str] | None:
        attempt_id = f"ATTEMPT-runtime-{self.identity}-{review_scope}-001"
        policy = self._merge_review_policy(
            review_scope=review_scope,
            purpose=purpose,
            sharing_status=sharing_status,
            single_logical_change=single_logical_change,
            disposable=disposable,
            audit_boundary_required=audit_boundary_required,
            rollback_boundary_required=rollback_boundary_required,
            future_gate_id=future_gate_id,
            authorization_id=authorization_id,
            rollback_ref=rollback_ref,
        )
        manager: WorkspaceManager | None = None
        workspace: Workspace | None = None
        root: Path | None = None
        try:
            existing_proposal = self._domain_record(
                "MERGE_PROPOSED",
                idempotency_key=(
                    f"configured-runtime:merge-proposal:{protected_operation_id}"
                ),
            )
            if existing_proposal is not None:
                loaded = self._load_reviewed_merge_proposal(
                    review_scope=review_scope,
                    route=expected_route,
                    protected_operation_id=protected_operation_id,
                    policy=policy,
                    require_current_git=True,
                )
                if self.git.remote_head(target_branch) != loaded[0].target_commit:
                    raise GitPolicyError(
                        "remote merge target moved during reviewer decision"
                    )
                self._dispose_persisted_merge_review_workspace(attempt_id)
                return loaded
            review_request = self.git.build_merge_review_request(
                source_ref=source_ref,
                target_branch=target_branch,
                **policy,
            )
            if review_request["route"] != expected_route:
                raise GitPolicyError(
                    "derived merge review route differs from the runtime stage"
                )
            provider = self._adapter_provider()
            if provider is None:
                raise ContractError("merge review requires one configured adapter")
            adapter_operation_id = self._id("OP", 490, scope=review_scope)
            attempt = self.store.get_entity_state("attempt", attempt_id)
            if not isinstance(attempt, Mapping):
                label = f"merge-review-{review_scope}"
                manager, workspace, root = self._workspace(
                    str(review_request["source_commit"]), label
                )
                context_manifest = build_context_manifest(
                    attempt_id=attempt_id,
                    items=(
                        ContextItem(
                            "invariant",
                            "AGENTS.md#merge-review",
                            "The reviewer is read-only and cannot authorize a protected mutation.",
                        ),
                        ContextItem(
                            "goal",
                            "nm-v6://merge-review/goal",
                            canonical_json(
                                {"purpose": purpose, "route": expected_route}
                            ).decode("utf-8"),
                        ),
                        ContextItem(
                            "requirement",
                            "nm-v6://merge-review/requirement",
                            "Propose exactly one configured strategy from current Git facts.",
                        ),
                        ContextItem(
                            "acceptance",
                            "nm-v6://merge-review/acceptance",
                            "The proposal must bind exact refs, trees, policy, and authority.",
                        ),
                        ContextItem(
                            "phase",
                            f"nm-v6://merge-review/phase/{review_scope}",
                            canonical_json({"review_scope": review_scope}).decode(
                                "utf-8"
                            ),
                        ),
                        ContextItem(
                            "task",
                            f"nm-v6://merge-review/task/{review_scope}",
                            "Review merge strategy without changing the workspace.",
                        ),
                        ContextItem(
                            "acceptance_action",
                            "nm-v6://merge-review/acceptance-action",
                            "Return one strict merge-review observation.",
                        ),
                        merge_review_context_item(review_request),
                    ),
                    allowed_paths=(),
                    prohibited_paths=(".nm/runtime",),
                    max_manifest_bytes=int(
                        self.project["context"]["max_manifest_bytes"]
                    ),
                    max_estimated_tokens=int(
                        self.project["context"]["max_estimated_tokens"]
                    ),
                )
                adapter_request = validate_adapter_request(
                    {
                        "protocol_version": "nm-v6/adapter-request-v1",
                        "operation_id": adapter_operation_id,
                        "run_id": self.run_id,
                        "attempt_id": attempt_id,
                        "role": "merge_reviewer",
                        "workspace": str(workspace.path),
                        "context_manifest": context_manifest,
                        "expected_output_schema": "nm-v6/adapter-result-v1",
                        "deadline": (
                            datetime.now(UTC) + timedelta(hours=1)
                        ).isoformat(),
                        "fencing_token": 0,
                        "allowed_capabilities": [],
                    }
                )
                adapter_request_digest = sha256_bytes(
                    canonical_json(adapter_request)
                )
                attempt = self._ensure_entity(
                    "attempt",
                    attempt_id,
                    initial_state="CREATED",
                    payload={
                        "role": "merge_reviewer",
                        "route": expected_route,
                        "review_scope": review_scope,
                        "provider": provider,
                        "attempt_id": attempt_id,
                        "operation_id": adapter_operation_id,
                        "protected_operation_id": protected_operation_id,
                        "source_ref": source_ref,
                        "target_branch": target_branch,
                        "source_commit": review_request["source_commit"],
                        "workspace_path": str(workspace.path),
                        "workspace_root": str(root),
                        "workspace_id": workspace.workspace_id,
                        "workspace_label": label,
                        "review_request": review_request,
                        "review_request_digest": review_request["request_digest"],
                        "adapter_request": adapter_request,
                        "adapter_request_digest": adapter_request_digest,
                    },
                )
            else:
                binding = attempt.get("payload", {})
                if not isinstance(binding, Mapping):
                    raise RecoveryError("merge reviewer Attempt payload is malformed")
                adapter_request = validate_adapter_request(
                    binding.get("adapter_request")
                )
                adapter_request_digest = sha256_bytes(
                    canonical_json(adapter_request)
                )
                expected = {
                    "role": "merge_reviewer",
                    "route": expected_route,
                    "review_scope": review_scope,
                    "provider": provider,
                    "attempt_id": attempt_id,
                    "protected_operation_id": protected_operation_id,
                    "source_ref": source_ref,
                    "target_branch": target_branch,
                    "source_commit": review_request["source_commit"],
                    "review_request": review_request,
                    "review_request_digest": review_request["request_digest"],
                    "adapter_request_digest": adapter_request_digest,
                }
                if any(binding.get(key) != value for key, value in expected.items()):
                    raise RecoveryError("merge reviewer Attempt binding drifted")
                if binding.get("adapter_request") != adapter_request:
                    raise RecoveryError("merge reviewer adapter request drifted")
                manager, workspace, root = self._merge_review_workspace(binding)
            assert isinstance(attempt, Mapping)
            binding = attempt["payload"]
            if attempt["state"] == "CREATED":
                self._entity_transition("attempt", attempt_id, "DISPATCH")
            requested_record = {
                "role": "merge_reviewer",
                "route": expected_route,
                "review_scope": review_scope,
                "provider": provider,
                "attempt_id": attempt_id,
                "operation_id": adapter_operation_id,
                "protected_operation_id": protected_operation_id,
                "request_digest": adapter_request_digest,
                "request": adapter_request,
                "workspace_path": binding["workspace_path"],
                "workspace_root": binding["workspace_root"],
                "workspace_id": binding["workspace_id"],
                "source_commit": review_request["source_commit"],
            }
            self._record_domain_once(
                "ADAPTER_REQUESTED",
                requested_record,
                idempotency_key=f"configured-runtime:adapter-request:{attempt_id}",
            )
            session_record = self._domain_record(
                "ADAPTER_SESSION_RECORDED",
                idempotency_key=f"configured-runtime:adapter-session:{attempt_id}",
            )
            result_record = self._domain_record(
                "ADAPTER_RESULT_RECORDED",
                idempotency_key=f"configured-runtime:adapter-result:{attempt_id}",
            )
            adapter = self._adapter_for_attempt(provider, manager)
            if session_record is None:
                session = adapter.start(adapter_request)
                session_record = self._record_domain_once(
                    "ADAPTER_SESSION_RECORDED",
                    {
                        "role": "merge_reviewer",
                        "route": expected_route,
                        "provider": provider,
                        "attempt_id": attempt_id,
                        "operation_id": adapter_operation_id,
                        "protected_operation_id": protected_operation_id,
                        "request_digest": adapter_request_digest,
                        "session_id": str(session["session_id"]),
                    },
                    idempotency_key=(
                        f"configured-runtime:adapter-session:{attempt_id}"
                    ),
                )
            session_id = str(session_record["session_id"])
            attempt = self.store.get_entity_state("attempt", attempt_id)
            assert isinstance(attempt, Mapping)
            if attempt["state"] == "DISPATCHED":
                self._entity_transition(
                    "attempt",
                    attempt_id,
                    "START",
                    payload={
                        "state_patch": {
                            "session_id": session_id,
                            "adapter_request_digest": adapter_request_digest,
                        }
                    },
                )
            if result_record is None:
                deadline = datetime.fromisoformat(
                    str(adapter_request["deadline"]).replace("Z", "+00:00")
                )
                while True:
                    observation = adapter.poll(session_id)
                    if observation["status"] != "running":
                        break
                    if datetime.now(UTC) >= deadline:
                        adapter.cancel(session_id)
                        break
                    time.sleep(0.1)
                result = adapter.collect_dict(session_id)
                result_record = self._record_domain_once(
                    "ADAPTER_RESULT_RECORDED",
                    {
                        **session_record,
                        "result": result,
                    },
                    idempotency_key=(
                        f"configured-runtime:adapter-result:{attempt_id}"
                    ),
                )
                checkpoint("runtime.after_merge_reviewer_result_record")
            if result_record.get("session_id") != session_id:
                raise RecoveryError("merge reviewer result session drifted")
            validated_result = validate_merge_reviewer_adapter_result(
                result_record["result"],
                adapter_request=adapter_request,
                review_request=review_request,
                expected_session_id=session_id,
            )
            assert workspace is not None
            if (
                run_command(
                    ("git", "rev-parse", "--verify", "HEAD^{commit}"),
                    cwd=workspace.path,
                ).stdout.strip()
                != review_request["source_commit"]
                or run_command(("git", "remote"), cwd=workspace.path)
                .stdout.splitlines()
                or run_command(
                    (
                        "git",
                        "status",
                        "--porcelain=v1",
                        "--untracked-files=all",
                    ),
                    cwd=workspace.path,
                ).stdout
            ):
                raise RecoveryError(
                    "merge reviewer modified its read-only remote-free workspace"
                )
            attempt = self.store.get_entity_state("attempt", attempt_id)
            assert isinstance(attempt, Mapping)
            if attempt["state"] == "RUNNING":
                self._entity_transition("attempt", attempt_id, "COLLECT")
            attempt = self.store.get_entity_state("attempt", attempt_id)
            assert isinstance(attempt, Mapping)
            if attempt["state"] == "COLLECTING":
                self._entity_transition(
                    "attempt",
                    attempt_id,
                    "SUCCEED",
                    payload={
                        "structured_result_valid": True,
                        "state_patch": {
                            "observation_digest": validated_result[
                                "observations"
                            ][0]["observation_digest"]
                        },
                    },
                )
            proposal = self.git.build_merge_proposal_from_review(
                request=review_request,
                observation=validated_result["observations"][0],
                **policy,
            )
            attempt = self.store.get_entity_state("attempt", attempt_id)
            assert isinstance(attempt, Mapping)
            attempt_provenance = {
                "attempt_id": attempt_id,
                "state": str(attempt["state"]),
                "entity_revision": int(attempt["revision"]),
                "provider": provider,
                "operation_id": adapter_operation_id,
                "protected_operation_id": protected_operation_id,
                "workspace_id": binding["workspace_id"],
                "source_commit": review_request["source_commit"],
                "adapter_request_digest": adapter_request_digest,
            }
            unsigned_record = {
                "operation_id": protected_operation_id,
                "review_scope": review_scope,
                "route": expected_route,
                "merge_review_request": review_request,
                "merge_review_observation": validated_result["observations"][0],
                "adapter_request": adapter_request,
                "adapter_request_digest": adapter_request_digest,
                "adapter_session": session_record,
                "adapter_result": result_record,
                "attempt_provenance": attempt_provenance,
                "merge_proposal": self._merge_proposal_document(proposal),
            }
            record = self._record_domain_once(
                "MERGE_PROPOSED",
                {
                    **unsigned_record,
                    "reviewed_proposal_digest": sha256_bytes(
                        canonical_json(unsigned_record)
                    ),
                },
                idempotency_key=(
                    f"configured-runtime:merge-proposal:{protected_operation_id}"
                ),
            )
            checkpoint("runtime.after_merge_proposed_record")
            validated = self._load_reviewed_merge_proposal(
                review_scope=review_scope,
                route=expected_route,
                protected_operation_id=protected_operation_id,
                policy=policy,
                require_current_git=True,
            )
            if self.git.remote_head(target_branch) != validated[0].target_commit:
                raise GitPolicyError(
                    "remote merge target moved during reviewer decision"
                )
            self._dispose_persisted_merge_review_workspace(attempt_id)
            return validated
        except NmV6Error as exc:
            self._merge_review_attention(
                run,
                review_scope=review_scope,
                route=expected_route,
                protected_operation_id=protected_operation_id,
                source_ref=source_ref,
                target_branch=target_branch,
                attempt_id=attempt_id,
                error=exc,
            )
            return None

    @staticmethod
    def _merge_proposal_document(proposal: MergeProposal) -> dict[str, Any]:
        return {
            "source_ref": proposal.source_ref,
            "source_commit": proposal.source_commit,
            "target_ref": proposal.target_ref,
            "target_commit": proposal.target_commit,
            "purpose": proposal.purpose,
            "sharing_status": proposal.sharing_status,
            "strategy": proposal.strategy,
            "rationale": proposal.rationale,
            "candidate_tree": proposal.candidate_tree,
            "expected_result_tree": proposal.expected_result_tree,
            "rollback_ref": proposal.rollback_ref,
            "gate_ids": list(proposal.gate_ids),
            "authorization_id": proposal.authorization_id,
        }

    def _hotfix_attention(
        self,
        run: Mapping[str, Any],
        *,
        reason: str,
        observations: Mapping[str, Any],
    ) -> bool:
        return self._transition(
            run,
            "REQUIRE_ATTENTION",
            payload={
                "actors_fenced": True,
                "external_operations_reconciled": True,
                "reason": reason,
                "required_decision": "repair_hotfix_git_relationship_and_replan",
                "external_observations": dict(observations),
            },
            state_patch={
                "runtime_attention_reason": reason,
                "runtime_attention_observations": dict(observations),
            },
        )

    def _prepare_hotfix_stable(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        branch = str(payload.get("runtime_hotfix_branch", ""))
        candidate = str(payload.get("runtime_hotfix_candidate_commit", ""))
        stable_before = str(payload.get("runtime_hotfix_base_commit", ""))
        if not all((branch, candidate, stable_before)):
            raise ContractError("hotfix stable gate lacks branch/source/base bindings")
        authorization = self._authorization(
            "hotfix_stable", protected_ref=self.git.stable_branch
        )
        if authorization is None:
            return self._wait(run, "trusted_hotfix_stable_authorization")
        authorization_id = self._authorization_id(authorization)
        try:
            if self.git.fetch_stable(
                expected_remote=stable_before, reconcile_local=True
            ) != stable_before:
                raise GitPolicyError("stable no longer equals the hotfix base")
            if self.git.resolve_commit(f"refs/heads/{branch}") != candidate:
                raise GitPolicyError("hotfix branch moved before stable gate")
            future_gate = self._gate_id("HOTFIX_STABLE_GATE")
            operation_id = self._id("OP", 520)
            reviewed = self._drive_merge_review(
                run,
                review_scope="hotfix-to-stable",
                expected_route="hotfix_to_stable",
                protected_operation_id=operation_id,
                source_ref=f"refs/heads/{branch}",
                target_branch=self.git.stable_branch,
                purpose=f"run-{self.identity}-hotfix-stable",
                sharing_status="retained-hotfix",
                single_logical_change=len(self._tasks()) == 1,
                disposable=False,
                audit_boundary_required=False,
                rollback_boundary_required=True,
                future_gate_id=future_gate,
                authorization_id=authorization_id,
                rollback_ref=f"refs/nm-v6/rollback/{self.identity}/hotfix-stable",
            )
        except GitPolicyError as exc:
            return self._hotfix_attention(
                run,
                reason=str(exc),
                observations={
                    "stage": "hotfix_stable_gate",
                    "stable_before": stable_before,
                    "candidate": candidate,
                },
            )
        if reviewed is None:
            return True
        proposal, proposal_record, review_evidence = reviewed
        if (
            proposal.source_commit != candidate
            or proposal.target_commit != stable_before
        ):
            raise RecoveryError("reviewed hotfix stable proposal bindings drifted")
        manager, workspace, root = self._workspace(candidate, "hotfix-stable-verify")
        try:
            result = self._execute(
                ActionExecutor(isolation_backend=manager.isolation_backend),
                workspace,
                str(self.project["actions"]["full_verify"]),
            )
        finally:
            self._dispose_workspace(manager, workspace, root)
        assertions = {
            "trusted_hotfix_authorization_present": True,
            "hotfix_base_matches_stable": self.git.is_ancestor(
                stable_before, candidate
            ),
            "simulated_result_tree_valid": proposal.expected_result_tree
            == self.git.tree_of(candidate),
            "independent_verification_passed": result.status == "succeeded",
            "rollback_ref_recorded": bool(proposal.rollback_ref),
            "expected_target_unchanged": self.git.remote_head(
                self.git.stable_branch
            )
            == stable_before,
        }
        evidence_id = self._evidence(
            520,
            "hotfix-stable-plan",
            {
                "reviewed_proposal_digest": proposal_record[
                    "reviewed_proposal_digest"
                ],
                "verification": result.as_dict(),
            },
            assertions=assertions,
            source_commit=stable_before,
            candidate_commit=candidate,
            subject_ids=(f"hotfix:{branch}",),
        )
        gate_id = self._gate(
            "HOTFIX_STABLE_GATE",
            (evidence_id, review_evidence),
            authorization_id=authorization_id,
            bindings={
                "candidate_commit": candidate,
                "target_commit": stable_before,
            },
        )
        return self._transition(
            run,
            "START_HOTFIX_STABLE_INTEGRATION",
            payload={"protected_ref": self.git.stable_branch},
            state_patch={
                "runtime_hotfix_stable_gate": gate_id,
                "runtime_hotfix_stable_authorization": authorization_id,
                "runtime_hotfix_stable_grant_revision": int(
                    authorization["grant_revision"]
                ),
                "runtime_hotfix_stable_operation": operation_id,
                "runtime_hotfix_stable_review_evidence": review_evidence,
                "runtime_hotfix_stable_reviewed_proposal_digest": proposal_record[
                    "reviewed_proposal_digest"
                ],
            },
            gate_ids=(gate_id,),
            authorization_id=authorization_id,
        )

    def _apply_hotfix_protected(
        self,
        run: Mapping[str, Any],
        *,
        action_id: str,
        operation_id: str,
        gate_id: str,
        authorization_id: str,
        grant_revision: int,
        protected_branch: str,
        event: str,
        patch_prefix: str,
    ) -> bool:
        payload = self._payload(run)
        if action_id == "hotfix_stable":
            review_scope = "hotfix-to-stable"
            route = "hotfix_to_stable"
            purpose = f"run-{self.identity}-hotfix-stable"
            sharing_status = "retained-hotfix"
            single_logical_change = len(self._tasks()) == 1
            disposable = False
            audit_boundary_required = False
            rollback_boundary_required = True
            rollback_ref = (
                f"refs/nm-v6/rollback/{self.identity}/hotfix-stable"
            )
            source_ref = f"refs/heads/{payload['runtime_hotfix_branch']}"
            persisted_digest = payload.get(
                "runtime_hotfix_stable_reviewed_proposal_digest"
            )
            persisted_evidence = payload.get(
                "runtime_hotfix_stable_review_evidence"
            )
        else:
            review_scope = "hotfix-to-dev"
            route = "hotfix_to_dev"
            purpose = f"run-{self.identity}-hotfix-dev-reconciliation"
            sharing_status = "retained-hotfix"
            single_logical_change = len(self._tasks()) == 1
            disposable = False
            audit_boundary_required = True
            rollback_boundary_required = True
            rollback_ref = f"refs/nm-v6/rollback/{self.identity}/hotfix-dev"
            source_ref = f"refs/heads/{payload['runtime_hotfix_branch']}"
            persisted_digest = payload.get(
                "runtime_hotfix_reconciliation_reviewed_proposal_digest"
            )
            persisted_evidence = payload.get(
                "runtime_hotfix_reconciliation_review_evidence"
            )
        policy = self._merge_review_policy(
            review_scope=review_scope,
            purpose=purpose,
            sharing_status=sharing_status,
            single_logical_change=single_logical_change,
            disposable=disposable,
            audit_boundary_required=audit_boundary_required,
            rollback_boundary_required=rollback_boundary_required,
            future_gate_id=gate_id,
            authorization_id=authorization_id,
            rollback_ref=rollback_ref,
        )
        raw_operation = self.store.get_operation(operation_id)
        try:
            proposal, proposal_record, review_evidence = (
                self._load_reviewed_merge_proposal(
                    review_scope=review_scope,
                    route=route,
                    protected_operation_id=operation_id,
                    policy=policy,
                    require_current_git=not isinstance(raw_operation, Mapping),
                )
            )
            if (
                persisted_digest != proposal_record["reviewed_proposal_digest"]
                or persisted_evidence != review_evidence
            ):
                raise RecoveryError("hotfix reviewed proposal run binding drifted")
            if isinstance(raw_operation, Mapping):
                scope = raw_operation.get("scope", {})
                if (
                    not isinstance(scope, Mapping)
                    or scope.get("reviewed_proposal_digest")
                    != proposal_record["reviewed_proposal_digest"]
                    or scope.get("merge_proposal")
                    != proposal_record["merge_proposal"]
                    or scope.get("merge_proposal_digest")
                    != sha256_bytes(
                        canonical_json(proposal_record["merge_proposal"])
                    )
                ):
                    raise RecoveryError(
                        "hotfix protected Operation review binding drifted"
                    )
        except NmV6Error as exc:
            return self._merge_review_attention(
                run,
                review_scope=review_scope,
                route=route,
                protected_operation_id=operation_id,
                source_ref=source_ref,
                target_branch=protected_branch,
                attempt_id=(
                    f"ATTEMPT-runtime-{self.identity}-{review_scope}-001"
                ),
                error=exc,
            )
        operation = self._reconcile_operation(operation_id)
        if isinstance(operation, Mapping) and operation.get("status") == "completed":
            result = operation.get("result", {})
            result_commit = str(result.get("target_after", ""))
            result_tree = str(result.get("result_tree", ""))
            local_after = self.git.resolve_commit(f"refs/heads/{protected_branch}")
            remote_after = self.git.remote_head(protected_branch)
            if (
                not result_commit
                or local_after != result_commit
                or remote_after != result_commit
                or self.git.tree_of(result_commit) != result_tree
                or result_tree != proposal.expected_result_tree
            ):
                raise RecoveryError(
                    "completed hotfix protected Operation differs from observed refs"
                )
            self._record_domain_once(
                "PROTECTED_REF_PUSHED",
                {
                    "operation_id": operation_id,
                    "branch": protected_branch,
                    "before": str(result.get("target_before", "")),
                    "after": result_commit,
                    "observed_after": remote_after,
                },
                idempotency_key=f"configured-runtime:protected-push:{operation_id}",
            )
        else:
            if isinstance(operation, Mapping) and operation.get("status") not in {
                "not_started"
            }:
                return self._wait(run, f"{action_id}_operation_reconciliation")
            if self.git.remote_head(protected_branch) != proposal.target_commit:
                return self._hotfix_attention(
                    run,
                    reason=f"remote {protected_branch} moved after its hotfix gate",
                    observations={
                        "operation_id": operation_id,
                        "expected": proposal.target_commit,
                        "observed": self.git.remote_head(protected_branch),
                    },
                )
            if operation is None:
                self.reducer.start_operation(
                    run_id=self.run_id,
                    expected_revision=self._revision(),
                    operation_id=operation_id,
                    action_id=action_id,
                    operation_kind="protected_ref",
                    idempotency_key=operation_id,
                    authorization_id=authorization_id,
                    gate_id=gate_id,
                    scope={
                        "protected_ref": protected_branch,
                        "candidate_commit": proposal.source_commit,
                        "source_commit": proposal.source_commit,
                        "target_commit": proposal.target_commit,
                        "merge_proposal": proposal_record["merge_proposal"],
                        "merge_proposal_digest": sha256_bytes(
                            canonical_json(proposal_record["merge_proposal"])
                        ),
                        "reviewed_proposal_digest": proposal_record[
                            "reviewed_proposal_digest"
                        ],
                        "gate_id": gate_id,
                    },
                )
            else:
                self.reducer.restart_operation(
                    run_id=self.run_id,
                    expected_revision=self._revision(),
                    operation_id=operation_id,
                    authorization_id=authorization_id,
                    grant_revision=grant_revision,
                    idempotency_key=(
                        f"configured-runtime:restart:{operation_id}:{self._revision()}"
                    ),
                )
            receipt = self.git.execute_proposal(
                proposal,
                require_source_tree_result=action_id == "hotfix_stable",
            )
            push = self.git.push_protected_cas(
                protected_branch,
                expected_remote=receipt.target_before,
                new_commit=receipt.target_after,
                proposal=proposal,
            )
            self.reducer.record_operation_observation(
                OperationObservation(
                    operation_id=operation_id,
                    action_id=action_id,
                    status="succeeded",
                    effect_id=(
                        f"git-{protected_branch}-{operation_id}-{receipt.target_after}"
                    ),
                    result={
                        "target_before": receipt.target_before,
                        "target_after": receipt.target_after,
                        "result_tree": receipt.result_tree,
                        "remote_after": push.observed_after,
                        "proposal_digest": proposal_record[
                            "reviewed_proposal_digest"
                        ],
                    },
                ),
                run_id=self.run_id,
                expected_revision=self._revision(),
                idempotency_key=f"configured-runtime:observe:{operation_id}",
                actor="nm-v6-configured-runtime",
            )
            self._record_domain_once(
                "PROTECTED_REF_PUSHED",
                {
                    "operation_id": operation_id,
                    "branch": push.branch,
                    "before": push.before,
                    "after": push.after,
                    "observed_after": push.observed_after,
                },
                idempotency_key=f"configured-runtime:protected-push:{operation_id}",
            )
            checkpoint(f"runtime.after_{action_id}_push")
            result_commit = receipt.target_after
            result_tree = receipt.result_tree
            remote_after = push.observed_after
        return self._transition(
            run,
            event,
            payload={"protected_ref": protected_branch},
            state_patch={
                f"{patch_prefix}_operation": operation_id,
                f"{patch_prefix}_result_commit": result_commit,
                f"{patch_prefix}_result_tree": result_tree,
                f"{patch_prefix}_remote_after": remote_after,
            },
            gate_ids=(gate_id,),
            authorization_id=authorization_id,
        )

    def _apply_hotfix_stable(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        return self._apply_hotfix_protected(
            run,
            action_id="hotfix_stable",
            operation_id=str(payload["runtime_hotfix_stable_operation"]),
            gate_id=str(payload["runtime_hotfix_stable_gate"]),
            authorization_id=str(payload["runtime_hotfix_stable_authorization"]),
            grant_revision=int(payload["runtime_hotfix_stable_grant_revision"]),
            protected_branch=self.git.stable_branch,
            event="HOTFIX_STABLE_APPLIED",
            patch_prefix="runtime_hotfix_stable",
        )

    def _prepare_hotfix_dev_reconciliation(
        self, run: Mapping[str, Any]
    ) -> bool:
        payload = self._payload(run)
        source = str(payload.get("runtime_hotfix_stable_result_commit", ""))
        source_tree = str(payload.get("runtime_hotfix_stable_result_tree", ""))
        stable_before = str(payload.get("runtime_hotfix_base_commit", ""))
        operation_id = str(payload.get("runtime_hotfix_stable_operation", ""))
        if not all((source, source_tree, stable_before, operation_id)):
            raise ContractError("hotfix stable result lacks persisted bindings")
        local_stable = self.git.resolve_commit(f"refs/heads/{self.git.stable_branch}")
        remote_stable = self.git.remote_head(self.git.stable_branch)
        manager, workspace, root = self._workspace(source, "hotfix-stable-result")
        try:
            post = self._execute(
                ActionExecutor(isolation_backend=manager.isolation_backend),
                workspace,
                str(self.project["actions"]["full_verify"]),
            )
        finally:
            self._dispose_workspace(manager, workspace, root)
        stable_evidence = self._evidence(
            530,
            "hotfix-stable-result",
            {
                "stable_before": stable_before,
                "stable_after": source,
                "local": local_stable,
                "remote": remote_stable,
                "post_verify": post.as_dict(),
            },
            assertions={
                "observed_local_ref_matches": local_stable == source,
                "observed_remote_ref_matches": remote_stable == source,
                "authorized_cas_result_matches": source
                == payload.get("runtime_hotfix_stable_remote_after"),
                "push_receipt_valid": remote_stable == source,
                "result_tree_matches": self.git.tree_of(source) == source_tree,
                "post_update_checks_passed": post.status == "succeeded",
            },
            source_commit=str(payload["runtime_hotfix_candidate_commit"]),
            candidate_commit=source,
            operation_id=operation_id,
            subject_ids=(f"hotfix:{payload['runtime_hotfix_branch']}",),
        )
        stable_result_gate = self._gate(
            "HOTFIX_STABLE_RESULT_GATE",
            (stable_evidence,),
            bindings={
                "source_commit": str(payload["runtime_hotfix_candidate_commit"]),
                "candidate_commit": source,
                "target_commit": stable_before,
            },
        )
        hotfix_branch = str(payload["runtime_hotfix_branch"])
        hotfix_head = str(payload["runtime_hotfix_candidate_commit"])
        stable_receipt_id, stable_receipt = self._protected_integration_receipt(
            operation_id
        )
        stable_cleanup_scope = "cleanup-hotfix-to-stable"
        stable_cleanup_evidence = self._cleanup_responsibility_evidence(
            review_scope=stable_cleanup_scope,
            branch=hotfix_branch,
            head=hotfix_head,
            assertions={
                "review_responsibility_closed": True,
                "backup_retention_absent": True,
                "dependent_work_closed": False,
                "release_responsibility_closed": False,
                "rollback_responsibility_closed": False,
                "audit_retention_absent": True,
                "explicit_retention_absent": False,
            },
            observation={
                "stage": "HOTFIX_STABLE_RESULT_GATE",
                "gate_id": stable_result_gate,
                "operation_id": operation_id,
                "branch": hotfix_branch,
                "branch_head": hotfix_head,
                "stable_result": source,
            },
        )
        stable_cleanup = self._drive_cleanup_review(
            run,
            review_scope=stable_cleanup_scope,
            branch=hotfix_branch,
            target_branch=self.git.stable_branch,
            receipt_id=stable_receipt_id,
            integration_receipt=stable_receipt,
        )
        if stable_cleanup is None:
            return True
        if stable_cleanup[0].result != "retain":
            raise RecoveryError("hotfix branch was not retained after stable integration")
        authorization = self._authorization(
            "hotfix_reconcile_dev", protected_ref=self.git.integration_branch
        )
        if authorization is None:
            return self._wait(run, "trusted_hotfix_dev_reconciliation_authorization")
        authorization_id = self._authorization_id(authorization)
        hotfix_effect = str(payload.get("runtime_hotfix_candidate_commit", ""))
        if not hotfix_effect:
            raise ContractError("hotfix reconciliation lacks its exact effect commit")
        try:
            dev_before = self.git.fetch_dev(reconcile_local=True)
            future_gate = self._gate_id("HOTFIX_RECONCILIATION_GATE")
            reconcile_operation = self._id("OP", 540)
            reviewed = self._drive_merge_review(
                run,
                review_scope="hotfix-to-dev",
                expected_route="hotfix_to_dev",
                protected_operation_id=reconcile_operation,
                source_ref=f"refs/heads/{payload['runtime_hotfix_branch']}",
                target_branch=self.git.integration_branch,
                purpose=f"run-{self.identity}-hotfix-dev-reconciliation",
                sharing_status="retained-hotfix",
                single_logical_change=len(self._tasks()) == 1,
                disposable=False,
                audit_boundary_required=True,
                rollback_boundary_required=True,
                future_gate_id=future_gate,
                authorization_id=authorization_id,
                rollback_ref=f"refs/nm-v6/rollback/{self.identity}/hotfix-dev",
            )
        except GitPolicyError as exc:
            return self._hotfix_attention(
                run,
                reason=str(exc),
                observations={
                    "stage": "hotfix_dev_reconciliation_gate",
                    "source": source,
                },
            )
        if reviewed is None:
            return True
        proposal, proposal_record, review_evidence = reviewed
        if (
            proposal.source_commit != hotfix_effect
            or proposal.target_commit != dev_before
        ):
            raise RecoveryError("reviewed hotfix reconciliation bindings drifted")
        manager, workspace, root = self._workspace(
            hotfix_effect, "hotfix-dev-plan"
        )
        try:
            if proposal.strategy != "fast_forward":
                simulated = run_command(
                    (
                        "git",
                        "merge-tree",
                        "--write-tree",
                        proposal.target_commit,
                        proposal.source_commit,
                    ),
                    cwd=workspace.path,
                    check=False,
                )
                simulated_tree = (
                    simulated.stdout.splitlines()[0].strip()
                    if simulated.returncode == 0 and simulated.stdout
                    else ""
                )
                if simulated_tree != proposal.expected_result_tree:
                    raise RecoveryError(
                        "hotfix reconciliation verification simulation drifted"
                    )
                run_command(
                    (
                        "git",
                        "read-tree",
                        "--reset",
                        "-u",
                        proposal.expected_result_tree,
                    ),
                    cwd=workspace.path,
                )
                if (
                    run_command(("git", "write-tree"), cwd=workspace.path)
                    .stdout.strip()
                    != proposal.expected_result_tree
                ):
                    raise RecoveryError(
                        "hotfix reconciliation verification workspace tree drifted"
                    )
            affected = self._execute(
                ActionExecutor(isolation_backend=manager.isolation_backend),
                workspace,
                str(self.project["actions"]["full_verify"]),
            )
        finally:
            self._dispose_workspace(manager, workspace, root)
        reconciliation_evidence = self._evidence(
            540,
            "hotfix-dev-reconciliation-plan",
            {
                "reviewed_proposal_digest": proposal_record[
                    "reviewed_proposal_digest"
                ],
                "verification": affected.as_dict(),
            },
            assertions={
                "exact_hotfix_effect_present": proposal.source_commit
                == hotfix_effect,
                "expected_dev_unchanged": self.git.remote_head(
                    self.git.integration_branch
                )
                == dev_before,
                "affected_verification_passed": affected.status == "succeeded",
            },
            source_commit=hotfix_effect,
            candidate_commit=hotfix_effect,
            subject_ids=(f"hotfix:{payload['runtime_hotfix_branch']}",),
        )
        reconciliation_gate = self._gate(
            "HOTFIX_RECONCILIATION_GATE",
            (reconciliation_evidence, review_evidence),
            authorization_id=authorization_id,
            bindings={
                "candidate_commit": hotfix_effect,
                "target_commit": dev_before,
            },
        )
        return self._transition(
            run,
            "START_HOTFIX_DEV_RECONCILIATION",
            payload={"protected_ref": self.git.integration_branch},
            state_patch={
                "runtime_hotfix_stable_result_gate": stable_result_gate,
                "runtime_hotfix_stable_cleanup_evidence": stable_cleanup_evidence,
                "runtime_hotfix_stable_cleanup_provenance_digest": stable_cleanup[1][
                    "provenance_digest"
                ],
                "runtime_hotfix_dev_before": dev_before,
                "runtime_hotfix_reconciliation_gate": reconciliation_gate,
                "runtime_hotfix_reconciliation_authorization": authorization_id,
                "runtime_hotfix_reconciliation_grant_revision": int(
                    authorization["grant_revision"]
                ),
                "runtime_hotfix_reconciliation_operation": reconcile_operation,
                "runtime_hotfix_reconciliation_review_evidence": review_evidence,
                "runtime_hotfix_reconciliation_reviewed_proposal_digest": proposal_record[
                    "reviewed_proposal_digest"
                ],
            },
            gate_ids=(stable_result_gate, reconciliation_gate),
            authorization_id=authorization_id,
        )

    def _apply_hotfix_dev_reconciliation(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        return self._apply_hotfix_protected(
            run,
            action_id="hotfix_reconcile_dev",
            operation_id=str(payload["runtime_hotfix_reconciliation_operation"]),
            gate_id=str(payload["runtime_hotfix_reconciliation_gate"]),
            authorization_id=str(
                payload["runtime_hotfix_reconciliation_authorization"]
            ),
            grant_revision=int(
                payload["runtime_hotfix_reconciliation_grant_revision"]
            ),
            protected_branch=self.git.integration_branch,
            event="HOTFIX_DEV_APPLIED",
            patch_prefix="runtime_hotfix_dev",
        )

    def _verify_hotfix_dev_reconciliation(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        release_source = str(
            payload.get("runtime_hotfix_stable_result_commit", "")
        )
        hotfix_effect = str(payload.get("runtime_hotfix_candidate_commit", ""))
        dev_before = str(payload.get("runtime_hotfix_dev_before", ""))
        result_commit = str(payload.get("runtime_hotfix_dev_result_commit", ""))
        result_tree = str(payload.get("runtime_hotfix_dev_result_tree", ""))
        operation_id = str(payload.get("runtime_hotfix_dev_operation", ""))
        if not all(
            (
                release_source,
                hotfix_effect,
                dev_before,
                result_commit,
                result_tree,
                operation_id,
            )
        ):
            raise ContractError("hotfix dev result lacks persisted bindings")
        local_after = self.git.resolve_commit(f"refs/heads/{self.git.integration_branch}")
        remote_after = self.git.remote_head(self.git.integration_branch)
        manager, workspace, root = self._workspace(
            result_commit, "hotfix-dev-result"
        )
        try:
            post = self._execute(
                ActionExecutor(isolation_backend=manager.isolation_backend),
                workspace,
                str(self.project["actions"]["full_verify"]),
            )
        finally:
            self._dispose_workspace(manager, workspace, root)
        exact_effect = self.git.is_ancestor(hotfix_effect, result_commit)
        evidence_id = self._evidence(
            550,
            "hotfix-dev-reconciliation-result",
            {
                "release_source": release_source,
                "hotfix_effect": hotfix_effect,
                "dev_before": dev_before,
                "dev_after": result_commit,
                "local": local_after,
                "remote": remote_after,
                "post_verify": post.as_dict(),
            },
            assertions={
                "observed_local_ref_matches": local_after == result_commit,
                "observed_remote_ref_matches": remote_after == result_commit,
                "authorized_cas_result_matches": result_commit
                == payload.get("runtime_hotfix_dev_remote_after"),
                "push_receipt_valid": remote_after == result_commit,
                "exact_hotfix_effect_present": exact_effect,
                "result_tree_matches": self.git.tree_of(result_commit) == result_tree,
                "post_update_checks_passed": post.status == "succeeded",
            },
            source_commit=release_source,
            candidate_commit=result_commit,
            operation_id=operation_id,
            subject_ids=(f"hotfix:{payload['runtime_hotfix_branch']}",),
        )
        phase_entities = tuple(
            self._entity_id(str(phase["id"])) for phase in self._phases()
        )
        result_gate = self._gate(
            "HOTFIX_RECONCILIATION_RESULT_GATE",
            (evidence_id,),
            bindings={
                "source_commit": release_source,
                "candidate_commit": result_commit,
                "target_commit": dev_before,
            },
            subject_ids=(self.run_id, *phase_entities),
        )
        hotfix_branch = str(payload["runtime_hotfix_branch"])
        receipt_id, integration_receipt = self._protected_integration_receipt(
            operation_id
        )
        cleanup_scope = "cleanup-hotfix-to-dev"
        cleanup_evidence = self._cleanup_responsibility_evidence(
            review_scope=cleanup_scope,
            branch=hotfix_branch,
            head=hotfix_effect,
            assertions={
                "review_responsibility_closed": True,
                "backup_retention_absent": True,
                "dependent_work_closed": True,
                "release_responsibility_closed": False,
                "rollback_responsibility_closed": False,
                "audit_retention_absent": True,
                "explicit_retention_absent": False,
            },
            observation={
                "stage": "HOTFIX_RECONCILIATION_RESULT_GATE",
                "gate_id": result_gate,
                "operation_id": operation_id,
                "branch": hotfix_branch,
                "branch_head": hotfix_effect,
                "dev_result": result_commit,
            },
        )
        cleanup_review = self._drive_cleanup_review(
            run,
            review_scope=cleanup_scope,
            branch=hotfix_branch,
            target_branch=self.git.integration_branch,
            receipt_id=receipt_id,
            integration_receipt=integration_receipt,
        )
        if cleanup_review is None:
            return True
        if cleanup_review[0].result != "retain":
            raise RecoveryError("hotfix branch was not retained after dev reconciliation")
        for phase, phase_entity_id in zip(self._phases(), phase_entities):
            entity = self.store.get_entity_state("phase", phase_entity_id)
            if not isinstance(entity, Mapping) or entity.get("state") != "ACCEPTED":
                raise RecoveryError(
                    f"hotfix Phase is not accepted before dev reconciliation: {phase['id']}"
                )
            self._entity_transition(
                "phase",
                phase_entity_id,
                "MARK_HOTFIX_INTEGRATED",
                gate_ids=(result_gate,),
            )
        return self._transition(
            run,
            "HOTFIX_RECONCILED",
            payload={"hotfix_effect_exact": exact_effect},
            state_patch={
                "runtime_hotfix_reconciliation_result_gate": result_gate,
                "runtime_verified_dev_commit": result_commit,
                "runtime_verified_dev_tree": result_tree,
                "runtime_hotfix_dev_cleanup_evidence": cleanup_evidence,
                "runtime_hotfix_dev_cleanup_provenance_digest": cleanup_review[1][
                    "provenance_digest"
                ],
                "runtime_completed_phases": sorted(
                    str(phase["id"]) for phase in self._phases()
                ),
            },
            gate_ids=(result_gate,),
        )

    # -- Release and publication -----------------------------------------

    def _delivery_contract(self) -> tuple[str, str, tuple[str, ...]]:
        value = self.traceability.get("required_delivery_stages")
        if not isinstance(value, Mapping):
            raise ContractError(
                "persisted traceability lacks canonical delivery decisions"
            )
        release = value.get("release")
        deploy = value.get("deploy")
        environments = value.get("environments")
        if release not in {"required", "not_applicable"} or deploy not in {
            "required",
            "not_applicable",
        }:
            raise ContractError("persisted delivery stage decision is invalid")
        if (
            not isinstance(environments, list)
            or not all(isinstance(item, str) and item for item in environments)
            or len(environments) != len(set(environments))
        ):
            raise ContractError("persisted delivery environment order is invalid")
        configured = self.project["delivery"]["environments"]
        missing = [item for item in environments if item not in configured]
        if missing:
            raise ContractError(
                "persisted delivery environments are not configured: "
                + ", ".join(missing)
            )
        return str(release), str(deploy), tuple(environments)

    @staticmethod
    def _environment_scope(index: int) -> str:
        if index < 0:
            raise ContractError("delivery environment index must be nonnegative")
        return f"env-{index:03d}"

    def _delivery_attention(
        self,
        run: Mapping[str, Any],
        *,
        reason: str,
        required_decision: str,
        observations: Mapping[str, Any],
        evidence_ids: Sequence[str] = (),
        external_operations_reconciled: bool,
        state_patch: Mapping[str, Any] | None = None,
    ) -> bool:
        attention = {
            "reason": reason,
            "required_decision": required_decision,
            "evidence_ids": list(evidence_ids),
            "external_observations": dict(observations),
        }
        return self._transition(
            run,
            "REQUIRE_ATTENTION",
            payload={
                "actors_fenced": True,
                "external_operations_reconciled": external_operations_reconciled,
                **attention,
            },
            state_patch={
                "runtime_attention": attention,
                **dict(state_patch or {}),
            },
        )

    def _skip_release_not_applicable(self, run: Mapping[str, Any]) -> bool:
        release, _deploy, environments = self._delivery_contract()
        assertions = {
            "spec_explicitly_not_applicable": release == "not_applicable",
            "stage_traceability_valid": True,
            "not_applicable_decision_valid": release == "not_applicable",
        }
        evidence_id = self._evidence(
            600,
            "release-not-applicable",
            {
                "decision": release,
                "environments": list(environments),
                "traceability_digest": sha256_bytes(
                    canonical_json(self.traceability)
                ),
            },
            assertions=assertions,
            subject_ids=("delivery:release",),
        )
        gate_id = self._gate(
            "RELEASE_GATE",
            (evidence_id,),
            not_applicable=True,
        )
        return self._transition(
            run,
            "SKIP_RELEASE_NOT_APPLICABLE",
            payload={"release_not_applicable": True},
            state_patch={
                "runtime_release_decision": "not_applicable",
                "runtime_release_gate": gate_id,
            },
            gate_ids=(gate_id,),
        )

    def _prepare_release(self, run: Mapping[str, Any]) -> bool:
        release_decision, _deploy_decision, _environments = self._delivery_contract()
        if release_decision == "not_applicable":
            return self._skip_release_not_applicable(run)
        authorization = self._authorization(
            "release", protected_ref=self.git.stable_branch
        )
        if authorization is None:
            return self._wait(run, "trusted_release_authorization")
        authorization_id = self._authorization_id(authorization)
        current = self._current()
        if not authorization_scope_allows(
            authorization,
            run_id=self.run_id,
            spec_hash=str(current["spec_hash"]),
            config_hash=str(current["config_hash"]),
            action="publish",
            protected_ref=self.git.stable_branch,
        ):
            return self._wait(run, "trusted_publish_authorization")
        payload = self._payload(run)
        hotfix = run.get("run_kind") == "hotfix"
        reconciliation_gate_id: str | None = None
        reconciliation_evidence_ids: tuple[str, ...] = ()
        release_review_record: dict[str, Any]
        if hotfix:
            source_kind = "hotfix_stable"
            source_commit = str(
                payload.get("runtime_hotfix_stable_result_commit", "")
            )
            source_tree = str(payload.get("runtime_hotfix_stable_result_tree", ""))
            stable_before = source_commit
            reconciliation_gate_id = str(
                payload.get("runtime_hotfix_reconciliation_result_gate", "")
            )
            reconciliation = self.store.get_gate(reconciliation_gate_id)
            if (
                not isinstance(reconciliation, Mapping)
                or reconciliation.get("gate_type")
                != "HOTFIX_RECONCILIATION_RESULT_GATE"
                or reconciliation.get("result") != "passed"
                or reconciliation.get("source_commit") != source_commit
                or reconciliation.get("candidate_commit")
                != payload.get("runtime_hotfix_dev_result_commit")
                or reconciliation.get("target_commit")
                != payload.get("runtime_hotfix_dev_before")
            ):
                raise RecoveryError(
                    "hotfix release lacks its exact reconciliation result gate"
                )
            reconciliation_evidence_ids = tuple(
                map(str, reconciliation.get("evidence_ids", []))
            )
            if (
                self.git.fetch_stable(reconcile_local=True) != source_commit
                or self.git.remote_head(self.git.stable_branch) != source_commit
                or self.git.tree_of(source_commit) != source_tree
            ):
                raise RecoveryError(
                    "hotfix release source differs from verified stable result"
                )
            expected_stable_tree = source_tree
            hotfix_review_policy = self._merge_review_policy(
                review_scope="hotfix-to-stable",
                purpose=f"run-{self.identity}-hotfix-stable",
                sharing_status="retained-hotfix",
                single_logical_change=len(self._tasks()) == 1,
                disposable=False,
                audit_boundary_required=False,
                rollback_boundary_required=True,
                future_gate_id=str(payload["runtime_hotfix_stable_gate"]),
                authorization_id=str(
                    payload["runtime_hotfix_stable_authorization"]
                ),
                rollback_ref=(
                    f"refs/nm-v6/rollback/{self.identity}/hotfix-stable"
                ),
            )
            _hotfix_proposal, release_review_record, _hotfix_review_evidence = (
                self._load_reviewed_merge_proposal(
                    review_scope="hotfix-to-stable",
                    route="hotfix_to_stable",
                    protected_operation_id=self._id("OP", 520),
                    policy=hotfix_review_policy,
                    require_current_git=False,
                )
            )
        else:
            source_kind = "dev"
            source_commit = str(payload.get("runtime_verified_dev_commit", ""))
            source_tree = str(payload.get("runtime_verified_dev_tree", ""))
            if not source_commit or not source_tree:
                raise ContractError("release lacks a verified dev source")
            if self.git.fetch_dev(reconcile_local=True) != source_commit:
                raise ContractError(
                    "remote dev moved after integration result verification"
                )
            stable_before = self.git.fetch_stable(reconcile_local=True)
            future_gate = self._gate_id("RELEASE_GATE")
            reviewed = self._drive_merge_review(
                run,
                review_scope="dev-to-stable",
                expected_route="dev_to_stable",
                protected_operation_id=self._id("OP", 602),
                source_ref=f"refs/heads/{self.git.integration_branch}",
                target_branch=self.git.stable_branch,
                purpose=f"run-{self.identity}-stable-promotion",
                sharing_status="protected",
                single_logical_change=False,
                disposable=False,
                audit_boundary_required=True,
                rollback_boundary_required=True,
                future_gate_id=future_gate,
                authorization_id=authorization_id,
                rollback_ref=f"refs/nm-v6/rollback/{self.identity}/stable",
            )
            if reviewed is None:
                return True
            proposal, release_review_record, _initial_review_evidence = reviewed
            if (
                proposal.source_commit != source_commit
                or proposal.target_commit != stable_before
                or proposal.expected_result_tree != source_tree
            ):
                raise RecoveryError("reviewed stable promotion bindings drifted")
            expected_stable_tree = proposal.expected_result_tree
        release_source = ReleaseSource(
            source_kind,
            source_commit,
            source_tree,
            str(run["spec_hash"]),
            str(run["config_hash"]),
            reconciliation_gate_id,
        )
        manager, workspace, root = self._workspace(source_commit, "release-build")
        try:
            executor = ActionExecutor(
                isolation_backend=manager.isolation_backend,
                secret_resolver=_ProjectSecretResolver(self.target, self.project),
            )
            delivery = DeliveryController(
                self.definitions,
                executor,
                RecoveryController(
                    self.definitions,
                    executor,
                    ReducerOperationRecorder(
                        self.reducer,
                        self.store,
                        run_id=self.run_id,
                        expected_revision=lambda: self._revision(),
                    ),
                ),
            )
            build = delivery.build(
                workspace=workspace,
                action_id=str(self.project["actions"]["build"]),
                source_commit=source_commit,
            )
            metadata = delivery.release_metadata(
                workspace=workspace,
                action_id=str(self.project["actions"]["release_metadata"]),
                source=release_source,
            )
        finally:
            self._dispose_workspace(manager, workspace, root)
        artifact = str(build.artifact_digest or "")
        release_review_evidence = self._evidence(
            599,
            "release-merge-review-binding",
            {
                "route": release_review_record["route"],
                "reviewed_proposal_digest": release_review_record[
                    "reviewed_proposal_digest"
                ],
                "review_evidence_id": self._merge_review_evidence(
                    review_scope=str(release_review_record["review_scope"]),
                    route=str(release_review_record["route"]),
                    record=release_review_record,
                ),
                "release_source_kind": source_kind,
                "release_source_commit": source_commit,
                "release_source_tree": source_tree,
                "artifact_digest": artifact,
            },
            assertions={"merge_proposal_valid": True},
            source_commit=source_commit,
            release_source_kind=source_kind,
            release_source_commit=source_commit,
            release_source_tree=source_tree,
            hotfix_reconciliation_gate_id=reconciliation_gate_id,
            artifact_digest=artifact,
            attempt_id=str(
                release_review_record["attempt_provenance"]["attempt_id"]
            ),
            subject_ids=(
                "release",
                str(release_review_record["reviewed_proposal_digest"]),
            ),
            scope="release-merge-review",
        )
        release_acceptance = self._mandatory_acceptance_evidence("release")
        release_acceptance_ids = tuple(
            dict.fromkeys(
                evidence_id
                for evidence_ids in release_acceptance.values()
                for evidence_id in evidence_ids
            )
        )
        assertions = {
            "release_source_fixed": (
                self.git.remote_head(self.git.stable_branch) == source_commit
                if hotfix
                else self.git.remote_head(self.git.integration_branch)
                == source_commit
            ),
            "release_acceptance_covered": all(release_acceptance.values()),
            "immutable_artifact_valid": bool(artifact),
            "stable_result_tree_valid": expected_stable_tree == source_tree,
            "release_metadata_valid": bool(
                metadata.tag
                and metadata.published_version
                and metadata.changelog_digest
                and metadata.metadata_digest
            ),
            "idempotency_present": all(
                self.definitions[str(self.project["actions"][action])].idempotency.mode
                == "required"
                for action in ("release", "publish")
            ),
            "observe_reconcile_ready": all(
                self.definitions[str(self.project["actions"][action])].observe_action_id
                and self.definitions[str(self.project["actions"][action])].reconcile_action_id
                for action in ("release", "publish")
            ),
            "rollback_target_recorded": bool(stable_before),
            "hotfix_reconciliation_valid_or_not_applicable": (
                not hotfix or bool(reconciliation_gate_id)
            ),
        }
        evidence_id = self._evidence(
            600,
            "release-plan",
            {
                "build": build.as_dict(),
                "source_commit": source_commit,
                "source_tree": source_tree,
                "stable_before": stable_before,
                "expected_stable_tree": expected_stable_tree,
                "release_source_kind": source_kind,
                "hotfix_reconciliation_gate_id": reconciliation_gate_id,
                "tag": metadata.tag,
                "version": metadata.published_version,
                "changelog_digest": metadata.changelog_digest,
                "release_metadata_digest": metadata.metadata_digest,
                "release_metadata_result": metadata.result.as_dict(),
            },
            assertions=assertions,
            source_commit=source_commit,
            release_source_kind=source_kind,
            release_source_commit=source_commit,
            release_source_tree=source_tree,
            hotfix_reconciliation_gate_id=reconciliation_gate_id,
            artifact_digest=artifact,
            subject_ids=("release",),
        )
        release_gate = self._gate(
            "RELEASE_GATE",
            (
                evidence_id,
                release_review_evidence,
                *release_acceptance_ids,
                *reconciliation_evidence_ids,
            ),
            authorization_id=authorization_id,
            bindings={
                "source_commit": source_commit,
                "target_commit": stable_before,
                "release_source_kind": source_kind,
                "release_source_commit": source_commit,
                "release_source_tree": source_tree,
                "hotfix_reconciliation_gate_id": reconciliation_gate_id,
                "artifact_digest": artifact,
            },
        )
        return self._transition(
            run,
            "START_RELEASE",
            payload={
                "release_required": True,
                "protected_ref": self.git.stable_branch,
            },
            state_patch={
                "runtime_release_gate": release_gate,
                "runtime_release_authorization": authorization_id,
                "runtime_release_grant_revision": int(
                    authorization["grant_revision"]
                ),
                "runtime_release_source_commit": source_commit,
                "runtime_release_source_tree": source_tree,
                "runtime_release_source_kind": source_kind,
                "runtime_hotfix_reconciliation_gate_id": reconciliation_gate_id,
                "runtime_release_artifact": artifact,
                "runtime_stable_before": stable_before,
                "runtime_release_tag": metadata.tag,
                "runtime_release_version": metadata.published_version,
                "runtime_release_changelog_digest": metadata.changelog_digest,
                "runtime_release_metadata_digest": metadata.metadata_digest,
                "runtime_release_decision": "required",
                "runtime_release_review_evidence": release_review_evidence,
                "runtime_release_reviewed_proposal_digest": release_review_record[
                    "reviewed_proposal_digest"
                ],
            },
            gate_ids=(release_gate,),
            authorization_id=authorization_id,
        )

    def _mandatory_acceptance_evidence(
        self, stage: str
    ) -> dict[str, tuple[str, ...]]:
        order = {
            "task": 0,
            "phase": 1,
            "dev_integration": 2,
            "release": 3,
            "deploy": 4,
            "completion": 5,
        }
        if stage not in order:
            raise ContractError(f"unknown acceptance stage: {stage}")
        receipts = self.store.list_evidence(self.run_id)
        current = self._current()
        result: dict[str, tuple[str, ...]] = {}
        for acceptance in self.traceability.get("acceptance", []):
            if not acceptance.get("mandatory", False):
                continue
            required = str(acceptance.get("required_by_stage"))
            if order.get(required, 999) > order[stage]:
                continue
            assertion = f"acceptance:{acceptance['id']}"
            supporting: list[str] = []
            for receipt in receipts:
                if (
                    receipt.get("attempt_id") is None
                    or acceptance["id"] not in receipt.get("subject_ids", [])
                    or receipt.get("assertions", {}).get(assertion) is not True
                ):
                    continue
                self.evidence_store.validate(receipt)
                if (
                    receipt.get("run_id") != self.run_id
                    or receipt.get("spec_hash") != current["spec_hash"]
                    or receipt.get("config_hash") != current["config_hash"]
                ):
                    raise RecoveryError(
                        f"acceptance evidence binding is stale: {acceptance['id']}"
                    )
                supporting.append(str(receipt["evidence_id"]))
            if not supporting:
                raise RecoveryError(
                    f"mandatory acceptance lacks original Task evidence: {acceptance['id']}"
                )
            result[str(acceptance["id"])] = tuple(dict.fromkeys(supporting))
        return result

    def _acceptance_due(self, stage: str) -> bool:
        self._mandatory_acceptance_evidence(stage)
        return True

    def _release(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        source_commit = str(payload.get("runtime_release_source_commit", ""))
        source_tree = str(payload.get("runtime_release_source_tree", ""))
        source_kind = str(payload.get("runtime_release_source_kind", "dev"))
        reconciliation_gate_id = payload.get(
            "runtime_hotfix_reconciliation_gate_id"
        )
        if reconciliation_gate_id is not None:
            reconciliation_gate_id = str(reconciliation_gate_id)
        artifact = str(payload.get("runtime_release_artifact", ""))
        stable_before = str(payload.get("runtime_stable_before", ""))
        gate_id = str(payload.get("runtime_release_gate", ""))
        authorization_id = str(
            payload.get("runtime_release_authorization", "")
        )
        grant_revision = int(payload.get("runtime_release_grant_revision", -1))
        if not all(
            (source_commit, source_tree, artifact, stable_before, gate_id, authorization_id)
        ) or grant_revision < 0:
            raise ContractError("release execution lacks persisted bindings")
        git_operation = self._id("OP", 602)
        proposal: MergeProposal | None = None
        proposal_record: dict[str, Any] | None = None
        raw_git_operation = self.store.get_operation(git_operation)
        if source_kind == "dev":
            review_policy = self._merge_review_policy(
                review_scope="dev-to-stable",
                purpose=f"run-{self.identity}-stable-promotion",
                sharing_status="protected",
                single_logical_change=False,
                disposable=False,
                audit_boundary_required=True,
                rollback_boundary_required=True,
                future_gate_id=gate_id,
                authorization_id=authorization_id,
                rollback_ref=f"refs/nm-v6/rollback/{self.identity}/stable",
            )
            try:
                proposal, proposal_record, _initial_review_evidence = (
                    self._load_reviewed_merge_proposal(
                        review_scope="dev-to-stable",
                        route="dev_to_stable",
                        protected_operation_id=git_operation,
                        policy=review_policy,
                        require_current_git=not isinstance(
                            raw_git_operation, Mapping
                        ),
                    )
                )
                if (
                    payload.get("runtime_release_reviewed_proposal_digest")
                    != proposal_record["reviewed_proposal_digest"]
                ):
                    raise RecoveryError(
                        "stable promotion reviewed proposal run binding drifted"
                    )
                release_review_evidence = self.store.get_evidence(
                    str(payload.get("runtime_release_review_evidence", ""))
                )
                if not isinstance(release_review_evidence, Mapping):
                    raise RecoveryError(
                        "stable promotion release-bound review evidence is missing"
                    )
                self.evidence_store.validate(release_review_evidence)
                review_observation = json.loads(
                    self.evidence_store.read_blob(
                        str(release_review_evidence["stdout_digest"])
                    )
                )
                if (
                    review_observation.get("reviewed_proposal_digest")
                    != proposal_record["reviewed_proposal_digest"]
                    or release_review_evidence.get("source_commit")
                    != source_commit
                    or release_review_evidence.get("artifact_digest") != artifact
                    or release_review_evidence.get("assertions", {}).get(
                        "merge_proposal_valid"
                    )
                    is not True
                ):
                    raise RecoveryError(
                        "stable promotion release review evidence drifted"
                    )
                if isinstance(raw_git_operation, Mapping):
                    operation_scope = raw_git_operation.get("scope", {})
                    if (
                        not isinstance(operation_scope, Mapping)
                        or operation_scope.get("reviewed_proposal_digest")
                        != proposal_record["reviewed_proposal_digest"]
                        or operation_scope.get("merge_proposal")
                        != proposal_record["merge_proposal"]
                    ):
                        raise RecoveryError(
                            "stable promotion Operation review binding drifted"
                        )
            except NmV6Error as exc:
                return self._merge_review_attention(
                    run,
                    review_scope="dev-to-stable",
                    route="dev_to_stable",
                    protected_operation_id=git_operation,
                    source_ref=f"refs/heads/{self.git.integration_branch}",
                    target_branch=self.git.stable_branch,
                    attempt_id=(
                        f"ATTEMPT-runtime-{self.identity}-dev-to-stable-001"
                    ),
                    error=exc,
                )
        existing_git: Mapping[str, Any] | None
        if source_kind == "hotfix_stable":
            existing_git = {
                "status": "completed",
                "result": {
                    "target_after": source_commit,
                    "result_tree": source_tree,
                    "remote_after": self.git.remote_head(self.git.stable_branch),
                },
            }
        else:
            existing_git = self._reconcile_operation(git_operation)
        if isinstance(existing_git, Mapping) and existing_git.get("status") == "completed":
            result = existing_git.get("result", {})
            stable_commit = str(result.get("target_after", source_commit))
            stable_tree = str(result.get("result_tree", source_tree))
            remote_stable = self.git.remote_head(self.git.stable_branch)
            local_stable = self.git.resolve_commit(
                f"refs/heads/{self.git.stable_branch}"
            )
            if (
                not stable_commit
                or stable_tree != source_tree
                or remote_stable != stable_commit
                or local_stable != stable_commit
                or (
                    proposal is not None
                    and stable_tree != proposal.expected_result_tree
                )
            ):
                raise RecoveryError(
                    "completed stable promotion does not match observed refs/tree"
                )
        else:
            if isinstance(existing_git, Mapping) and existing_git.get("status") != "not_started":
                return self._wait(run, "stable_promotion_operation_reconciliation")
            if proposal is None or proposal_record is None:
                raise RecoveryError("stable promotion lacks its reviewed proposal")
            if proposal.target_commit != stable_before:
                return self._merge_review_attention(
                    run,
                    review_scope="dev-to-stable",
                    route="dev_to_stable",
                    protected_operation_id=git_operation,
                    source_ref=f"refs/heads/{self.git.integration_branch}",
                    target_branch=self.git.stable_branch,
                    attempt_id=(
                        f"ATTEMPT-runtime-{self.identity}-dev-to-stable-001"
                    ),
                    error=GitPolicyError("stable moved after merge review"),
                )
            if existing_git is None:
                self.reducer.start_operation(
                    run_id=self.run_id,
                    expected_revision=self._revision(),
                    operation_id=git_operation,
                    action_id="release",
                    operation_kind="protected_ref",
                    idempotency_key=git_operation,
                    authorization_id=authorization_id,
                    gate_id=gate_id,
                    scope={
                        "protected_ref": self.git.stable_branch,
                        "source_commit": source_commit,
                        "target_commit": stable_before,
                        "release_source_kind": source_kind,
                        "release_source_commit": source_commit,
                        "release_source_tree": source_tree,
                        "hotfix_reconciliation_gate_id": reconciliation_gate_id,
                        "artifact_digest": artifact,
                        "merge_proposal": proposal_record["merge_proposal"],
                        "merge_proposal_digest": sha256_bytes(
                            canonical_json(proposal_record["merge_proposal"])
                        ),
                        "reviewed_proposal_digest": proposal_record[
                            "reviewed_proposal_digest"
                        ],
                        "gate_id": gate_id,
                    },
                )
            else:
                self.reducer.restart_operation(
                    run_id=self.run_id,
                    expected_revision=self._revision(),
                    operation_id=git_operation,
                    authorization_id=authorization_id,
                    grant_revision=grant_revision,
                    idempotency_key=(
                        f"configured-runtime:restart:{git_operation}:"
                        f"{self._revision()}"
                    ),
                )
            stable_receipt = self.git.execute_proposal(
                proposal, require_source_tree_result=True
            )
            stable_push = self.git.push_protected_cas(
                self.git.stable_branch,
                expected_remote=stable_receipt.target_before,
                new_commit=stable_receipt.target_after,
                proposal=proposal,
            )
            self.reducer.record_operation_observation(
                OperationObservation(
                    operation_id=git_operation,
                    action_id="release",
                    status="succeeded",
                    effect_id=f"git-stable-{stable_receipt.target_after}",
                    result={
                        "target_after": stable_receipt.target_after,
                        "result_tree": stable_receipt.result_tree,
                        "remote_after": stable_push.observed_after,
                        "reviewed_proposal_digest": proposal_record[
                            "reviewed_proposal_digest"
                        ],
                    },
                ),
                run_id=self.run_id,
                expected_revision=self._revision(),
                idempotency_key=f"configured-runtime:observe:{git_operation}",
                actor="nm-v6-configured-runtime",
            )
            stable_commit = stable_receipt.target_after
            stable_tree = stable_receipt.result_tree
            remote_stable = stable_push.observed_after
        if source_kind == "dev":
            assert proposal is not None
            self._record_domain_once(
                "PROTECTED_REF_PUSHED",
                {
                    "operation_id": git_operation,
                    "branch": self.git.stable_branch,
                    "before": proposal.target_commit,
                    "after": stable_commit,
                    "observed_after": remote_stable,
                },
                idempotency_key=(
                    f"configured-runtime:protected-push:{git_operation}"
                ),
            )
        release_operation = self._reconcile_operation(self._id("OP", 603))
        publish_operation = self._reconcile_operation(self._id("OP", 604))
        for operation, name in (
            (release_operation, "release"),
            (publish_operation, "publish"),
        ):
            if isinstance(operation, Mapping) and operation.get("status") not in {
                "completed",
                "not_started",
            }:
                return self._wait(run, f"{name}_operation_reconciliation")
        manager, workspace, root = self._operation_workspace(
            release_operation or publish_operation,
            commit=source_commit,
            label="release",
            allow_completed_rebuild=all(
                isinstance(operation, Mapping)
                and operation.get("status") == "completed"
                for operation in (release_operation, publish_operation)
            ),
        )
        try:
            executor = ActionExecutor(
                isolation_backend=manager.isolation_backend,
                secret_resolver=_ProjectSecretResolver(self.target, self.project),
            )
            recorder = ReducerOperationRecorder(
                self.reducer,
                self.store,
                run_id=self.run_id,
                expected_revision=lambda: self._revision(),
                scope={
                    "protected_ref": self.git.stable_branch,
                    "source_commit": source_commit,
                    "target_commit": stable_before,
                    "release_source_kind": source_kind,
                    "release_source_commit": source_commit,
                    "release_source_tree": source_tree,
                    "hotfix_reconciliation_gate_id": reconciliation_gate_id,
                    "artifact_digest": artifact,
                    "gate_id": gate_id,
                    "workspace_path": str(workspace.path),
                    "workspace_root": str(root),
                    "workspace_id": workspace.workspace_id,
                },
            )
            recovery = RecoveryController(self.definitions, executor, recorder)
            delivery = DeliveryController(
                self.definitions, executor, recovery, git=self.git
            )
            build = delivery.build(
                workspace=workspace,
                action_id=str(self.project["actions"]["build"]),
                source_commit=source_commit,
            )
            if build.artifact_digest != artifact:
                raise RecoveryError("release replay build substituted the gated artifact")
            common_env = {
                "NM_V6_SPEC_HASH": str(run["spec_hash"]),
                "NM_V6_CONFIG_HASH": str(run["config_hash"]),
                "NM_V6_RELEASE_SOURCE_KIND": source_kind,
                "NM_V6_RELEASE_SOURCE_COMMIT": source_commit,
                "NM_V6_RELEASE_SOURCE_TREE": source_tree,
                "NM_V6_ARTIFACT_DIGEST": artifact,
                "NM_V6_STABLE_COMMIT": stable_commit,
                "NM_V6_STABLE_TREE": stable_tree,
                "NM_V6_RELEASE_TAG": str(payload["runtime_release_tag"]),
                "NM_V6_RELEASE_VERSION": str(
                    payload["runtime_release_version"]
                ),
                "NM_V6_RELEASE_METADATA_DIGEST": str(
                    payload["runtime_release_metadata_digest"]
                ),
            }
            normalized: dict[str, Mapping[str, Any]] = {}
            effect_ids: dict[str, str] = {}
            for name, operation_id, existing in (
                ("release", self._id("OP", 603), release_operation),
                ("publish", self._id("OP", 604), publish_operation),
            ):
                if isinstance(existing, Mapping) and existing.get("status") == "completed":
                    observed = existing.get("result", {})
                else:
                    _, observation = delivery._mutate_and_observe(
                        str(self.project["actions"][name]),
                        workspace=workspace,
                        operation_id=operation_id,
                        grant_id=authorization_id,
                        grant_revision=grant_revision,
                        core_env=common_env,
                    )
                    observed = observation.observation.as_dict()
                if not isinstance(observed, Mapping):
                    raise RecoveryError(f"completed {name} lacks canonical observation")
                state = observed.get("observed_state", {})
                if not isinstance(state, Mapping) or state.get("classification") != "completed":
                    raise RecoveryError(f"{name} observation is not completed")
                if state.get("artifact_digest") != artifact and observed.get("artifact_digest") != artifact:
                    raise RecoveryError(f"{name} observation substituted artifact")
                normalized[name] = {
                    field: observed[field]
                    for field in (
                        "protocol_version",
                        "action_id",
                        "operation_id",
                        "status",
                        "effect_id",
                        "artifact_digest",
                        "environment_id",
                        "environment_fingerprint",
                        "observed_state",
                        "started_at",
                        "finished_at",
                        "diagnostics",
                        "redactions",
                    )
                    if field in observed
                }
            release_source = ReleaseSource(
                source_kind,
                source_commit,
                source_tree,
                str(run["spec_hash"]),
                str(run["config_hash"]),
                reconciliation_gate_id,
            )
            if source_kind == "hotfix_stable":
                reconciliation = self.store.get_gate(str(reconciliation_gate_id))
                if not isinstance(reconciliation, Mapping):
                    raise RecoveryError(
                        "hotfix release reconciliation result disappeared"
                    )
                DeliveryController._verify_hotfix_reconciliation(
                    release_source, decision=reconciliation
                )
                if (
                    reconciliation.get("candidate_commit")
                    != payload.get("runtime_hotfix_dev_result_commit")
                    or reconciliation.get("target_commit")
                    != payload.get("runtime_hotfix_dev_before")
                ):
                    raise RecoveryError(
                        "hotfix reconciliation result changed before publication"
                    )
            else:
                DeliveryController._verify_hotfix_reconciliation(
                    release_source, decision=None
                )
            for name, operation_id in (
                ("release", self._id("OP", 603)),
                ("publish", self._id("OP", 604)),
            ):
                mutation_definition = self.definitions[
                    str(self.project["actions"][name])
                ]
                observe_id = mutation_definition.observe_action_id
                if not isinstance(observe_id, str):
                    raise RecoveryError(f"{name} lacks its observe action")
                observed_result = ActionResult.from_mapping(
                    normalized[name],
                    definition=self.definitions[observe_id],
                    operation_id=operation_id,
                )
                persisted_operation = self.store.get_operation(operation_id)
                effect_id = (
                    str(persisted_operation.get("effect_id", ""))
                    if isinstance(persisted_operation, Mapping)
                    else ""
                )
                if not effect_id:
                    raise RecoveryError(f"{name} lacks its persisted provider effect ID")
                effect_ids[name] = effect_id
                delivery._require_release_binding(
                    observed_result,
                    source=release_source,
                    stable_commit=stable_commit,
                    stable_tree=stable_tree,
                    artifact_digest=artifact,
                    effect_id=effect_id,
                    action=f"{name} observation",
                    release_tag=str(payload["runtime_release_tag"]),
                    published_version=str(payload["runtime_release_version"]),
                    release_metadata_digest=str(
                        payload["runtime_release_metadata_digest"]
                    ),
                )
            publish_state = normalized["publish"].get("observed_state", {})
            published_artifact = str(
                normalized["publish"].get("artifact_digest")
                or publish_state.get("artifact_digest", "")
            )
            published_tag = str(publish_state.get("tag", ""))
            published_version = str(publish_state.get("published_version", ""))
            tag_target = str(publish_state.get("tag_target", ""))
            delivery._publication_identity(
                ActionResult.from_mapping(
                    normalized["publish"],
                    definition=self.definitions[
                        str(
                            self.definitions[
                                str(self.project["actions"]["publish"])
                            ].observe_action_id
                        )
                    ],
                    operation_id=self._id("OP", 604),
                ),
                mutation=ActionResult.from_mapping(
                    normalized["publish"],
                    definition=self.definitions[
                        str(
                            self.definitions[
                                str(self.project["actions"]["publish"])
                            ].observe_action_id
                        )
                    ],
                    operation_id=self._id("OP", 604),
                ),
                stable_commit=stable_commit,
                expected_tag=str(payload["runtime_release_tag"]),
                expected_version=str(payload["runtime_release_version"]),
            )
            partial_reconciled = True
        except BaseException:
            # Preserve the Operation-bound standalone workspace so a later
            # invocation can re-observe provider state without core-owned
            # provider fixtures or a blind mutation retry.
            raise
        checkpoint("runtime.after_release_publish")
        assertions = {
            "stable_ref_observed": remote_stable == stable_commit,
            "source_binding_observed": bool(
                source_kind in {"dev", "hotfix_stable"}
                and source_commit
                and source_tree
            ),
            "tag_observed": published_tag == payload["runtime_release_tag"],
            "tag_target_matches_stable": tag_target == stable_commit,
            "published_release_observed": (
                published_version == payload["runtime_release_version"]
                and tag_target == stable_commit
            ),
            "release_metadata_matches": (
                publish_state.get("release_metadata_digest")
                == payload["runtime_release_metadata_digest"]
            ),
            "release_effect_observed": bool(effect_ids.get("release")),
            "publish_effect_observed": bool(effect_ids.get("publish")),
            "artifact_digest_matches": published_artifact == artifact,
            "partial_unknown_reconciled": partial_reconciled,
        }
        evidence_id = self._evidence(
            610,
            "release-result",
            {
                "stable_commit": stable_commit,
                "stable_tree": stable_tree,
                "tag": published_tag,
                "tag_target": tag_target,
                "published_version": published_version,
                "artifact_digest": published_artifact,
                "release_source_kind": source_kind,
                "release_source_commit": source_commit,
                "release_source_tree": source_tree,
                "release_metadata_digest": payload[
                    "runtime_release_metadata_digest"
                ],
                "release_operation_id": self._id("OP", 603),
                "release_effect_id": effect_ids["release"],
                "publish_operation_id": self._id("OP", 604),
                "publish_effect_id": effect_ids["publish"],
            },
            assertions=assertions,
            source_commit=source_commit,
            candidate_commit=stable_commit,
            release_source_kind=source_kind,
            release_source_commit=source_commit,
            release_source_tree=source_tree,
            hotfix_reconciliation_gate_id=reconciliation_gate_id,
            artifact_digest=artifact,
            subject_ids=("release-result",),
        )
        result_gate = self._gate(
            "RELEASE_RESULT_GATE",
            (evidence_id,),
            bindings={
                "source_commit": source_commit,
                "candidate_commit": stable_commit,
                "release_source_kind": source_kind,
                "release_source_commit": source_commit,
                "release_source_tree": source_tree,
                "hotfix_reconciliation_gate_id": reconciliation_gate_id,
                "artifact_digest": artifact,
            },
        )
        self._dispose_workspace(manager, workspace, root)
        cleanup_evidence: str | None = None
        cleanup_provenance_digest: str | None = None
        if source_kind == "dev":
            receipt_id, integration_receipt = self._protected_integration_receipt(
                git_operation
            )
            cleanup_scope = "cleanup-dev-to-stable"
            cleanup_evidence = self._cleanup_responsibility_evidence(
                review_scope=cleanup_scope,
                branch=self.git.integration_branch,
                head=source_commit,
                assertions={
                    "review_responsibility_closed": True,
                    "backup_retention_absent": True,
                    "dependent_work_closed": True,
                    "release_responsibility_closed": True,
                    "rollback_responsibility_closed": False,
                    "audit_retention_absent": True,
                    "explicit_retention_absent": True,
                },
                observation={
                    "stage": "RELEASE_RESULT_GATE",
                    "gate_id": result_gate,
                    "operation_id": git_operation,
                    "branch": self.git.integration_branch,
                    "branch_head": source_commit,
                    "stable_result": stable_commit,
                },
            )
            cleanup_review = self._drive_cleanup_review(
                run,
                review_scope=cleanup_scope,
                branch=self.git.integration_branch,
                target_branch=self.git.stable_branch,
                receipt_id=receipt_id,
                integration_receipt=integration_receipt,
            )
            if cleanup_review is None:
                return True
            if cleanup_review[0].result != "retain":
                raise RecoveryError("protected dev branch cleanup was not retained")
            cleanup_provenance_digest = cleanup_review[1]["provenance_digest"]
        transitioned = self._transition(
            run,
            "RELEASE_OBSERVED",
            state_patch={
                "runtime_release_result_gate": result_gate,
                "runtime_stable_commit": stable_commit,
                "runtime_stable_tree": stable_tree,
                "runtime_published_artifact": published_artifact,
                "runtime_published_version": published_version,
                "runtime_release_tag_target": tag_target,
                "runtime_release_effect_id": effect_ids["release"],
                "runtime_publish_effect_id": effect_ids["publish"],
                "runtime_release_result": "passed",
                "runtime_dev_stable_cleanup_evidence": cleanup_evidence,
                "runtime_dev_stable_cleanup_provenance_digest": (
                    cleanup_provenance_digest
                ),
            },
            gate_ids=(result_gate,),
        )
        return transitioned

    # -- Deployment, completion, and rollback ----------------------------

    def _configured_environment(
        self, index: int
    ) -> tuple[str, Mapping[str, Any]]:
        _release, deploy, ordered = self._delivery_contract()
        if deploy != "required" or not 0 <= index < len(ordered):
            raise ContractError("delivery environment index is outside canonical order")
        name = ordered[index]
        value = self.project["delivery"]["environments"][name]
        if not isinstance(value, Mapping):
            raise ContractError("configured delivery environment is malformed")
        return str(name), value

    @staticmethod
    def _environment_target(
        environment_id: str,
        config: Mapping[str, Any],
        *,
        fingerprint: str | None,
    ) -> EnvironmentTarget:
        expected_identity = str(config["expected_identity"])
        return EnvironmentTarget(
            environment_id=environment_id,
            expected_identity=expected_identity,
            expected_fingerprint=fingerprint,
            identity_probe_action=str(config["identity_probe"]),
            preflight_action=str(config["preflight"]),
            deploy_action=str(config["deploy"]),
            health_action=str(config["health"]),
            rollback_action=str(config["rollback"]),
            post_rollback_verify_action=str(config["post_rollback_verify"]),
        )

    def _completion_gate(
        self,
        payload: Mapping[str, Any],
        *,
        deployment_resolved: bool,
        no_rollback_responsibility: bool,
        completed_environments: Sequence[Mapping[str, Any]],
        terminal_evidence_id: str,
        terminal_resolution: Mapping[str, Any],
    ) -> str:
        from .specs import validate_traceability

        mandatory = list(
            validate_traceability(self.traceability).mandatory_acceptance_ids
        )
        original_acceptance = self._mandatory_acceptance_evidence("completion")
        if tuple(original_acceptance) != tuple(mandatory):
            raise RecoveryError(
                "Completion mandatory Acceptance evidence is not canonical"
            )
        acceptance_evidence = {
            acceptance_id: list(original_acceptance[acceptance_id])
            for acceptance_id in mandatory
        }
        expected_phase_ids = {str(item["id"]) for item in self._phases()}
        phase_states = {
            phase_id: self.store.get_entity_state(
                "phase", self._entity_id(phase_id)
            )
            for phase_id in expected_phase_ids
        }
        task_states = [
            self.store.get_entity_state(
                "task", self._entity_id(str(task["id"]))
            )
            for task in self._tasks()
        ]
        release_decision, _deploy_decision, _ordered = self._delivery_contract()
        release_resolved = (
            payload.get("runtime_release_decision") == "not_applicable"
            if release_decision == "not_applicable"
            else (
                payload.get("runtime_release_decision") == "required"
                and payload.get("runtime_release_result") == "passed"
                and bool(payload.get("runtime_published_version"))
            )
        )
        completion_assertions = {
            "mandatory_acceptance_complete": len(acceptance_evidence)
            == len(mandatory),
            "all_phases_integrated": set(
                payload.get("runtime_completed_phases", [])
            )
            == expected_phase_ids
            and all(
                isinstance(state, Mapping) and state.get("state") == "INTEGRATED"
                for state in phase_states.values()
            ),
            "release_resolved": release_resolved,
            "deployment_resolved": deployment_resolved,
            "no_mandatory_work_remaining": len(task_states) == len(self._tasks())
            and all(
                isinstance(state, Mapping)
                and state.get("state") in {"INTEGRATED", "SKIPPED"}
                for state in task_states
            ),
            "no_rollback_responsibility": no_rollback_responsibility,
            "branch_cleanup_resolved": bool(
                terminal_resolution.get("cleanup_result")
                in {"deleted", "retain"}
            ),
            "terminal_resources_closed": not any(
                terminal_resolution.get("resources", {}).get(field, [])
                for field in (
                    "live_lease_ids",
                    "active_attempt_ids",
                    "live_session_ids",
                    "live_workspace_paths",
                    "nonterminal_operation_ids",
                    "missing_cleanup_scopes",
                )
            ),
            "no_remote_cleanup_effect": not any(
                terminal_resolution.get("resources", {}).get(field, [])
                for field in (
                    "remote_cleanup_operation_ids",
                    "remote_delete_authorization_consumptions",
                )
            ),
        }
        completion_evidence = self._evidence(
            800,
            "completion",
            {
                "mandatory_acceptance": mandatory,
                "prior_acceptance_evidence": acceptance_evidence,
                "completed_phases": payload.get("runtime_completed_phases", []),
                "delivery_contract": self.traceability[
                    "required_delivery_stages"
                ],
                "completed_environments": [
                    dict(item) for item in completed_environments
                ],
                "terminal_resolution": dict(terminal_resolution),
            },
            assertions=completion_assertions,
            subject_ids=("completion",),
        )
        original_evidence_ids = tuple(
            dict.fromkeys(
                evidence_id
                for acceptance_id in mandatory
                for evidence_id in acceptance_evidence[acceptance_id]
            )
        )
        return self._gate(
            "COMPLETION_GATE",
            (completion_evidence, terminal_evidence_id, *original_evidence_ids),
            mandatory_acceptance_ids=mandatory,
            acceptance_evidence=acceptance_evidence,
        )

    def _skip_deploy_not_applicable(self, run: Mapping[str, Any]) -> bool:
        _release, deploy, environments = self._delivery_contract()
        assertions = {
            "spec_explicitly_not_applicable": deploy == "not_applicable",
            "stage_traceability_valid": not environments,
            "not_applicable_decision_valid": (
                deploy == "not_applicable" and not environments
            ),
        }
        evidence_id = self._evidence(
            700,
            "deploy-not-applicable",
            {
                "decision": deploy,
                "environments": list(environments),
                "traceability_digest": sha256_bytes(
                    canonical_json(self.traceability)
                ),
            },
            assertions=assertions,
            subject_ids=("delivery:deploy",),
        )
        deploy_gate = self._gate(
            "DEPLOY_GATE",
            (evidence_id,),
            not_applicable=True,
        )
        payload = {
            **self._payload(self._current()),
            "runtime_deploy_decision": "not_applicable",
            "runtime_delivery_order": [],
            "runtime_delivery_completed": [],
        }
        terminal_evidence, terminal_resolution = self._final_branch_cleanup(
            run,
            terminal_stage="completion",
            terminal_observation={
                "deployment_decision": "not_applicable",
                "deploy_gate_id": deploy_gate,
            },
        )
        completion_gate = self._completion_gate(
            payload,
            deployment_resolved=True,
            no_rollback_responsibility=True,
            completed_environments=(),
            terminal_evidence_id=terminal_evidence,
            terminal_resolution=terminal_resolution,
        )
        return self._transition(
            run,
            "SKIP_DEPLOY_NOT_APPLICABLE",
            payload={"deploy_not_applicable": True},
            state_patch={
                "runtime_deploy_decision": "not_applicable",
                "runtime_deploy_gate": deploy_gate,
                "runtime_delivery_order": [],
                "runtime_delivery_completed": [],
                "runtime_terminal_resolution": terminal_resolution,
            },
            gate_ids=(deploy_gate, completion_gate),
        )


    def _prepare_deployment(self, run: Mapping[str, Any]) -> bool:
        _release_decision, deploy_decision, ordered = self._delivery_contract()
        if deploy_decision == "not_applicable":
            return self._skip_deploy_not_applicable(run)
        payload = self._payload(run)
        completed = payload.get("runtime_delivery_completed", [])
        if not isinstance(completed, list):
            raise RecoveryError("persisted delivery completion records are malformed")
        index = len(completed)
        if index >= len(ordered):
            raise RecoveryError("deployment has no remaining canonical environment")
        logical_name, environment = self._configured_environment(index)
        scope = self._environment_scope(index)
        expected_identity = str(environment["expected_identity"])
        authorization = self._authorization(
            "deploy", environment=expected_identity
        )
        if authorization is None:
            return self._wait(run, "trusted_deploy_authorization")
        authorization_id = self._authorization_id(authorization)
        artifact = str(payload.get("runtime_published_artifact", ""))
        stable_commit = str(payload.get("runtime_stable_commit", ""))
        if not artifact or not stable_commit:
            raise ContractError("deployment lacks a published immutable artifact")
        manager, workspace, root = self._workspace(
            stable_commit, "deploy-readiness"
        )
        try:
            executor = ActionExecutor(
                isolation_backend=manager.isolation_backend,
                secret_resolver=_ProjectSecretResolver(self.target, self.project),
            )
            target = self._environment_target(
                expected_identity, environment, fingerprint=None
            )
            delivery = DeliveryController(
                self.definitions,
                executor,
                RecoveryController(
                    self.definitions,
                    executor,
                    ReducerOperationRecorder(
                        self.reducer,
                        self.store,
                        run_id=self.run_id,
                        expected_revision=lambda: self._revision(),
                    ),
                ),
            )
            identity = delivery.observe_environment(
                workspace=workspace, target=target
            )
            identity_matches = (
                identity.status == "succeeded"
                and identity.environment_id == expected_identity
                and bool(identity.environment_fingerprint)
            )
            preflight = (
                self._execute(
                    executor,
                    workspace,
                    str(environment["preflight"]),
                    allow_network=True,
                )
                if identity_matches
                else None
            )
        finally:
            self._dispose_workspace(manager, workspace, root)
        if not identity_matches:
            mismatch_scope = (
                f"{scope}-probe-{self._revision():06d}"
            )
            mismatch_evidence = self._evidence(
                699,
                "environment-identity-mismatch",
                {
                    "logical_environment": logical_name,
                    "expected_identity": expected_identity,
                    "observation": identity.as_dict(),
                },
                assertions={
                    "identity_probe_succeeded": identity.status == "succeeded",
                    "configured_identity_matches": (
                        identity.environment_id == expected_identity
                    ),
                    "fingerprint_present": bool(identity.environment_fingerprint),
                },
                artifact_digest=artifact,
                environment_id=(
                    identity.environment_id
                    if identity.environment_id and identity.environment_fingerprint
                    else None
                ),
                environment_fingerprint=(
                    identity.environment_fingerprint
                    if identity.environment_id and identity.environment_fingerprint
                    else None
                ),
                subject_ids=("environment-mismatch", logical_name),
                scope=mismatch_scope,
            )
            return self._delivery_attention(
                run,
                reason="observed environment identity differs from configured and authorized target",
                required_decision="correct_environment_identity_or_authorization",
                observations={
                    "logical_environment": logical_name,
                    "expected_identity": expected_identity,
                    "observed": identity.as_dict(),
                },
                evidence_ids=(mismatch_evidence,),
                external_operations_reconciled=True,
                state_patch={
                    "runtime_environment_index": index,
                    "runtime_environment_key": logical_name,
                },
            )
        assert preflight is not None
        fingerprint = str(identity.environment_fingerprint or "")
        previous_version = str(identity.observed_state.get("deployed_version", ""))
        deploy_definition = self.definitions[str(environment["deploy"])]
        deploy_acceptance = self._mandatory_acceptance_evidence("deploy")
        deploy_acceptance_ids = tuple(
            dict.fromkeys(
                evidence_id
                for evidence_ids in deploy_acceptance.values()
                for evidence_id in evidence_ids
            )
        )
        assertions = {
            "deploy_acceptance_covered": all(deploy_acceptance.values()),
            "artifact_fixed": bool(artifact),
            "environment_confirmed": (
                identity.environment_id == expected_identity and bool(fingerprint)
            ),
            "credentials_are_references": bool(deploy_definition.secret_refs),
            "preflight_passed": preflight.status == "succeeded",
            "idempotency_present": deploy_definition.idempotency.mode
            == "required",
            "observe_reconcile_ready": bool(
                deploy_definition.observe_action_id
                and deploy_definition.reconcile_action_id
            ),
            "rollback_ready": bool(
                previous_version
                and environment.get("rollback")
                and environment.get("post_rollback_verify")
            ),
        }
        evidence_id = self._evidence(
            700,
            "deployment-readiness",
            {
                "logical_environment": logical_name,
                "identity": identity.as_dict(),
                "preflight": preflight.as_dict(),
                "previous_version": previous_version,
            },
            assertions=assertions,
            artifact_digest=artifact,
            environment_id=expected_identity,
            environment_fingerprint=fingerprint,
            subject_ids=("deploy", logical_name, expected_identity),
            scope=scope,
        )
        deploy_gate = self._gate(
            "DEPLOY_GATE",
            (evidence_id, *deploy_acceptance_ids),
            authorization_id=authorization_id,
            bindings={
                "artifact_digest": artifact,
                "environment_id": expected_identity,
                "environment_fingerprint": fingerprint,
            },
            scope=scope,
        )
        return self._transition(
            run,
            "START_DEPLOYMENT",
            payload={
                "deploy_required": True,
                "environment_id": expected_identity,
                "environment_index": index,
                "environment_key": logical_name,
            },
            state_patch={
                "runtime_deploy_gate": deploy_gate,
                "runtime_deploy_authorization": authorization_id,
                "runtime_deploy_grant_revision": int(
                    authorization["grant_revision"]
                ),
                "runtime_environment_key": logical_name,
                "runtime_environment_index": index,
                "runtime_environment_id": expected_identity,
                "runtime_environment_fingerprint": fingerprint,
                "runtime_rollback_target": previous_version,
                "runtime_delivery_order": list(ordered),
                "runtime_delivery_completed": list(completed),
                "runtime_deploy_decision": "required",
            },
            gate_ids=(deploy_gate,),
            authorization_id=authorization_id,
        )

    def _deploy(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        environments = self.project["delivery"]["environments"]
        environment = environments[str(payload["runtime_environment_key"])]
        environment_id = str(payload["runtime_environment_id"])
        fingerprint = str(payload["runtime_environment_fingerprint"])
        artifact = str(payload["runtime_published_artifact"])
        gate_id = str(payload["runtime_deploy_gate"])
        authorization_id = str(payload["runtime_deploy_authorization"])
        grant_revision = int(payload["runtime_deploy_grant_revision"])
        stable_commit = str(payload["runtime_stable_commit"])
        environment_index = int(payload["runtime_environment_index"])
        scope = self._environment_scope(environment_index)
        operation_id = self._id("OP", 703, scope=scope)
        existing = self._reconcile_operation(operation_id)
        if isinstance(existing, Mapping) and existing.get("status") == "completed":
            health_record = next(
                (
                    event.get("payload", {}).get("record")
                    for event in self.store.list_events(run_id=self.run_id)
                    if event.get("idempotency_key")
                    == f"configured-runtime:health:{operation_id}"
                ),
                None,
            )
            if isinstance(health_record, Mapping):
                patch = dict(health_record["state_patch"])
                event = (
                    "DEPLOYMENT_OBSERVED"
                    if patch.get("runtime_deploy_state") == "POST_DEPLOY_VERIFIED"
                    else "DEPLOYMENT_REQUIRES_ROLLBACK"
                )
                return self._transition(
                    run,
                    event,
                    payload=(
                        {}
                        if event == "DEPLOYMENT_OBSERVED"
                        else {"external_operations_reconciled": True}
                    ),
                    state_patch=patch,
                )
        if isinstance(existing, Mapping) and existing.get("status") not in {
            "completed",
            "not_started",
        }:
            return self._wait(run, "deploy_operation_reconciliation")
        manager, workspace, root = self._operation_workspace(
            existing,
            commit=stable_commit,
            label=f"deploy-{environment_index:03d}",
        )
        identity_mismatch: ActionResult | None = None
        deploy_observation: Mapping[str, Any] | None = None
        try:
            executor = ActionExecutor(
                isolation_backend=manager.isolation_backend,
                secret_resolver=_ProjectSecretResolver(self.target, self.project),
            )
            recorder = ReducerOperationRecorder(
                self.reducer,
                self.store,
                run_id=self.run_id,
                expected_revision=lambda: self._revision(),
                scope={
                    "environment_id": environment_id,
                    "environment_fingerprint": fingerprint,
                    "artifact_digest": artifact,
                    "gate_id": gate_id,
                    "source_commit": stable_commit,
                    "environment_key": str(payload["runtime_environment_key"]),
                    "environment_index": environment_index,
                    "workspace_path": str(workspace.path),
                    "workspace_root": str(root),
                    "workspace_id": workspace.workspace_id,
                },
            )
            recovery = RecoveryController(self.definitions, executor, recorder)
            target = self._environment_target(
                environment_id, environment, fingerprint=fingerprint
            )
            delivery = DeliveryController(self.definitions, executor, recovery)
            identity = delivery.observe_environment(
                workspace=workspace, target=target
            )
            if (
                identity.status != "succeeded"
                or identity.environment_id != environment_id
                or identity.environment_fingerprint != fingerprint
            ):
                identity_mismatch = identity
            if isinstance(existing, Mapping) and existing.get("status") == "completed":
                observed = existing.get("result", {})
                if not isinstance(observed, Mapping):
                    raise RecoveryError(
                        "completed deployment lacks canonical observation"
                    )
                observed_state = observed.get("observed_state", {})
                if (
                    observed.get("artifact_digest") != artifact
                    or observed.get("environment_id") != environment_id
                    or observed.get("environment_fingerprint") != fingerprint
                    or not isinstance(observed_state, Mapping)
                    or observed_state.get("classification") != "completed"
                ):
                    raise RecoveryError(
                        "completed deployment observation binding mismatch"
                    )
                deploy_observation = dict(observed)
            else:
                if identity_mismatch is None:
                    preflight = self._execute(
                        executor,
                        workspace,
                        str(environment["preflight"]),
                        allow_network=True,
                    )
                    if preflight.status != "succeeded":
                        raise RecoveryError("deployment preflight failed")
                    _, observed = delivery._mutate_and_observe(
                        str(environment["deploy"]),
                        workspace=workspace,
                        operation_id=operation_id,
                        grant_id=authorization_id,
                        grant_revision=grant_revision,
                        core_env={
                            "NM_V6_ARTIFACT_DIGEST": artifact,
                            "NM_V6_ENVIRONMENT_ID": environment_id,
                            "NM_V6_ENVIRONMENT_FINGERPRINT": fingerprint,
                        },
                    )
                    if (
                        observed.observation.artifact_digest != artifact
                        or observed.observation.environment_id != environment_id
                        or observed.observation.environment_fingerprint != fingerprint
                    ):
                        raise RecoveryError("deployment observation binding mismatch")
                    deploy_observation = observed.observation.as_dict()
            if identity_mismatch is not None:
                health = None
                healthy = False
            else:
                persisted_operation = self.store.get_operation(operation_id)
                deploy_effect_id = (
                    str(persisted_operation.get("effect_id", ""))
                    if isinstance(persisted_operation, Mapping)
                    else ""
                )
                observed_state = (
                    deploy_observation.get("observed_state", {})
                    if isinstance(deploy_observation, Mapping)
                    else {}
                )
                if (
                    not deploy_effect_id
                    or not isinstance(observed_state, Mapping)
                    or observed_state.get("effect_id") != deploy_effect_id
                ):
                    raise RecoveryError(
                        "deployment observation does not match persisted provider effect"
                    )
                checkpoint("runtime.after_deploy_observation")
                health = self._execute(
                    executor,
                    workspace,
                    str(environment["health"]),
                    allow_network=True,
                )
                healthy = (
                    health.observed_state.get("healthy") is True
                    and health.artifact_digest == artifact
                    and health.environment_id == environment_id
                    and health.environment_fingerprint == fingerprint
                )
        except BaseException:
            # The persisted workspace is part of the Operation recovery
            # context.  Keep it until health is durably recorded and the run
            # has advanced beyond DEPLOYING.
            raise
        if identity_mismatch is not None:
            self._dispose_workspace(manager, workspace, root)
            mismatch_evidence = self._evidence(
                699,
                "environment-identity-mismatch",
                {
                    "logical_environment": payload["runtime_environment_key"],
                    "expected_identity": environment_id,
                    "expected_fingerprint": fingerprint,
                    "observation": identity_mismatch.as_dict(),
                },
                assertions={
                    "identity_probe_succeeded": identity_mismatch.status
                    == "succeeded",
                    "authorized_identity_matches": identity_mismatch.environment_id
                    == environment_id,
                    "authorized_fingerprint_matches": (
                        identity_mismatch.environment_fingerprint == fingerprint
                    ),
                },
                artifact_digest=artifact,
                environment_id=(
                    identity_mismatch.environment_id
                    if identity_mismatch.environment_id
                    and identity_mismatch.environment_fingerprint
                    else None
                ),
                environment_fingerprint=(
                    identity_mismatch.environment_fingerprint
                    if identity_mismatch.environment_id
                    and identity_mismatch.environment_fingerprint
                    else None
                ),
                subject_ids=(
                    "environment-mismatch",
                    str(payload["runtime_environment_key"]),
                ),
                scope=f"{scope}-probe-{self._revision():06d}",
            )
            return self._delivery_attention(
                run,
                reason="deployment environment changed after DEPLOY_GATE",
                required_decision="restore_environment_identity_or_replan",
                observations={
                    "operation_id": operation_id,
                    "observed": identity_mismatch.as_dict(),
                },
                evidence_ids=(mismatch_evidence,),
                external_operations_reconciled=(
                    existing is None
                    or existing.get("status") in {"completed", "not_started"}
                ),
            )
        assert health is not None
        patch = {
            "runtime_deploy_operation": operation_id,
            "runtime_deploy_effect_id": deploy_effect_id,
            "runtime_deploy_state": (
                "POST_DEPLOY_VERIFIED" if healthy else "ATTENTION_REQUIRED"
            ),
            "runtime_deploy_previous_version": payload["runtime_rollback_target"],
            "runtime_deploy_health": health.as_dict(),
            "runtime_deploy_observed_artifact": artifact,
            "runtime_deploy_observation": dict(deploy_observation or {}),
        }
        self._record_domain_once(
            "HEALTH_OPERATION_RECORDED",
            {"operation_id": operation_id, "state_patch": patch},
            idempotency_key=f"configured-runtime:health:{operation_id}",
        )
        checkpoint("runtime.after_deploy_health_record")
        if healthy:
            transitioned = self._transition(
                run,
                "DEPLOYMENT_OBSERVED",
                state_patch=patch,
            )
        else:
            rollback_authorization = self._authorization(
                "rollback", environment=environment_id
            )
            if rollback_authorization is None:
                failure_evidence = self._evidence(
                    711,
                    "deployment-health-failure",
                    {
                        "operation_id": operation_id,
                        "effect_id": deploy_effect_id,
                        "health": health.as_dict(),
                    },
                    assertions={
                        "deployment_effect_reconciled": bool(deploy_effect_id),
                        "health_failure_observed": not healthy,
                    },
                    artifact_digest=artifact,
                    environment_id=environment_id,
                    environment_fingerprint=fingerprint,
                    operation_id=operation_id,
                    subject_ids=("deployment-failure",),
                    scope=scope,
                )
                self._dispose_workspace(manager, workspace, root)
                return self._delivery_attention(
                    run,
                    reason="post-deployment health failed without authorized rollback",
                    required_decision="authorize_exact_environment_rollback_or_recover",
                    observations={
                        "operation_id": operation_id,
                        "effect_id": deploy_effect_id,
                        "health": health.as_dict(),
                    },
                    evidence_ids=(failure_evidence,),
                    external_operations_reconciled=True,
                    state_patch=patch,
                )
            transitioned = self._transition(
                run,
                "DEPLOYMENT_REQUIRES_ROLLBACK",
                payload={"external_operations_reconciled": True},
                state_patch=patch,
            )
        self._dispose_workspace(manager, workspace, root)
        return transitioned

    def _complete(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        artifact = str(payload["runtime_published_artifact"])
        environment_id = str(payload["runtime_environment_id"])
        fingerprint = str(payload["runtime_environment_fingerprint"])
        environment_index = int(payload["runtime_environment_index"])
        scope = self._environment_scope(environment_index)
        logical_name = str(payload["runtime_environment_key"])
        health = payload.get("runtime_deploy_health", {})
        healthy = (
            isinstance(health, Mapping)
            and health.get("status") == "succeeded"
            and health.get("observed_state", {}).get("healthy") is True
            and health.get("artifact_digest") == artifact
            and health.get("environment_id") == environment_id
            and health.get("environment_fingerprint") == fingerprint
        )
        post_assertions = {
            "health_passed": healthy,
            "smoke_passed": healthy,
            "project_observations_passed": payload.get(
                "runtime_deploy_observed_artifact"
            )
            == artifact,
            "artifact_environment_binding_valid": bool(
                artifact and environment_id and fingerprint
            ),
        }
        post_evidence = self._evidence(
            710,
            "post-deployment",
            {
                "health": health,
                "artifact": artifact,
                "logical_environment": logical_name,
                "environment_index": environment_index,
                "deploy_operation_id": payload["runtime_deploy_operation"],
                "deploy_effect_id": payload["runtime_deploy_effect_id"],
                "deploy_observation": payload.get("runtime_deploy_observation"),
                "stable_commit": payload["runtime_stable_commit"],
            },
            assertions=post_assertions,
            artifact_digest=artifact,
            environment_id=environment_id,
            environment_fingerprint=fingerprint,
            operation_id=str(payload["runtime_deploy_operation"]),
            subject_ids=("post-deploy", logical_name),
            scope=scope,
        )
        post_gate = self._gate(
            "POST_DEPLOY_GATE",
            (post_evidence,),
            bindings={
                "artifact_digest": artifact,
                "environment_id": environment_id,
                "environment_fingerprint": fingerprint,
            },
            scope=scope,
        )
        completed = payload.get("runtime_delivery_completed", [])
        if not isinstance(completed, list) or len(completed) != environment_index:
            raise RecoveryError("delivery completion cursor is not canonical")
        completed = [
            *completed,
            {
                "logical_key": logical_name,
                "environment_index": environment_index,
                "environment_id": environment_id,
                "environment_fingerprint": fingerprint,
                "artifact_digest": artifact,
                "deploy_gate_id": payload["runtime_deploy_gate"],
                "deploy_operation_id": payload["runtime_deploy_operation"],
                "deploy_effect_id": payload["runtime_deploy_effect_id"],
                "post_deploy_gate_id": post_gate,
                "rollback_target": payload["runtime_rollback_target"],
            },
        ]
        _release, _deploy, ordered = self._delivery_contract()
        if len(completed) < len(ordered):
            return self._transition(
                run,
                "CONTINUE_DEPLOYMENT",
                payload={
                    "more_environments": True,
                    "next_environment_index": len(completed),
                },
                state_patch={
                    "runtime_delivery_completed": completed,
                    "runtime_environment_index": len(completed),
                },
                gate_ids=(post_gate,),
            )
        completion_payload = {
            **payload,
            "runtime_delivery_completed": completed,
        }
        terminal_evidence, terminal_resolution = self._final_branch_cleanup(
            run,
            terminal_stage="completion",
            terminal_observation={
                "post_deploy_gate_id": post_gate,
                "completed_environments": completed,
                "healthy": healthy,
            },
        )
        completion_gate = self._completion_gate(
            completion_payload,
            deployment_resolved=healthy and len(completed) == len(ordered),
            no_rollback_responsibility=healthy,
            completed_environments=completed,
            terminal_evidence_id=terminal_evidence,
            terminal_resolution=terminal_resolution,
        )
        return self._transition(
            run,
            "COMPLETE_RUN",
            state_patch={
                "runtime_delivery_completed": completed,
                "runtime_terminal_resolution": terminal_resolution,
            },
            gate_ids=(post_gate, completion_gate),
        )

    def _prepare_rollback(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        environment_id = str(payload["runtime_environment_id"])
        environment_index = int(payload["runtime_environment_index"])
        scope = self._environment_scope(environment_index)
        authorization = self._authorization(
            "rollback", environment=environment_id
        )
        if authorization is None:
            artifact = str(payload["runtime_published_artifact"])
            fingerprint = str(payload["runtime_environment_fingerprint"])
            evidence_id = self._evidence(
                719,
                "rollback-authorization-required",
                {
                    "deploy_operation_id": payload.get("runtime_deploy_operation"),
                    "deploy_effect_id": payload.get("runtime_deploy_effect_id"),
                    "health": payload.get("runtime_deploy_health"),
                },
                assertions={
                    "deployment_effect_reconciled": bool(
                        payload.get("runtime_deploy_effect_id")
                    ),
                    "rollback_authorization_absent": True,
                },
                artifact_digest=artifact,
                environment_id=environment_id,
                environment_fingerprint=fingerprint,
                operation_id=str(payload["runtime_deploy_operation"]),
                subject_ids=("rollback-authorization",),
                scope=scope,
            )
            return self._delivery_attention(
                run,
                reason="deployment requires rollback but no exact authorization exists",
                required_decision="authorize_exact_environment_rollback_or_recover",
                observations={
                    "deploy_operation_id": payload.get("runtime_deploy_operation"),
                    "deploy_effect_id": payload.get("runtime_deploy_effect_id"),
                    "health": payload.get("runtime_deploy_health"),
                },
                evidence_ids=(evidence_id,),
                external_operations_reconciled=True,
            )
        authorization_id = self._authorization_id(authorization)
        artifact = str(payload["runtime_published_artifact"])
        fingerprint = str(payload["runtime_environment_fingerprint"])
        assertions = {
            "rollback_target_exists": bool(payload.get("runtime_rollback_target")),
            "environment_confirmed": bool(environment_id and fingerprint),
            "rollback_action_available": bool(
                self.project["delivery"]["environments"][
                    payload["runtime_environment_key"]
                ].get("rollback")
            ),
            "post_rollback_verification_available": bool(
                self.project["delivery"]["environments"][
                    payload["runtime_environment_key"]
                ].get("post_rollback_verify")
            ),
        }
        evidence_id = self._evidence(
            720,
            "rollback-readiness",
            {
                "rollback_target": payload.get("runtime_rollback_target"),
                "deploy_health": payload.get("runtime_deploy_health"),
            },
            assertions=assertions,
            artifact_digest=artifact,
            environment_id=environment_id,
            environment_fingerprint=fingerprint,
            subject_ids=("rollback",),
            scope=scope,
        )
        gate_id = self._gate(
            "ROLLBACK_GATE",
            (evidence_id,),
            authorization_id=authorization_id,
            bindings={
                "artifact_digest": artifact,
                "environment_id": environment_id,
                "environment_fingerprint": fingerprint,
            },
            scope=scope,
        )
        return self._transition(
            run,
            "START_ROLLBACK",
            payload={
                "environment_id": environment_id,
                "environment_index": environment_index,
                "environment_key": payload["runtime_environment_key"],
            },
            state_patch={
                "runtime_rollback_gate": gate_id,
                "runtime_rollback_authorization": authorization_id,
                "runtime_rollback_grant_revision": int(
                    authorization["grant_revision"]
                ),
            },
            gate_ids=(gate_id,),
            authorization_id=authorization_id,
        )

    def _rollback(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        environment = self.project["delivery"]["environments"][
            str(payload["runtime_environment_key"])
        ]
        environment_id = str(payload["runtime_environment_id"])
        fingerprint = str(payload["runtime_environment_fingerprint"])
        artifact = str(payload["runtime_published_artifact"])
        gate_id = str(payload["runtime_rollback_gate"])
        authorization_id = str(payload["runtime_rollback_authorization"])
        environment_index = int(payload["runtime_environment_index"])
        scope = self._environment_scope(environment_index)
        operation_id = self._id("OP", 723, scope=scope)
        existing = self._reconcile_operation(operation_id)
        if isinstance(existing, Mapping) and existing.get("status") == "completed":
            recorded = next(
                (
                    event.get("payload", {}).get("record")
                    for event in self.store.list_events(run_id=self.run_id)
                    if event.get("idempotency_key")
                    == f"configured-runtime:rollback-result:{operation_id}"
                ),
                None,
            )
            if isinstance(recorded, Mapping):
                return self._transition(
                    run,
                    "ROLLBACK_OBSERVED",
                    state_patch=dict(recorded["state_patch"]),
                )
        if isinstance(existing, Mapping) and existing.get("status") not in {
            "completed",
            "not_started",
        }:
            failure_evidence = self._evidence(
                724,
                "rollback-operation-failure",
                {
                    "operation_id": operation_id,
                    "operation": dict(existing),
                },
                assertions={
                    "rollback_failure_observed": True,
                    "external_effect_reconciled": existing.get("status")
                    == "failed",
                },
                artifact_digest=artifact,
                environment_id=environment_id,
                environment_fingerprint=fingerprint,
                operation_id=operation_id,
                subject_ids=("rollback-failure",),
                scope=scope,
            )
            return self._delivery_attention(
                run,
                reason="rollback operation failed or remains ambiguous",
                required_decision="reconcile_or_recover_rollback_operation",
                observations={"operation": dict(existing)},
                evidence_ids=(failure_evidence,),
                external_operations_reconciled=existing.get("status") == "failed",
            )
        manager, workspace, root = self._operation_workspace(
            existing,
            commit=str(payload["runtime_stable_commit"]),
            label=f"rollback-{environment_index:03d}",
        )
        rollback_failure: ActionError | ContractError | RecoveryError | None = None
        rollback_observation: Mapping[str, Any] | None = None
        try:
            executor = ActionExecutor(
                isolation_backend=manager.isolation_backend,
                secret_resolver=_ProjectSecretResolver(self.target, self.project),
            )
            recorder = ReducerOperationRecorder(
                self.reducer,
                self.store,
                run_id=self.run_id,
                expected_revision=lambda: self._revision(),
                scope={
                    "environment_id": environment_id,
                    "environment_fingerprint": fingerprint,
                    "artifact_digest": artifact,
                    "gate_id": gate_id,
                    "source_commit": str(payload["runtime_stable_commit"]),
                    "environment_key": str(payload["runtime_environment_key"]),
                    "environment_index": environment_index,
                    "workspace_path": str(workspace.path),
                    "workspace_root": str(root),
                    "workspace_id": workspace.workspace_id,
                },
            )
            target = self._environment_target(
                environment_id, environment, fingerprint=fingerprint
            )
            if isinstance(existing, Mapping) and existing.get("status") == "completed":
                delivery = DeliveryController(
                    self.definitions,
                    executor,
                    RecoveryController(self.definitions, executor, recorder),
                )
                identity = delivery.observe_environment(
                    workspace=workspace, target=target
                )
                if (
                    identity.status != "succeeded"
                    or identity.environment_id != environment_id
                    or identity.environment_fingerprint != fingerprint
                ):
                    raise RecoveryError(
                        "rollback environment changed after ROLLBACK_GATE"
                    )
                observed = existing.get("result", {})
                observed_state = (
                    observed.get("observed_state", {})
                    if isinstance(observed, Mapping)
                    else {}
                )
                if (
                    not isinstance(observed_state, Mapping)
                    or observed_state.get("classification") != "completed"
                    or observed.get("environment_id") != environment_id
                    or observed.get("environment_fingerprint") != fingerprint
                ):
                    raise RecoveryError(
                        "completed rollback observation binding mismatch"
                    )
                rollback_observation = dict(observed)
                verification = self._execute(
                    executor,
                    workspace,
                    str(environment["post_rollback_verify"]),
                    allow_network=True,
                )
                rollback_state = (
                    "ROLLED_BACK"
                    if verification.observed_state.get("healthy") is True
                    and verification.observed_state.get("deployed_version")
                    == payload["runtime_rollback_target"]
                    and verification.environment_id == environment_id
                    and verification.environment_fingerprint
                    == identity.environment_fingerprint
                else "ATTENTION_REQUIRED"
                )
                rollback_target = str(payload["runtime_rollback_target"])
            else:
                receipt = DeliveryController(
                    self.definitions,
                    executor,
                    RecoveryController(self.definitions, executor, recorder),
                ).rollback(
                    workspace=workspace,
                    target=target,
                    rollback_target=str(payload["runtime_rollback_target"]),
                    operation_id=operation_id,
                    grant_id=authorization_id,
                    grant_revision=int(payload["runtime_rollback_grant_revision"]),
                )
                verification = receipt.verification
                rollback_state = receipt.state
                rollback_target = receipt.rollback_target
                rollback_observation = receipt.rollback_observation.observation.as_dict()
            checkpoint("runtime.after_rollback_observation")
        except (ActionError, ContractError, RecoveryError) as exc:
            rollback_failure = exc
        if rollback_failure is not None:
            current_operation = self.store.get_operation(operation_id)
            classification = (
                str(current_operation.get("status", "unknown"))
                if isinstance(current_operation, Mapping)
                else "not_started"
            )
            failure_evidence = self._evidence(
                724,
                "rollback-operation-failure",
                {
                    "operation_id": operation_id,
                    "classification": classification,
                    "operation": (
                        dict(current_operation)
                        if isinstance(current_operation, Mapping)
                        else None
                    ),
                    "error": str(rollback_failure),
                },
                assertions={
                    "rollback_failure_observed": True,
                    "external_effect_reconciled": classification
                    in {"completed", "failed", "not_started"},
                },
                artifact_digest=artifact,
                environment_id=environment_id,
                environment_fingerprint=fingerprint,
                operation_id=operation_id,
                subject_ids=("rollback-failure",),
                scope=scope,
            )
            if classification in {"completed", "failed", "not_started"}:
                self._dispose_workspace(manager, workspace, root)
            return self._delivery_attention(
                run,
                reason="rollback failed deterministic validation or reconciliation",
                required_decision="inspect_rollback_observation_and_recover",
                observations={
                    "operation_id": operation_id,
                    "classification": classification,
                    "error": str(rollback_failure),
                },
                evidence_ids=(failure_evidence,),
                external_operations_reconciled=classification
                in {"completed", "failed", "not_started"},
            )
        current_operation = self.store.get_operation(operation_id)
        rollback_effect_id = (
            str(current_operation.get("effect_id", ""))
            if isinstance(current_operation, Mapping)
            else ""
        )
        observed_state = (
            rollback_observation.get("observed_state", {})
            if isinstance(rollback_observation, Mapping)
            else {}
        )
        if (
            not rollback_effect_id
            or not isinstance(observed_state, Mapping)
            or observed_state.get("effect_id") != rollback_effect_id
        ):
            raise RecoveryError(
                "rollback observation does not match persisted provider effect"
            )
        rollback_evidence = self._evidence(
            725,
            "rollback-result",
            {
                "operation_id": operation_id,
                "effect_id": rollback_effect_id,
                "rollback_target": rollback_target,
                "observation": dict(rollback_observation or {}),
                "verification": verification.as_dict(),
            },
            assertions={
                "rollback_operation_reconciled": (
                    isinstance(current_operation, Mapping)
                    and current_operation.get("status") == "completed"
                ),
                "rollback_effect_matches": True,
                "rollback_environment_binding_valid": bool(
                    environment_id and fingerprint
                ),
            },
            artifact_digest=artifact,
            environment_id=environment_id,
            environment_fingerprint=fingerprint,
            operation_id=operation_id,
            subject_ids=("rollback-result",),
            scope=scope,
        )
        patch = {
            "runtime_rollback_operation": operation_id,
            "runtime_rollback_effect_id": rollback_effect_id,
            "runtime_rollback_evidence": rollback_evidence,
            "runtime_rollback_result": {
                "state": rollback_state,
                "target": rollback_target,
                "verification": verification.as_dict(),
            },
        }
        self._record_domain_once(
            "ROLLBACK_OPERATION_RECORDED",
            {"operation_id": operation_id, "state_patch": patch},
            idempotency_key=f"configured-runtime:rollback-result:{operation_id}",
        )
        checkpoint("runtime.after_rollback_result_record")
        transitioned = self._transition(
            run,
            "ROLLBACK_OBSERVED",
            state_patch=patch,
        )
        self._dispose_workspace(manager, workspace, root)
        return transitioned

    def _verify_rollback(self, run: Mapping[str, Any]) -> bool:
        payload = self._payload(run)
        result = payload.get("runtime_rollback_result", {})
        verification = result.get("verification", {}) if isinstance(result, Mapping) else {}
        artifact = str(payload["runtime_published_artifact"])
        environment_id = str(payload["runtime_environment_id"])
        fingerprint = str(payload["runtime_environment_fingerprint"])
        environment_index = int(payload["runtime_environment_index"])
        scope = self._environment_scope(environment_index)
        assertions = {
            "observed_environment_equals_rollback_target": (
                isinstance(verification, Mapping)
                and verification.get("observed_state", {}).get("deployed_version")
                == payload.get("runtime_rollback_target")
            ),
            "post_rollback_verification_passed": (
                isinstance(verification, Mapping)
                and verification.get("status") == "succeeded"
                and verification.get("observed_state", {}).get("healthy") is True
            ),
        }
        evidence_id = self._evidence(
            730,
            "post-rollback",
            {
                "rollback": result,
                "operation_id": payload["runtime_rollback_operation"],
                "effect_id": payload["runtime_rollback_effect_id"],
                "rollback_evidence_id": payload["runtime_rollback_evidence"],
                "stable_commit": payload["runtime_stable_commit"],
                "artifact_digest": artifact,
            },
            assertions=assertions,
            artifact_digest=artifact,
            environment_id=environment_id,
            environment_fingerprint=fingerprint,
            operation_id=str(payload["runtime_rollback_operation"]),
            subject_ids=("post-rollback", str(payload["runtime_environment_key"])),
            scope=scope,
        )
        if not all(assertions.values()):
            return self._delivery_attention(
                run,
                reason="post-rollback verification failed",
                required_decision="inspect_environment_and_choose_recovery",
                observations={
                    "rollback": result,
                    "verification": verification,
                },
                evidence_ids=(
                    str(payload["runtime_rollback_evidence"]),
                    evidence_id,
                ),
                external_operations_reconciled=True,
            )
        terminal_evidence, terminal_resolution = self._final_branch_cleanup(
            run,
            terminal_stage="rollback",
            terminal_observation={
                "post_rollback_evidence_id": evidence_id,
                "rollback_operation_id": payload["runtime_rollback_operation"],
                "rollback_effect_id": payload["runtime_rollback_effect_id"],
            },
        )
        gate_id = self._gate(
            "POST_ROLLBACK_GATE",
            (evidence_id, terminal_evidence),
            bindings={
                "artifact_digest": artifact,
                "environment_id": environment_id,
                "environment_fingerprint": fingerprint,
            },
            scope=scope,
        )
        return self._transition(
            run,
            "ROLLBACK_VERIFIED",
            state_patch={"runtime_terminal_resolution": terminal_resolution},
            gate_ids=(gate_id,),
        )


@dataclass
class RuntimeComposition:
    target: Path
    store: Any
    reducer: Any
    run_id: str
    project: Mapping[str, Any]
    dispatcher: ConfiguredDispatcher
    launcher: DurableChildLauncher
    reconciler: RuntimeOperationReconciler
    controller: WorkflowController

    @classmethod
    def create(cls, target: Path, store: Any, reducer: Any, run_id: str) -> "RuntimeComposition":
        target = target.resolve()
        project = validate_project_config(load_json(target / "project.json"))
        run = store.get_run(run_id)
        if not isinstance(run, Mapping):
            raise ContractError(f"unknown run: {run_id}")
        current_config_hash = sha256_bytes(canonical_json(project))
        from .specs import canonical_spec_hash

        spec_path = (target / str(project["spec"]["document"])).resolve()
        try:
            spec_path.relative_to(target)
        except ValueError as exc:
            raise ContractError("configured Spec path escapes the project root") from exc
        current_spec_hash = canonical_spec_hash(spec_path)
        if (
            run.get("config_hash") != current_config_hash
            or run.get("spec_hash") != current_spec_hash
        ):
            raise ContractError(
                "run Spec/config inputs changed; amend and replan before dispatch"
            )
        persisted_payload = run.get("payload", {})
        persisted_traceability = (
            persisted_payload.get("traceability")
            if isinstance(persisted_payload, Mapping)
            else None
        )
        current_traceability = load_json(
            target / str(project["spec"]["traceability"])
        )
        if (
            not isinstance(persisted_traceability, Mapping)
            or canonical_json(persisted_traceability)
            != canonical_json(current_traceability)
        ):
            raise ContractError(
                "run traceability inputs changed; amend and replan before dispatch"
            )
        persisted_baseline_raw = (
            persisted_payload.get("version_baseline")
            if isinstance(persisted_payload, Mapping)
            else None
        )
        try:
            persisted_baseline = validate_version_record(
                persisted_baseline_raw
            )
        except Exception as exc:
            raise ContractError(
                "run runtime version baseline is missing or invalid"
            ) from exc
        current_baseline = collect_project_runtime_versions(target, project)
        version_drift = detect_version_drift(
            persisted_baseline, current_baseline
        )
        if version_drift:
            raise ContractError(
                "run runtime version baseline drifted before dispatch: "
                + ", ".join(sorted(version_drift))
            )
        configured_engine = ConfiguredRuntimeEngine(
            target,
            project,
            reducer,
            store,
            run_id=run_id,
            version_baseline=persisted_baseline,
        )
        dispatcher = ConfiguredDispatcher(
            reducer,
            store,
            run_id=run_id,
            configured_step=configured_engine,
        )
        launcher = DurableChildLauncher(target, reducer, store, run_id=run_id)
        reconciler = RuntimeOperationReconciler(target, project, reducer, store, run_id)
        authenticators = project["authorization"]["trusted_authenticators"]
        public_keys: dict[str, Path] = {}
        for authenticator in authenticators:
            key = (target / str(authenticator["public_key"])).resolve()
            try:
                key.relative_to(target)
            except ValueError as exc:
                raise ContractError(
                    "trusted authenticator public key escapes the project root"
                ) from exc
            public_keys[str(authenticator["authenticator_id"])] = key
        signature_verifier = OpenSSLSignatureVerifier(public_keys)
        controller = WorkflowController(
            reducer,
            store,
            run_id=run_id,
            durable_launcher=launcher,
            operation_reconciler=reconciler,
            drive_step=dispatcher,
            signature_verifier=signature_verifier,
        )
        return cls(
            target,
            store,
            reducer,
            run_id,
            project,
            dispatcher,
            launcher,
            reconciler,
            controller,
        )

    def handle(self, command: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        controller_id = os.environ.get("NM_V6_CONTROLLER_ID") if arguments.get("child") else None
        if controller_id:
            self.launcher.mark(controller_id, status="running", run=self.store.get_run(self.run_id))
        try:
            result = self.controller.handle_cli(command, arguments)
        except BaseException:
            if controller_id:
                self.launcher.mark(
                    controller_id,
                    status="failed",
                    run=self.store.get_run(self.run_id),
                    result={"result": "failed"},
                )
            raise
        if controller_id:
            run = self.store.get_run(self.run_id)
            state = str(run["state"]) if isinstance(run, Mapping) else "UNKNOWN"
            status = "terminal" if state in _TERMINAL_STATES else "idle"
            if result.get("result") == "waiting_for_input":
                status = "waiting_for_input"
            self.launcher.mark(controller_id, status=status, run=run, result=result)
        return result


def compose_runtime(target: Path, store: Any, reducer: Any, run_id: str) -> RuntimeComposition:
    return RuntimeComposition.create(target, store, reducer, run_id)


# The generated-project self-test is appended below.  It deliberately owns a
# disposable repository, database, fake trust boundary, and fake providers; no
# helper below is reachable from normal ``run`` dispatch.


class _SelfTestVerifier:
    @staticmethod
    def verify(record: Mapping[str, Any], *, now: datetime | None = None) -> Any:
        return validate_authorization_record(record, now=now)


class _CountingExecutor(ActionExecutor):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.executed: list[str] = []

    def execute(self, definition: Any, **kwargs: Any) -> ActionResult:
        self.executed.append(str(definition.action_id))
        return super().execute(definition, **kwargs)


class _FakeSecretResolver:
    def __init__(self, project: Mapping[str, Any]) -> None:
        references = project.get("secret_references")
        if not isinstance(references, Mapping):
            raise ContractError("self-test project has no secret reference registry")
        self.references = references
        for name, value in references.items():
            if not isinstance(value, Mapping) or value.get("provider") != "fake":
                raise ContractError(
                    f"credential-free self-test refuses non-fake secret provider: {name}"
                )

    def __call__(self, reference: str) -> SecretValue:
        if reference not in self.references:
            raise ContractError(f"unknown self-test secret reference: {reference}")
        env_name = "NM_V6_FAKE_" + reference.upper().replace("-", "_")
        return SecretValue(reference, env_name, f"fixture-only-{reference}")


class _GeneratedProjectSelfTest:
    def __init__(self, target: Path, root: Path) -> None:
        self.target = target.resolve()
        self.root = root.resolve()
        self.project = validate_project_config(load_json(self.target / "project.json"))
        self.definitions = validate_action_registry(self.project["action_definitions"])
        for action_id, definition in self.definitions.items():
            if (
                len(definition.argv) != 3
                or Path(definition.argv[0]).name not in {"python3", "python"}
                or definition.argv[1] != "0d-scripts/fake-action.py"
                or definition.argv[2] != action_id
            ):
                raise ContractError(
                    "generated self-test executes only the credential-free fixture action registry"
                )
        self.run_id = "selftest"
        self.sequence = 0
        self.evidence_sequence = 0
        self.gate_sequence = 0
        self.remote = self.root / "remote.git"
        self.checkout = self.root / "checkout"
        self.workspace_root = self.root / "workspaces"
        self.evidence_store = EvidenceStore(self.root / "evidence")
        self.store: Any = None
        self.reducer: Any = None
        self.git: GitController | None = None
        self.manager: WorkspaceManager | None = None
        self.workspace: Workspace | None = None
        self.executor: _CountingExecutor | None = None

    def run(self) -> dict[str, Any]:
        self._prepare_repository()
        from .specs import canonical_spec_hash, validate_traceability

        spec_path = self.target / self.project["spec"]["document"]
        spec_hash = canonical_spec_hash(spec_path)
        traceability = load_json(
            self.target / self.project["spec"]["traceability"]
        )
        validate_traceability(traceability)
        config_hash = sha256_bytes(canonical_json(self.project))
        from .store import Store

        self.store = Store(self.root / "state.sqlite3")
        self.reducer = Reducer(self.store, evidence_store=self.evidence_store)
        self.reducer.create_run(
            run_id=self.run_id,
            spec_hash=spec_hash,
            config_hash=config_hash,
            mode="staged",
            run_kind="normal",
            actor="generated-self-test",
            idempotency_key="selftest:create",
            payload={
                "normal_run": True,
                "all_phases_done": True,
                "release_required": True,
                "deploy_required": True,
                "traceability": traceability,
            },
        )
        self.git = GitController(
            self.checkout,
            protected_authority=StoreProtectedMutationAuthority(self.store),
        )
        try:
            self._confirm_and_plan()
            grant_id, grant_revision = self._grant()
            self.reducer.set_mode(
                run_id=self.run_id,
                expected_revision=self._revision(),
                mode="auto",
                authorization_id=grant_id,
                idempotency_key="selftest:mode:auto",
            )
            self._transition("START_IMPLEMENTATION")
            candidate = self._prepare_candidate()
            task_evidence = self._run_scheduled_actions(candidate)
            self._transition("START_PHASE_VERIFICATION")
            phase_result = self._execute_pure("phase_verify")
            full_result = self._execute_pure("full_verify")
            phase_evidence = self._evidence(
                "phase-verification",
                canonical_json(
                    {
                        "tasks": task_evidence,
                        "phase": phase_result.as_dict(),
                        "full": full_result.as_dict(),
                    }
                ),
                candidate_commit=candidate,
                gate_types=("PHASE_GATE", "DEV_INTEGRATION_GATE"),
            )
            phase_gate = self._gate("PHASE_GATE", phase_evidence)
            dev_gate = self._gate(
                "DEV_INTEGRATION_GATE",
                phase_evidence,
                authorization_id=grant_id,
                context={
                    "candidate_commit": candidate,
                    "target_commit": self.git.resolve_commit("refs/heads/dev"),
                },
            )
            self._transition(
                "START_DEV_INTEGRATION",
                gate_ids=(phase_gate, dev_gate),
                authorization_id=grant_id,
                payload={"protected_ref": "dev"},
            )
            integration = self._integrate_dev(candidate, dev_gate, grant_id)
            self._transition(
                "DEV_INTEGRATION_APPLIED",
                gate_ids=(dev_gate,),
                authorization_id=grant_id,
                payload={"protected_ref": "dev"},
            )
            integration_evidence = self._evidence(
                "dev-integration-result",
                canonical_json(integration),
                source_commit=candidate,
                candidate_commit=integration["target_after"],
                gate_types=("DEV_INTEGRATION_RESULT_GATE",),
            )
            result_gate = self._gate(
                "DEV_INTEGRATION_RESULT_GATE",
                integration_evidence,
                context={"target_commit": integration["target_after"]},
            )
            self._transition(
                "ALL_PHASES_INTEGRATED",
                gate_ids=(result_gate,),
                payload={"all_phases_done": True},
            )

            release_source_commit = integration["target_after"]
            release_source_tree = self.git.tree_of(release_source_commit)
            approved_build = self._execute_build(release_source_commit)
            approved_artifact = approved_build.artifact_digest or ""
            release_build_evidence = self._evidence(
                "release-build",
                canonical_json(approved_build.as_dict()),
                source_commit=release_source_commit,
                candidate_commit=release_source_commit,
                release_source_kind="dev",
                release_source_commit=release_source_commit,
                release_source_tree=release_source_tree,
                artifact_digest=approved_artifact,
                gate_types=("RELEASE_GATE",),
            )
            release_gate = self._gate(
                "RELEASE_GATE",
                release_build_evidence,
                authorization_id=grant_id,
                context={
                    "source_commit": release_source_commit,
                    "candidate_commit": release_source_commit,
                    "target_commit": self.git.resolve_commit("refs/heads/main"),
                    "release_source_kind": "dev",
                    "release_source_commit": release_source_commit,
                    "release_source_tree": release_source_tree,
                    "artifact_digest": approved_artifact,
                },
            )
            self._transition(
                "START_RELEASE",
                gate_ids=(release_gate,),
                authorization_id=grant_id,
                payload={"release_required": True, "protected_ref": "main"},
            )
            stable = self._promote_stable(grant_id, release_gate)
            release_receipt = self._release(
                grant_id,
                grant_revision,
                release_gate_id=release_gate,
                stable_commit=stable["target_after"],
                expected_artifact_digest=approved_artifact,
            )
            release_evidence = self._evidence(
                "release-result",
                canonical_json(
                    {
                        "tag": release_receipt.tag,
                        "published_version": release_receipt.published_version,
                        "release_reconciliation": bool(
                            release_receipt.release_observation.reconciliation
                        ),
                        "publish_reconciliation": bool(
                            release_receipt.publish_observation.reconciliation
                        ),
                    }
                ),
                source_commit=release_receipt.source.commit,
                candidate_commit=release_receipt.stable_commit,
                release_source_kind="dev",
                release_source_commit=release_receipt.source.commit,
                release_source_tree=release_receipt.source.tree,
                artifact_digest=release_receipt.artifact_digest,
                gate_types=("RELEASE_RESULT_GATE",),
            )
            release_result_gate = self._gate(
                "RELEASE_RESULT_GATE", release_evidence
            )
            self._transition("RELEASE_OBSERVED", gate_ids=(release_result_gate,))
            self._transition("PREPARE_DEPLOYMENT")
            deploy_readiness_evidence = self._deployment_readiness_evidence(
                release_receipt.artifact_digest
            )
            deploy_gate = self._gate(
                "DEPLOY_GATE",
                deploy_readiness_evidence,
                authorization_id=grant_id,
            )
            self._transition(
                "START_DEPLOYMENT",
                gate_ids=(deploy_gate,),
                authorization_id=grant_id,
                payload={
                    "deploy_required": True,
                    "environment_id": "project-production",
                    "environment_index": 0,
                    "environment_key": "production",
                },
            )
            deployment, rollback = self._deploy_and_rollback(
                grant_id,
                grant_revision,
                release_receipt.artifact_digest,
                deploy_gate,
            )
            deploy_evidence = self._evidence(
                "deployment-and-rollback",
                canonical_json(
                    {
                        "deploy_state": deployment.state,
                        "deploy_reconciliation": bool(
                            deployment.deploy_observation.reconciliation
                        ),
                        "rollback_state": rollback.state,
                    }
                ),
                artifact_digest=release_receipt.artifact_digest,
                environment_id="project-production",
                environment_fingerprint="fake-project-production-v1",
                gate_types=("POST_ROLLBACK_GATE",),
            )
            post_rollback_gate = self._gate(
                "POST_ROLLBACK_GATE", deploy_evidence
            )
            self._transition(
                "ROLLBACK_VERIFIED", gate_ids=(post_rollback_gate,)
            )
            final = self._current()
            if final["state"] != "ROLLED_BACK":
                raise NmV6Error("generated self-test did not reach verified rollback")
            expected_actions = set(self.definitions)
            executed = set(self.executor.executed if self.executor else ())
            missing = sorted(expected_actions - executed)
            if missing:
                raise NmV6Error(
                    "generated self-test did not execute configured actions: "
                    + ", ".join(missing)
                )
            return {
                "schema_version": "nm-v6/self-test-v2",
                "result": "passed",
                "state": final["state"],
                "revision": final["revision"],
                "scheduler": {"selected_parallel": 2, "completed_tasks": 2},
                "git": {
                    "dev": self.git.remote_head("dev") if self.git else None,
                    "stable": self.git.remote_head("main") if self.git else None,
                    "stable_equals_dev": (
                        self.git.remote_head("dev") == self.git.remote_head("main")
                        if self.git
                        else False
                    ),
                },
                "actions_executed": list(self.executor.executed if self.executor else ()),
                "partial_unknown_reconciliation": {
                    "release": release_receipt.release_observation.reconciliation is not None,
                    "publish": release_receipt.publish_observation.reconciliation is not None,
                    "deploy": deployment.deploy_observation.reconciliation is not None,
                },
                "persisted_operations": {
                    operation_id: self.store.get_operation(operation_id)["status"]
                    for operation_id in (
                        "OP-selftest-001",
                        "OP-selftest-002",
                        "OP-selftest-003",
                        "OP-selftest-004",
                        "OP-selftest-005",
                        "OP-selftest-006",
                    )
                },
                "rollback": {
                    "state": rollback.state,
                    "verified": rollback.verification.observed_state.get("healthy") is True,
                },
                "credentials": "fake_references_only",
                "audit_events": len(self.store.list_audit()),
            }
        finally:
            if self.workspace is not None and self.manager is not None:
                self.manager.dispose(self.workspace)
            if self.store is not None:
                self.store.close()

    def _prepare_repository(self) -> None:
        status = run_command(
            ("git", "status", "--porcelain=v1", "--untracked-files=all"),
            cwd=self.target,
        ).stdout.strip()
        if status:
            raise ContractError(
                "generated self-test requires a clean checkout so action inputs are immutable"
            )
        source_head = run_command(("git", "rev-parse", "HEAD"), cwd=self.target).stdout.strip()
        run_command(("git", "clone", "--bare", "--no-local", str(self.target), str(self.remote)), cwd=self.root)
        run_command(("git", "update-ref", "refs/heads/main", source_head), cwd=self.remote)
        run_command(("git", "update-ref", "refs/heads/dev", source_head), cwd=self.remote)
        run_command(("git", "symbolic-ref", "HEAD", "refs/heads/main"), cwd=self.remote)
        run_command(("git", "clone", "--no-local", str(self.remote), str(self.checkout)), cwd=self.root)
        run_command(("git", "config", "user.name", "NM V6 Self Test"), cwd=self.checkout)
        run_command(("git", "config", "user.email", "nm-v6-self-test@example.invalid"), cwd=self.checkout)

    def _confirm_and_plan(self) -> None:
        self._transition("DRAFT_SPEC", payload={"discovery_complete": True})
        self._transition("SUBMIT_SPEC_REVIEW")
        self._transition("REQUEST_SPEC_CONFIRMATION")
        run = self._current()
        request = self.reducer.create_authorization_request(
            run_id=self.run_id,
            expected_revision=int(run["revision"]),
            request_id="AUTHREQ-selftest-confirm",
            request_type="spec_confirmation",
            scope={"spec_hash": run["spec_hash"], "decision": "confirmed"},
            expires_at=self._expiry(),
            nonce="selftest-confirmation-nonce",
            idempotency_key="selftest:confirmation-request",
        )["request"]
        confirmation_id = "AUTH-selftest-001"
        self.reducer.import_authorization(
            {
                "record_type": "spec_confirmation",
                "confirmation_id": confirmation_id,
                "spec_id": "SPEC-SELFTEST",
                "version": 1,
                "spec_hash": run["spec_hash"],
                "decision": "confirmed",
                "administrator_identity": "self-test-fixture",
                "issued_at": utc_now(),
                "nonce": request["nonce"],
                "authenticator_id": "self-test-only",
                "authenticator_signature": base64.b64encode(b"self-test").decode("ascii"),
            },
            _SelfTestVerifier(),
            expected_revision=int(request["expected_revision"]),
            idempotency_key="selftest:confirmation-import",
        )
        evidence = self._evidence(
            "spec-contract",
            canonical_json({"project_valid": True, "spec_hash": run["spec_hash"]}),
            gate_types=("SPEC_GATE",),
        )
        gate = self._gate("SPEC_GATE", evidence, authorization_id=confirmation_id)
        self._transition(
            "CONFIRM_SPEC", gate_ids=(gate,), authorization_id=confirmation_id
        )
        self._transition("START_PLANNING")
        plan_evidence = self._evidence(
            "plan-contract",
            canonical_json(
                {
                    "task_dag": ["TASK-001", "TASK-002"],
                    "max_workers": self.project["scheduler"]["max_workers"],
                }
            ),
            gate_types=("PLAN_GATE",),
        )
        plan_gate = self._gate("PLAN_GATE", plan_evidence)
        self._transition("PLAN_READY", gate_ids=(plan_gate,))

    def _grant(self) -> tuple[str, int]:
        run = self._current()
        scope = {
            "run_id": self.run_id,
            "spec_hash": run["spec_hash"],
            "config_hash": run["config_hash"],
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
        request = self.reducer.create_authorization_request(
            run_id=self.run_id,
            expected_revision=int(run["revision"]),
            request_id="AUTHREQ-selftest-grant",
            request_type="grant",
            scope=scope,
            expires_at=self._expiry(),
            nonce="selftest-grant-nonce",
            idempotency_key="selftest:grant-request",
        )["request"]
        grant_id = "AUTH-selftest-002"
        grant = {
            "record_type": "grant",
            "grant_id": grant_id,
            **scope,
            "created_by": "self-test-fixture",
            "created_at": utc_now(),
            "expires_at": self._expiry(),
            "request_digest": request["request_digest"],
            "nonce": request["nonce"],
            "grant_revision": request["expected_revision"],
            "authenticator_id": "self-test-only",
            "authenticator_signature": base64.b64encode(b"self-test").decode("ascii"),
            "one_time": False,
        }
        self.reducer.import_authorization(
            grant,
            _SelfTestVerifier(),
            expected_revision=int(request["expected_revision"]),
            idempotency_key="selftest:grant-import",
        )
        return grant_id, int(grant["grant_revision"])

    def _prepare_candidate(self) -> str:
        if self.git is None:
            raise NmV6Error("self-test Git controller is missing")
        self.git.create_work_branch("feature/self-test")
        run_command(("git", "switch", "feature/self-test"), cwd=self.checkout)
        (self.checkout / "nm-v6-self-test.txt").write_text(
            "verified generated workflow\n", encoding="utf-8"
        )
        run_command(("git", "add", "nm-v6-self-test.txt"), cwd=self.checkout)
        run_command(("git", "commit", "-m", "test: generated workflow fixture"), cwd=self.checkout)
        candidate = run_command(("git", "rev-parse", "HEAD"), cwd=self.checkout).stdout.strip()
        run_command(("git", "switch", "--detach", "refs/heads/main"), cwd=self.checkout)
        self.manager = WorkspaceManager(self.checkout, self.workspace_root)
        self.workspace = self.manager.create("generated-self-test", commit=candidate)
        self.executor = _CountingExecutor(
            isolation_backend=self.manager.isolation_backend,
            secret_resolver=_FakeSecretResolver(self.project),
        )
        return candidate

    def _run_scheduled_actions(self, candidate: str) -> list[str]:
        if self.executor is None or self.workspace is None:
            raise NmV6Error("self-test action runtime is unavailable")
        graph = TaskGraph(
            (
                TaskDefinition("TASK-001", write_set=("src/a/**",)),
                TaskDefinition("TASK-002", write_set=("src/b/**",)),
            )
        )
        scheduler = Scheduler(
            graph,
            ReducerLeaseAuthority(self.reducer, run_id=self.run_id),
            max_workers=2,
            lease_seconds=120,
        )
        selected = scheduler.select(completed=(), active={})
        if len(selected) != 2:
            raise NmV6Error("generated self-test did not schedule safe Tasks concurrently")
        evidence: list[str] = []
        for index, task in enumerate(selected, start=1):
            lease = scheduler.acquire(
                task.task_id,
                owner=f"selftest-worker-{index}",
                attempt_id=f"ATTEMPT-selftest-{index:03d}",
                expected_revision=self._revision(),
            )
            result = self._execute_pure("task_verify")
            evidence.append(
                self._evidence(
                    f"task-{index}",
                    canonical_json(result.as_dict()),
                    candidate_commit=candidate,
                )
            )
            scheduler.release(lease, expected_revision=self._revision())
        return evidence

    def _integrate_dev(self, candidate: str, gate_id: str, grant_id: str) -> dict[str, Any]:
        if self.git is None:
            raise NmV6Error("self-test Git controller is missing")
        operation_id = "OP-selftest-001"
        self.reducer.start_operation(
            run_id=self.run_id,
            expected_revision=self._revision(),
            operation_id=operation_id,
            action_id="integrate_dev",
            operation_kind="protected_ref",
            idempotency_key=operation_id,
            authorization_id=grant_id,
            gate_id=gate_id,
            scope={
                "protected_ref": "dev",
                "candidate_commit": candidate,
                "target_commit": self.git.resolve_commit("refs/heads/dev"),
            },
        )
        proposal = self.git.build_merge_proposal(
            source_ref="refs/heads/feature/self-test",
            target_branch="dev",
            strategy="fast_forward",
            purpose="generated-self-test-integration",
            sharing_status="local",
            rationale="linear disposable candidate",
            rollback_ref="refs/nm-v6/rollback/selftest-dev",
            gate_ids=(gate_id,),
            authorization_id=grant_id,
        )
        receipt = self.git.execute_proposal(proposal)
        push = self.git.push_protected_cas(
            "dev",
            expected_remote=receipt.target_before,
            new_commit=receipt.target_after,
            proposal=proposal,
        )
        self._observe_operation(
            operation_id,
            "integrate_dev",
            f"dev-integration-{receipt.target_after}",
            {"target_after": receipt.target_after, "remote_after": push.observed_after},
        )
        return {
            "target_before": receipt.target_before,
            "target_after": receipt.target_after,
            "result_tree": receipt.result_tree,
            "remote_after": push.observed_after,
        }

    def _promote_stable(self, grant_id: str, release_gate_id: str) -> dict[str, Any]:
        if self.git is None:
            raise NmV6Error("self-test Git controller is missing")
        operation_id = "OP-selftest-002"
        source = self.git.resolve_commit("refs/heads/dev")
        gate = self.store.get_gate(release_gate_id)
        if not isinstance(gate, Mapping):
            raise NmV6Error("self-test release gate disappeared")
        self.reducer.start_operation(
            run_id=self.run_id,
            expected_revision=self._revision(),
            operation_id=operation_id,
            action_id="release",
            operation_kind="protected_ref",
            idempotency_key=operation_id,
            authorization_id=grant_id,
            gate_id=release_gate_id,
            scope={
                "protected_ref": "main",
                "source_commit": source,
                "target_commit": gate["target_commit"],
                "release_source_kind": gate["release_source_kind"],
                "release_source_commit": gate["release_source_commit"],
                "release_source_tree": gate["release_source_tree"],
                "artifact_digest": gate["artifact_digest"],
            },
        )
        proposal = self.git.build_merge_proposal(
            source_ref="refs/heads/dev",
            target_branch="main",
            strategy="fast_forward",
            purpose="generated-self-test-promotion",
            sharing_status="protected",
            rationale="stable must equal verified dev",
            rollback_ref="refs/nm-v6/rollback/selftest-main",
            gate_ids=(release_gate_id,),
            authorization_id=grant_id,
        )
        receipt = self.git.execute_proposal(
            proposal, require_source_tree_result=True
        )
        push = self.git.push_protected_cas(
            "main",
            expected_remote=receipt.target_before,
            new_commit=receipt.target_after,
            proposal=proposal,
        )
        self._observe_operation(
            operation_id,
            "release",
            f"stable-promotion-{receipt.target_after}",
            {"target_after": receipt.target_after, "remote_after": push.observed_after},
        )
        return {"target_after": receipt.target_after, "remote_after": push.observed_after}

    def _release(
        self,
        grant_id: str,
        grant_revision: int,
        *,
        release_gate_id: str,
        stable_commit: str,
        expected_artifact_digest: str,
    ) -> Any:
        if self.workspace is None or self.executor is None or self.git is None:
            raise NmV6Error("self-test release runtime is unavailable")
        for flag in (
            "force-release-partial",
            "force-observe_release-unknown",
            "force-publish-unknown",
            "force-observe_publish-unknown",
        ):
            (self.workspace.path / flag).write_text("yes\n", encoding="utf-8")
        recorder = ReducerOperationRecorder(
            self.reducer,
            self.store,
            run_id=self.run_id,
            expected_revision=lambda: self._revision(),
            scope={
                "protected_ref": "main",
                "source_commit": stable_commit,
                "target_commit": self.store.get_gate(release_gate_id)["target_commit"],
                "release_source_kind": "dev",
                "release_source_commit": stable_commit,
                "release_source_tree": self.git.tree_of(stable_commit),
                "artifact_digest": expected_artifact_digest,
                "gate_id": release_gate_id,
            },
        )
        recovery = RecoveryController(self.definitions, self.executor, recorder)
        delivery = DeliveryController(
            self.definitions, self.executor, recovery, git=self.git
        )
        run = self._current()
        tree = self.git.tree_of(stable_commit)
        source = ReleaseSource(
            "dev", stable_commit, tree, run["spec_hash"], run["config_hash"]
        )
        metadata = delivery.release_metadata(
            workspace=self.workspace,
            action_id=self.project["actions"]["release_metadata"],
            source=source,
        )
        return delivery.release(
            workspace=self.workspace,
            source=source,
            build_action=self.project["actions"]["build"],
            release_action=self.project["actions"]["release"],
            publish_action=self.project["actions"]["publish"],
            stable_commit=stable_commit,
            stable_tree=tree,
            release_operation_id="OP-selftest-003",
            publish_operation_id="OP-selftest-004",
            grant_id=grant_id,
            grant_revision=grant_revision,
            expected_tag=metadata.tag,
            expected_version=metadata.published_version,
            expected_release_metadata_digest=metadata.metadata_digest,
            expected_artifact_digest=expected_artifact_digest,
        )

    def _deploy_and_rollback(
        self,
        grant_id: str,
        grant_revision: int,
        artifact_digest: str,
        deploy_gate_id: str,
    ) -> tuple[Any, Any]:
        if self.workspace is None or self.executor is None:
            raise NmV6Error("self-test deployment runtime is unavailable")
        for flag in (
            "force-deploy-partial",
            "force-observe-deploy-unknown",
            "force-unhealthy",
        ):
            (self.workspace.path / flag).write_text("yes\n", encoding="utf-8")
        recorder = ReducerOperationRecorder(
            self.reducer,
            self.store,
            run_id=self.run_id,
            expected_revision=lambda: self._revision(),
            scope={
                "environment_id": "project-production",
                "environment_fingerprint": "fake-project-production-v1",
                "artifact_digest": artifact_digest,
                "gate_id": deploy_gate_id,
            },
        )
        recovery = RecoveryController(self.definitions, self.executor, recorder)
        delivery = DeliveryController(self.definitions, self.executor, recovery)
        environment = self.project["delivery"]["environments"]["production"]
        target = EnvironmentTarget(
            environment_id="project-production",
            expected_identity=str(environment["expected_identity"]),
            expected_fingerprint="fake-project-production-v1",
            identity_probe_action=str(environment["identity_probe"]),
            preflight_action=str(environment["preflight"]),
            deploy_action=str(environment["deploy"]),
            health_action=str(environment["health"]),
            rollback_action=str(environment["rollback"]),
            post_rollback_verify_action=str(environment["post_rollback_verify"]),
        )
        deployment = delivery.deploy(
            workspace=self.workspace,
            target=target,
            artifact_digest=artifact_digest,
            deploy_operation_id="OP-selftest-005",
            grant_id=grant_id,
            grant_revision=grant_revision,
            rollback_authorized=False,
        )
        if deployment.state != "ATTENTION_REQUIRED":
            raise NmV6Error("unhealthy self-test deployment did not require rollback")
        self._transition(
            "DEPLOYMENT_REQUIRES_ROLLBACK",
            payload={"external_operations_reconciled": True},
        )
        deploy_evidence = self._evidence(
            "unhealthy-deployment",
            canonical_json(
                {
                    "state": deployment.state,
                    "health": deployment.health_result.as_dict(),
                }
            ),
            artifact_digest=artifact_digest,
            environment_id=target.expected_identity,
            environment_fingerprint=target.expected_fingerprint,
            gate_types=("ROLLBACK_GATE",),
        )
        rollback_gate = self._gate(
            "ROLLBACK_GATE", deploy_evidence, authorization_id=grant_id
        )
        self._transition(
            "START_ROLLBACK",
            gate_ids=(rollback_gate,),
            authorization_id=grant_id,
            payload={"environment_id": "project-production"},
        )
        recorder.scope["gate_id"] = rollback_gate
        rollback = delivery.rollback(
            workspace=self.workspace,
            target=target,
            rollback_target=deployment.previous_version,
            operation_id="OP-selftest-006",
            grant_id=grant_id,
            grant_revision=grant_revision,
        )
        if rollback.state != "ROLLED_BACK":
            raise NmV6Error("generated self-test rollback was not independently verified")
        self._transition("ROLLBACK_OBSERVED")
        return deployment, rollback

    def _deployment_readiness_evidence(self, artifact_digest: str) -> str:
        if self.executor is None or self.workspace is None:
            raise NmV6Error("self-test action runtime is unavailable")
        environment = self.project["delivery"]["environments"]["production"]
        identity = self.executor.execute(
            self.definitions[str(environment["identity_probe"])],
            workspace=self.workspace,
            operation_id=None,
            allow_network=True,
        )
        preflight = self.executor.execute(
            self.definitions[str(environment["preflight"])],
            workspace=self.workspace,
            operation_id=None,
            allow_network=True,
        )
        if (
            identity.status != "succeeded"
            or identity.environment_id != str(environment["expected_identity"])
            or not identity.environment_fingerprint
            or preflight.status != "succeeded"
        ):
            raise NmV6Error("self-test deployment readiness checks failed")
        return self._evidence(
            "deployment-readiness",
            canonical_json(
                {
                    "identity": identity.as_dict(),
                    "preflight": preflight.as_dict(),
                }
            ),
            artifact_digest=artifact_digest,
            environment_id=identity.environment_id,
            environment_fingerprint=identity.environment_fingerprint,
            gate_types=("DEPLOY_GATE",),
        )

    def _execute_pure(self, logical_action: str) -> ActionResult:
        if self.executor is None or self.workspace is None:
            raise NmV6Error("self-test action runtime is unavailable")
        action_id = self.project["actions"].get(logical_action, logical_action)
        return self.executor.execute(
            self.definitions[action_id], workspace=self.workspace, operation_id=None
        )

    def _execute_build(self, source_commit: str) -> ActionResult:
        if self.executor is None or self.workspace is None:
            raise NmV6Error("self-test action runtime is unavailable")
        action_id = self.project["actions"]["build"]
        result = self.executor.execute(
            self.definitions[action_id],
            workspace=self.workspace,
            operation_id=None,
            core_env={"NM_V6_SOURCE_COMMIT": source_commit},
        )
        if result.status != "succeeded" or not result.artifact_digest:
            raise NmV6Error("self-test build did not produce an immutable artifact")
        return result

    def _observe_operation(
        self, operation_id: str, action_id: str, effect_id: str, result: Mapping[str, Any]
    ) -> None:
        self.reducer.record_operation_observation(
            OperationObservation(
                operation_id=operation_id,
                action_id=action_id,
                status="succeeded",
                effect_id=effect_id,
                result=dict(result),
            ),
            run_id=self.run_id,
            expected_revision=self._revision(),
            idempotency_key=f"selftest:observe:{operation_id}",
        )

    def _evidence(
        self,
        label: str,
        output: bytes,
        *,
        source_commit: str | None = None,
        candidate_commit: str | None = None,
        release_source_kind: str | None = None,
        release_source_commit: str | None = None,
        release_source_tree: str | None = None,
        artifact_digest: str | None = None,
        environment_id: str | None = None,
        environment_fingerprint: str | None = None,
        gate_types: Sequence[str] = (),
    ) -> str:
        self.evidence_sequence += 1
        run = self._current()
        evidence_id = f"EVID-selftest-{self.evidence_sequence:03d}"
        timestamp = utc_now()
        subjects = [label]
        for gate_type in gate_types:
            for prerequisite in GATE_DEFINITIONS[gate_type].prerequisites:
                if prerequisite not in subjects:
                    subjects.append(prerequisite)
        receipt = self.evidence_store.persist(
            {
                "evidence_id": evidence_id,
                "evidence_type": "generated_project_self_test",
                "producer": "nm-v6-self-test-core",
                "run_id": self.run_id,
                "subject_ids": subjects,
                "assertions": {name: True for name in subjects},
                "spec_hash": run["spec_hash"],
                "config_hash": run["config_hash"],
                "source_commit": source_commit,
                "candidate_commit": candidate_commit,
                "release_source_kind": release_source_kind,
                "release_source_commit": release_source_commit,
                "release_source_tree": release_source_tree,
                "hotfix_reconciliation_gate_id": None,
                "artifact_digest": artifact_digest,
                "environment_id": environment_id,
                "environment_fingerprint": environment_fingerprint,
                "operation_id": None,
                "attempt_id": None,
                "command_action_id": label,
                "argv_digest": sha256_bytes(label.encode("utf-8")),
                "working_directory": ".",
                "started_at": timestamp,
                "finished_at": timestamp,
                "exit_code": 0,
                "result": "passed",
                "tool_versions": {"nm-v6": "self-test"},
                "producer_version": "nm-v6/self-test-v2",
                "evaluator_version": "nm-v6/gates-v1",
            },
            output,
            b"",
        )
        self.reducer.record_evidence(
            run_id=self.run_id,
            expected_revision=self._revision(),
            receipt=receipt,
            idempotency_key=f"selftest:evidence:{evidence_id}",
        )
        return evidence_id

    def _gate(
        self,
        gate_type: str,
        evidence_id: str,
        *,
        authorization_id: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> str:
        self.gate_sequence += 1
        run = self._current()
        facts = {
            name: True for name in GATE_DEFINITIONS[gate_type].prerequisites
        }
        if context:
            facts.update(context)
        receipt = self.store.get_evidence(evidence_id)
        if not isinstance(receipt, Mapping):
            raise NmV6Error("self-test gate evidence disappeared")
        for field in required_bindings(gate_type):
            if field != "target_commit" and facts.get(field) is None:
                facts[field] = receipt.get(field)
        facts["run_id"] = self.run_id
        facts["prerequisite_evidence"] = {
            name: [evidence_id]
            for name in GATE_DEFINITIONS[gate_type].prerequisites
        }
        gate_id = f"GATE-selftest-{self.gate_sequence:03d}"
        evaluator = GateEvaluator(
            self.store.get_evidence,
            evidence_validator=self.evidence_store.validate,
        )
        decision = evaluator.evaluate(
            GateObservation(
                gate_type=gate_type,
                subject_ids=(self.run_id,),
                context=facts,
                evidence_ids=(evidence_id,),
                evaluator="generated-self-test",
                authorization_id=authorization_id,
            ),
            gate_id=gate_id,
            spec_hash=run["spec_hash"],
            config_hash=run["config_hash"],
            run_revision=int(run["revision"]),
        )
        if decision["result"] != "passed":
            raise NmV6Error(f"generated self-test gate failed: {gate_type}")
        self.reducer.record_gate(
            run_id=self.run_id,
            expected_revision=self._revision(),
            decision=decision,
            idempotency_key=f"selftest:gate:{gate_id}",
        )
        return gate_id

    def _transition(
        self,
        event: str,
        *,
        payload: Mapping[str, Any] | None = None,
        gate_ids: Sequence[str] = (),
        authorization_id: str | None = None,
    ) -> None:
        self.sequence += 1
        self.reducer.transition(
            TransitionProposal(
                run_id=self.run_id,
                expected_revision=self._revision(),
                event=event,
                actor="generated-self-test",
                idempotency_key=f"selftest:transition:{self.sequence:03d}:{event}",
                payload=dict(payload or {}),
                gate_ids=tuple(gate_ids),
                authorization_id=authorization_id,
            )
        )

    def _current(self) -> dict[str, Any]:
        value = self.store.get_run(self.run_id)
        if not isinstance(value, Mapping):
            raise NmV6Error("generated self-test run disappeared")
        return dict(value)

    def _revision(self) -> int:
        return int(self._current()["revision"])

    @staticmethod
    def _expiry() -> str:
        return (datetime.now(UTC) + timedelta(hours=1)).isoformat()


def run_generated_self_test(target: Path) -> dict[str, Any]:
    """Execute every fake project action through the complete disposable stack."""

    target = target.resolve()
    with tempfile.TemporaryDirectory(prefix="nm-v6-generated-self-test-") as directory:
        return _GeneratedProjectSelfTest(target, Path(directory)).run()
