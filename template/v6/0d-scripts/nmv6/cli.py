"""Command-line surface for the single NM V6 deterministic core."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .errors import ContractError, NmV6Error
from .repository_check import check_repository, check_skill
from .supply_chain import (
    collect_project_runtime_versions,
    detect_version_drift,
    validate_credential_free_environment,
)
from .template_sync import (
    abort_update,
    check_generated_project,
    check_installed_project,
    initialize_project,
    repository_root,
    resume_update,
    update_project,
)
from .util import (
    atomic_write,
    canonical_json,
    dump_json,
    ensure_python_311,
    load_json,
    sha256_bytes,
    sha256_file,
    utc_now,
)


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _add_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", default=".", help="Project or repository root.")


def _add_run(parser: argparse.ArgumentParser) -> None:
    _add_target(parser)
    parser.add_argument("--run-id", help="Run ID; defaults to the latest run.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NM V6 transactional workflow controller")
    parser.add_argument("--version", action="version", version=f"NM V6 {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize a clean V6 project.")
    _add_target(init)
    init.add_argument("--source-dir", default=str(repository_root()))
    init.add_argument("--project-name")
    init.add_argument("--package-name")
    init.add_argument("--dry-run", action="store_true")

    update = sub.add_parser("update", help="Safely update an existing V6 project.")
    _add_target(update)
    update.add_argument("--source-dir", default=str(repository_root()))
    update.add_argument("--remote", default="origin")
    update.add_argument("--branch")
    update.add_argument("--dry-run", action="store_true")
    mode = update.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--abort", action="store_true")

    check = sub.add_parser("check", help="Validate a generated V6 project.")
    _add_target(check)
    check.add_argument("--source-dir")
    check.add_argument("--installed", action="store_true")

    repository_check_parser = sub.add_parser("repository-check", help="Run V6 repository static checks.")
    _add_target(repository_check_parser)

    acceptance = sub.add_parser("acceptance-test", help="Run the credential-free V6 acceptance suite.")
    _add_target(acceptance)
    acceptance.add_argument("--pattern", default="test*.py")
    acceptance.add_argument("--output", help="Optional machine-readable result path.")

    skill_check = sub.add_parser("check-skill", help="Validate the thin V6 Skill.")
    _add_target(skill_check)
    skill_check.add_argument("--source-dir", default=str(repository_root()))

    install_skill = sub.add_parser("install-skill", help="Install the thin V6 Skill atomically.")
    install_skill.add_argument("--target-dir", default=str(Path.home() / ".agents/skills"))
    install_skill.add_argument("--source-dir", default=str(repository_root()))
    install_skill.add_argument("--dry-run", action="store_true")

    status = sub.add_parser("status", help="Project canonical-state projection.")
    _add_run(status)
    status.add_argument("--json", action="store_true")

    plan = sub.add_parser("plan", help="Validate the project Spec and create a planned run.")
    _add_target(plan)
    plan.add_argument("--spec", default="0a-docs/0a-spec/SPEC.md")
    plan.add_argument("--traceability", default="0a-docs/0a-spec/traceability.json")
    plan.add_argument("--run-id")
    plan.add_argument("--run-kind", choices=("normal", "hotfix"), default="normal")

    spec = sub.add_parser("spec", help="Project Spec confirmation lifecycle.")
    spec_sub = spec.add_subparsers(dest="spec_command", required=True)
    confirmation = spec_sub.add_parser("confirmation")
    confirmation_sub = confirmation.add_subparsers(dest="confirmation_command", required=True)
    confirmation_request = confirmation_sub.add_parser("request")
    _add_run(confirmation_request)
    confirmation_request.add_argument("--expires-at", required=True)
    spec_confirm = spec_sub.add_parser("confirm")
    _add_run(spec_confirm)
    spec_confirm.add_argument("--record", required=True, help="Externally signed confirmation JSON.")

    mode_parser = sub.add_parser("mode", help="Persist workflow mode changes.")
    mode_sub = mode_parser.add_subparsers(dest="mode_command", required=True)
    mode_set = mode_sub.add_parser("set")
    _add_run(mode_set)
    mode_set.add_argument("mode", choices=("staged", "auto"))
    mode_set.add_argument("--grant-id")

    authorize = sub.add_parser("authorize", help="Trusted authorization lifecycle.")
    authorize_sub = authorize.add_subparsers(dest="authorize_command", required=True)
    authorize_request = authorize_sub.add_parser("request")
    _add_run(authorize_request)
    authorize_request.add_argument("--scope", required=True, help="Exact scope JSON file.")
    authorize_request.add_argument("--expires-at", required=True)
    authorize_approve = authorize_sub.add_parser("approve")
    _add_run(authorize_approve)
    authorize_approve.add_argument("--record", required=True, help="Externally signed grant JSON.")
    authorize_revoke = authorize_sub.add_parser("revoke")
    _add_run(authorize_revoke)
    authorize_revoke.add_argument("--record", required=True, help="Externally signed revocation JSON.")

    run = sub.add_parser("run", help="Drive ready work through the common controller.")
    _add_run(run)
    run.add_argument("--detach", action="store_true")
    run.add_argument("--once", action="store_true")
    run.add_argument("--child", action="store_true", help=argparse.SUPPRESS)

    for name in ("pause", "resume", "cancel", "reconcile"):
        lifecycle = sub.add_parser(name)
        _add_run(lifecycle)
        lifecycle.add_argument("--reason")
        if name == "cancel":
            lifecycle.add_argument("--grant-id")

    adapter = sub.add_parser("adapter", help="Probe a configured provider adapter.")
    adapter_sub = adapter.add_subparsers(dest="adapter_command", required=True)
    adapter_probe = adapter_sub.add_parser("probe")
    _add_target(adapter_probe)
    adapter_probe.add_argument("provider", choices=("codex", "grok", "claude", "fake"))

    evidence = sub.add_parser("evidence", help="Inspect core evidence receipts.")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_show = evidence_sub.add_parser("show")
    _add_target(evidence_show)
    evidence_show.add_argument("evidence_id")

    audit = sub.add_parser("audit", help="Export the verified append-only audit chain.")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    audit_export = audit_sub.add_parser("export")
    _add_target(audit_export)
    audit_export.add_argument("--output", required=True)

    notify = sub.add_parser("notify-test", help="Persist a test notification in the V6 outbox.")
    _add_run(notify)
    notify.add_argument("--route", default="fixture-notification-sink")

    self_test = sub.add_parser("self-test", help="Run generated-project core self-tests.")
    _add_target(self_test)

    verify = sub.add_parser("verify", help="Run the configured full_verify action in isolation.")
    _add_target(verify)

    return parser


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _runtime_paths(target: Path) -> dict[str, Path]:
    root = target / ".nm/runtime/v6"
    return {
        "root": root,
        "db": root / "state.sqlite3",
        "evidence": root / "evidence",
        "projections": root / "projections",
        "acceptance": root / "acceptance",
    }


def _store(target: Path):
    from .store import Store

    store = Store(_runtime_paths(target)["db"])
    store.initialize()
    return store


def _latest_run_id(store: Any, explicit: str | None) -> str:
    if explicit:
        return explicit
    latest = store.latest_run()
    if latest is None:
        raise NmV6Error("no V6 run exists; create a plan first")
    return latest["run_id"] if isinstance(latest, dict) else latest.run_id


def _acceptance_source_change(target: Path) -> dict[str, Any]:
    """Select a new clean C scope or reuse the valid committed manifest's B/C scope."""

    from .traceability import (
        source_change_record,
        validate_acceptance_manifest,
        validate_source_change_record,
    )

    relative = "tools/nm-v6/acceptance-manifest.json"
    manifest_path = target / relative
    environment = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}
    listing = subprocess.run(
        ["git", "ls-tree", "HEAD", "--", relative],
        cwd=target,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if listing.returncode != 0:
        detail = listing.stderr.strip() or listing.stdout.strip() or "unknown Git failure"
        raise ContractError(f"cannot inspect committed acceptance manifest: {detail}")
    committed = bool(listing.stdout.strip())
    exists_in_worktree = os.path.lexists(manifest_path)
    if not committed and not exists_in_worktree:
        return source_change_record(target)
    if not committed:
        raise ContractError(
            "existing acceptance manifest is not committed; refusing to create a new source scope"
        )
    fields = listing.stdout.split("\t", 1)[0].split()
    if len(fields) != 3 or fields[0] != "100644" or fields[1] != "blob":
        raise ContractError("committed acceptance manifest must be one Git mode 100644 blob")
    for arguments in (
        ("diff", "--cached", "--quiet", "HEAD", "--", relative),
        ("diff", "--quiet", "--", relative),
    ):
        unchanged = subprocess.run(
            ["git", *arguments],
            cwd=target,
            env=environment,
            check=False,
        )
        if unchanged.returncode != 0:
            raise ContractError(
                "committed acceptance manifest differs from the index or working tree; "
                "refusing fallback"
            )
    manifest = validate_acceptance_manifest(manifest_path, repository=target)
    try:
        source = manifest["evidence"]["automated"]["result"]["source_change"]
    except (KeyError, TypeError) as exc:
        raise ContractError("acceptance manifest lacks its embedded B/C source record") from exc
    if not isinstance(source, dict):
        raise ContractError("acceptance manifest embedded B/C source record is invalid")
    validate_source_change_record(source, repository=target)
    return source


def _repository_acceptance(
    target: Path,
    pattern: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    from .traceability import (
        discover_acceptance_suite,
        selector_for_test,
        validate_source_change_record,
    )

    validate_credential_free_environment(os.environ)

    class AcceptanceResult(unittest.TextTestResult):
        _priority = {
            "pass": 0,
            "skip": 1,
            "expected_failure": 2,
            "unexpected_success": 3,
            "fail": 4,
            "error": 5,
        }

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.outcomes: dict[str, str] = {}

        def _record(self, test: unittest.TestCase, status: str) -> None:
            parent = getattr(test, "test_case", test)
            selector = selector_for_test(parent, repository=target)
            current = self.outcomes.get(selector)
            if current is None or self._priority[status] > self._priority[current]:
                self.outcomes[selector] = status

        def addSuccess(self, test: unittest.TestCase) -> None:  # noqa: N802
            super().addSuccess(test)
            self._record(test, "pass")

        def addFailure(self, test: unittest.TestCase, err: Any) -> None:  # noqa: N802
            super().addFailure(test, err)
            self._record(test, "fail")

        def addError(self, test: unittest.TestCase, err: Any) -> None:  # noqa: N802
            super().addError(test, err)
            self._record(test, "error")

        def addSkip(self, test: unittest.TestCase, reason: str) -> None:  # noqa: N802
            super().addSkip(test, reason)
            self._record(test, "skip")

        def addExpectedFailure(self, test: unittest.TestCase, err: Any) -> None:  # noqa: N802
            super().addExpectedFailure(test, err)
            self._record(test, "expected_failure")

        def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:  # noqa: N802
            super().addUnexpectedSuccess(test)
            self._record(test, "unexpected_success")

        def addSubTest(self, test: unittest.TestCase, subtest: Any, err: Any) -> None:  # noqa: N802
            super().addSubTest(test, subtest, err)
            if err is not None:
                status = "fail" if issubclass(err[0], test.failureException) else "error"
                self._record(test, status)

    suite, inventory = discover_acceptance_suite(target, pattern=pattern)
    source_change = _acceptance_source_change(target)
    started_at = utc_now()
    stream = sys.stderr
    result = unittest.TextTestRunner(
        stream=stream,
        verbosity=2,
        resultclass=AcceptanceResult,
    ).run(suite)
    outcomes = {
        selector: result.outcomes.get(selector, "error")
        for selector in inventory["selectors"]
    }
    statuses = {"pass", "fail", "error", "skip", "expected_failure", "unexpected_success"}
    counts = {status: sum(value == status for value in outcomes.values()) for status in sorted(statuses)}
    validate_source_change_record(source_change, repository=target)
    command = {
        "argv": ["nm-v6", "acceptance-test", "--target", ".", "--pattern", pattern],
        "target": ".",
        "pattern": pattern,
    }
    record = {
        "schema_version": "nm-v6/acceptance-result-v2",
        "spec_hash": "62196ab27c2be08ea1c716081903a009185f1d518ba7a53ed9b3d8485236cb7f",
        "started_at": started_at,
        "finished_at": utc_now(),
        "command": command,
        "command_digest": sha256_bytes(canonical_json(command)),
        "source_change": source_change,
        "test_inventory": inventory,
        "test_outcomes": outcomes,
        "summary": {"tests_run": len(outcomes), **counts},
        "result": "passed" if set(outcomes.values()) == {"pass"} else "failed",
    }
    output = _path(output_path) if output_path else None
    result_bytes = dump_json(record)
    result_file_sha256 = sha256_bytes(result_bytes)
    if output is not None:
        digest_binding = {
            "schema_version": "nm-v6/acceptance-result-digest-v1",
            "result_file_sha256": result_file_sha256,
            "spec_hash": record["spec_hash"],
            "source_change_digest": source_change["digest"],
            "test_inventory_digest": inventory["digest"],
            "command_digest": record["command_digest"],
        }
        atomic_write(output, result_bytes)
        atomic_write(Path(f"{output}.sha256.json"), dump_json(digest_binding))
    if record["result"] != "passed":
        suffix = f"; details recorded at {output}" if output is not None else ""
        raise NmV6Error(f"V6 acceptance suite failed{suffix}")
    return {
        "schema_version": "nm-v6/acceptance-run-summary-v1",
        "spec_hash": record["spec_hash"],
        "result": record["result"],
        "summary": record["summary"],
        "test_outcomes": outcomes,
        "source_change_digest": source_change["digest"],
        "test_inventory_digest": inventory["digest"],
        "command_digest": record["command_digest"],
        "result_file": str(output) if output is not None else None,
        "result_file_sha256": result_file_sha256 if output is not None else None,
    }


def _skill_source_binding(source_root: Path) -> dict[str, Any]:
    root = source_root.expanduser().resolve()
    required = (
        root / "docs/nm-v6-workflow-spec.md",
        root / "template/v6/manifest.json",
        root / "tools/nm-v6/nm_v6.py",
    )
    if any(not path.is_file() or path.is_symlink() for path in required):
        raise ContractError("Skill source checkout lacks a regular V6 Spec, manifest, or CLI")
    try:
        git = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError(f"cannot verify the Skill source Git root: {exc}") from exc
    if git.returncode != 0 or Path(git.stdout.strip()).resolve() != root:
        raise ContractError("Skill source must be the exact trusted Git checkout root")
    candidates = set(required)
    for directory in (root / "tools/nm-v6", root / "skills/nm-init-project-v6"):
        for path in directory.rglob("*"):
            if (
                path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
                and path.name != "source-binding.json"
            ):
                candidates.add(path)
    files = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(candidates)
    }
    return {
        "schema_version": "nm-v6/skill-source-binding-v1",
        "source_root": str(root),
        "files": files,
    }


def _install_skill(source_root: Path, target_root: Path, *, dry_run: bool) -> dict[str, Any]:
    source = source_root / "skills/nm-init-project-v6"
    check_skill(source_root, source)
    source_binding = _skill_source_binding(source_root)
    source_binding_bytes = dump_json(source_binding)
    destination = target_root.expanduser().resolve() / source.name
    record = {
        "schema_version": "nm-v6/skill-install-v1",
        "source": str(source),
        "destination": str(destination),
        "files": sorted(path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()),
        "source_binding_sha256": sha256_bytes(source_binding_bytes),
        "dry_run": dry_run,
    }
    if dry_run:
        return record
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".nm-init-project-v6-", dir=destination.parent))
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, stage / destination.name)
        atomic_write(
            stage / destination.name / "source-binding.json",
            source_binding_bytes,
            mode=0o600,
        )
        check_skill(source_root, stage / destination.name)
        if destination.exists():
            os.replace(destination, backup)
        os.replace(stage / destination.name, destination)
        shutil.rmtree(backup, ignore_errors=True)
    except BaseException:
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return record


def _status(args: argparse.Namespace) -> dict[str, Any]:
    target = _path(args.target)
    paths = _runtime_paths(target)
    if not paths["db"].is_file():
        return {
            "schema_version": "nm-v6/status-v1",
            "project": target.name,
            "run": None,
            "state": "UNINITIALIZED",
            "revision": 0,
            "last_event_sequence": 0,
            "attention": None,
        }
    store = _store(target)
    try:
        run_id = _latest_run_id(store, args.run_id)
        run = store.get_run(run_id)
        if run is None:
            raise NmV6Error(f"unknown run: {run_id}")
        events = store.list_events(run_id=run_id)
        return {
            "schema_version": "nm-v6/status-v1",
            "project": target.name,
            "run": dict(run),
            "state": run["state"],
            "revision": run["revision"],
            "last_event_sequence": events[-1]["sequence"] if events else 0,
            "attention": run.get("attention_reason") if isinstance(run, dict) else None,
        }
    finally:
        store.close()


def _plan(args: argparse.Namespace) -> dict[str, Any]:
    from .models import TransitionProposal
    from .reducer import Reducer
    from .specs import canonical_spec_hash, parse_spec, validate_spec
    from .util import canonical_json

    target = _path(args.target)
    spec_path = target / args.spec
    config = load_json(target / "project.json")
    from .contracts import validate_project_config, validate_version_record

    config = validate_project_config(config)
    version_baseline = collect_project_runtime_versions(target, config)
    traceability = load_json(target / args.traceability)
    parsed = validate_spec(spec_path, traceability=traceability)
    spec_hash = canonical_spec_hash(parsed)
    config_hash = sha256_bytes(canonical_json(config))
    run_id = args.run_id or f"run-{uuid.uuid4().hex[:16]}"
    store = _store(target)
    try:
        reducer = Reducer(store)
        run = store.get_run(run_id)
        if run is None:
            reducer.create_run(
                run_id=run_id,
                spec_hash=spec_hash,
                config_hash=config_hash,
                mode="staged",
                run_kind=args.run_kind,
                actor="nm-v6-cli",
                idempotency_key=f"run-create:{run_id}:{spec_hash}:{config_hash}",
                payload={
                    "spec_id": parsed.metadata["spec_id"],
                    "spec_version": parsed.metadata["version"],
                    "traceability": traceability,
                    "version_baseline": version_baseline,
                },
            )
            run = store.get_run(run_id)
        if run is None:
            raise NmV6Error("run registration did not produce canonical state")
        if run["spec_hash"] != spec_hash or run["config_hash"] != config_hash:
            raise ContractError("existing run is bound to another Spec or configuration")
        persisted_payload = run.get("payload", {})
        persisted_baseline = (
            persisted_payload.get("version_baseline")
            if isinstance(persisted_payload, dict)
            else None
        )
        try:
            persisted_baseline = validate_version_record(persisted_baseline)
        except Exception as exc:
            raise ContractError(
                "existing run has no valid runtime version baseline"
            ) from exc
        drift = detect_version_drift(persisted_baseline, version_baseline)
        if drift:
            raise ContractError(
                "runtime version baseline drifted after planning: "
                + ", ".join(sorted(drift))
            )
        if run["state"] == "DISCOVERING":
            reducer.transition(
                TransitionProposal(
                    run_id=run_id,
                    expected_revision=int(run["revision"]),
                    event="DRAFT_SPEC",
                    actor="nm-v6-cli",
                    idempotency_key=f"spec-draft:{run_id}:{spec_hash}",
                    payload={"discovery_complete": True},
                )
            )
            run = store.get_run(run_id)
        if run is not None and run["state"] == "SPEC_DRAFT":
            reducer.transition(
                TransitionProposal(
                    run_id=run_id,
                    expected_revision=int(run["revision"]),
                    event="SUBMIT_SPEC_REVIEW",
                    actor="nm-v6-cli",
                    idempotency_key=f"spec-review:{run_id}:{spec_hash}",
                )
            )
        result = store.get_run(run_id)
        if result is None:
            raise NmV6Error("planned run disappeared from canonical state")
        return result
    finally:
        store.close()


def _adapter_probe(args: argparse.Namespace) -> dict[str, Any]:
    from .adapters import create_adapter

    adapter = create_adapter(args.provider)
    return adapter.probe()


def _evidence_show(args: argparse.Namespace) -> dict[str, Any]:
    store = _store(_path(args.target))
    try:
        value = store.get_evidence(args.evidence_id)
        if value is None:
            raise NmV6Error(f"unknown evidence: {args.evidence_id}")
        return dict(value)
    finally:
        store.close()


def _audit_export(args: argparse.Namespace) -> dict[str, Any]:
    from .audit import export_audit

    store = _store(_path(args.target))
    try:
        return export_audit(store.list_audit(), _path(args.output))
    finally:
        store.close()


def _self_test(target: Path) -> dict[str, Any]:
    from .runtime import run_generated_self_test

    validate_credential_free_environment(os.environ)
    return run_generated_self_test(target)


def _verify(target: Path) -> dict[str, Any]:
    from .actions import ActionExecutor, validate_action_registry
    from .workspace import WorkspaceManager, temporary_workspace_root

    project = load_json(target / "project.json")
    definitions = validate_action_registry(project["action_definitions"])
    action_id = project["actions"]["full_verify"]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=target, text=True, capture_output=True, check=True
    ).stdout.strip()
    root = temporary_workspace_root()
    manager = WorkspaceManager(target, root)
    workspace = manager.create("verify", commit=commit)
    try:
        result = ActionExecutor(isolation_backend=manager.isolation_backend).execute(
            definitions[action_id],
            workspace=workspace,
            operation_id=None,
        )
        return {"schema_version": "nm-v6/verify-result-v1", "result": result.status, "action": result.as_dict()}
    finally:
        manager.dispose(workspace)
        shutil.rmtree(root, ignore_errors=True)


def _not_yet_dispatched(args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch lifecycle commands through the configured project runtime."""

    from .reducer import Reducer
    from .runtime import compose_runtime

    target = _path(args.target)
    store = _store(target)
    try:
        run_id = _latest_run_id(store, getattr(args, "run_id", None))
        reducer = Reducer(store)
        runtime = compose_runtime(target, store, reducer, run_id)
        return dict(runtime.handle(args.command, vars(args)))
    finally:
        store.close()


def dispatch(args: argparse.Namespace) -> Any:
    command = args.command
    if command == "init":
        return initialize_project(
            _path(args.target),
            source_root=_path(args.source_dir),
            project_name=args.project_name,
            package_name=args.package_name,
            dry_run=args.dry_run,
        )
    if command == "update":
        target = _path(args.target)
        source = _path(args.source_dir)
        if args.abort:
            abort_update(target)
            return {"schema_version": "nm-v6/update-recovery-v1", "result": "aborted"}
        if args.resume:
            return resume_update(target, source)
        return update_project(
            target,
            source_root=source,
            remote=args.remote,
            branch=args.branch,
            dry_run=args.dry_run,
        )
    if command == "check":
        if args.installed or args.source_dir is None:
            return check_installed_project(_path(args.target))
        return check_generated_project(_path(args.target), source_root=_path(args.source_dir))
    if command == "repository-check":
        return check_repository(_path(args.target))
    if command == "acceptance-test":
        return _repository_acceptance(_path(args.target), args.pattern, args.output)
    if command == "check-skill":
        return check_skill(_path(args.source_dir), _path(args.target))
    if command == "install-skill":
        return _install_skill(_path(args.source_dir), _path(args.target_dir), dry_run=args.dry_run)
    if command == "status":
        return _status(args)
    if command == "plan":
        return _plan(args)
    if command == "adapter" and args.adapter_command == "probe":
        return _adapter_probe(args)
    if command == "evidence" and args.evidence_command == "show":
        return _evidence_show(args)
    if command == "audit" and args.audit_command == "export":
        return _audit_export(args)
    if command == "self-test":
        return _self_test(_path(args.target))
    if command == "verify":
        return _verify(_path(args.target))
    return _not_yet_dispatched(args)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        ensure_python_311()
        args = build_parser().parse_args(argv)
        result = dispatch(args)
        if result is not None:
            _print(result)
        return 0
    except (NmV6Error, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
