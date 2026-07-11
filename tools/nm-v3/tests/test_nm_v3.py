from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / "tools/nm-v3/nm_v3.py"
FIXTURES = REPO / "tools/nm-v3/tests/fixtures"


def run(command: list[str], cwd: Path, *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


class NmV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def tool(self, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None, check: bool = True):
        return run(["python3", str(TOOL), *args], cwd or REPO, env=env, check=check)

    def generate(self, name: str = "project") -> Path:
        target = self.root / name
        self.tool("init", "--target", str(target), "--source-dir", str(REPO), "--no-git-init")
        return target

    def link_dependencies(self, target: Path) -> None:
        (target / "node_modules").symlink_to(REPO / "node_modules", target_is_directory=True)

    def make_remote_dev(self, target: Path) -> Path:
        run(["git", "init", "-b", "dev"], target)
        run(["git", "config", "user.name", "NM Test"], target)
        run(["git", "config", "user.email", "nm-test@example.invalid"], target)
        run(["git", "add", "--all"], target)
        run(["git", "commit", "-m", "test: seed project"], target)
        remote = self.root / f"{target.name}.git"
        run(["git", "init", "--bare", str(remote)], self.root)
        run(["git", "remote", "add", "origin", str(remote)], target)
        run(["git", "push", "-u", "origin", "dev"], target)
        return remote

    def test_repository_template_check(self) -> None:
        result = self.tool("check", "--target", str(REPO / "template/v3"), "--source-dir", str(REPO))
        self.assertIn("Template version: 3.1.0", result.stdout)
        self.assertIn("Warnings: 0", result.stdout)

    def test_no_git_init_and_project_check(self) -> None:
        target = self.generate()
        state = json.loads((target / ".nm-template-state.json").read_text())
        self.assertEqual(state["stateSchemaVersion"], 2)
        self.assertEqual(state["templateVersion"], "3.1.0")
        self.assertFalse((target / "0a-docs/spec.md").exists())
        result = self.tool("check", "--target", str(target), "--source-dir", str(REPO))
        self.assertIn("Warnings: 0", result.stdout)

    def test_bootstrap_creates_clean_main_and_dev(self) -> None:
        target = self.root / "bootstrap"
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "NM Test",
                "GIT_AUTHOR_EMAIL": "nm-test@example.invalid",
                "GIT_COMMITTER_NAME": "NM Test",
                "GIT_COMMITTER_EMAIL": "nm-test@example.invalid",
            }
        )
        self.tool("init", "--target", str(target), "--source-dir", str(REPO), env=env)
        self.assertEqual(run(["git", "branch", "--show-current"], target).stdout.strip(), "dev")
        main = run(["git", "rev-parse", "main"], target).stdout.strip()
        dev = run(["git", "rev-parse", "dev"], target).stdout.strip()
        self.assertEqual(main, dev)
        self.assertEqual(run(["git", "status", "--short"], target).stdout.strip(), "")

    def test_update_preserves_project_rules_and_readme(self) -> None:
        target = self.generate("update")
        self.make_remote_dev(target)
        agents = target / "AGENTS.md"
        agents.write_text(agents.read_text().replace("required: []", "required:\n    - custom.md", 1))
        (target / "custom.md").write_text("custom context\n")
        readme = target / "README.md"
        readme.write_text("project-owned README\n")
        chinese = target / "AGENTS.zh-CN.md"
        chinese.write_text(chinese.read_text().replace("required: []", "required:\n    - custom.md", 1))
        run(["git", "add", "--all"], target)
        run(["git", "commit", "-m", "test: customize project"], target)
        run(["git", "push", "origin", "dev"], target)
        self.tool("update", "--target", str(target), "--source-dir", str(REPO))
        self.assertIn("- custom.md", agents.read_text())
        self.assertEqual(readme.read_text(), "project-owned README\n")
        self.assertTrue(run(["git", "branch", "--show-current"], target).stdout.strip().startswith("chore/sync-"))

    def test_create_spec_registers_and_stamps(self) -> None:
        target = self.generate("spec")
        self.make_remote_dev(target)
        for agents_name in ("AGENTS.md", "AGENTS.zh-CN.md"):
            agents = target / agents_name
            agents.write_text(agents.read_text().replace("required: []", "required:\n    - custom.md", 1))
        (target / "custom.md").write_text("required context\n")
        run(["git", "add", "--all"], target)
        run(["git", "commit", "-m", "test: add existing project reference"], target)
        run(["git", "push", "origin", "dev"], target)
        self.tool("create-spec", "--target", str(target), "--source-dir", str(REPO))
        spec = target / "0a-docs/spec.md"
        self.assertTrue(spec.is_file())
        self.assertIn("0a-docs/spec.md", (target / "AGENTS.md").read_text())
        self.assertIn("custom.md", (target / "AGENTS.md").read_text())
        state = json.loads((target / ".nm-template-state.json").read_text())
        self.assertEqual(state["documents"]["spec"]["version"], "0.1.0")
        text = spec.read_text()
        spec.write_text(text.replace("## Goals", "New context.\n\n## Goals"))
        rejected = self.tool("spec-stamp", "--target", str(target), check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("increment spec_version", rejected.stderr)
        spec.write_text(spec.read_text().replace("spec_version: 0.1.0", "spec_version: 0.2.0"))
        self.tool("spec-stamp", "--target", str(target))
        restamped = json.loads((target / ".nm-template-state.json").read_text())
        self.assertEqual(restamped["documents"]["spec"]["version"], "0.2.0")
        accepted = spec.read_text()
        accepted = accepted.replace("  status: pending", "  status: accepted", 1)
        accepted = accepted.replace("  accepted_by: null", '  accepted_by: "Administrator"', 1)
        accepted = accepted.replace("  accepted_spec_version: null", "  accepted_spec_version: 0.2.0", 1)
        accepted = accepted.replace("  accepted_body_sha256: null", f'  accepted_body_sha256: "{"0" * 64}"', 1)
        accepted = accepted.replace("  accepted_at: null", '  accepted_at: "2026-07-11T18:00:00+08:00"', 1)
        spec.write_text(accepted)
        self.link_dependencies(target)
        stale = run(["node", "0d-scripts/check-workflow.mjs"], target, check=False)
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("must bind the current spec version and body hash", stale.stderr)

    def test_migrate_moves_old_documents_to_pending(self) -> None:
        target = self.generate("migration")
        state_path = target / ".nm-template-state.json"
        state = json.loads(state_path.read_text())
        state["templateVersion"] = "3.0.0"
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        product = target / "0a-docs/0a-product"
        product.mkdir(parents=True)
        (product / "REQUIREMENTS.md").write_text("# Requirements\n\nBuild it.\n")
        (product / "ACCEPTANCE.md").write_text("# Acceptance\n\nIt works.\n")
        (target / "AGENTS.md").write_text((FIXTURES / "v3.0/AGENTS.md").read_text())
        (target / "AGENTS.zh-CN.md").write_text((FIXTURES / "v3.0/AGENTS.zh-CN.md").read_text())
        self.make_remote_dev(target)
        self.tool("migrate", "--target", str(target), "--source-dir", str(REPO))
        self.assertTrue((target / "0a-docs/spec.md").is_file())
        pending = target / ".delete-pending/v3-3.1.0-migration/0a-docs/0a-product"
        self.assertTrue((pending / "REQUIREMENTS.md").is_file())
        self.assertTrue((pending / "ACCEPTANCE.md").is_file())
        guidance = target / ".delete-pending/v3-3.1.0-migration/legacy-agent-guidance"
        self.assertIn("custom-context.md", (guidance / "AGENTS.md").read_text())
        self.assertIn("NM-V3-PROJECT-RULES:START", (target / "AGENTS.md").read_text())
        self.assertEqual(json.loads(state_path.read_text())["templateVersion"], "3.1.0")

    def test_transaction_rolls_back_after_injected_failure(self) -> None:
        spec = importlib.util.spec_from_file_location("nm_v3_test_module", TOOL)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        target = self.root / "transaction"
        target.mkdir()
        (target / "one.txt").write_text("old one\n")
        (target / "two.txt").write_text("old two\n")
        with self.assertRaises(module.NmV3Error):
            module.apply_transaction(
                target,
                {"one.txt": b"new one\n", "two.txt": b"new two\n"},
                fail_after=1,
            )
        self.assertEqual((target / "one.txt").read_text(), "old one\n")
        self.assertEqual((target / "two.txt").read_text(), "old two\n")

    def test_reference_cannot_escape_project(self) -> None:
        target = self.generate("unsafe-reference")
        self.link_dependencies(target)
        for name in ("AGENTS.md", "AGENTS.zh-CN.md"):
            path = target / name
            path.write_text(path.read_text().replace("required: []", "required:\n    - ../outside.md", 1))
        result = run(["node", "0d-scripts/check-workflow.mjs"], target, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not contain . or ..", result.stderr)

    def test_skill_install_bundles_exact_tool(self) -> None:
        target = self.generate("skill-status")
        skill_root = self.root / "skills"
        self.tool("install-skill", "--target-dir", str(skill_root), "--source-dir", str(REPO))
        installed = skill_root / "nm-init-project-v3"
        binding = json.loads((installed / ".nm-v3-binding.json").read_text())
        bundled = installed / "scripts/vendor/nm_v3.py"
        self.assertTrue(bundled.is_file())
        self.assertEqual(binding["templateVersion"], "3.1.0")
        self.assertEqual(binding["toolSha256"], __import__("hashlib").sha256(bundled.read_bytes()).hexdigest())
        wrapper = installed / "scripts/run_nm_v3.py"
        self.assertNotIn("urllib", wrapper.read_text())
        result = run(["python3", str(wrapper), "status", "--target", str(target)], REPO)
        self.assertIn("Managed drift: 0", result.stdout)

    def test_planned_goal_requires_parent_plan(self) -> None:
        target = self.generate("orphan-goal")
        self.link_dependencies(target)
        goal = target / "0b-goals/0b-current/goal-p999-g001-orphan.md"
        goal.write_text(
            "---\n"
            "schema_version: 1\n"
            "plan_id: p999\n"
            "goal_id: g001\n"
            "status: planned\n"
            "source_type: plan\n"
            "base_branch: feature/plan-p999-orphan\n"
            "working_branch: task/goal-p999-g001-orphan\n"
            "verification_status: not_run\n"
            "verification_commit: null\n"
            "self_review_status: not_run\n"
            "independent_review_status: not_required\n"
            "integration_status: not_integrated\n"
            "integration_commit: null\n"
            "review:\n"
            "  independent_reviewer_required: false\n"
            "---\n\n# Goal: Orphan\n"
        )
        result = run(["node", "0d-scripts/check-workflow.mjs"], target, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("parent Plan does not exist", result.stderr)

    def test_notification_routes_strict_channels_and_rejects_shell_config(self) -> None:
        target = self.generate("notify")
        home = self.root / "home"
        config = home / ".config/nm-docs/nm-notify-feishu.env"
        config.parent.mkdir(parents=True)
        config.write_text(
            'FEISHU_WEBHOOK_PROGRESS="https://example.invalid/progress"\n'
            'FEISHU_SIGN_SECRET_PROGRESS="progress-secret"\n'
            'FEISHU_WEBHOOK_ATTENTION="https://example.invalid/attention"\n'
            'FEISHU_SIGN_SECRET_ATTENTION="attention-secret"\n'
        )
        config.chmod(0o600)
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake_curl = fake_bin / "curl"
        fake_curl.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "config=''\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  if [ \"$1\" = --config ]; then config=$2; shift 2; else shift; fi\n"
            "done\n"
            "cat \"$config\" > \"$NM_TEST_CONFIG\"\n"
            "cat > \"$NM_TEST_PAYLOAD\"\n"
            "printf 'x\\n' >> \"$NM_TEST_COUNT\"\n"
            "printf '{\"code\":0,\"msg\":\"ok\"}'\n"
        )
        fake_curl.chmod(0o755)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "PATH": f"{fake_bin}:{env['PATH']}",
                "NM_TEST_CONFIG": str(self.root / "curl-config"),
                "NM_TEST_PAYLOAD": str(self.root / "payload"),
                "NM_TEST_COUNT": str(self.root / "curl-count"),
            }
        )
        script = target / "0d-scripts/notify-event.sh"
        run([str(script), "--event", "notify_test", "--severity", "progress", "--message", "hello"], target, env=env)
        self.assertIn("/progress", (self.root / "curl-config").read_text())
        payload = (self.root / "payload").read_text()
        self.assertNotIn("progress-secret", payload)
        run([str(script), "--event", "notify_test", "--severity", "attention", "--message", "look"], target, env=env)
        self.assertIn("/attention", (self.root / "curl-config").read_text())
        run([str(script), "--event", "work_completed", "--severity", "attention", "--message", "done"], target, env=env)
        self.assertIn("/attention", (self.root / "curl-config").read_text())
        payload = json.loads((self.root / "payload").read_text())
        self.assertEqual(payload["card"]["header"]["template"], "green")
        self.assertIn("severity=attention", payload["card"]["elements"][0]["text"]["content"])
        run([str(script), "--event", "decision_required", "--severity", "attention"], target, env=env)
        payload = json.loads((self.root / "payload").read_text())
        self.assertEqual(payload["card"]["header"]["template"], "yellow")
        run([str(script), "--event", "validation_failed", "--severity", "attention"], target, env=env)
        payload = json.loads((self.root / "payload").read_text())
        self.assertEqual(payload["card"]["header"]["template"], "red")
        mismatch = run(
            [str(script), "--event", "work_completed", "--severity", "progress", "--message", "done"],
            target,
            env=env,
            check=False,
        )
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("requires severity=attention", mismatch.stderr)

        count = self.root / "curl-count"
        count.write_text("")
        self.link_dependencies(target)
        goal = target / "0b-goals/0b-current/goal-g001-finish.md"
        goal.write_text(
            "---\n"
            "schema_version: 1\n"
            "plan_id: null\n"
            "goal_id: g001\n"
            "status: verified\n"
            "source_type: administrator_request\n"
            "base_branch: dev\n"
            "working_branch: task/goal-g001-finish\n"
            "verification_status: pass\n"
            f"verification_commit: {'a' * 40}\n"
            "self_review_status: pass\n"
            "independent_review_status: not_required\n"
            "integration_status: not_integrated\n"
            "integration_commit: null\n"
            "review:\n"
            "  independent_reviewer_required: false\n"
            "---\n\n"
            "# Goal: Finish\n\n"
            "## Objective\n\nFinish safely.\n\n"
            "## Scope\n\n- Completion handoff.\n\n"
            "## TODO\n\n- [x] Verify.\n\n"
            "## Acceptance Criteria\n\n- Notification is sent once.\n\n"
            "## Verification\n\n`npm test` passed.\n"
        )
        self.tool("finish", "--target", str(target), "--file", str(goal.relative_to(target)), env=env)
        self.tool("finish", "--target", str(target), "--file", str(goal.relative_to(target)), env=env)
        self.assertEqual(count.read_text().splitlines(), ["x"])
        notification_state = json.loads((target / ".nm-template-state.json").read_text())["notifications"]
        self.assertEqual(notification_state["work_completed:0b-goals/0b-current/goal-g001-finish.md"]["status"], "sent")

        marker = self.root / "executed"
        config.write_text(
            config.read_text() + f'MALICIOUS=$(touch "{marker}")\n'
        )
        result = run([str(script), "--event", "notify_test", "--severity", "progress"], target, env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())

        config.write_text(
            'FEISHU_WEBHOOK_PROGRESS="https://example.invalid/same"\n'
            'FEISHU_WEBHOOK_ATTENTION="https://example.invalid/same"\n'
        )
        config.chmod(0o600)
        result = run([str(script), "--event", "notify_test", "--severity", "attention"], target, env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be distinct", result.stderr)


if __name__ == "__main__":
    unittest.main()
