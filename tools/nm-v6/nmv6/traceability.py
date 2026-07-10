"""Deterministic V6 acceptance, test, and implementation traceability."""

from __future__ import annotations

import ast
import inspect
import os
import re
import stat
import subprocess
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .errors import ContractError
from .specs import canonical_spec_hash
from .util import canonical_json, dump_json, load_json, sha256_bytes, sha256_file


REQ_IDS = {f"V6-REQ-{index:03d}" for index in range(1, 25)}
AC_IDS = {f"V6-AC-{index:03d}" for index in range(1, 61)}
DEC_IDS = {f"V6-DEC-{index:03d}" for index in range(1, 10)}
INV_IDS = {f"V6-INV-{index:03d}" for index in range(1, 17)}
REQ_PATTERN = re.compile(r"^V6-REQ-(?:00[1-9]|01[0-9]|02[0-4])$")
AC_PATTERN = re.compile(r"^V6-AC-(?:00[1-9]|0[1-5][0-9]|060)$")
GENERATED_TRACEABILITY_PATHS = {
    "tools/nm-v6/acceptance-manifest.json",
    "docs/nm-v6-implementation-traceability.md",
    "docs/nm-v6-implementation-traceability.zh-CN.md",
}
ADMINISTRATOR_ACCEPTANCE_RECORD_PATH = "tools/nm-v6/administrator-acceptance.json"
EVIDENCE_ONLY_PATHS = GENERATED_TRACEABILITY_PATHS | {
    ADMINISTRATOR_ACCEPTANCE_RECORD_PATH,
}
ADMINISTRATOR_ACCEPTANCE_SCHEMA_VERSION = "nm-v6/administrator-acceptance-v1"
_ADMINISTRATOR_ACCEPTANCE_FIELDS = {
    "schema_version",
    "decision",
    "spec_id",
    "spec_version",
    "spec_hash",
    "source_change_digest",
    "base_sha",
    "head_sha",
    "acceptance_result_sha256",
    "independent_review_sha256",
    "recommended",
    "production_ready",
    "recorded_at",
    "authority_basis",
}
_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_CACHE_PARTS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
}


def validate_implementation_plan(path: Path) -> dict[str, Any]:
    plan = load_json(path)
    if plan.get("schema_version") != "nm-v6/implementation-plan-v1":
        raise ContractError("unsupported implementation-plan schema")
    if (
        plan.get("spec_id") != "SPEC-NM-WORKFLOW-V6-V1"
        or plan.get("spec_version") != 1
        or not isinstance(plan.get("spec_hash"), str)
    ):
        raise ContractError("implementation plan targets another V6 Spec")
    status = plan.get("status")
    administrator_acceptance = plan.get("administrator_acceptance")
    acceptance_record = plan.get("administrator_acceptance_record")
    if status == "acceptance-candidate":
        if administrator_acceptance != "pending" or acceptance_record is not None:
            raise ContractError("candidate implementation plan overstates administrator acceptance")
    elif status == "accepted":
        if (
            administrator_acceptance != "accepted"
            or acceptance_record != ADMINISTRATOR_ACCEPTANCE_RECORD_PATH
        ):
            raise ContractError("accepted implementation plan lacks its administrator record")
    else:
        raise ContractError("implementation plan has an unsupported status")
    if plan.get("recommended") is not False or plan.get("production_ready") is not False:
        raise ContractError("V6 is not designated recommended or production-ready")
    requirements = plan.get("requirements")
    if not isinstance(requirements, dict) or set(requirements) != REQ_IDS:
        raise ContractError("implementation plan must map every V6 Requirement exactly once")
    for requirement_id, record in requirements.items():
        if not REQ_PATTERN.fullmatch(requirement_id) or not isinstance(record, dict):
            raise ContractError(f"invalid implementation-plan entry: {requirement_id}")
        files = record.get("files")
        tests = record.get("tests")
        if (
            not isinstance(files, list)
            or not files
            or not all(isinstance(item, str) and item for item in files)
            or not isinstance(tests, list)
            or not tests
            or not all(isinstance(item, str) and item for item in tests)
        ):
            raise ContractError(f"implementation-plan entry lacks files/tests: {requirement_id}")
    return plan


def _section(text: str, heading: str, next_heading: str | None) -> str:
    marker = f"### {heading}"
    if marker not in text:
        raise ContractError(f"V6 Spec is missing section {heading}")
    section = text.split(marker, 1)[1]
    if next_heading is not None:
        following = f"### {next_heading}"
        if following not in section:
            raise ContractError(f"V6 Spec is missing section {next_heading}")
        section = section.split(following, 1)[0]
    return section


def _link_table(
    text: str,
    *,
    heading: str,
    next_heading: str | None,
    source_prefix: str,
    target_prefix: str,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for line in _section(text, heading, next_heading).splitlines():
        identifiers = re.findall(r"`(V6-[A-Z]+-[0-9]{3})`", line)
        if not identifiers or not identifiers[0].startswith(source_prefix):
            continue
        source = identifiers[0]
        if source in result:
            raise ContractError(f"duplicate V6 Spec traceability row: {source}")
        targets = [item for item in identifiers[1:] if item.startswith(target_prefix)]
        if not targets or len(targets) != len(set(targets)):
            raise ContractError(f"invalid V6 Spec traceability links: {source}")
        result[source] = targets
    return result


def spec_traceability(spec_path: Path) -> dict[str, dict[str, list[str]]]:
    """Parse and fully validate the normative Spec's three coverage tables."""

    text = spec_path.read_text(encoding="utf-8")
    requirement_acceptance = _link_table(
        text,
        heading="27.1 Requirement coverage",
        next_heading="27.2 Decision coverage",
        source_prefix="V6-REQ-",
        target_prefix="V6-AC-",
    )
    decision_requirements = _link_table(
        text,
        heading="27.2 Decision coverage",
        next_heading="27.3 Invariant coverage",
        source_prefix="V6-DEC-",
        target_prefix="V6-REQ-",
    )
    invariant_requirements = _link_table(
        text,
        heading="27.3 Invariant coverage",
        next_heading=None,
        source_prefix="V6-INV-",
        target_prefix="V6-REQ-",
    )
    expected = (
        ("Requirement", requirement_acceptance, REQ_IDS, AC_IDS),
        ("Decision", decision_requirements, DEC_IDS, REQ_IDS),
        ("Invariant", invariant_requirements, INV_IDS, REQ_IDS),
    )
    for label, mapping, expected_sources, expected_targets in expected:
        if set(mapping) != expected_sources:
            raise ContractError(f"V6 Spec {label} coverage source IDs are incomplete")
        linked = {target for targets in mapping.values() for target in targets}
        if not linked <= expected_targets:
            raise ContractError(f"V6 Spec {label} coverage has dangling links")
    linked_acceptance = {
        acceptance
        for acceptances in requirement_acceptance.values()
        for acceptance in acceptances
    }
    if linked_acceptance != AC_IDS:
        raise ContractError("V6 Spec Requirement coverage must reach every Acceptance ID")
    return {
        "requirements": requirement_acceptance,
        "decisions": decision_requirements,
        "invariants": invariant_requirements,
    }


def acceptance_requirement_map(spec_path: Path) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = {identifier: [] for identifier in AC_IDS}
    for requirement, acceptances in spec_traceability(spec_path)["requirements"].items():
        for acceptance in acceptances:
            reverse[acceptance].append(requirement)
    return {identifier: sorted(requirements) for identifier, requirements in reverse.items()}


def _walk_suite(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _walk_suite(item)
        elif isinstance(item, unittest.TestCase):
            yield item
        else:
            raise ContractError(f"unrecognized unittest suite item: {item!r}")


def selector_for_test(test: unittest.TestCase, *, repository: Path) -> str:
    """Return the stable path::Class.method selector for one discovered test."""

    source = inspect.getsourcefile(test.__class__)
    method = getattr(test, "_testMethodName", None)
    if source is None or not isinstance(method, str) or not method.startswith("test"):
        raise ContractError(f"cannot resolve discovered unittest exactly: {test.id()}")
    try:
        relative = Path(source).resolve().relative_to(repository.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"discovered unittest is outside repository: {test.id()}") from exc
    return f"{relative}::{test.__class__.__name__}.{method}"


def ast_test_selectors(repository: Path) -> set[str]:
    """Read the declared selector inventory without executing test code."""

    selectors: set[str] = set()
    tests_root = repository / "tools/nm-v6/tests"
    for path in sorted(tests_root.glob("test*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ContractError(f"cannot parse V6 test file {path}: {exc}") from exc
        relative = path.relative_to(repository).as_posix()
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                    selector = f"{relative}::{node.name}.{child.name}"
                    if selector in selectors:
                        raise ContractError(f"duplicate AST test selector: {selector}")
                    selectors.add(selector)
    return selectors


def discover_acceptance_suite(
    repository: Path,
    *,
    pattern: str = "test*.py",
) -> tuple[unittest.TestSuite, dict[str, Any]]:
    """Discover the exact suite and bind its unittest and AST inventories."""

    repository = repository.resolve()
    loader = unittest.TestLoader()
    suite = loader.discover(str(repository / "tools/nm-v6/tests"), pattern=pattern)
    if loader.errors:
        raise ContractError("unittest discovery failed: " + " | ".join(loader.errors))
    selectors: list[str] = []
    for test in _walk_suite(suite):
        selectors.append(selector_for_test(test, repository=repository))
    if not selectors or len(selectors) != len(set(selectors)):
        raise ContractError("unittest discovery returned no tests or duplicate selectors")
    declared = ast_test_selectors(repository)
    unresolved = sorted(set(selectors) - declared)
    if unresolved:
        raise ContractError(f"unittest selectors do not resolve exactly through AST: {unresolved}")
    if pattern == "test*.py" and set(selectors) != declared:
        raise ContractError(
            "default unittest discovery does not exactly match AST test inventory; "
            f"undiscovered={sorted(declared - set(selectors))}"
        )
    files = sorted({selector.split("::", 1)[0] for selector in selectors})
    inventory: dict[str, Any] = {
        "pattern": pattern,
        "selectors": sorted(selectors),
        "test_file_sha256": {
            path: sha256_file(repository / path)
            for path in files
        },
    }
    inventory["digest"] = sha256_bytes(canonical_json(inventory))
    return suite, inventory


def discover_test_inventory(repository: Path, *, pattern: str = "test*.py") -> dict[str, Any]:
    _, inventory = discover_acceptance_suite(repository, pattern=pattern)
    return inventory


def validate_test_selector(selector: str, *, inventory: dict[str, Any]) -> None:
    parts = selector.split("::")
    if len(parts) != 2 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.test[A-Za-z0-9_]+", parts[1]):
        raise ContractError(f"invalid acceptance test selector: {selector}")
    if selector not in inventory.get("selectors", []):
        raise ContractError(f"acceptance test selector is not discovered exactly: {selector}")


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git failure"
        raise ContractError(f"cannot establish V6 changed-file scope: {detail}")
    return result.stdout.strip()


def _git_bytes(repository: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        if not detail:
            detail = result.stdout.decode("utf-8", errors="replace").strip()
        raise ContractError(
            f"cannot establish V6 changed-file scope: {detail or 'unknown Git failure'}"
        )
    return result.stdout


def _git_paths(repository: Path, *args: str) -> list[str]:
    raw = _git_bytes(repository, *args)
    if raw and not raw.endswith(b"\0"):
        raise ContractError("Git path output is not NUL terminated")
    try:
        return [item.decode("utf-8") for item in raw.split(b"\0") if item]
    except UnicodeDecodeError as exc:
        raise ContractError("Git path is not valid UTF-8") from exc


def _commit(repository: Path, revision: str, *, subject: str) -> str:
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ContractError(f"{subject} must be a full lowercase Git commit ID")
    resolved = _git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if resolved != revision:
        raise ContractError(f"{subject} does not resolve to its exact Git commit")
    return resolved


def _require_ancestor(repository: Path, ancestor: str, descendant: str, *, subject: str) -> None:
    if _git(repository, "merge-base", ancestor, descendant) != ancestor:
        raise ContractError(subject)


def is_generated_or_cache_path(path: str) -> bool:
    parts = Path(path).parts
    if any(part in _CACHE_PARTS for part in parts) or path.endswith((".pyc", ".pyo")):
        return True
    return path.startswith((".nm/runtime/", ".nm/update/", "tools/nm-v6/acceptance-results/"))


def current_changed_files(
    repository: Path,
    *,
    base_ref: str = "origin/dev",
    base_sha: str | None = None,
    head_sha: str | None = None,
) -> list[str]:
    """Return the fixed-baseline scope for a commit or the current working tree."""

    repository = repository.resolve()
    if base_sha is None:
        resolved_base = _git(
            repository,
            "rev-parse",
            "--verify",
            f"refs/remotes/{base_ref}^{{commit}}",
        )
    else:
        resolved_base = _commit(repository, base_sha, subject="recorded source baseline")
    if head_sha is None:
        resolved_head = _git(repository, "rev-parse", "--verify", "HEAD^{commit}")
        diff_target: tuple[str, ...] = (resolved_base,)
    else:
        resolved_head = _commit(repository, head_sha, subject="recorded tested source")
        diff_target = (resolved_base, resolved_head)
    _require_ancestor(
        repository,
        resolved_base,
        resolved_head,
        subject="recorded source baseline is not an ancestor of the tested source",
    )
    tracked = _git_paths(
        repository,
        "diff",
        "--no-renames",
        "-z",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        *diff_target,
        "--",
    )
    untracked = (
        _git_paths(repository, "ls-files", "-z", "--others", "--exclude-standard")
        if head_sha is None
        else []
    )
    return sorted(
        {path for path in tracked if path}
        | {path for path in untracked if path and not is_generated_or_cache_path(path)}
    )


def _committed_source_file(repository: Path, head_sha: str, relative: str) -> dict[str, str]:
    raw = _git_bytes(repository, "ls-tree", "-z", head_sha, "--", relative)
    if not raw:
        return {"state": "deleted"}
    entries = [entry for entry in raw.split(b"\0") if entry]
    if len(entries) != 1 or b"\t" not in entries[0]:
        raise ContractError(f"cannot parse committed source path: {relative}")
    metadata_bytes, listed_path_bytes = entries[0].split(b"\t", 1)
    try:
        metadata = metadata_bytes.decode("ascii")
        listed_path = listed_path_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"committed source path is not valid UTF-8: {relative}") from exc
    fields = metadata.split()
    if listed_path != relative or len(fields) != 3 or fields[1] != "blob":
        raise ContractError(f"committed source path is not one regular file: {relative}")
    git_mode, _, object_sha = fields
    modes = {"100644", "100755"}
    if git_mode not in modes:
        raise ContractError(f"committed source path has unsupported Git mode: {relative}")
    return {
        "state": "present",
        "mode": git_mode,
        "sha256": sha256_bytes(_git_bytes(repository, "cat-file", "blob", object_sha)),
    }


def source_change_record(
    repository: Path,
    *,
    base_ref: str = "origin/dev",
    base_sha: str | None = None,
    tested_head_sha: str | None = None,
) -> dict[str, Any]:
    """Bind exact committed implementation bytes to immutable baseline B and tested commit C."""

    repository = repository.resolve()
    if base_sha is None:
        resolved_base = _git(
            repository,
            "rev-parse",
            "--verify",
            f"refs/remotes/{base_ref}^{{commit}}",
        )
    else:
        resolved_base = _commit(repository, base_sha, subject="recorded source baseline")
    if tested_head_sha is None:
        resolved_head = _git(repository, "rev-parse", "--verify", "HEAD^{commit}")
        dirty_source = [
            path
            for path in current_changed_files(repository, base_sha=resolved_head)
            if path not in EVIDENCE_ONLY_PATHS
        ]
        if dirty_source:
            raise ContractError(
                "acceptance source must be committed before testing; "
                f"dirty non-generated paths={dirty_source}"
            )
    else:
        resolved_head = _commit(
            repository,
            tested_head_sha,
            subject="recorded tested source",
        )
    _require_ancestor(
        repository,
        resolved_base,
        resolved_head,
        subject="recorded source baseline is not an ancestor of the tested source",
    )
    parents = _git(repository, "rev-list", "--parents", "-n", "1", resolved_head).split()
    if parents != [resolved_head, resolved_base]:
        raise ContractError(
            "tested source must be one non-merge commit whose exact parent is the recorded baseline"
        )
    paths = [
        path
        for path in current_changed_files(
            repository,
            base_ref=base_ref,
            base_sha=resolved_base,
            head_sha=resolved_head,
        )
        if path not in EVIDENCE_ONLY_PATHS
    ]
    files = {
        relative: _committed_source_file(repository, resolved_head, relative)
        for relative in paths
    }
    bound: dict[str, Any] = {
        "base_ref": base_ref,
        "base_ref_sha": resolved_base,
        "merge_base_sha": resolved_base,
        "head_sha": resolved_head,
        "files": files,
    }
    bound["digest"] = sha256_bytes(canonical_json(bound))
    return bound


def validate_source_change_record(record: dict[str, Any], *, repository: Path) -> dict[str, Any]:
    """Validate immutable B/C evidence against an evidence-only descendant checkout."""

    required = {
        "base_ref",
        "base_ref_sha",
        "merge_base_sha",
        "head_sha",
        "files",
        "digest",
    }
    if not isinstance(record, dict) or set(record) != required:
        raise ContractError("acceptance source/change record has invalid fields")
    base_ref = record.get("base_ref")
    if base_ref != "origin/dev":
        raise ContractError("acceptance source/change record must use origin/dev")
    expected = source_change_record(
        repository,
        base_ref=base_ref,
        base_sha=record.get("base_ref_sha"),
        tested_head_sha=record.get("head_sha"),
    )
    if record != expected:
        raise ContractError("acceptance result is stale for the recorded B/C source scope")
    current_head = _git(repository, "rev-parse", "--verify", "HEAD^{commit}")
    _require_ancestor(
        repository,
        expected["head_sha"],
        current_head,
        subject="recorded tested source is not an ancestor of the current HEAD",
    )
    disallowed = [
        path
        for path in current_changed_files(repository, base_sha=expected["head_sha"])
        if path not in EVIDENCE_ONLY_PATHS
    ]
    if disallowed:
        raise ContractError(
            "current HEAD/worktree is not an evidence-only descendant of the tested source; "
            f"paths={disallowed}"
        )
    return record


def validate_generated_traceability_paths(repository: Path) -> None:
    """Require each generated evidence path to be a local regular non-executable file."""

    repository = repository.resolve()
    current_head = _git(repository, "rev-parse", "--verify", "HEAD^{commit}")
    for relative in sorted(GENERATED_TRACEABILITY_PATHS):
        path = repository / relative
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise ContractError(f"generated V6 traceability path is missing: {relative}") from exc
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o111:
            raise ContractError(
                f"generated V6 traceability path must be a non-executable regular file: {relative}"
            )
        listing = _git(repository, "ls-tree", current_head, "--", relative)
        if listing and not listing.startswith("100644 blob "):
            raise ContractError(
                f"committed V6 traceability path must use Git mode 100644: {relative}"
            )


def _canonical_administrator_acceptance_path(repository: Path, path: Path) -> Path:
    repository = repository.resolve()
    canonical = repository / ADMINISTRATOR_ACCEPTANCE_RECORD_PATH
    if path.expanduser().resolve() != canonical.resolve():
        raise ContractError(
            "administrator acceptance must use the canonical repository record path"
        )
    try:
        metadata = canonical.lstat()
    except FileNotFoundError as exc:
        raise ContractError("administrator acceptance record is missing") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o111:
        raise ContractError(
            "administrator acceptance record must be a non-executable regular file"
        )
    listing = _git(repository, "ls-tree", "HEAD", "--", ADMINISTRATOR_ACCEPTANCE_RECORD_PATH)
    if listing and not listing.startswith("100644 blob "):
        raise ContractError("committed administrator acceptance record must use Git mode 100644")
    return canonical


def _validate_recorded_at(value: Any) -> None:
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise ContractError("administrator acceptance recorded_at must be RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("administrator acceptance recorded_at must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise ContractError("administrator acceptance recorded_at requires a timezone")


def independent_review_digest(review: dict[str, Any]) -> str:
    """Bind the complete deterministic independent-review projection."""

    return sha256_bytes(canonical_json(review))


def validate_administrator_acceptance_record(
    path: Path,
    *,
    repository: Path,
    acceptance_result: dict[str, Any],
    acceptance_result_sha256: str,
    independent_review: dict[str, Any],
) -> dict[str, Any]:
    """Validate an explicit administrator record against exact B/C and review evidence."""

    canonical = _canonical_administrator_acceptance_path(repository, path)
    record = load_json(canonical)
    if not isinstance(record, dict) or set(record) != _ADMINISTRATOR_ACCEPTANCE_FIELDS:
        raise ContractError("administrator acceptance record has invalid fields")
    if canonical.read_bytes() != dump_json(record):
        raise ContractError("administrator acceptance record must use canonical JSON encoding")
    source = acceptance_result.get("source_change")
    if not isinstance(source, dict):
        raise ContractError("administrator acceptance lacks a source/change result binding")
    spec_hash = canonical_spec_hash(repository / "docs/nm-v6-workflow-spec.md")
    expected = {
        "schema_version": ADMINISTRATOR_ACCEPTANCE_SCHEMA_VERSION,
        "decision": "accepted",
        "spec_id": "SPEC-NM-WORKFLOW-V6-V1",
        "spec_version": 1,
        "spec_hash": spec_hash,
        "source_change_digest": source.get("digest"),
        "base_sha": source.get("base_ref_sha"),
        "head_sha": source.get("head_sha"),
        "acceptance_result_sha256": acceptance_result_sha256,
        "independent_review_sha256": independent_review_digest(independent_review),
        "recommended": False,
        "production_ready": False,
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise ContractError(
                f"administrator acceptance record has a stale or invalid {field} binding"
            )
    if acceptance_result.get("result") != "passed":
        raise ContractError("administrator acceptance requires a passing machine result")
    if independent_review.get("status") != "pass":
        raise ContractError("administrator acceptance requires a passing independent review")
    _validate_recorded_at(record.get("recorded_at"))
    authority_basis = record.get("authority_basis")
    if (
        not isinstance(authority_basis, str)
        or authority_basis != authority_basis.strip()
        or not authority_basis
        or len(authority_basis) > 512
        or "\n" in authority_basis
        or "\r" in authority_basis
    ):
        raise ContractError(
            "administrator acceptance authority_basis must be a bounded single line"
        )
    return record


def administrator_acceptance_binding(
    path: Path,
    *,
    repository: Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Return the exact manifest projection for a validated administrator record."""

    canonical = _canonical_administrator_acceptance_path(repository, path)
    return {
        "record_path": ADMINISTRATOR_ACCEPTANCE_RECORD_PATH,
        "record_sha256": sha256_file(canonical),
        "recorded_at": record["recorded_at"],
        "authority_basis": record["authority_basis"],
        "recommended": False,
        "production_ready": False,
    }


def validate_acceptance_result(record: dict[str, Any], *, repository: Path) -> dict[str, Any]:
    """Validate an actual unittest result against the current source and inventory."""

    if record.get("schema_version") != "nm-v6/acceptance-result-v2":
        raise ContractError("unsupported acceptance-result schema")
    spec_hash = canonical_spec_hash(repository / "docs/nm-v6-workflow-spec.md")
    if record.get("spec_hash") != spec_hash:
        raise ContractError("acceptance result is bound to another V6 Spec")
    source = record.get("source_change")
    if not isinstance(source, dict):
        raise ContractError("acceptance result lacks its source/change binding")
    validate_source_change_record(source, repository=repository)
    command = record.get("command")
    if not isinstance(command, dict):
        raise ContractError("acceptance result lacks its command binding")
    expected_command_digest = sha256_bytes(canonical_json(command))
    if record.get("command_digest") != expected_command_digest:
        raise ContractError("acceptance result command digest mismatch")
    argv = command.get("argv")
    pattern = command.get("pattern")
    if (
        not isinstance(argv, list)
        or "acceptance-test" not in argv
        or command.get("target") != "."
        or not isinstance(pattern, str)
        or pattern != "test*.py"
    ):
        raise ContractError("acceptance result command is not the mandatory full suite")
    inventory = discover_test_inventory(repository, pattern=pattern)
    if record.get("test_inventory") != inventory:
        raise ContractError("acceptance result test inventory is stale or incomplete")
    outcomes = record.get("test_outcomes")
    if not isinstance(outcomes, dict) or set(outcomes) != set(inventory["selectors"]):
        raise ContractError("acceptance result must record exactly one outcome per discovered test")
    allowed = {"pass", "fail", "error", "skip", "expected_failure", "unexpected_success"}
    if any(status not in allowed for status in outcomes.values()):
        raise ContractError("acceptance result contains an unknown test outcome")
    counts = {status: sum(value == status for value in outcomes.values()) for status in sorted(allowed)}
    summary = record.get("summary")
    if not isinstance(summary, dict) or summary != {"tests_run": len(outcomes), **counts}:
        raise ContractError("acceptance result summary does not match per-test outcomes")
    expected_result = "passed" if set(outcomes.values()) == {"pass"} else "failed"
    if record.get("result") != expected_result:
        raise ContractError("acceptance result incorrectly classifies a failure/error/mandatory skip")
    return record


def validate_bilingual_review(repository: Path, *, spec_hash: str) -> dict[str, Any]:
    english_spec = repository / "docs/nm-v6-workflow-spec.md"
    chinese_spec = repository / "docs/nm-v6-workflow-spec.zh-CN.md"
    english_review = repository / "docs/nm-v6-bilingual-semantic-review.md"
    chinese_review = repository / "docs/nm-v6-bilingual-semantic-review.zh-CN.md"
    for path in (english_spec, chinese_spec, english_review, chinese_review):
        if not path.is_file():
            raise ContractError(f"V6-AC-044 review input is missing: {path}")
    english_spec_sha = sha256_file(english_spec)
    chinese_spec_sha = sha256_file(chinese_spec)
    english_text = english_review.read_text(encoding="utf-8")
    chinese_text = chinese_review.read_text(encoding="utf-8")
    for text in (english_text, chinese_text):
        if spec_hash not in text or english_spec_sha not in text or chinese_spec_sha not in text:
            raise ContractError("V6-AC-044 review is stale for the current bilingual Spec files")
    if "**pass**" not in english_text.lower() or "**通过**" not in chinese_text:
        raise ContractError("V6-AC-044 independent review does not record a pass")
    reviewer = re.search(r"^- Reviewer: `([^`]+)`", english_text, re.MULTILINE)
    if reviewer is None or not reviewer.group(1).strip():
        raise ContractError("V6-AC-044 independent review lacks reviewer identity")
    return {
        "status": "pass",
        "reviewer": reviewer.group(1),
        "spec_hash": spec_hash,
        "english_spec_sha256": english_spec_sha,
        "chinese_spec_sha256": chinese_spec_sha,
        "files": {
            english_review.relative_to(repository).as_posix(): sha256_file(english_review),
            chinese_review.relative_to(repository).as_posix(): sha256_file(chinese_review),
        },
    }


def validate_static_traceability(
    spec_path: Path,
    *,
    acceptance: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, int]:
    """Prove every Decision/Invariant reaches executable discovered evidence."""

    coverage = spec_traceability(spec_path)
    for source_kind in ("decisions", "invariants"):
        for source_id, requirements in coverage[source_kind].items():
            executable = False
            for requirement in requirements:
                for acceptance_id in coverage["requirements"][requirement]:
                    record = acceptance.get(acceptance_id)
                    tests = record.get("tests") if isinstance(record, dict) else None
                    if not isinstance(tests, list):
                        continue
                    for selector in tests:
                        validate_test_selector(selector, inventory=inventory)
                    if tests:
                        executable = True
            if not executable:
                raise ContractError(f"{source_id} does not reach executable Acceptance evidence")
    return {
        "decisions": len(coverage["decisions"]),
        "invariants": len(coverage["invariants"]),
        "requirements": len(coverage["requirements"]),
        "acceptance": len(AC_IDS),
    }


def validate_changed_file_mapping(
    manifest: dict[str, Any],
    *,
    changed_files: list[str],
    ignored_prefixes: tuple[str, ...] = (),
) -> None:
    """Require exact bidirectional changed-file coverage with no stale entries."""

    file_map = manifest.get("files")
    if not isinstance(file_map, dict):
        raise ContractError("acceptance manifest requires a files mapping")
    scoped = {
        path
        for path in changed_files
        if not path.startswith(ignored_prefixes)
    }
    if set(file_map) != scoped:
        raise ContractError(
            "changed-file mapping is not bidirectional; "
            f"missing={sorted(scoped - set(file_map))}, stale={sorted(set(file_map) - scoped)}"
        )
    for path, links in file_map.items():
        if not isinstance(links, list) or not links or not all(REQ_PATTERN.fullmatch(item) for item in links):
            raise ContractError(f"changed implementation file lacks Requirement mapping: {path}")


def _requirement_evidence(
    *,
    acceptance: dict[str, Any],
    files: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    return {
        requirement: {
            "acceptance": sorted(
                acceptance_id
                for acceptance_id, record in acceptance.items()
                if requirement in record["requirements"]
            ),
            "files": sorted(path for path, requirements in files.items() if requirement in requirements),
        }
        for requirement in sorted(REQ_IDS)
    }


def validate_acceptance_manifest(
    path: Path,
    *,
    repository: Path,
    require_passed: bool = True,
) -> dict[str, Any]:
    validate_generated_traceability_paths(repository)
    manifest = load_json(path)
    if not isinstance(manifest, dict):
        raise ContractError("acceptance manifest must be a JSON object")
    if manifest.get("schema_version") != "nm-v6/acceptance-manifest-v2":
        raise ContractError("unsupported acceptance-manifest schema")
    expected_manifest_fields = {
        "schema_version",
        "spec_id",
        "spec_version",
        "spec_hash",
        "implementation_status",
        "administrator_acceptance",
        "evidence",
        "acceptance",
        "files",
        "requirements",
        "file_scope",
    }
    if set(manifest) != expected_manifest_fields:
        raise ContractError("acceptance manifest has incomplete or unknown fields")
    if (
        manifest.get("spec_id") != "SPEC-NM-WORKFLOW-V6-V1"
        or manifest.get("spec_version") != 1
    ):
        raise ContractError("acceptance manifest targets another Spec version")
    implementation_status = manifest.get("implementation_status")
    administrator_acceptance = manifest.get("administrator_acceptance")
    if (implementation_status, administrator_acceptance) not in {
        ("acceptance-candidate", "pending"),
        ("accepted", "accepted"),
    }:
        raise ContractError("acceptance manifest has an invalid implementation/acceptance state")
    acceptance = manifest.get("acceptance")
    if not isinstance(acceptance, dict) or set(acceptance) != AC_IDS:
        raise ContractError("acceptance manifest must cover every V6 Acceptance ID exactly once")
    spec_path = repository / "docs/nm-v6-workflow-spec.md"
    spec_hash = canonical_spec_hash(spec_path)
    if manifest.get("spec_hash") != spec_hash:
        raise ContractError("acceptance manifest is bound to another V6 Spec")
    evidence = manifest.get("evidence")
    automated = evidence.get("automated") if isinstance(evidence, dict) else None
    if not isinstance(automated, dict) or not isinstance(automated.get("result"), dict):
        raise ContractError("acceptance manifest lacks machine acceptance evidence")
    expected_evidence_fields = {"automated", "independent_review"}
    if implementation_status == "accepted":
        expected_evidence_fields.add("administrator_acceptance")
    if not isinstance(evidence, dict) or set(evidence) != expected_evidence_fields:
        raise ContractError("acceptance manifest evidence fields do not match its state")
    result = automated["result"]
    canonical_result = dump_json(result)
    if automated.get("result_file_sha256") != sha256_bytes(canonical_result):
        raise ContractError("acceptance result file digest is not bound to its embedded record")
    digest_binding = automated.get("digest_binding")
    expected_binding = {
        "schema_version": "nm-v6/acceptance-result-digest-v1",
        "result_file_sha256": sha256_bytes(canonical_result),
        "spec_hash": result.get("spec_hash"),
        "source_change_digest": (result.get("source_change") or {}).get("digest"),
        "test_inventory_digest": (result.get("test_inventory") or {}).get("digest"),
        "command_digest": result.get("command_digest"),
    }
    if digest_binding != expected_binding:
        raise ContractError("acceptance result digest binding is incomplete or stale")
    validate_acceptance_result(result, repository=repository)
    if require_passed and result.get("result") != "passed":
        raise ContractError("mandatory V6 acceptance suite contains a non-passing test outcome")
    inventory = result["test_inventory"]
    outcomes = result["test_outcomes"]
    expected_requirements = acceptance_requirement_map(spec_path)
    review = validate_bilingual_review(repository, spec_hash=spec_hash)
    if evidence.get("independent_review") != review:
        raise ContractError("acceptance manifest independent-review evidence is stale")
    if implementation_status == "accepted":
        record_path = repository / ADMINISTRATOR_ACCEPTANCE_RECORD_PATH
        record = validate_administrator_acceptance_record(
            record_path,
            repository=repository,
            acceptance_result=result,
            acceptance_result_sha256=automated["result_file_sha256"],
            independent_review=review,
        )
        expected_administrator_binding = administrator_acceptance_binding(
            record_path,
            repository=repository,
            record=record,
        )
        if evidence.get("administrator_acceptance") != expected_administrator_binding:
            raise ContractError("administrator acceptance manifest binding is stale")
    for acceptance_id, record in acceptance.items():
        if not AC_PATTERN.fullmatch(acceptance_id) or not isinstance(record, dict):
            raise ContractError(f"invalid acceptance entry: {acceptance_id}")
        if record.get("requirements") != expected_requirements[acceptance_id]:
            raise ContractError(f"Acceptance-to-Requirement links differ from Spec: {acceptance_id}")
        tests = record.get("tests")
        if not isinstance(tests, list) or not tests or len(tests) != len(set(tests)):
            raise ContractError(f"automated acceptance lacks unique tests: {acceptance_id}")
        if acceptance_id == "V6-AC-044":
            if record.get("independent_review") != review:
                raise ContractError(
                    "V6-AC-044 must combine automated structure evidence with the current independent review"
                )
        elif "independent_review" in record:
            raise ContractError(f"unexpected independent-review evidence: {acceptance_id}")
        for selector in tests:
            validate_test_selector(selector, inventory=inventory)
        selector_statuses = [outcomes[selector] for selector in tests]
        expected_status = (
            "pass"
            if all(status == "pass" for status in selector_statuses)
            else "fail"
            if any(status in {"fail", "error", "unexpected_success"} for status in selector_statuses)
            else "not_run"
        )
        if record.get("status") != expected_status:
            raise ContractError(f"acceptance status is not derived from actual test outcomes: {acceptance_id}")
        if require_passed and expected_status != "pass":
            raise ContractError(f"mandatory Acceptance evidence is not passing: {acceptance_id}")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ContractError("acceptance manifest lacks implementation-file mapping")
    source = result["source_change"]
    changed_files = current_changed_files(
        repository,
        base_ref=source["base_ref"],
        base_sha=source["base_ref_sha"],
    )
    validate_changed_file_mapping(manifest, changed_files=changed_files)
    if {requirement for links in files.values() for requirement in links} != REQ_IDS:
        raise ContractError("implementation files do not map every V6 Requirement")
    expected_requirement_evidence = _requirement_evidence(acceptance=acceptance, files=files)
    if manifest.get("requirements") != expected_requirement_evidence:
        raise ContractError("Requirement-to-file/passing-evidence projection is stale")
    for requirement, record in expected_requirement_evidence.items():
        if not record["files"] or not record["acceptance"]:
            raise ContractError(f"Requirement lacks files or Acceptance evidence: {requirement}")
        if require_passed and not all(acceptance[item]["status"] == "pass" for item in record["acceptance"]):
            raise ContractError(f"Requirement evidence contains non-passing Acceptance: {requirement}")
    file_scope = manifest.get("file_scope")
    expected_file_scope = {
        "base_ref": source["base_ref"],
        "merge_base_sha": source["merge_base_sha"],
        "changed_files_digest": sha256_bytes(canonical_json(sorted(files))),
    }
    if file_scope != expected_file_scope:
        raise ContractError("acceptance changed-file scope binding is stale")
    validate_static_traceability(spec_path, acceptance=acceptance, inventory=inventory)
    return manifest


def render_traceability_markdown(manifest: dict[str, Any], *, chinese: bool = False) -> str:
    implementation_status = manifest.get("implementation_status", "acceptance-candidate")
    administrator_status = manifest.get("administrator_acceptance", "pending")
    administrator_binding = (manifest.get("evidence") or {}).get(
        "administrator_acceptance"
    )
    if chinese:
        lines = [
            "# NM V6 实现追踪报告",
            "",
            "[English](nm-v6-implementation-traceability.md) | 中文",
            "",
            f"Spec hash：`{manifest['spec_hash']}`",
            f"实现状态：`{implementation_status}`",
            f"管理员接受：`{administrator_status}`",
            "推荐状态：`false`",
            "生产就绪：`false`",
            "",
            "本报告由机器验收结果与 `tools/nm-v6/acceptance-manifest.json` 确定性生成。它记录实现证据，不替代管理员接受，也不把 V6 标为推荐或生产就绪。",
            "",
            "## 验收证据",
            "",
            "| 验收项 | Requirement | 证据 | 状态 |",
            "| --- | --- | --- | --- |",
        ]
    else:
        lines = [
            "# NM V6 Implementation Traceability",
            "",
            "English | [中文](nm-v6-implementation-traceability.zh-CN.md)",
            "",
            f"Spec hash: `{manifest['spec_hash']}`",
            f"Implementation status: `{implementation_status}`",
            f"Administrator acceptance: `{administrator_status}`",
            "Recommended: `false`",
            "Production-ready: `false`",
            "",
            "This report is generated deterministically from the machine acceptance result and `tools/nm-v6/acceptance-manifest.json`. It records implementation evidence; it does not replace administrator acceptance or make V6 recommended or production-ready.",
            "",
            "## Acceptance evidence",
            "",
            "| Acceptance | Requirements | Evidence | Status |",
            "| --- | --- | --- | --- |",
        ]
    if administrator_status == "accepted" and isinstance(administrator_binding, dict):
        record_line = (
            f"管理员接受记录：`{administrator_binding['record_path']}` "
            f"(`{administrator_binding['record_sha256']}`)"
            if chinese
            else f"Administrator acceptance record: `{administrator_binding['record_path']}` "
            f"(`{administrator_binding['record_sha256']}`)"
        )
        acceptance_heading = "## 验收证据" if chinese else "## Acceptance evidence"
        heading_index = lines.index(acceptance_heading)
        lines[heading_index:heading_index] = [record_line, ""]
    for acceptance_id, record in sorted(manifest["acceptance"].items()):
        requirements = ", ".join(f"`{item}`" for item in record["requirements"])
        if acceptance_id == "V6-AC-044":
            evidence = (
                "<br>".join(f"`{item}`" for item in record["tests"])
                + "<br>independent bilingual semantic review"
            )
        else:
            evidence = "<br>".join(f"`{item}`" for item in record["tests"])
        lines.append(f"| `{acceptance_id}` | {requirements} | {evidence} | `{record['status']}` |")
    lines.extend(
        [
            "",
            "## " + ("机器证据绑定" if chinese else "Machine evidence binding"),
            "",
            f"- Result file SHA-256: `{manifest['evidence']['automated']['result_file_sha256']}`",
            f"- Source/change digest: `{manifest['evidence']['automated']['result']['source_change']['digest']}`",
            f"- Test inventory digest: `{manifest['evidence']['automated']['result']['test_inventory']['digest']}`",
            f"- Command digest: `{manifest['evidence']['automated']['result']['command_digest']}`",
            "",
            "## " + ("Requirement 覆盖" if chinese else "Requirement coverage"),
            "",
            (
                "| Requirement | 实现文件 | 通过的验收证据 |"
                if chinese
                else "| Requirement | Implementation files | Passing Acceptance evidence |"
            ),
            "| --- | --- | --- |",
        ]
    )
    for requirement, record in sorted(manifest["requirements"].items()):
        files = "<br>".join(f"`{path}`" for path in record["files"])
        evidence = "<br>".join(
            f"`{acceptance_id}` (`{manifest['acceptance'][acceptance_id]['status']}`)"
            for acceptance_id in record["acceptance"]
        )
        lines.append(f"| `{requirement}` | {files} | {evidence} |")
    lines.extend(
        [
            "",
            "## " + ("实现文件" if chinese else "Implementation files"),
            "",
            "| " + ("文件" if chinese else "File") + " | Requirements |",
            "| --- | --- |",
        ]
    )
    for path, requirements in sorted(manifest["files"].items()):
        lines.append(f"| `{path}` | {', '.join(f'`{item}`' for item in requirements)} |")
    return "\n".join(lines) + "\n"
