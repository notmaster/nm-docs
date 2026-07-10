from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch


TOOL_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
REPOSITORY = TOOL_ROOT.parents[1]
for value in (TOOL_ROOT, TEST_ROOT):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from nmv6.actions import ActionExecutor, ActionResult, SecretValue, validate_action_registry  # noqa: E402
from nmv6.audit import export_audit, verify_audit_chain  # noqa: E402
from nmv6.authorization import (  # noqa: E402
    OpenSSLSignatureVerifier,
    signed_payload,
    validate_authorization_record,
)
from nmv6.controller import WorkflowController  # noqa: E402
from nmv6.delivery import DeliveryController, EnvironmentTarget, ReleaseSource  # noqa: E402
from nmv6.evidence import EvidenceStore  # noqa: E402
from nmv6.errors import ContractError, GitPolicyError, RecoveryError, TransitionError  # noqa: E402
from nmv6.gates import GateEvaluator, required_prerequisites  # noqa: E402
import nmv6.git_controller as git_controller_module  # noqa: E402
from nmv6.git_controller import CleanupFacts, GitController, MergeReceipt  # noqa: E402
from nmv6.models import GateObservation, OperationObservation, TransitionProposal  # noqa: E402
from nmv6.outbox import NotificationIntent  # noqa: E402
from nmv6.recovery import RecoveryController  # noqa: E402
from nmv6.reducer import DOMAIN_EVENT_TYPES, Reducer  # noqa: E402
from nmv6.store import Store  # noqa: E402
from nmv6.util import utc_now  # noqa: E402
from nmv6.workspace import Workspace  # noqa: E402
from test_operations import (  # noqa: E402
    FakeRecorder,
    TestIsolationBackend,
    create_delivery_fixture,
    create_git_fixture,
    git,
)
from test_state_auth_evidence import (  # noqa: E402
    base_receipt,
    complete_gate_receipt,
    gate_context,
)


class ShapeOnlyVerifier:
    """Audit-fixture verifier; cryptographic rejection is covered elsewhere."""

    @staticmethod
    def verify(record: dict[str, object], *, now: datetime | None = None):
        return validate_authorization_record(record, now=now)


def _revision(store: Store, run_id: str) -> int:
    run = store.get_run(run_id)
    if run is None:
        raise AssertionError(f"missing run: {run_id}")
    return int(run["revision"])


def _authorization_record(
    *,
    record_type: str,
    identifier: str,
    request: dict[str, object],
) -> dict[str, object]:
    id_field = "grant_id" if record_type == "grant" else "approval_id"
    return {
        "record_type": record_type,
        id_field: identifier,
        "run_id": request["run_id"],
        "spec_hash": request["spec_hash"],
        "config_hash": request["config_hash"],
        "allowed_actions": ["audit_fixture"],
        "allowed_environments": [],
        "allowed_protected_refs": [],
        "created_by": "administrator",
        "created_at": utc_now(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "request_digest": request["request_digest"],
        "nonce": request["nonce"],
        "grant_revision": request["expected_revision"],
        "authenticator_id": "audit-fixture-verifier",
        "authenticator_signature": "AA==",
    }


def _advance_remote_dev(root: Path, remote: Path, filename: str = "remote.txt") -> str:
    updater = root / f"updater-{filename.replace('.', '-')}"
    git("clone", str(remote), str(updater), cwd=root)
    git("config", "user.name", "Updater", cwd=updater)
    git("config", "user.email", "updater@example.invalid", cwd=updater)
    git("switch", "dev", cwd=updater)
    (updater / filename).write_text("remote movement\n", encoding="utf-8")
    git("add", filename, cwd=updater)
    git("commit", "-m", f"move dev with {filename}", cwd=updater)
    commit = git("rev-parse", "HEAD", cwd=updater)
    git("push", "origin", "dev", cwd=updater)
    return commit


def _cleanup_receipt(controller: GitController, head: str) -> MergeReceipt:
    return MergeReceipt(
        "fast_forward",
        head,
        head,
        head,
        controller.tree_of(head),
        "refs/nm-v6/rollback/dev",
        "AUTH-cleanup",
        "2026-01-01T00:00:00Z",
    )


def _record_cleanup_responsibility_closure(
    *,
    reducer: Reducer,
    evidence: EvidenceStore,
    run_id: str,
    branch: str,
    head: str,
    sequence: int = 1,
) -> str:
    receipt = base_receipt(run_id, f"EVID-cleanup-{sequence:03d}")
    receipt.update(
        {
            "evidence_type": "branch_cleanup_responsibility",
            "producer": "nm-v6-core/cleanup-evaluator",
            "subject_ids": [f"branch:{branch}", f"branch-head:{head}"],
            "assertions": {
                "review_responsibility_closed": True,
                "backup_retention_absent": True,
                "dependent_work_closed": True,
                "release_responsibility_closed": True,
                "rollback_responsibility_closed": True,
                "audit_retention_absent": True,
                "explicit_retention_absent": True,
            },
            "source_commit": head,
            "candidate_commit": head,
            "attempt_id": None,
            "command_action_id": "branch_cleanup_responsibility",
        }
    )
    persisted = evidence.persist(receipt, b"cleanup responsibilities closed\n", b"")
    run = reducer.store.get_run(run_id)
    if run is None:
        raise AssertionError(f"missing run: {run_id}")
    reducer.record_evidence(
        run_id=run_id,
        expected_revision=int(run["revision"]),
        receipt=persisted,
        idempotency_key=f"cleanup-responsibility:{sequence}",
        actor="cleanup-evaluator",
    )
    return str(persisted["evidence_id"])


def _sign_authorization(
    root: Path, private_key: Path, name: str, record: dict[str, object]
) -> dict[str, object]:
    payload = root / f"{name}-payload.json"
    signature = root / f"{name}-signature.bin"
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
        "authenticator_signature": base64.b64encode(signature.read_bytes()).decode(
            "ascii"
        ),
    }


def _import_nonprotected_grant(
    *,
    root: Path,
    reducer: Reducer,
    verifier: OpenSSLSignatureVerifier,
    private_key: Path,
    run_id: str,
    sequence: int,
    grant: dict[str, object],
) -> None:
    current = reducer.store.get_run(run_id)
    if current is None:
        raise AssertionError(f"missing run: {run_id}")
    revision = int(current["revision"])
    exact_scope = {
        key: grant[key]
        for key in (
            "grant_id",
            "action",
            "remote",
            "ref",
            "expected_sha",
            "force",
            "one_time",
            "expires_at",
        )
    }
    authorization_id = str(grant["administrator_authorization_id"])
    request = reducer.create_authorization_request(
        run_id=run_id,
        expected_revision=revision,
        request_id=f"AUTHREQ-git-ref-{sequence:03d}",
        request_type="grant",
        scope={
            "run_id": run_id,
            "spec_hash": "a" * 64,
            "config_hash": "b" * 64,
            "allowed_actions": [grant["action"]],
            "allowed_environments": [],
            "allowed_protected_refs": [],
            "one_time": True,
            "nonprotected_ref": exact_scope,
        },
        expires_at=str(grant["expires_at"]),
        idempotency_key=f"request-git-ref-{sequence:03d}",
        nonce=f"git-ref-nonce-{sequence:03d}",
    )["request"]
    record = _sign_authorization(
        root,
        private_key,
        f"git-ref-{sequence:03d}",
        {
            "record_type": "grant",
            "grant_id": authorization_id,
            "run_id": run_id,
            "spec_hash": "a" * 64,
            "config_hash": "b" * 64,
            "allowed_actions": [grant["action"]],
            "allowed_environments": [],
            "allowed_protected_refs": [],
            "created_by": "administrator",
            "created_at": utc_now(),
            "expires_at": grant["expires_at"],
            "request_digest": request["request_digest"],
            "nonce": request["nonce"],
            "grant_revision": request["expected_revision"],
            "authenticator_id": "git-test-admin",
            "one_time": True,
            "nonprotected_ref": exact_scope,
        },
    )
    reducer.import_authorization(
        record,
        verifier,
        expected_revision=revision + 1,
        idempotency_key=f"import-git-ref-{sequence:03d}",
    )


def _template_delivery(
    checkout: Path,
    git_controller: GitController,
) -> tuple[DeliveryController, Workspace, EnvironmentTarget]:
    script_target = checkout / "0d-scripts/fake-action.py"
    script_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPOSITORY / "template/v6/0d-scripts/fake-action.py", script_target)
    project = json.loads(
        (REPOSITORY / "template/v6/project.example.json").read_text(encoding="utf-8")
    )
    definitions = validate_action_registry(project["action_definitions"])

    def resolve_secret(reference: str) -> SecretValue:
        env_name = "NM_V6_FAKE_" + reference.upper().replace("-", "_")
        return SecretValue(reference, env_name, f"fixture-{reference}-value")

    executor = ActionExecutor(
        isolation_backend=TestIsolationBackend(),
        secret_resolver=resolve_secret,
    )
    recorder = FakeRecorder()
    recovery = RecoveryController(definitions, executor, recorder)
    delivery = DeliveryController(
        definitions,
        executor,
        recovery,
        git=git_controller,
    )
    workspace = Workspace("release-fixture", checkout, "fixture", None)
    target = EnvironmentTarget(
        environment_id="production",
        expected_identity="project-production",
        expected_fingerprint="fake-project-production-v1",
        identity_probe_action="identity_probe",
        preflight_action="preflight",
        deploy_action="deploy",
        health_action="health",
        rollback_action="rollback",
        post_rollback_verify_action="post_rollback_verify",
    )
    return delivery, workspace, target


class GitPolicyAcceptanceTests(unittest.TestCase):
    def test_ac052_git_failure_matrix_and_resync_invalidates_old_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, _ = create_git_fixture(root)
            (checkout / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(GitPolicyError, "dirty"):
                controller.fetch_dev()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote, checkout, controller, base = create_git_fixture(root)
            controller.fetch_dev()
            git("branch", "feature/candidate", base, cwd=checkout)
            old = controller.build_merge_proposal(
                source_ref="refs/heads/feature/candidate",
                target_branch="dev",
                strategy="fast_forward",
                purpose="stale-evidence",
                sharing_status="local",
                rationale="prove remote movement invalidates prior evidence",
                rollback_ref="refs/nm-v6/rollback/dev-old",
                gate_ids=("GATE-old",),
                authorization_id="AUTH-old",
            )
            moved = _advance_remote_dev(root, remote)
            with self.assertRaisesRegex(GitPolicyError, "stale"):
                controller.fetch_dev(reconcile_local=False)
            self.assertEqual(controller.fetch_dev(reconcile_local=True), moved)
            with self.assertRaisesRegex(GitPolicyError, "target moved"):
                controller.validate_proposal(old)
            fresh = controller.build_merge_proposal(
                source_ref="refs/heads/feature/candidate",
                target_branch="dev",
                strategy="merge_commit",
                purpose="fresh-evidence",
                sharing_status="local",
                rationale="new target requires new simulation and gate evidence",
                rollback_ref="refs/nm-v6/rollback/dev-fresh",
                gate_ids=("GATE-fresh",),
                authorization_id="AUTH-fresh",
            )
            self.assertEqual(fresh.target_commit, moved)
            tampered = replace(fresh, expected_result_tree=controller.tree_of(base))
            with self.assertRaisesRegex(GitPolicyError, "result tree mismatch"):
                controller.validate_proposal(tampered)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, _ = create_git_fixture(root)
            git("switch", "dev", cwd=checkout)
            (checkout / "local-only.txt").write_text("divergent\n", encoding="utf-8")
            git("add", "local-only.txt", cwd=checkout)
            git("commit", "-m", "local-only dev", cwd=checkout)
            git("switch", "main", cwd=checkout)
            with self.assertRaisesRegex(GitPolicyError, "divergent"):
                controller.fetch_dev()
            with self.assertRaisesRegex(GitPolicyError, "invalid prefix"):
                controller.create_work_branch("invalid/work")
            git("remote", "set-url", "origin", str(root / "missing.git"), cwd=checkout)
            with self.assertRaisesRegex(GitPolicyError, "failed to fetch"):
                controller.fetch_branch("dev")

    def test_ac057_nonprotected_grants_are_exact_one_time_and_action_separated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote, checkout, _, base = create_git_fixture(root)
            store = Store(root / "git-authority.sqlite3")
            reducer = Reducer(store, evidence_store=EvidenceStore(root / "evidence"))
            run_id = "run-git-ref"
            reducer.create_run(
                run_id=run_id,
                spec_hash="a" * 64,
                config_hash="b" * 64,
                mode="staged",
                run_kind="normal",
                actor="git-test",
                idempotency_key="create-git-ref-run",
            )
            private_key = root / "git-test-admin-private.pem"
            public_key = root / "git-test-admin-public.pem"
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
            verifier = OpenSSLSignatureVerifier({"git-test-admin": public_key})
            controller = GitController(checkout, nonprotected_store=store)
            expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
            grant = {
                "grant_id": "grant-backup-exact",
                "action": "push_backup",
                "remote": "origin",
                "ref": "refs/heads/review/exact",
                "expected_sha": base,
                "force": False,
                "one_time": True,
                "expires_at": expires,
                "administrator_authorization_id": "AUTH-git-backup-001",
            }
            _import_nonprotected_grant(
                root=root,
                reducer=reducer,
                verifier=verifier,
                private_key=private_key,
                run_id=run_id,
                sequence=1,
                grant=grant,
            )
            invalid = (
                {**grant, "grant_id": "wrong-remote", "remote": "upstream"},
                {**grant, "grant_id": "wrong-ref", "ref": "refs/heads/main"},
                {**grant, "grant_id": "force", "force": True},
                {**grant, "grant_id": "reusable", "one_time": False},
                {
                    **grant,
                    "grant_id": "expired",
                    "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                },
                {
                    **grant,
                    "grant_id": "unsigned-forgery",
                    "administrator_authorization_id": "AUTH-does-not-exist-999",
                },
            )
            for value in invalid:
                with self.subTest(grant_id=value["grant_id"]), self.assertRaises(
                    GitPolicyError
                ):
                    controller.execute_nonprotected_ref_grant(value, base)

            pushed = controller.execute_nonprotected_ref_grant(grant, base)
            self.assertEqual(pushed.observed_after, base)
            restarted = Store(store.path)
            restarted_controller = GitController(checkout, nonprotected_store=restarted)
            with self.assertRaisesRegex(GitPolicyError, "already consumed"):
                restarted_controller.execute_nonprotected_ref_grant(grant, base)
            restarted.close()
            with self.assertRaises(GitPolicyError):
                controller.execute_nonprotected_ref_grant(
                    {**grant, "grant_id": "backup-cannot-delete"}
                )
            delete = {
                **grant,
                "grant_id": "grant-delete-new",
                "action": "delete_remote",
                "administrator_authorization_id": "AUTH-git-delete-002",
            }
            _import_nonprotected_grant(
                root=root,
                reducer=reducer,
                verifier=verifier,
                private_key=private_key,
                run_id=run_id,
                sequence=2,
                grant=delete,
            )
            receipt = controller.execute_nonprotected_ref_grant(delete)
            self.assertIsNone(receipt.observed_after)
            self.assertFalse(receipt.force)

            race_backup = {
                **grant,
                "grant_id": "grant-backup-delete-race",
                "ref": "refs/heads/review/delete-race",
                "administrator_authorization_id": "AUTH-git-backup-race-003",
            }
            _import_nonprotected_grant(
                root=root,
                reducer=reducer,
                verifier=verifier,
                private_key=private_key,
                run_id=run_id,
                sequence=3,
                grant=race_backup,
            )
            controller.execute_nonprotected_ref_grant(race_backup, base)

            updater = root / "delete-race-updater"
            git("clone", str(remote), str(updater), cwd=root)
            git("config", "user.name", "Race Updater", cwd=updater)
            git("config", "user.email", "race@example.invalid", cwd=updater)
            git(
                "switch",
                "-c",
                "review/delete-race",
                "origin/review/delete-race",
                cwd=updater,
            )
            (updater / "race.txt").write_text("moved after observation\n", encoding="utf-8")
            git("add", "race.txt", cwd=updater)
            git("commit", "-m", "move nonprotected ref during delete", cwd=updater)
            moved = git("rev-parse", "HEAD", cwd=updater)
            race_delete = {
                **race_backup,
                "grant_id": "grant-delete-race",
                "action": "delete_remote",
                "administrator_authorization_id": "AUTH-git-delete-race-004",
            }
            _import_nonprotected_grant(
                root=root,
                reducer=reducer,
                verifier=verifier,
                private_key=private_key,
                run_id=run_id,
                sequence=4,
                grant=race_delete,
            )
            original_run_command = git_controller_module.run_command
            raced = False

            def move_after_final_observation(argv, **kwargs):
                nonlocal raced
                lease = (
                    "--force-with-lease=refs/heads/review/delete-race:"
                    f"{base}"
                )
                if (
                    not raced
                    and tuple(argv[:3]) == ("git", "push", "--porcelain")
                    and lease in argv
                    and ":refs/heads/review/delete-race" in argv
                ):
                    raced = True
                    git(
                        "push",
                        "origin",
                        f"{moved}:refs/heads/review/delete-race",
                        cwd=updater,
                    )
                return original_run_command(argv, **kwargs)

            with patch.object(
                git_controller_module,
                "run_command",
                side_effect=move_after_final_observation,
            ):
                with self.assertRaisesRegex(GitPolicyError, "CAS rejected a moved ref"):
                    controller.execute_nonprotected_ref_grant(race_delete)
            self.assertTrue(raced)
            self.assertEqual(controller.remote_head("review/delete-race"), moved)

    def test_protected_integration_preobserves_remote_and_restores_local_on_push_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote, checkout, controller, base = create_git_fixture(root)
            controller.fetch_dev()
            git("branch", "feature/stale-before-integrate", base, cwd=checkout)
            proposal = controller.build_merge_proposal(
                source_ref="refs/heads/feature/stale-before-integrate",
                target_branch="dev",
                strategy="fast_forward",
                purpose="preobserve-remote",
                sharing_status="local",
                rationale="remote movement must precede any local protected mutation",
                rollback_ref="refs/nm-v6/rollback/dev-stale",
                gate_ids=("GATE-stale",),
                authorization_id="AUTH-stale",
            )
            _advance_remote_dev(root, remote, "stale-before-integrate.txt")
            with self.assertRaisesRegex(GitPolicyError, "moved before integration"):
                controller.execute_proposal(proposal)
            self.assertEqual(
                controller.resolve_commit("refs/heads/dev"),
                base,
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote, checkout, controller, base = create_git_fixture(root)
            controller.create_work_branch("feature/remote-race")
            git("switch", "feature/remote-race", cwd=checkout)
            (checkout / "race.txt").write_text("candidate\n", encoding="utf-8")
            git("add", "race.txt", cwd=checkout)
            git("commit", "-m", "candidate before remote race", cwd=checkout)
            git("switch", "main", cwd=checkout)
            proposal = controller.build_merge_proposal(
                source_ref="refs/heads/feature/remote-race",
                target_branch="dev",
                strategy="fast_forward",
                purpose="restore-after-remote-race",
                sharing_status="local",
                rationale="remote movement after integration must restore local dev",
                rollback_ref="refs/nm-v6/rollback/dev-race",
                gate_ids=("GATE-race",),
                authorization_id="AUTH-race",
            )
            receipt = controller.execute_proposal(proposal)
            moved = _advance_remote_dev(root, remote, "race-remote.txt")
            with self.assertRaisesRegex(GitPolicyError, "moved before push"):
                controller.push_protected_cas(
                    "dev",
                    expected_remote=base,
                    new_commit=receipt.target_after,
                    proposal=proposal,
                )
            self.assertEqual(controller.resolve_commit("refs/heads/dev"), base)
            self.assertEqual(controller.remote_head("dev"), moved)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote, checkout, controller, base = create_git_fixture(root)
            controller.create_work_branch("feature/rejected-push")
            git("switch", "feature/rejected-push", cwd=checkout)
            (checkout / "rejected.txt").write_text("candidate\n", encoding="utf-8")
            git("add", "rejected.txt", cwd=checkout)
            git("commit", "-m", "candidate rejected by remote", cwd=checkout)
            candidate = git("rev-parse", "HEAD", cwd=checkout)
            git("switch", "main", cwd=checkout)
            proposal = controller.build_merge_proposal(
                source_ref="refs/heads/feature/rejected-push",
                target_branch="dev",
                strategy="fast_forward",
                purpose="restore-on-cas-failure",
                sharing_status="local",
                rationale="failed remote effect must leave local dev unchanged",
                rollback_ref="refs/nm-v6/rollback/dev-rejected",
                gate_ids=("GATE-rejected",),
                authorization_id="AUTH-rejected",
            )
            receipt = controller.execute_proposal(proposal)
            self.assertEqual(controller.resolve_commit("refs/heads/dev"), candidate)
            hook = remote / "hooks/pre-receive"
            hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            hook.chmod(0o755)
            with self.assertRaisesRegex(GitPolicyError, "CAS push failed"):
                controller.push_protected_cas(
                    "dev",
                    expected_remote=base,
                    new_commit=receipt.target_after,
                    proposal=proposal,
                )
            self.assertEqual(controller.resolve_commit("refs/heads/dev"), base)
            self.assertEqual(controller.remote_head("dev"), base)

    def test_ac060_cleanup_rechecks_current_facts_and_records_fresh_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, controller, base = create_git_fixture(root)
            git("branch", "feature/recheck", base, cwd=checkout)
            receipt = _cleanup_receipt(controller, base)
            administrator_needed = controller.evaluate_cleanup(
                CleanupFacts(
                    "feature/recheck",
                    "f" * 40,
                    receipt,
                    ancestry_proven=True,
                )
            )
            self.assertEqual(administrator_needed.result, "request_administrator")

            current = CleanupFacts(
                "feature/recheck",
                base,
                receipt,
                ancestry_proven=True,
            )
            fresh_decision = controller.evaluate_cleanup(current)
            self.assertEqual(fresh_decision.result, "delete_local")
            changed = replace(current, live_session=True)
            with self.assertRaisesRegex(GitPolicyError, "facts changed"):
                controller.delete_local_branch(
                    fresh_decision,
                    current_facts=changed,
                )
            self.assertEqual(
                controller.resolve_commit("refs/heads/feature/recheck"), base
            )

            reevaluated = controller.evaluate_cleanup(current)
            deletion = controller.delete_local_branch(
                reevaluated,
                current_facts=current,
            )
            self.assertEqual(deletion.result, "deleted")
            self.assertEqual(deletion.deleted_head, base)
            self.assertTrue(deletion.reevaluated_at)
            self.assertIsNone(
                controller.try_resolve_commit("refs/heads/feature/recheck")
            )

    def test_cleanup_ignores_false_caller_live_fact_claims_and_reads_store(self) -> None:
        for blocker, expected_reason in (
            ("lease", "live_lease"),
            ("session", "live_session"),
            ("workspace", "dependent_workspace"),
        ):
            with self.subTest(blocker=blocker), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, checkout, fixture_controller, head = create_git_fixture(root)
                branch = f"feature/canonical-{blocker}"
                git("branch", branch, head, cwd=checkout)
                store = Store(root / "state.sqlite3")
                evidence = EvidenceStore(root / "evidence")
                reducer = Reducer(store, evidence_store=evidence)
                run_id = f"run-cleanup-{blocker}"
                reducer.create_run(
                    run_id=run_id,
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    idempotency_key=f"create:{run_id}",
                )
                _record_cleanup_responsibility_closure(
                    reducer=reducer,
                    evidence=evidence,
                    run_id=run_id,
                    branch=branch,
                    head=head,
                )
                run = store.get_run(run_id)
                if run is None:
                    raise AssertionError(f"missing run: {run_id}")
                if blocker == "lease":
                    reducer.acquire_lease(
                        run_id=run_id,
                        expected_revision=int(run["revision"]),
                        resource_id="TASK-cleanup-live",
                        owner="worker-cleanup-live",
                        lease_seconds=300,
                        idempotency_key="cleanup-live-lease",
                    )
                else:
                    payload: dict[str, object]
                    if blocker == "session":
                        payload = {
                            "branch": branch,
                            "session_id": "SESSION-cleanup-live",
                        }
                    else:
                        workspace = root / "dependent-workspace"
                        workspace.mkdir()
                        payload = {
                            "branch": branch,
                            "workspace_path": str(workspace),
                        }
                    reducer.create_entity(
                        run_id=run_id,
                        expected_revision=int(run["revision"]),
                        machine="attempt",
                        entity_id=f"ATTEMPT-cleanup-{blocker}",
                        initial_state="CREATED",
                        idempotency_key=f"create-attempt:{blocker}",
                        payload=payload,
                    )
                controller = GitController(
                    checkout,
                    protected_authority=fixture_controller.protected_authority,
                    cleanup_store=store,
                )
                # All legacy caller booleans are false.  Only canonical Store
                # state is allowed to decide whether these facts are live.
                facts = CleanupFacts(
                    branch,
                    head,
                    _cleanup_receipt(controller, head),
                    ancestry_proven=True,
                    run_id=run_id,
                )
                decision = controller.evaluate_cleanup(facts)
                self.assertEqual(decision.result, "retain")
                self.assertIn(expected_reason, decision.reasons)
                with self.assertRaisesRegex(
                    GitPolicyError, "does not authorize local deletion"
                ):
                    controller.delete_local_branch(decision, current_facts=facts)
                self.assertEqual(controller.resolve_commit(f"refs/heads/{branch}"), head)
                store.close()

    def test_cleanup_fails_closed_without_responsibility_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, fixture_controller, head = create_git_fixture(root)
            branch = "feature/missing-cleanup-evidence"
            git("branch", branch, head, cwd=checkout)
            store = Store(root / "state.sqlite3")
            evidence = EvidenceStore(root / "evidence")
            reducer = Reducer(store, evidence_store=evidence)
            run_id = "run-cleanup-missing-evidence"
            reducer.create_run(
                run_id=run_id,
                spec_hash="a" * 64,
                config_hash="b" * 64,
                idempotency_key=f"create:{run_id}",
            )
            controller = GitController(
                checkout,
                protected_authority=fixture_controller.protected_authority,
                cleanup_store=store,
            )
            decision = controller.evaluate_cleanup(
                CleanupFacts(
                    branch,
                    head,
                    _cleanup_receipt(controller, head),
                    ancestry_proven=True,
                    run_id=run_id,
                )
            )
            self.assertEqual(decision.result, "request_administrator")
            self.assertIn("canonical_responsibility_evidence_missing", decision.reasons)
            self.assertTrue(decision.facts_digest)
            self.assertTrue(decision.decision_event_id)
            self.assertEqual(controller.resolve_commit(f"refs/heads/{branch}"), head)
            _record_cleanup_responsibility_closure(
                reducer=reducer,
                evidence=evidence,
                run_id=run_id,
                branch=branch,
                head=head,
            )
            reevaluated = controller.evaluate_cleanup(
                CleanupFacts(
                    branch,
                    head,
                    _cleanup_receipt(controller, head),
                    ancestry_proven=True,
                    run_id=run_id,
                )
            )
            self.assertEqual(reevaluated.result, "delete_local")
            self.assertGreater(
                int(reevaluated.input_revision or 0), int(decision.input_revision or 0)
            )
            self.assertNotEqual(reevaluated.facts_digest, decision.facts_digest)
            store.close()

    def test_cleanup_persists_fresh_facts_digest_and_execution_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, fixture_controller, head = create_git_fixture(root)
            branch = "feature/persisted-cleanup"
            git("branch", branch, head, cwd=checkout)
            store = Store(root / "state.sqlite3")
            evidence = EvidenceStore(root / "evidence")
            reducer = Reducer(store, evidence_store=evidence)
            run_id = "run-cleanup-persisted"
            reducer.create_run(
                run_id=run_id,
                spec_hash="a" * 64,
                config_hash="b" * 64,
                idempotency_key=f"create:{run_id}",
            )
            _record_cleanup_responsibility_closure(
                reducer=reducer,
                evidence=evidence,
                run_id=run_id,
                branch=branch,
                head=head,
            )
            controller = GitController(
                checkout,
                protected_authority=fixture_controller.protected_authority,
                cleanup_store=store,
            )
            facts = CleanupFacts(
                branch,
                head,
                _cleanup_receipt(controller, head),
                ancestry_proven=True,
                run_id=run_id,
            )
            decision = controller.evaluate_cleanup(facts)
            self.assertEqual(decision.result, "delete_local")
            self.assertTrue(decision.facts_digest)
            self.assertTrue(decision.decision_event_id)
            deletion = controller.delete_local_branch(decision, current_facts=facts)
            self.assertEqual(deletion.result, "deleted")
            self.assertTrue(deletion.facts_digest)
            self.assertTrue(deletion.decision_event_id)
            self.assertTrue(deletion.execution_event_id)
            self.assertIsNone(controller.try_resolve_commit(f"refs/heads/{branch}"))
            cleanup_events = [
                event
                for event in store.list_events(run_id)
                if event["event_type"] == "BRANCH_CLEANUP_DECIDED"
            ]
            self.assertEqual(
                [event["payload"]["record"]["record_kind"] for event in cleanup_events],
                ["decision", "decision", "execution_receipt"],
            )
            self.assertEqual(
                cleanup_events[-1]["payload"]["record"]["facts_digest"],
                deletion.facts_digest,
            )
            store.close()


class DeliveryBindingAcceptanceTests(unittest.TestCase):
    def test_ac050_release_publish_partial_unknown_are_observed_and_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, git_controller, _ = create_git_fixture(root)
            git("switch", "dev", cwd=checkout)
            delivery, workspace, _ = _template_delivery(checkout, git_controller)
            git("add", "0d-scripts/fake-action.py", cwd=checkout)
            git("commit", "-m", "add partial unknown fixture", cwd=checkout)
            source_commit = git("rev-parse", "HEAD", cwd=checkout)
            source_tree = git_controller.tree_of(source_commit)
            git("push", "origin", "dev", cwd=checkout)
            git("branch", "--force", "main", source_commit, cwd=checkout)
            git("push", "origin", "main", cwd=checkout)
            for flag in (
                "force-release-partial",
                "force-publish-unknown",
                "force-observe_release-unknown",
                "force-observe_publish-unknown",
            ):
                (checkout / flag).write_text("injected\n", encoding="utf-8")
            source = ReleaseSource(
                "dev",
                source_commit,
                source_tree,
                "s" * 64,
                "c" * 64,
            )
            metadata = delivery.release_metadata(
                workspace=workspace,
                action_id="release_metadata",
                source=source,
            )
            receipt = delivery.release(
                workspace=workspace,
                source=source,
                build_action="build",
                release_action="release",
                publish_action="publish",
                stable_commit=source_commit,
                stable_tree=source_tree,
                release_operation_id="OP-release-partial-001",
                publish_operation_id="OP-publish-unknown-001",
                grant_id="AUTH-release-reconcile-001",
                grant_revision=1,
                expected_tag=metadata.tag,
                expected_version=metadata.published_version,
                expected_release_metadata_digest=metadata.metadata_digest,
                expected_artifact_digest=hashlib.sha256(
                    source_commit.encode("utf-8")
                ).hexdigest(),
            )
            self.assertEqual(receipt.release_result.status, "partial")
            self.assertEqual(receipt.publish_result.status, "unknown")
            self.assertEqual(receipt.release_observation.classification, "completed")
            self.assertEqual(receipt.publish_observation.classification, "completed")
            self.assertIsNotNone(receipt.release_observation.reconciliation)
            self.assertIsNotNone(receipt.publish_observation.reconciliation)
            provider = json.loads(
                (checkout / ".nm-v6-fake-provider.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(provider["operations"]),
                {"OP-release-partial-001", "OP-publish-unknown-001"},
            )

    def test_ac031_ac032_authorized_rollback_and_failure_paths_require_attention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, _, recorder, _, delivery, target = create_delivery_fixture(root)
            (root / "force-unhealthy").write_text("yes", encoding="utf-8")
            rolled_back = delivery.deploy(
                workspace=workspace,
                target=target,
                artifact_digest="a" * 64,
                deploy_operation_id="OP-deploy-auto-001",
                grant_id="AUTH-deploy-auto-001",
                grant_revision=1,
                rollback_operation_id="OP-rollback-auto-001",
                rollback_authorized=True,
            )
            self.assertEqual(rolled_back.state, "ROLLED_BACK")
            self.assertIsNotNone(rolled_back.rollback)
            self.assertEqual(
                json.loads((root / "external-state.json").read_text(encoding="utf-8"))[
                    "deployed_version"
                ],
                "v1",
            )
            self.assertEqual(recorder.operations["OP-deploy-auto-001"]["status"], "succeeded")
            self.assertEqual(
                recorder.operations["OP-rollback-auto-001"]["status"], "succeeded"
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, _, _, _, delivery, target = create_delivery_fixture(root)
            (root / "force-unhealthy").write_text("yes", encoding="utf-8")
            (root / "force-post-rollback-failure").write_text("yes", encoding="utf-8")
            attention = delivery.deploy(
                workspace=workspace,
                target=target,
                artifact_digest="b" * 64,
                deploy_operation_id="OP-deploy-postfail-001",
                grant_id="AUTH-deploy-postfail-001",
                grant_revision=1,
                rollback_operation_id="OP-rollback-postfail-001",
                rollback_authorized=True,
            )
            self.assertEqual(attention.state, "ATTENTION_REQUIRED")
            self.assertIsNotNone(attention.rollback)
            assert attention.rollback is not None
            self.assertEqual(attention.rollback.state, "ATTENTION_REQUIRED")
            self.assertFalse(attention.rollback.verification.observed_state["healthy"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, _, recorder, _, delivery, target = create_delivery_fixture(root)
            (root / "force-unhealthy").write_text("yes", encoding="utf-8")
            (root / "force-rollback-partial").write_text("yes", encoding="utf-8")
            (root / "force-unknown-OP-rollback-rbfail-001").write_text(
                "yes", encoding="utf-8"
            )
            (root / "force-reconcile-unknown-OP-rollback-rbfail-001").write_text(
                "yes", encoding="utf-8"
            )
            with self.assertRaisesRegex(RecoveryError, "ambiguous"):
                delivery.deploy(
                    workspace=workspace,
                    target=target,
                    artifact_digest="c" * 64,
                    deploy_operation_id="OP-deploy-rbfail-001",
                    grant_id="AUTH-deploy-rbfail-001",
                    grant_revision=1,
                    rollback_operation_id="OP-rollback-rbfail-001",
                    rollback_authorized=True,
                )
            self.assertEqual(
                recorder.operations["OP-rollback-rbfail-001"]["status"], "unknown"
            )

    def test_ac053_normal_and_hotfix_release_binding_chain_rejects_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, git_controller, _ = create_git_fixture(root)
            git("switch", "dev", cwd=checkout)
            delivery, workspace, _ = _template_delivery(checkout, git_controller)
            git("add", "0d-scripts/fake-action.py", cwd=checkout)
            git("commit", "-m", "add deterministic release fixture", cwd=checkout)
            source_commit = git("rev-parse", "HEAD", cwd=checkout)
            git("push", "origin", "dev", cwd=checkout)
            git("branch", "--force", "main", source_commit, cwd=checkout)
            git("push", "origin", "main", cwd=checkout)
            source_tree = git_controller.tree_of(source_commit)
            source = ReleaseSource(
                "dev",
                source_commit,
                source_tree,
                "s" * 64,
                "c" * 64,
            )
            metadata = delivery.release_metadata(
                workspace=workspace,
                action_id="release_metadata",
                source=source,
            )
            with self.assertRaisesRegex(RecoveryError, "RELEASE_GATE"):
                delivery.release(
                    workspace=workspace,
                    source=source,
                    build_action="build",
                    release_action="release",
                    publish_action="publish",
                    stable_commit=source_commit,
                    stable_tree=source_tree,
                    release_operation_id="OP-release-substituted-001",
                    publish_operation_id="OP-publish-substituted-001",
                    grant_id="AUTH-release-normal",
                    grant_revision=1,
                    expected_tag=metadata.tag,
                    expected_version=metadata.published_version,
                    expected_release_metadata_digest=metadata.metadata_digest,
                    expected_artifact_digest="0" * 64,
                )
            release = delivery.release(
                workspace=workspace,
                source=source,
                build_action="build",
                release_action="release",
                publish_action="publish",
                stable_commit=source_commit,
                stable_tree=source_tree,
                release_operation_id="OP-release-normal-001",
                publish_operation_id="OP-publish-normal-001",
                grant_id="AUTH-release-normal",
                grant_revision=1,
                expected_tag=metadata.tag,
                expected_version=metadata.published_version,
                expected_release_metadata_digest=metadata.metadata_digest,
                expected_artifact_digest=hashlib.sha256(
                    source_commit.encode("utf-8")
                ).hexdigest(),
            )
            self.assertEqual(
                release.artifact_digest,
                hashlib.sha256(source_commit.encode("utf-8")).hexdigest(),
            )
            self.assertEqual(release.tag_target, source_commit)
            self.assertEqual(release.stable_tree, source_tree)
            self.assertTrue(release.release_result.effect_id)
            self.assertTrue(release.publish_result.effect_id)
            previous_main = git("rev-parse", f"{source_commit}^", cwd=checkout)
            git(
                "update-ref",
                "refs/heads/main",
                previous_main,
                source_commit,
                cwd=checkout,
            )
            with self.assertRaisesRegex(ContractError, "local stable ref"):
                delivery._verify_release_source(
                    source,
                    stable_commit=source_commit,
                    stable_tree=source_tree,
                )
            git(
                "update-ref",
                "refs/heads/main",
                source_commit,
                previous_main,
                cwd=checkout,
            )

            observed = release.publish_observation.observation
            expected = {
                "release_source_kind": source.kind,
                "release_source_commit": source.commit,
                "release_source_tree": source.tree,
                "stable_commit": release.stable_commit,
                "stable_tree": release.stable_tree,
                "artifact_digest": release.artifact_digest,
                "effect_id": release.publish_result.effect_id or "",
                "tag": metadata.tag,
                "published_version": metadata.published_version,
                "release_metadata_digest": metadata.metadata_digest,
            }
            for field, expected_value in expected.items():
                replacement = "0" * len(expected_value)
                if replacement == expected_value:
                    replacement = "x" + expected_value[1:]
                tampered = replace(
                    observed,
                    observed_state={**observed.observed_state, field: replacement},
                )
                with self.subTest(field=field), self.assertRaises(RecoveryError):
                    delivery._require_release_binding(
                        tampered,
                        source=source,
                        stable_commit=release.stable_commit,
                        stable_tree=release.stable_tree,
                        artifact_digest=release.artifact_digest,
                        effect_id=release.publish_result.effect_id or "",
                        action="tampered publication",
                        release_tag=metadata.tag,
                        published_version=metadata.published_version,
                        release_metadata_digest=metadata.metadata_digest,
                    )

            for field, value in (
                ("tag", None),
                ("published_version", None),
                ("tag_target", "f" * 40),
            ):
                state = dict(observed.observed_state)
                if value is None:
                    state.pop(field, None)
                else:
                    state[field] = value
                tampered = replace(observed, observed_state=state)
                with self.subTest(publication_field=field), self.assertRaises(
                    RecoveryError
                ):
                    delivery._publication_identity(
                        tampered,
                        mutation=tampered,
                        stable_commit=source_commit,
                        expected_tag="v0.1.0",
                        expected_version="0.1.0",
                    )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, checkout, git_controller, _ = create_git_fixture(root)
            git("switch", "dev", cwd=checkout)
            (checkout / "unreleased-dev.txt").write_text("future\n", encoding="utf-8")
            git("add", "unreleased-dev.txt", cwd=checkout)
            git("commit", "-m", "unreleased dev work", cwd=checkout)
            dev_head = git("rev-parse", "HEAD", cwd=checkout)
            git("push", "origin", "dev", cwd=checkout)
            git("switch", "main", cwd=checkout)
            git("switch", "-c", "hotfix/release-binding", cwd=checkout)
            delivery, workspace, _ = _template_delivery(checkout, git_controller)
            git("add", "0d-scripts/fake-action.py", cwd=checkout)
            git("commit", "-m", "hotfix release fixture", cwd=checkout)
            hotfix_commit = git("rev-parse", "HEAD", cwd=checkout)
            git("branch", "--force", "main", hotfix_commit, cwd=checkout)
            git("push", "origin", "main", cwd=checkout)
            hotfix_tree = git_controller.tree_of(hotfix_commit)
            git("switch", "dev", cwd=checkout)
            git(
                "merge",
                "--no-ff",
                "hotfix/release-binding",
                "-m",
                "reconcile verified hotfix",
                cwd=checkout,
            )
            reconciled_dev = git("rev-parse", "HEAD", cwd=checkout)
            git("push", "origin", "dev", cwd=checkout)
            hotfix = ReleaseSource(
                "hotfix_stable",
                hotfix_commit,
                hotfix_tree,
                "a" * 64,
                "c" * 64,
                "GATE-hotfix-dev-reconciliation",
            )
            reconciliation_evidence_id = "EVID-hotfix-reconciliation-001"
            reconciliation_facts = gate_context(
                "HOTFIX_RECONCILIATION_RESULT_GATE",
                reconciliation_evidence_id,
                run_id="run-hotfix-release",
                source_commit=hotfix_commit,
                candidate_commit=reconciled_dev,
            )
            reconciliation_facts["target_commit"] = dev_head
            reconciliation_receipt = complete_gate_receipt(
                "run-hotfix-release",
                reconciliation_evidence_id,
                subject_ids=list(
                    required_prerequisites(
                        "HOTFIX_RECONCILIATION_RESULT_GATE"
                    )
                ),
                config_hash="c" * 64,
                source_commit=hotfix_commit,
                candidate_commit=reconciled_dev,
                assertions={
                    name: True
                    for name in required_prerequisites(
                        "HOTFIX_RECONCILIATION_RESULT_GATE"
                    )
                },
            )
            reconciliation = GateEvaluator(
                lambda requested: (
                    reconciliation_receipt
                    if requested == reconciliation_evidence_id
                    else None
                ),
                evidence_validator=lambda value: None,
            ).evaluate(
                GateObservation(
                    gate_type="HOTFIX_RECONCILIATION_RESULT_GATE",
                    subject_ids=("hotfix/release-binding",),
                    context=reconciliation_facts,
                    evidence_ids=(reconciliation_evidence_id,),
                    evaluator="hotfix-release-fixture",
                ),
                gate_id="GATE-hotfix-dev-reconciliation",
                spec_hash="a" * 64,
                config_hash="c" * 64,
                run_revision=1,
            )
            with self.assertRaisesRegex(ContractError, "requires"):
                delivery._verify_hotfix_reconciliation(hotfix, decision=None)
            metadata = delivery.release_metadata(
                workspace=workspace,
                action_id="release_metadata",
                source=hotfix,
            )
            receipt = delivery.release(
                workspace=workspace,
                source=hotfix,
                build_action="build",
                release_action="release",
                publish_action="publish",
                stable_commit=hotfix_commit,
                stable_tree=hotfix_tree,
                release_operation_id="OP-release-hotfix-001",
                publish_operation_id="OP-publish-hotfix-001",
                grant_id="AUTH-release-hotfix",
                grant_revision=1,
                expected_tag=metadata.tag,
                expected_version=metadata.published_version,
                expected_release_metadata_digest=metadata.metadata_digest,
                expected_artifact_digest=hashlib.sha256(
                    hotfix_commit.encode("utf-8")
                ).hexdigest(),
                hotfix_reconciliation_decision=reconciliation,
            )
            self.assertEqual(receipt.source.kind, "hotfix_stable")
            self.assertEqual(receipt.source.commit, hotfix_commit)
            self.assertNotEqual(receipt.source.commit, dev_head)
            with self.assertRaisesRegex(RecoveryError, "not bound"):
                delivery._require_artifact_binding(
                    receipt.publish_result,
                    "0" * 64,
                    "substituted publish",
                )


class AuditAndEnvironmentAcceptanceTests(unittest.TestCase):
    def test_ac029_not_started_retries_same_operation_id_under_original_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root / "state.sqlite3")
            reducer = Reducer(store)
            run_id = "run-operation-retry"
            try:
                reducer.create_run(
                    run_id=run_id,
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    mode="auto",
                    idempotency_key="create-operation-retry",
                )
                requested = reducer.create_authorization_request(
                    run_id=run_id,
                    expected_revision=0,
                    request_id="AUTHREQ-operation-retry",
                    request_type="grant",
                    scope={
                        "run_id": run_id,
                        "spec_hash": "a" * 64,
                        "config_hash": "b" * 64,
                        "allowed_actions": ["credential_probe"],
                        "allowed_environments": ["production"],
                        "allowed_protected_refs": [],
                    },
                    expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                    idempotency_key="request-operation-retry",
                    nonce="operation-retry-nonce",
                )["request"]
                grant_id = "AUTH-operation-retry-001"
                reducer.import_authorization(
                    {
                        **_authorization_record(
                            record_type="grant",
                            identifier=grant_id,
                            request=requested,
                        ),
                        "allowed_actions": ["credential_probe"],
                        "allowed_environments": ["production"],
                    },
                    ShapeOnlyVerifier(),
                    expected_revision=1,
                    idempotency_key="import-operation-retry",
                )
                operation_id = "OP-operation-retry-001"
                reducer.start_operation(
                    run_id=run_id,
                    expected_revision=2,
                    operation_id=operation_id,
                    action_id="credential_probe",
                    operation_kind="agent",
                    idempotency_key=operation_id,
                    authorization_id=grant_id,
                    scope={"environment_id": "production"},
                )
                reducer.record_operation_observation(
                    run_id=run_id,
                    expected_revision=3,
                    observation=OperationObservation(
                        operation_id=operation_id,
                        action_id="credential_probe",
                        status="not_started",
                        effect_id=None,
                        result={"classification": "not_started"},
                    ),
                    idempotency_key="observe-operation-not-started",
                )
                operation = store.get_operation(operation_id)
                self.assertEqual(operation["status"], "not_started")
                restarted = reducer.restart_operation(
                    run_id=run_id,
                    expected_revision=4,
                    operation_id=operation_id,
                    authorization_id=grant_id,
                    grant_revision=operation["grant_revision"],
                    idempotency_key="restart-operation-retry",
                )
                self.assertEqual(restarted["status"], "started")
                self.assertEqual(store.get_operation(operation_id)["status"], "started")
                with self.assertRaisesRegex(TransitionError, "not_started"):
                    reducer.restart_operation(
                        run_id=run_id,
                        expected_revision=5,
                        operation_id=operation_id,
                        authorization_id=grant_id,
                        grant_revision=operation["grant_revision"],
                        idempotency_key="restart-operation-again",
                    )
                events = store.list_events(run_id)
                self.assertEqual(
                    sum(
                        event["event_type"] == "EXTERNAL_OPERATION_STARTED"
                        for event in events
                    ),
                    1,
                )
                self.assertEqual(
                    sum(
                        event["event_type"] == "EXTERNAL_OPERATION_RESTARTED"
                        for event in events
                    ),
                    1,
                )
                store.rebuild_materialized_views()
                self.assertEqual(store.get_operation(operation_id)["status"], "started")
            finally:
                store.close()

    def test_ac028_environment_mismatch_persists_evidence_and_requires_attention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root / "state.sqlite3")
            evidence_store = EvidenceStore(root / "evidence")
            reducer = Reducer(store, evidence_store=evidence_store)
            try:
                reducer.create_run(
                    run_id="run-environment",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    idempotency_key="create-environment-run",
                )
                receipt_data = base_receipt(
                    "run-environment", "EVID-environment-identity-001"
                )
                receipt_data.update(
                    {
                        "evidence_type": "environment_identity",
                        "subject_ids": ["production"],
                        "assertions": {},
                        "environment_id": "unexpected-production",
                        "environment_fingerprint": "unexpected-fingerprint-v1",
                        "artifact_digest": "d" * 64,
                        "command_action_id": "identity_probe",
                    }
                )
                receipt = evidence_store.persist(
                    receipt_data,
                    b'{"environment_id":"unexpected-production"}',
                    b"",
                )
                reducer.record_evidence(
                    run_id="run-environment",
                    expected_revision=0,
                    receipt=receipt,
                    idempotency_key="record-environment-identity",
                )
                controller = WorkflowController(reducer, store)
                proposal = controller.environment_mismatch_proposal(
                    run_id="run-environment",
                    expected_revision=1,
                    current_state="DISCOVERING",
                    evidence_id="EVID-environment-identity-001",
                    configured_identity="project-production",
                    configured_fingerprint="expected-fingerprint-v1",
                    authorized_identity="project-production",
                    authorized_fingerprint="expected-fingerprint-v1",
                )
                result = controller.submit(proposal)
                self.assertEqual(result["state"], "ATTENTION_REQUIRED")
                self.assertEqual(store.get_run("run-environment")["state"], "ATTENTION_REQUIRED")
                self.assertEqual(
                    store.get_evidence("EVID-environment-identity-001")[
                        "environment_id"
                    ],
                    "unexpected-production",
                )
                last_event = store.list_events("run-environment")[-1]
                proposal_payload = last_event["payload"]["request"]["proposal"]["payload"]
                self.assertEqual(
                    proposal_payload["evidence_ids"],
                    ["EVID-environment-identity-001"],
                )
                self.assertTrue(proposal_payload["actors_fenced"])

                with self.assertRaisesRegex(ContractError, "matches"):
                    controller.environment_mismatch_proposal(
                        run_id="run-environment",
                        expected_revision=2,
                        current_state="ATTENTION_REQUIRED",
                        evidence_id="EVID-environment-identity-001",
                        configured_identity="unexpected-production",
                        configured_fingerprint="unexpected-fingerprint-v1",
                        authorized_identity="unexpected-production",
                        authorized_fingerprint="unexpected-fingerprint-v1",
                    )
            finally:
                store.close()

    def test_ac055_every_audit_class_is_append_only_tamper_evident_and_restart_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root / "state.sqlite3")
            evidence_store = EvidenceStore(root / "evidence")
            reducer = Reducer(store, evidence_store=evidence_store)
            run_id = "run-audit"
            try:
                reducer.create_run(
                    run_id=run_id,
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    idempotency_key="create-audit-run",
                )
                reducer.transition(
                    TransitionProposal(
                        run_id=run_id,
                        expected_revision=0,
                        event="DRAFT_SPEC",
                        actor="planner",
                        idempotency_key="audit-state-transition",
                        payload={"discovery_complete": True},
                    )
                )

                for record_type in ("grant", "approval"):
                    request_result = reducer.create_authorization_request(
                        run_id=run_id,
                        expected_revision=_revision(store, run_id),
                        request_id=f"AUTHREQ-audit-{record_type}",
                        request_type=record_type,
                        scope={
                            "run_id": run_id,
                            "spec_hash": "a" * 64,
                            "config_hash": "b" * 64,
                            "allowed_actions": ["audit_fixture"],
                            "allowed_environments": [],
                            "allowed_protected_refs": [],
                        },
                        expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                        idempotency_key=f"request-audit-{record_type}",
                        nonce=f"audit-{record_type}-nonce",
                    )
                    request = request_result["request"]
                    reducer.import_authorization(
                        _authorization_record(
                            record_type=record_type,
                            identifier=f"AUTH-audit-{record_type}-001",
                            request=request,
                        ),
                        ShapeOnlyVerifier(),
                        expected_revision=_revision(store, run_id),
                        idempotency_key=f"import-audit-{record_type}",
                    )

                receipt_data = base_receipt(run_id, "EVID-audit-command-001")
                receipt_data["subject_ids"] = list(
                    required_prerequisites("PLAN_GATE")
                )
                receipt_data["assertions"] = {
                    name: True
                    for name in required_prerequisites("PLAN_GATE")
                }
                receipt = evidence_store.persist(
                    receipt_data,
                    b"audit fixture verification passed",
                    b"",
                )
                reducer.record_evidence(
                    run_id=run_id,
                    expected_revision=_revision(store, run_id),
                    receipt=receipt,
                    idempotency_key="record-audit-evidence",
                )
                gate_type = "PLAN_GATE"
                facts = gate_context(
                    gate_type,
                    "EVID-audit-command-001",
                    run_id=run_id,
                )
                revision = _revision(store, run_id)
                decision = GateEvaluator(
                    store.get_evidence,
                    evidence_validator=evidence_store.validate,
                ).evaluate(
                    GateObservation(
                        gate_type=gate_type,
                        subject_ids=(run_id, "PHASE-001"),
                        context=facts,
                        evidence_ids=("EVID-audit-command-001",),
                        evaluator="audit-fixture-gate",
                    ),
                    gate_id="GATE-audit-plan-001",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    run_revision=revision,
                )
                reducer.record_gate(
                    run_id=run_id,
                    expected_revision=revision,
                    decision=decision,
                    idempotency_key="record-audit-gate",
                )

                for event_type in sorted(DOMAIN_EVENT_TYPES):
                    reducer.record_domain_event(
                        run_id=run_id,
                        expected_revision=_revision(store, run_id),
                        event_type=event_type,
                        payload={
                            "fixture": event_type.lower(),
                            "operation_id": "OP-audit-domain-001",
                        },
                        idempotency_key=f"domain-{event_type.lower()}",
                        actor="deterministic-audit-fixture",
                    )
                with self.assertRaisesRegex(ContractError, "unsupported"):
                    reducer.record_domain_event(
                        run_id=run_id,
                        expected_revision=_revision(store, run_id),
                        event_type="ARBITRARY_AGENT_EVENT",
                        payload={},
                        idempotency_key="forbidden-domain-event",
                        actor="agent",
                    )

                queued = reducer.enqueue_notification(
                    run_id=run_id,
                    expected_revision=_revision(store, run_id),
                    intent=NotificationIntent(
                        route="fixture-feishu",
                        severity="progress",
                        payload={"message": "audit fixture"},
                    ),
                    idempotency_key="enqueue-audit-notification",
                )
                self.assertTrue(queued["queued"])
                notification_id = store.list_outbox()[0]["notification_id"]
                reducer.record_notification_attempt(
                    run_id=run_id,
                    expected_revision=_revision(store, run_id),
                    notification_id=notification_id,
                    succeeded=False,
                    error="injected transport failure",
                    idempotency_key="audit-notification-failed",
                )
                reducer.record_notification_attempt(
                    run_id=run_id,
                    expected_revision=_revision(store, run_id),
                    notification_id=notification_id,
                    succeeded=True,
                    idempotency_key="audit-notification-delivered",
                )

                rows = store.list_audit()
                verify_audit_chain(rows)
                event_types = {row["event_type"] for row in rows}
                self.assertTrue(DOMAIN_EVENT_TYPES <= event_types)
                self.assertTrue(
                    {
                        "STATE_TRANSITION",
                        "AUTHORIZATION_IMPORTED",
                        "EVIDENCE_RECORDED",
                        "GATE_DECIDED",
                        "NOTIFICATION_DELIVERY_FAILED",
                        "NOTIFICATION_DELIVERED",
                    }
                    <= event_types
                )
                imported_types = {
                    row["payload"]["record_type"]
                    for row in rows
                    if row["event_type"] == "AUTHORIZATION_IMPORTED"
                }
                self.assertEqual(imported_types, {"grant", "approval"})

                tampered = [dict(row) for row in rows]
                tampered[1]["sequence"] = tampered[0]["sequence"]
                with self.assertRaises(TransitionError):
                    verify_audit_chain(tampered)
                direct = sqlite3.connect(store.path)
                try:
                    with self.assertRaises(sqlite3.DatabaseError):
                        direct.execute(
                            "UPDATE audit_records SET actor = 'tamper' WHERE sequence = 1"
                        )
                    with self.assertRaises(sqlite3.DatabaseError):
                        direct.execute("DELETE FROM audit_records WHERE sequence = 1")
                finally:
                    direct.close()

                before = root / "audit-before-restart.json"
                after = root / "audit-after-restart.json"
                export_audit(rows, before)
                store.integrity_check()
                store.rebuild_materialized_views()
                restarted = Store(store.path)
                try:
                    restarted.integrity_check()
                    export_audit(restarted.list_audit(), after)
                finally:
                    restarted.close()
                self.assertEqual(before.read_bytes(), after.read_bytes())
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
