"""Versioned argv/action-result contracts and isolated action execution."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .contracts import SAFE_INHERITED_ENV_NAMES
from .errors import ActionError, ContractError, IsolationError
from .failpoints import checkpoint
from .util import (
    IDENTIFIER_PATTERNS,
    ensure_relative_path,
    reject_unknown_keys,
    require_keys,
    safe_environment,
)
from .workspace import IsolationBackend, Workspace, require_isolation_backend


ACTION_SCHEMA = "nm-v6/action-v1"
ACTION_RESULT_SCHEMA = "nm-v6/action-result-v1"
ACTION_KINDS = frozenset({"pure", "external_observe", "external_mutation"})
RESULT_STATUSES = frozenset({"succeeded", "failed", "partial", "unknown"})
IDEMPOTENCY_MODES = frozenset({"not_applicable", "read_only", "required"})
_ACTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INTERPOLATION = re.compile(r"\$\(|\$\{|`")
_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_SHELL_EXECUTABLES = frozenset(
    {"sh", "bash", "zsh", "dash", "ksh", "fish", "cmd", "cmd.exe", "powershell", "pwsh"}
)

_ACTION_FIELDS = frozenset(
    {
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
)
_RESULT_FIELDS = frozenset(
    {
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
)


@dataclass(frozen=True)
class IdempotencyContract:
    mode: str
    operation_id_env: str | None


@dataclass(frozen=True)
class ActionDefinition:
    schema_version: str
    action_id: str
    kind: str
    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: int
    accepted_exit_codes: tuple[int, ...]
    env_allowlist: tuple[str, ...]
    core_injected_env: tuple[str, ...]
    secret_refs: tuple[str, ...]
    result_schema: str
    idempotency: IdempotencyContract
    observe_action_id: str | None
    reconcile_action_id: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ActionDefinition":
        if not isinstance(value, Mapping):
            raise ContractError("action definition must be an object")
        require_keys(value, _ACTION_FIELDS, subject="action definition")
        reject_unknown_keys(value, _ACTION_FIELDS, subject="action definition")
        if value["schema_version"] != ACTION_SCHEMA:
            raise ContractError(f"unsupported action schema: {value['schema_version']!r}")
        action_id = _validated_identifier(value["action_id"], field="action_id")
        kind = value["kind"]
        if kind not in ACTION_KINDS:
            raise ContractError(f"invalid action kind: {kind!r}")
        argv = _string_tuple(value["argv"], field="argv", nonempty=True)
        if Path(argv[0]).name.lower() in _SHELL_EXECUTABLES:
            raise ContractError("argv must not invoke a command shell")
        for argument in argv:
            if "\x00" in argument or "\n" in argument or "\r" in argument:
                raise ContractError("argv values cannot contain NUL or line terminators")
            if _INTERPOLATION.search(argument):
                raise ContractError("argv cannot contain shell interpolation syntax")
        cwd = _validated_cwd(value["cwd"])
        timeout = value["timeout_seconds"]
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
            raise ContractError("timeout_seconds must be an integer from 1 to 86400")
        exit_codes_raw = value["accepted_exit_codes"]
        if (
            not isinstance(exit_codes_raw, list)
            or not exit_codes_raw
            or any(isinstance(item, bool) or not isinstance(item, int) for item in exit_codes_raw)
        ):
            raise ContractError("accepted_exit_codes must be a nonempty integer array")
        accepted_exit_codes = tuple(dict.fromkeys(exit_codes_raw))
        env_allowlist = _environment_tuple(value["env_allowlist"], field="env_allowlist")
        unsupported_inherited = sorted(
            set(env_allowlist) - SAFE_INHERITED_ENV_NAMES
        )
        if unsupported_inherited:
            raise ContractError(
                "env_allowlist may inherit only non-sensitive process settings; "
                "project credentials must use secret_refs, not: "
                + ", ".join(unsupported_inherited)
            )
        core_injected_env = _environment_tuple(
            value["core_injected_env"], field="core_injected_env"
        )
        if set(env_allowlist) & set(core_injected_env):
            raise ContractError("inherited and core-injected environment names must be disjoint")
        secret_refs = _string_tuple(value["secret_refs"], field="secret_refs")
        if len(secret_refs) != len(set(secret_refs)):
            raise ContractError("secret_refs contains duplicates")
        for reference in secret_refs:
            _validated_identifier(reference, field="secret reference")
        if value["result_schema"] != ACTION_RESULT_SCHEMA:
            raise ContractError(f"unsupported action result schema: {value['result_schema']!r}")
        idempotency = _parse_idempotency(value["idempotency"], core_injected_env)
        observe = _optional_action_id(value.get("observe_action_id"), "observe_action_id")
        reconcile = _optional_action_id(
            value.get("reconcile_action_id"), "reconcile_action_id"
        )
        if kind == "external_mutation":
            if idempotency.mode != "required" or not idempotency.operation_id_env:
                raise ContractError("external_mutation requires Operation-ID idempotency")
            if not observe or not reconcile:
                raise ContractError(
                    "external_mutation requires observe_action_id and reconcile_action_id"
                )
        elif observe is not None or reconcile is not None:
            raise ContractError("only external_mutation may declare observe/reconcile actions")
        if kind == "external_observe" and idempotency.mode != "read_only":
            raise ContractError("external_observe actions must declare read_only idempotency")
        if kind == "pure" and idempotency.mode not in {"not_applicable", "read_only"}:
            raise ContractError("pure actions cannot require external-operation idempotency")
        return cls(
            ACTION_SCHEMA,
            action_id,
            kind,
            argv,
            cwd,
            timeout,
            accepted_exit_codes,
            env_allowlist,
            core_injected_env,
            secret_refs,
            ACTION_RESULT_SCHEMA,
            idempotency,
            observe,
            reconcile,
        )


@dataclass(frozen=True)
class ActionResult:
    protocol_version: str
    action_id: str
    operation_id: str | None
    status: str
    effect_id: str | None
    artifact_digest: str | None
    environment_id: str | None
    environment_fingerprint: str | None
    observed_state: dict[str, Any]
    started_at: str
    finished_at: str
    diagnostics: dict[str, Any]
    redactions: tuple[Any, ...]

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        definition: ActionDefinition,
        operation_id: str | None,
    ) -> "ActionResult":
        if not isinstance(value, Mapping):
            raise ActionError("action result must be a JSON object")
        try:
            require_keys(value, _RESULT_FIELDS, subject="action result")
            reject_unknown_keys(value, _RESULT_FIELDS, subject="action result")
        except ContractError as exc:
            raise ActionError(str(exc)) from exc
        if value["protocol_version"] != ACTION_RESULT_SCHEMA:
            raise ActionError("action result protocol version mismatch")
        if value["action_id"] != definition.action_id:
            raise ActionError("action result action_id mismatch")
        result_operation_id = value["operation_id"]
        if result_operation_id is not None and not isinstance(result_operation_id, str):
            raise ActionError("operation_id must be a string or null")
        if result_operation_id is not None and not IDENTIFIER_PATTERNS["operation"].fullmatch(
            result_operation_id
        ):
            raise ActionError("operation_id has invalid V6 identifier format")
        if result_operation_id != operation_id:
            raise ActionError("action result operation_id mismatch")
        status = value["status"]
        if status not in RESULT_STATUSES:
            raise ActionError(f"invalid action result status: {status!r}")
        for field in (
            "effect_id",
            "artifact_digest",
            "environment_id",
            "environment_fingerprint",
        ):
            if value[field] is not None and not isinstance(value[field], str):
                raise ActionError(f"{field} must be a string or null")
        if value["artifact_digest"] is not None and not _SHA256.fullmatch(
            value["artifact_digest"]
        ):
            raise ActionError("artifact_digest must be a lowercase SHA-256 digest or null")
        if not isinstance(value["observed_state"], dict):
            raise ActionError("observed_state must be an object")
        if not isinstance(value["diagnostics"], dict):
            raise ActionError("diagnostics must be an object")
        redactions_raw = value["redactions"]
        if not isinstance(redactions_raw, list) or not all(
            isinstance(item, (str, Mapping)) for item in redactions_raw
        ):
            raise ActionError("redactions must contain strings or objects")
        started = _validate_timestamp(value["started_at"], "started_at")
        finished = _validate_timestamp(value["finished_at"], "finished_at")
        if finished < started:
            raise ActionError("finished_at precedes started_at")
        if status == "succeeded" and definition.kind == "external_mutation":
            if not value["effect_id"]:
                raise ActionError("successful external mutation must identify its effect")
        return cls(
            ACTION_RESULT_SCHEMA,
            definition.action_id,
            result_operation_id,
            status,
            value["effect_id"],
            value["artifact_digest"],
            value["environment_id"],
            value["environment_fingerprint"],
            dict(value["observed_state"]),
            value["started_at"],
            value["finished_at"],
            dict(value["diagnostics"]),
            tuple(redactions_raw),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "action_id": self.action_id,
            "operation_id": self.operation_id,
            "status": self.status,
            "effect_id": self.effect_id,
            "artifact_digest": self.artifact_digest,
            "environment_id": self.environment_id,
            "environment_fingerprint": self.environment_fingerprint,
            "observed_state": self.observed_state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "diagnostics": self.diagnostics,
            "redactions": list(self.redactions),
        }


@dataclass(frozen=True)
class SecretValue:
    reference: str
    env_name: str
    value: str

    def __post_init__(self) -> None:
        if not _ACTION_ID.fullmatch(self.reference):
            raise ContractError(f"invalid secret reference: {self.reference!r}")
        if not _ENV_NAME.fullmatch(self.env_name):
            raise ContractError(f"invalid secret environment name: {self.env_name!r}")
        if not isinstance(self.value, str) or not self.value:
            raise ContractError("resolved secret must be a nonempty string")


class SecretResolver(Protocol):
    def __call__(self, reference: str) -> SecretValue: ...


class OperationRecorder(Protocol):
    def begin_operation(
        self,
        *,
        operation_id: str,
        action_id: str,
        idempotency_key: str,
        grant_id: str | None,
        grant_revision: int | None,
    ) -> Any: ...

    def finish_operation(
        self,
        *,
        operation_id: str,
        status: str,
        result: Mapping[str, Any] | None,
        error: str | None,
    ) -> Any: ...


class ActionExecutor:
    """Execute one structured action without shell or ambient credentials."""

    def __init__(
        self,
        *,
        isolation_backend: IsolationBackend | None = None,
        environment: Mapping[str, str] | None = None,
        secret_resolver: SecretResolver | None = None,
    ) -> None:
        self.isolation_backend = isolation_backend
        self.environment = dict(os.environ if environment is None else environment)
        self.secret_resolver = secret_resolver

    def execute(
        self,
        definition: ActionDefinition,
        *,
        workspace: Workspace | Path,
        operation_id: str | None,
        core_env: Mapping[str, str] | None = None,
        recorder: OperationRecorder | None = None,
        grant_id: str | None = None,
        grant_revision: int | None = None,
        allow_network: bool = False,
    ) -> ActionResult:
        root = workspace.path if isinstance(workspace, Workspace) else workspace
        root = root.resolve()
        relative_cwd = _validated_cwd(definition.cwd)
        cwd = (root / relative_cwd).resolve()
        try:
            cwd.relative_to(root)
        except ValueError as exc:
            raise IsolationError("action cwd escapes its disposable workspace") from exc
        if not cwd.is_dir():
            raise ActionError(f"action cwd does not exist: {definition.cwd}")

        unsupported_inherited = sorted(
            set(definition.env_allowlist) - SAFE_INHERITED_ENV_NAMES
        )
        if unsupported_inherited:
            raise ActionError(
                "action cannot inherit sensitive or unsupported environment names: "
                + ", ".join(unsupported_inherited)
            )

        injected = dict(core_env or {})
        undeclared = sorted(set(injected) - set(definition.core_injected_env))
        if undeclared:
            raise ActionError(f"undeclared core environment names: {', '.join(undeclared)}")
        expected_operation_env = definition.idempotency.operation_id_env
        if operation_id is not None and definition.kind == "pure":
            raise ActionError("pure action must not receive an external operation_id")
        if expected_operation_env:
            if not operation_id:
                raise ActionError("idempotent external action requires an operation_id")
            current = injected.get(expected_operation_env)
            if current not in {None, operation_id}:
                raise ActionError("core Operation-ID injection does not match operation_id")
            injected[expected_operation_env] = operation_id
        elif operation_id is not None:
            candidates = [
                name
                for name in definition.core_injected_env
                if "OPERATION" in name.upper() and "ID" in name.upper()
            ]
            if len(candidates) == 1:
                current = injected.get(candidates[0])
                if current not in {None, operation_id}:
                    raise ActionError("core Operation-ID injection does not match operation_id")
                injected[candidates[0]] = operation_id
        missing_injected = sorted(set(definition.core_injected_env) - set(injected))
        if missing_injected:
            raise ActionError(
                f"missing required core environment names: {', '.join(missing_injected)}"
            )

        secrets = self._resolve_secrets(definition)
        for secret in secrets:
            if (
                secret.env_name in injected
                or secret.env_name in definition.env_allowlist
                or secret.env_name in {"PATH", "LANG", "LC_ALL"}
            ):
                raise ActionError("secret environment collides with another environment source")
            injected[secret.env_name] = secret.value
        environment = safe_environment(
            inherit=definition.env_allowlist,
            injected=injected,
            source=self.environment,
        )
        action_tmp = root / ".nm-action-tmp"
        action_tmp.mkdir(mode=0o700, exist_ok=True)
        environment["TMPDIR"] = str(action_tmp)
        backend = require_isolation_backend(self.isolation_backend)
        isolated = backend.wrap(
            definition.argv,
            workspace=root,
            cwd=cwd,
            allow_network=allow_network,
        )

        if definition.kind == "external_mutation":
            if recorder is None:
                raise ActionError("external mutation must be persisted before invocation")
            if grant_id is None or grant_revision is None:
                raise ActionError("external mutation must bind a persisted authorization revision")
            operation_record = recorder.begin_operation(
                operation_id=operation_id or "",
                action_id=definition.action_id,
                idempotency_key=operation_id or "",
                grant_id=grant_id,
                grant_revision=grant_revision,
            )
            if isinstance(operation_record, Mapping) and operation_record.get("_replayed"):
                raise ActionError(
                    "external operation ID already exists; observe/reconcile instead of invoking again"
                )

        checkpoint("action.before_invoke")
        checkpoint(f"action.{definition.action_id}.before_invoke")

        try:
            completed = subprocess.run(
                list(isolated.argv),
                cwd=isolated.cwd,
                env=environment,
                text=True,
                capture_output=True,
                timeout=definition.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            if recorder is not None and definition.kind == "external_mutation":
                recorder.finish_operation(
                    operation_id=operation_id or "",
                    status="unknown",
                    result=None,
                    error="action timed out; observe/reconcile required",
                )
            raise ActionError("action timed out; external state is unknown") from exc
        except OSError as exc:
            if recorder is not None and definition.kind == "external_mutation":
                recorder.finish_operation(
                    operation_id=operation_id or "",
                    status="unknown",
                    result=None,
                    error="action process could not be observed",
                )
            raise ActionError(f"cannot execute isolated action: {exc}") from exc

        checkpoint(f"action.{definition.action_id}.after_invoke")
        checkpoint("action.after_invoke")

        if self._contains_secret(completed.stdout, secrets) or self._contains_secret(
            completed.stderr, secrets
        ):
            if recorder is not None and definition.kind == "external_mutation":
                recorder.finish_operation(
                    operation_id=operation_id or "",
                    status="unknown",
                    result=None,
                    error="action output contained secret material",
                )
            raise ActionError("action output contained secret material and was discarded")
        if completed.returncode not in definition.accepted_exit_codes:
            status = "unknown" if definition.kind == "external_mutation" else "failed"
            if recorder is not None and definition.kind == "external_mutation":
                recorder.finish_operation(
                    operation_id=operation_id or "",
                    status=status,
                    result=None,
                    error=f"action exited {completed.returncode}",
                )
            raise ActionError(f"action exited with unaccepted code {completed.returncode}")
        try:
            raw = json.loads(completed.stdout)
        except (json.JSONDecodeError, UnicodeError) as exc:
            if recorder is not None and definition.kind == "external_mutation":
                recorder.finish_operation(
                    operation_id=operation_id or "",
                    status="unknown",
                    result=None,
                    error="malformed structured result",
                )
            raise ActionError("action did not return one valid JSON result") from exc
        result = ActionResult.from_mapping(raw, definition=definition, operation_id=operation_id)
        if recorder is not None and definition.kind == "external_mutation":
            reported_status = (
                "partial" if result.status in {"succeeded", "partial"} else "unknown"
            )
            recorder.finish_operation(
                operation_id=operation_id or "",
                status=reported_status,
                result=result.as_dict(),
                error="action result is advisory until independently observed",
            )
        return result

    def _resolve_secrets(self, definition: ActionDefinition) -> tuple[SecretValue, ...]:
        if not definition.secret_refs:
            return ()
        if self.secret_resolver is None:
            raise ActionError("action declares secrets but no resolver is available")
        resolved: list[SecretValue] = []
        for reference in definition.secret_refs:
            value = self.secret_resolver(reference)
            if value.reference != reference:
                raise ActionError("secret resolver returned a different reference")
            resolved.append(value)
        names = [value.env_name for value in resolved]
        if len(names) != len(set(names)):
            raise ActionError("resolved secret environment names collide")
        return tuple(resolved)

    @staticmethod
    def _contains_secret(output: str, secrets: Sequence[SecretValue]) -> bool:
        return any(secret.value and secret.value in output for secret in secrets)


def validate_action_registry(
    definitions: Mapping[str, Mapping[str, Any]],
) -> dict[str, ActionDefinition]:
    if not isinstance(definitions, Mapping):
        raise ContractError("action_definitions must be an object")
    parsed: dict[str, ActionDefinition] = {}
    for key, raw in definitions.items():
        if not isinstance(key, str):
            raise ContractError("action definition keys must be strings")
        definition = ActionDefinition.from_mapping(raw)
        if definition.action_id != key:
            raise ContractError(f"action definition key does not match action_id: {key!r}")
        parsed[key] = definition
    for definition in parsed.values():
        for field, reference in (
            ("observe_action_id", definition.observe_action_id),
            ("reconcile_action_id", definition.reconcile_action_id),
        ):
            if reference is None:
                continue
            target = parsed.get(reference)
            if target is None:
                raise ContractError(f"{field} references unknown action: {reference}")
            if field == "observe_action_id" and target.kind != "external_observe":
                raise ContractError("observe_action_id must reference external_observe")
            if field == "reconcile_action_id" and target.kind != "external_observe":
                raise ContractError("reconcile_action_id must reference an idempotent observe action")
    return parsed


def _parse_idempotency(value: Any, injected: tuple[str, ...]) -> IdempotencyContract:
    if isinstance(value, str):
        mode = value
        operation_env = None
        if mode == "required":
            candidates = [name for name in injected if "OPERATION" in name.upper() and "ID" in name.upper()]
            if len(candidates) != 1:
                raise ContractError(
                    "required idempotency must declare exactly one Operation-ID injection"
                )
            operation_env = candidates[0]
    elif isinstance(value, Mapping):
        require_keys(value, ("mode", "operation_id_env"), subject="idempotency")
        reject_unknown_keys(value, ("mode", "operation_id_env"), subject="idempotency")
        mode = value["mode"]
        operation_env = value["operation_id_env"]
        if operation_env is not None and (
            not isinstance(operation_env, str) or not _ENV_NAME.fullmatch(operation_env)
        ):
            raise ContractError("operation_id_env must be a valid environment name or null")
    else:
        raise ContractError("idempotency must be a mode string or versioned object")
    if mode not in IDEMPOTENCY_MODES:
        raise ContractError(f"invalid idempotency mode: {mode!r}")
    if mode == "required":
        if not operation_env or operation_env not in injected:
            raise ContractError("required idempotency Operation-ID env must be core-injected")
    elif operation_env is not None:
        raise ContractError("only required idempotency may declare operation_id_env")
    return IdempotencyContract(mode, operation_env)


def _validated_identifier(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _ACTION_ID.fullmatch(value):
        raise ContractError(f"{field} must be a stable identifier")
    return value


def _optional_action_id(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _validated_identifier(value, field=field)


def _string_tuple(value: Any, *, field: str, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ContractError(f"{field} must be a string array")
    if nonempty and not value:
        raise ContractError(f"{field} must not be empty")
    return tuple(value)


def _environment_tuple(value: Any, *, field: str) -> tuple[str, ...]:
    values = _string_tuple(value, field=field)
    if len(values) != len(set(values)):
        raise ContractError(f"{field} contains duplicates")
    if any(not _ENV_NAME.fullmatch(item) for item in values):
        raise ContractError(f"{field} contains an invalid environment name")
    return values


def _validate_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ActionError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ActionError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ActionError(f"{field} must include a timezone")
    return parsed


def _validated_cwd(value: Any) -> str:
    if value == ".":
        return "."
    if not isinstance(value, str):
        raise ContractError("action cwd must be a repository-relative directory")
    return ensure_relative_path(value, field="action cwd")
