#!/usr/bin/env python3
"""Initialize, update, check, or install the NM V3 workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPOSITORY = "https://github.com/notmaster/nm-docs.git"
RAW_BASE = "https://raw.githubusercontent.com/notmaster/nm-docs"
DEFAULT_REF = "main"
MANIFEST_PATH = "template/v3/manifest.json"
STATE_FILE = ".nm-template-state.json"
SAFE_BRANCH_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


class NmV3Error(RuntimeError):
    """Fatal workflow error."""


@dataclass
class SyncPlan:
    target: Path
    mode: str
    dry_run: bool
    source_label: str
    ref: str
    manifest: dict[str, Any]
    project: dict[str, str]
    created_dirs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    updated_files: list[str] = field(default_factory=list)
    preserved_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    records: dict[str, dict[str, Any]] = field(default_factory=dict)


def run(command: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise NmV3Error(f"command failed: {' '.join(command)}\n{message}")
    return result


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage the NM V3 workflow template.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("init", "update", "check"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--target", default=".", help="Target project directory.")
        sub.add_argument("--project-name", help="Render {{PROJECT_NAME}}.")
        sub.add_argument("--package-name", help="Render {{PACKAGE_NAME}}.")
        sub.add_argument("--ref", default=DEFAULT_REF, help="nm-docs ref to read from.")
        sub.add_argument("--source-dir", help="Read templates from a local nm-docs checkout.")
        sub.add_argument("--dry-run", action="store_true", help="Show actions without writing.")
        if name == "init":
            sub.add_argument("--no-git-init", action="store_true", help="Do not run git init for a new project.")
        if name == "update":
            sub.add_argument(
                "--branch",
                help="Branch to create before updating. Defaults to chore/sync-nm-workflow-v3-YYYYMMDD.",
            )
            sub.add_argument(
                "--allow-dirty",
                action="store_true",
                help="Allow update with a dirty working tree. Not recommended.",
            )

    install = subparsers.add_parser("install-skill")
    install.add_argument("--agent", default="agents", choices=("agents", "codex"))
    install.add_argument("--target-dir", help="Skill root directory. Defaults to ~/.agents/skills.")
    install.add_argument("--source-dir", help="Local nm-docs checkout. Defaults to this script's repo.")
    install.add_argument("--dry-run", action="store_true")

    return parser.parse_args()


def local_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_target(value: str, *, create: bool) -> Path:
    target = Path(value).expanduser().resolve()
    if create:
        target.mkdir(parents=True, exist_ok=True)
    if not target.exists() or not target.is_dir():
        raise NmV3Error(f"target directory does not exist: {target}")
    return target


def validate_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise NmV3Error(f"invalid manifest path: {value!r}")
    path = Path(value)
    if path.is_absolute() or value == "." or ".." in path.parts:
        raise NmV3Error(f"manifest path must stay inside project: {value}")
    return value


def read_source_file(relative: str, *, source_dir: Path | None, ref: str) -> bytes:
    if source_dir:
        path = source_dir / relative
        if not path.is_file():
            raise NmV3Error(f"missing template source: {path}")
        return path.read_bytes()

    url = f"{RAW_BASE}/{ref}/{relative}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise NmV3Error(f"failed to download {url}: {exc}") from exc


def load_manifest(*, source_dir: Path | None, ref: str) -> dict[str, Any]:
    data = read_source_file(MANIFEST_PATH, source_dir=source_dir, ref=ref)
    try:
        manifest = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise NmV3Error(f"invalid manifest JSON: {exc}") from exc
    for key in ("directories", "templates"):
        if not isinstance(manifest.get(key), list):
            raise NmV3Error(f"manifest missing list: {key}")
    return manifest


def render_content(data: bytes, project: dict[str, str]) -> bytes:
    text = data.decode("utf-8")
    for key, value in project.items():
        text = text.replace("{{" + key + "}}", value)
    return text.encode("utf-8")


def project_values(target: Path, args: argparse.Namespace) -> dict[str, str]:
    project_name = args.project_name or target.name
    package_name = args.package_name or re.sub(r"[^a-z0-9._~-]+", "-", project_name.lower()).strip("-")
    return {
        "PROJECT_NAME": project_name,
        "PACKAGE_NAME": package_name or "nm-project",
    }


def load_state(target: Path) -> dict[str, Any]:
    path = target / STATE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NmV3Error(f"invalid {STATE_FILE}: {exc}") from exc


def write_state(plan: SyncPlan) -> None:
    state = {
        "template": "v3",
        "templateVersion": plan.manifest.get("templateVersion"),
        "source": plan.source_label,
        "ref": plan.ref,
        "project": plan.project,
        "files": plan.records,
    }
    if not plan.dry_run:
        (plan.target / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_write(path: Path, data: bytes, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def merge_package_json(existing: bytes | None, incoming: bytes, merge_roots: list[str]) -> bytes:
    if existing is None:
        return incoming
    try:
        current = json.loads(existing.decode("utf-8"))
        desired = json.loads(incoming.decode("utf-8"))
    except json.JSONDecodeError:
        return existing
    changed = False
    for root in merge_roots:
        if root not in desired:
            continue
        if root not in current or not isinstance(current[root], dict):
            current[root] = desired[root]
            changed = True
            continue
        for key, value in desired[root].items():
            if key not in current[root]:
                current[root][key] = value
                changed = True
    if not changed:
        return existing
    return (json.dumps(current, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def apply_manifest(args: argparse.Namespace, *, mode: str) -> SyncPlan:
    target = resolve_target(args.target, create=(mode == "init"))
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else None
    manifest = load_manifest(source_dir=source_dir, ref=args.ref)
    source_label = str(source_dir) if source_dir else f"{RAW_BASE}/{args.ref}"
    project = project_values(target, args)
    plan = SyncPlan(target, mode, args.dry_run or mode == "check", source_label, args.ref, manifest, project)
    state = load_state(target)

    for directory in manifest.get("directories", []):
        relative = validate_relative_path(directory)
        path = target / relative
        if path.exists():
            continue
        plan.created_dirs.append(relative)
        if not plan.dry_run:
            path.mkdir(parents=True, exist_ok=True)

    for directory in manifest.get("gitkeepDirectories", []):
        relative = validate_relative_path(directory)
        gitkeep = target / relative / ".gitkeep"
        if not gitkeep.exists():
            plan.created_files.append(str(Path(relative) / ".gitkeep"))
            safe_write(gitkeep, b"", dry_run=plan.dry_run)

    for item in manifest.get("templates", []):
        target_rel = validate_relative_path(item.get("target"))
        source_rel = validate_relative_path(item.get("source"))
        policy = item.get("policy", "create-only")
        target_path = target / target_rel
        incoming = render_content(read_source_file(source_rel, source_dir=source_dir, ref=args.ref), project)
        existing = target_path.read_bytes() if target_path.exists() else None

        if mode == "check":
            if existing is None:
                plan.warnings.append(f"missing: {target_rel}")
            continue

        if policy == "json-merge":
            content = merge_package_json(existing, incoming, item.get("mergeRoots", []))
            if existing == content:
                plan.preserved_files.append(target_rel)
            else:
                (plan.updated_files if existing is not None else plan.created_files).append(target_rel)
                safe_write(target_path, content, dry_run=plan.dry_run)
                plan.records[target_rel] = {"sha256": sha256(content), "policy": policy}
            continue

        should_write = False
        if existing is None:
            plan.created_files.append(target_rel)
            should_write = True
        elif mode == "update":
            plan.updated_files.append(target_rel)
            should_write = True
        else:
            plan.preserved_files.append(target_rel)

        if should_write:
            safe_write(target_path, incoming, dry_run=plan.dry_run)
            plan.records[target_rel] = {"sha256": sha256(incoming), "policy": policy}

    if mode != "check":
        existing_records = state.get("files", {}) if isinstance(state.get("files"), dict) else {}
        plan.records = {**existing_records, **plan.records}
        write_state(plan)

    return plan


def git_root(target: Path) -> Path | None:
    result = run(["git", "rev-parse", "--show-toplevel"], target, check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def ensure_git_for_update(target: Path, *, allow_dirty: bool, branch: str | None, dry_run: bool) -> None:
    root = git_root(target)
    if root is None or root != target:
        raise NmV3Error("update requires target to be the root of a Git repository")
    status = run(["git", "status", "--short"], target).stdout.strip()
    if status and not allow_dirty:
        raise NmV3Error("working tree has changes; commit or stash before update")
    branch_name = branch or default_update_branch()
    exists = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"], target, check=False).returncode == 0
    if exists:
        raise NmV3Error(f"branch already exists: {branch_name}")
    if dry_run:
        print(f"DRY-RUN create branch: {branch_name}")
        return
    run(["git", "switch", "-c", branch_name], target)


def default_update_branch() -> str:
    from datetime import datetime

    return f"chore/sync-nm-workflow-v3-{datetime.now().strftime('%Y%m%d')}"


def set_executable_bits(target: Path, *, dry_run: bool) -> None:
    for rel in (
        "0d-scripts/check-workflow.sh",
        "0d-scripts/verify.sh",
        "0d-scripts/notify-admin.sh",
        "0d-scripts/nm-notify-feishu.sh",
        ".codex/hooks/stop-status.sh",
    ):
        path = target / rel
        if path.exists() and not dry_run:
            path.chmod(path.stat().st_mode | 0o755)


def maybe_git_init(target: Path, *, disabled: bool, dry_run: bool) -> None:
    if disabled or git_root(target) is not None:
        return
    if dry_run:
        print("DRY-RUN git init")
        return
    result = run(["git", "init", "-b", "main"], target, check=False)
    if result.returncode != 0:
        run(["git", "init"], target)


def install_skill(args: argparse.Namespace) -> None:
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else local_repo_root()
    skill_source = source_dir / "skills" / "nm-init-project-v3"
    if not skill_source.is_dir():
        raise NmV3Error(f"missing skill source: {skill_source}")
    if args.target_dir:
        target_root = Path(args.target_dir).expanduser().resolve()
    elif args.agent == "codex":
        target_root = Path.home() / ".codex" / "skills"
    else:
        target_root = Path.home() / ".agents" / "skills"
    destination = target_root / "nm-init-project-v3"
    print(f"Install skill source: {skill_source}")
    print(f"Install skill target: {destination}")
    if args.dry_run:
        return
    target_root.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(skill_source, destination)
    print("Skill installed.")


def print_plan(plan: SyncPlan) -> None:
    print(f"Mode: {plan.mode}")
    print(f"Target: {plan.target}")
    print(f"Source: {plan.source_label}")
    print(f"Template version: {plan.manifest.get('templateVersion')}")
    for label, values in (
        ("Created directories", plan.created_dirs),
        ("Created files", plan.created_files),
        ("Updated files", plan.updated_files),
        ("Preserved files", plan.preserved_files),
        ("Warnings", plan.warnings),
    ):
        print(f"{label}: {len(values)}")
        for value in values:
            print(f"  - {value}")


def main() -> int:
    args = parse_args()
    try:
        if args.command == "install-skill":
            install_skill(args)
            return 0
        if args.command == "update":
            target = resolve_target(args.target, create=False)
            ensure_git_for_update(target, allow_dirty=args.allow_dirty, branch=args.branch, dry_run=args.dry_run)
        plan = apply_manifest(args, mode=args.command)
        if args.command == "init":
            maybe_git_init(plan.target, disabled=args.no_git_init, dry_run=plan.dry_run)
        set_executable_bits(plan.target, dry_run=plan.dry_run)
        print_plan(plan)
        return 2 if plan.warnings and args.command == "check" else 0
    except NmV3Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
