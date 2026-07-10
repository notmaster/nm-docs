"""Disposable standalone workspaces and fail-closed command isolation.

Worker and gate commands never receive the authoritative checkout's Git
metadata.  A workspace is a real clone (not a linked worktree), has no remote,
and can only be executed through a detected OS sandbox backend.
"""

from __future__ import annotations

import platform
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from .errors import ContractError, IsolationError
from .util import ensure_relative_path, run_command


_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class IsolatedCommand:
    """An argv/cwd pair ready for direct ``subprocess`` execution."""

    argv: tuple[str, ...]
    cwd: Path


class IsolationBackend(Protocol):
    """Build an isolated command without executing it."""

    name: str

    def wrap(
        self,
        argv: Sequence[str],
        *,
        workspace: Path,
        cwd: Path,
        allow_network: bool = False,
    ) -> IsolatedCommand: ...


def _quoted_sandbox_path(path: Path) -> str:
    # sandbox-exec profiles use quoted Scheme strings.  Reject control
    # characters and escape the only two characters with string significance.
    value = str(path.resolve())
    if any(ord(character) < 32 for character in value):
        raise IsolationError("sandbox path contains control characters")
    return value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass(frozen=True)
class MacOSSandboxBackend:
    executable: str = "/usr/bin/sandbox-exec"
    runtime_read_roots: tuple[Path, ...] = ()
    denied_read_roots: tuple[Path, ...] = ()
    name: str = "sandbox-exec"

    def wrap(
        self,
        argv: Sequence[str],
        *,
        workspace: Path,
        cwd: Path,
        allow_network: bool = False,
    ) -> IsolatedCommand:
        _validate_command_scope(argv, workspace=workspace, cwd=cwd)
        workspace = workspace.resolve()
        writable = _quoted_sandbox_path(workspace)
        runtime_roots = _validated_runtime_roots(
            (*_default_runtime_roots("Darwin"), *self.runtime_read_roots),
            workspace=workspace,
            denied=self.denied_read_roots,
        )
        _require_executable_allowed(argv[0], workspace=workspace, runtime_roots=runtime_roots)
        denied_roots = _validated_denied_roots(self.denied_read_roots, workspace=workspace)
        clauses = [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow sysctl-read)",
            # sandbox-exec needs to inspect the root directory entry while
            # resolving otherwise explicitly allowed paths.  ``literal`` does
            # not grant reads below the filesystem root.
            '(allow file-read-data (literal "/"))',
            f'(allow file-read* (subpath "{writable}"))',
            f'(allow file-write* (subpath "{writable}"))',
        ]
        for root in runtime_roots:
            kind = "subpath" if root.is_dir() else "literal"
            clauses.append(
                f'(allow file-read* ({kind} "{_quoted_sandbox_path(root)}"))'
            )
        for root in denied_roots:
            quoted = _quoted_sandbox_path(root)
            clauses.append(f'(deny file-read* file-write* (subpath "{quoted}"))')
        clauses.append("(allow network*)" if allow_network else "(deny network*)")
        profile = "".join(clauses)
        return IsolatedCommand(
            argv=(self.executable, "-p", profile, "--", *tuple(argv)),
            cwd=cwd,
        )


@dataclass(frozen=True)
class BubblewrapBackend:
    executable: str
    runtime_read_roots: tuple[Path, ...] = ()
    denied_read_roots: tuple[Path, ...] = ()
    name: str = "bubblewrap"

    def wrap(
        self,
        argv: Sequence[str],
        *,
        workspace: Path,
        cwd: Path,
        allow_network: bool = False,
    ) -> IsolatedCommand:
        _validate_command_scope(argv, workspace=workspace, cwd=cwd)
        workspace = workspace.resolve()
        cwd = cwd.resolve()
        runtime_roots = _validated_runtime_roots(
            (*_default_runtime_roots("Linux"), *self.runtime_read_roots),
            workspace=workspace,
            denied=self.denied_read_roots,
        )
        _require_executable_allowed(argv[0], workspace=workspace, runtime_roots=runtime_roots)
        relative_cwd = cwd.relative_to(workspace)
        sandbox_cwd = Path("/workspace") / relative_cwd
        sandbox_argv = _rewrite_workspace_argv(argv, workspace=workspace)
        command = [
            self.executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--tmpfs",
            "/",
            "--dir",
            "/workspace",
        ]
        for directory in _mount_parent_directories(runtime_roots):
            command.extend(("--dir", str(directory)))
        for root in runtime_roots:
            command.extend(("--ro-bind", str(root), str(root)))
        command.extend(
            [
                "--bind",
                str(workspace),
                "/workspace",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--tmpfs",
                "/tmp",
                "--chdir",
                str(sandbox_cwd),
            ]
        )
        if not allow_network:
            command.append("--unshare-net")
        command.extend(("--", *sandbox_argv))
        return IsolatedCommand(argv=tuple(command), cwd=cwd)


def detect_isolation_backend(
    *,
    system: str | None = None,
    which: object = shutil.which,
    runtime_read_roots: Sequence[Path] = (),
    denied_read_roots: Sequence[Path] = (),
) -> IsolationBackend | None:
    """Return a supported OS sandbox, or ``None`` for fail-closed callers."""

    current = system or platform.system()
    lookup = which
    if current == "Darwin":
        executable = lookup("sandbox-exec")  # type: ignore[operator]
        if executable:
            return MacOSSandboxBackend(
                str(executable),
                tuple(Path(path).absolute() for path in runtime_read_roots),
                tuple(Path(path).resolve() for path in denied_read_roots),
            )
        return None
    if current == "Linux":
        executable = lookup("bwrap")  # type: ignore[operator]
        if executable:
            return BubblewrapBackend(
                str(executable),
                tuple(Path(path).absolute() for path in runtime_read_roots),
                tuple(Path(path).resolve() for path in denied_read_roots),
            )
        return None
    return None


def require_isolation_backend(backend: IsolationBackend | None = None) -> IsolationBackend:
    selected = backend or detect_isolation_backend()
    if selected is None:
        raise IsolationError(
            "no supported isolation backend is available; refusing to run an untrusted action"
        )
    return selected


def _validate_command_scope(argv: Sequence[str], *, workspace: Path, cwd: Path) -> None:
    if not argv or not all(isinstance(value, str) and value for value in argv):
        raise ContractError("sandbox argv must be a nonempty string array")
    workspace = workspace.resolve()
    cwd = cwd.resolve()
    try:
        cwd.relative_to(workspace)
    except ValueError as exc:
        raise IsolationError("sandbox cwd must stay inside its workspace") from exc


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    path: Path
    base_commit: str
    branch: str | None

    def resolve_cwd(self, relative: str) -> Path:
        relative = "." if relative == "." else ensure_relative_path(relative, field="action cwd")
        path = (self.path / relative).resolve()
        try:
            path.relative_to(self.path.resolve())
        except ValueError as exc:
            raise IsolationError("action cwd escapes the disposable workspace") from exc
        if not path.is_dir():
            raise IsolationError(f"action cwd is not a directory: {relative}")
        return path


class WorkspaceManager:
    """Create and dispose isolated, credential-free standalone clones."""

    def __init__(
        self,
        authoritative_checkout: Path,
        workspace_root: Path,
        *,
        isolation_backend: IsolationBackend | None = None,
        runtime_read_roots: Sequence[Path] = (),
    ) -> None:
        self.authoritative_checkout = authoritative_checkout.resolve()
        self.workspace_root = workspace_root.resolve()
        denied = _default_denied_roots(self.authoritative_checkout)
        self.isolation_backend = isolation_backend or detect_isolation_backend(
            runtime_read_roots=runtime_read_roots,
            denied_read_roots=denied,
        )
        if not (self.authoritative_checkout / ".git").exists():
            raise IsolationError("authoritative checkout is not a Git working tree")

    def create(
        self,
        workspace_id: str,
        *,
        commit: str,
        branch: str | None = None,
    ) -> Workspace:
        if not _WORKSPACE_ID.fullmatch(workspace_id):
            raise ContractError(f"invalid workspace id: {workspace_id!r}")
        if branch is not None and not branch:
            raise ContractError("workspace branch cannot be empty")
        self._reject_tracked_runtime()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        target = (self.workspace_root / workspace_id).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError as exc:
            raise IsolationError("workspace target escapes workspace root") from exc
        if target.exists():
            raise IsolationError(f"workspace already exists: {workspace_id}")

        # --no-local avoids object hardlinks/alternates back into authoritative
        # Git metadata.  The clone is safe to delete independently.
        run_command(
            (
                "git",
                "clone",
                "--no-local",
                "--no-checkout",
                "--",
                str(self.authoritative_checkout),
                str(target),
            ),
            cwd=self.workspace_root,
        )
        try:
            resolved = run_command(("git", "rev-parse", "--verify", f"{commit}^{{commit}}"), cwd=target)
            base_commit = resolved.stdout.strip()
            if branch is None:
                run_command(("git", "checkout", "--detach", base_commit), cwd=target)
            else:
                run_command(("git", "checkout", "-b", branch, base_commit), cwd=target)
            for remote in self._git_lines(target, "remote"):
                run_command(("git", "remote", "remove", remote), cwd=target)
            git_dir = run_command(("git", "rev-parse", "--absolute-git-dir"), cwd=target).stdout.strip()
            try:
                Path(git_dir).resolve().relative_to(target)
            except ValueError as exc:
                raise IsolationError("workspace Git metadata is not standalone") from exc
            runtime = target / ".nm" / "runtime"
            if runtime.exists():
                shutil.rmtree(runtime)
            return Workspace(workspace_id, target, base_commit, branch)
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise

    def isolated_command(
        self,
        workspace: Workspace,
        argv: Sequence[str],
        *,
        cwd: Path,
        allow_network: bool = False,
    ) -> IsolatedCommand:
        backend = require_isolation_backend(self.isolation_backend)
        return backend.wrap(
            argv,
            workspace=workspace.path,
            cwd=cwd,
            allow_network=allow_network,
        )

    def dispose(self, workspace: Workspace) -> None:
        path = workspace.path.resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise IsolationError("refusing to dispose a path outside workspace root") from exc
        shutil.rmtree(path, ignore_errors=False)

    def _reject_tracked_runtime(self) -> None:
        tracked = run_command(
            ("git", "ls-files", "--", ".nm/runtime", ".nm/runtime/**"),
            cwd=self.authoritative_checkout,
        ).stdout.strip()
        if tracked:
            raise IsolationError(".nm/runtime must not be tracked or copied to worker workspaces")

    @staticmethod
    def _git_lines(cwd: Path, *args: str) -> tuple[str, ...]:
        result = run_command(("git", *args), cwd=cwd)
        return tuple(line for line in result.stdout.splitlines() if line)


def temporary_workspace_root(prefix: str = "nm-v6-workspaces-") -> Path:
    """Create a caller-owned temporary root without weakening disposal rules."""

    return Path(tempfile.mkdtemp(prefix=prefix)).resolve()


def _default_runtime_roots(system: str) -> tuple[Path, ...]:
    candidates: tuple[str, ...]
    if system == "Darwin":
        candidates = (
            "/bin",
            "/sbin",
            "/usr/bin",
            "/usr/lib",
            "/usr/share",
            "/System/Library",
            "/Library/Apple",
            "/private/var/db/timezone",
            "/dev/null",
            "/dev/urandom",
            sys.prefix,
            sys.base_prefix,
        )
    else:
        candidates = (
            "/bin",
            "/usr/bin",
            "/usr/lib",
            "/usr/lib64",
            "/lib",
            "/lib64",
            "/etc/ld.so.cache",
            "/etc/ld.so.conf",
            sys.prefix,
            sys.base_prefix,
        )
    return tuple(Path(value).absolute() for value in candidates if Path(value).exists())


def _default_denied_roots(authoritative: Path | None = None) -> tuple[Path, ...]:
    home = Path.home().resolve()
    candidates = [
        home / ".config",
        home / ".ssh",
        home / ".aws",
        home / ".gnupg",
        home / ".kube",
    ]
    if authoritative is not None:
        candidates.extend((authoritative.resolve(), authoritative.resolve() / ".nm" / "runtime"))
    return tuple(path.resolve() for path in candidates)


def _validated_runtime_roots(
    roots: Sequence[Path],
    *,
    workspace: Path,
    denied: Sequence[Path],
) -> tuple[Path, ...]:
    denied_roots = tuple(path.resolve() for path in (*_default_denied_roots(), *denied))
    values: list[Path] = []
    for raw in roots:
        root = Path(raw).absolute()
        resolved = root.resolve()
        if not root.exists():
            raise IsolationError(f"runtime read root does not exist: {root}")
        if resolved == Path(resolved.anchor):
            raise IsolationError("filesystem root cannot be a runtime read root")
        if _overlaps(resolved, workspace):
            # Workspace already has its exact read/write rule.
            continue
        if any(_overlaps(resolved, blocked) for blocked in denied_roots):
            raise IsolationError(f"runtime read root overlaps a denied secret root: {root}")
        if root not in values:
            values.append(root)
    return tuple(values)


def _validated_denied_roots(roots: Sequence[Path], *, workspace: Path) -> tuple[Path, ...]:
    values: list[Path] = []
    for raw in (*_default_denied_roots(), *roots):
        root = Path(raw).resolve()
        if _overlaps(root, workspace):
            raise IsolationError("workspace overlaps a denied authority or secret root")
        if root not in values:
            values.append(root)
    return tuple(values)


def _require_executable_allowed(
    executable: str,
    *,
    workspace: Path,
    runtime_roots: Sequence[Path],
) -> Path:
    if Path(executable).is_absolute():
        resolved = Path(executable).resolve()
    else:
        located = shutil.which(executable)
        if not located:
            raise IsolationError(f"cannot resolve action executable: {executable}")
        resolved = Path(located).resolve()
    if not resolved.is_file():
        raise IsolationError(f"action executable is not a file: {resolved}")
    if not _within(resolved, workspace) and not any(
        _within(resolved, root) for root in runtime_roots
    ):
        raise IsolationError(
            f"action executable is outside allowed runtime roots: {resolved}; "
            "declare its minimum runtime read root"
        )
    return resolved


def _rewrite_workspace_argv(argv: Sequence[str], *, workspace: Path) -> tuple[str, ...]:
    values: list[str] = []
    for value in argv:
        path = Path(value)
        if path.is_absolute() and _within(path.resolve(), workspace):
            values.append(str(Path("/workspace") / path.resolve().relative_to(workspace)))
        else:
            values.append(value)
    return tuple(values)


def _mount_parent_directories(paths: Sequence[Path]) -> tuple[Path, ...]:
    values: set[Path] = set()
    for path in paths:
        destination = path if path.is_dir() else path.parent
        for parent in (destination, *destination.parents):
            if parent == Path("/"):
                break
            values.add(parent)
    return tuple(sorted(values, key=lambda value: (len(value.parts), str(value))))


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _overlaps(left: Path, right: Path) -> bool:
    return _within(left, right) or _within(right, left)
