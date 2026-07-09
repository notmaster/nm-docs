#!/usr/bin/env python3
"""NM V5 workflow runner (auto / assisted progression).

Launches short headless agent sessions. Disk state is authoritative:
0b-runtime/INDEX.yaml and 0b-runtime/tasks/*.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

INDEX_REL = "0b-runtime/INDEX.yaml"
NOTIFY_EVENT_REL = "0d-scripts/notify-event.sh"


class RunnerError(RuntimeError):
    """Fatal runner error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NM V5 workflow sessions.")
    parser.add_argument("--agent", required=True, choices=("codex", "claude", "grok"))
    parser.add_argument("--mode", choices=("staged", "auto"), help="Override INDEX mode for this run.")
    parser.add_argument("--max-tasks", type=int, default=0, help="Stop after N task sessions. 0 = no limit.")
    parser.add_argument("--project-root", help="Project root. Defaults to git toplevel.")
    parser.add_argument("--timeout-minutes", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def git_root(start: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RunnerError("not inside a git repository; use --project-root")
    return Path(result.stdout.strip())


def read_index(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or ":" not in line:
            continue
        # only simple top-level keys (ignore nested list bodies lightly)
        if line.startswith(" ") or line.startswith("\t") or line.startswith("-"):
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def notify(root: Path, event: str, severity: str, message: str, *, dry_run: bool) -> None:
    cmd = [
        str(root / NOTIFY_EVENT_REL),
        "--event",
        event,
        "--severity",
        severity,
        "--message",
        message,
    ]
    if dry_run:
        print("DRY-RUN notify:", " ".join(cmd))
        return
    subprocess.run(cmd, cwd=root, check=False)


def build_prompt(mode: str) -> str:
    return (
        "Follow AGENTS.md (NM V5). Disk state is truth: 0b-runtime/INDEX.yaml and task cards. "
        f"Execution mode for this session: {mode}. "
        "If mode was unspecified you must stop and ask the administrator to choose staged or auto. "
        "Work on at most one Task: create a branch from dev, implement, run acceptance, "
        "self-repair up to repair_max (default 10), update the task card, merge back to dev per BRANCHING.md, "
        "emit notify-event when required, then stop this session. "
        "Do not physically delete files; use .delete-pending/."
    )


def launch(agent: str, root: Path, prompt: str, *, timeout_minutes: int, dry_run: bool) -> int:
    if agent == "codex":
        cmd = ["codex", "exec", "--full-auto", prompt]
    elif agent == "claude":
        cmd = ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"]
    else:
        cmd = ["grok", prompt]

    if dry_run:
        print("DRY-RUN launch:", cmd)
        return 0

    timeout = timeout_minutes * 60 if timeout_minutes > 0 else None
    try:
        result = subprocess.run(cmd, cwd=root, timeout=timeout, check=False)
        return result.returncode
    except FileNotFoundError as exc:
        raise RunnerError(f"agent CLI not found: {agent}") from exc
    except subprocess.TimeoutExpired:
        return 124


def main() -> int:
    args = parse_args()
    try:
        root = Path(args.project_root).expanduser().resolve() if args.project_root else git_root(Path.cwd())
        index_path = root / INDEX_REL
        index = read_index(index_path)
        mode = args.mode or index.get("mode", "unspecified")
        if mode in ("", "unspecified"):
            notify(
                root,
                "mode_selection_required",
                "attention",
                "INDEX mode is unspecified; choose staged or auto before running.",
                dry_run=args.dry_run,
            )
            print("ERROR: mode is unspecified. Set INDEX.yaml mode or pass --mode.", file=sys.stderr)
            return 2

        status = index.get("status", "idle")
        if status == "completed":
            print("Workflow already completed.")
            return 0

        sessions = 0
        while True:
            if args.max_tasks and sessions >= args.max_tasks:
                break
            if mode == "staged" and sessions > 0:
                # staged: one session per invocation by default after first unit
                break
            code = launch(
                args.agent,
                root,
                build_prompt(mode),
                timeout_minutes=args.timeout_minutes,
                dry_run=args.dry_run,
            )
            sessions += 1
            if code != 0:
                notify(
                    root,
                    "blocked",
                    "attention",
                    f"agent session exited with code {code}",
                    dry_run=args.dry_run,
                )
                return code
            if mode == "staged":
                break
            # auto: re-read index; stop if blocked/awaiting/completed
            index = read_index(index_path)
            st = index.get("status", "")
            if st in {"blocked", "awaiting_acceptance", "stopped", "completed"}:
                break
            if not args.max_tasks and sessions >= 50:
                notify(
                    root,
                    "blocked",
                    "attention",
                    "runner safety stop after 50 sessions",
                    dry_run=args.dry_run,
                )
                return 1
        return 0
    except RunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
