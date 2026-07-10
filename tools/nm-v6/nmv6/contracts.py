"""Fail-closed validators for NM V6's versioned JSON contracts.

JSON Schema documents are shipped for interoperability, while these validators
are the executable standard-library implementation used by the core.  They are
intentionally explicit: unsupported protocol versions and unknown security-
relevant fields fail rather than being guessed.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from .errors import ContractError
from .models import AdapterResult
from .util import (
    IDENTIFIER_PATTERNS,
    canonical_json,
    ensure_relative_path,
    reject_unknown_keys,
    require_keys,
    sha256_bytes,
)


SCHEMA_PREFIX = "nm-v6/"
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
SAFE_INHERITED_ENV_NAMES = frozenset(
    {"PATH", "LANG", "LC_ALL", "TZ", "TERM", "NO_COLOR", "CI"}
)
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
SHELL_EXECUTABLES = {
    "sh",
    "bash",
    "dash",
    "zsh",
    "fish",
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
}
RAW_INTERPOLATION_RE = re.compile(r"\$\(|\$\{|`|%[A-Za-z_][A-Za-z0-9_]*%")
SECRET_FIELD_RE = re.compile(
    r"(?:secret|password|passwd|credential|private[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|webhook[_-]?(?:url|value))",
    re.IGNORECASE,
)
FORBIDDEN_AGENT_CAPABILITY_RE = re.compile(
    r"(?:push|protected[_-]?ref|release|publish|deploy|rollback|production|"
    r"secret|credential|state[_-]?(?:write|store|database)|reducer)",
    re.IGNORECASE,
)


PROJECT_KEYS = {
    "schema_version",
    "project",
    "git",
    "scheduler",
    "context",
    "actions",
    "delivery",
    "action_definitions",
    "secret_references",
    "notifications",
    "adapters",
    "spec",
    "version_constraints",
    "authorization",
    "evidence",
    "supply_chain",
}
ACTION_KEYS = {
    "schema_version",
    "action_id",
    "kind",
    "argv",
    "cwd",
    "timeout_seconds",
    "accepted_exit_codes",
    "env_allowlist",
    "core_injected_env",
    "secret_refs",
    "result_schema",
    "idempotency",
    "observe_action_id",
    "reconcile_action_id",
}
ACTION_RESULT_KEYS = {
    "protocol_version",
    "action_id",
    "operation_id",
    "status",
    "effect_id",
    "artifact_digest",
    "environment_id",
    "environment_fingerprint",
    "observed_state",
    "started_at",
    "finished_at",
    "diagnostics",
    "redactions",
}
ADAPTER_REQUEST_KEYS = {
    "protocol_version",
    "operation_id",
    "run_id",
    "attempt_id",
    "role",
    "workspace",
    "context_manifest",
    "expected_output_schema",
    "deadline",
    "fencing_token",
    "allowed_capabilities",
}
ADAPTER_RESULT_KEYS = {
    "protocol_version",
    "operation_id",
    "attempt_id",
    "status",
    "session_id",
    "candidate_commit",
    "changed_paths",
    "observations",
    "requested_followups",
    "usage",
    "adapter_diagnostics",
}


def _mapping(value: Any, *, subject: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{subject} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ContractError(f"{subject} keys must be strings")
    return value


def _array(value: Any, *, subject: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{subject} must be an array")
    return value


def _nonempty_string(value: Any, *, subject: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{subject} must be a nonempty string")
    return value


def _positive_int(value: Any, *, subject: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{subject} must be a positive integer")
    if maximum is not None and value > maximum:
        raise ContractError(f"{subject} exceeds maximum {maximum}")
    return value


def _nonnegative_int(value: Any, *, subject: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{subject} must be a nonnegative integer")
    return value


def _unique_strings(value: Any, *, subject: str, allow_empty: bool = True) -> list[str]:
    items = _array(value, subject=subject)
    if not all(isinstance(item, str) and item for item in items):
        raise ContractError(f"{subject} must contain nonempty strings")
    if not allow_empty and not items:
        raise ContractError(f"{subject} must not be empty")
    if len(items) != len(set(items)):
        raise ContractError(f"{subject} must not contain duplicates")
    return list(items)


def _rfc3339(value: Any, *, subject: str) -> str:
    text = _nonempty_string(value, subject=subject)
    if not RFC3339_RE.fullmatch(text):
        raise ContractError(f"{subject} must be an RFC3339 timestamp with timezone")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{subject} is not a valid timestamp") from exc
    return text


def _digest(value: Any, *, subject: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    text = _nonempty_string(value, subject=subject)
    if not SHA256_RE.fullmatch(text):
        raise ContractError(f"{subject} must be a lowercase SHA-256 digest")
    return text


def _operation_id(value: Any, *, subject: str = "operation_id") -> str:
    text = _nonempty_string(value, subject=subject)
    if not IDENTIFIER_PATTERNS["operation"].fullmatch(text):
        raise ContractError(f"{subject} has invalid V6 identifier format")
    return text


def _attempt_id(value: Any, *, subject: str = "attempt_id") -> str:
    text = _nonempty_string(value, subject=subject)
    if not IDENTIFIER_PATTERNS["attempt"].fullmatch(text):
        raise ContractError(f"{subject} has invalid V6 identifier format")
    return text


def _reject_secret_material(value: Any, *, path: str = "input") -> None:
    """Reject credential-shaped keys and obvious literal credential values."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            safe_policy_value = nested is None or nested is False or (
                isinstance(nested, str)
                and nested in {"forbidden", "reference_only", "not_applicable"}
            )
            if SECRET_FIELD_RE.search(str(key)) and not safe_policy_value:
                raise ContractError(f"{path}.{key} may contain credential material")
            _reject_secret_material(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_material(nested, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if (
            "-----begin " in lowered
            or lowered.startswith(("ghp_", "github_pat_", "sk-", "xoxb-", "xoxp-"))
            or "open-apis/bot/v2/hook/" in lowered
        ):
            raise ContractError(f"{path} contains literal credential material")


def _validate_supply_chain_policy(policy: Any) -> dict[str, Any]:
    value = _mapping(policy, subject="supply_chain")
    keys = {
        "schema_version",
        "allowed_download_origins",
        "require_download_digest_or_signature",
        "disable_provider_auto_update",
        "mandatory_ci_credentials",
    }
    require_keys(value, keys, subject="supply_chain")
    reject_unknown_keys(value, keys, subject="supply_chain")
    validate_schema_version(
        value["schema_version"],
        "nm-v6/supply-chain-v1",
        subject="supply_chain.schema_version",
    )
    origins = _unique_strings(
        value["allowed_download_origins"],
        subject="supply_chain.allowed_download_origins",
        allow_empty=False,
    )
    for origin in origins:
        parsed = urlparse(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ContractError(
                "supply_chain.allowed_download_origins must contain credential-free HTTPS origins"
            )
    if value["require_download_digest_or_signature"] is not True:
        raise ContractError("supply_chain must require a download digest or signature")
    if value["disable_provider_auto_update"] is not True:
        raise ContractError("supply_chain must disable provider auto-update during a run")
    if value["mandatory_ci_credentials"] != "forbidden":
        raise ContractError("supply_chain must forbid credentials in mandatory CI")
    _reject_secret_material(value, path="supply_chain")
    return dict(value)


def validate_schema_version(value: Any, expected: str, *, subject: str = "schema_version") -> str:
    text = _nonempty_string(value, subject=subject)
    if text != expected:
        raise ContractError(f"{subject} must be literal {expected!r}, got {text!r}")
    return text


def _validate_argv(argv: Any, *, subject: str) -> list[str]:
    values = _unique_strings(argv, subject=subject, allow_empty=False)
    executable = Path(values[0]).name.lower()
    if executable in SHELL_EXECUTABLES:
        raise ContractError(f"{subject} must not invoke a command shell")
    for value in values:
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ContractError(f"{subject} contains an unsafe control character")
        if RAW_INTERPOLATION_RE.search(value):
            raise ContractError(f"{subject} contains raw shell interpolation")
    return values


def validate_action_definition(
    definition: Mapping[str, Any],
    *,
    expected_id: str | None = None,
    known_secret_refs: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Validate one complete deterministic action definition."""

    value = _mapping(definition, subject="action definition")
    require_keys(value, ACTION_KEYS, subject="action definition")
    reject_unknown_keys(value, ACTION_KEYS, subject="action definition")
    validate_schema_version(value["schema_version"], "nm-v6/action-v1")
    action_id = _nonempty_string(value["action_id"], subject="action_id")
    if not SAFE_NAME_RE.fullmatch(action_id):
        raise ContractError("action_id contains unsupported characters")
    if expected_id is not None and action_id != expected_id:
        raise ContractError(f"action_id {action_id!r} does not match configuration key {expected_id!r}")
    kind = value["kind"]
    if kind not in {"pure", "external_observe", "external_mutation"}:
        raise ContractError("action kind must be pure|external_observe|external_mutation")
    _validate_argv(value["argv"], subject=f"{action_id}.argv")
    if value["cwd"] != ".":
        ensure_relative_path(value["cwd"], field=f"{action_id}.cwd")
    _positive_int(value["timeout_seconds"], subject=f"{action_id}.timeout_seconds", maximum=86400)
    exit_codes = _array(value["accepted_exit_codes"], subject=f"{action_id}.accepted_exit_codes")
    if not exit_codes or not all(isinstance(code, int) and not isinstance(code, bool) for code in exit_codes):
        raise ContractError(f"{action_id}.accepted_exit_codes must contain integers")
    if len(exit_codes) != len(set(exit_codes)):
        raise ContractError(f"{action_id}.accepted_exit_codes contains duplicates")
    for field in ("env_allowlist", "core_injected_env"):
        names = _unique_strings(value[field], subject=f"{action_id}.{field}")
        if not all(ENV_NAME_RE.fullmatch(name) for name in names):
            raise ContractError(f"{action_id}.{field} contains an invalid environment name")
        if field == "env_allowlist":
            unsupported = sorted(set(names) - SAFE_INHERITED_ENV_NAMES)
            if unsupported:
                raise ContractError(
                    f"{action_id}.env_allowlist may inherit only non-sensitive process "
                    f"settings ({', '.join(sorted(SAFE_INHERITED_ENV_NAMES))}); "
                    f"project credentials must use secret_refs, not: {', '.join(unsupported)}"
                )
    overlap = set(value["env_allowlist"]) & set(value["core_injected_env"])
    if overlap:
        raise ContractError(f"{action_id} environment names cannot be both inherited and injected")
    secret_refs = _unique_strings(value["secret_refs"], subject=f"{action_id}.secret_refs")
    if known_secret_refs is not None:
        unknown = sorted(set(secret_refs) - set(known_secret_refs))
        if unknown:
            raise ContractError(f"{action_id} references unknown secrets: {', '.join(unknown)}")
    validate_schema_version(
        value["result_schema"], "nm-v6/action-result-v1", subject=f"{action_id}.result_schema"
    )
    idempotency = value["idempotency"]
    if idempotency not in {"not_applicable", "read_only", "required"}:
        raise ContractError(f"{action_id}.idempotency has unsupported value")
    observe_id = value["observe_action_id"]
    reconcile_id = value["reconcile_action_id"]
    if kind == "external_mutation":
        if idempotency != "required":
            raise ContractError(f"external mutation {action_id} must require idempotency")
        if "NM_V6_OPERATION_ID" not in value["core_injected_env"]:
            raise ContractError(
                f"external mutation {action_id} must declare NM_V6_OPERATION_ID injection"
            )
        if not isinstance(observe_id, str) or not observe_id:
            raise ContractError(f"external mutation {action_id} requires observe_action_id")
        if not isinstance(reconcile_id, str) or not reconcile_id:
            raise ContractError(f"external mutation {action_id} requires reconcile_action_id")
    else:
        if observe_id is not None or reconcile_id is not None:
            raise ContractError(f"non-mutating action {action_id} cannot declare observe/reconcile actions")
        expected_idempotency = "read_only" if kind == "external_observe" else "not_applicable"
        if idempotency != expected_idempotency:
            raise ContractError(f"{kind} action {action_id} requires idempotency={expected_idempotency}")
    return dict(value)


def _validate_secret_references(value: Any) -> set[str]:
    references = _mapping(value, subject="secret_references")
    names: set[str] = set()
    for name, descriptor in references.items():
        if not SAFE_NAME_RE.fullmatch(name):
            raise ContractError(f"invalid secret reference name: {name!r}")
        item = _mapping(descriptor, subject=f"secret_references.{name}")
        allowed = {"provider", "reference", "env", "name", "description", "fake_id"}
        reject_unknown_keys(item, allowed, subject=f"secret_references.{name}")
        provider = _nonempty_string(item.get("provider"), subject=f"secret_references.{name}.provider")
        if provider not in {"environment", "keychain", "file", "fake"}:
            raise ContractError(f"secret_references.{name}.provider is unsupported")
        locators = [key for key in ("reference", "env", "name", "fake_id") if item.get(key)]
        if len(locators) != 1:
            raise ContractError(f"secret_references.{name} must declare exactly one locator")
        locator = _nonempty_string(item[locators[0]], subject=f"secret_references.{name}.{locators[0]}")
        if provider == "environment" and (locators[0] != "env" or not ENV_NAME_RE.fullmatch(locator)):
            raise ContractError(f"secret_references.{name} environment locator is invalid")
        if "://" in locator or "-----BEGIN" in locator:
            raise ContractError(f"secret_references.{name} contains a value instead of a reference")
        names.add(name)
    return names


def _walk_action_references(project: Mapping[str, Any]) -> set[str]:
    references: set[str] = set()
    actions = _mapping(project["actions"], subject="actions")
    for logical_name, action_id in actions.items():
        if not isinstance(logical_name, str):
            raise ContractError("actions keys must be strings")
        references.add(_nonempty_string(action_id, subject=f"actions.{logical_name}"))
    delivery = _mapping(project["delivery"], subject="delivery")
    require_keys(delivery, ("artifact_digest_result_field", "environments"), subject="delivery")
    reject_unknown_keys(delivery, ("artifact_digest_result_field", "environments"), subject="delivery")
    if delivery["artifact_digest_result_field"] != "artifact_digest":
        raise ContractError("delivery.artifact_digest_result_field must be literal 'artifact_digest'")
    environments = _mapping(delivery["environments"], subject="delivery.environments")
    for environment_name, environment in environments.items():
        if not SAFE_NAME_RE.fullmatch(environment_name):
            raise ContractError(f"invalid environment name: {environment_name!r}")
        item = _mapping(environment, subject=f"delivery.environments.{environment_name}")
        required = {
            "expected_identity",
            "identity_probe",
            "preflight",
            "deploy",
            "health",
            "rollback",
            "post_rollback_verify",
        }
        require_keys(item, required, subject=f"delivery.environments.{environment_name}")
        reject_unknown_keys(item, required, subject=f"delivery.environments.{environment_name}")
        _nonempty_string(item["expected_identity"], subject=f"{environment_name}.expected_identity")
        for key in required - {"expected_identity"}:
            references.add(_nonempty_string(item[key], subject=f"{environment_name}.{key}"))
    notifications = _mapping(project["notifications"], subject="notifications")
    require_keys(notifications, ("routes",), subject="notifications")
    reject_unknown_keys(notifications, ("routes",), subject="notifications")
    routes = _array(notifications["routes"], subject="notifications.routes")
    for index, route in enumerate(routes):
        item = _mapping(route, subject=f"notifications.routes[{index}]")
        require_keys(item, ("action_id",), subject=f"notifications.routes[{index}]")
        reject_unknown_keys(
            item,
            ("route_id", "event_types", "action_id", "severity", "idempotency"),
            subject=f"notifications.routes[{index}]",
        )
        if "route_id" in item:
            _nonempty_string(item["route_id"], subject=f"notifications.routes[{index}].route_id")
        if "event_types" in item:
            _unique_strings(item["event_types"], subject=f"notifications.routes[{index}].event_types", allow_empty=False)
        references.add(_nonempty_string(item["action_id"], subject=f"notifications.routes[{index}].action_id"))
        if item.get("severity") not in (None, "progress", "attention"):
            raise ContractError("notification severity must be progress|attention")
        if item.get("idempotency") not in (None, "notification_id"):
            raise ContractError("notification routes must use notification_id idempotency")
    return references


def validate_project_config(project: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete V6 project/action/delivery topology."""

    value = _mapping(project, subject="project configuration")
    required = PROJECT_KEYS - {
        "adapters",
        "spec",
        "version_constraints",
        "authorization",
        "evidence",
        "supply_chain",
    }
    require_keys(value, required, subject="project configuration")
    reject_unknown_keys(value, PROJECT_KEYS, subject="project configuration")
    validate_schema_version(value["schema_version"], "nm-v6/project-v1")

    project_info = _mapping(value["project"], subject="project")
    require_keys(project_info, ("name",), subject="project")
    reject_unknown_keys(project_info, ("name", "id"), subject="project")
    _nonempty_string(project_info["name"], subject="project.name")

    git = _mapping(value["git"], subject="git")
    git_keys = {
        "remote",
        "stable_branch",
        "integration_branch",
        "protected_branches",
        "work_branch_prefixes",
        "hotfix_prefix",
        "other_branch_push",
        "remote_branch_delete",
        "force_push",
        "integration_unit",
        "merge_strategies",
    }
    require_keys(git, git_keys, subject="git")
    reject_unknown_keys(git, git_keys, subject="git")
    _nonempty_string(git["remote"], subject="git.remote")
    stable = _nonempty_string(git["stable_branch"], subject="git.stable_branch")
    if stable not in {"main", "master"}:
        raise ContractError("git.stable_branch must be main or master")
    if git["integration_branch"] != "dev":
        raise ContractError("git.integration_branch must be literal 'dev'")
    if stable == git["integration_branch"]:
        raise ContractError("stable and integration branches must be distinct")
    protected = set(_unique_strings(git["protected_branches"], subject="git.protected_branches", allow_empty=False))
    if not {stable, "dev"}.issubset(protected):
        raise ContractError("git.protected_branches must include stable and dev")
    prefixes = _unique_strings(git["work_branch_prefixes"], subject="git.work_branch_prefixes", allow_empty=False)
    if not all(prefix.endswith("/") and prefix not in {"hotfix/", "release/"} for prefix in prefixes):
        raise ContractError("git.work_branch_prefixes contains an invalid or privileged prefix")
    if git["hotfix_prefix"] != "hotfix/":
        raise ContractError("git.hotfix_prefix must be literal 'hotfix/'")
    if git["other_branch_push"] != "administrator_grant_only":
        raise ContractError("other branch pushes must require an administrator grant")
    if git["remote_branch_delete"] != "administrator_grant_only":
        raise ContractError("remote branch deletion must require an administrator grant")
    if git["force_push"] != "forbidden":
        raise ContractError("force push must be forbidden")
    if git["integration_unit"] not in {"phase", "task"}:
        raise ContractError("git.integration_unit must be phase or task")
    strategies = set(_unique_strings(git["merge_strategies"], subject="git.merge_strategies", allow_empty=False))
    if not strategies.issubset({"fast_forward", "squash", "merge_commit"}):
        raise ContractError("git.merge_strategies contains an unsupported strategy")

    scheduler = _mapping(value["scheduler"], subject="scheduler")
    require_keys(scheduler, ("max_workers", "lease_seconds"), subject="scheduler")
    reject_unknown_keys(
        scheduler,
        ("max_workers", "lease_seconds", "heartbeat_seconds", "retry_budget"),
        subject="scheduler",
    )
    _positive_int(scheduler["max_workers"], subject="scheduler.max_workers", maximum=256)
    lease_seconds = _positive_int(scheduler["lease_seconds"], subject="scheduler.lease_seconds", maximum=86400)
    if "heartbeat_seconds" in scheduler:
        heartbeat = _positive_int(
            scheduler["heartbeat_seconds"], subject="scheduler.heartbeat_seconds", maximum=86400
        )
        if heartbeat >= lease_seconds:
            raise ContractError("scheduler.heartbeat_seconds must be shorter than lease_seconds")
    if "retry_budget" in scheduler:
        _nonnegative_int(scheduler["retry_budget"], subject="scheduler.retry_budget")

    context = _mapping(value["context"], subject="context")
    require_keys(context, ("max_manifest_bytes", "max_estimated_tokens"), subject="context")
    reject_unknown_keys(context, ("max_manifest_bytes", "max_estimated_tokens"), subject="context")
    _positive_int(context["max_manifest_bytes"], subject="context.max_manifest_bytes")
    _positive_int(context["max_estimated_tokens"], subject="context.max_estimated_tokens")

    actions = _mapping(value["actions"], subject="actions")
    missing_required_actions = sorted({"full_verify", "release_metadata"} - set(actions))
    if missing_required_actions:
        raise ContractError(
            "actions must define required logical actions: "
            + ", ".join(missing_required_actions)
        )
    secret_names = _validate_secret_references(value["secret_references"])
    definitions = _mapping(value["action_definitions"], subject="action_definitions")
    validated_definitions: dict[str, dict[str, Any]] = {}
    for action_id, definition in definitions.items():
        if action_id in validated_definitions:
            raise ContractError(f"duplicate action definition: {action_id}")
        validated_definitions[action_id] = validate_action_definition(
            definition, expected_id=action_id, known_secret_refs=secret_names
        )
    references = _walk_action_references(value)
    missing = sorted(references - set(validated_definitions))
    if missing:
        raise ContractError("configuration references undefined actions: " + ", ".join(missing))

    for action_id, definition in validated_definitions.items():
        if definition["kind"] != "external_mutation":
            continue
        observe_id = definition["observe_action_id"]
        reconcile_id = definition["reconcile_action_id"]
        for reference, purpose in ((observe_id, "observe"), (reconcile_id, "reconcile")):
            target = validated_definitions.get(reference)
            if target is None:
                raise ContractError(f"{action_id} {purpose} action is undefined: {reference}")
            if target["kind"] != "external_observe" or target["idempotency"] != "read_only":
                raise ContractError(f"{action_id} {purpose} action must be read-only external_observe")

    for logical_name, action_id in actions.items():
        definition = validated_definitions[action_id]
        if logical_name in {"release", "publish", "deploy", "rollback"} and definition["kind"] != "external_mutation":
            raise ContractError(f"{logical_name} must resolve to an external_mutation action")
        if logical_name == "build" and definition["kind"] != "pure":
            raise ContractError("build must resolve to a pure action")
        if logical_name == "release_metadata":
            if definition["kind"] != "pure":
                raise ContractError("release_metadata must resolve to a pure action")
            if definition["secret_refs"]:
                raise ContractError("release_metadata must not reference secrets")
        if logical_name in {"release", "publish"}:
            required_metadata_env = {
                "NM_V6_RELEASE_TAG",
                "NM_V6_RELEASE_VERSION",
                "NM_V6_RELEASE_METADATA_DIGEST",
            }
            missing_metadata_env = sorted(
                required_metadata_env - set(definition["core_injected_env"])
            )
            if missing_metadata_env:
                raise ContractError(
                    f"{logical_name} must declare release metadata injection: "
                    + ", ".join(missing_metadata_env)
                )
    environments = value["delivery"]["environments"]
    for environment_name, environment in environments.items():
        for field in ("identity_probe", "preflight", "health", "post_rollback_verify"):
            if validated_definitions[environment[field]]["kind"] != "external_observe":
                raise ContractError(f"{environment_name}.{field} must be external_observe")
        for field in ("deploy", "rollback"):
            if validated_definitions[environment[field]]["kind"] != "external_mutation":
                raise ContractError(f"{environment_name}.{field} must be external_mutation")

    if "adapters" in value:
        adapters = _mapping(value["adapters"], subject="adapters")
        if "configured" in adapters:
            reject_unknown_keys(
                adapters,
                ("protocol_version", "configured", "real_cli_smoke_tests"),
                subject="adapters",
            )
            validate_schema_version(
                adapters.get("protocol_version"),
                "nm-v6/adapter-request-v1",
                subject="adapters.protocol_version",
            )
            configured = _unique_strings(adapters["configured"], subject="adapters.configured", allow_empty=False)
            if not set(configured).issubset({"codex", "grok", "claude", "fake"}):
                raise ContractError("adapters.configured contains an unsupported provider")
            if adapters.get("real_cli_smoke_tests") != "opt_in_only":
                raise ContractError("real adapter smoke tests must be opt_in_only")
        else:
            for adapter_id, adapter in adapters.items():
                item = _mapping(adapter, subject=f"adapters.{adapter_id}")
                require_keys(item, ("protocol_version", "provider"), subject=f"adapters.{adapter_id}")
                validate_schema_version(
                    item["protocol_version"], "nm-v6/adapter-config-v1", subject=f"adapters.{adapter_id}.protocol_version"
                )
                if item["provider"] not in {"codex", "grok", "claude", "fake"}:
                    raise ContractError(f"adapters.{adapter_id}.provider is unsupported")
                _reject_secret_material(item, path=f"adapters.{adapter_id}")
    if "version_constraints" in value:
        constraints = _mapping(value["version_constraints"], subject="version_constraints")
        for component, constraint in constraints.items():
            _nonempty_string(component, subject="version constraint component")
            text = _nonempty_string(constraint, subject=f"version_constraints.{component}")
            if text in {"*", "latest", "any"}:
                raise ContractError(f"version_constraints.{component} is not constrained")
    for field, schema_version in (
        ("authorization", "nm-v6/authorization-config-v1"),
        ("evidence", "nm-v6/evidence-config-v1"),
    ):
        if field not in value:
            continue
        extension = _mapping(value[field], subject=field)
        require_keys(extension, ("schema_version",), subject=field)
        validate_schema_version(extension["schema_version"], schema_version, subject=f"{field}.schema_version")
        _reject_secret_material(extension, path=field)
    if "supply_chain" in value:
        _validate_supply_chain_policy(value["supply_chain"])
    return dict(value)


def validate_action_result(
    result: Mapping[str, Any],
    *,
    definition: Mapping[str, Any] | None = None,
    expected_operation_id: str | None = None,
) -> dict[str, Any]:
    """Validate a structured action result, including success conditionals."""

    value = _mapping(result, subject="action result")
    require_keys(value, ACTION_RESULT_KEYS, subject="action result")
    reject_unknown_keys(value, ACTION_RESULT_KEYS, subject="action result")
    validate_schema_version(value["protocol_version"], "nm-v6/action-result-v1", subject="protocol_version")
    action_id = _nonempty_string(value["action_id"], subject="action_id")
    validated_definition = (
        validate_action_definition(definition, expected_id=action_id)
        if definition is not None
        else None
    )
    raw_operation_id = value["operation_id"]
    operation_id = (
        None
        if raw_operation_id is None
        else _operation_id(raw_operation_id)
    )
    if expected_operation_id is not None and operation_id != expected_operation_id:
        raise ContractError("action result operation_id does not match the persisted Operation")
    if (
        validated_definition is not None
        and validated_definition["kind"] == "external_mutation"
        and operation_id is None
    ):
        raise ContractError("external mutation result requires a canonical operation_id")
    status = value["status"]
    if status not in {"succeeded", "failed", "partial", "unknown"}:
        raise ContractError("action result status is unsupported")
    for field in ("effect_id", "environment_id", "environment_fingerprint"):
        if value[field] is not None and not isinstance(value[field], str):
            raise ContractError(f"{field} must be string or null")
    _digest(value["artifact_digest"], subject="artifact_digest", nullable=True)
    _mapping(value["observed_state"], subject="observed_state")
    started = _rfc3339(value["started_at"], subject="started_at")
    finished = _rfc3339(value["finished_at"], subject="finished_at")
    if datetime.fromisoformat(finished.replace("Z", "+00:00")) < datetime.fromisoformat(started.replace("Z", "+00:00")):
        raise ContractError("finished_at precedes started_at")
    _mapping(value["diagnostics"], subject="diagnostics")
    redactions = _array(value["redactions"], subject="redactions")
    if not all(isinstance(item, (str, Mapping)) for item in redactions):
        raise ContractError("redactions entries must be strings or objects")
    if validated_definition is not None:
        validated = validated_definition
        if status == "succeeded":
            if validated["kind"] == "external_mutation" and not value["effect_id"]:
                raise ContractError("successful external mutation requires effect_id")
            if action_id == "build" and not value["artifact_digest"]:
                raise ContractError("successful build requires artifact_digest")
            if action_id in {"release", "publish"} and not value["artifact_digest"]:
                raise ContractError(f"successful {action_id} requires artifact_digest")
            if action_id in {"deploy", "rollback"} and (
                not value["environment_id"] or not value["environment_fingerprint"]
            ):
                raise ContractError(f"successful {action_id} requires environment identity fields")
    return dict(value)


def validate_adapter_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the provider-neutral request envelope and capability boundary."""

    value = _mapping(request, subject="adapter request")
    require_keys(value, ADAPTER_REQUEST_KEYS, subject="adapter request")
    reject_unknown_keys(value, ADAPTER_REQUEST_KEYS, subject="adapter request")
    validate_schema_version(value["protocol_version"], "nm-v6/adapter-request-v1", subject="protocol_version")
    _operation_id(value["operation_id"])
    _nonempty_string(value["run_id"], subject="run_id")
    _attempt_id(value["attempt_id"])
    _nonempty_string(value["role"], subject="role")
    workspace = _nonempty_string(value["workspace"], subject="workspace")
    if not Path(workspace).is_absolute():
        raise ContractError("adapter workspace must be an absolute isolated path")
    validate_context_manifest(_mapping(value["context_manifest"], subject="context_manifest"))
    validate_schema_version(
        value["expected_output_schema"],
        "nm-v6/adapter-result-v1",
        subject="expected_output_schema",
    )
    _rfc3339(value["deadline"], subject="deadline")
    _nonnegative_int(value["fencing_token"], subject="fencing_token")
    capabilities = _unique_strings(value["allowed_capabilities"], subject="allowed_capabilities")
    forbidden = sorted(capability for capability in capabilities if FORBIDDEN_AGENT_CAPABILITY_RE.search(capability))
    if forbidden:
        raise ContractError("adapter request grants prohibited capabilities: " + ", ".join(forbidden))
    _reject_secret_material(value, path="adapter request")
    return dict(value)


def validate_adapter_result(
    result: Mapping[str, Any],
    *,
    request: Mapping[str, Any] | None = None,
) -> AdapterResult:
    """Validate and normalize a provider-neutral result envelope."""

    value = _mapping(result, subject="adapter result")
    require_keys(value, ADAPTER_RESULT_KEYS, subject="adapter result")
    reject_unknown_keys(value, ADAPTER_RESULT_KEYS, subject="adapter result")
    validate_schema_version(value["protocol_version"], "nm-v6/adapter-result-v1", subject="protocol_version")
    operation_id = _operation_id(value["operation_id"])
    attempt_id = _attempt_id(value["attempt_id"])
    if request is not None:
        validated_request = validate_adapter_request(request)
        if operation_id != validated_request["operation_id"]:
            raise ContractError("adapter result operation_id is stale or mismatched")
        if attempt_id != validated_request["attempt_id"]:
            raise ContractError("adapter result attempt_id is stale or mismatched")
    status = value["status"]
    if status not in {"succeeded", "failed", "cancelled", "partial", "unknown"}:
        raise ContractError("adapter result status is unsupported")
    for field in ("session_id", "candidate_commit"):
        if value[field] is not None and not isinstance(value[field], str):
            raise ContractError(f"{field} must be string or null")
    if value["candidate_commit"] is not None and not re.fullmatch(r"[0-9a-f]{40,64}", value["candidate_commit"]):
        raise ContractError("candidate_commit must be a full hexadecimal object id")
    changed_paths = _unique_strings(value["changed_paths"], subject="changed_paths")
    changed_paths = [ensure_relative_path(path, field="changed_paths entry") for path in changed_paths]
    observations = _array(value["observations"], subject="observations")
    followups = _array(value["requested_followups"], subject="requested_followups")
    if not all(isinstance(item, Mapping) for item in observations + followups):
        raise ContractError("observations and requested_followups must contain objects")
    usage = _mapping(value["usage"], subject="usage")
    diagnostics = _mapping(value["adapter_diagnostics"], subject="adapter_diagnostics")
    _reject_secret_material(value, path="adapter result")
    return AdapterResult(
        protocol_version=value["protocol_version"],
        operation_id=operation_id,
        attempt_id=attempt_id,
        status=status,
        session_id=value["session_id"],
        candidate_commit=value["candidate_commit"],
        changed_paths=tuple(changed_paths),
        observations=tuple(dict(item) for item in observations),
        requested_followups=tuple(dict(item) for item in followups),
        usage=dict(usage),
        diagnostics=dict(diagnostics),
    )


def adapter_result_to_dict(result: AdapterResult) -> dict[str, Any]:
    value = asdict(result)
    value["adapter_diagnostics"] = value.pop("diagnostics")
    for field in ("changed_paths", "observations", "requested_followups"):
        value[field] = list(value[field])
    return value


def validate_context_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate content digests, totals, path policy, and self digest."""

    value = _mapping(manifest, subject="context manifest")
    keys = {
        "schema_version",
        "attempt_id",
        "entries",
        "on_demand",
        "allowed_paths",
        "prohibited_paths",
        "expected_result_schema",
        "totals",
        "manifest_digest",
    }
    require_keys(value, keys, subject="context manifest")
    reject_unknown_keys(value, keys, subject="context manifest")
    validate_schema_version(value["schema_version"], "nm-v6/context-manifest-v1")
    _attempt_id(value["attempt_id"])
    entries = _array(value["entries"], subject="entries")
    on_demand = _array(value["on_demand"], subject="on_demand")
    seen_ids: set[str] = set()
    byte_total = 0
    token_total = 0
    for collection_name, collection, content_required in (
        ("entries", entries, True),
        ("on_demand", on_demand, False),
    ):
        for index, entry in enumerate(collection):
            item = _mapping(entry, subject=f"{collection_name}[{index}]")
            base_keys = {"entry_id", "kind", "source", "digest", "byte_size", "estimated_tokens"}
            allowed = base_keys | ({"content"} if content_required else set())
            require_keys(item, allowed, subject=f"{collection_name}[{index}]")
            reject_unknown_keys(item, allowed, subject=f"{collection_name}[{index}]")
            entry_id = _nonempty_string(item["entry_id"], subject="entry_id")
            if entry_id in seen_ids:
                raise ContractError(f"duplicate context entry_id: {entry_id}")
            seen_ids.add(entry_id)
            _nonempty_string(item["kind"], subject=f"{entry_id}.kind")
            _nonempty_string(item["source"], subject=f"{entry_id}.source")
            digest = _digest(item["digest"], subject=f"{entry_id}.digest")
            size = _nonnegative_int(item["byte_size"], subject=f"{entry_id}.byte_size")
            tokens = _nonnegative_int(item["estimated_tokens"], subject=f"{entry_id}.estimated_tokens")
            if content_required:
                content = _nonempty_string(item["content"], subject=f"{entry_id}.content")
                encoded = content.encode("utf-8")
                if len(encoded) != size or digest.removeprefix("sha256:") != sha256_bytes(encoded):
                    raise ContractError(f"{entry_id} content address does not match content")
                byte_total += size
                token_total += tokens
    allowed_paths = _unique_strings(value["allowed_paths"], subject="allowed_paths")
    prohibited_paths = _unique_strings(value["prohibited_paths"], subject="prohibited_paths")
    for path in allowed_paths + prohibited_paths:
        ensure_relative_path(path, field="context path policy")
    if set(allowed_paths) & set(prohibited_paths):
        raise ContractError("a context path cannot be both allowed and prohibited")
    validate_schema_version(
        value["expected_result_schema"], "nm-v6/adapter-result-v1", subject="expected_result_schema"
    )
    totals = _mapping(value["totals"], subject="totals")
    require_keys(totals, ("byte_size", "estimated_tokens"), subject="totals")
    reject_unknown_keys(totals, ("byte_size", "estimated_tokens"), subject="totals")
    if totals["byte_size"] != byte_total or totals["estimated_tokens"] != token_total:
        raise ContractError("context totals do not match included entries")
    expected_digest = "sha256:" + sha256_bytes(
        canonical_json({key: nested for key, nested in value.items() if key != "manifest_digest"})
    )
    if value["manifest_digest"] != expected_digest:
        raise ContractError("context manifest_digest is invalid")
    return dict(value)


def validate_status_document(status: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(status, subject="status document")
    required = {
        "schema_version",
        "run_id",
        "revision",
        "state",
        "mode",
        "spec_hash",
        "config_hash",
        "last_event_sequence",
        "updated_at",
        "attention_required",
    }
    require_keys(value, required, subject="status document")
    reject_unknown_keys(value, required | {"active_phase_id", "active_task_ids", "summary"}, subject="status document")
    validate_schema_version(value["schema_version"], "nm-v6/status-v1")
    _nonempty_string(value["run_id"], subject="run_id")
    _nonnegative_int(value["revision"], subject="revision")
    _nonempty_string(value["state"], subject="state")
    if value["mode"] not in {"staged", "auto"}:
        raise ContractError("status mode must be staged|auto")
    _digest(value["spec_hash"], subject="spec_hash")
    _digest(value["config_hash"], subject="config_hash")
    _nonnegative_int(value["last_event_sequence"], subject="last_event_sequence")
    _rfc3339(value["updated_at"], subject="updated_at")
    if not isinstance(value["attention_required"], bool):
        raise ContractError("attention_required must be boolean")
    return dict(value)


def validate_audit_export(export: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(export, subject="audit export")
    required = {
        "schema_version",
        "run_id",
        "exported_at",
        "first_sequence",
        "last_sequence",
        "head_digest",
        "records",
    }
    require_keys(value, required, subject="audit export")
    reject_unknown_keys(value, required, subject="audit export")
    validate_schema_version(value["schema_version"], "nm-v6/audit-export-v1")
    _nonempty_string(value["run_id"], subject="run_id")
    _rfc3339(value["exported_at"], subject="exported_at")
    first = _nonnegative_int(value["first_sequence"], subject="first_sequence")
    last = _nonnegative_int(value["last_sequence"], subject="last_sequence")
    _digest(value["head_digest"], subject="head_digest")
    records = _array(value["records"], subject="records")
    if records:
        if first <= 0 or last < first or len(records) != last - first + 1:
            raise ContractError("audit export sequence bounds do not match records")
    elif first != 0 or last != 0:
        raise ContractError("empty audit export must use zero sequence bounds")
    previous_sequence = first - 1
    for index, record in enumerate(records):
        item = _mapping(record, subject=f"records[{index}]")
        fields = {
            "sequence",
            "previous_digest",
            "event_digest",
            "event_type",
            "actor",
            "run_revision",
            "timestamp",
            "payload",
        }
        require_keys(item, fields, subject=f"records[{index}]")
        reject_unknown_keys(item, fields, subject=f"records[{index}]")
        sequence = _positive_int(item["sequence"], subject="audit sequence")
        if sequence != previous_sequence + 1:
            raise ContractError("audit export sequence is not contiguous")
        previous_sequence = sequence
        if item["previous_digest"] is not None:
            _digest(item["previous_digest"], subject="previous_digest")
        _digest(item["event_digest"], subject="event_digest")
        _nonempty_string(item["event_type"], subject="event_type")
        _nonempty_string(item["actor"], subject="actor")
        _nonnegative_int(item["run_revision"], subject="run_revision")
        _rfc3339(item["timestamp"], subject="timestamp")
        _mapping(item["payload"], subject="audit payload")
    if records and value["head_digest"].removeprefix("sha256:") != records[-1]["event_digest"].removeprefix("sha256:"):
        raise ContractError("audit head_digest does not match the last record")
    return dict(value)


def validate_version_record(record: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(record, subject="version record")
    required = {
        "schema_version",
        "python",
        "sqlite",
        "git",
        "core_cli",
        "schemas",
        "evaluator",
        "adapters",
    }
    require_keys(value, required, subject="version record")
    reject_unknown_keys(value, required, subject="version record")
    validate_schema_version(value["schema_version"], "nm-v6/version-record-v1")
    for field in ("python", "sqlite", "git", "core_cli", "evaluator"):
        _nonempty_string(value[field], subject=field)
    schemas = _mapping(value["schemas"], subject="schemas")
    adapters = _mapping(value["adapters"], subject="adapters")
    if not schemas:
        raise ContractError("version record must include schema versions")
    for group_name, group in (("schemas", schemas), ("adapters", adapters)):
        for name, version in group.items():
            _nonempty_string(name, subject=f"{group_name} component")
            _nonempty_string(version, subject=f"{group_name}.{name}")
    return dict(value)


def contract_digest(value: Mapping[str, Any]) -> str:
    """Return the canonical content address of a validated JSON contract."""

    return "sha256:" + sha256_bytes(canonical_json(value))
