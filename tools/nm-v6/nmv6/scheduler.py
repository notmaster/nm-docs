"""Deterministic DAG scheduling, leases, fencing, and conflict detection."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .errors import ContractError, TransitionError
from .util import ensure_relative_path


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    dependencies: tuple[str, ...] = ()
    write_set: tuple[str, ...] = ()
    optional: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ContractError("task_id must be a nonempty string")
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ContractError(f"task {self.task_id} has duplicate dependencies")
        normalized = tuple(_normalize_write_pattern(value) for value in self.write_set)
        if len(normalized) != len(set(normalized)):
            raise ContractError(f"task {self.task_id} has duplicate write-set entries")
        object.__setattr__(self, "write_set", normalized)


class TaskGraph:
    def __init__(self, tasks: Iterable[TaskDefinition]) -> None:
        task_list = tuple(tasks)
        self.tasks = {task.task_id: task for task in task_list}
        if len(self.tasks) != len(task_list):
            raise ContractError("Task graph contains duplicate IDs")
        for task in task_list:
            missing = sorted(set(task.dependencies) - set(self.tasks))
            if missing:
                raise ContractError(
                    f"task {task.task_id} references unknown dependencies: {', '.join(missing)}"
                )
            if task.task_id in task.dependencies:
                raise ContractError(f"task {task.task_id} depends on itself")
        self._assert_acyclic()

    def topological_order(self) -> tuple[str, ...]:
        indegree = {task_id: 0 for task_id in self.tasks}
        followers: dict[str, list[str]] = {task_id: [] for task_id in self.tasks}
        for task in self.tasks.values():
            indegree[task.task_id] = len(task.dependencies)
            for dependency in task.dependencies:
                followers[dependency].append(task.task_id)
        ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for follower in sorted(followers[current]):
                indegree[follower] -= 1
                if indegree[follower] == 0:
                    ready.append(follower)
                    ready.sort()
        if len(ordered) != len(self.tasks):
            raise ContractError("Task graph contains a cycle")
        return tuple(ordered)

    def ready(
        self,
        *,
        completed: Iterable[str],
        unavailable: Iterable[str] = (),
    ) -> tuple[TaskDefinition, ...]:
        completed_set = set(completed)
        unavailable_set = set(unavailable)
        unknown = (completed_set | unavailable_set) - set(self.tasks)
        if unknown:
            raise ContractError(f"scheduler state references unknown Tasks: {sorted(unknown)!r}")
        result = [
            self.tasks[task_id]
            for task_id in self.topological_order()
            if task_id not in completed_set
            and task_id not in unavailable_set
            and set(self.tasks[task_id].dependencies) <= completed_set
        ]
        return tuple(result)

    def _assert_acyclic(self) -> None:
        self.topological_order()


@dataclass(frozen=True)
class Lease:
    task_id: str
    owner: str
    attempt_id: str
    fencing_token: int
    expires_at: str
    run_revision: int

    def expired(self, *, now: datetime | None = None) -> bool:
        current = datetime.now(UTC) if now is None else now
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return current >= expiry


class LeaseAuthority(Protocol):
    """Only the reducer-backed authority may create or change a lease."""

    def acquire(
        self,
        *,
        task_id: str,
        owner: str,
        attempt_id: str,
        expected_revision: int,
        lease_seconds: int,
        write_set: tuple[str, ...],
    ) -> Lease: ...

    def heartbeat(
        self,
        *,
        task_id: str,
        owner: str,
        fencing_token: int,
        expected_revision: int,
        lease_seconds: int,
    ) -> Lease: ...

    def release(
        self,
        *,
        task_id: str,
        owner: str,
        fencing_token: int,
        expected_revision: int,
    ) -> None: ...


class ReducerLeaseAuthority:
    """Thin adapter over reducer lease methods; it never writes state itself."""

    def __init__(self, reducer: Any, *, run_id: str) -> None:
        self.reducer = reducer
        self.run_id = run_id

    def acquire(
        self,
        *,
        task_id: str,
        owner: str,
        attempt_id: str,
        expected_revision: int,
        lease_seconds: int,
        write_set: tuple[str, ...],
    ) -> Lease:
        raw = self.reducer.acquire_lease(
            run_id=self.run_id,
            resource_id=task_id,
            owner=owner,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            lease_seconds=lease_seconds,
            write_set=write_set,
            idempotency_key=f"lease:acquire:{task_id}:{attempt_id}:{expected_revision}",
        )
        return _lease_from_result(raw, task_id=task_id, owner=owner, attempt_id=attempt_id)

    def heartbeat(
        self,
        *,
        task_id: str,
        owner: str,
        fencing_token: int,
        expected_revision: int,
        lease_seconds: int,
    ) -> Lease:
        raw = self.reducer.heartbeat_lease(
            run_id=self.run_id,
            resource_id=task_id,
            owner=owner,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            lease_seconds=lease_seconds,
            idempotency_key=f"lease:heartbeat:{task_id}:{fencing_token}:{expected_revision}",
        )
        persisted = self.reducer.store.get_lease(task_id)
        combined = {**dict(raw), **dict(persisted or {})}
        return _lease_from_result(combined, task_id=task_id, owner=owner, attempt_id=None)

    def release(
        self,
        *,
        task_id: str,
        owner: str,
        fencing_token: int,
        expected_revision: int,
    ) -> None:
        self.reducer.release_lease(
            run_id=self.run_id,
            resource_id=task_id,
            owner=owner,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            idempotency_key=f"lease:release:{task_id}:{fencing_token}:{expected_revision}",
        )


class Scheduler:
    """Select conflict-free ready work and validate reducer-owned leases."""

    def __init__(
        self,
        graph: TaskGraph,
        lease_authority: LeaseAuthority,
        *,
        max_workers: int = 1,
        lease_seconds: int = 120,
    ) -> None:
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise ContractError("max_workers must be a positive integer")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds < 1:
            raise ContractError("lease_seconds must be a positive integer")
        self.graph = graph
        self.leases = lease_authority
        self.max_workers = max_workers
        self.lease_seconds = lease_seconds

    def select(
        self,
        *,
        completed: Iterable[str],
        active: Mapping[str, Lease],
        limit: int | None = None,
    ) -> tuple[TaskDefinition, ...]:
        capacity = self.max_workers - len(active)
        if limit is not None:
            if limit < 0:
                raise ContractError("scheduler limit cannot be negative")
            capacity = min(capacity, limit)
        if capacity <= 0:
            return ()
        candidates = self.graph.ready(completed=completed, unavailable=active)
        selected: list[TaskDefinition] = []
        occupied = [self.graph.tasks[task_id] for task_id in active if task_id in self.graph.tasks]
        for candidate in candidates:
            if any(write_sets_overlap(candidate.write_set, task.write_set) for task in occupied):
                continue
            if any(write_sets_overlap(candidate.write_set, task.write_set) for task in selected):
                continue
            selected.append(candidate)
            if len(selected) >= capacity:
                break
        return tuple(selected)

    def acquire(
        self,
        task_id: str,
        *,
        owner: str,
        attempt_id: str,
        expected_revision: int,
    ) -> Lease:
        if task_id not in self.graph.tasks:
            raise ContractError(f"unknown task: {task_id}")
        return self.leases.acquire(
            task_id=task_id,
            owner=owner,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            lease_seconds=self.lease_seconds,
            write_set=self.graph.tasks[task_id].write_set,
        )

    def heartbeat(self, lease: Lease, *, expected_revision: int) -> Lease:
        self.validate_result(
            task_id=lease.task_id,
            owner=lease.owner,
            fencing_token=lease.fencing_token,
            lease=lease,
        )
        return self.leases.heartbeat(
            task_id=lease.task_id,
            owner=lease.owner,
            fencing_token=lease.fencing_token,
            expected_revision=expected_revision,
            lease_seconds=self.lease_seconds,
        )

    def release(self, lease: Lease, *, expected_revision: int) -> None:
        self.leases.release(
            task_id=lease.task_id,
            owner=lease.owner,
            fencing_token=lease.fencing_token,
            expected_revision=expected_revision,
        )

    @staticmethod
    def validate_result(
        *,
        task_id: str,
        owner: str,
        fencing_token: int,
        lease: Lease,
        now: datetime | None = None,
    ) -> None:
        if lease.task_id != task_id or lease.owner != owner:
            raise TransitionError("result does not belong to the active lease")
        if lease.fencing_token != fencing_token:
            raise TransitionError("stale fencing token")
        if lease.expired(now=now):
            raise TransitionError("lease expired before result collection")

    def assert_actual_diff_isolated(
        self,
        task_id: str,
        changed_paths: Iterable[str],
        accepted_candidates: Mapping[str, Iterable[str]],
    ) -> tuple[str, ...]:
        if task_id not in self.graph.tasks:
            raise ContractError(f"unknown task: {task_id}")
        normalized = tuple(sorted({_normalize_changed_path(path) for path in changed_paths}))
        declared = self.graph.tasks[task_id].write_set
        outside = tuple(path for path in normalized if not path_matches_any(path, declared))
        if outside:
            raise TransitionError(
                f"Task {task_id} changed paths outside its declared write set: {outside!r}"
            )
        for other_id, other_paths in accepted_candidates.items():
            if other_id == task_id:
                continue
            overlap = actual_paths_overlap(normalized, other_paths)
            if overlap:
                raise TransitionError(
                    f"actual write overlap between {task_id} and {other_id}: {overlap!r}"
                )
        return normalized


def write_sets_overlap(left: Sequence[str], right: Sequence[str]) -> bool:
    if not left or not right:
        return False
    return any(_patterns_may_overlap(first, second) for first in left for second in right)


def path_matches_any(path: str, patterns: Sequence[str]) -> bool:
    normalized = _normalize_changed_path(path)
    return any(_path_matches(normalized, pattern) for pattern in patterns)


def actual_paths_overlap(
    left: Iterable[str], right: Iterable[str]
) -> tuple[str, ...]:
    first = {_normalize_changed_path(path) for path in left}
    second = {_normalize_changed_path(path) for path in right}
    conflicts: set[str] = set()
    for left_path in first:
        for right_path in second:
            if (
                left_path == right_path
                or left_path.startswith(right_path.rstrip("/") + "/")
                or right_path.startswith(left_path.rstrip("/") + "/")
            ):
                conflicts.add(left_path if len(left_path) >= len(right_path) else right_path)
    return tuple(sorted(conflicts))


def _patterns_may_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    if not _has_glob(left) and not _has_glob(right):
        return left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/")
    left_prefix = _literal_prefix(left)
    right_prefix = _literal_prefix(right)
    if left_prefix and right_prefix:
        if not (
            left_prefix.startswith(right_prefix.rstrip("/") + "/")
            or right_prefix.startswith(left_prefix.rstrip("/") + "/")
            or left_prefix == right_prefix
        ):
            return False
    # Glob intersection is undecidable in the general case.  If disjointness
    # was not proved from literal prefixes, serialize conservatively.
    return True


def _path_matches(path: str, pattern: str) -> bool:
    if not _has_glob(pattern):
        return path == pattern or path.startswith(pattern.rstrip("/") + "/")
    return fnmatch.fnmatchcase(path, pattern) or PurePosixPath(path).match(pattern)


def _normalize_write_pattern(value: str) -> str:
    value = ensure_relative_path(value, field="write-set path")
    if value.startswith(".git/") or value == ".git" or value.startswith(".nm/runtime"):
        raise ContractError("write set cannot include Git metadata or V6 runtime authority")
    return value.rstrip("/")


def _normalize_changed_path(value: str) -> str:
    value = ensure_relative_path(value, field="changed path")
    if _has_glob(value):
        raise ContractError("actual changed path cannot contain glob syntax")
    return value.rstrip("/")


def _has_glob(value: str) -> bool:
    return any(character in value for character in "*?[")


def _literal_prefix(value: str) -> str:
    parts: list[str] = []
    for part in value.split("/"):
        if _has_glob(part):
            break
        parts.append(part)
    return "/".join(parts)


def _lease_from_result(
    value: Any,
    *,
    task_id: str,
    owner: str,
    attempt_id: str | None,
) -> Lease:
    if isinstance(value, Lease):
        return value
    if not isinstance(value, Mapping):
        raise TransitionError("reducer did not return a structured lease")
    try:
        return Lease(
            task_id=str(value.get("task_id", value.get("resource_id", task_id))),
            owner=str(value.get("owner", owner)),
            attempt_id=str(value.get("attempt_id", attempt_id or "")),
            fencing_token=int(value["fencing_token"]),
            expires_at=str(value["expires_at"]),
            run_revision=int(value.get("run_revision", value.get("revision"))),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TransitionError("reducer returned an invalid lease") from exc
