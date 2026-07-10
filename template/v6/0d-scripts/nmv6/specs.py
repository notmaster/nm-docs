"""Canonical NM V6 Spec parsing, hashing, and traceability validation.

The canonical hash implementation in this module intentionally does not use a
YAML parser.  V6 frontmatter is a flat, tightly constrained scalar mapping, so
the standard-library parser below is both sufficient and fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .errors import ContractError
from .util import IDENTIFIER_PATTERNS, ensure_relative_path


NORMATIVE_METADATA_KEYS = (
    "spec_id",
    "document_title",
    "version",
    "workflow",
    "language",
    "normative",
    "admin_mirror",
)
CONTROL_METADATA_KEYS = (
    "status",
    "implementation_authorized",
    "content_hash",
)
ALLOWED_FRONTMATTER_KEYS = frozenset(NORMATIVE_METADATA_KEYS + CONTROL_METADATA_KEYS)
REQUIRED_STAGES = (
    "task",
    "phase",
    "dev_integration",
    "release",
    "deploy",
    "completion",
)
STAGE_INDEX = {stage: index for index, stage in enumerate(REQUIRED_STAGES)}
HASH_SEPARATOR = b"\n---body---\n"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ParsedSpec:
    """A parsed English Spec and its independently calculated identity."""

    frontmatter: dict[str, Any]
    metadata: dict[str, Any]
    controls: dict[str, Any]
    body: str
    body_bytes: bytes
    spec_hash: str


@dataclass(frozen=True)
class TraceabilityReport:
    """Validated project-Spec graph counts and mandatory coverage."""

    goal_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    acceptance_ids: tuple[str, ...]
    phase_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    mandatory_acceptance_ids: tuple[str, ...]
    covered_acceptance_ids: tuple[str, ...]


def _read_source(source: str | bytes | Path) -> str:
    if isinstance(source, Path):
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise ContractError(f"cannot read Spec {source}: {exc}") from exc
    elif isinstance(source, bytes):
        data = source
    elif isinstance(source, str):
        return source
    else:
        raise ContractError("Spec source must be UTF-8 text, bytes, or a Path")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("Spec must be valid UTF-8") from exc


def _strip_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1]
    return line, ""


def _parse_scalar(raw: str, *, key: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContractError(f"frontmatter {key!r} has invalid quoted value") from exc
        if not isinstance(parsed, str):
            raise ContractError(f"frontmatter {key!r} must be a scalar")
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise ContractError(f"frontmatter {key!r} has invalid quoted value")
        return value[1:-1].replace("''", "'")
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "~"}:
        return None
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
        return int(value)
    if any(token in value for token in (" #", "\t#")):
        # Inline comments are deliberately unsupported: accepting them would
        # create multiple plausible byte-to-value interpretations.
        raise ContractError(f"frontmatter {key!r} must not use inline comments")
    return value


def parse_frontmatter(source: str | bytes | Path) -> tuple[dict[str, Any], str]:
    """Parse a flat frontmatter mapping and return it with the exact body text.

    The closing delimiter must have a line terminator because the normative
    algorithm defines the body as starting after that terminator.
    """

    text = _read_source(source)
    if text.startswith("\ufeff"):
        raise ContractError("Spec must be UTF-8 without a BOM")
    lines = text.splitlines(keepends=True)
    if not lines:
        raise ContractError("Spec is empty")
    first, first_ending = _strip_line_ending(lines[0])
    if first != "---" or not first_ending:
        raise ContractError("Spec must start with a frontmatter '---' line")

    closing_index: int | None = None
    body_offset = len(lines[0])
    for index, line in enumerate(lines[1:], start=1):
        content, ending = _strip_line_ending(line)
        if content == "---":
            if not ending:
                raise ContractError("closing frontmatter delimiter must end with a line terminator")
            closing_index = index
            body_offset += len(line)
            break
        body_offset += len(line)
    if closing_index is None:
        raise ContractError("Spec frontmatter is not closed")

    result: dict[str, Any] = {}
    for line_number, line in enumerate(lines[1:closing_index], start=2):
        content, _ = _strip_line_ending(line)
        if not content.strip() or content.lstrip().startswith("#"):
            continue
        if content[:1].isspace() or ":" not in content:
            raise ContractError(f"frontmatter line {line_number} is not a flat key/value pair")
        key, raw_value = content.split(":", 1)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ContractError(f"invalid frontmatter key on line {line_number}: {key!r}")
        if key in result:
            raise ContractError(f"duplicate frontmatter key: {key}")
        result[key] = _parse_scalar(raw_value, key=key)
    return result, text[body_offset:]


def _canonical_body(body: str) -> bytes:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.rstrip("\n") + "\n"
    return normalized.encode("utf-8")


def parse_spec(source: str | bytes | Path) -> ParsedSpec:
    """Parse an English V6 Spec and calculate its canonical hash."""

    frontmatter, body = parse_frontmatter(source)
    missing = [key for key in NORMATIVE_METADATA_KEYS if key not in frontmatter]
    if missing:
        raise ContractError(f"Spec frontmatter missing required fields: {', '.join(missing)}")
    unknown = sorted(set(frontmatter) - ALLOWED_FRONTMATTER_KEYS)
    if unknown:
        raise ContractError(f"English Spec frontmatter has unknown fields: {', '.join(unknown)}")
    metadata = {key: frontmatter[key] for key in NORMATIVE_METADATA_KEYS}
    controls = {key: frontmatter[key] for key in CONTROL_METADATA_KEYS if key in frontmatter}
    metadata_bytes = json.dumps(
        metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    body_bytes = _canonical_body(body)
    spec_hash = hashlib.sha256(metadata_bytes + HASH_SEPARATOR + body_bytes).hexdigest()
    return ParsedSpec(
        frontmatter=frontmatter,
        metadata=metadata,
        controls=controls,
        body=body,
        body_bytes=body_bytes,
        spec_hash=spec_hash,
    )


def canonical_spec_hash(source: str | bytes | Path | ParsedSpec) -> str:
    """Return the independently calculated canonical Spec hash."""

    return source.spec_hash if isinstance(source, ParsedSpec) else parse_spec(source).spec_hash


def validate_spec(
    source: str | bytes | Path,
    *,
    traceability: Mapping[str, Any] | None = None,
    require_confirmed_hint: bool = False,
) -> ParsedSpec:
    """Validate the immutable document contract and optional project graph.

    ``require_confirmed_hint`` validates the document's human-facing hint only;
    it deliberately does not authorize execution.  The trusted confirmation
    record is validated separately by the authorization boundary.
    """

    parsed = parse_spec(source)
    metadata = parsed.metadata
    if not isinstance(metadata["spec_id"], str) or not metadata["spec_id"]:
        raise ContractError("spec_id must be a nonempty string")
    if not isinstance(metadata["document_title"], str) or not metadata["document_title"]:
        raise ContractError("document_title must be a nonempty string")
    if isinstance(metadata["version"], bool) or not isinstance(metadata["version"], int) or metadata["version"] <= 0:
        raise ContractError("version must be a positive integer")
    if metadata["workflow"] != "v6":
        raise ContractError("workflow must be literal 'v6'")
    if metadata["language"] != "en" or metadata["normative"] is not True:
        raise ContractError("the normative Spec must declare language=en and normative=true")
    mirror = metadata["admin_mirror"]
    if not isinstance(mirror, str) or not mirror.endswith(".zh-CN.md"):
        raise ContractError("admin_mirror must identify a Simplified Chinese Markdown mirror")
    ensure_relative_path(mirror, field="admin_mirror")

    status = parsed.controls.get("status")
    if status is not None and status not in {"draft", "review-ready", "confirmed", "retired"}:
        raise ContractError(f"unsupported Spec status hint: {status!r}")
    if require_confirmed_hint and status != "confirmed":
        raise ContractError("Spec status hint is not confirmed")
    authorized = parsed.controls.get("implementation_authorized")
    if authorized is not None and not isinstance(authorized, bool):
        raise ContractError("implementation_authorized must be boolean")
    displayed = parsed.controls.get("content_hash")
    if displayed is not None:
        if not isinstance(displayed, str) or displayed.lower() != parsed.spec_hash:
            raise ContractError("displayed content_hash does not match the calculated Spec hash")
    if traceability is not None:
        validate_traceability(traceability)
    return parsed


def validate_confirmation_binding(parsed: ParsedSpec, record: Mapping[str, Any]) -> None:
    """Fail if a trusted confirmation record is bound to another Spec."""

    expected = {
        "spec_id": parsed.metadata["spec_id"],
        "version": parsed.metadata["version"],
        "spec_hash": parsed.spec_hash,
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise ContractError(f"confirmation {field} does not match the canonical Spec")
    if record.get("decision") != "confirmed":
        raise ContractError("confirmation decision must be literal 'confirmed'")


def _entity_list(
    graph: Mapping[str, Any], name: str, aliases: Sequence[str] = ()
) -> list[Mapping[str, Any]]:
    value: Any = []
    for key in (name, *aliases):
        if key in graph:
            value = graph[key]
            break
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ContractError(f"traceability {name} must be an array of objects")
    return list(value)


def _identifier_map(
    entities: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    subject: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    pattern = IDENTIFIER_PATTERNS[kind]
    for item in entities:
        identifier = item.get("id", item.get(f"{kind}_id"))
        if not isinstance(identifier, str) or not pattern.fullmatch(identifier):
            raise ContractError(f"{subject} has invalid {kind} identifier: {identifier!r}")
        if identifier in result:
            raise ContractError(f"duplicate {subject} identifier: {identifier}")
        result[identifier] = item
    return result


def _string_ids(item: Mapping[str, Any], fields: Iterable[str], *, subject: str) -> list[str]:
    value: Any = None
    selected = ""
    for field in fields:
        if field in item:
            value = item[field]
            selected = field
            break
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(entry, str) and entry for entry in value):
        raise ContractError(f"{subject}.{selected} must be an array of identifiers")
    if len(value) != len(set(value)):
        raise ContractError(f"{subject}.{selected} contains duplicate identifiers")
    return list(value)


def _require_references(values: Iterable[str], available: Mapping[str, Any], *, subject: str) -> None:
    missing = sorted(set(values) - set(available))
    if missing:
        raise ContractError(f"{subject} references unknown identifiers: {', '.join(missing)}")


def _validate_dag(
    entities: Mapping[str, Mapping[str, Any]], *, subject: str
) -> dict[str, tuple[str, ...]]:
    edges: dict[str, list[str]] = {}
    for identifier, item in entities.items():
        dependencies = _string_ids(item, ("depends_on", "dependencies"), subject=identifier)
        _require_references(dependencies, entities, subject=identifier)
        if identifier in dependencies:
            raise ContractError(f"{identifier} cannot depend on itself")
        edges[identifier] = dependencies

    state: dict[str, int] = {}

    def visit(identifier: str, trail: tuple[str, ...]) -> None:
        current = state.get(identifier, 0)
        if current == 2:
            return
        if current == 1:
            cycle = " -> ".join((*trail, identifier))
            raise ContractError(f"{subject} dependency cycle: {cycle}")
        state[identifier] = 1
        for dependency in edges[identifier]:
            visit(dependency, (*trail, identifier))
        state[identifier] = 2

    for identifier in sorted(edges):
        visit(identifier, ())
    return {identifier: tuple(dependencies) for identifier, dependencies in edges.items()}


def _transitive_dependencies(
    edges: Mapping[str, Sequence[str]],
) -> dict[str, frozenset[str]]:
    """Return the complete dependency ancestry for an already validated DAG."""

    resolved: dict[str, frozenset[str]] = {}

    def visit(identifier: str) -> frozenset[str]:
        if identifier in resolved:
            return resolved[identifier]
        dependencies = set(edges[identifier])
        for dependency in edges[identifier]:
            dependencies.update(visit(dependency))
        resolved[identifier] = frozenset(dependencies)
        return resolved[identifier]

    for identifier in edges:
        visit(identifier)
    return resolved


def _is_mandatory(item: Mapping[str, Any], *, subject: str) -> bool:
    if "mandatory" in item:
        value = item["mandatory"]
        if not isinstance(value, bool):
            raise ContractError(f"{subject}.mandatory must be boolean")
        return value
    classification = item.get("classification")
    if classification not in {"mandatory", "optional"}:
        raise ContractError(f"{subject} must declare mandatory/optional classification")
    return classification == "mandatory"


def validate_traceability(graph: Mapping[str, Any]) -> TraceabilityReport:
    """Validate Goal/Requirement/Acceptance/Phase/Task links and DAGs."""

    if not isinstance(graph, Mapping):
        raise ContractError("traceability graph must be an object")
    goals = _identifier_map(_entity_list(graph, "goals"), kind="goal", subject="Goal")
    requirements = _identifier_map(
        _entity_list(graph, "requirements"), kind="requirement", subject="Requirement"
    )
    acceptance = _identifier_map(
        _entity_list(graph, "acceptance", ("acceptance_criteria",)),
        kind="acceptance",
        subject="Acceptance criterion",
    )
    phases = _identifier_map(_entity_list(graph, "phases"), kind="phase", subject="Phase")
    tasks = _identifier_map(_entity_list(graph, "tasks"), kind="task", subject="Task")

    if not goals or not requirements or not acceptance:
        raise ContractError("a confirmed Spec requires at least one Goal, Requirement, and Acceptance criterion")

    for identifier, item in requirements.items():
        goal_ids = _string_ids(item, ("goal_ids", "goals"), subject=identifier)
        if not goal_ids and item.get("status") != "retired":
            raise ContractError(f"{identifier} must trace to at least one Goal")
        _require_references(goal_ids, goals, subject=identifier)

    mandatory_ids: set[str] = set()
    for identifier, item in acceptance.items():
        requirement_ids = _string_ids(
            item, ("requirement_ids", "requirements"), subject=identifier
        )
        mandatory = _is_mandatory(item, subject=identifier)
        if mandatory:
            mandatory_ids.add(identifier)
            if not requirement_ids:
                raise ContractError(f"mandatory {identifier} must trace to at least one Requirement")
        _require_references(requirement_ids, requirements, subject=identifier)
        stage = item.get("required_by_stage")
        if stage not in STAGE_INDEX:
            raise ContractError(
                f"{identifier}.required_by_stage must be one of {', '.join(REQUIRED_STAGES)}"
            )

    covered: set[str] = set()
    for identifier, item in tasks.items():
        acceptance_ids = _string_ids(
            item, ("acceptance_ids", "acceptance"), subject=identifier
        )
        enabling = _string_ids(
            item,
            ("enabling_requirement_ids", "enabling_requirements"),
            subject=identifier,
        )
        if not acceptance_ids and not enabling:
            raise ContractError(
                f"{identifier} must trace to Acceptance criteria or an enabling Requirement"
            )
        _require_references(acceptance_ids, acceptance, subject=identifier)
        _require_references(enabling, requirements, subject=identifier)
        covered.update(acceptance_ids)

    actions = graph.get("acceptance_actions", {})
    if isinstance(actions, Mapping):
        action_covered = set(actions)
    elif isinstance(actions, list):
        if not all(isinstance(value, str) for value in actions):
            raise ContractError("acceptance_actions must contain Acceptance identifiers")
        action_covered = set(actions)
    else:
        raise ContractError("acceptance_actions must be an object or identifier array")
    _require_references(action_covered, acceptance, subject="acceptance_actions")
    covered.update(action_covered)
    for identifier, item in acceptance.items():
        if item.get("action_id") or item.get("acceptance_action"):
            covered.add(identifier)

    missing_coverage = sorted(mandatory_ids - covered)
    if missing_coverage:
        raise ContractError(
            "mandatory Acceptance criteria lack Task/action coverage: "
            + ", ".join(missing_coverage)
        )

    phase_dependencies = _validate_dag(phases, subject="Phase")
    task_dependencies = _validate_dag(tasks, subject="Task")
    for task_id, task in tasks.items():
        phase_id = task.get("phase_id")
        if phase_id is not None:
            if not isinstance(phase_id, str) or phase_id not in phases:
                raise ContractError(f"{task_id} references unknown phase_id: {phase_id!r}")

    phase_ancestors = _transitive_dependencies(phase_dependencies)
    for task_id, dependencies in task_dependencies.items():
        phase_id = tasks[task_id].get("phase_id")
        if phase_id is None:
            continue
        for dependency in dependencies:
            dependency_phase_id = tasks[dependency].get("phase_id")
            if dependency_phase_id in {None, phase_id}:
                continue
            if dependency_phase_id not in phase_ancestors[phase_id]:
                raise ContractError(
                    f"{task_id} in {phase_id} depends on {dependency} in "
                    f"{dependency_phase_id}, but {dependency_phase_id} is not a "
                    f"declared ancestor of {phase_id}"
                )

    delivery_stages = graph.get("required_delivery_stages")
    if not isinstance(delivery_stages, Mapping):
        raise ContractError("required_delivery_stages must be an object")
    allowed_delivery_fields = {*REQUIRED_STAGES, "environments"}
    unknown = sorted(set(delivery_stages) - allowed_delivery_fields)
    if unknown:
        raise ContractError(
            "required_delivery_stages contains unknown fields: " + ", ".join(unknown)
        )
    missing = sorted({"release", "deploy", "environments"} - set(delivery_stages))
    if missing:
        raise ContractError(
            "required_delivery_stages is missing required fields: " + ", ".join(missing)
        )
    for stage, decision in delivery_stages.items():
        if stage == "environments":
            continue
        if decision not in {"required", "not_applicable"}:
            raise ContractError(f"required_delivery_stages.{stage} is invalid")
    environments = delivery_stages["environments"]
    if not isinstance(environments, list) or not all(
        isinstance(environment, str) and environment for environment in environments
    ):
        raise ContractError(
            "required_delivery_stages.environments must be an ordered string array"
        )
    if len(environments) != len(set(environments)):
        raise ContractError(
            "required_delivery_stages.environments must not contain duplicates"
        )
    if delivery_stages["deploy"] == "required" and not environments:
        raise ContractError(
            "required deployment must declare at least one target environment"
        )
    if delivery_stages["deploy"] == "not_applicable" and environments:
        raise ContractError(
            "not-applicable deployment must declare no target environments"
        )
    if (
        delivery_stages["release"] == "not_applicable"
        and delivery_stages["deploy"] == "required"
    ):
        raise ContractError(
            "deployment cannot be required when release is not_applicable"
        )

    return TraceabilityReport(
        goal_ids=tuple(sorted(goals)),
        requirement_ids=tuple(sorted(requirements)),
        acceptance_ids=tuple(sorted(acceptance)),
        phase_ids=tuple(sorted(phases)),
        task_ids=tuple(sorted(tasks)),
        mandatory_acceptance_ids=tuple(sorted(mandatory_ids)),
        covered_acceptance_ids=tuple(sorted(covered)),
    )


def criteria_due_by_stage(
    acceptance: Sequence[Mapping[str, Any]], stage: str
) -> tuple[str, ...]:
    """Return mandatory criteria due at ``stage`` under V6 gate semantics."""

    if stage not in STAGE_INDEX:
        raise ContractError(f"unknown acceptance stage: {stage}")
    due: list[str] = []
    for item in acceptance:
        identifier = item.get("id", item.get("acceptance_id"))
        if not isinstance(identifier, str) or not IDENTIFIER_PATTERNS["acceptance"].fullmatch(identifier):
            raise ContractError(f"invalid Acceptance identifier: {identifier!r}")
        required_stage = item.get("required_by_stage")
        if required_stage not in STAGE_INDEX:
            raise ContractError(f"{identifier} has invalid required_by_stage")
        if _is_mandatory(item, subject=identifier) and (
            stage == "completion" or STAGE_INDEX[required_stage] <= STAGE_INDEX[stage]
        ):
            due.append(identifier)
    return tuple(sorted(due))


def validate_optional_task_skip(
    graph: Mapping[str, Any],
    *,
    skipped_task_id: str,
    satisfied_acceptance_ids: Iterable[str] = (),
) -> None:
    """Prove that skipping one optional Task preserves mandatory coverage."""

    report = validate_traceability(graph)
    tasks = {
        item.get("id", item.get("task_id")): item for item in _entity_list(graph, "tasks")
    }
    task = tasks.get(skipped_task_id)
    if task is None:
        raise ContractError(f"unknown Task: {skipped_task_id}")
    if task.get("optional") is not True:
        raise ContractError(f"{skipped_task_id} is not explicitly optional")
    remaining = set(satisfied_acceptance_ids)
    for identifier, item in tasks.items():
        if identifier == skipped_task_id:
            continue
        remaining.update(_string_ids(item, ("acceptance_ids", "acceptance"), subject=identifier))
    actions = graph.get("acceptance_actions", {})
    remaining.update(actions if isinstance(actions, Mapping) else actions)
    missing = sorted(set(report.mandatory_acceptance_ids) - remaining)
    if missing:
        raise ContractError(
            f"skipping {skipped_task_id} leaves mandatory Acceptance uncovered: "
            + ", ".join(missing)
        )
