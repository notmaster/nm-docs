from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[3]
TOOLS = REPOSITORY / "tools/nm-v6"
sys.path.insert(0, str(TOOLS))

from nmv6.authorization import authorization_scope_allows, signed_payload  # noqa: E402
from nmv6.errors import GitPolicyError  # noqa: E402
from nmv6.evidence import EvidenceStore  # noqa: E402
from nmv6.git_controller import GitController  # noqa: E402
from nmv6.store import Store  # noqa: E402
from nmv6.template_sync import initialize_project  # noqa: E402


class GeneratedHotfixRuntimeTests(unittest.TestCase):
    def _git(self, target: Path, *arguments: str, check: bool = True) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=target,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout)
        return completed.stdout.strip()

    def _environment(self, **extra: str) -> dict[str, str]:
        python_bin = str(Path(sys.executable).resolve().parent)
        return {
            **os.environ,
            "PATH": python_bin + os.pathsep + os.environ.get("PATH", ""),
            "NM_V6_PYTHON": sys.executable,
            **extra,
        }

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

    def test_cli_hotfix_preserves_unreleased_dev_and_recovers_both_pushes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "project"
            initialize_project(
                target,
                source_root=REPOSITORY,
                project_name="Hotfix Runtime Fixture",
                package_name="hotfix-runtime-fixture",
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
            project_path.write_text(
                json.dumps(project, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            marker = target / ".nm-v6-fake-provider.json"
            marker.write_text(
                json.dumps(
                    {
                        "adapter_candidate": {
                            "enabled": True,
                            "path": "src/hotfix.txt",
                            "content": "verified hotfix\n",
                        },
                        "deployed_version": "v1",
                        "healthy": True,
                        "operations": {},
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self._git(
                target,
                "add",
                "project.json",
                str(public_key.relative_to(target)),
                marker.name,
            )
            self._git(
                target,
                "-c",
                "user.name=NM V6 Test",
                "-c",
                "user.email=nm-v6-test@example.invalid",
                "commit",
                "-m",
                "test: configure hotfix runtime fixture",
            )
            stable_before = self._git(target, "rev-parse", "HEAD")
            remote = root / "remote.git"
            subprocess.run(
                ["git", "clone", "--bare", "--no-local", str(target), str(remote)],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            )
            self._git(remote, "update-ref", "refs/heads/main", stable_before)
            self._git(remote, "update-ref", "refs/heads/dev", stable_before)

            dev_seed = root / "dev-seed"
            subprocess.run(
                ["git", "clone", "--no-local", str(remote), str(dev_seed)],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            )
            self._git(dev_seed, "checkout", "-B", "dev", "origin/dev")
            dev_only = dev_seed / "src/dev-only.txt"
            dev_only.parent.mkdir(parents=True, exist_ok=True)
            dev_only.write_text("unreleased dev work\n", encoding="utf-8")
            self._git(dev_seed, "add", "src/dev-only.txt")
            self._git(
                dev_seed,
                "-c",
                "user.name=NM V6 Test",
                "-c",
                "user.email=nm-v6-test@example.invalid",
                "commit",
                "-m",
                "test: seed unreleased dev work",
            )
            self._git(dev_seed, "push", "origin", "dev")
            dev_before = self._git(remote, "rev-parse", "refs/heads/dev")
            self.assertNotEqual(stable_before, dev_before)
            self._git(target, "remote", "add", "origin", str(remote))

            run_id = "run-hotfix-runtime"

            def invoke(*arguments: str) -> dict[str, Any]:
                completed = subprocess.run(
                    [sys.executable, str(TOOLS / "nm_v6.py"), *arguments],
                    cwd=target,
                    env=self._environment(),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
                if completed.returncode != 0:
                    with Store(target / ".nm/runtime/v6/state.sqlite3") as failed_store:
                        failed_run = failed_store.get_run(run_id)
                        failed_events = failed_store.list_events(run_id=run_id)[-4:]
                    self.fail(
                        completed.stderr
                        + "\nrun="
                        + repr(failed_run)
                        + "\nevents="
                        + repr(failed_events)
                    )
                return json.loads(completed.stdout)

            planned = invoke(
                "plan",
                "--target",
                str(target),
                "--run-id",
                run_id,
                "--run-kind",
                "hotfix",
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
                    "confirmation_id": "AUTH-hotfix-confirm-001",
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
                self.assertEqual(
                    expected,
                    invoke(
                        "run",
                        "--target",
                        str(target),
                        "--run-id",
                        run_id,
                        "--once",
                    )["state"],
                )

            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                current = store.get_run(run_id)
                self.assertIsNotNone(current)
                scope = {
                    "run_id": run_id,
                    "spec_hash": current["spec_hash"],
                    "config_hash": current["config_hash"],
                    "allowed_actions": [
                        "mode_set_auto",
                        "hotfix",
                        "hotfix_stable",
                        "hotfix_reconcile_dev",
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
                    "grant_id": "AUTH-hotfix-grant-002",
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

            def status() -> dict[str, Any]:
                return invoke(
                    "status", "--target", str(target), "--run-id", run_id, "--json"
                )

            def crash_after_push() -> None:
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
                    env=self._environment(
                        NM_V6_FAILPOINT="git.after_protected_push",
                        NM_V6_FAILPOINT_ACTION="sigkill",
                    ),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
                self.assertNotEqual(0, crashed.returncode)

            crashed_stable = False
            crashed_dev = False
            observed_states: list[str] = []
            for _ in range(50):
                current_state = str(status()["state"])
                observed_states.append(current_state)
                if current_state == "COMPLETED":
                    break
                if current_state == "HOTFIX_INTEGRATING_STABLE" and not crashed_stable:
                    crash_after_push()
                    crashed_stable = True
                    self.assertEqual("HOTFIX_INTEGRATING_STABLE", status()["state"])
                    self.assertNotEqual(
                        stable_before,
                        self._git(remote, "rev-parse", "refs/heads/main"),
                    )
                    continue
                if current_state == "HOTFIX_RECONCILING_DEV" and not crashed_dev:
                    crash_after_push()
                    crashed_dev = True
                    self.assertEqual("HOTFIX_RECONCILING_DEV", status()["state"])
                    self.assertNotEqual(
                        dev_before,
                        self._git(remote, "rev-parse", "refs/heads/dev"),
                    )
                    continue
                invoke(
                    "run",
                    "--target",
                    str(target),
                    "--run-id",
                    run_id,
                    "--once",
                )
            else:
                self.fail("hotfix CLI run did not terminate within 50 steps")

            self.assertTrue(crashed_stable)
            self.assertTrue(crashed_dev)
            self.assertIn("HOTFIX_VERIFYING", observed_states)
            self.assertIn("HOTFIX_STABLE_VERIFYING", observed_states)
            self.assertIn("HOTFIX_DEV_VERIFYING", observed_states)
            stable_after = self._git(remote, "rev-parse", "refs/heads/main")
            dev_after = self._git(remote, "rev-parse", "refs/heads/dev")
            self.assertNotEqual(stable_after, dev_after)
            self.assertEqual(
                "verified hotfix",
                self._git(remote, "show", f"{stable_after}:src/hotfix.txt"),
            )
            self.assertEqual(
                "verified hotfix",
                self._git(remote, "show", f"{dev_after}:src/hotfix.txt"),
            )
            self.assertEqual(
                "unreleased dev work",
                self._git(remote, "show", f"{dev_after}:src/dev-only.txt"),
            )
            self.assertNotEqual(
                0,
                subprocess.run(
                    ["git", "cat-file", "-e", f"{stable_after}:src/dev-only.txt"],
                    cwd=remote,
                    text=True,
                    capture_output=True,
                    check=False,
                ).returncode,
            )
            self.assertEqual(
                "",
                self._git(
                    remote,
                    "merge-base",
                    "--is-ancestor",
                    stable_after,
                    dev_after,
                ),
            )

            with Store(target / ".nm/runtime/v6/state.sqlite3") as store:
                completed = store.get_run(run_id)
                self.assertEqual("COMPLETED", completed["state"])
                payload = completed["payload"]
                self.assertEqual("hotfix_stable", payload["runtime_release_source_kind"])
                self.assertEqual(stable_before, payload["runtime_hotfix_base_commit"])
                self.assertEqual(dev_before, payload["runtime_hotfix_dev_before"])
                self.assertEqual(stable_after, payload["runtime_release_source_commit"])
                stable_result = store.get_gate(
                    payload["runtime_hotfix_stable_result_gate"]
                )
                reconciliation_result = store.get_gate(
                    payload["runtime_hotfix_reconciliation_result_gate"]
                )
                release_result = store.get_gate(payload["runtime_release_result_gate"])
                self.assertEqual(stable_before, stable_result["target_commit"])
                self.assertEqual(stable_after, stable_result["source_commit"])
                self.assertEqual(stable_after, stable_result["candidate_commit"])
                self.assertEqual(stable_after, reconciliation_result["source_commit"])
                self.assertEqual(dev_before, reconciliation_result["target_commit"])
                self.assertEqual(dev_after, reconciliation_result["candidate_commit"])
                self.assertEqual("hotfix_stable", release_result["release_source_kind"])
                self.assertEqual(stable_after, release_result["release_source_commit"])
                self.assertEqual(
                    payload["runtime_hotfix_reconciliation_result_gate"],
                    release_result["hotfix_reconciliation_gate_id"],
                )
                events = store.list_events(run_id=run_id)
                reviewer_requests = [
                    event["payload"]["record"]
                    for event in events
                    if event["event_type"] == "ADAPTER_REQUESTED"
                    and event["payload"].get("record", {}).get("role")
                    == "merge_reviewer"
                ]
                self.assertEqual(
                    ["hotfix_to_stable", "hotfix_to_dev"],
                    [record["route"] for record in reviewer_requests],
                )
                merge_records = [
                    event["payload"]["record"]
                    for event in events
                    if event["event_type"] == "MERGE_PROPOSED"
                ]
                self.assertEqual(
                    ["hotfix_to_stable", "hotfix_to_dev"],
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
                        "cleanup-hotfix-to-stable",
                        "cleanup-hotfix-to-dev",
                        "cleanup-hotfix-final",
                    ],
                    [record["review_scope"] for record in cleanup_records],
                )
                self.assertEqual(
                    ["retain", "retain", "retain"],
                    [record["core_decision"]["result"] for record in cleanup_records],
                )
                self.assertFalse(
                    any(
                        event["event_type"] == "BRANCH_CLEANUP_DECIDED"
                        and event["payload"].get("record", {}).get("record_kind")
                        == "execution_receipt"
                        for event in events
                    )
                )
                self.assertEqual(
                    payload["runtime_hotfix_candidate_commit"],
                    self._git(
                        target,
                        "rev-parse",
                        f"refs/heads/{payload['runtime_hotfix_branch']}",
                    ),
                )
                self.assertEqual(
                    "retain",
                    payload["runtime_terminal_resolution"]["cleanup_result"],
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
                protected_starts = [
                    event["payload"]["projection"]["action_id"]
                    for event in events
                    if event["event_type"] == "EXTERNAL_OPERATION_STARTED"
                    and event["payload"].get("projection", {}).get("action_id")
                    in {"hotfix_stable", "hotfix_reconcile_dev"}
                ]
                self.assertEqual(
                    ["hotfix_stable", "hotfix_reconcile_dev"], protected_starts
                )
                pushed_refs = {
                    event["payload"]["record"]["branch"]
                    for event in events
                    if event["event_type"] == "PROTECTED_REF_PUSHED"
                }
                self.assertEqual({"main", "dev"}, pushed_refs)
                task_entity = (
                    hashlib.sha256(run_id.encode()).hexdigest()[:16] + ".TASK-001"
                )
                phase_entity = (
                    hashlib.sha256(run_id.encode()).hexdigest()[:16] + ".PHASE-001"
                )
                self.assertEqual(
                    "INTEGRATED",
                    store.get_entity_state("task", task_entity)["state"],
                )
                self.assertEqual(
                    "INTEGRATED",
                    store.get_entity_state("phase", phase_entity)["state"],
                )
                task_receipt = next(
                    receipt
                    for receipt in store.list_evidence(run_id)
                    if receipt.get("attempt_id") is not None
                    and "TASK-001" in receipt.get("subject_ids", [])
                )
            observation = json.loads(
                EvidenceStore(target / ".nm/runtime/v6/evidence").read_blob(
                    task_receipt["stdout_digest"]
                )
            )
            self.assertEqual(["src/hotfix.txt"], observation["changed_paths"])

    def test_legacy_hotfix_action_aliases_do_not_authorize_canonical_actions(
        self,
    ) -> None:
        for legacy, canonical in (
            ("create_hotfix", "hotfix"),
            ("integrate_hotfix_stable", "hotfix_stable"),
            ("reconcile_hotfix_dev", "hotfix_reconcile_dev"),
        ):
            with self.subTest(legacy=legacy):
                self.assertFalse(
                    authorization_scope_allows(
                        {
                            "record_type": "grant",
                            "run_id": "run-hotfix-alias",
                            "spec_hash": "s" * 64,
                            "config_hash": "c" * 64,
                            "allowed_actions": [legacy],
                            "allowed_environments": [],
                            "allowed_protected_refs": ["dev", "main"],
                        },
                        run_id="run-hotfix-alias",
                        spec_hash="s" * 64,
                        config_hash="c" * 64,
                        action=canonical,
                    )
                )
        self.assertEqual(
            ("hotfix_stable", "HOTFIX_STABLE_GATE"),
            GitController._route_authority("hotfix_to_stable"),
        )
        self.assertEqual(
            ("hotfix_reconcile_dev", "HOTFIX_RECONCILIATION_GATE"),
            GitController._route_authority("hotfix_to_dev"),
        )
        for legacy_route in ("integrate_hotfix_stable", "reconcile_hotfix_dev"):
            with self.assertRaises(GitPolicyError):
                GitController._route_authority(legacy_route)


if __name__ == "__main__":
    unittest.main()
