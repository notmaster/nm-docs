from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from nmv6.cleanup_review import (  # noqa: E402
    CLEANUP_FACTS_SCHEMA_VERSION,
    CLEANUP_REVIEW_CONTEXT_SOURCE,
    INTEGRATION_PROOF_SCHEMA_VERSION,
    INTEGRATION_RECEIPT_SCHEMA_VERSION,
    OBSERVATION_FIELDS,
    OBSERVATION_SCHEMA_VERSION,
    REQUEST_FIELDS,
    REQUEST_SCHEMA_VERSION,
    build_cleanup_review_context_manifest,
    cleanup_review_context_item,
    cleanup_review_delete_eligible,
    cleanup_review_risk_flags,
    deterministic_fake_cleanup_review,
    seal_cleanup_facts,
    seal_cleanup_integration_proof,
    seal_cleanup_integration_receipt,
    seal_cleanup_review_observation,
    seal_cleanup_review_request,
    validate_cleanup_review_context,
    validate_cleanup_review_observations,
    validate_cleanup_review_request,
    validate_cleanup_reviewer_adapter_result,
)
from nmv6.adapters import FakeAdapter, MemoryBackend  # noqa: E402
from nmv6.context import ContextItem, build_context_manifest  # noqa: E402
from nmv6.evidence import EvidenceStore  # noqa: E402
from nmv6.errors import ContractError, GitPolicyError  # noqa: E402
from nmv6.git_controller import CleanupFacts, GitController, MergeReceipt  # noqa: E402
from nmv6.reducer import Reducer  # noqa: E402
from nmv6.store import Store  # noqa: E402
from nmv6.supply_chain import validate_schema_catalog  # noqa: E402
from nmv6.util import canonical_json, utc_now  # noqa: E402


HEAD = "a" * 40
TARGET_BEFORE = "b" * 40
TARGET_AFTER = "c" * 40
RESULT_TREE = "d" * 40
OTHER_HEAD = "e" * 40
SPEC_HASH = "1" * 64
CONFIG_HASH = "2" * 64


def _unsigned(value: dict, digest_field: str) -> dict:
    result = copy.deepcopy(value)
    result.pop(digest_field, None)
    return result


def valid_request() -> dict:
    receipt = seal_cleanup_integration_receipt(
        {
            "schema_version": INTEGRATION_RECEIPT_SCHEMA_VERSION,
            "receipt_id": "MERGE-RECEIPT-run-cleanup-001",
            "strategy": "merge_commit",
            "source_commit": HEAD,
            "target_ref": "refs/heads/dev",
            "target_before": TARGET_BEFORE,
            "target_after": TARGET_AFTER,
            "result_tree": RESULT_TREE,
            "rollback_ref": "refs/nm-v6/rollback/run-cleanup/dev",
            "authorization_id": "AUTH-run-cleanup-001",
            "executed_at": "2026-07-10T09:00:00Z",
        }
    )
    proof = seal_cleanup_integration_proof(
        {
            "schema_version": INTEGRATION_PROOF_SCHEMA_VERSION,
            "proof_kind": "graph_ancestry",
            "strategy": "merge_commit",
            "source_head": HEAD,
            "target_commit": TARGET_AFTER,
            "current_target_head": TARGET_AFTER,
            "target_tree": RESULT_TREE,
            "target_contains_integration_result": True,
            "ancestry_proven": True,
            "patch_equivalent": False,
            "tree_equivalent": False,
        }
    )
    facts = seal_cleanup_facts(
        {
            "schema_version": CLEANUP_FACTS_SCHEMA_VERSION,
            "run_id": "run-cleanup",
            "input_revision": 42,
            "branch": "feature/cleanup-contract",
            "expected_head": HEAD,
            "observed_head": HEAD,
            "authority_available": True,
            "responsibility_evidence_id": "EVID-cleanup-responsibility-001",
            "is_protected": False,
            "retained_pattern": False,
            "remote_branch_status": "present",
            "remote_head": HEAD,
            "checked_out": False,
            "linked_worktree_paths": [],
            "responsibilities": {
                "review_responsibility_closed": True,
                "backup_retention_absent": True,
                "dependent_work_closed": True,
                "release_responsibility_closed": True,
                "rollback_responsibility_closed": True,
                "audit_retention_absent": True,
                "explicit_retention_absent": True,
            },
            "blockers": {
                "live_lease_ids": [],
                "live_session_ids": [],
                "dependent_workspace_paths": [],
            },
        }
    )
    return seal_cleanup_review_request(
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "review_id": "CLEANUP-REVIEW-run-cleanup-001",
            "run_id": "run-cleanup",
            "spec_hash": SPEC_HASH,
            "config_hash": CONFIG_HASH,
            "input_revision": 42,
            "branch": "feature/cleanup-contract",
            "branch_head": HEAD,
            "integration_receipt": receipt,
            "integration_proof": proof,
            "cleanup_facts": facts,
        }
    )


def with_facts(request: dict, mutate) -> dict:
    raw_request = _unsigned(request, "request_digest")
    raw_facts = _unsigned(raw_request["cleanup_facts"], "facts_digest")
    mutate(raw_facts)
    raw_request["cleanup_facts"] = seal_cleanup_facts(raw_facts)
    return seal_cleanup_review_request(raw_request)


def with_receipt(request: dict, mutate) -> dict:
    raw_request = _unsigned(request, "request_digest")
    raw_receipt = _unsigned(raw_request["integration_receipt"], "receipt_digest")
    mutate(raw_receipt)
    raw_request["integration_receipt"] = seal_cleanup_integration_receipt(raw_receipt)
    return seal_cleanup_review_request(raw_request)


def with_proof(request: dict, mutate) -> dict:
    raw_request = _unsigned(request, "request_digest")
    raw_proof = _unsigned(raw_request["integration_proof"], "proof_digest")
    mutate(raw_proof)
    raw_request["integration_proof"] = seal_cleanup_integration_proof(raw_proof)
    return seal_cleanup_review_request(raw_request)


def force_delete_observation(request: dict) -> dict:
    observation = deterministic_fake_cleanup_review(request)
    raw = _unsigned(observation, "observation_digest")
    raw["decision"] = "delete_local"
    raw["rationale"] = "attempted deletion despite a core blocker"
    return seal_cleanup_review_observation(raw)


def required_context_items() -> tuple[ContextItem, ...]:
    return tuple(
        ContextItem(kind, f"fixture://{kind}", f"cleanup reviewer {kind}")
        for kind in (
            "invariant",
            "goal",
            "requirement",
            "acceptance",
            "phase",
            "task",
            "acceptance_action",
        )
    )


def cleanup_adapter_request(workspace: Path, request: dict) -> dict:
    manifest = build_cleanup_review_context_manifest(
        request=request,
        attempt_id="ATTEMPT-cleanup-review-001",
        required_items=required_context_items(),
        max_manifest_bytes=100_000,
        max_estimated_tokens=20_000,
    )
    return {
        "protocol_version": "nm-v6/adapter-request-v1",
        "operation_id": "OP-cleanup-review-001",
        "run_id": request["run_id"],
        "attempt_id": "ATTEMPT-cleanup-review-001",
        "role": "cleanup_reviewer",
        "workspace": str(workspace.resolve()),
        "context_manifest": manifest,
        "expected_output_schema": "nm-v6/adapter-result-v1",
        "deadline": "2026-07-10T10:00:00Z",
        "fencing_token": 1,
        "allowed_capabilities": [],
    }


def git(*arguments: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(arguments)} failed:\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def _base_evidence(run_id: str, evidence_id: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "branch_cleanup_responsibility",
        "producer": "nm-v6-core/cleanup-evaluator",
        "run_id": run_id,
        "subject_ids": [],
        "assertions": {},
        "spec_hash": SPEC_HASH,
        "config_hash": CONFIG_HASH,
        "source_commit": None,
        "candidate_commit": None,
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
        "argv_digest": "3" * 64,
        "working_directory": ".",
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "exit_code": 0,
        "result": "passed",
        "stdout_digest": None,
        "stderr_digest": None,
        "tool_versions": {"python": sys.version.split()[0]},
        "producer_version": "cleanup-contract-test-v1",
        "evaluator_version": "cleanup-contract-test-v1",
        "redaction_version": "placeholder",
    }


def record_responsibility_evidence(
    fixture: "CleanupGitFixture",
    *,
    sequence: int,
    release_closed: bool = True,
    terminal_resource_proof_complete: bool | None = None,
) -> str:
    evidence_id = f"EVID-cleanup-review-{sequence:03d}"
    receipt = _base_evidence(fixture.run_id, evidence_id)
    receipt.update(
        {
            "subject_ids": [
                f"branch:{fixture.branch}",
                f"branch-head:{fixture.head}",
            ],
            "source_commit": fixture.head,
            "candidate_commit": fixture.head,
            "assertions": {
                "review_responsibility_closed": True,
                "backup_retention_absent": True,
                "dependent_work_closed": True,
                "release_responsibility_closed": release_closed,
                "rollback_responsibility_closed": True,
                "audit_retention_absent": True,
                "explicit_retention_absent": True,
                **(
                    {
                        "terminal_resource_proof_complete": (
                            terminal_resource_proof_complete
                        )
                    }
                    if terminal_resource_proof_complete is not None
                    else {}
                ),
            },
        }
    )
    persisted = fixture.evidence.persist(
        receipt, b"cleanup responsibility facts\n", b""
    )
    run = fixture.store.get_run(fixture.run_id)
    assert run is not None
    fixture.reducer.record_evidence(
        run_id=fixture.run_id,
        expected_revision=int(run["revision"]),
        receipt=persisted,
        idempotency_key=f"cleanup-responsibility:{sequence}",
        actor="cleanup-contract-test",
    )
    return evidence_id


@dataclass
class CleanupGitFixture:
    remote: Path
    checkout: Path
    store: Store
    evidence: EvidenceStore
    reducer: Reducer
    controller: GitController
    run_id: str
    branch: str
    base: str
    head: str
    target_after: str
    receipt: MergeReceipt


def create_cleanup_git_fixture(
    root: Path, *, strategy: str = "fast_forward"
) -> CleanupGitFixture:
    remote = root / "remote.git"
    seed = root / "seed"
    checkout = root / "checkout"
    git("init", "--bare", str(remote), cwd=root)
    seed.mkdir()
    git("init", "-b", "main", cwd=seed)
    git("config", "user.name", "Cleanup Test", cwd=seed)
    git("config", "user.email", "cleanup@example.invalid", cwd=seed)
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
    git("config", "user.name", "Cleanup Test", cwd=checkout)
    git("config", "user.email", "cleanup@example.invalid", cwd=checkout)

    branch = f"feature/cleanup-{strategy.replace('_', '-')}"
    git("switch", "-c", branch, base, cwd=checkout)
    (checkout / "change.txt").write_text(f"{strategy}\n", encoding="utf-8")
    git("add", "change.txt", cwd=checkout)
    git("commit", "-m", f"cleanup {strategy}", cwd=checkout)
    head = git("rev-parse", "HEAD", cwd=checkout)
    git("push", "origin", branch, cwd=checkout)
    git("switch", "main", cwd=checkout)
    if strategy == "fast_forward":
        git("branch", "-f", "dev", head, cwd=checkout)
        target_after = head
        git("push", "origin", f"{head}:refs/heads/dev", cwd=checkout)
    elif strategy == "squash":
        git("switch", "-c", "dev", "origin/dev", cwd=checkout)
        git("merge", "--squash", branch, cwd=checkout)
        git("commit", "-m", "squash cleanup fixture", cwd=checkout)
        target_after = git("rev-parse", "HEAD", cwd=checkout)
        git("push", "origin", "dev", cwd=checkout)
        git("switch", "main", cwd=checkout)
    else:
        raise AssertionError(f"unsupported cleanup fixture strategy: {strategy}")

    run_id = f"run-cleanup-{strategy}"
    store = Store(root / "state.sqlite3")
    evidence = EvidenceStore(root / "evidence")
    reducer = Reducer(store, evidence_store=evidence)
    reducer.create_run(
        run_id=run_id,
        spec_hash=SPEC_HASH,
        config_hash=CONFIG_HASH,
        idempotency_key=f"create:{run_id}",
    )
    receipt = MergeReceipt(
        strategy,
        head,
        base,
        target_after,
        git("rev-parse", f"{target_after}^{{tree}}", cwd=checkout),
        f"refs/nm-v6/rollback/{run_id}/dev",
        f"AUTH-{run_id}-001",
        "2026-07-10T09:00:00Z",
    )
    fixture = CleanupGitFixture(
        remote,
        checkout,
        store,
        evidence,
        reducer,
        GitController(checkout, cleanup_store=store),
        run_id,
        branch,
        base,
        head,
        target_after,
        receipt,
    )
    record_responsibility_evidence(fixture, sequence=1)
    return fixture


def cleanup_policy(fixture: CleanupGitFixture) -> dict[str, object]:
    return {
        "review_id": f"CLEANUP-REVIEW-{fixture.run_id}-001",
        "run_id": fixture.run_id,
        "spec_hash": SPEC_HASH,
        "config_hash": CONFIG_HASH,
        "branch": fixture.branch,
        "target_branch": "dev",
        "receipt_id": f"MERGE-RECEIPT-{fixture.run_id}-001",
        "integration_receipt": fixture.receipt,
        "caller_facts": CleanupFacts(
            fixture.branch,
            fixture.head,
            fixture.receipt,
            run_id=fixture.run_id,
        ),
    }


class CleanupReviewContractTests(unittest.TestCase):
    def test_terminal_delivery_state_requires_final_resource_evidence_and_no_active_operation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = create_cleanup_git_fixture(Path(directory))
            try:
                authority = fixture.controller.cleanup_authority
                assert authority is not None
                with fixture.store._write_transaction() as connection:
                    connection.execute(
                        "UPDATE runs SET state = ? WHERE run_id = ?",
                        ("POST_DEPLOY_VERIFYING", fixture.run_id),
                    )
                early = authority.snapshot(
                    run_id=fixture.run_id,
                    branch=fixture.branch,
                    head=fixture.head,
                )
                self.assertIsNone(early.responsibility_evidence_id)
                record_responsibility_evidence(
                    fixture,
                    sequence=2,
                    terminal_resource_proof_complete=True,
                )
                terminal = authority.snapshot(
                    run_id=fixture.run_id,
                    branch=fixture.branch,
                    head=fixture.head,
                )
                self.assertEqual(
                    "EVID-cleanup-review-002",
                    terminal.responsibility_evidence_id,
                )
                self.assertTrue(terminal.responsibilities_closed)
                now = utc_now()
                with fixture.store._write_transaction() as connection:
                    connection.execute(
                        "INSERT INTO external_operations("
                        "operation_id, run_id, action_id, operation_kind, "
                        "idempotency_key, status, effect_id, authorization_id, "
                        "grant_revision, fencing_token, scope_json, result_json, "
                        "started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            "OP-terminal-active-001",
                            fixture.run_id,
                            "terminal-probe",
                            "provider_api",
                            "terminal-active-operation",
                            "started",
                            None,
                            None,
                            None,
                            None,
                            "{}",
                            "{}",
                            now,
                            now,
                        ),
                    )
                blocked = authority.snapshot(
                    run_id=fixture.run_id,
                    branch=fixture.branch,
                    head=fixture.head,
                )
                self.assertIsNone(blocked.responsibility_evidence_id)
                self.assertFalse(blocked.responsibilities_closed)
            finally:
                fixture.store.close()

    def test_cleanup_reviewer_adapter_three_decisions_and_strict_envelope(self) -> None:
        requests = (
            (valid_request(), "delete_local"),
            (
                with_facts(
                    valid_request(),
                    lambda facts: facts["blockers"].update(
                        live_lease_ids=["LEASE-review-001"]
                    ),
                ),
                "retain",
            ),
            (
                with_facts(
                    valid_request(),
                    lambda facts: facts.update(observed_head=OTHER_HEAD),
                ),
                "request_administrator",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            for review_request, expected in requests:
                with self.subTest(decision=expected):
                    envelope = cleanup_adapter_request(workspace, review_request)
                    adapter = FakeAdapter(backend=MemoryBackend())
                    session_id = adapter.start(envelope)["session_id"]
                    self.assertEqual("finished", adapter.poll(session_id)["status"])
                    result = adapter.collect_dict(session_id)
                    validated = validate_cleanup_reviewer_adapter_result(
                        result,
                        adapter_request=envelope,
                        review_request=review_request,
                        expected_session_id=session_id,
                    )
                    self.assertEqual(expected, validated["observations"][0]["decision"])

                    candidate = copy.deepcopy(result)
                    candidate["candidate_commit"] = HEAD
                    with self.assertRaisesRegex(ContractError, "candidate commit"):
                        validate_cleanup_reviewer_adapter_result(
                            candidate,
                            adapter_request=envelope,
                            review_request=review_request,
                            expected_session_id=session_id,
                        )

            worker = cleanup_adapter_request(workspace, valid_request())
            worker["role"] = "worker"
            worker_result = MemoryBackend._default_result(
                worker, "SESSION-fake-worker"
            )
            self.assertEqual([], worker_result["observations"])

    def test_cleanup_reviewer_context_and_durable_restart_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            review_request = valid_request()
            envelope = cleanup_adapter_request(workspace, review_request)
            validate_cleanup_review_context(
                envelope["context_manifest"], review_request
            )
            self.assertEqual(
                1,
                sum(
                    entry["source"] == CLEANUP_REVIEW_CONTEXT_SOURCE
                    for entry in envelope["context_manifest"]["entries"]
                ),
            )

            with self.assertRaisesRegex(ContractError, "missing required slices"):
                build_cleanup_review_context_manifest(
                    request=review_request,
                    attempt_id="ATTEMPT-cleanup-review-002",
                    required_items=required_context_items()[:-1],
                    max_manifest_bytes=100_000,
                    max_estimated_tokens=20_000,
                )
            duplicate = build_context_manifest(
                attempt_id="ATTEMPT-cleanup-review-003",
                items=(
                    *required_context_items(),
                    cleanup_review_context_item(review_request),
                    ContextItem(
                        "decision",
                        CLEANUP_REVIEW_CONTEXT_SOURCE,
                        canonical_json(review_request).decode("utf-8"),
                        entry_id="CTX-CLEANUP-REVIEW-DUPLICATE",
                    ),
                ),
                allowed_paths=[],
                prohibited_paths=[".nm/runtime"],
                max_manifest_bytes=100_000,
                max_estimated_tokens=20_000,
            )
            with self.assertRaisesRegex(ContractError, "exactly one"):
                validate_cleanup_review_context(duplicate, review_request)

            state_root = root / "adapter-sessions"
            first = FakeAdapter(state_root=state_root)
            session_id = first.start(envelope)["session_id"]
            restarted = FakeAdapter(state_root=state_root)
            self.assertEqual("finished", restarted.poll(session_id)["status"])
            result = restarted.collect_dict(session_id)
            validate_cleanup_reviewer_adapter_result(
                result,
                adapter_request=envelope,
                review_request=review_request,
                expected_session_id=session_id,
            )
            self.assertEqual([session_id], [path.name for path in state_root.iterdir()])

    def test_git_cleanup_review_rechecks_ai_core_and_preserves_remote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = create_cleanup_git_fixture(Path(directory))
            policy = cleanup_policy(fixture)
            request = fixture.controller.build_cleanup_review_request(**policy)
            self.assertEqual(fixture.head, request["cleanup_facts"]["remote_head"])
            observation = deterministic_fake_cleanup_review(request)
            self.assertEqual("delete_local", observation["decision"])

            conservative = _unsigned(observation, "observation_digest")
            conservative["decision"] = "retain"
            conservative["rationale"] = "AI attempts to disagree with core facts"
            mismatch = seal_cleanup_review_observation(conservative)
            with self.assertRaisesRegex(GitPolicyError, "differs from deterministic core"):
                fixture.controller.validate_cleanup_review_decision(
                    request=request,
                    observation=mismatch,
                    **policy,
                )
            self.assertEqual(
                fixture.head,
                fixture.controller.resolve_commit(f"refs/heads/{fixture.branch}"),
            )

            fresh_request = fixture.controller.build_cleanup_review_request(**policy)
            fresh_observation = deterministic_fake_cleanup_review(fresh_request)
            decision = fixture.controller.validate_cleanup_review_decision(
                request=fresh_request,
                observation=fresh_observation,
                **policy,
            )
            self.assertEqual("delete_local", decision.result)
            deletion = fixture.controller.delete_local_branch(
                decision,
                current_facts=CleanupFacts(
                    fixture.branch,
                    fixture.head,
                    fixture.receipt,
                    ancestry_proven=True,
                    run_id=fixture.run_id,
                ),
            )
            self.assertEqual("deleted", deletion.result)
            self.assertIsNone(
                fixture.controller.try_resolve_commit(
                    f"refs/heads/{fixture.branch}"
                )
            )
            self.assertEqual(
                fixture.head, fixture.controller.remote_head(fixture.branch)
            )
            fixture.store.close()

    def test_git_cleanup_review_stale_facts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = create_cleanup_git_fixture(root)
            policy = cleanup_policy(fixture)

            def sealed() -> tuple[dict, dict]:
                request = fixture.controller.build_cleanup_review_request(**policy)
                return request, deterministic_fake_cleanup_review(request)

            def rejected(old: tuple[dict, dict]) -> None:
                request, observation = old
                with self.assertRaisesRegex(
                    GitPolicyError, "differs from current core facts"
                ):
                    fixture.controller.validate_cleanup_review_decision(
                        request=request,
                        observation=observation,
                        **policy,
                    )

            old = sealed()
            run = fixture.store.get_run(fixture.run_id)
            assert run is not None
            fixture.reducer.record_domain_event(
                run_id=fixture.run_id,
                expected_revision=int(run["revision"]),
                event_type="RECONCILIATION_RECORDED",
                payload={"reason": "stale review"},
                idempotency_key="cleanup-test:revision",
                actor="cleanup-contract-test",
            )
            rejected(old)

            old = sealed()
            record_responsibility_evidence(
                fixture, sequence=2, release_closed=False
            )
            rejected(old)

            old = sealed()
            run = fixture.store.get_run(fixture.run_id)
            assert run is not None
            fixture.reducer.acquire_lease(
                run_id=fixture.run_id,
                expected_revision=int(run["revision"]),
                resource_id="TASK-cleanup-stale",
                owner="worker-cleanup-stale",
                lease_seconds=300,
                idempotency_key="cleanup-test:lease",
            )
            rejected(old)

            old = sealed()
            run = fixture.store.get_run(fixture.run_id)
            assert run is not None
            fixture.reducer.create_entity(
                run_id=fixture.run_id,
                expected_revision=int(run["revision"]),
                machine="attempt",
                entity_id="ATTEMPT-cleanup-session-001",
                initial_state="CREATED",
                idempotency_key="cleanup-test:session",
                payload={"session_id": "SESSION-cleanup-stale"},
            )
            rejected(old)

            old = sealed()
            dependent = root / "dependent-workspace"
            dependent.mkdir()
            run = fixture.store.get_run(fixture.run_id)
            assert run is not None
            fixture.reducer.create_entity(
                run_id=fixture.run_id,
                expected_revision=int(run["revision"]),
                machine="attempt",
                entity_id="ATTEMPT-cleanup-workspace-002",
                initial_state="CREATED",
                idempotency_key="cleanup-test:workspace",
                payload={"workspace_path": str(dependent)},
            )
            rejected(old)

            old = sealed()
            updater = root / "updater"
            git("clone", str(fixture.remote), str(updater), cwd=root)
            git("config", "user.name", "Remote Updater", cwd=updater)
            git("config", "user.email", "updater@example.invalid", cwd=updater)
            git("switch", "--track", f"origin/{fixture.branch}", cwd=updater)
            (updater / "remote.txt").write_text("remote moved\n", encoding="utf-8")
            git("add", "remote.txt", cwd=updater)
            git("commit", "-m", "move remote cleanup branch", cwd=updater)
            git("push", "origin", fixture.branch, cwd=updater)
            rejected(old)

            old = sealed()
            moved = git(
                "commit-tree",
                fixture.controller.tree_of(fixture.head),
                "-p",
                fixture.head,
                "-m",
                "move local cleanup branch",
                cwd=fixture.checkout,
            )
            git(
                "update-ref",
                f"refs/heads/{fixture.branch}",
                moved,
                fixture.head,
                cwd=fixture.checkout,
            )
            rejected(old)
            fixture.store.close()

    def test_git_cleanup_review_squash_proof_ignores_caller_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = create_cleanup_git_fixture(
                Path(directory), strategy="squash"
            )
            policy = cleanup_policy(fixture)
            policy["caller_facts"] = replace(
                policy["caller_facts"], patch_or_tree_equivalent=False
            )
            request = fixture.controller.build_cleanup_review_request(**policy)
            proof = request["integration_proof"]
            self.assertTrue(proof["patch_equivalent"])
            self.assertTrue(proof["tree_equivalent"])
            self.assertEqual(
                "delete_local",
                deterministic_fake_cleanup_review(request)["decision"],
            )

            wrong_receipt = replace(
                fixture.receipt,
                result_tree=fixture.controller.tree_of(fixture.base),
            )
            with self.assertRaisesRegex(GitPolicyError, "differs from Git"):
                fixture.controller.build_cleanup_review_request(
                    **{
                        **policy,
                        "integration_receipt": wrong_receipt,
                        "caller_facts": replace(
                            policy["caller_facts"],
                            integration_receipt=wrong_receipt,
                            patch_or_tree_equivalent=True,
                        ),
                    }
                )
            fixture.store.close()

    def test_exact_positive_request_allows_only_local_cleanup(self) -> None:
        request = valid_request()
        self.assertEqual(request, validate_cleanup_review_request(request))
        self.assertTrue(cleanup_review_delete_eligible(request))
        self.assertEqual(("remote_branch_present",), cleanup_review_risk_flags(request))

        first = deterministic_fake_cleanup_review(request)
        second = deterministic_fake_cleanup_review(request)
        self.assertEqual(first, second)
        self.assertEqual("delete_local", first["decision"])
        self.assertEqual(["remote_branch_present"], first["risk_flags"])
        self.assertEqual(
            first, validate_cleanup_review_observations(request, [first])
        )
        self.assertNotIn("remote_delete", json.dumps(first, sort_keys=True))

    def test_every_core_blocker_prevents_delete_local(self) -> None:
        cases = {
            "branch_missing": lambda facts: facts.update(observed_head=None),
            "branch_moved": lambda facts: facts.update(observed_head=OTHER_HEAD),
            "cleanup_authority_unavailable": lambda facts: facts.update(
                authority_available=False
            ),
            "responsibility_evidence_missing": lambda facts: facts.update(
                responsibility_evidence_id=None
            ),
            "protected_branch": lambda facts: facts.update(is_protected=True),
            "retained_pattern": lambda facts: facts.update(retained_pattern=True),
            "remote_status_unknown": lambda facts: facts.update(
                remote_branch_status="unknown", remote_head=None
            ),
            "branch_checked_out": lambda facts: facts.update(checked_out=True),
            "linked_worktree": lambda facts: facts.update(
                linked_worktree_paths=["/tmp/nm-v6-worktree"]
            ),
            "review_open": lambda facts: facts["responsibilities"].update(
                review_responsibility_closed=False
            ),
            "backup_retention": lambda facts: facts["responsibilities"].update(
                backup_retention_absent=False
            ),
            "dependent_work": lambda facts: facts["responsibilities"].update(
                dependent_work_closed=False
            ),
            "release_responsibility": lambda facts: facts[
                "responsibilities"
            ].update(release_responsibility_closed=False),
            "rollback_responsibility": lambda facts: facts[
                "responsibilities"
            ].update(rollback_responsibility_closed=False),
            "audit_retention": lambda facts: facts["responsibilities"].update(
                audit_retention_absent=False
            ),
            "explicit_retention": lambda facts: facts[
                "responsibilities"
            ].update(explicit_retention_absent=False),
            "live_lease": lambda facts: facts["blockers"].update(
                live_lease_ids=["LEASE-001"]
            ),
            "live_session": lambda facts: facts["blockers"].update(
                live_session_ids=["SESSION-001"]
            ),
            "dependent_workspace": lambda facts: facts["blockers"].update(
                dependent_workspace_paths=["/tmp/nm-v6-dependent"]
            ),
        }
        for expected_flag, mutate in cases.items():
            with self.subTest(expected_flag=expected_flag):
                request = with_facts(valid_request(), mutate)
                observation = deterministic_fake_cleanup_review(request)
                self.assertFalse(cleanup_review_delete_eligible(request))
                self.assertIn(expected_flag, observation["risk_flags"])
                expected_decision = (
                    "request_administrator"
                    if expected_flag
                    in {"branch_missing", "branch_moved", "remote_status_unknown"}
                    or expected_flag
                    in {
                        "cleanup_authority_unavailable",
                        "responsibility_evidence_missing",
                    }
                    else "retain"
                )
                self.assertEqual(expected_decision, observation["decision"])
                with self.assertRaisesRegex(ContractError, "cannot delete"):
                    validate_cleanup_review_observations(
                        request, [force_delete_observation(request)]
                    )

    def test_integration_source_and_proof_are_core_bound(self) -> None:
        source_mismatch = with_receipt(
            valid_request(), lambda receipt: receipt.update(source_commit=OTHER_HEAD)
        )
        mismatch = deterministic_fake_cleanup_review(source_mismatch)
        self.assertEqual("request_administrator", mismatch["decision"])
        self.assertIn("integration_source_mismatch", mismatch["risk_flags"])

        incomplete = with_proof(
            valid_request(), lambda proof: proof.update(ancestry_proven=False)
        )
        observation = deterministic_fake_cleanup_review(incomplete)
        self.assertEqual("retain", observation["decision"])
        self.assertIn("integration_proof_incomplete", observation["risk_flags"])
        with self.assertRaisesRegex(ContractError, "cannot delete"):
            validate_cleanup_review_observations(
                incomplete, [force_delete_observation(incomplete)]
            )

    def test_squash_requires_patch_or_tree_equivalence(self) -> None:
        request = valid_request()
        raw = _unsigned(request, "request_digest")
        receipt = _unsigned(raw["integration_receipt"], "receipt_digest")
        receipt["strategy"] = "squash"
        raw["integration_receipt"] = seal_cleanup_integration_receipt(receipt)
        proof = _unsigned(raw["integration_proof"], "proof_digest")
        proof.update(
            {
                "proof_kind": "patch_tree_equivalence",
                "strategy": "squash",
                "ancestry_proven": False,
                "patch_equivalent": False,
                "tree_equivalent": False,
            }
        )
        raw["integration_proof"] = seal_cleanup_integration_proof(proof)
        incomplete = seal_cleanup_review_request(raw)
        self.assertEqual(
            "retain",
            deterministic_fake_cleanup_review(incomplete)["decision"],
        )

        complete = with_proof(
            incomplete,
            lambda value: value.update(
                patch_equivalent=True, tree_equivalent=True
            ),
        )
        self.assertTrue(cleanup_review_delete_eligible(complete))
        self.assertEqual(
            "delete_local", deterministic_fake_cleanup_review(complete)["decision"]
        )

    def test_stale_tampered_multiple_and_unknown_data_fail_closed(self) -> None:
        request = valid_request()

        tampered = copy.deepcopy(request)
        tampered["branch"] = "feature/tampered"
        with self.assertRaisesRegex(ContractError, "stale|digest mismatch"):
            validate_cleanup_review_request(tampered)

        unknown = copy.deepcopy(request)
        unknown["unexpected"] = True
        with self.assertRaisesRegex(ContractError, "unknown"):
            validate_cleanup_review_request(unknown)

        nested_unknown = copy.deepcopy(request)
        nested_unknown["cleanup_facts"]["unexpected"] = True
        with self.assertRaisesRegex(ContractError, "unknown"):
            validate_cleanup_review_request(nested_unknown)

        bad_receipt = copy.deepcopy(request)
        bad_receipt["integration_receipt"]["receipt_digest"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "receipt digest mismatch"):
            validate_cleanup_review_request(bad_receipt)

        receipt = _unsigned(request["integration_receipt"], "receipt_digest")
        for field, invalid, message in (
            ("source_commit", "a" * 41, "full lowercase Git object ID"),
            ("target_ref", "refs/heads/../dev", "exact branch ref"),
            ("executed_at", "2026-07-10 09:00:00+00:00", "RFC3339"),
        ):
            with self.subTest(receipt_field=field):
                malformed = copy.deepcopy(receipt)
                malformed[field] = invalid
                with self.assertRaisesRegex(ContractError, message):
                    seal_cleanup_integration_receipt(malformed)
        invalid_fast_forward = copy.deepcopy(receipt)
        invalid_fast_forward["strategy"] = "fast_forward"
        with self.assertRaisesRegex(ContractError, "target_after must equal"):
            seal_cleanup_integration_receipt(invalid_fast_forward)

        observation = deterministic_fake_cleanup_review(request)
        for values in ([], [observation, observation]):
            with self.assertRaisesRegex(ContractError, "exactly one"):
                validate_cleanup_review_observations(request, values)

        stale = _unsigned(observation, "observation_digest")
        stale["input_revision"] += 1
        stale_observation = seal_cleanup_review_observation(stale)
        with self.assertRaisesRegex(ContractError, "stale input_revision"):
            validate_cleanup_review_observations(request, [stale_observation])

        omitted_risk = _unsigned(observation, "observation_digest")
        omitted_risk["risk_flags"] = []
        omitted_observation = seal_cleanup_review_observation(omitted_risk)
        with self.assertRaisesRegex(ContractError, "omitted or invented"):
            validate_cleanup_review_observations(request, [omitted_observation])

        observation_unknown = copy.deepcopy(observation)
        observation_unknown["unexpected"] = True
        with self.assertRaisesRegex(ContractError, "unknown"):
            validate_cleanup_review_observations(request, [observation_unknown])

        invalid_flag = _unsigned(observation, "observation_digest")
        invalid_flag["risk_flags"] = ["reviewer_invented_fact"]
        with self.assertRaisesRegex(ContractError, "not canonical"):
            seal_cleanup_review_observation(invalid_flag)

    def test_schemas_are_versioned_catalogued_and_root_strict(self) -> None:
        schema_directory = TOOLS_ROOT / "schemas"
        catalog = validate_schema_catalog(schema_directory)
        self.assertEqual(
            "cleanup-review-request-v1.schema.json",
            catalog[
                "https://notmaster.dev/nm-v6/schemas/cleanup-review-request-v1.schema.json"
            ],
        )
        self.assertEqual(
            "cleanup-review-observation-v1.schema.json",
            catalog[
                "https://notmaster.dev/nm-v6/schemas/cleanup-review-observation-v1.schema.json"
            ],
        )
        request_schema = json.loads(
            (schema_directory / "cleanup-review-request-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        observation_schema = json.loads(
            (
                schema_directory / "cleanup-review-observation-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(request_schema["additionalProperties"])
        self.assertFalse(observation_schema["additionalProperties"])
        self.assertEqual(set(REQUEST_FIELDS), set(request_schema["required"]))
        self.assertEqual(set(OBSERVATION_FIELDS), set(observation_schema["required"]))
        self.assertEqual(set(REQUEST_FIELDS), set(request_schema["properties"]))
        self.assertEqual(set(OBSERVATION_FIELDS), set(observation_schema["properties"]))
        for definition in (
            "integrationReceipt",
            "integrationProof",
            "responsibilities",
            "blockers",
            "cleanupFacts",
        ):
            self.assertFalse(request_schema["$defs"][definition]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
