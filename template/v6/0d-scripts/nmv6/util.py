"""Small deterministic helpers shared by the NM V6 core."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .errors import ContractError, NmV6Error


IDENTIFIER_PATTERNS = {
    "goal": re.compile(r"^GOAL-[0-9]{3}$"),
    "requirement": re.compile(r"^REQ-[0-9]{3}$"),
    "acceptance": re.compile(r"^AC-[0-9]{3}$"),
    "decision": re.compile(r"^DEC-[0-9]{3}$"),
    "phase": re.compile(r"^PHASE-[0-9]{3}$"),
    "task": re.compile(r"^TASK-[0-9]{3}$"),
    "attempt": re.compile(r"^ATTEMPT-[A-Za-z0-9._-]+-[0-9]{3}$"),
    "evidence": re.compile(r"^EVID-[A-Za-z0-9._-]+-[0-9]{3}$"),
    "gate": re.compile(r"^GATE-[A-Za-z0-9._-]+-[0-9]{3}$"),
    "operation": re.compile(r"^OP-[A-Za-z0-9._-]+-[0-9]{3}$"),
    "authorization": re.compile(r"^AUTH-[A-Za-z0-9._-]+-[0-9]{3}$"),
}


def utc_now() -> str:
    """Return a stable RFC3339 UTC timestamp."""

    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    """Encode JSON exactly once for hashes and signed records."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_relative_path(value: str, *, field: str = "path") -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field} must be a nonempty relative path")
    path = Path(value)
    if path.is_absolute() or value == "." or ".." in path.parts:
        raise ContractError(f"{field} must stay inside the declared root: {value!r}")
    return path.as_posix()


def atomic_write(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Durably replace a file without exposing partial content."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read valid JSON from {path}: {exc}") from exc


def dump_json(value: Any, *, pretty: bool = True) -> bytes:
    if pretty:
        return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return canonical_json(value)


def require_keys(mapping: Mapping[str, Any], keys: Iterable[str], *, subject: str) -> None:
    missing = sorted(set(keys) - set(mapping))
    if missing:
        raise ContractError(f"{subject} missing required fields: {', '.join(missing)}")


def reject_unknown_keys(mapping: Mapping[str, Any], keys: Iterable[str], *, subject: str) -> None:
    unknown = sorted(set(mapping) - set(keys))
    if unknown:
        raise ContractError(f"{subject} has unknown fields: {', '.join(unknown)}")


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise ContractError("argv must be a nonempty string array")
    result = subprocess.run(
        list(argv),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise NmV6Error(f"command failed ({result.returncode}): {' '.join(argv)}\n{message}")
    return result


def safe_environment(
    *,
    inherit: Iterable[str] = (),
    injected: Mapping[str, str] | None = None,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source_env = os.environ if source is None else source
    result = {name: source_env[name] for name in inherit if name in source_env}
    result.update(
        {
            "LANG": source_env.get("LANG", "C.UTF-8"),
            "LC_ALL": source_env.get("LC_ALL", "C.UTF-8"),
            "PATH": source_env.get("PATH", "/usr/bin:/bin"),
        }
    )
    if injected:
        result.update(injected)
    return result


def ensure_python_311() -> None:
    import sys

    if sys.version_info < (3, 11):
        raise NmV6Error(
            "NM V6 requires Python 3.11 or newer; "
            f"current runtime is {sys.version_info.major}.{sys.version_info.minor}"
        )
