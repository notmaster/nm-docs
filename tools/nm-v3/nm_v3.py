#!/usr/bin/env python3
"""Initialize, migrate, update, inspect, and validate NM V3 projects."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPOSITORY = "https://github.com/notmaster/nm-docs.git"
RAW_BASE = "https://raw.githubusercontent.com/notmaster/nm-docs"
COMMITS_API = "https://api.github.com/repos/notmaster/nm-docs/commits"
DEFAULT_REF = "main"
MANIFEST_PATH = "template/v3/manifest.json"
STATE_FILE = ".nm-template-state.json"
TEMPLATE_VERSION = "3.1.0"
STATE_SCHEMA_VERSION = 2
PROJECT_RULES_START = "<!-- NM-V3-PROJECT-RULES:START -->"
PROJECT_RULES_END = "<!-- NM-V3-PROJECT-RULES:END -->"
ALLOWED_BRANCH = re.compile(r"^(feature|fix|docs|refactor|chore|task)/[A-Za-z0-9][A-Za-z0-9._/-]*$")


class NmV3Error(RuntimeError):
    """Fatal V3 operation error."""


@dataclass
class SyncPlan:
    target: Path
    mode: str
    dry_run: bool
    source_label: str
    source_commit: str | None
    source_dirty: bool | None
    ref: str
    manifest: dict[str, Any]
    project: dict[str, str]
    created_dirs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    updated_files: list[str] = field(default_factory=list)
    preserved_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    contents: dict[str, bytes] = field(default_factory=dict)


def run(command: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise NmV3Error(f"command failed: {' '.join(command)}\n{message}")
    return result


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage the NM V3.1 workflow template.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("init", "update", "migrate", "check", "status", "create-spec"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--target", default=".", help="Target project directory.")
        if name in {"init", "update", "migrate", "check", "create-spec"}:
            sub.add_argument("--project-name", help="Render {{PROJECT_NAME}}.")
            sub.add_argument("--package-name", help="Render {{PACKAGE_NAME}}.")
            sub.add_argument("--ref", default=DEFAULT_REF, help="nm-docs ref to read from.")
            sub.add_argument("--source-dir", help="Read templates from a local nm-docs checkout.")
        if name in {"init", "update", "migrate", "create-spec"}:
            sub.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
        if name == "init":
            sub.add_argument("--no-git-init", action="store_true", help="Generate files without bootstrap Git branches.")
        if name in {"update", "migrate", "create-spec"}:
            sub.add_argument("--branch", help="Task branch to create when currently on a protected branch.")

    stamp = subparsers.add_parser("spec-stamp", help="Bind current spec version and body hash in template state.")
    stamp.add_argument("--target", default=".")

    notify = subparsers.add_parser("notify-test", help="Send one explicitly requested live notification test.")
    notify.add_argument("--target", default=".")
    notify.add_argument("--severity", required=True, choices=("progress", "attention"))
    notify.add_argument("--message", default="NM V3 notify-test")

    finish = subparsers.add_parser("finish", help="Send one idempotent completion handoff for a verified Goal or Plan.")
    finish.add_argument("--target", default=".")
    finish.add_argument("--file", required=True, help="Project-relative standalone Goal or Plan path.")
    finish.add_argument("--message", default="NM V3 work completed")

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


def source_info(source_dir: Path | None, ref: str) -> tuple[str | None, bool | None]:
    if source_dir:
        result = run(["git", "rev-parse", "HEAD"], source_dir, check=False)
        commit = result.stdout.strip() if result.returncode == 0 else None
        status = run(["git", "status", "--short", "--", "template/v3", "tools/nm-v3", "skills/nm-init-project-v3"], source_dir, check=False)
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return commit, dirty
    return (ref if re.fullmatch(r"[0-9a-fA-F]{40}", ref) else None, None)


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


def resolve_remote_ref(ref: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{40}", ref):
        return ref.lower()
    encoded = urllib.parse.quote(ref, safe="")
    request = urllib.request.Request(
        f"{COMMITS_API}/{encoded}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "nm-v3/3.1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise NmV3Error(f"failed to resolve remote ref {ref!r} to an immutable commit: {exc}") from exc
    commit = data.get("sha") if isinstance(data, dict) else None
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise NmV3Error(f"remote ref {ref!r} did not resolve to a valid commit")
    return commit.lower()


def load_manifest(*, source_dir: Path | None, ref: str) -> dict[str, Any]:
    raw = read_source_file(MANIFEST_PATH, source_dir=source_dir, ref=ref)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise NmV3Error(f"invalid manifest JSON: {exc}") from exc
    if manifest.get("schemaVersion") != 2 or manifest.get("templateVersion") != TEMPLATE_VERSION:
        raise NmV3Error("manifest must declare schemaVersion=2 and templateVersion=3.1.0")
    for key in ("directories", "templates"):
        if not isinstance(manifest.get(key), list):
            raise NmV3Error(f"manifest missing list: {key}")
    targets: set[str] = set()
    for item in manifest["templates"]:
        target = validate_relative_path(item.get("target"))
        if target in targets:
            raise NmV3Error(f"duplicate manifest target: {target}")
        targets.add(target)
        if item.get("policy") not in {"create-only", "managed", "section-merge", "json-merge"}:
            raise NmV3Error(f"unsupported policy for {target}: {item.get('policy')}")
    return manifest


def render_content(data: bytes, project: dict[str, str]) -> bytes:
    text = data.decode("utf-8")
    for key, value in project.items():
        text = text.replace("{{" + key + "}}", value)
    return text.encode("utf-8")


def project_values(target: Path, args: argparse.Namespace) -> dict[str, str]:
    project_name = getattr(args, "project_name", None) or target.name
    package_name = getattr(args, "package_name", None) or re.sub(
        r"[^a-z0-9._~-]+", "-", project_name.lower()
    ).strip("-")
    return {"PROJECT_NAME": project_name, "PACKAGE_NAME": package_name or "nm-project"}


def load_state(target: Path) -> dict[str, Any]:
    path = target / STATE_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NmV3Error(f"invalid {STATE_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise NmV3Error(f"invalid {STATE_FILE}: root must be an object")
    return data


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def section_bounds(text: str, start: str, end: str) -> tuple[int, int]:
    first = text.find(start)
    last = text.find(end)
    if first < 0 or last < 0 or last < first:
        raise NmV3Error(f"section markers are missing or invalid: {start} ... {end}")
    return first, last + len(end)


def merge_section(existing: bytes, incoming: bytes, item: dict[str, Any]) -> bytes:
    start = item.get("startMarker")
    end = item.get("endMarker")
    if not isinstance(start, str) or not isinstance(end, str):
        raise NmV3Error("section-merge requires startMarker and endMarker")
    old = existing.decode("utf-8")
    new = incoming.decode("utf-8")
    old_first, old_last = section_bounds(old, start, end)
    new_first, new_last = section_bounds(new, start, end)
    return (new[:new_first] + old[old_first:old_last] + new[new_last:]).encode("utf-8")


def framework_hash(data: bytes, item: dict[str, Any]) -> str:
    if item.get("policy") != "section-merge":
        return sha256(data)
    text = data.decode("utf-8")
    first, last = section_bounds(text, item["startMarker"], item["endMarker"])
    return sha256((text[:first] + "<PROJECT_RULES>" + text[last:]).encode("utf-8"))


def merge_package_json(existing: bytes | None, incoming: bytes, item: dict[str, Any]) -> bytes:
    if existing is None:
        return incoming
    try:
        current = json.loads(existing.decode("utf-8"))
        desired = json.loads(incoming.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise NmV3Error(f"cannot merge invalid package.json: {exc}") from exc
    overwrite = item.get("overwriteKeys", {})
    for root in item.get("mergeRoots", []):
        desired_root = desired.get(root, {})
        if not isinstance(current.get(root), dict):
            current[root] = {}
        for key, value in desired_root.items():
            if key not in current[root] or key in overwrite.get(root, []):
                current[root][key] = value
    return (json.dumps(current, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def state_value(plan: SyncPlan, *, documents: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = load_state(plan.target)
    created = previous.get("installedAt") or now_iso()
    return {
        "stateSchemaVersion": STATE_SCHEMA_VERSION,
        "template": "v3",
        "templateVersion": plan.manifest["templateVersion"],
        "source": plan.source_label,
        "sourceRef": plan.ref,
        "sourceCommit": plan.source_commit,
        "sourceDirty": plan.source_dirty,
        "sourceSnapshotSha256": sha256(
            "\n".join(
                f"{path}:{record['sourceSha256']}" for path, record in sorted(plan.records.items())
            ).encode("utf-8")
        ),
        "installedAt": created,
        "updatedAt": now_iso(),
        "project": plan.project,
        "files": plan.records,
        "documents": documents if documents is not None else previous.get("documents", {}),
        "notifications": previous.get("notifications", {}),
    }


def build_sync_plan(args: argparse.Namespace, *, mode: str) -> SyncPlan:
    target = resolve_target(args.target, create=mode == "init")
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else None
    effective_ref = args.ref if source_dir else resolve_remote_ref(args.ref)
    manifest = load_manifest(source_dir=source_dir, ref=effective_ref)
    label = str(source_dir) if source_dir else f"{RAW_BASE}/{effective_ref}"
    commit, dirty = source_info(source_dir, effective_ref)
    plan = SyncPlan(
        target=target,
        mode=mode,
        dry_run=bool(getattr(args, "dry_run", False)) or mode == "check",
        source_label=label,
        source_commit=commit,
        source_dirty=dirty,
        ref=args.ref,
        manifest=manifest,
        project=project_values(target, args),
    )

    for directory in manifest["directories"]:
        relative = validate_relative_path(directory)
        if not (target / relative).exists():
            plan.created_dirs.append(relative)

    for directory in manifest.get("gitkeepDirectories", []):
        relative = str(Path(validate_relative_path(directory)) / ".gitkeep")
        if not (target / relative).exists():
            plan.created_files.append(relative)
            plan.contents[relative] = b""

    for item in manifest["templates"]:
        target_rel = validate_relative_path(item["target"])
        source_rel = validate_relative_path(item["source"])
        incoming = render_content(read_source_file(source_rel, source_dir=source_dir, ref=effective_ref), plan.project)
        path = target / target_rel
        existing = path.read_bytes() if path.exists() else None
        policy = item["policy"]

        if mode == "check":
            if existing is None:
                plan.warnings.append(f"missing: {target_rel}")
            continue

        if existing is None:
            content = incoming
            if target_rel not in plan.created_files:
                plan.created_files.append(target_rel)
        elif policy == "create-only" or mode == "init":
            content = existing
            plan.preserved_files.append(target_rel)
        elif policy == "managed":
            content = incoming
            (plan.updated_files if content != existing else plan.preserved_files).append(target_rel)
        elif policy == "section-merge":
            if mode == "migrate" and (
                item["startMarker"].encode() not in existing or item["endMarker"].encode() not in existing
            ):
                content = incoming
                plan.warnings.append(f"legacy project guidance preserved for administrator review: {target_rel}")
            else:
                content = merge_section(existing, incoming, item)
            (plan.updated_files if content != existing else plan.preserved_files).append(target_rel)
        elif policy == "json-merge":
            content = merge_package_json(existing, incoming, item)
            (plan.updated_files if content != existing else plan.preserved_files).append(target_rel)
        else:
            raise NmV3Error(f"unsupported policy: {policy}")

        plan.contents[target_rel] = content
        plan.records[target_rel] = {
            "policy": policy,
            "sourceSha256": sha256(incoming),
            "installedSha256": sha256(content),
            "frameworkSha256": framework_hash(content, item),
        }
    return plan


def validate_staged_contents(staging: Path, relatives: list[str]) -> None:
    for relative in relatives:
        path = staging / relative
        if relative.endswith(".json"):
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise NmV3Error(f"staged JSON is invalid: {relative}: {exc}") from exc
        if relative.endswith(".sh"):
            run(["bash", "-n", str(path)], staging)
        if relative.endswith(".mjs"):
            run(["node", "--check", str(path)], staging)


def apply_transaction(
    target: Path,
    contents: dict[str, bytes],
    *,
    remove_paths: list[str] | None = None,
    fail_after: int | None = None,
) -> None:
    removals = remove_paths or []
    for relative in [*contents, *removals]:
        validate_relative_path(relative)
    with tempfile.TemporaryDirectory(prefix=".nm-v3-transaction-", dir=target.parent) as temporary:
        transaction = Path(temporary)
        staging = transaction / "staging"
        backup = transaction / "backup"
        for relative, content in contents.items():
            staged = staging / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(content)
        validate_staged_contents(staging, list(contents))

        changed: list[tuple[str, bool]] = []
        removed: list[str] = []
        created_dirs: list[Path] = []
        operations = 0

        def ensure_target_parent(destination: Path) -> None:
            missing: list[Path] = []
            current = destination.parent
            while current != target and not current.exists():
                missing.append(current)
                current = current.parent
            destination.parent.mkdir(parents=True, exist_ok=True)
            created_dirs.extend(reversed(missing))

        try:
            for relative in sorted(contents):
                destination = target / relative
                existed = destination.exists()
                if existed:
                    saved = backup / "changed" / relative
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, saved)
                changed.append((relative, existed))
                ensure_target_parent(destination)
                os.replace(staging / relative, destination)
                operations += 1
                if fail_after is not None and operations >= fail_after:
                    raise NmV3Error("injected transaction failure")
            for relative in removals:
                source = target / relative
                if not source.exists():
                    continue
                saved = backup / "removed" / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, saved)
                removed.append(relative)
        except Exception:
            for relative in reversed(removed):
                source = backup / "removed" / relative
                destination = target / relative
                ensure_target_parent(destination)
                if source.exists():
                    os.replace(source, destination)
            for relative, existed in reversed(changed):
                destination = target / relative
                if destination.exists():
                    destination.unlink()
                if existed:
                    saved = backup / "changed" / relative
                    ensure_target_parent(destination)
                    os.replace(saved, destination)
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise


def apply_sync_plan(
    plan: SyncPlan,
    *,
    documents: dict[str, Any] | None = None,
    remove_paths: list[str] | None = None,
    fail_after: int | None = None,
) -> None:
    if plan.dry_run:
        return
    contents = dict(plan.contents)
    state = state_value(plan, documents=documents)
    contents[STATE_FILE] = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    apply_transaction(plan.target, contents, remove_paths=remove_paths, fail_after=fail_after)


def git_root(target: Path) -> Path | None:
    result = run(["git", "rev-parse", "--show-toplevel"], target, check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def require_clean_git_root(target: Path) -> None:
    root = git_root(target)
    if root is None or root != target:
        raise NmV3Error("operation requires target to be the root of a Git repository")
    if run(["git", "status", "--short"], target).stdout.strip():
        raise NmV3Error("working tree has changes; preserve them before continuing")


def exact_remote_dev(target: Path) -> str:
    if run(["git", "remote", "get-url", "origin"], target, check=False).returncode != 0:
        raise NmV3Error("origin remote is required")
    run(["git", "fetch", "--prune", "origin", "dev"], target)
    remote = run(["git", "rev-parse", "--verify", "origin/dev"], target).stdout.strip()
    local_result = run(["git", "rev-parse", "--verify", "dev"], target, check=False)
    if local_result.returncode != 0:
        raise NmV3Error("local dev is missing")
    local = local_result.stdout.strip()
    if local != remote:
        raise NmV3Error(f"local dev diverged from origin/dev: local={local} remote={remote}")
    return remote


def default_branch(action: str) -> str:
    return f"chore/{action}-nm-workflow-v3-{datetime.now().strftime('%Y%m%d')}"


def prepare_exact_dev_branch(target: Path, branch: str, *, dry_run: bool) -> None:
    require_clean_git_root(target)
    remote = exact_remote_dev(target)
    if not ALLOWED_BRANCH.fullmatch(branch):
        raise NmV3Error(f"invalid task branch: {branch}")
    if run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], target, check=False).returncode == 0:
        raise NmV3Error(f"branch already exists: {branch}")
    print(f"Expected origin/dev: {remote}")
    print(f"Task branch: {branch}")
    if not dry_run:
        run(["git", "switch", "-c", branch, "origin/dev"], target)


def prepare_current_or_new_branch(target: Path, branch: str, *, dry_run: bool) -> None:
    require_clean_git_root(target)
    remote = exact_remote_dev(target)
    current = run(["git", "branch", "--show-current"], target).stdout.strip()
    if ALLOWED_BRANCH.fullmatch(current):
        ancestor = run(["git", "merge-base", "--is-ancestor", "origin/dev", "HEAD"], target, check=False)
        if ancestor.returncode != 0:
            raise NmV3Error(f"current task branch is not based on origin/dev {remote}")
        print(f"Using current task branch: {current}")
        return
    prepare_exact_dev_branch(target, branch, dry_run=dry_run)


def set_executable_bits(target: Path, *, dry_run: bool) -> None:
    for relative in (
        "0d-scripts/check-workflow.mjs",
        "0d-scripts/verify.sh",
        "0d-scripts/notify-event.sh",
        "0d-scripts/notify-admin.sh",
        "0d-scripts/nm-notify-feishu.sh",
        ".codex/hooks/stop-status.sh",
    ):
        path = target / relative
        if path.exists() and not dry_run:
            path.chmod(path.stat().st_mode | 0o755)


def bootstrap_init(args: argparse.Namespace) -> SyncPlan:
    target = resolve_target(args.target, create=True)
    existing_root = git_root(target)
    nonempty = any(target.iterdir())
    if existing_root is not None:
        raise NmV3Error("init does not modify an existing Git repository; use update or migrate")
    if nonempty and not args.no_git_init:
        raise NmV3Error("automatic bootstrap requires an empty target; use --no-git-init or initialize Git first")
    if not args.dry_run and not args.no_git_init:
        run(["git", "init", "-b", "task/bootstrap-v3"], target)
        if run(["git", "var", "GIT_AUTHOR_IDENT"], target, check=False).returncode != 0:
            raise NmV3Error("Git author identity is not configured; configure it before bootstrap init")
    plan = build_sync_plan(args, mode="init")
    apply_sync_plan(plan)
    set_executable_bits(target, dry_run=plan.dry_run)
    if not plan.dry_run and not args.no_git_init:
        run(["git", "add", "--all"], target)
        run(["git", "commit", "-m", "chore: initialize NM V3 3.1.0 workflow"], target)
        head = run(["git", "rev-parse", "HEAD"], target).stdout.strip()
        run(["git", "branch", "main", head], target)
        run(["git", "branch", "dev", head], target)
        run(["git", "switch", "dev"], target)
        run(["git", "branch", "-d", "task/bootstrap-v3"], target)
        print(f"Bootstrap commit: {head}")
        print("Created clean main and dev at the bootstrap commit; current branch is dev.")
    return plan


def spec_parts_from_text(text: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$", text)
    if not match:
        raise NmV3Error("spec has no YAML frontmatter")
    metadata: dict[str, str] = {}
    for key in ("spec_version", "workflow_version", "body_sha256"):
        found = re.search(rf"^{key}:\s*[\"']?([^\"'\s]+)", match.group(1), re.MULTILINE)
        if found:
            metadata[key] = found.group(1)
    return metadata, match.group(2)


def spec_parts(path: Path) -> tuple[dict[str, str], str]:
    try:
        return spec_parts_from_text(path.read_text(encoding="utf-8"))
    except NmV3Error as exc:
        raise NmV3Error(f"{exc}: {path}") from exc


def spec_document(body: str, project_name: str) -> str:
    body = body.replace("<title>", project_name, 1)
    digest = sha256(body.replace("\r\n", "\n").encode("utf-8"))
    stamp = now_iso()
    frontmatter = f'''---
schema_version: 2
spec_version: 0.1.0
workflow_version: 3.1.0
body_sha256: "{digest}"
status: draft
created_at: "{stamp}"
updated_at: "{stamp}"
authors:
  - type: agent
    provider: "notmaster"
    product: "nm-v3"
    model: "deterministic-tool"
reviewers: []
administrator_acceptance:
  status: pending
  accepted_by: null
  accepted_spec_version: null
  accepted_body_sha256: null
  accepted_at: null
---
'''
    return frontmatter + body


def add_spec_reference_text(text: str, *, label: str) -> str:
    first, last = section_bounds(text, PROJECT_RULES_START, PROJECT_RULES_END)
    block = text[first:last]
    if "0a-docs/spec.md" in block:
        return text
    empty = re.search(r"(?m)^  required:\s*\[\]\s*$", block)
    if empty:
        updated = block[: empty.start()] + "  required:\n    - 0a-docs/spec.md" + block[empty.end() :]
    else:
        required = re.search(r"(?m)^  required:\s*$", block)
        if not required:
            raise NmV3Error(f"cannot locate references.required in {label}")
        insertion = required.end()
        updated = block[:insertion] + "\n    - 0a-docs/spec.md" + block[insertion:]
    return text[:first] + updated + text[last:]


def document_state(target: Path) -> dict[str, Any]:
    spec = target / "0a-docs/spec.md"
    if not spec.exists():
        return {}
    metadata, body = spec_parts(spec)
    actual = sha256(body.replace("\r\n", "\n").encode("utf-8"))
    if metadata.get("workflow_version") != TEMPLATE_VERSION:
        raise NmV3Error("spec workflow_version must be 3.1.0")
    if metadata.get("body_sha256") != actual:
        raise NmV3Error("spec body_sha256 does not match the Markdown body")
    return {"spec": {"path": "0a-docs/spec.md", "version": metadata.get("spec_version"), "bodySha256": actual}}


def stamped_spec_text(path: Path, state: dict[str, Any]) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^(---\r?\n)([\s\S]*?)(\r?\n---\r?\n)([\s\S]*)$", text)
    if not match:
        raise NmV3Error(f"spec has no YAML frontmatter: {path}")
    metadata = match.group(2)
    body = match.group(4)
    digest = sha256(body.replace("\r\n", "\n").encode("utf-8"))
    version_match = re.search(r'^spec_version:\s*["\']?([^"\'\s]+)', metadata, re.MULTILINE)
    if not version_match:
        raise NmV3Error("spec-stamp requires spec_version")
    previous = state.get("documents", {}).get("spec")
    if previous and previous.get("bodySha256") != digest and previous.get("version") == version_match.group(1):
        raise NmV3Error("spec body changed without a spec_version change; increment spec_version before stamping")
    metadata, hash_count = re.subn(
        r'^body_sha256:\s*["\']?[^"\'\s]+["\']?\s*$',
        f'body_sha256: "{digest}"',
        metadata,
        count=1,
        flags=re.MULTILINE,
    )
    metadata, time_count = re.subn(
        r'^updated_at:\s*["\']?[^\r\n]+["\']?\s*$',
        f'updated_at: "{now_iso()}"',
        metadata,
        count=1,
        flags=re.MULTILINE,
    )
    if hash_count != 1 or time_count != 1:
        raise NmV3Error("spec-stamp requires body_sha256 and updated_at frontmatter fields")
    return match.group(1) + metadata + match.group(3) + body


def create_spec(args: argparse.Namespace) -> None:
    target = resolve_target(args.target, create=False)
    state = load_state(target)
    if state.get("templateVersion") != TEMPLATE_VERSION:
        raise NmV3Error("create-spec requires an installed NM V3 3.1.0 project")
    branch = args.branch or default_branch("create-spec")
    prepare_current_or_new_branch(target, branch, dry_run=args.dry_run)
    destination = target / "0a-docs/spec.md"
    if destination.exists():
        raise NmV3Error("0a-docs/spec.md already exists")
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else None
    effective_ref = args.ref if source_dir else resolve_remote_ref(args.ref)
    template = read_source_file("template/v3/0c-workflow/SPEC_TEMPLATE.md", source_dir=source_dir, ref=effective_ref).decode("utf-8")
    match = re.match(r"^---\r?\n[\s\S]*?\r?\n---\r?\n([\s\S]*)$", template)
    if not match:
        raise NmV3Error("invalid SPEC_TEMPLATE.md")
    content = spec_document(match.group(1), args.project_name or target.name)
    print("Create: 0a-docs/spec.md")
    print("Update project reference blocks: AGENTS.md, AGENTS.zh-CN.md")
    if args.dry_run:
        return
    english = add_spec_reference_text((target / "AGENTS.md").read_text(encoding="utf-8"), label="AGENTS.md")
    chinese = add_spec_reference_text((target / "AGENTS.zh-CN.md").read_text(encoding="utf-8"), label="AGENTS.zh-CN.md")
    updated_state = dict(state)
    updated_state["documents"] = {
        "spec": {
            "path": "0a-docs/spec.md",
            "version": "0.1.0",
            "bodySha256": sha256(match.group(1).replace("<title>", args.project_name or target.name, 1).replace("\r\n", "\n").encode("utf-8")),
        }
    }
    updated_state["updatedAt"] = now_iso()
    contents = {
        "0a-docs/spec.md": content.encode("utf-8"),
        "AGENTS.md": english.encode("utf-8"),
        "AGENTS.zh-CN.md": chinese.encode("utf-8"),
        STATE_FILE: (json.dumps(updated_state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    }
    apply_transaction(target, contents)


def migrate(args: argparse.Namespace) -> SyncPlan:
    target = resolve_target(args.target, create=False)
    old_state = load_state(target)
    if old_state.get("templateVersion") != "3.0.0":
        raise NmV3Error("migrate currently requires an installed V3 3.0.0 state")
    branch = args.branch or default_branch("migrate")
    prepare_exact_dev_branch(target, branch, dry_run=args.dry_run)
    requirements = target / "0a-docs/0a-product/REQUIREMENTS.md"
    acceptance = target / "0a-docs/0a-product/ACCEPTANCE.md"
    if not requirements.is_file() or not acceptance.is_file():
        raise NmV3Error("V3 3.0 migration requires REQUIREMENTS.md and ACCEPTANCE.md")
    spec = target / "0a-docs/spec.md"
    if spec.exists():
        raise NmV3Error("refusing to overwrite existing 0a-docs/spec.md")
    pending_root = target / ".delete-pending/v3-3.1.0-migration"
    if pending_root.exists():
        raise NmV3Error("migration pending directory already exists; review it before retrying")
    req_text = requirements.read_text(encoding="utf-8")
    acc_text = acceptance.read_text(encoding="utf-8")
    body = (
        f"# Specification: {args.project_name or target.name}\n\n"
        "## Migrated Requirements\n\n"
        f"{req_text.strip()}\n\n"
        "## Migrated Acceptance Criteria\n\n"
        f"{acc_text.strip()}\n"
    )
    old_agents = {
        name: (target / name).read_bytes()
        for name in ("AGENTS.md", "AGENTS.zh-CN.md")
        if (target / name).is_file()
    }
    plan = build_sync_plan(args, mode="migrate")
    plan.mode = "migrate"
    print("Create migration candidate: 0a-docs/spec.md")
    for legacy in (requirements, acceptance):
        print(f"Move pending administrator deletion: {legacy.relative_to(target)}")
    if args.dry_run:
        return plan
    spec_content = spec_document(body, args.project_name or target.name)
    for name in ("AGENTS.md", "AGENTS.zh-CN.md"):
        rendered = plan.contents[name].decode("utf-8")
        plan.contents[name] = add_spec_reference_text(rendered, label=name).encode("utf-8")
    plan.contents["0a-docs/spec.md"] = spec_content.encode("utf-8")
    for legacy in (requirements, acceptance):
        pending_relative = str(Path(".delete-pending/v3-3.1.0-migration") / legacy.relative_to(target))
        plan.contents[pending_relative] = legacy.read_bytes()
    for name, content in old_agents.items():
        pending_relative = str(Path(".delete-pending/v3-3.1.0-migration/legacy-agent-guidance") / name)
        plan.contents[pending_relative] = content
    _, spec_body = spec_parts_from_text(spec_content)
    documents = {
        "spec": {
            "path": "0a-docs/spec.md",
            "version": "0.1.0",
            "bodySha256": sha256(spec_body.replace("\r\n", "\n").encode("utf-8")),
        }
    }
    apply_sync_plan(
        plan,
        documents=documents,
        remove_paths=[str(requirements.relative_to(target)), str(acceptance.relative_to(target))],
    )
    set_executable_bits(target, dry_run=False)
    return plan


def check_project(args: argparse.Namespace) -> SyncPlan:
    plan = build_sync_plan(args, mode="check")
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else None
    is_template_source = source_dir is not None and plan.target == source_dir / "template/v3"
    if not is_template_source:
        state = load_state(plan.target)
        if not state:
            plan.warnings.append(f"missing: {STATE_FILE}")
        else:
            if state.get("stateSchemaVersion") != STATE_SCHEMA_VERSION:
                plan.warnings.append("state schema is not current")
            if state.get("templateVersion") != TEMPLATE_VERSION:
                plan.warnings.append(f"installed template version is {state.get('templateVersion')}; current is {TEMPLATE_VERSION}")
            records = state.get("files", {})
            manifest_items = {item["target"]: item for item in plan.manifest["templates"]}
            for relative, record in records.items():
                path = plan.target / relative
                if not path.exists():
                    plan.warnings.append(f"tracked file is missing: {relative}")
                    continue
                if record.get("policy") == "create-only":
                    continue
                item = manifest_items.get(relative)
                if item and framework_hash(path.read_bytes(), item) != record.get("frameworkSha256"):
                    plan.warnings.append(f"managed framework drift: {relative}")
            try:
                current_docs = document_state(plan.target)
            except NmV3Error as exc:
                plan.warnings.append(str(exc))
            else:
                old_spec = state.get("documents", {}).get("spec")
                current_spec = current_docs.get("spec")
                if old_spec and current_spec and old_spec.get("version") == current_spec.get("version"):
                    if old_spec.get("bodySha256") != current_spec.get("bodySha256"):
                        plan.warnings.append("spec body changed without a spec_version change; run spec-stamp only after versioning the change")
    return plan


def status(target: Path) -> int:
    target = resolve_target(str(target), create=False)
    state = load_state(target)
    if not state:
        print(f"Status: unmanaged (missing {STATE_FILE})")
        return 2
    installed = state.get("templateVersion")
    print(f"Template: {state.get('template')}")
    print(f"Installed version: {installed}")
    print(f"Current version: {TEMPLATE_VERSION}")
    print(f"Source ref: {state.get('sourceRef')}")
    print(f"Source commit: {state.get('sourceCommit') or 'unknown'}")
    print(f"Source dirty: {state.get('sourceDirty') if state.get('sourceDirty') is not None else 'unknown'}")
    print(f"Source snapshot: {state.get('sourceSnapshotSha256') or 'unknown'}")
    print(f"Updated at: {state.get('updatedAt')}")
    spec = state.get("documents", {}).get("spec")
    print(f"Spec: {spec.get('version') if spec else 'not configured'}")
    drift: list[str] = []
    for relative, record in state.get("files", {}).items():
        path = target / relative
        if not path.is_file():
            drift.append(f"missing:{relative}")
            continue
        policy = record.get("policy")
        if policy == "create-only":
            continue
        item: dict[str, Any] = {"policy": policy}
        if policy == "section-merge":
            item.update({"startMarker": PROJECT_RULES_START, "endMarker": PROJECT_RULES_END})
        try:
            actual = framework_hash(path.read_bytes(), item)
        except NmV3Error:
            drift.append(f"invalid:{relative}")
            continue
        if actual != record.get("frameworkSha256"):
            drift.append(f"changed:{relative}")
    print(f"Managed drift: {len(drift)}")
    for item in drift:
        print(f"  - {item}")
    if installed == TEMPLATE_VERSION and not drift:
        print("Upgrade: not required")
        return 0
    if installed == TEMPLATE_VERSION:
        print("Upgrade: version is current but managed files drifted; run check and review an update")
        return 2
    if installed == "3.0.0":
        print("Upgrade: supported through explicit migrate --dry-run then migrate")
        return 2
    print("Upgrade: unsupported without administrator-guided migration")
    return 2


def notify_test(target: Path, severity: str, message: str) -> int:
    script = target / "0d-scripts/notify-event.sh"
    if not script.is_file():
        raise NmV3Error(f"missing notification entry point: {script}")
    result = run(
        [str(script), "--event", "notify_test", "--severity", severity, "--title", f"[TEST] V3 {severity}", "--message", message],
        target,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        raise NmV3Error(result.stderr.strip() or "notification test failed")
    return 0


def scalar_frontmatter(path: Path) -> tuple[dict[str, str | None], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$", text)
    if not match:
        raise NmV3Error(f"missing YAML frontmatter: {path}")
    values: dict[str, str | None] = {}
    for raw in match.group(1).splitlines():
        scalar = re.match(r"^([a-z_]+):\s*(.*?)\s*$", raw)
        if not scalar:
            continue
        value = scalar.group(2).strip().strip('"\'')
        values[scalar.group(1)] = None if value in {"", "null", "~"} else value
    return values, match.group(2)


def finish_work(target: Path, relative_value: str, message: str) -> int:
    target = resolve_target(str(target), create=False)
    relative = validate_relative_path(relative_value)
    if not (
        relative.startswith("0b-goals/0a-plans/plan-")
        or relative.startswith("0b-goals/0b-current/goal-g")
        or relative.startswith("0b-goals/0c-archive/goal-g")
    ):
        raise NmV3Error("finish accepts only a Plan or standalone Goal file")
    subject = target / relative
    if not subject.is_file():
        raise NmV3Error(f"finish subject is missing: {relative}")
    root = git_root(target)
    if root == target:
        branch = run(["git", "branch", "--show-current"], target).stdout.strip()
        if not ALLOWED_BRANCH.fullmatch(branch):
            raise NmV3Error("finish requires an allowed non-protected task branch")
    check = target / "0d-scripts/check-workflow.mjs"
    run(["node", str(check)], target)
    metadata, _ = scalar_frontmatter(subject)
    if relative.startswith("0b-goals/0a-plans/"):
        if metadata.get("status") not in {"awaiting_review", "completed"}:
            raise NmV3Error("Plan finish requires status awaiting_review or completed")
        if metadata.get("full_verification_status") != "pass":
            raise NmV3Error("Plan finish requires full_verification_status=pass")
        if not re.fullmatch(r"[0-9a-f]{40}", metadata.get("full_verification_commit") or ""):
            raise NmV3Error("Plan finish requires full_verification_commit")
    else:
        if metadata.get("plan_id") is not None:
            raise NmV3Error("Goal finish is only for a standalone Goal")
        if metadata.get("status") not in {"verified", "integrated", "archived"}:
            raise NmV3Error("standalone Goal finish requires verified, integrated, or archived status")
        if metadata.get("verification_status") != "pass":
            raise NmV3Error("standalone Goal finish requires verification_status=pass")

    state = load_state(target)
    if state.get("templateVersion") != TEMPLATE_VERSION:
        raise NmV3Error("finish requires an installed NM V3 3.1.0 project")
    digest = sha256(subject.read_bytes())
    key = f"work_completed:{relative}"
    notifications = dict(state.get("notifications", {}))
    existing = notifications.get(key, {})
    if existing.get("status") == "sent" and existing.get("subjectSha256") == digest:
        print(f"Completion notification already sent for unchanged subject: {relative}")
        return 0
    script = target / "0d-scripts/notify-event.sh"
    result = run(
        [str(script), "--event", "work_completed", "--severity", "attention", "--title", "NM V3 work completed", "--message", message],
        target,
        check=False,
    )
    record = {
        "event": "work_completed",
        "subject": relative,
        "subjectSha256": digest,
        "status": "sent" if result.returncode == 0 else "failed",
        "attemptedAt": now_iso(),
    }
    notifications[key] = record
    state["notifications"] = notifications
    state["updatedAt"] = now_iso()
    atomic_json(target / STATE_FILE, state)
    if result.returncode != 0:
        raise NmV3Error(result.stderr.strip() or "completion notification failed")
    if result.stdout:
        print(result.stdout, end="")
    return 0


def install_skill(args: argparse.Namespace) -> None:
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else local_repo_root()
    skill_source = source_dir / "skills/nm-init-project-v3"
    if not skill_source.is_dir():
        raise NmV3Error(f"missing skill source: {skill_source}")
    if args.target_dir:
        target_root = Path(args.target_dir).expanduser().resolve()
    elif args.agent == "codex":
        target_root = Path.home() / ".codex/skills"
    else:
        target_root = Path.home() / ".agents/skills"
    destination = target_root / "nm-init-project-v3"
    tool_source = source_dir / "tools/nm-v3/nm_v3.py"
    if not tool_source.is_file():
        raise NmV3Error(f"missing V3 tool source: {tool_source}")
    commit, dirty = source_info(source_dir, DEFAULT_REF)
    binding = {
        "schemaVersion": 1,
        "templateVersion": TEMPLATE_VERSION,
        "toolSha256": sha256(tool_source.read_bytes()),
        "sourceCheckout": str(source_dir),
        "sourceCommit": commit,
        "sourceDirty": dirty,
        "installedAt": now_iso(),
    }
    print(f"Install skill source: {skill_source}")
    print(f"Install skill target: {destination}")
    print(f"Bundled tool SHA-256: {binding['toolSha256']}")
    print(f"Source commit: {commit or 'unknown'}")
    print(f"Source dirty: {dirty if dirty is not None else 'unknown'}")
    if args.dry_run:
        return
    target_root.mkdir(parents=True, exist_ok=True)
    temporary = target_root / f".nm-init-project-v3-{os.getpid()}"
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(skill_source, temporary)
    vendor = temporary / "scripts/vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tool_source, vendor / "nm_v3.py")
    atomic_json(temporary / ".nm-v3-binding.json", binding)
    run([sys.executable, "-m", "py_compile", str(temporary / "scripts/run_nm_v3.py"), str(vendor / "nm_v3.py")], source_dir)
    for cache in temporary.rglob("__pycache__"):
        shutil.rmtree(cache)
    backup: Path | None = None
    if destination.exists():
        backup = target_root / ".delete-pending" / f"nm-init-project-v3-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(backup))
        print(f"Previous skill moved to: {backup}")
    try:
        os.replace(temporary, destination)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    print("Skill installed.")


def print_plan(plan: SyncPlan) -> None:
    print(f"Mode: {plan.mode}")
    print(f"Target: {plan.target}")
    print(f"Source: {plan.source_label}")
    print(f"Source commit: {plan.source_commit or 'unknown'}")
    print(f"Source dirty: {plan.source_dirty if plan.source_dirty is not None else 'unknown'}")
    print(f"Template version: {plan.manifest['templateVersion']}")
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
        if args.command == "status":
            return status(Path(args.target).expanduser().resolve())
        if args.command == "notify-test":
            return notify_test(resolve_target(args.target, create=False), args.severity, args.message)
        if args.command == "finish":
            return finish_work(Path(args.target).expanduser().resolve(), args.file, args.message)
        if args.command == "spec-stamp":
            target = resolve_target(args.target, create=False)
            root = git_root(target)
            if root == target:
                branch = run(["git", "branch", "--show-current"], target).stdout.strip()
                if not ALLOWED_BRANCH.fullmatch(branch):
                    raise NmV3Error("spec-stamp requires an allowed non-protected task branch")
            state = load_state(target)
            if not state:
                raise NmV3Error(f"missing {STATE_FILE}; initialize or migrate the project first")
            spec_path = target / "0a-docs/spec.md"
            stamped = stamped_spec_text(spec_path, state)
            metadata, body = spec_parts_from_text(stamped)
            updated_state = dict(state)
            updated_state["documents"] = {
                "spec": {
                    "path": "0a-docs/spec.md",
                    "version": metadata.get("spec_version"),
                    "bodySha256": sha256(body.replace("\r\n", "\n").encode("utf-8")),
                }
            }
            updated_state["updatedAt"] = now_iso()
            apply_transaction(
                target,
                {
                    "0a-docs/spec.md": stamped.encode("utf-8"),
                    STATE_FILE: (json.dumps(updated_state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                },
            )
            print("Spec version and body hash stamped in template state.")
            return 0
        if args.command == "init":
            plan = bootstrap_init(args)
        elif args.command == "update":
            target = resolve_target(args.target, create=False)
            installed = load_state(target).get("templateVersion")
            if installed == "3.0.0":
                raise NmV3Error("V3 3.0.0 requires explicit migrate; update must not bypass document migration")
            if installed != TEMPLATE_VERSION:
                raise NmV3Error(f"update requires installed V3 {TEMPLATE_VERSION}; found {installed or 'unmanaged'}")
            prepare_exact_dev_branch(target, args.branch or default_branch("sync"), dry_run=args.dry_run)
            plan = build_sync_plan(args, mode="update")
            apply_sync_plan(plan)
            set_executable_bits(target, dry_run=plan.dry_run)
        elif args.command == "migrate":
            plan = migrate(args)
        elif args.command == "create-spec":
            create_spec(args)
            return 0
        elif args.command == "check":
            plan = check_project(args)
        else:
            raise NmV3Error(f"unsupported command: {args.command}")
        print_plan(plan)
        return 2 if plan.warnings and args.command == "check" else 0
    except NmV3Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
