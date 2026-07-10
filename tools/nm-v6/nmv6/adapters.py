"""Provider-neutral agent adapters with isolated provider command details."""

from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .contracts import (
    adapter_result_to_dict,
    validate_adapter_request,
    validate_adapter_result,
)
from .cleanup_review import (
    CLEANUP_REVIEW_CONTEXT_SOURCE,
    deterministic_fake_cleanup_review,
    validate_cleanup_review_context,
    validate_cleanup_review_request,
)
from .errors import ContractError
from .merge_review import (
    MERGE_REVIEW_CONTEXT_SOURCE,
    deterministic_fake_merge_review,
    validate_merge_review_context,
    validate_merge_review_request,
)
from .models import AdapterResult
from .util import (
    atomic_write,
    canonical_json,
    dump_json,
    load_json,
    safe_environment,
    sha256_bytes,
    utc_now,
)
from .workspace import IsolationBackend, require_isolation_backend


@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    executable: str
    version_args: tuple[str, ...]
    adapter_version: str
    headless: bool
    structured_output: bool
    resume: bool
    cancellation: bool
    native_subagents: bool
    background_tasks: bool
    sandbox_modes: tuple[str, ...]
    instruction_sources: tuple[str, ...]
    size_limits: Mapping[str, int | None]


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    stdin_text: str | None


class AdapterBackend(Protocol):
    def probe(self, profile: ProviderProfile) -> Mapping[str, Any]: ...

    def start(
        self,
        profile: ProviderProfile,
        request: Mapping[str, Any],
        invocation: Invocation,
    ) -> str: ...

    def poll(self, session_id: str) -> Mapping[str, Any]: ...

    def cancel(self, session_id: str) -> Mapping[str, Any]: ...

    def collect(self, session_id: str) -> Mapping[str, Any]: ...

    def request(
        self, profile: ProviderProfile, session_id: str
    ) -> Mapping[str, Any]: ...


def _probe_document(
    profile: ProviderProfile,
    *,
    available: bool,
    cli_version: str | None,
    authentication_ready: bool | None,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "protocol_version": "nm-v6/adapter-probe-v1",
        "adapter_id": profile.provider,
        "adapter_version": profile.adapter_version,
        "cli_version": cli_version,
        "available": available,
        "authentication_ready": authentication_ready,
        "capabilities": {
            "headless": profile.headless,
            "structured_output": profile.structured_output,
            "resume": profile.resume,
            "cancellation": profile.cancellation,
            "native_subagents": profile.native_subagents,
            "background_tasks": profile.background_tasks,
            "sandbox_modes": list(profile.sandbox_modes),
        },
        "instruction_sources": list(profile.instruction_sources),
        "size_limits": dict(profile.size_limits),
        "diagnostics": dict(diagnostics or {}),
    }


_SESSION_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "session_id",
        "provider",
        "adapter_version",
        "request",
        "request_digest",
        "invocation_digest",
        "pid",
        "process_identity",
        "status",
        "cancel_requested",
        "exit_code",
        "recovery_reason",
        "created_at",
        "updated_at",
    }
)
_SESSION_STATUSES = frozenset(
    {"starting", "running", "finished", "cancelled", "unknown"}
)


class _DurableSessionJournal:
    """Controller-owned adapter state that is never placed in an agent workspace."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def require_outside(self, workspace: Path) -> None:
        workspace = workspace.resolve()
        if self.root == workspace or self.root.is_relative_to(workspace):
            raise ContractError("adapter session state must stay outside the agent workspace")

    def _session_root(self, session_id: str) -> Path:
        if not session_id.startswith("SESSION-") or "/" in session_id:
            raise ContractError(f"invalid adapter session identifier: {session_id!r}")
        return self.root / session_id

    def record_path(self, session_id: str) -> Path:
        return self._session_root(session_id) / "session.json"

    def stdin_path(self, session_id: str) -> Path:
        return self._session_root(session_id) / "stdin.json"

    def stdout_path(self, session_id: str) -> Path:
        return self._session_root(session_id) / "stdout.log"

    def stderr_path(self, session_id: str) -> Path:
        return self._session_root(session_id) / "stderr.log"

    def result_path(self, session_id: str) -> Path:
        return self._session_root(session_id) / "result.json"

    def create(self, record: Mapping[str, Any]) -> bool:
        session_id = str(record["session_id"])
        session_root = self._session_root(session_id)
        try:
            session_root.mkdir(mode=0o700)
        except FileExistsError:
            return False
        atomic_write(self.record_path(session_id), dump_json(dict(record)), mode=0o600)
        return True

    def load(self, session_id: str) -> dict[str, Any]:
        value = load_json(self.record_path(session_id))
        if not isinstance(value, Mapping) or set(value) != _SESSION_RECORD_FIELDS:
            raise ContractError("adapter session journal record is incomplete or unknown")
        record = dict(value)
        if (
            record.get("schema_version") != "nm-v6/adapter-session-journal-v1"
            or record.get("session_id") != session_id
            or record.get("status") not in _SESSION_STATUSES
        ):
            raise ContractError("adapter session journal record is invalid")
        request = validate_adapter_request(record.get("request"))
        if sha256_bytes(canonical_json(request)) != record.get("request_digest"):
            raise ContractError("adapter session request differs from its durable digest")
        workspace = Path(str(request["workspace"])).resolve()
        self.require_outside(workspace)
        return record

    def update(self, session_id: str, **changes: Any) -> dict[str, Any]:
        unknown = sorted(set(changes) - _SESSION_RECORD_FIELDS)
        if unknown:
            raise ContractError(
                "adapter session update has unknown fields: " + ", ".join(unknown)
            )
        record = self.load(session_id)
        record.update(changes)
        record["updated_at"] = utc_now()
        atomic_write(self.record_path(session_id), dump_json(record), mode=0o600)
        return record


class SubprocessBackend:
    """Isolated headless backend with restart-safe controller-owned session state."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        isolation_backend: IsolationBackend | None = None,
        state_root: Path | None = None,
    ) -> None:
        self.executable = executable
        self.isolation_backend = isolation_backend
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._session_requests: dict[str, Mapping[str, Any]] = {}
        self._configured_state_root = state_root.resolve() if state_root else None
        self._journal: _DurableSessionJournal | None = None

    def _executable(self, profile: ProviderProfile) -> str:
        return self.executable or profile.executable

    def probe(self, profile: ProviderProfile) -> Mapping[str, Any]:
        executable = self._executable(profile)
        resolved = shutil.which(executable)
        if resolved is None:
            return _probe_document(
                profile,
                available=False,
                cli_version=None,
                authentication_ready=False,
                diagnostics={"reason": "executable_not_found"},
            )
        try:
            result = subprocess.run(
                [resolved, *profile.version_args],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
                env=safe_environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return _probe_document(
                profile,
                available=False,
                cli_version=None,
                authentication_ready=False,
                diagnostics={"reason": type(exc).__name__},
            )
        output = (result.stdout or result.stderr).strip().splitlines()
        return _probe_document(
            profile,
            available=result.returncode == 0,
            cli_version=output[0][:256] if output else None,
            # A version probe cannot prove authentication without potentially
            # accessing credentials.  Unknown is explicit and fail-closed.
            authentication_ready=None,
            diagnostics={"version_probe_exit_code": result.returncode},
        )

    def start(
        self,
        profile: ProviderProfile,
        request: Mapping[str, Any],
        invocation: Invocation,
    ) -> str:
        validated = validate_adapter_request(request)
        executable = shutil.which(self._executable(profile))
        if executable is None:
            raise ContractError(f"{profile.provider} CLI is unavailable")
        argv = [executable, *invocation.argv]
        workspace = Path(str(validated["workspace"])).resolve()
        journal = self._journal_for_start(workspace)
        journal.require_outside(workspace)
        request_digest = sha256_bytes(canonical_json(validated))
        invocation_digest = sha256_bytes(
            canonical_json(
                {
                    "argv": list(invocation.argv),
                    "stdin_digest": (
                        sha256_bytes(invocation.stdin_text.encode("utf-8"))
                        if invocation.stdin_text is not None
                        else None
                    ),
                }
            )
        )
        identity = sha256_bytes(
            canonical_json(
                {
                    "provider": profile.provider,
                    "request_digest": request_digest,
                    "invocation_digest": invocation_digest,
                }
            )
        )[:24]
        session_id = f"SESSION-{profile.provider}-{identity}"
        timestamp = utc_now()
        initial = {
            "schema_version": "nm-v6/adapter-session-journal-v1",
            "session_id": session_id,
            "provider": profile.provider,
            "adapter_version": profile.adapter_version,
            "request": validated,
            "request_digest": request_digest,
            "invocation_digest": invocation_digest,
            "pid": None,
            "process_identity": None,
            "status": "starting",
            "cancel_requested": False,
            "exit_code": None,
            "recovery_reason": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        if not journal.create(initial):
            existing = journal.load(session_id)
            if (
                existing["provider"] != profile.provider
                or existing["adapter_version"] != profile.adapter_version
                or existing["request_digest"] != request_digest
                or existing["invocation_digest"] != invocation_digest
            ):
                raise ContractError("adapter session identity collided with other durable state")
            self._session_requests[session_id] = validated
            return session_id
        backend = require_isolation_backend(self.isolation_backend)
        isolated = backend.wrap(
            argv,
            workspace=workspace,
            cwd=workspace,
            allow_network="network" in validated["allowed_capabilities"],
        )
        stdin_stream: Any = subprocess.DEVNULL
        if invocation.stdin_text is not None:
            atomic_write(
                journal.stdin_path(session_id),
                invocation.stdin_text.encode("utf-8"),
                mode=0o600,
            )
            stdin_stream = journal.stdin_path(session_id).open("r", encoding="utf-8")
        stdout_stream = self._exclusive_text_output(journal.stdout_path(session_id))
        stderr_stream = self._exclusive_text_output(journal.stderr_path(session_id))
        try:
            process = subprocess.Popen(
                isolated.argv,
                cwd=isolated.cwd,
                env=safe_environment(
                    injected={"NM_V6_ADAPTER_SESSION_ID": session_id}
                ),
                text=True,
                stdin=stdin_stream,
                stdout=stdout_stream,
                stderr=stderr_stream,
                shell=False,
                start_new_session=True,
            )
        except BaseException as exc:
            journal.update(
                session_id,
                status="unknown",
                recovery_reason=f"spawn_failed:{type(exc).__name__}",
            )
            raise
        finally:
            if stdin_stream is not subprocess.DEVNULL:
                stdin_stream.close()
            stdout_stream.close()
            stderr_stream.close()
        self._processes[session_id] = process
        self._session_requests[session_id] = validated
        journal.update(
            session_id,
            pid=process.pid,
            process_identity=self._process_identity(process.pid),
            status="running",
        )
        return session_id

    @staticmethod
    def _exclusive_text_output(path: Path):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        return os.fdopen(descriptor, "w", encoding="utf-8")

    def _journal_for_start(self, workspace: Path) -> _DurableSessionJournal:
        if self._journal is None:
            root = self._configured_state_root or (
                workspace.parent / ".nm-v6-adapter-sessions"
            )
            self._journal = _DurableSessionJournal(root)
        return self._journal

    def _required_journal(self) -> _DurableSessionJournal:
        if self._journal is None:
            if self._configured_state_root is None:
                raise ContractError(
                    "adapter restart recovery requires the durable state_root"
                )
            self._journal = _DurableSessionJournal(self._configured_state_root)
        return self._journal

    @staticmethod
    def _process_identity(pid: int) -> str | None:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
            env=safe_environment(),
        )
        output = result.stdout.strip()
        if result.returncode != 0 or not output:
            return None
        state = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
            env=safe_environment(),
        ).stdout.strip()
        if not state or "Z" in state:
            return None
        return sha256_bytes(f"{pid}:{output}".encode("utf-8"))

    def _record(self, session_id: str) -> dict[str, Any]:
        return self._required_journal().load(session_id)

    def request(
        self, profile: ProviderProfile, session_id: str
    ) -> Mapping[str, Any]:
        record = self._record(session_id)
        if (
            record["provider"] != profile.provider
            or record["adapter_version"] != profile.adapter_version
        ):
            raise ContractError("adapter session belongs to another provider or version")
        return dict(record["request"])

    def _observe(self, session_id: str) -> dict[str, Any]:
        journal = self._required_journal()
        record = journal.load(session_id)
        if record["status"] in {"finished", "cancelled", "unknown"}:
            return record
        process = self._processes.get(session_id)
        if process is not None:
            returncode = process.poll()
            if returncode is None:
                if record["status"] != "running":
                    return journal.update(session_id, status="running")
                return record
            return journal.update(
                session_id,
                status="cancelled" if record["cancel_requested"] else "finished",
                exit_code=returncode,
            )
        pid = record.get("pid")
        expected_identity = record.get("process_identity")
        if not isinstance(pid, int) or not isinstance(expected_identity, str):
            return journal.update(
                session_id,
                status="unknown",
                recovery_reason="process_identity_was_not_persisted",
            )
        observed_identity = self._process_identity(pid)
        if observed_identity == expected_identity:
            return journal.update(session_id, status="running")
        if observed_identity is not None:
            return journal.update(
                session_id,
                status="unknown",
                recovery_reason="pid_identity_mismatch",
            )
        return journal.update(
            session_id,
            status="cancelled" if record["cancel_requested"] else "finished",
            recovery_reason=(
                "cancelled_after_controller_restart"
                if record["cancel_requested"]
                else "process_completed_after_controller_restart"
            ),
        )

    def poll(self, session_id: str) -> Mapping[str, Any]:
        record = self._observe(session_id)
        return {
            "session_id": session_id,
            "status": record["status"],
            "exit_code": record["exit_code"],
        }

    def cancel(self, session_id: str) -> Mapping[str, Any]:
        journal = self._required_journal()
        record = self._observe(session_id)
        if record["status"] != "running":
            return {
                "session_id": session_id,
                "status": record["status"],
                "exit_code": record["exit_code"],
            }
        record = journal.update(session_id, cancel_requested=True)
        process = self._processes.get(session_id)
        if process is not None:
            self._terminate_process_group(process.pid)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._kill_process_group(process.pid)
                process.wait(timeout=5)
            exit_code = process.returncode
        else:
            pid = int(record["pid"])
            if self._process_identity(pid) != record["process_identity"]:
                record = journal.update(
                    session_id,
                    status="unknown",
                    recovery_reason="process_identity_changed_before_cancel",
                )
                return {
                    "session_id": session_id,
                    "status": record["status"],
                    "exit_code": record["exit_code"],
                }
            self._terminate_process_group(pid)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and self._process_identity(pid) is not None:
                time.sleep(0.05)
            if self._process_identity(pid) is not None:
                self._kill_process_group(pid)
            exit_code = None
        record = journal.update(
            session_id,
            status="cancelled",
            exit_code=exit_code,
            recovery_reason=(
                "cancelled_after_controller_restart"
                if process is None
                else record.get("recovery_reason")
            ),
        )
        return {
            "session_id": session_id,
            "status": "cancelled",
            "exit_code": record["exit_code"],
        }

    @staticmethod
    def _terminate_process_group(pid: int) -> None:
        try:
            if os.getpgid(pid) != pid:
                raise ContractError("adapter process does not own its recorded process group")
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    @staticmethod
    def _kill_process_group(pid: int) -> None:
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    @staticmethod
    def _parse_structured_output(stdout: str) -> Mapping[str, Any]:
        candidates = [stdout.strip(), *reversed([line.strip() for line in stdout.splitlines()])]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                return value
        raise ContractError("adapter process did not produce a structured result envelope")

    def collect(self, session_id: str) -> Mapping[str, Any]:
        record = self._observe(session_id)
        if record["status"] == "running":
            raise ContractError(f"adapter session is still running: {session_id}")
        request = dict(record["request"])
        if record["status"] in {"cancelled", "unknown"}:
            return self._recovery_result(
                request,
                session_id,
                status=str(record["status"]),
                reason=str(record.get("recovery_reason") or record["status"]),
            )
        journal = self._required_journal()
        stdout_path = journal.stdout_path(session_id)
        stderr_path = journal.stderr_path(session_id)
        stdout = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
        stderr = stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else ""
        try:
            result = dict(self._parse_structured_output(stdout))
        except ContractError:
            if session_id in self._processes:
                raise
            return self._recovery_result(
                request,
                session_id,
                status="unknown",
                reason="process_lost_without_structured_result",
            )
        diagnostics = result.get("adapter_diagnostics")
        if isinstance(diagnostics, Mapping):
            diagnostics = dict(diagnostics)
        else:
            diagnostics = {}
        diagnostics.update(
            {
                "process_exit_code": record.get("exit_code"),
                "stderr_present": bool(stderr),
                "restart_recovered": session_id not in self._processes,
            }
        )
        result["adapter_diagnostics"] = diagnostics
        return result

    @staticmethod
    def _recovery_result(
        request: Mapping[str, Any],
        session_id: str,
        *,
        status: str,
        reason: str,
    ) -> Mapping[str, Any]:
        return {
            "protocol_version": "nm-v6/adapter-result-v1",
            "operation_id": request["operation_id"],
            "attempt_id": request["attempt_id"],
            "status": status,
            "session_id": session_id,
            "candidate_commit": None,
            "changed_paths": [],
            "observations": [],
            "requested_followups": [],
            "usage": {},
            "adapter_diagnostics": {"restart_recovery": reason},
        }


class MemoryBackend:
    """Deterministic fake backend with optional restart-safe session state."""

    def __init__(
        self,
        result_factory: Callable[[Mapping[str, Any], str], Mapping[str, Any]] | None = None,
        *,
        capabilities_override: Mapping[str, Any] | None = None,
        state_root: Path | None = None,
    ) -> None:
        self.result_factory = result_factory or self._default_result
        self.capabilities_override = dict(capabilities_override or {})
        self._sessions: dict[str, dict[str, Any]] = {}
        self._journal = _DurableSessionJournal(state_root) if state_root else None

    @staticmethod
    def _default_result(request: Mapping[str, Any], session_id: str) -> Mapping[str, Any]:
        if request.get("role") == "cleanup_reviewer":
            return MemoryBackend._cleanup_review_result(request, session_id)
        if request.get("role") == "merge_reviewer":
            return MemoryBackend._merge_review_result(request, session_id)
        configured = MemoryBackend._configured_candidate_result(request, session_id)
        if configured is not None:
            return configured
        return {
            "protocol_version": "nm-v6/adapter-result-v1",
            "operation_id": request["operation_id"],
            "attempt_id": request["attempt_id"],
            "status": "succeeded",
            "session_id": session_id,
            "candidate_commit": None,
            "changed_paths": [],
            "observations": [],
            "requested_followups": [],
            "usage": {},
            "adapter_diagnostics": {"backend": "memory"},
        }

    @staticmethod
    def _cleanup_review_result(
        request: Mapping[str, Any], session_id: str
    ) -> Mapping[str, Any]:
        if request.get("allowed_capabilities") != []:
            raise ContractError("fake cleanup reviewer requires zero capabilities")
        manifest = request.get("context_manifest")
        if not isinstance(manifest, Mapping):
            raise ContractError("fake cleanup reviewer context manifest is malformed")
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise ContractError("fake cleanup reviewer context entries are malformed")
        matching = [
            entry
            for entry in entries
            if isinstance(entry, Mapping)
            and entry.get("source") == CLEANUP_REVIEW_CONTEXT_SOURCE
        ]
        if len(matching) != 1:
            raise ContractError(
                "fake cleanup reviewer requires exactly one canonical request entry"
            )
        content = matching[0].get("content")
        if not isinstance(content, str) or not content:
            raise ContractError("fake cleanup reviewer request content is malformed")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ContractError("fake cleanup reviewer request is not valid JSON") from exc
        review_request = validate_cleanup_review_request(parsed)
        validate_cleanup_review_context(manifest, review_request)
        observation = deterministic_fake_cleanup_review(review_request)
        return {
            "protocol_version": "nm-v6/adapter-result-v1",
            "operation_id": request["operation_id"],
            "attempt_id": request["attempt_id"],
            "status": "succeeded",
            "session_id": session_id,
            "candidate_commit": None,
            "changed_paths": [],
            "observations": [observation],
            "requested_followups": [],
            "usage": {},
            "adapter_diagnostics": {
                "backend": "memory",
                "role": "cleanup_reviewer",
            },
        }

    @staticmethod
    def _merge_review_result(
        request: Mapping[str, Any], session_id: str
    ) -> Mapping[str, Any]:
        if request.get("allowed_capabilities") != []:
            raise ContractError("fake merge reviewer requires zero capabilities")
        manifest = request.get("context_manifest")
        if not isinstance(manifest, Mapping):
            raise ContractError("fake merge reviewer context manifest is malformed")
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise ContractError("fake merge reviewer context entries are malformed")
        matching = [
            entry
            for entry in entries
            if isinstance(entry, Mapping)
            and entry.get("source") == MERGE_REVIEW_CONTEXT_SOURCE
        ]
        if len(matching) != 1:
            raise ContractError(
                "fake merge reviewer requires exactly one canonical request entry"
            )
        content = matching[0].get("content")
        if not isinstance(content, str) or not content:
            raise ContractError("fake merge reviewer request content is malformed")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ContractError("fake merge reviewer request is not valid JSON") from exc
        review_request = validate_merge_review_request(parsed)
        validate_merge_review_context(manifest, review_request)
        observation = deterministic_fake_merge_review(review_request)
        return {
            "protocol_version": "nm-v6/adapter-result-v1",
            "operation_id": request["operation_id"],
            "attempt_id": request["attempt_id"],
            "status": "succeeded",
            "session_id": session_id,
            "candidate_commit": None,
            "changed_paths": [],
            "observations": [observation],
            "requested_followups": [],
            "usage": {},
            "adapter_diagnostics": {
                "backend": "memory",
                "role": "merge_reviewer",
            },
        }

    @staticmethod
    def _configured_candidate_result(
        request: Mapping[str, Any], session_id: str
    ) -> Mapping[str, Any] | None:
        """Create a deterministic fake candidate only for an explicit fixture marker."""

        workspace = Path(str(request["workspace"])).resolve()
        marker_path = workspace / ".nm-v6-fake-provider.json"
        if not marker_path.is_file():
            return None
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ContractError("fake provider marker is unreadable") from exc
        candidate = marker.get("adapter_candidate") if isinstance(marker, Mapping) else None
        if not isinstance(candidate, Mapping) or candidate.get("enabled") is not True:
            return None
        relative_value = candidate.get("path")
        content = candidate.get("content")
        if not isinstance(relative_value, str) or not relative_value:
            raise ContractError("fake provider candidate path must be a nonempty string")
        if not isinstance(content, str):
            raise ContractError("fake provider candidate content must be a string")
        relative = Path(relative_value)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative.parts[0] in {".git", ".nm"}
        ):
            raise ContractError("fake provider candidate path is unsafe")
        destination = (workspace / relative).resolve()
        try:
            destination.relative_to(workspace)
        except ValueError as exc:
            raise ContractError("fake provider candidate path escapes its workspace") from exc

        def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
            result = subprocess.run(
                ["git", *arguments],
                cwd=workspace,
                text=True,
                capture_output=True,
                check=False,
            )
            if check and result.returncode != 0:
                raise ContractError(
                    "fake provider Git command failed: "
                    + (result.stderr.strip() or result.stdout.strip() or "unknown error")
                )
            return result

        base_commit = git("rev-parse", "HEAD").stdout.strip()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        git("add", "--", relative.as_posix())
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return None
        git(
            "-c",
            "user.name=NM V6 Fake Adapter",
            "-c",
            "user.email=nm-v6-fake-adapter@example.invalid",
            "commit",
            "-m",
            "test: create deterministic adapter candidate",
        )
        candidate_commit = git("rev-parse", "HEAD").stdout.strip()
        changed_paths = tuple(
            sorted(
                path
                for path in git(
                    "diff", "--name-only", "-z", base_commit, candidate_commit, "--"
                ).stdout.split("\0")
                if path
            )
        )
        return {
            "protocol_version": "nm-v6/adapter-result-v1",
            "operation_id": request["operation_id"],
            "attempt_id": request["attempt_id"],
            "status": "succeeded",
            "session_id": session_id,
            "candidate_commit": candidate_commit,
            "changed_paths": list(changed_paths),
            "observations": [{"fixture": "configured_candidate"}],
            "requested_followups": [],
            "usage": {},
            "adapter_diagnostics": {"backend": "memory", "candidate": True},
        }

    def probe(self, profile: ProviderProfile) -> Mapping[str, Any]:
        document = _probe_document(
            profile,
            available=True,
            cli_version=f"fake-{profile.provider}-1.0",
            authentication_ready=True,
            diagnostics={"backend": "memory"},
        )
        document["capabilities"].update(self.capabilities_override)
        return document

    def start(
        self,
        profile: ProviderProfile,
        request: Mapping[str, Any],
        invocation: Invocation,
    ) -> str:
        validated = validate_adapter_request(request)
        workspace = Path(str(validated["workspace"])).resolve()
        request_digest = sha256_bytes(canonical_json(validated))
        invocation_digest = sha256_bytes(
            canonical_json(
                {
                    "backend": "memory",
                    "argv": list(invocation.argv),
                    "stdin_digest": (
                        sha256_bytes(invocation.stdin_text.encode("utf-8"))
                        if invocation.stdin_text is not None
                        else None
                    ),
                }
            )
        )
        identity = sha256_bytes(
            canonical_json(
                {
                    "provider": profile.provider,
                    "adapter_version": profile.adapter_version,
                    "request_digest": request_digest,
                    "invocation_digest": invocation_digest,
                }
            )
        )[:24]
        session_id = f"SESSION-{profile.provider}-{identity}"
        existing = self._sessions.get(session_id)
        if existing is not None:
            if (
                existing["provider"] != profile.provider
                or existing["adapter_version"] != profile.adapter_version
                or existing["request_digest"] != request_digest
                or existing["invocation_digest"] != invocation_digest
            ):
                raise ContractError("adapter session identity collided with other fake state")
            return session_id

        timestamp = utc_now()
        initial = {
            "schema_version": "nm-v6/adapter-session-journal-v1",
            "session_id": session_id,
            "provider": profile.provider,
            "adapter_version": profile.adapter_version,
            "request": validated,
            "request_digest": request_digest,
            "invocation_digest": invocation_digest,
            "pid": None,
            "process_identity": None,
            "status": "starting",
            "cancel_requested": False,
            "exit_code": None,
            "recovery_reason": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        if self._journal is not None:
            self._journal.require_outside(workspace)
            if not self._journal.create(initial):
                record = self._journal.load(session_id)
                if (
                    record["provider"] != profile.provider
                    or record["adapter_version"] != profile.adapter_version
                    or record["request_digest"] != request_digest
                    or record["invocation_digest"] != invocation_digest
                ):
                    raise ContractError(
                        "adapter session identity collided with other durable state"
                    )
                if record["status"] == "starting":
                    if self._journal.result_path(session_id).is_file():
                        self._journal.update(
                            session_id,
                            status="running",
                            recovery_reason="fake_result_recovered_after_restart",
                        )
                    else:
                        self._journal.update(
                            session_id,
                            status="unknown",
                            recovery_reason="fake_dispatch_outcome_unknown",
                        )
                return session_id
        else:
            # Claim the logical dispatch before invoking the fake. If the
            # factory raises after a side effect, the same request cannot be
            # dispatched again in this controller process.
            self._sessions[session_id] = dict(initial)

        try:
            result = dict(self.result_factory(validated, session_id))
        except BaseException as exc:
            if self._journal is not None:
                self._journal.update(
                    session_id,
                    status="unknown",
                    recovery_reason=f"fake_dispatch_failed:{type(exc).__name__}",
                )
            else:
                self._sessions[session_id].update(
                    status="unknown",
                    recovery_reason=f"fake_dispatch_failed:{type(exc).__name__}",
                )
            raise
        if self._journal is not None:
            atomic_write(
                self._journal.result_path(session_id),
                dump_json(result),
                mode=0o600,
            )
            self._journal.update(session_id, status="running")
        else:
            self._sessions[session_id].update(status="running", result=result)
        return session_id

    def _session(self, session_id: str) -> dict[str, Any]:
        if self._journal is not None:
            return self._journal.load(session_id)
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise ContractError(f"unknown adapter session: {session_id}") from exc

    def request(
        self, profile: ProviderProfile, session_id: str
    ) -> Mapping[str, Any]:
        session = self._session(session_id)
        if (
            session["provider"] != profile.provider
            or session["adapter_version"] != profile.adapter_version
        ):
            raise ContractError("adapter session belongs to another provider or version")
        return dict(session["request"])

    def poll(self, session_id: str) -> Mapping[str, Any]:
        session = self._session(session_id)
        if session["status"] == "running":
            if self._journal is not None:
                session = self._journal.update(session_id, status="finished", exit_code=0)
            else:
                session["status"] = "finished"
        return {"session_id": session_id, "status": session["status"], "exit_code": 0}

    def cancel(self, session_id: str) -> Mapping[str, Any]:
        session = self._session(session_id)
        if self._journal is not None:
            self._journal.update(session_id, status="cancelled", cancel_requested=True)
        else:
            session["status"] = "cancelled"
        return {"session_id": session_id, "status": "cancelled", "exit_code": None}

    def collect(self, session_id: str) -> Mapping[str, Any]:
        session = self._session(session_id)
        if session["status"] == "running":
            raise ContractError(f"adapter session is still running: {session_id}")
        if session["status"] == "cancelled":
            request = session["request"]
            return {
                "protocol_version": "nm-v6/adapter-result-v1",
                "operation_id": request["operation_id"],
                "attempt_id": request["attempt_id"],
                "status": "cancelled",
                "session_id": session_id,
                "candidate_commit": None,
                "changed_paths": [],
                "observations": [],
                "requested_followups": [],
                "usage": {},
                "adapter_diagnostics": {"backend": "memory"},
            }
        if session["status"] != "finished":
            return SubprocessBackend._recovery_result(
                session["request"],
                session_id,
                status="unknown",
                reason=str(session.get("recovery_reason") or session["status"]),
            )
        if self._journal is not None:
            result_path = self._journal.result_path(session_id)
            if not result_path.is_file():
                self._journal.update(
                    session_id,
                    status="unknown",
                    recovery_reason="fake_result_missing",
                )
                return SubprocessBackend._recovery_result(
                    session["request"],
                    session_id,
                    status="unknown",
                    reason="fake_result_missing",
                )
            result = load_json(result_path)
            if not isinstance(result, Mapping):
                raise ContractError("durable fake adapter result is invalid")
            return dict(result)
        return dict(session["result"])


class Adapter:
    """Logical V6 adapter. Provider details live in profiles/invocations."""

    profile: ProviderProfile

    def __init__(
        self,
        *,
        backend: AdapterBackend | None = None,
        executable: str | None = None,
        isolation_backend: IsolationBackend | None = None,
        state_root: Path | None = None,
    ) -> None:
        self.backend = backend or SubprocessBackend(
            executable=executable,
            isolation_backend=isolation_backend,
            state_root=state_root,
        )
        self._requests: dict[str, Mapping[str, Any]] = {}

    def probe(self) -> dict[str, Any]:
        result = dict(self.backend.probe(self.profile))
        if result.get("protocol_version") != "nm-v6/adapter-probe-v1":
            raise ContractError("adapter probe returned an unsupported protocol version")
        required = {
            "adapter_id",
            "adapter_version",
            "cli_version",
            "available",
            "authentication_ready",
            "capabilities",
            "instruction_sources",
            "size_limits",
            "diagnostics",
        }
        if not required.issubset(result):
            raise ContractError("adapter probe result is incomplete")
        return result

    def _invocation(self, request: Mapping[str, Any]) -> Invocation:
        raise NotImplementedError

    def start(self, request: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_adapter_request(request)
        session_id = self.backend.start(
            self.profile,
            validated,
            self._invocation(validated),
        )
        if not isinstance(session_id, str) or not session_id:
            raise ContractError("adapter backend returned an invalid session identifier")
        self._requests[session_id] = validated
        return {
            "protocol_version": "nm-v6/adapter-session-v1",
            "operation_id": validated["operation_id"],
            "attempt_id": validated["attempt_id"],
            "session_id": session_id,
            "status": "started",
        }

    def _request(self, session_id: str) -> Mapping[str, Any]:
        try:
            return self._requests[session_id]
        except KeyError as exc:
            resolver = getattr(self.backend, "request", None)
            if not callable(resolver):
                raise ContractError(
                    f"session does not belong to this adapter: {session_id}"
                ) from exc
            validated = validate_adapter_request(
                resolver(self.profile, session_id)
            )
            self._requests[session_id] = validated
            return validated

    def poll(self, session_id: str) -> dict[str, Any]:
        self._request(session_id)
        result = dict(self.backend.poll(session_id))
        if result.get("session_id") != session_id or result.get("status") not in {
            "running",
            "finished",
            "cancelled",
            "unknown",
        }:
            raise ContractError("adapter poll returned an invalid session observation")
        return result

    def cancel(self, session_id: str) -> dict[str, Any]:
        self._request(session_id)
        result = dict(self.backend.cancel(session_id))
        if result.get("session_id") != session_id or result.get("status") not in {
            "cancelled",
            "finished",
            "unknown",
        }:
            raise ContractError("adapter cancel returned an invalid observation")
        return result

    def collect(self, session_id: str) -> AdapterResult:
        request = self._request(session_id)
        raw = self.backend.collect(session_id)
        result = validate_adapter_result(raw, request=request)
        if result.session_id != session_id:
            raise ContractError("adapter result session_id is stale or mismatched")
        return result

    def collect_dict(self, session_id: str) -> dict[str, Any]:
        return adapter_result_to_dict(self.collect(session_id))


class CodexAdapter(Adapter):
    profile = ProviderProfile(
        provider="codex",
        executable="codex",
        version_args=("--version",),
        adapter_version="nm-v6/codex-adapter-v1",
        headless=True,
        structured_output=True,
        resume=False,
        cancellation=True,
        native_subagents=False,
        background_tasks=False,
        sandbox_modes=("read-only", "workspace-write"),
        instruction_sources=("AGENTS.md", ".codex/config.toml"),
        size_limits={},
    )

    def _invocation(self, request: Mapping[str, Any]) -> Invocation:
        return Invocation(("exec", "--json", "-"), canonical_json(request).decode("utf-8"))


class GrokAdapter(Adapter):
    profile = ProviderProfile(
        provider="grok",
        executable="grok",
        version_args=("--version",),
        adapter_version="nm-v6/grok-adapter-v1",
        headless=True,
        structured_output=True,
        resume=False,
        cancellation=True,
        native_subagents=False,
        background_tasks=False,
        sandbox_modes=("workspace",),
        instruction_sources=("GROK.md", "AGENTS.md"),
        size_limits={},
    )

    def _invocation(self, request: Mapping[str, Any]) -> Invocation:
        return Invocation(("--json",), canonical_json(request).decode("utf-8"))


class ClaudeAdapter(Adapter):
    profile = ProviderProfile(
        provider="claude",
        executable="claude",
        version_args=("--version",),
        adapter_version="nm-v6/claude-adapter-v1",
        headless=True,
        structured_output=True,
        resume=False,
        cancellation=True,
        native_subagents=False,
        background_tasks=False,
        sandbox_modes=("default",),
        instruction_sources=("CLAUDE.md", "AGENTS.md"),
        size_limits={},
    )

    def _invocation(self, request: Mapping[str, Any]) -> Invocation:
        payload = canonical_json(request).decode("utf-8")
        return Invocation(("-p", payload, "--output-format", "json"), None)


class FakeAdapter(Adapter):
    profile = ProviderProfile(
        provider="fake",
        executable="false",
        version_args=("--version",),
        adapter_version="nm-v6/fake-adapter-v1",
        headless=True,
        structured_output=True,
        resume=False,
        cancellation=True,
        native_subagents=False,
        background_tasks=False,
        sandbox_modes=("isolated",),
        instruction_sources=("AGENTS.md",),
        size_limits={"max_request_bytes": 1024 * 1024},
    )

    def __init__(
        self,
        *,
        backend: AdapterBackend | None = None,
        result_factory: Callable[[Mapping[str, Any], str], Mapping[str, Any]] | None = None,
        state_root: Path | None = None,
    ) -> None:
        if backend is not None and state_root is not None:
            raise ContractError("fake adapter state_root must be configured on its backend")
        super().__init__(
            backend=backend or MemoryBackend(result_factory, state_root=state_root)
        )

    def _invocation(self, request: Mapping[str, Any]) -> Invocation:
        return Invocation((), canonical_json(request).decode("utf-8"))


def create_adapter(
    provider: str,
    *,
    backend: AdapterBackend | None = None,
    executable: str | None = None,
    isolation_backend: IsolationBackend | None = None,
    state_root: Path | None = None,
) -> Adapter:
    """Create an adapter without leaking provider branching into the core."""

    adapters: dict[str, type[Adapter]] = {
        "codex": CodexAdapter,
        "grok": GrokAdapter,
        "claude": ClaudeAdapter,
        "fake": FakeAdapter,
    }
    try:
        adapter_type = adapters[provider]
    except KeyError as exc:
        raise ContractError(f"unsupported adapter provider: {provider!r}") from exc
    if adapter_type is FakeAdapter:
        if executable is not None:
            raise ContractError("fake adapter does not accept an executable")
        if backend is not None and state_root is not None:
            raise ContractError("fake adapter state_root must be configured on its backend")
        # The provider-neutral factory accepts one runtime call shape. The
        # in-memory fake performs no subprocess isolation, so this dependency
        # is intentionally unused while durable state_root remains enforced.
        return FakeAdapter(backend=backend, state_root=state_root)
    return adapter_type(
        backend=backend,
        executable=executable,
        isolation_backend=isolation_backend,
        state_root=state_root,
    )
