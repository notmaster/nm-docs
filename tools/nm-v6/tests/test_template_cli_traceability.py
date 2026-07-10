from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = TOOL_ROOT.parents[1]
sys.path.insert(0, str(TOOL_ROOT))

import generate_traceability
from nmv6.cli import _acceptance_source_change, build_parser
from nmv6.errors import ContractError, GitPolicyError, NmV6Error
from nmv6.repository_check import _check_bilingual, check_repository, check_skill
from nmv6.template_sync import (
    abort_update,
    check_installed_project,
    initialize_project,
    resume_update,
    update_project,
)
from nmv6.traceability import (
    ADMINISTRATOR_ACCEPTANCE_RECORD_PATH,
    ADMINISTRATOR_ACCEPTANCE_SCHEMA_VERSION,
    EVIDENCE_ONLY_PATHS,
    GENERATED_TRACEABILITY_PATHS,
    administrator_acceptance_binding,
    current_changed_files,
    discover_test_inventory,
    render_traceability_markdown,
    source_change_record,
    spec_traceability,
    independent_review_digest,
    validate_administrator_acceptance_record,
    validate_changed_file_mapping,
    validate_implementation_plan,
    validate_static_traceability,
    validate_source_change_record,
    validate_test_selector,
)
from nmv6.util import canonical_json, dump_json, sha256_bytes


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def prepare_update_fixture(root: Path) -> tuple[Path, Path, Path]:
    target = root / "project"
    remote = root / "remote.git"
    initialize_project(target, source_root=REPOSITORY)
    git(root, "init", "--bare", str(remote))
    git(target, "remote", "add", "origin", str(remote))
    git(target, "push", "origin", "main:main", "dev:dev")
    user_file = target / "project-owned.txt"
    user_file.write_text("preserve me\n", encoding="utf-8")
    git(target, "add", "project-owned.txt")
    git(
        target,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@invalid",
        "commit",
        "-m",
        "test: project file",
    )
    git(target, "branch", "--force", "dev", "HEAD")
    git(target, "push", "origin", "dev:dev")
    return target, remote, user_file


def interrupt_update(target: Path, *, branch: str) -> Path:
    with mock.patch.dict(os.environ, {"NM_V6_UPDATE_FAIL_AFTER": "1"}):
        with unittest.TestCase().assertRaises(NmV6Error):
            update_project(
                target,
                source_root=REPOSITORY,
                branch=branch,
            )
    journals = sorted((target / ".nm/update/v6").glob("*/journal.json"))
    if len(journals) != 1:
        raise AssertionError(f"expected one durable update journal, got {journals}")
    return journals[0]


def rewrite_journal(path: Path, journal: dict[str, object]) -> None:
    journal["plan_digest"] = sha256_bytes(
        canonical_json({"plan": journal["plan"], "state": journal["state"]})
    )
    without_digest = {key: value for key, value in journal.items() if key != "journal_digest"}
    journal["journal_digest"] = sha256_bytes(canonical_json(without_digest))
    path.write_bytes(dump_json(journal))


def prepare_bilingual_fixture(root: Path) -> None:
    for relative in (
        "docs/nm-v6-workflow-spec.md",
        "docs/nm-v6-workflow-spec.zh-CN.md",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY / relative, destination)
    for english_relative, chinese_relative in (
        ("AGENTS.md", "AGENTS.zh-CN.md"),
        ("README.md", "docs/README.zh-CN.md"),
        ("docs/template-versions.md", "docs/template-versions.zh-CN.md"),
        ("docs/installation.md", "docs/installation.zh-CN.md"),
        ("template/v6/AGENTS.md", "template/v6/AGENTS.zh-CN.md"),
        (
            "docs/nm-v6-bilingual-semantic-review.md",
            "docs/nm-v6-bilingual-semantic-review.zh-CN.md",
        ),
        (
            "docs/nm-v6-implementation-traceability.md",
            "docs/nm-v6-implementation-traceability.zh-CN.md",
        ),
    ):
        english = root / english_relative
        chinese = root / chinese_relative
        english.parent.mkdir(parents=True, exist_ok=True)
        chinese.parent.mkdir(parents=True, exist_ok=True)
        english.write_text("# English fixture\n\n- V6-REQ-021\n", encoding="utf-8")
        chinese.write_text("# 中文测试\n\n- V6-REQ-021\n", encoding="utf-8")
    shutil.copytree(
        REPOSITORY / "template/v6/0c-workflow",
        root / "template/v6/0c-workflow",
    )


def prepare_source_binding_fixture(
    root: Path,
) -> tuple[Path, Path, dict[str, object], str, str, str]:
    repository = root / "repository"
    remote = root / "remote.git"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.name", "Evidence Fixture")
    git(repository, "config", "user.email", "evidence@invalid")
    baseline = repository / "baseline.txt"
    baseline.write_text("baseline\n", encoding="utf-8")
    spec = repository / "docs/nm-v6-workflow-spec.md"
    spec.parent.mkdir(parents=True)
    shutil.copy2(REPOSITORY / "docs/nm-v6-workflow-spec.md", spec)
    git(repository, "add", "baseline.txt", "docs/nm-v6-workflow-spec.md")
    git(repository, "commit", "-m", "baseline")
    base_sha = git(repository, "rev-parse", "HEAD")
    git(repository, "branch", "dev", base_sha)
    git(root, "init", "--bare", str(remote))
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "push", "-u", "origin", "dev:dev")
    git(repository, "switch", "-c", "feature/evidence", base_sha)

    implementation = repository / "tools/nm-v6/nmv6/example.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("VALUE = 6\n", encoding="utf-8")
    git(repository, "add", "tools/nm-v6/nmv6/example.py")
    git(repository, "commit", "-m", "implement source")
    tested_sha = git(repository, "rev-parse", "HEAD")
    source = source_change_record(repository)

    for relative in EVIDENCE_ONLY_PATHS:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"generated: {relative}\n", encoding="utf-8")
    git(repository, "add", *sorted(EVIDENCE_ONLY_PATHS))
    git(repository, "commit", "-m", "record acceptance evidence")
    evidence_sha = git(repository, "rev-parse", "HEAD")
    return repository, remote, source, base_sha, tested_sha, evidence_sha


def minimal_traceability_manifest() -> dict[str, object]:
    acceptance = {
        "V6-AC-001": {
            "requirements": ["V6-REQ-001"],
            "tests": ["fixture.py::FixtureTests.test_evidence"],
            "status": "pass",
        }
    }
    return {
        "spec_hash": "62196ab27c2be08ea1c716081903a009185f1d518ba7a53ed9b3d8485236cb7f",
        "implementation_status": "acceptance-candidate",
        "administrator_acceptance": "pending",
        "acceptance": acceptance,
        "requirements": {
            "V6-REQ-001": {
                "files": ["fixture.py"],
                "acceptance": ["V6-AC-001"],
            }
        },
        "files": {"fixture.py": ["V6-REQ-001"]},
        "evidence": {
            "automated": {
                "result_file_sha256": "result-digest",
                "result": {
                    "source_change": {"digest": "source-digest"},
                    "test_inventory": {"digest": "inventory-digest"},
                    "command_digest": "command-digest",
                    "summary": {"tests_run": 1},
                },
            }
        },
    }


class TemplateAndCliAcceptanceTests(unittest.TestCase):
    def test_ac037_init_is_clean_and_protected_refs_are_not_the_commit_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            initialize_project(
                target,
                source_root=REPOSITORY,
                project_name="Fixture",
                package_name="fixture",
            )
            self.assertEqual(git(target, "status", "--porcelain=v1"), "")
            self.assertEqual(git(target, "branch", "--show-current"), "task/nm-v6-bootstrap")
            self.assertTrue(git(target, "show-ref", "--verify", "refs/heads/main"))
            self.assertTrue(git(target, "show-ref", "--verify", "refs/heads/dev"))
            self.assertEqual(
                git(target, "log", "-1", "--format=%D", "refs/heads/main").find("HEAD -> main"),
                -1,
            )

    def test_ac038_interrupted_update_can_abort_without_losing_user_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, _, user_file = prepare_update_fixture(root)
            journal = interrupt_update(target, branch="chore/test-v6-update")
            self.assertEqual(journal.parent.parent, target / ".nm/update/v6")
            self.assertTrue((journal.parent / "rendered").is_dir())
            self.assertTrue((journal.parent / "backup").is_dir())
            abort_update(target)
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")
            self.assertEqual(list((target / ".nm/update/v6").iterdir()), [])

    def test_ac038_interrupted_update_resumes_from_durable_project_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, _, user_file = prepare_update_fixture(root)
            journal = interrupt_update(target, branch="chore/test-v6-resume")
            operation_root = journal.parent
            self.assertTrue(str(operation_root).startswith(str(target / ".nm/update/v6")))
            result = resume_update(target, REPOSITORY)
            self.assertEqual(result["branch"], "chore/test-v6-resume")
            self.assertFalse(operation_root.exists())
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")
            self.assertEqual(check_installed_project(target)["result"], "passed")

    def test_ac038_missing_stage_or_backup_fails_closed_without_deleting_prior_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, _, user_file = prepare_update_fixture(root)
            journal_path = interrupt_update(target, branch="chore/test-v6-missing-stage")
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            first = journal["plan"]["files"][0]
            destination = target / first["target"]
            destination_before = destination.read_bytes()
            staged = journal_path.parent / "rendered" / first["target"]
            staged.unlink()
            with self.assertRaisesRegex(ContractError, "staged file"):
                resume_update(target, REPOSITORY)
            with self.assertRaisesRegex(ContractError, "staged file"):
                abort_update(target)
            self.assertEqual(destination.read_bytes(), destination_before)
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")
            self.assertTrue(journal_path.is_file())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, _, user_file = prepare_update_fixture(root)
            journal_path = interrupt_update(target, branch="chore/test-v6-missing-backup")
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            applied = journal["plan"]["files"][journal["next_index"] - 1]
            self.assertIsNotNone(applied["previous_sha256"])
            destination = target / applied["target"]
            destination_before = destination.read_bytes()
            backup = journal_path.parent / "backup" / applied["target"]
            backup.unlink()
            with self.assertRaisesRegex(ContractError, "backup"):
                abort_update(target)
            with self.assertRaisesRegex(ContractError, "backup"):
                resume_update(target, REPOSITORY)
            self.assertTrue(destination.is_file())
            self.assertEqual(destination.read_bytes(), destination_before)
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")
            self.assertTrue(journal_path.is_file())

    def test_ac038_journal_traversal_tamper_and_recovery_context_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, _, user_file = prepare_update_fixture(root)
            journal_path = interrupt_update(target, branch="chore/test-v6-path-tamper")
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            journal["plan"]["files"][0]["target"] = "../../outside.txt"
            rewrite_journal(journal_path, journal)
            outside = root / "outside.txt"
            outside.write_text("do not touch\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "inside|unsafe|escape"):
                abort_update(target)
            self.assertEqual(outside.read_text(encoding="utf-8"), "do not touch\n")
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, _, user_file = prepare_update_fixture(root)
            journal_path = interrupt_update(target, branch="chore/test-v6-digest-tamper")
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            original = json.loads(json.dumps(journal))
            journal["next_index"] = 0
            journal_path.write_bytes(dump_json(journal))
            with self.assertRaisesRegex(ContractError, "digest mismatch"):
                resume_update(target, REPOSITORY)
            original["plan"]["created_at"] = "tampered"
            without_digest = {
                key: value for key, value in original.items() if key != "journal_digest"
            }
            original["journal_digest"] = sha256_bytes(canonical_json(without_digest))
            journal_path.write_bytes(dump_json(original))
            with self.assertRaisesRegex(ContractError, "plan digest mismatch"):
                resume_update(target, REPOSITORY)
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, _, user_file = prepare_update_fixture(root)
            interrupt_update(target, branch="chore/test-v6-delta")
            unexpected = target / "unexpected-user-change.txt"
            unexpected.write_text("unrelated\n", encoding="utf-8")
            with self.assertRaisesRegex(GitPolicyError, "outside the recorded update"):
                abort_update(target)
            self.assertTrue(unexpected.is_file())
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, _, user_file = prepare_update_fixture(root)
            interrupt_update(target, branch="chore/test-v6-branch")
            git(target, "switch", "dev")
            with self.assertRaisesRegex(GitPolicyError, "recorded update branch"):
                abort_update(target)
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, _, user_file = prepare_update_fixture(root)
            interrupt_update(target, branch="chore/test-v6-head")
            git(
                target,
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@invalid",
                "commit",
                "--allow-empty",
                "-m",
                "move recovery HEAD",
            )
            with self.assertRaisesRegex(GitPolicyError, "recorded update baseline"):
                resume_update(target, REPOSITORY)
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, remote, user_file = prepare_update_fixture(root)
            interrupt_update(target, branch="chore/test-v6-remote")
            updater = root / "updater"
            git(root, "clone", str(remote), str(updater))
            git(updater, "config", "user.name", "Remote updater")
            git(updater, "config", "user.email", "remote-updater@invalid")
            git(updater, "switch", "dev")
            (updater / "remote-moved.txt").write_text("moved\n", encoding="utf-8")
            git(updater, "add", "remote-moved.txt")
            git(updater, "commit", "-m", "move remote dev")
            git(updater, "push", "origin", "dev")
            with self.assertRaisesRegex(GitPolicyError, "stale|moved"):
                abort_update(target)
            self.assertEqual(user_file.read_text(encoding="utf-8"), "preserve me\n")

    def test_ac039_and_ac042_installed_check_rejects_v5_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            initialize_project(target, source_root=REPOSITORY)
            self.assertEqual(check_installed_project(target)["result"], "passed")
            legacy = target / "0b-runtime/INDEX.yaml"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("version: 5\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "V5 mutable"):
                check_installed_project(target)

    def test_ac039_repository_check_rejects_tampered_traceability_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in range(1, 6):
                (root / f"template/v{version}").mkdir(parents=True)
            (root / "README.md").write_text("V5 remains experimental.\n", encoding="utf-8")
            spec = root / "docs/nm-v6-workflow-spec.md"
            spec.parent.mkdir(parents=True)
            shutil.copy2(REPOSITORY / "docs/nm-v6-workflow-spec.md", spec)
            project = root / "template/v6/project.example.json"
            project.parent.mkdir(parents=True)
            project.write_text("{}\n", encoding="utf-8")
            manifest = minimal_traceability_manifest()
            english = root / "docs/nm-v6-implementation-traceability.md"
            chinese = root / "docs/nm-v6-implementation-traceability.zh-CN.md"
            english.write_text(
                render_traceability_markdown(manifest, chinese=False),
                encoding="utf-8",
            )
            chinese.write_text(
                render_traceability_markdown(manifest, chinese=True),
                encoding="utf-8",
            )
            english.write_text(english.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
            with (
                mock.patch("nmv6.repository_check.validate_project_config"),
                mock.patch(
                    "nmv6.repository_check.validate_dependency_constraints",
                    return_value={},
                ),
                mock.patch("nmv6.repository_check.validate_schema_catalog", return_value={}),
                mock.patch("nmv6.repository_check.validate_legacy_preservation", return_value={}),
                mock.patch(
                    "nmv6.repository_check.validate_implementation_plan",
                    return_value={
                        "spec_hash": manifest["spec_hash"],
                        "status": "acceptance-candidate",
                        "administrator_acceptance": "pending",
                        "administrator_acceptance_record": None,
                        "recommended": False,
                        "production_ready": False,
                    },
                ),
                mock.patch(
                    "nmv6.repository_check.validate_acceptance_manifest",
                    return_value=manifest,
                ),
            ):
                with self.assertRaisesRegex(ContractError, "traceability report is stale"):
                    check_repository(root)

    def test_ac041_generated_project_commands_pass_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            initialize_project(target, source_root=REPOSITORY)
            environment = {**os.environ, "NM_V6_PYTHON": sys.executable}
            for command in ("workflow:check", "workflow:test", "verify"):
                result = subprocess.run(
                    ["npm", "run", command],
                    cwd=target,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    msg=f"{command} failed:\n{result.stdout}\n{result.stderr}",
                )
            plan = subprocess.run(
                [
                    str(target / "0d-scripts/python311.sh"),
                    str(target / "0d-scripts/nm-v6.py"),
                    "plan",
                    "--target",
                    str(target),
                    "--run-id",
                    "run-generated",
                ],
                cwd=target,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(plan.returncode, 0, msg=plan.stderr)
            self.assertEqual(json.loads(plan.stdout)["state"], "SPEC_REVIEW")
            status = subprocess.run(
                [
                    str(target / "0d-scripts/python311.sh"),
                    str(target / "0d-scripts/nm-v6.py"),
                    "status",
                    "--target",
                    str(target),
                    "--run-id",
                    "run-generated",
                    "--json",
                ],
                cwd=target,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(status.returncode, 0, msg=status.stderr)
            status_document = json.loads(status.stdout)
            self.assertEqual(status_document["state"], "SPEC_REVIEW")
            version_baseline = status_document["run"]["payload"]["version_baseline"]
            self.assertEqual(version_baseline["schema_version"], "nm-v6/version-record-v1")
            self.assertTrue(version_baseline["schemas"])
            self.assertTrue(version_baseline["adapters"])

    def test_ac044_repository_bilingual_check_covers_workflow_and_missing_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_bilingual_fixture(root)
            result = _check_bilingual(root)
            self.assertEqual(result["workflow_pairs"], 9)
            self.assertEqual(result["pairs"], 17)

        missing_cases = (
            "template/v6/0c-workflow/adapters/grok.zh-CN.md",
            "template/v6/0c-workflow/recovery/git.md",
        )
        for relative in missing_cases:
            with self.subTest(missing=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                prepare_bilingual_fixture(root)
                (root / relative).unlink()
                with self.assertRaisesRegex(ContractError, "missing bilingual pair"):
                    _check_bilingual(root)

    def test_ac044_repository_bilingual_check_rejects_id_and_structure_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_bilingual_fixture(root)
            chinese = root / "template/v6/0c-workflow/adapters/claude.zh-CN.md"
            chinese.write_text(
                chinese.read_text(encoding="utf-8") + "\nV6-REQ-999\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "semantic IDs"):
                _check_bilingual(root)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_bilingual_fixture(root)
            chinese = root / "template/v6/0c-workflow/recovery/agent.zh-CN.md"
            content = chinese.read_text(encoding="utf-8")
            chinese.write_text(content.replace("# ", "## ", 1), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "heading hierarchy"):
                _check_bilingual(root)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_bilingual_fixture(root)
            chinese = root / "template/v6/0c-workflow/PROTOCOLS.zh-CN.md"
            chinese.write_text(
                chinese.read_text(encoding="utf-8") + "\n- 结构漂移\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "list structure"):
                _check_bilingual(root)

    def test_ac045_implementation_plan_maps_every_requirement(self) -> None:
        plan = validate_implementation_plan(TOOL_ROOT / "implementation-plan.json")
        self.assertEqual(len(plan["requirements"]), 24)
        changed = sorted(set(current_changed_files(REPOSITORY)) | GENERATED_TRACEABILITY_PATHS)
        files = {path: generate_traceability.map_file(path) for path in changed}
        validate_changed_file_mapping({"files": files}, changed_files=changed)
        self.assertEqual(
            {requirement for requirements in files.values() for requirement in requirements},
            {f"V6-REQ-{index:03d}" for index in range(1, 25)},
        )
        with self.assertRaisesRegex(ContractError, "bidirectional"):
            validate_changed_file_mapping(
                {"files": {**files, "stale-unrelated.txt": ["V6-REQ-024"]}},
                changed_files=changed,
            )
        with self.assertRaisesRegex(ContractError, "bidirectional"):
            validate_changed_file_mapping(
                {"files": files},
                changed_files=[
                    *changed,
                    "tools/nm-v6/nmv6/__pycache__/tracked.pyc",
                ],
            )
        with self.assertRaisesRegex(ContractError, "no explicit"):
            generate_traceability.map_file("unrelated-new-file.txt")
        inventory = discover_test_inventory(REPOSITORY)
        for selectors in generate_traceability.TESTS.values():
            for selector in selectors:
                validate_test_selector(selector, inventory=inventory)
        broken_class = (
            "tools/nm-v6/tests/test_state_auth_evidence.py::"
            "StoreReducerTests.test_schema_required_fields_and_versions_match_runtime_outputs"
        )
        with self.assertRaisesRegex(ContractError, "not discovered exactly"):
            validate_test_selector(broken_class, inventory=inventory)
        self.assertEqual(
            generate_traceability._acceptance_status(["test"], {"test": "skip"}),
            "not_run",
        )
        self.assertEqual(
            generate_traceability._acceptance_status(["test"], {"test": "fail"}),
            "fail",
        )

    def test_ac045_acceptance_binding_survives_evidence_commit_ref_move_and_clone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, remote, source, base_sha, tested_sha, evidence_sha = (
                prepare_source_binding_fixture(root)
            )
            self.assertEqual(source["base_ref_sha"], base_sha)
            self.assertEqual(source["merge_base_sha"], base_sha)
            self.assertEqual(source["head_sha"], tested_sha)
            self.assertEqual(source["files"]["tools/nm-v6/nmv6/example.py"]["mode"], "100644")
            self.assertEqual(validate_source_change_record(source, repository=repository), source)
            git(repository, "switch", "--detach", tested_sha)
            self.assertEqual(_acceptance_source_change(repository), source)
            git(repository, "switch", "--detach", evidence_sha)
            expected_scope = sorted(set(source["files"]) | EVIDENCE_ONLY_PATHS)
            self.assertEqual(
                current_changed_files(repository, base_sha=base_sha),
                expected_scope,
            )

            embedded = {"evidence": {"automated": {"result": {"source_change": source}}}}
            with mock.patch(
                "nmv6.traceability.validate_acceptance_manifest",
                return_value=embedded,
            ):
                self.assertEqual(_acceptance_source_change(repository), source)
                git(repository, "update-ref", "refs/remotes/origin/dev", evidence_sha)
                self.assertEqual(_acceptance_source_change(repository), source)
                self.assertEqual(validate_source_change_record(source, repository=repository), source)
                self.assertEqual(
                    current_changed_files(repository, base_sha=base_sha),
                    expected_scope,
                )

                git(repository, "push", "origin", f"{evidence_sha}:dev")
                git(remote, "symbolic-ref", "HEAD", "refs/heads/dev")
                clone = root / "clone"
                git(root, "clone", "--branch", "dev", str(remote), str(clone))
                self.assertEqual(_acceptance_source_change(clone), source)
                self.assertEqual(validate_source_change_record(source, repository=clone), source)
                self.assertEqual(
                    current_changed_files(clone, base_sha=base_sha),
                    expected_scope,
                )

    def test_ac045_acceptance_binding_rejects_source_drift_extra_and_nonancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, _, source, base_sha, _, evidence_sha = prepare_source_binding_fixture(root)
            implementation = repository / "tools/nm-v6/nmv6/example.py"
            implementation.write_text("VALUE = 7\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "evidence-only descendant"):
                validate_source_change_record(source, repository=repository)
            git(repository, "restore", "--", "tools/nm-v6/nmv6/example.py")

            extra = repository / "tools/nm-v6/nmv6/extra.py"
            extra.write_text("EXTRA = True\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "evidence-only descendant"):
                validate_source_change_record(source, repository=repository)
            extra.unlink()

            git(repository, "switch", "--detach", base_sha)
            with self.assertRaisesRegex(ContractError, "not an ancestor of the current HEAD"):
                validate_source_change_record(source, repository=repository)
            git(repository, "switch", "--detach", evidence_sha)

            with (
                mock.patch(
                    "nmv6.traceability.validate_acceptance_manifest",
                    side_effect=ContractError("stale acceptance manifest"),
                ),
                mock.patch("nmv6.traceability.source_change_record") as fallback,
            ):
                with self.assertRaisesRegex(ContractError, "stale acceptance manifest"):
                    _acceptance_source_change(repository)
                fallback.assert_not_called()

            manifest_path = repository / "tools/nm-v6/acceptance-manifest.json"
            manifest_path.write_text("tampered\n", encoding="utf-8")
            with mock.patch("nmv6.traceability.source_change_record") as fallback:
                with self.assertRaisesRegex(ContractError, "differs from the index or working tree"):
                    _acceptance_source_change(repository)
                fallback.assert_not_called()

    def test_ac045_administrator_acceptance_is_explicit_exact_and_nonproduction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, _, source, _, _, _ = prepare_source_binding_fixture(root)
            result_sha = "a" * 64
            acceptance_result = {"result": "passed", "source_change": source}
            review = {"status": "pass", "reviewer": "independent-fixture"}
            record = {
                "schema_version": ADMINISTRATOR_ACCEPTANCE_SCHEMA_VERSION,
                "decision": "accepted",
                "spec_id": "SPEC-NM-WORKFLOW-V6-V1",
                "spec_version": 1,
                "spec_hash": "62196ab27c2be08ea1c716081903a009185f1d518ba7a53ed9b3d8485236cb7f",
                "source_change_digest": source["digest"],
                "base_sha": source["base_ref_sha"],
                "head_sha": source["head_sha"],
                "acceptance_result_sha256": result_sha,
                "independent_review_sha256": independent_review_digest(review),
                "recommended": False,
                "production_ready": False,
                "recorded_at": "2026-07-10T12:00:00+08:00",
                "authority_basis": "Explicit administrator decision for the exact tested source.",
            }
            record_path = repository / ADMINISTRATOR_ACCEPTANCE_RECORD_PATH
            record_path.write_bytes(dump_json(record))
            self.assertEqual(
                validate_administrator_acceptance_record(
                    record_path,
                    repository=repository,
                    acceptance_result=acceptance_result,
                    acceptance_result_sha256=result_sha,
                    independent_review=review,
                ),
                record,
            )
            binding = administrator_acceptance_binding(
                record_path,
                repository=repository,
                record=record,
            )
            self.assertEqual(binding["record_path"], ADMINISTRATOR_ACCEPTANCE_RECORD_PATH)
            self.assertEqual(len(binding["record_sha256"]), 64)
            self.assertFalse(binding["recommended"])
            self.assertFalse(binding["production_ready"])
            rendered_manifest = minimal_traceability_manifest()
            rendered_manifest["implementation_status"] = "accepted"
            rendered_manifest["administrator_acceptance"] = "accepted"
            rendered_manifest["evidence"]["administrator_acceptance"] = binding
            english_report = render_traceability_markdown(rendered_manifest, chinese=False)
            chinese_report = render_traceability_markdown(rendered_manifest, chinese=True)
            self.assertIn("Implementation status: `accepted`", english_report)
            self.assertIn("Administrator acceptance record:", english_report)
            self.assertIn("管理员接受：`accepted`", chinese_report)
            self.assertEqual(
                generate_traceability._implementation_state(None),
                ("acceptance-candidate", "pending"),
            )
            self.assertEqual(
                generate_traceability._implementation_state(binding),
                ("accepted", "accepted"),
            )

            mutations = {
                "decision": "rejected",
                "source_change_digest": "b" * 64,
                "base_sha": "b" * 40,
                "head_sha": "b" * 40,
                "acceptance_result_sha256": "b" * 64,
                "independent_review_sha256": "b" * 64,
                "recommended": True,
                "production_ready": True,
                "recorded_at": "not-a-time",
                "authority_basis": "invalid\nsecond line",
            }
            for field, value in mutations.items():
                with self.subTest(field=field):
                    invalid = {**record, field: value}
                    record_path.write_bytes(dump_json(invalid))
                    with self.assertRaises(ContractError):
                        validate_administrator_acceptance_record(
                            record_path,
                            repository=repository,
                            acceptance_result=acceptance_result,
                            acceptance_result_sha256=result_sha,
                            independent_review=review,
                        )
            record_path.write_bytes(dump_json({**record, "unexpected": True}))
            with self.assertRaisesRegex(ContractError, "invalid fields"):
                validate_administrator_acceptance_record(
                    record_path,
                    repository=repository,
                    acceptance_result=acceptance_result,
                    acceptance_result_sha256=result_sha,
                    independent_review=review,
                )

            record_path.write_bytes(dump_json(record))
            outside = root / "administrator-acceptance.json"
            outside.write_bytes(dump_json(record))
            with self.assertRaisesRegex(ContractError, "canonical repository record path"):
                validate_administrator_acceptance_record(
                    outside,
                    repository=repository,
                    acceptance_result=acceptance_result,
                    acceptance_result_sha256=result_sha,
                    independent_review=review,
                )

            schema = json.loads(
                (
                    REPOSITORY
                    / "tools/nm-v6/schemas/administrator-acceptance-v1.schema.json"
                ).read_text(encoding="utf-8")
            )
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(record))

    def test_ac059_decisions_and_invariants_reach_executable_acceptance(self) -> None:
        spec_path = REPOSITORY / "docs/nm-v6-workflow-spec.md"
        coverage = spec_traceability(spec_path)
        self.assertEqual(sum(map(len, coverage["requirements"].values())), 91)
        self.assertEqual(sum(map(len, coverage["decisions"].values())), 19)
        self.assertEqual(sum(map(len, coverage["invariants"].values())), 29)
        acceptance = {
            f"V6-AC-{index:03d}": {
                "tests": generate_traceability.TESTS[index]
            }
            for index in range(1, 61)
        }
        result = validate_static_traceability(
            spec_path,
            acceptance=acceptance,
            inventory=discover_test_inventory(REPOSITORY),
        )
        self.assertEqual(
            result,
            {"decisions": 9, "invariants": 16, "requirements": 24, "acceptance": 60},
        )

    def test_ac020_cli_exposes_required_surface(self) -> None:
        help_text = build_parser().format_help()
        for command in (
            "init",
            "update",
            "check",
            "status",
            "spec",
            "plan",
            "mode",
            "authorize",
            "run",
            "pause",
            "resume",
            "cancel",
            "reconcile",
            "adapter",
            "evidence",
            "audit",
            "notify-test",
        ):
            self.assertIn(command, help_text)

    def test_ac020_skill_is_thin_and_has_no_download_fallback(self) -> None:
        result = check_skill(REPOSITORY, REPOSITORY / "skills/nm-init-project-v6")
        self.assertEqual(result["result"], "passed")

    def test_ac043_installed_skill_binds_exact_source_and_ignores_hostile_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "skills"
            install = subprocess.run(
                [
                    sys.executable,
                    str(TOOL_ROOT / "nm_v6.py"),
                    "install-skill",
                    "--source-dir",
                    str(REPOSITORY),
                    "--target-dir",
                    str(target),
                ],
                cwd=REPOSITORY,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, install.returncode, msg=install.stderr)
            installed = target / "nm-init-project-v6"
            binding_path = installed / "source-binding.json"
            self.assertEqual(0o600, binding_path.stat().st_mode & 0o777)
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
            self.assertEqual(
                "nm-v6/skill-source-binding-v1", binding["schema_version"]
            )
            self.assertGreater(len(binding["files"]), 50)
            self.assertEqual(
                "verified", check_skill(REPOSITORY, installed)["source_binding"]
            )

            hostile = root / "hostile"
            (hostile / "tools/nm-v6").mkdir(parents=True)
            (hostile / "docs").mkdir()
            (hostile / "tools/nm-v6/nm_v6.py").write_text(
                "raise SystemExit('hostile cwd executed')\n", encoding="utf-8"
            )
            shutil.copy2(
                REPOSITORY / "docs/nm-v6-workflow-spec.md",
                hostile / "docs/nm-v6-workflow-spec.md",
            )
            wrapper = installed / "scripts/run_nm_v6.py"
            invoked = subprocess.run(
                [sys.executable, str(wrapper), "--version"],
                cwd=hostile,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, invoked.returncode, msg=invoked.stderr)
            self.assertIn("NM V6 6.0.0", invoked.stdout)
            self.assertNotIn("hostile cwd executed", invoked.stderr)

            mismatched = subprocess.run(
                [sys.executable, str(wrapper), "--version"],
                cwd=hostile,
                env={**os.environ, "NM_DOCS_DIR": str(hostile)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, mismatched.returncode)
            self.assertIn("differs from", mismatched.stderr)

            binding["files"]["tools/nm-v6/nm_v6.py"] = "0" * 64
            binding_path.write_text(json.dumps(binding), encoding="utf-8")
            binding_path.chmod(0o600)
            drifted = subprocess.run(
                [sys.executable, str(wrapper), "--version"],
                cwd=hostile,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, drifted.returncode)
            self.assertIn("changed after Skill installation", drifted.stderr)

    def test_ac043_acceptance_and_self_test_reject_credential_environment(self) -> None:
        environment = {**os.environ, "NM_V6_TEST_API_TOKEN": "fixture-only"}
        for command in ("acceptance-test", "self-test"):
            with self.subTest(command=command):
                result = subprocess.run(
                    [
                        str(TOOL_ROOT / "python311.sh"),
                        str(TOOL_ROOT / "nm_v6.py"),
                        command,
                        "--target",
                        str(REPOSITORY),
                    ],
                    cwd=REPOSITORY,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(2, result.returncode)
                self.assertIn("credential variables", result.stderr)

    def test_ac052_update_rejects_dirty_authoritative_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            initialize_project(target, source_root=REPOSITORY)
            (target / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaises(GitPolicyError):
                update_project(target, source_root=REPOSITORY, dry_run=True)


if __name__ == "__main__":
    unittest.main()
