"""Manifest-backed, transactional NM V6 template initialization and update."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import ContractError, GitPolicyError, NmV6Error
from .supply_chain import (
    validate_dependency_constraints,
    validate_install_plan_hashes,
    validate_schema_catalog,
    validate_template_manifest,
)
from .util import (
    atomic_write,
    canonical_json,
    dump_json,
    ensure_relative_path,
    load_json,
    run_command,
    sha256_bytes,
    utc_now,
)


MANIFEST_RELATIVE = Path("template/v6/manifest.json")
STATE_FILE = ".nm-template-state.json"
UPDATE_ROOT_RELATIVE = Path(".nm/update/v6")
JOURNAL_NAME = "journal.json"
ALLOWED_BRANCH = re.compile(r"^(feature|fix|docs|refactor|chore|task)/[A-Za-z0-9._/-]+$")
PROTECTED_BRANCHES = {"main", "master", "dev"}
OPERATION_ID = re.compile(r"^sync-[0-9a-f]{32}$")
REMOTE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass
class RenderedFile:
    target: str
    source: str
    policy: str
    mode: int
    rendered_sha256: str
    previous_sha256: str | None
    previous_mode: int | None
    content: bytes = field(repr=False)


@dataclass
class SyncPlan:
    operation_id: str
    mode: str
    target: Path
    source_root: Path
    branch: str | None
    remote: str | None
    expected_dev_sha: str | None
    manifest_sha256: str
    files: list[RenderedFile]
    created_directories: list[str]
    conflicts: list[str]
    created_at: str

    def public_record(self) -> dict[str, Any]:
        return {
            "schema_version": "nm-v6/sync-plan-v1",
            "operation_id": self.operation_id,
            "mode": self.mode,
            "target": str(self.target),
            "source_root": str(self.source_root),
            "branch": self.branch,
            "remote": self.remote,
            "expected_dev_sha": self.expected_dev_sha,
            "manifest_sha256": self.manifest_sha256,
            "created_at": self.created_at,
            "created_directories": self.created_directories,
            "conflicts": self.conflicts,
            "files": [
                {
                    "target": item.target,
                    "source": item.source,
                    "policy": item.policy,
                    "mode": oct(item.mode),
                    "rendered_sha256": item.rendered_sha256,
                    "previous_sha256": item.previous_sha256,
                    "previous_mode": oct(item.previous_mode) if item.previous_mode is not None else None,
                }
                for item in self.files
            ],
        }


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_manifest(source_root: Path) -> dict[str, Any]:
    manifest_path = _confined_path(source_root, MANIFEST_RELATIVE, subject="V6 manifest")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ContractError("V6 manifest must be a JSON object")
    if manifest.get("schemaVersion") != 2:
        raise ContractError("V6 manifest schemaVersion must be 2")
    for key in ("directories", "templates"):
        if not isinstance(manifest.get(key), list):
            raise ContractError(f"V6 manifest {key} must be an array")
    return manifest


def _project_values(target: Path, project_name: str | None, package_name: str | None) -> dict[str, str]:
    name = project_name or target.name
    package = package_name or re.sub(r"[^a-z0-9._~-]+", "-", name.lower()).strip("-")
    return {"PROJECT_NAME": name, "PACKAGE_NAME": package or "nm-project"}


def _render(data: bytes, values: dict[str, str]) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("template sources must be UTF-8") from exc
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    unresolved = sorted(set(re.findall(r"\{\{[A-Z][A-Z0-9_]*\}\}", text)))
    if unresolved:
        raise ContractError(f"unresolved template variables: {', '.join(unresolved)}")
    return text.encode("utf-8")


def _load_state(target: Path) -> dict[str, Any]:
    path = target / STATE_FILE
    if not path.exists():
        return {}
    value = load_json(path)
    if not isinstance(value, dict):
        raise ContractError(f"{STATE_FILE} must be a JSON object")
    return value


def _git_root(target: Path) -> Path | None:
    result = run_command(["git", "rev-parse", "--show-toplevel"], cwd=target, check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _require_clean_git_root(target: Path) -> None:
    root = _git_root(target)
    if root != target.resolve():
        raise GitPolicyError("target must be the root of a Git repository")
    status = run_command(["git", "status", "--porcelain=v1"], cwd=target).stdout
    if status.strip():
        raise GitPolicyError("authoritative working tree must be clean")


def _fetch_exact_dev(target: Path, remote: str) -> str:
    if not REMOTE_NAME.fullmatch(remote):
        raise GitPolicyError(f"invalid update remote name: {remote!r}")
    run_command(["git", "fetch", "--prune", remote, "dev"], cwd=target)
    expected = run_command(
        ["git", "rev-parse", "--verify", f"refs/remotes/{remote}/dev"],
        cwd=target,
    ).stdout.strip()
    local = run_command(["git", "show-ref", "--verify", "--hash", "refs/heads/dev"], cwd=target, check=False)
    if local.returncode == 0 and local.stdout.strip() != expected:
        raise GitPolicyError("local dev is stale or divergent from the fetched remote dev")
    return expected


def _confined_path(root: Path, relative: str | Path, *, subject: str) -> Path:
    """Resolve a project-owned path without permitting symlink or traversal escapes."""

    root = root.resolve()
    candidate = root / relative
    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"{subject} escapes its declared root") from exc
    current = root
    for part in lexical_relative.parts:
        if part in {"", ".", ".."}:
            raise ContractError(f"{subject} contains an unsafe path component")
        current = current / part
        if current.is_symlink():
            raise ContractError(f"{subject} contains a symlink: {current}")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ContractError(f"{subject} resolves outside its declared root") from exc
    return candidate


def build_sync_plan(
    *,
    target: Path,
    source_root: Path,
    mode: str,
    project_name: str | None = None,
    package_name: str | None = None,
    branch: str | None = None,
    remote: str | None = None,
    expected_dev_sha: str | None = None,
) -> SyncPlan:
    if mode not in {"init", "update", "check"}:
        raise ContractError(f"unsupported sync mode: {mode}")
    install_plan = validate_template_manifest(
        _confined_path(source_root, MANIFEST_RELATIVE, subject="V6 manifest"),
        repository_root=source_root,
    )
    validate_install_plan_hashes(install_plan, source_root / "template/v6")
    manifest = load_manifest(source_root)
    manifest_path = _confined_path(source_root, MANIFEST_RELATIVE, subject="V6 manifest")
    manifest_sha256 = sha256_bytes(manifest_path.read_bytes())
    if mode == "update" and (remote is None or not REMOTE_NAME.fullmatch(remote)):
        raise GitPolicyError("update plan requires a safe recorded remote name")
    values = _project_values(target, project_name, package_name)
    state = _load_state(target) if target.exists() else {}
    prior_files = state.get("files", {}) if isinstance(state.get("files"), dict) else {}
    rendered: list[RenderedFile] = []
    conflicts: list[str] = []
    seen_targets: set[str] = set()
    for item in manifest["templates"]:
        if not isinstance(item, dict):
            raise ContractError("manifest template entries must be objects")
        target_rel = ensure_relative_path(item.get("target"), field="manifest target")
        source_rel = ensure_relative_path(item.get("source"), field="manifest source")
        if target_rel in seen_targets:
            raise ContractError(f"duplicate manifest target: {target_rel}")
        seen_targets.add(target_rel)
        policy = item.get("policy")
        if policy not in {"managed", "create-only", "json-merge"}:
            raise ContractError(f"unsupported policy for {target_rel}: {policy}")
        source_path = _confined_path(source_root, source_rel, subject="manifest source")
        if not source_path.is_file():
            raise ContractError(f"missing manifest source: {source_rel}")
        content = _render(source_path.read_bytes(), values)
        destination = _confined_path(target, target_rel, subject="manifest target")
        if destination.exists() and not destination.is_file():
            raise ContractError(f"manifest target is not a regular file: {target_rel}")
        previous = sha256_bytes(destination.read_bytes()) if destination.is_file() else None
        previous_mode = stat.S_IMODE(destination.stat().st_mode) if destination.is_file() else None
        prior = prior_files.get(target_rel, {}) if isinstance(prior_files.get(target_rel), dict) else {}
        prior_hash = prior.get("sha256")
        if mode == "update" and destination.exists() and policy == "managed":
            if prior_hash is None or previous != prior_hash:
                conflicts.append(target_rel)
        if mode == "update" and destination.exists() and policy == "create-only":
            content = destination.read_bytes()
        if mode == "update" and destination.exists() and policy == "json-merge":
            content = _merge_package(destination.read_bytes(), content, item.get("mergeRoots", []))
        file_mode = int(item.get("mode", "0644"), 8) if isinstance(item.get("mode", "0644"), str) else 0o644
        rendered.append(
            RenderedFile(
                target=target_rel,
                source=source_rel,
                policy=policy,
                mode=file_mode,
                rendered_sha256=sha256_bytes(content),
                previous_sha256=previous,
                previous_mode=previous_mode,
                content=content,
            )
        )
    directories = [ensure_relative_path(value, field="manifest directory") for value in manifest["directories"]]
    return SyncPlan(
        operation_id=f"sync-{uuid.uuid4().hex}",
        mode=mode,
        target=target.resolve(),
        source_root=source_root.resolve(),
        branch=branch,
        remote=remote,
        expected_dev_sha=expected_dev_sha,
        manifest_sha256=manifest_sha256,
        files=rendered,
        created_directories=directories,
        conflicts=conflicts,
        created_at=utc_now(),
    )


def _merge_package(existing_bytes: bytes, desired_bytes: bytes, roots: list[str]) -> bytes:
    try:
        existing = json.loads(existing_bytes)
        desired = json.loads(desired_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("json-merge target and template must be valid JSON") from exc
    if not isinstance(existing, dict) or not isinstance(desired, dict):
        raise ContractError("json-merge target and template must be objects")
    for root in roots:
        incoming = desired.get(root)
        if not isinstance(incoming, dict):
            raise ContractError(f"json-merge root must be an object: {root}")
        current = existing.setdefault(root, {})
        if not isinstance(current, dict):
            raise ContractError(f"existing json-merge root is not an object: {root}")
        current.update(incoming)
    return dump_json(existing)


def _validate_staged_plan(plan: SyncPlan) -> None:
    if plan.conflicts:
        raise NmV6Error(
            "managed files contain project changes; preserve or reconcile before update: "
            + ", ".join(plan.conflicts)
        )
    targets = {item.target for item in plan.files}
    required = {
        "AGENTS.md",
        "AGENTS.zh-CN.md",
        "project.json",
        "package.json",
        "0d-scripts/nm-v6.py",
    }
    missing = sorted(required - targets)
    if missing:
        raise ContractError(f"manifest omits required generated files: {', '.join(missing)}")
    for item in plan.files:
        if item.target == "project.json":
            from .contracts import validate_project_config

            validate_project_config(json.loads(item.content))


def _state_bytes(plan: SyncPlan, *, manifest: dict[str, Any]) -> bytes:
    record = {
        "schema_version": "nm-v6/template-state-v1",
        "template": "v6",
        "template_version": manifest.get("templateVersion"),
        "source": str(plan.source_root),
        "expected_dev_sha": plan.expected_dev_sha,
        "updated_at": plan.created_at,
        "files": {
            item.target: {"sha256": item.rendered_sha256, "policy": item.policy, "source": item.source}
            for item in plan.files
        },
    }
    return dump_json(record)


def _write_state(plan: SyncPlan, *, manifest: dict[str, Any]) -> None:
    atomic_write(plan.target / STATE_FILE, _state_bytes(plan, manifest=manifest), mode=0o644)


def _apply_transient_plan(plan: SyncPlan) -> dict[str, Any]:
    """Apply an initialization plan; interrupted updates use the durable path below."""

    _validate_staged_plan(plan)
    manifest = load_manifest(plan.source_root)
    stage_root = Path(tempfile.mkdtemp(prefix="nm-v6-init-"))
    try:
        rendered_root = stage_root / "rendered"
        for item in plan.files:
            output = rendered_root / item.target
            output.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(output, item.content, mode=item.mode)
        for directory in plan.created_directories:
            _confined_path(plan.target, directory, subject="manifest directory").mkdir(
                parents=True, exist_ok=True
            )
        for item in plan.files:
            destination = _confined_path(plan.target, item.target, subject="manifest target")
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(destination, (rendered_root / item.target).read_bytes(), mode=item.mode)
        _write_state(plan, manifest=manifest)
        return plan.public_record()
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def _operation_root(target: Path, operation_id: str) -> Path:
    if not OPERATION_ID.fullmatch(operation_id):
        raise ContractError(f"invalid update operation ID: {operation_id!r}")
    return _confined_path(
        target,
        UPDATE_ROOT_RELATIVE / operation_id,
        subject="update operation root",
    )


def _assert_no_pending_update(target: Path) -> None:
    root = _confined_path(target, UPDATE_ROOT_RELATIVE, subject="update root")
    if root.exists():
        if not root.is_dir():
            raise ContractError("V6 update root is not a directory")
        if any(root.iterdir()):
            raise NmV6Error("a V6 update operation already exists; resume or abort it first")


def _find_update_journal(target: Path) -> tuple[Path, Path]:
    root = _confined_path(target, UPDATE_ROOT_RELATIVE, subject="update root")
    if not root.is_dir():
        raise NmV6Error("no interrupted V6 update to recover")
    operations = list(root.iterdir())
    if len(operations) != 1:
        raise ContractError("V6 update root must contain exactly one recoverable operation")
    operation_root = operations[0]
    if operation_root.is_symlink() or not operation_root.is_dir():
        raise ContractError("V6 update operation root is not a confined directory")
    expected = _operation_root(target, operation_root.name)
    if expected != operation_root:
        raise ContractError("V6 update operation path does not match its operation ID")
    journal_path = _confined_path(
        operation_root,
        JOURNAL_NAME,
        subject="update journal",
    )
    if not journal_path.is_file() or journal_path.is_symlink():
        raise ContractError("V6 update operation has no regular journal")
    if stat.S_IMODE(journal_path.stat().st_mode) != 0o600:
        raise ContractError("V6 update journal must use mode 0600")
    return operation_root, journal_path


def _journal_digest(journal: dict[str, Any]) -> str:
    value = {key: item for key, item in journal.items() if key != "journal_digest"}
    return sha256_bytes(canonical_json(value))


def _write_update_journal(path: Path, journal: dict[str, Any]) -> None:
    journal["updated_at"] = utc_now()
    journal["journal_digest"] = _journal_digest(journal)
    atomic_write(path, dump_json(journal), mode=0o600)


def _require_exact_keys(value: dict[str, Any], expected: set[str], *, subject: str) -> None:
    if set(value) != expected:
        raise ContractError(
            f"{subject} keys differ; missing={sorted(expected - set(value))}, "
            f"unknown={sorted(set(value) - expected)}"
        )


def _parse_mode(value: Any, *, field_name: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0o[0-7]{3,4}", value):
        raise ContractError(f"{field_name} must be an octal mode")
    mode = int(value, 8)
    if mode < 0o400 or mode > 0o777:
        raise ContractError(f"{field_name} is outside the allowed file-mode range")
    return mode


def _parse_update_plan(
    record: Any,
    *,
    target: Path,
    operation_id: str,
) -> SyncPlan:
    if not isinstance(record, dict):
        raise ContractError("update journal plan must be an object")
    _require_exact_keys(
        record,
        {
            "schema_version",
            "operation_id",
            "mode",
            "target",
            "source_root",
            "branch",
            "remote",
            "expected_dev_sha",
            "manifest_sha256",
            "created_at",
            "created_directories",
            "conflicts",
            "files",
        },
        subject="update journal plan",
    )
    target = target.resolve()
    if (
        record.get("schema_version") != "nm-v6/sync-plan-v1"
        or record.get("operation_id") != operation_id
        or record.get("mode") != "update"
        or record.get("target") != str(target)
    ):
        raise ContractError("update journal plan identity does not match this project operation")
    source_value = record.get("source_root")
    if not isinstance(source_value, str) or not Path(source_value).is_absolute():
        raise ContractError("update journal source_root must be absolute")
    source_root = Path(source_value).resolve()
    if str(source_root) != source_value:
        raise ContractError("update journal source_root is not canonical")
    branch = record.get("branch")
    remote = record.get("remote")
    expected_dev_sha = record.get("expected_dev_sha")
    if not isinstance(branch, str) or not ALLOWED_BRANCH.fullmatch(branch):
        raise ContractError("update journal contains an invalid recorded branch")
    if not isinstance(remote, str) or not REMOTE_NAME.fullmatch(remote):
        raise ContractError("update journal contains an invalid recorded remote")
    if not isinstance(expected_dev_sha, str) or not GIT_SHA.fullmatch(expected_dev_sha):
        raise ContractError("update journal contains an invalid expected dev SHA")
    manifest_sha256 = record.get("manifest_sha256")
    if not isinstance(manifest_sha256, str) or not SHA256.fullmatch(manifest_sha256):
        raise ContractError("update journal contains an invalid manifest digest")
    created_at = record.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ContractError("update journal contains an invalid creation time")
    if record.get("conflicts") != []:
        raise ContractError("a recoverable update plan cannot contain conflicts")
    directories = record.get("created_directories")
    if not isinstance(directories, list) or len(directories) != len(set(directories)):
        raise ContractError("update journal directories must be a unique array")
    for directory in directories:
        ensure_relative_path(directory, field="update journal directory")
        _confined_path(target, directory, subject="update journal directory")
    file_records = record.get("files")
    if not isinstance(file_records, list) or not file_records:
        raise ContractError("update journal plan must contain files")
    files: list[RenderedFile] = []
    targets: set[str] = set()
    for item in file_records:
        if not isinstance(item, dict):
            raise ContractError("update journal file entries must be objects")
        _require_exact_keys(
            item,
            {
                "target",
                "source",
                "policy",
                "mode",
                "rendered_sha256",
                "previous_sha256",
                "previous_mode",
            },
            subject="update journal file",
        )
        target_rel = ensure_relative_path(item.get("target"), field="update journal target")
        source_rel = ensure_relative_path(item.get("source"), field="update journal source")
        if target_rel in targets:
            raise ContractError(f"duplicate update journal target: {target_rel}")
        targets.add(target_rel)
        if target_rel == STATE_FILE or target_rel.startswith(UPDATE_ROOT_RELATIVE.as_posix() + "/"):
            raise ContractError(f"update journal target overlaps control state: {target_rel}")
        _confined_path(target, target_rel, subject="update journal target")
        _confined_path(source_root, source_rel, subject="update journal source")
        policy = item.get("policy")
        if policy not in {"managed", "create-only", "json-merge"}:
            raise ContractError(f"invalid update journal policy: {policy!r}")
        rendered_sha = item.get("rendered_sha256")
        previous_sha = item.get("previous_sha256")
        if not isinstance(rendered_sha, str) or not SHA256.fullmatch(rendered_sha):
            raise ContractError("update journal rendered digest is invalid")
        if previous_sha is not None and (
            not isinstance(previous_sha, str) or not SHA256.fullmatch(previous_sha)
        ):
            raise ContractError("update journal previous digest is invalid")
        mode = _parse_mode(item.get("mode"), field_name="update journal mode")
        previous_mode_value = item.get("previous_mode")
        previous_mode = (
            None
            if previous_mode_value is None
            else _parse_mode(previous_mode_value, field_name="update journal previous_mode")
        )
        if (previous_sha is None) != (previous_mode is None):
            raise ContractError("update journal previous digest/mode must be present together")
        files.append(
            RenderedFile(
                target=target_rel,
                source=source_rel,
                policy=policy,
                mode=mode,
                rendered_sha256=rendered_sha,
                previous_sha256=previous_sha,
                previous_mode=previous_mode,
                content=b"",
            )
        )
    return SyncPlan(
        operation_id=operation_id,
        mode="update",
        target=target,
        source_root=source_root,
        branch=branch,
        remote=remote,
        expected_dev_sha=expected_dev_sha,
        manifest_sha256=manifest_sha256,
        files=files,
        created_directories=list(directories),
        conflicts=[],
        created_at=created_at,
    )


def _load_update_operation(target: Path) -> tuple[Path, Path, dict[str, Any], SyncPlan]:
    target = target.resolve()
    operation_root, journal_path = _find_update_journal(target)
    journal = load_json(journal_path)
    if not isinstance(journal, dict):
        raise ContractError("update journal must be a JSON object")
    _require_exact_keys(
        journal,
        {
            "schema_version",
            "operation_id",
            "plan",
            "plan_digest",
            "state",
            "next_index",
            "status",
            "updated_at",
            "journal_digest",
        },
        subject="update journal",
    )
    if journal.get("schema_version") != "nm-v6/update-journal-v2":
        raise ContractError("unsupported update journal schema")
    if not isinstance(journal.get("updated_at"), str) or not journal["updated_at"]:
        raise ContractError("update journal has an invalid update time")
    operation_id = journal.get("operation_id")
    if operation_id != operation_root.name or not isinstance(operation_id, str):
        raise ContractError("update journal operation ID does not match its directory")
    digest = journal.get("journal_digest")
    if not isinstance(digest, str) or digest != _journal_digest(journal):
        raise ContractError("update journal digest mismatch")
    state = journal.get("state")
    if not isinstance(state, dict):
        raise ContractError("update journal state metadata must be an object")
    _require_exact_keys(
        state,
        {"previous_sha256", "previous_mode", "rendered_sha256", "mode"},
        subject="update journal state metadata",
    )
    previous_state_sha = state.get("previous_sha256")
    rendered_state_sha = state.get("rendered_sha256")
    if previous_state_sha is not None and (
        not isinstance(previous_state_sha, str) or not SHA256.fullmatch(previous_state_sha)
    ):
        raise ContractError("update journal previous state digest is invalid")
    if not isinstance(rendered_state_sha, str) or not SHA256.fullmatch(rendered_state_sha):
        raise ContractError("update journal rendered state digest is invalid")
    previous_state_mode = state.get("previous_mode")
    if (previous_state_sha is None) != (previous_state_mode is None):
        raise ContractError("update journal previous state digest/mode must be present together")
    if previous_state_mode is not None:
        _parse_mode(previous_state_mode, field_name="update journal previous state mode")
    _parse_mode(state.get("mode"), field_name="update journal state mode")
    expected_plan_digest = sha256_bytes(
        canonical_json({"plan": journal.get("plan"), "state": state})
    )
    if journal.get("plan_digest") != expected_plan_digest:
        raise ContractError("update journal plan digest mismatch")
    plan = _parse_update_plan(
        journal.get("plan"),
        target=target,
        operation_id=operation_id,
    )
    next_index = journal.get("next_index")
    if type(next_index) is not int or not 0 <= next_index <= len(plan.files):
        raise ContractError("update journal next_index is invalid")
    if journal.get("status") not in {"applying", "failed", "aborting", "completed"}:
        raise ContractError("update journal status is invalid")
    return operation_root, journal_path, journal, plan


def _file_state(path: Path) -> tuple[str, int] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"recovery path is not a regular file: {path}")
    return sha256_bytes(path.read_bytes()), stat.S_IMODE(path.stat().st_mode)


def _validate_staged_operation(
    operation_root: Path,
    journal: dict[str, Any],
    plan: SyncPlan,
) -> tuple[Path, Path, bytes]:
    rendered_root = _confined_path(operation_root, "rendered", subject="rendered stage")
    backup_root = _confined_path(operation_root, "backup", subject="update backup")
    if not rendered_root.is_dir() or not backup_root.is_dir():
        raise ContractError("durable update stage or backup directory is missing")
    for item in plan.files:
        staged = _confined_path(rendered_root, item.target, subject="rendered staged file")
        state = _file_state(staged)
        if state != (item.rendered_sha256, item.mode):
            raise ContractError(f"rendered staged file is missing or corrupt: {item.target}")
        item.content = staged.read_bytes()
        backup = _confined_path(backup_root, item.target, subject="update backup file")
        if item.previous_sha256 is None:
            if backup.exists():
                raise ContractError(f"unexpected backup for newly created target: {item.target}")
        elif _file_state(backup) != (item.previous_sha256, item.previous_mode):
            raise ContractError(f"required prior-file backup is missing or corrupt: {item.target}")
    state_stage = _confined_path(rendered_root, STATE_FILE, subject="rendered state file")
    state_record = journal["state"]
    state_mode = _parse_mode(state_record["mode"], field_name="update journal state mode")
    if _file_state(state_stage) != (state_record["rendered_sha256"], state_mode):
        raise ContractError("rendered template state is missing or corrupt")
    state_backup = _confined_path(backup_root, STATE_FILE, subject="template state backup")
    if state_record["previous_sha256"] is None:
        if state_backup.exists():
            raise ContractError("unexpected prior template-state backup")
    else:
        previous_mode = _parse_mode(
            state_record["previous_mode"],
            field_name="update journal previous state mode",
        )
        if _file_state(state_backup) != (state_record["previous_sha256"], previous_mode):
            raise ContractError("required prior template-state backup is missing or corrupt")
    return rendered_root, backup_root, state_stage.read_bytes()


def _git_changed_paths(target: Path) -> set[str]:
    tracked = run_command(
        ["git", "diff", "--name-only", "HEAD", "--"], cwd=target
    ).stdout.splitlines()
    untracked = run_command(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=target
    ).stdout.splitlines()
    return {path for path in tracked + untracked if path}


def _git_head_file_state(target: Path, relative: str) -> tuple[str, int] | None:
    tree = run_command(
        ["git", "ls-tree", "HEAD", "--", relative],
        cwd=target,
        check=False,
    )
    if tree.returncode != 0:
        raise GitPolicyError(f"cannot inspect recorded baseline path: {relative}")
    if not tree.stdout.strip():
        return None
    fields = tree.stdout.split(None, 3)
    if len(fields) != 4 or fields[1] != "blob":
        raise GitPolicyError(f"recorded baseline path is not a file: {relative}")
    git_mode = fields[0]
    mode = 0o755 if git_mode == "100755" else 0o644 if git_mode == "100644" else None
    if mode is None:
        raise GitPolicyError(f"recorded baseline path has unsupported mode: {relative}")
    content = run_command(
        ["git", "show", f"HEAD:{relative}"],
        cwd=target,
        check=False,
    )
    if content.returncode != 0:
        raise GitPolicyError(f"cannot read recorded baseline path: {relative}")
    return sha256_bytes(content.stdout.encode("utf-8")), mode


def _validate_recovery_git(plan: SyncPlan, journal: dict[str, Any]) -> None:
    root = _git_root(plan.target)
    if root != plan.target.resolve():
        raise GitPolicyError("recovery target is not the recorded project Git root")
    branch = run_command(["git", "branch", "--show-current"], cwd=plan.target).stdout.strip()
    if branch != plan.branch:
        raise GitPolicyError("current branch differs from the recorded update branch")
    head = run_command(["git", "rev-parse", "HEAD"], cwd=plan.target).stdout.strip()
    if head != plan.expected_dev_sha:
        raise GitPolicyError("current HEAD differs from the recorded update baseline")
    def matches_git_baseline(
        recorded: tuple[str, int | None] | None,
        baseline: tuple[str, int] | None,
    ) -> bool:
        if recorded is None or baseline is None:
            return recorded is baseline
        return recorded[0] == baseline[0] and bool((recorded[1] or 0) & 0o111) == bool(
            baseline[1] & 0o111
        )

    for item in plan.files:
        recorded = (
            None
            if item.previous_sha256 is None
            else (item.previous_sha256, item.previous_mode)
        )
        if not matches_git_baseline(recorded, _git_head_file_state(plan.target, item.target)):
            raise GitPolicyError(f"journal prior state differs from Git baseline: {item.target}")
    state_record = journal["state"]
    recorded_state = (
        None
        if state_record["previous_sha256"] is None
        else (
            state_record["previous_sha256"],
            _parse_mode(
                state_record["previous_mode"],
                field_name="recorded previous template state mode",
            ),
        )
    )
    if not matches_git_baseline(recorded_state, _git_head_file_state(plan.target, STATE_FILE)):
        raise GitPolicyError("journal prior template state differs from Git baseline")
    allowed = {item.target for item in plan.files} | {STATE_FILE}
    unexpected = sorted(_git_changed_paths(plan.target) - allowed)
    if unexpected:
        raise GitPolicyError(f"working tree contains changes outside the recorded update: {unexpected}")
    fetched = _fetch_exact_dev(plan.target, plan.remote or "")
    if fetched != plan.expected_dev_sha:
        raise GitPolicyError("remote dev moved since the interrupted update")


def _matches_previous(path: Path, item: RenderedFile) -> bool:
    current = _file_state(path)
    if item.previous_sha256 is None:
        return current is None
    return current == (item.previous_sha256, item.previous_mode)


def _matches_rendered(path: Path, item: RenderedFile) -> bool:
    return _file_state(path) == (item.rendered_sha256, item.mode)


def _observe_update_progress(plan: SyncPlan, journal: dict[str, Any]) -> int:
    recorded = journal["next_index"]
    observed = recorded
    aborting = journal["status"] == "aborting"
    for index, item in enumerate(plan.files):
        destination = _confined_path(plan.target, item.target, subject="update destination")
        previous = _matches_previous(destination, item)
        rendered = _matches_rendered(destination, item)
        if index < recorded:
            if not rendered and not (aborting and previous):
                raise GitPolicyError(f"applied update destination was modified: {item.target}")
            continue
        if index == recorded and rendered and not previous and not aborting:
            observed = recorded + 1
            continue
        if not previous:
            raise GitPolicyError(f"unapplied update destination was modified: {item.target}")
    state_record = journal["state"]
    state_path = _confined_path(plan.target, STATE_FILE, subject="template state")
    current_state = _file_state(state_path)
    previous_state = (
        None
        if state_record["previous_sha256"] is None
        else (
            state_record["previous_sha256"],
            _parse_mode(
                state_record["previous_mode"],
                field_name="update journal previous state mode",
            ),
        )
    )
    rendered_state = (
        state_record["rendered_sha256"],
        _parse_mode(state_record["mode"], field_name="update journal state mode"),
    )
    if current_state not in {previous_state, rendered_state}:
        raise GitPolicyError("template state changed outside the recorded update")
    if current_state == rendered_state and observed < len(plan.files):
        raise GitPolicyError("template state advanced before all recorded files")
    return observed


def _cleanup_operation(operation_root: Path) -> None:
    if operation_root.is_symlink() or not operation_root.is_dir():
        raise ContractError("refusing to clean an unconfined update operation")
    shutil.rmtree(operation_root)


def _continue_update(
    plan: SyncPlan,
    operation_root: Path,
    journal_path: Path,
    journal: dict[str, Any],
) -> dict[str, Any]:
    _, _, staged_state = _validate_staged_operation(operation_root, journal, plan)
    _validate_recovery_git(plan, journal)
    observed = _observe_update_progress(plan, journal)
    if observed != journal["next_index"]:
        journal["next_index"] = observed
        _write_update_journal(journal_path, journal)
    fail_after = int(os.environ.get("NM_V6_UPDATE_FAIL_AFTER", "-1"))
    try:
        for directory in plan.created_directories:
            _confined_path(plan.target, directory, subject="manifest directory").mkdir(
                parents=True, exist_ok=True
            )
        for index in range(journal["next_index"], len(plan.files)):
            item = plan.files[index]
            destination = _confined_path(plan.target, item.target, subject="update destination")
            if not _matches_previous(destination, item):
                raise GitPolicyError(f"update destination changed before apply: {item.target}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(destination, item.content, mode=item.mode)
            journal["next_index"] = index + 1
            _write_update_journal(journal_path, journal)
            if fail_after >= 0 and index + 1 >= fail_after:
                raise NmV6Error("injected update failure")
        state_mode = _parse_mode(journal["state"]["mode"], field_name="template state mode")
        atomic_write(plan.target / STATE_FILE, staged_state, mode=state_mode)
        journal["status"] = "completed"
        _write_update_journal(journal_path, journal)
        _cleanup_operation(operation_root)
        return plan.public_record()
    except Exception:
        journal["status"] = "failed"
        _write_update_journal(journal_path, journal)
        raise


def _prepare_update_operation(plan: SyncPlan) -> tuple[Path, Path, dict[str, Any]]:
    _assert_no_pending_update(plan.target)
    manifest = load_manifest(plan.source_root)
    manifest_path = _confined_path(plan.source_root, MANIFEST_RELATIVE, subject="V6 manifest")
    if sha256_bytes(manifest_path.read_bytes()) != plan.manifest_sha256:
        raise ContractError("V6 source manifest changed after the update plan was built")
    operation_root = _operation_root(plan.target, plan.operation_id)
    rendered_root = operation_root / "rendered"
    backup_root = operation_root / "backup"
    try:
        rendered_root.mkdir(parents=True, mode=0o700)
        backup_root.mkdir(parents=True, mode=0o700)
        os.chmod(operation_root, 0o700)
        for item in plan.files:
            destination = _confined_path(plan.target, item.target, subject="update destination")
            if not _matches_previous(destination, item):
                raise GitPolicyError(f"update destination changed after planning: {item.target}")
            staged = _confined_path(rendered_root, item.target, subject="rendered staged file")
            staged.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(staged, item.content, mode=item.mode)
            if item.previous_sha256 is not None:
                backup = _confined_path(backup_root, item.target, subject="update backup file")
                backup.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(backup, destination.read_bytes(), mode=item.previous_mode)
        state_bytes = _state_bytes(plan, manifest=manifest)
        state_path = _confined_path(plan.target, STATE_FILE, subject="template state")
        previous_state = _file_state(state_path)
        staged_state = _confined_path(rendered_root, STATE_FILE, subject="rendered state file")
        atomic_write(staged_state, state_bytes, mode=0o644)
        if previous_state is not None:
            state_backup = _confined_path(backup_root, STATE_FILE, subject="template state backup")
            atomic_write(state_backup, state_path.read_bytes(), mode=previous_state[1])
        state_record = {
            "previous_sha256": previous_state[0] if previous_state else None,
            "previous_mode": oct(previous_state[1]) if previous_state else None,
            "rendered_sha256": sha256_bytes(state_bytes),
            "mode": oct(0o644),
        }
        plan_record = plan.public_record()
        journal: dict[str, Any] = {
            "schema_version": "nm-v6/update-journal-v2",
            "operation_id": plan.operation_id,
            "plan": plan_record,
            "plan_digest": sha256_bytes(
                canonical_json({"plan": plan_record, "state": state_record})
            ),
            "state": state_record,
            "next_index": 0,
            "status": "applying",
            "updated_at": utc_now(),
            "journal_digest": "",
        }
        journal_path = _confined_path(operation_root, JOURNAL_NAME, subject="update journal")
        _write_update_journal(journal_path, journal)
        return operation_root, journal_path, journal
    except Exception:
        if operation_root.exists() and not (operation_root / JOURNAL_NAME).exists():
            _cleanup_operation(operation_root)
        raise


def _apply_plan(plan: SyncPlan) -> dict[str, Any]:
    _validate_staged_plan(plan)
    if plan.mode != "update":
        return _apply_transient_plan(plan)
    operation_root, journal_path, journal = _prepare_update_operation(plan)
    return _continue_update(plan, operation_root, journal_path, journal)


def abort_update(target: Path) -> None:
    target = target.expanduser().resolve()
    operation_root, journal_path, journal, plan = _load_update_operation(target)
    if journal["status"] not in {"applying", "failed", "aborting"}:
        raise NmV6Error("update journal is not in an abortable state")
    _validate_staged_operation(operation_root, journal, plan)
    _validate_recovery_git(plan, journal)
    observed = _observe_update_progress(plan, journal)
    journal["status"] = "aborting"
    journal["next_index"] = observed
    _write_update_journal(journal_path, journal)
    backup_root = _confined_path(operation_root, "backup", subject="update backup")
    for item in reversed(plan.files[:observed]):
        destination = _confined_path(target, item.target, subject="update destination")
        if item.previous_sha256 is None:
            if _matches_previous(destination, item):
                continue
            if not _matches_rendered(destination, item):
                raise GitPolicyError(f"refusing to delete changed update destination: {item.target}")
            destination.unlink()
        else:
            if _matches_previous(destination, item):
                continue
            if not _matches_rendered(destination, item):
                raise GitPolicyError(f"refusing to restore changed update destination: {item.target}")
            backup = _confined_path(backup_root, item.target, subject="update backup file")
            atomic_write(destination, backup.read_bytes(), mode=item.previous_mode)
    state_record = journal["state"]
    state_path = _confined_path(target, STATE_FILE, subject="template state")
    current_state = _file_state(state_path)
    rendered_state = (
        state_record["rendered_sha256"],
        _parse_mode(state_record["mode"], field_name="template state mode"),
    )
    if current_state == rendered_state:
        if state_record["previous_sha256"] is None:
            state_path.unlink()
        else:
            state_backup = _confined_path(backup_root, STATE_FILE, subject="template state backup")
            atomic_write(
                state_path,
                state_backup.read_bytes(),
                mode=_parse_mode(
                    state_record["previous_mode"],
                    field_name="previous template state mode",
                ),
            )
    if _git_changed_paths(target):
        raise GitPolicyError("abort did not restore the exact clean update baseline")
    _cleanup_operation(operation_root)


def resume_update(target: Path, source_root: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    source_root = source_root.expanduser().resolve()
    operation_root, journal_path, journal, plan = _load_update_operation(target)
    if journal["status"] not in {"applying", "failed", "completed"}:
        raise NmV6Error("update journal is not in a resumable state")
    if plan.source_root != source_root:
        raise NmV6Error("resume source differs from the recorded update source")
    manifest_path = _confined_path(source_root, MANIFEST_RELATIVE, subject="V6 manifest")
    if not manifest_path.is_file() or sha256_bytes(manifest_path.read_bytes()) != plan.manifest_sha256:
        raise ContractError("resume source manifest differs from the recorded update plan")
    if journal["status"] == "completed":
        _validate_staged_operation(operation_root, journal, plan)
        _validate_recovery_git(plan, journal)
        if _observe_update_progress(plan, journal) != len(plan.files):
            raise ContractError("completed update journal does not match observed destinations")
        _cleanup_operation(operation_root)
        return plan.public_record()
    return _continue_update(plan, operation_root, journal_path, journal)


def initialize_project(
    target: Path,
    *,
    source_root: Path | None = None,
    project_name: str | None = None,
    package_name: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = (source_root or repository_root()).resolve()
    target = target.expanduser().resolve()
    if target.exists() and not target.is_dir():
        raise NmV6Error("V6 init target exists and is not a directory")
    if target.exists() and any(target.iterdir()):
        raise NmV6Error("V6 init requires an empty target; use update for an existing project")
    if not target.exists() and not dry_run:
        target.mkdir(parents=True)
    plan = build_sync_plan(
        target=target,
        source_root=source,
        mode="init",
        project_name=project_name,
        package_name=package_name,
        branch="task/nm-v6-bootstrap",
    )
    _validate_staged_plan(plan)
    if dry_run:
        return plan.public_record()
    result = _apply_plan(plan)
    run_command(["git", "init", "-b", "task/nm-v6-bootstrap"], cwd=target)
    run_command(["git", "add", "--all"], cwd=target)
    run_command(
        [
            "git",
            "-c",
            "user.name=NM V6 Bootstrap",
            "-c",
            "user.email=nm-v6-bootstrap@invalid",
            "commit",
            "-m",
            "chore: initialize NM V6 workflow",
        ],
        cwd=target,
    )
    run_command(["git", "branch", "main"], cwd=target)
    run_command(["git", "branch", "dev"], cwd=target)
    if run_command(["git", "status", "--porcelain=v1"], cwd=target).stdout.strip():
        raise NmV6Error("V6 init did not leave a clean repository")
    return result


def update_project(
    target: Path,
    *,
    source_root: Path | None = None,
    remote: str = "origin",
    branch: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = (source_root or repository_root()).resolve()
    target = target.expanduser().resolve()
    _require_clean_git_root(target)
    _assert_no_pending_update(target)
    expected = _fetch_exact_dev(target, remote)
    branch_name = branch or f"chore/sync-nm-v6-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if not ALLOWED_BRANCH.fullmatch(branch_name) or branch_name in PROTECTED_BRANCHES:
        raise GitPolicyError(f"update branch is not allowed: {branch_name}")
    if run_command(["git", "show-ref", "--verify", f"refs/heads/{branch_name}"], cwd=target, check=False).returncode == 0:
        raise GitPolicyError(f"update branch already exists: {branch_name}")
    plan = build_sync_plan(
        target=target,
        source_root=source,
        mode="update",
        branch=branch_name,
        remote=remote,
        expected_dev_sha=expected,
    )
    _validate_staged_plan(plan)
    if dry_run:
        return plan.public_record()
    run_command(["git", "switch", "--create", branch_name, expected], cwd=target)
    return _apply_plan(plan)


def check_generated_project(target: Path, *, source_root: Path | None = None) -> dict[str, Any]:
    target = target.expanduser().resolve()
    source = (source_root or repository_root()).resolve()
    plan = build_sync_plan(target=target, source_root=source, mode="check")
    _validate_staged_plan(plan)
    missing = [item.target for item in plan.files if not (target / item.target).is_file()]
    if missing:
        raise ContractError(f"generated project files are missing: {', '.join(missing)}")
    if (target / ".nm/runtime/v5").exists() or (
        (target / "0b-runtime/INDEX.yaml").exists() and not (target / ".nm/runtime/v6/state.sqlite3").exists()
    ):
        raise ContractError("V5 mutable INDEX/task-card runtime cannot be imported or resumed as V6 state")
    from .contracts import validate_project_config

    validate_project_config(load_json(target / "project.json"))
    dependencies = validate_dependency_constraints(target, require_lock=False)
    schemas = validate_schema_catalog(target / "0c-workflow/schemas")
    return {
        "schema_version": "nm-v6/check-result-v1",
        "result": "passed",
        "files": len(plan.files),
        "dependencies": dependencies,
        "schemas": len(schemas),
    }


def check_installed_project(target: Path) -> dict[str, Any]:
    """Validate a generated project without requiring the source checkout."""

    target = target.expanduser().resolve()
    state = _load_state(target)
    if state.get("schema_version") != "nm-v6/template-state-v1" or state.get("template") != "v6":
        raise ContractError(f"missing or invalid {STATE_FILE}")
    files = state.get("files")
    if not isinstance(files, dict) or not files:
        raise ContractError("template state does not describe generated files")
    missing: list[str] = []
    changed_managed: list[str] = []
    for relative, record in files.items():
        ensure_relative_path(relative, field="template state target")
        path = target / relative
        if not path.is_file():
            missing.append(relative)
            continue
        if record.get("policy") == "managed" and sha256_bytes(path.read_bytes()) != record.get("sha256"):
            changed_managed.append(relative)
    if missing:
        raise ContractError(f"generated project files are missing: {', '.join(sorted(missing))}")
    if changed_managed:
        raise ContractError(f"managed workflow files differ from installed hashes: {', '.join(sorted(changed_managed))}")
    ignore = (target / ".gitignore").read_text(encoding="utf-8")
    if ".nm/runtime/" not in ignore:
        raise ContractError(".gitignore must exclude the V6 runtime authority")
    if (target / ".nm/runtime/v5").exists() or (
        (target / "0b-runtime/INDEX.yaml").exists() and not (target / ".nm/runtime/v6/state.sqlite3").exists()
    ):
        raise ContractError("V5 mutable INDEX/task-card runtime cannot be imported or resumed as V6 state")
    from .contracts import validate_project_config

    validate_project_config(load_json(target / "project.json"))
    dependencies = validate_dependency_constraints(target, require_lock=False)
    schemas = validate_schema_catalog(target / "0c-workflow/schemas")
    return {
        "schema_version": "nm-v6/check-result-v1",
        "result": "passed",
        "files": len(files),
        "dependencies": dependencies,
        "schemas": len(schemas),
    }
