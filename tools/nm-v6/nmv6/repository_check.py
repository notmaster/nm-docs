"""Repository-level static checks required by the V6 implementation Spec."""

from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Any

from .contracts import validate_project_config
from .errors import ContractError
from .specs import canonical_spec_hash
from .supply_chain import (
    validate_bilingual_pair,
    validate_dependency_constraints,
    validate_legacy_preservation,
    validate_schema_catalog,
    validate_template_manifest,
)
from .traceability import (
    ADMINISTRATOR_ACCEPTANCE_RECORD_PATH,
    render_traceability_markdown,
    validate_acceptance_manifest,
    validate_implementation_plan,
)
from .util import load_json, sha256_file


EXPECTED_SPEC_HASH = "62196ab27c2be08ea1c716081903a009185f1d518ba7a53ed9b3d8485236cb7f"
ID_PREFIXES = ("V6-DEC", "V6-INV", "V6-REQ", "V6-AC")


def _all_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store"
    }


def _check_manifest(repository: Path) -> dict[str, Any]:
    plan = validate_template_manifest(
        repository / "template/v6/manifest.json",
        repository_root=repository,
    )
    targets = {entry["target"] for entry in plan["entries"]}
    return {
        "templates": len(plan["entries"]),
        "targets": len(targets),
        "manifest_sha256": plan["manifest_sha256"],
    }


def _extract_ids(path: Path) -> dict[str, set[str]]:
    text = path.read_text(encoding="utf-8")
    return {
        prefix: set(re.findall(rf"`({re.escape(prefix)}-[0-9]{{3}})`", text))
        for prefix in ID_PREFIXES
    }


def _markdown_structure(path: Path) -> dict[str, tuple[Any, ...]]:
    """Extract translation-independent Markdown heading and list structure."""

    headings: list[int] = []
    list_items: list[tuple[int, str]] = []
    fence_marker: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        fence = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)[0]
            if fence_marker is None:
                fence_marker = marker
            elif fence_marker == marker:
                fence_marker = None
            continue
        if fence_marker is not None:
            continue
        heading = re.match(r"^(#{1,6})[ \t]+\S", line)
        if heading:
            headings.append(len(heading.group(1)))
        list_item = re.match(r"^([ \t]*)([-+*]|[0-9]+[.)])[ \t]+\S", line)
        if list_item:
            indentation = len(list_item.group(1).expandtabs(4))
            kind = "unordered" if list_item.group(2) in {"-", "+", "*"} else "ordered"
            list_items.append((indentation, kind))
    return {"headings": tuple(headings), "lists": tuple(list_items)}


def _validate_markdown_structure(english: Path, chinese: Path) -> None:
    english_structure = _markdown_structure(english)
    chinese_structure = _markdown_structure(chinese)
    if english_structure["headings"] != chinese_structure["headings"]:
        raise ContractError(
            f"bilingual Markdown heading hierarchy differs for {english} / {chinese}"
        )
    if english_structure["lists"] != chinese_structure["lists"]:
        raise ContractError(
            f"bilingual Markdown list structure differs for {english} / {chinese}"
        )


def _workflow_bilingual_pairs(repository: Path) -> list[tuple[Path, Path]]:
    workflow_root = repository / "template/v6/0c-workflow"
    if not workflow_root.is_dir():
        raise ContractError(f"V6 workflow documentation directory is missing: {workflow_root}")
    markdown_files = sorted(
        (path for path in workflow_root.rglob("*.md") if path.is_file()),
        key=lambda path: path.relative_to(workflow_root).as_posix(),
    )
    pairs: list[tuple[Path, Path]] = []
    for path in markdown_files:
        if path.name.endswith(".zh-CN.md"):
            english = path.with_name(
                path.name[: -len(".zh-CN.md")] + ".md"
            )
            if not english.is_file():
                raise ContractError(f"missing bilingual pair: {english} / {path}")
            continue
        chinese = path.with_name(f"{path.stem}.zh-CN.md")
        if not chinese.is_file():
            raise ContractError(f"missing bilingual pair: {path} / {chinese}")
        pairs.append((path, chinese))
    return pairs


def _check_bilingual(repository: Path) -> dict[str, Any]:
    english_spec = repository / "docs/nm-v6-workflow-spec.md"
    chinese_spec = repository / "docs/nm-v6-workflow-spec.zh-CN.md"
    pairs = [
        (english_spec, chinese_spec),
        (repository / "AGENTS.md", repository / "AGENTS.zh-CN.md"),
        (repository / "README.md", repository / "docs/README.zh-CN.md"),
        (repository / "docs/template-versions.md", repository / "docs/template-versions.zh-CN.md"),
        (repository / "docs/installation.md", repository / "docs/installation.zh-CN.md"),
        (repository / "template/v6/AGENTS.md", repository / "template/v6/AGENTS.zh-CN.md"),
        (
            repository / "docs/nm-v6-bilingual-semantic-review.md",
            repository / "docs/nm-v6-bilingual-semantic-review.zh-CN.md",
        ),
        (
            repository / "docs/nm-v6-implementation-traceability.md",
            repository / "docs/nm-v6-implementation-traceability.zh-CN.md",
        ),
    ]
    workflow_pairs = _workflow_bilingual_pairs(repository)
    pairs.extend(workflow_pairs)
    for english, chinese in pairs:
        validate_bilingual_pair(english, chinese)
        _validate_markdown_structure(english, chinese)
    en_ids = _extract_ids(english_spec)
    zh_ids = _extract_ids(chinese_spec)
    if en_ids != zh_ids:
        raise ContractError("English and Chinese V6 Spec stable-ID sets differ")
    expected_counts = {"V6-DEC": 9, "V6-INV": 16, "V6-REQ": 24, "V6-AC": 60}
    observed = {prefix: len(values) for prefix, values in en_ids.items()}
    if observed != expected_counts:
        raise ContractError(f"unexpected V6 Spec stable-ID counts: {observed}")
    return {
        "stable_ids": observed,
        "pairs": len(pairs),
        "workflow_pairs": len(workflow_pairs),
    }


def _check_core_sync(repository: Path) -> None:
    source = repository / "tools/nm-v6/nmv6"
    vendored = repository / "template/v6/0d-scripts/nmv6"
    if _all_files(source) != _all_files(vendored):
        raise ContractError("vendored V6 core file set differs from tools/nm-v6/nmv6")
    for relative in _all_files(source):
        if (source / relative).read_bytes() != (vendored / relative).read_bytes():
            raise ContractError(f"vendored V6 core is stale: {relative}")
    schemas = repository / "tools/nm-v6/schemas"
    vendored_schemas = repository / "template/v6/0c-workflow/schemas"
    if _all_files(schemas) != _all_files(vendored_schemas):
        raise ContractError("vendored V6 schema file set differs")
    for relative in _all_files(schemas):
        if (schemas / relative).read_bytes() != (vendored_schemas / relative).read_bytes():
            raise ContractError(f"vendored V6 schema is stale: {relative}")


def _check_skill(repository: Path, target: Path) -> dict[str, Any]:
    skill = target.resolve()
    content = (skill / "SKILL.md").read_text(encoding="utf-8")
    if not content.startswith("---\n") or "name: nm-init-project-v6" not in content:
        raise ContractError("V6 Skill has invalid frontmatter or name")
    if "TODO" in content:
        raise ContractError("V6 Skill contains unresolved TODO markers")
    frontmatter = content.split("---\n", 2)[1]
    keys = [line.split(":", 1)[0] for line in frontmatter.splitlines() if ":" in line]
    if keys != ["name", "description"]:
        raise ContractError("V6 Skill frontmatter may contain only name and description")
    wrapper = (skill / "scripts/run_nm_v6.py").read_text(encoding="utf-8")
    if "urlopen" in wrapper or "requests" in wrapper or "curl" in wrapper:
        raise ContractError("V6 Skill wrapper must not download unchecked executable code")
    if "tools\" / \"nm-v6\" / \"nm_v6.py" not in wrapper:
        raise ContractError("V6 Skill wrapper must delegate to the repository CLI")
    if "Path.cwd" in wrapper or 'Path.home() / "code"' in wrapper:
        raise ContractError("V6 Skill wrapper must not discover executable code from CWD or guessed paths")
    if (
        '"source-binding.json"' not in wrapper
        or '"-I"' not in wrapper
        or "runpy.run_path" not in wrapper
    ):
        raise ContractError("V6 Skill wrapper must enforce its source binding and isolated Python mode")
    binding_path = skill / "source-binding.json"
    binding_checked = False
    if binding_path.exists():
        if binding_path.is_symlink() or stat.S_IMODE(binding_path.stat().st_mode) != 0o600:
            raise ContractError("installed V6 Skill source binding must be a regular mode-0600 file")
        binding = load_json(binding_path)
        if not isinstance(binding, dict) or set(binding) != {
            "schema_version",
            "source_root",
            "files",
        }:
            raise ContractError("installed V6 Skill source binding fields are incomplete or unknown")
        if binding.get("schema_version") != "nm-v6/skill-source-binding-v1":
            raise ContractError("installed V6 Skill source binding version is unsupported")
        source_root = Path(str(binding.get("source_root", ""))).expanduser().resolve()
        if source_root != repository.resolve():
            raise ContractError("installed V6 Skill is bound to another checkout")
        files = binding.get("files")
        required = {
            "docs/nm-v6-workflow-spec.md",
            "template/v6/manifest.json",
            "tools/nm-v6/nm_v6.py",
        }
        if not isinstance(files, dict) or not required.issubset(files):
            raise ContractError("installed V6 Skill source binding lacks required files")
        actual = set(required)
        for directory in (
            source_root / "tools/nm-v6",
            source_root / "skills/nm-init-project-v6",
        ):
            for path in directory.rglob("*"):
                if (
                    path.is_file()
                    and "__pycache__" not in path.parts
                    and path.suffix != ".pyc"
                    and path.name != "source-binding.json"
                ):
                    actual.add(path.relative_to(source_root).as_posix())
        if set(files) != actual:
            raise ContractError("installed V6 Skill source inventory drifted")
        for relative, expected in files.items():
            if (
                not isinstance(relative, str)
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not isinstance(expected, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected)
            ):
                raise ContractError("installed V6 Skill source binding path or digest is invalid")
            raw_source = source_root / relative
            source = raw_source.resolve()
            try:
                source.relative_to(source_root)
            except ValueError as exc:
                raise ContractError("installed V6 Skill source binding escapes its checkout") from exc
            if raw_source.is_symlink() or not source.is_file() or sha256_file(source) != expected:
                raise ContractError(f"installed V6 Skill source binding drifted: {relative}")
        binding_checked = True
    return {
        "result": "passed",
        "files": len(_all_files(skill)),
        "source_binding": "verified" if binding_checked else "source-tree",
    }


def check_skill(repository: Path, target: Path) -> dict[str, Any]:
    return _check_skill(repository, target)


def check_repository(repository: Path) -> dict[str, Any]:
    repository = repository.resolve()
    for version in range(1, 6):
        if not (repository / f"template/v{version}").is_dir():
            raise ContractError(f"preserved template/v{version} is missing")
    readme = (repository / "README.md").read_text(encoding="utf-8").lower()
    if "v5" not in readme or "experimental" not in readme:
        raise ContractError("V5 must remain visibly experimental")
    actual_hash = canonical_spec_hash(repository / "docs/nm-v6-workflow-spec.md")
    if actual_hash != EXPECTED_SPEC_HASH:
        raise ContractError(f"canonical V6 Spec hash changed unexpectedly: {actual_hash}")
    validate_project_config(load_json(repository / "template/v6/project.example.json"))
    dependency_result = {
        "repository": validate_dependency_constraints(repository),
        "template": validate_dependency_constraints(
            repository / "template/v6",
            require_lock=False,
        ),
    }
    schema_result = validate_schema_catalog(repository / "tools/nm-v6/schemas")
    legacy_result = validate_legacy_preservation(repository)
    plan = validate_implementation_plan(repository / "tools/nm-v6/implementation-plan.json")
    acceptance = validate_acceptance_manifest(
        repository / "tools/nm-v6/acceptance-manifest.json",
        repository=repository,
    )
    expected_record = (
        ADMINISTRATOR_ACCEPTANCE_RECORD_PATH
        if acceptance["administrator_acceptance"] == "accepted"
        else None
    )
    if (
        plan.get("status") != acceptance.get("implementation_status")
        or plan.get("administrator_acceptance")
        != acceptance.get("administrator_acceptance")
        or plan.get("administrator_acceptance_record") != expected_record
        or plan.get("recommended") is not False
        or plan.get("production_ready") is not False
    ):
        raise ContractError(
            "V6 implementation plan and acceptance manifest status are inconsistent"
        )
    reports = (
        (
            repository / "docs/nm-v6-implementation-traceability.md",
            render_traceability_markdown(acceptance, chinese=False),
        ),
        (
            repository / "docs/nm-v6-implementation-traceability.zh-CN.md",
            render_traceability_markdown(acceptance, chinese=True),
        ),
    )
    for path, expected in reports:
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            raise ContractError(f"generated V6 traceability report is stale: {path}")
    manifest_result = _check_manifest(repository)
    bilingual_result = _check_bilingual(repository)
    _check_core_sync(repository)
    skill_result = _check_skill(repository, repository / "skills/nm-init-project-v6")
    if plan.get("spec_hash") != actual_hash or acceptance.get("spec_hash") != actual_hash:
        raise ContractError("V6 implementation/acceptance traceability uses the wrong Spec hash")
    return {
        "schema_version": "nm-v6/repository-check-v1",
        "result": "passed",
        "spec_hash": actual_hash,
        "manifest": manifest_result,
        "dependencies": dependency_result,
        "schemas": {"count": len(schema_result)},
        "legacy": legacy_result,
        "bilingual": bilingual_result,
        "skill": skill_result,
        "acceptance_tests": acceptance["evidence"]["automated"]["result"]["summary"],
    }
