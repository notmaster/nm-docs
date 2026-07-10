"""Static manifest, bilingual, legacy, dependency, and artifact controls."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from .contracts import validate_project_config, validate_version_record
from .errors import ContractError
from .specs import parse_frontmatter
from .util import ensure_relative_path, load_json, sha256_bytes, sha256_file


PINNED_NODE_VERSION_RE = re.compile(
    r"^(?:[~^]|>=?|<=?)?[0-9]+(?:\.[0-9xX*]+){0,2}(?:[-+][A-Za-z0-9.-]+)?(?:\s+<\s*[0-9][^\s]*)?$"
)
PYTHON_PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s;]+(?:\s*;.+)?$")
SEMANTIC_ID_RE = re.compile(r"\b(?:V6-(?:DEC|INV|REQ|AC)-[0-9]{3}|(?:GOAL|REQ|AC|DEC|PHASE|TASK)-[0-9]{3})\b")
CREDENTIAL_ENV_RE = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE_KEY|WEBHOOK|API_KEY)",
    re.IGNORECASE,
)
V5_RUNTIME_PATHS = (
    "0b-runtime/INDEX.yaml",
    "0b-runtime/issues-ledger.md",
    "0b-runtime/tasks",
)
MANIFEST_SPEC_ID = "SPEC-NM-WORKFLOW-V6-V1"
MANIFEST_SPEC_HASH = "62196ab27c2be08ea1c716081903a009185f1d518ba7a53ed9b3d8485236cb7f"
CONFIGURED_RUNTIME_EVALUATOR_VERSION = "nm-v6/configured-runtime-gates-v1"
MANIFEST_TOP_LEVEL_KEYS = {
    "schemaVersion",
    "templateVersion",
    "maturity",
    "recommended",
    "productionReady",
    "specId",
    "specVersion",
    "specHash",
    "python",
    "stateFile",
    "runtimeAuthority",
    "directories",
    "templates",
    "git",
}
MANIFEST_ENTRY_KEYS = {
    "target",
    "source",
    "sourceSha256",
    "policy",
    "mode",
    "mergeRoots",
}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _manifest_source_path(
    source: str,
    *,
    template_root: Path,
    repository_root: Path,
) -> Path:
    relative = ensure_relative_path(source, field="manifest source")
    candidate = (repository_root / relative).resolve()
    if not _inside(candidate, template_root.resolve()):
        # A compact manifest may use paths relative to template/v6.
        candidate = (template_root / relative).resolve()
    if not _inside(candidate, template_root.resolve()):
        raise ContractError(f"manifest source escapes template/v6: {source}")
    return candidate


def validate_template_manifest(
    manifest_path: Path,
    *,
    repository_root: Path | None = None,
    strict_coverage: bool = True,
) -> dict[str, Any]:
    """Validate source/target coverage and return a deterministic hash plan."""

    manifest_path = manifest_path.resolve()
    template_root = manifest_path.parent
    repository_root = (repository_root or template_root.parents[1]).resolve()
    manifest = load_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ContractError("template manifest must be a JSON object")
    missing_top_level = sorted(MANIFEST_TOP_LEVEL_KEYS - set(manifest))
    unknown_top_level = sorted(set(manifest) - MANIFEST_TOP_LEVEL_KEYS)
    if missing_top_level or unknown_top_level:
        raise ContractError(
            "template manifest fields differ; "
            f"missing={missing_top_level}, unknown={unknown_top_level}"
        )
    if manifest.get("schemaVersion") != 2:
        raise ContractError("template manifest schemaVersion must be 2")
    template_version = manifest.get("templateVersion")
    if not isinstance(template_version, str) or not template_version.startswith("6."):
        raise ContractError("template manifest must declare a V6 template version")
    if (
        manifest.get("maturity") != "accepted"
        or manifest.get("recommended") is not False
        or manifest.get("productionReady") is not False
    ):
        raise ContractError(
            "template manifest must remain accepted, non-recommended, and non-production"
        )
    if (
        manifest.get("specId") != MANIFEST_SPEC_ID
        or manifest.get("specVersion") != 1
        or manifest.get("specHash") != MANIFEST_SPEC_HASH
    ):
        raise ContractError("template manifest is bound to another V6 Spec")
    if manifest.get("python") != ">=3.11,<4":
        raise ContractError("template manifest Python constraint is not the V6 bound")
    for field in ("stateFile", "runtimeAuthority"):
        ensure_relative_path(manifest.get(field), field=f"manifest {field}")
    git = manifest.get("git")
    if not isinstance(git, Mapping) or set(git) != {
        "integrationBranch",
        "stableBranch",
        "protectedBranches",
    }:
        raise ContractError("template manifest Git policy fields are incomplete or unknown")
    if (
        git.get("integrationBranch") != "dev"
        or git.get("stableBranch") not in {"main", "master"}
        or git.get("protectedBranches") != [git.get("stableBranch"), "dev"]
    ):
        raise ContractError("template manifest Git policy is not the protected V6 topology")
    templates = manifest.get("templates")
    if not isinstance(templates, list):
        raise ContractError("template manifest templates must be an array")
    directories = manifest.get("directories", [])
    if not isinstance(directories, list):
        raise ContractError("template manifest directories must be an array")
    directory_set: set[str] = set()
    for directory in directories:
        relative = ensure_relative_path(directory, field="manifest directory")
        if relative in directory_set:
            raise ContractError(f"duplicate manifest directory: {relative}")
        directory_set.add(relative)

    target_paths: set[str] = set()
    source_paths: set[str] = set()
    plan: list[dict[str, Any]] = []
    for index, entry in enumerate(templates):
        if not isinstance(entry, Mapping):
            raise ContractError(f"manifest templates[{index}] must be an object")
        required = {"target", "source", "sourceSha256", "policy", "mode"}
        missing = sorted(required - set(entry))
        if missing:
            raise ContractError(f"manifest templates[{index}] missing fields: {', '.join(missing)}")
        unknown = sorted(set(entry) - MANIFEST_ENTRY_KEYS)
        if unknown:
            raise ContractError(f"manifest templates[{index}] has unknown fields: {', '.join(unknown)}")
        target = ensure_relative_path(entry["target"], field="manifest target")
        if target in target_paths:
            raise ContractError(f"duplicate manifest target: {target}")
        target_paths.add(target)
        source_path = _manifest_source_path(
            entry["source"], template_root=template_root, repository_root=repository_root
        )
        if not source_path.is_file():
            raise ContractError(f"manifest source is missing: {entry['source']}")
        relative_source = source_path.relative_to(template_root).as_posix()
        if relative_source in source_paths:
            raise ContractError(f"duplicate manifest source: {relative_source}")
        source_paths.add(relative_source)
        policy = entry["policy"]
        if policy not in {"create-only", "managed", "json-merge"}:
            raise ContractError(f"unsupported manifest policy for {target}: {policy!r}")
        merge_roots = entry.get("mergeRoots")
        if policy == "json-merge":
            if not isinstance(merge_roots, list) or not merge_roots or not all(
                isinstance(root, str) and root for root in merge_roots
            ):
                raise ContractError(f"json-merge target {target} requires merge roots")
        elif merge_roots is not None:
            raise ContractError(f"non-json target {target} cannot declare merge roots")
        digest = sha256_file(source_path)
        declared_digest = entry.get("sourceSha256")
        if not isinstance(declared_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", declared_digest):
            raise ContractError(f"manifest source digest is invalid: {relative_source}")
        if declared_digest != digest:
            raise ContractError(f"manifest source digest mismatch: {relative_source}")
        mode_text = entry.get("mode")
        if not isinstance(mode_text, str) or not re.fullmatch(r"0[0-7]{3}", mode_text):
            raise ContractError(f"manifest source mode is invalid: {target}")
        declared_mode = int(mode_text, 8)
        actual_mode = stat.S_IMODE(source_path.stat().st_mode)
        normalized_actual_mode = 0o755 if actual_mode & 0o111 else 0o644
        if declared_mode != normalized_actual_mode:
            raise ContractError(f"manifest source mode mismatch: {relative_source}")
        plan.append(
            {
                "target": target,
                "source": relative_source,
                "policy": policy,
                "source_sha256": digest,
                "source_bytes": source_path.stat().st_size,
                "mode": mode_text,
                "executable": bool(declared_mode & 0o111),
            }
        )

    actual_sources = {
        path.relative_to(template_root).as_posix()
        for path in template_root.rglob("*")
        if path.is_file()
        and path != manifest_path
        and "__pycache__" not in path.parts
        and path.name != ".DS_Store"
    }
    covered_sources = source_paths
    if strict_coverage:
        uncovered = sorted(actual_sources - covered_sources)
        nonexistent = sorted(covered_sources - actual_sources)
        if uncovered:
            raise ContractError("template files missing from manifest: " + ", ".join(uncovered))
        if nonexistent:
            raise ContractError("manifest covers nonexistent template files: " + ", ".join(nonexistent))
        expected_directories = {
            parent.relative_to(template_root).as_posix()
            for source in actual_sources
            for parent in (template_root / source).parents
            if parent != template_root and template_root in parent.parents
        }
        if directory_set != expected_directories:
            raise ContractError(
                "manifest directory coverage mismatch; "
                f"missing={sorted(expected_directories - directory_set)}, "
                f"extra={sorted(directory_set - expected_directories)}"
            )
    return {
        "schema_version": "nm-v6/install-plan-v1",
        "template_version": template_version,
        "manifest_sha256": sha256_file(manifest_path),
        "entries": sorted(plan, key=lambda item: item["target"]),
    }


def validate_install_plan_hashes(plan: Mapping[str, Any], template_root: Path) -> None:
    """Recheck a previously generated plan immediately before application."""

    if plan.get("schema_version") != "nm-v6/install-plan-v1":
        raise ContractError("unsupported install plan version")
    entries = plan.get("entries")
    if not isinstance(entries, list):
        raise ContractError("install plan entries must be an array")
    root = template_root.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or plan.get("manifest_sha256") != sha256_file(manifest_path):
        raise ContractError("template manifest changed after install-plan validation")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ContractError("install plan entry must be an object")
        source = (root / ensure_relative_path(entry.get("source"), field="install source")).resolve()
        if not _inside(source, root) or not source.is_file():
            raise ContractError(f"install plan source is unavailable: {source}")
        if entry.get("source_sha256") != sha256_file(source):
            raise ContractError(f"install plan source changed after validation: {entry.get('source')}")


def validate_bilingual_pair(english_path: Path, chinese_path: Path) -> dict[str, Any]:
    """Check paired control fields and stable semantic identifier coverage."""

    if not english_path.is_file() or not chinese_path.is_file():
        raise ContractError(f"missing bilingual pair: {english_path} / {chinese_path}")
    english = english_path.read_text(encoding="utf-8")
    chinese = chinese_path.read_text(encoding="utf-8")
    english_meta, _ = parse_frontmatter(english) if english.startswith("---") else ({}, english)
    chinese_meta, _ = parse_frontmatter(chinese) if chinese.startswith("---") else ({}, chinese)
    for field in ("spec_id", "version", "workflow", "status"):
        if field in english_meta or field in chinese_meta:
            if english_meta.get(field) != chinese_meta.get(field):
                raise ContractError(f"bilingual pair differs in {field}: {english_path.name}")
    if english_meta:
        if english_meta.get("language") != "en":
            raise ContractError(f"English document has wrong language: {english_path}")
        if chinese_meta.get("language") != "zh-CN":
            raise ContractError(f"Chinese mirror has wrong language: {chinese_path}")
    english_ids = set(SEMANTIC_ID_RE.findall(english))
    chinese_ids = set(SEMANTIC_ID_RE.findall(chinese))
    if english_ids != chinese_ids:
        missing_zh = sorted(english_ids - chinese_ids)
        missing_en = sorted(chinese_ids - english_ids)
        raise ContractError(
            f"bilingual semantic IDs differ for {english_path.name}; "
            f"missing zh={missing_zh}, missing en={missing_en}"
        )
    return {
        "english": str(english_path),
        "chinese": str(chinese_path),
        "semantic_ids": sorted(english_ids),
    }


def validate_bilingual_pairs(pairs: Sequence[tuple[Path, Path]]) -> list[dict[str, Any]]:
    seen: set[Path] = set()
    results: list[dict[str, Any]] = []
    for english, chinese in pairs:
        for path in (english.resolve(), chinese.resolve()):
            if path in seen:
                raise ContractError(f"bilingual document appears in multiple pairs: {path}")
            seen.add(path)
        results.append(validate_bilingual_pair(english, chinese))
    return results


def validate_legacy_preservation(repository_root: Path) -> dict[str, Any]:
    """Prove V1-V5 remain present and V5 remains explicitly experimental."""

    root = repository_root.resolve()
    versions: dict[str, str] = {}
    for number in range(1, 6):
        directory = root / "template" / f"v{number}"
        if not directory.is_dir():
            raise ContractError(f"legacy template is missing: template/v{number}")
        versions[f"v{number}"] = str(directory)
    v5_manifest = load_json(root / "template" / "v5" / "manifest.json")
    if not isinstance(v5_manifest, Mapping) or v5_manifest.get("maturity") != "experimental":
        raise ContractError("V5 must remain marked experimental")
    return {"versions": versions, "v5_maturity": "experimental"}


def reject_v5_runtime(target: Path) -> None:
    """Reject automatic import/resumption of mutable V5 runtime state."""

    present = [path for path in V5_RUNTIME_PATHS if (target / path).exists()]
    if present:
        raise ContractError(
            "V5 mutable runtime cannot be imported or resumed by V6: " + ", ".join(present)
        )


def validate_no_mutable_runtime_markdown(paths: Iterable[Path]) -> None:
    """Reject Markdown used as a duplicate mutable runtime authority."""

    patterns = (
        re.compile(r"(?m)^current_(?:phase|task)_id\s*:"),
        re.compile(r"(?m)^run_revision\s*:"),
        re.compile(r"(?m)^lease_(?:holder|token)\s*:"),
        re.compile(r"(?m)^runtime_status\s*:"),
    )
    for path in paths:
        if path.suffix.lower() != ".md" or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in patterns):
            raise ContractError(f"Markdown contains duplicate mutable runtime facts: {path}")


def _validate_node_version(name: str, version: Any) -> None:
    if not isinstance(version, str) or not version or version in {"*", "latest", "next"}:
        raise ContractError(f"Node dependency {name} is not version constrained")
    if version.startswith(("http:", "https:", "git:", "git+", "github:")):
        raise ContractError(f"Node dependency {name} uses an unverified remote artifact")
    if version.startswith(("file:", "workspace:")):
        return
    if not PINNED_NODE_VERSION_RE.fullmatch(version):
        raise ContractError(f"Node dependency {name} has unsupported constraint: {version}")


def validate_dependency_constraints(
    repository_root: Path,
    *,
    require_lock: bool = True,
) -> dict[str, Any]:
    """Validate declared Node/Python dependencies are bounded and reproducible."""

    root = repository_root.resolve()
    checked: list[str] = []
    package = root / "package.json"
    if package.is_file():
        data = load_json(package)
        if not isinstance(data, Mapping):
            raise ContractError("package.json must be an object")
        has_dependencies = False
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            dependencies = data.get(section, {})
            if not isinstance(dependencies, Mapping):
                raise ContractError(f"package.json {section} must be an object")
            for name, version in dependencies.items():
                _validate_node_version(name, version)
                has_dependencies = True
        if require_lock and has_dependencies and not (root / "package-lock.json").is_file():
            raise ContractError("Node dependencies require package-lock.json")
        checked.append("package.json")
    for requirements in sorted(root.glob("requirements*.txt")):
        for line_number, raw in enumerate(requirements.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("-r", "--requirement")):
                raise ContractError(f"nested requirement file is not allowed: {requirements}:{line_number}")
            if not PYTHON_PIN_RE.fullmatch(line):
                raise ContractError(f"Python dependency is not exactly pinned: {requirements}:{line_number}")
        checked.append(requirements.name)
    return {"checked": checked}


def verify_downloaded_artifact(
    data: bytes,
    *,
    origin: str,
    expected_sha256: str,
    allowed_origins: Iterable[str],
) -> str:
    """Verify allowlisted HTTPS origin and digest before an artifact is usable."""

    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ContractError("download origin must be credential-free HTTPS")
    normalized_origin = f"https://{parsed.hostname.lower()}"
    if parsed.port not in (None, 443):
        normalized_origin += f":{parsed.port}"
    normalized_origin += parsed.path
    allowlist = tuple(allowed_origins)
    if not allowlist or not any(
        normalized_origin == allowed.rstrip("/")
        or normalized_origin.startswith(allowed.rstrip("/") + "/")
        for allowed in allowlist
    ):
        raise ContractError(f"download origin is not allowlisted: {origin}")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ContractError("expected artifact digest must be lowercase SHA-256")
    actual = sha256_bytes(data)
    if actual != expected_sha256:
        raise ContractError("downloaded artifact digest mismatch")
    return actual


def validate_provider_update_policy(policy: Mapping[str, Any]) -> None:
    """Require provider self-update to be disabled for every configured adapter."""

    if not isinstance(policy, Mapping) or not policy:
        raise ContractError("provider update policy must be a nonempty object")
    for provider, item in policy.items():
        if not isinstance(item, Mapping):
            raise ContractError(f"provider update policy must be an object: {provider}")
        if item.get("auto_update") is not False:
            raise ContractError(f"provider auto-update must be disabled during runs: {provider}")


def detect_version_drift(
    baseline: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, tuple[Any, Any]]:
    """Return changed version bindings; callers invalidate dependent evidence."""

    validate_version_record(baseline)
    validate_version_record(current)
    drift: dict[str, tuple[Any, Any]] = {}
    for key in sorted(set(baseline) | set(current)):
        if baseline.get(key) != current.get(key):
            drift[key] = (baseline.get(key), current.get(key))
    return drift


def validate_credential_free_environment(environment: Mapping[str, str]) -> None:
    leaked = sorted(
        name for name, value in environment.items() if value and CREDENTIAL_ENV_RE.search(name)
    )
    if leaked:
        raise ContractError(
            "mandatory credential-free execution received credential variables: "
            + ", ".join(leaked)
        )


def validate_schema_catalog(schema_directory: Path) -> dict[str, str]:
    """Load every JSON Schema and reject duplicate or unversioned identifiers."""

    if not schema_directory.is_dir():
        raise ContractError(f"schema directory is missing: {schema_directory}")
    identifiers: dict[str, str] = {}
    files = sorted(schema_directory.glob("*.schema.json"))
    if not files:
        raise ContractError("schema catalog is empty")
    for path in files:
        schema = load_json(path)
        if not isinstance(schema, Mapping):
            raise ContractError(f"schema must be an object: {path}")
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ContractError(f"schema does not declare draft 2020-12: {path.name}")
        identifier = schema.get("$id")
        if not isinstance(identifier, str) or not identifier.startswith("https://notmaster.dev/nm-v6/schemas/"):
            raise ContractError(f"schema has invalid $id: {path.name}")
        if identifier in identifiers:
            raise ContractError(f"duplicate schema $id: {identifier}")
        if identifier.rsplit("/", 1)[-1] != path.name:
            raise ContractError(f"schema $id does not match its file name: {path.name}")
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not isinstance(properties, Mapping):
            raise ContractError(f"schema root required/properties are invalid: {path.name}")
        if not set(required).issubset(properties):
            raise ContractError(f"schema requires undefined root properties: {path.name}")

        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                reference = value.get("$ref")
                if isinstance(reference, str) and not reference.startswith(("#", "https://")):
                    referenced = (schema_directory / reference).resolve()
                    try:
                        referenced.relative_to(schema_directory.resolve())
                    except ValueError as exc:
                        raise ContractError(
                            f"schema reference escapes the catalog: {path.name}: {reference}"
                        ) from exc
                    if not referenced.is_file():
                        raise ContractError(
                            f"schema reference is missing: {path.name}: {reference}"
                        )
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        visit(schema)
        identifiers[identifier] = path.name
    return identifiers


def collect_runtime_versions(
    *,
    core_cli_version: str,
    schema_versions: Mapping[str, str],
    evaluator_version: str,
    adapter_versions: Mapping[str, str],
) -> dict[str, Any]:
    """Collect the exact platform versions bound into evidence."""

    try:
        git_result = subprocess.run(
            ["git", "--version"], text=True, capture_output=True, timeout=10, check=False
        )
        git_version = (git_result.stdout or git_result.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError(f"cannot determine Git version: {exc}") from exc
    import sqlite3

    record = {
        "schema_version": "nm-v6/version-record-v1",
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "git": git_version,
        "core_cli": core_cli_version,
        "schemas": dict(schema_versions),
        "evaluator": evaluator_version,
        "adapters": dict(adapter_versions),
    }
    return validate_version_record(record)


def collect_project_runtime_versions(
    project_root: Path,
    project: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect the exact runtime baseline derived from one project contract.

    Planning and dispatch both call this function.  It intentionally probes no
    provider credentials or mutable external state: adapter implementation
    versions come from the configured provider profiles, while platform, core,
    schema-catalog, and evaluator versions come from the executing controller.
    """

    from . import __version__
    from .adapters import create_adapter

    root = project_root.expanduser().resolve()
    validated = validate_project_config(project)
    catalog = validate_schema_catalog(root / "0c-workflow/schemas")
    schema_versions = {
        filename: identifier for identifier, filename in catalog.items()
    }
    configured = validated["adapters"]
    adapter_versions: dict[str, str] = {}
    if "configured" in configured:
        protocol = str(configured["protocol_version"])
        for provider in sorted(configured["configured"]):
            profile = create_adapter(str(provider)).profile
            adapter_versions[str(provider)] = (
                f"{profile.adapter_version}@{protocol}"
            )
    else:
        for adapter_id, raw in sorted(configured.items()):
            if not isinstance(raw, Mapping):
                raise ContractError(
                    f"configured adapter is malformed: {adapter_id}"
                )
            provider = str(raw["provider"])
            profile = create_adapter(provider).profile
            adapter_versions[str(adapter_id)] = (
                f"{provider}:{profile.adapter_version}@{raw['protocol_version']}"
            )
    return collect_runtime_versions(
        core_cli_version=__version__,
        schema_versions=schema_versions,
        evaluator_version=CONFIGURED_RUNTIME_EVALUATOR_VERSION,
        adapter_versions=adapter_versions,
    )
