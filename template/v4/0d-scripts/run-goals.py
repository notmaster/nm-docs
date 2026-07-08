#!/usr/bin/env python3
"""NM V4 auto-mode runner.

Runs Spec phases serially, one fresh headless agent session per phase.
State is handed over through 0b-goals/ROADMAP.md. The runner never edits
project files itself; it launches sessions, checks phase progress in the
ROADMAP, and notifies the administrator on completion or failure.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROADMAP_REL = "0b-goals/ROADMAP.md"
NOTIFY_REL = "0d-scripts/notify-admin.sh"
DONE_STATUSES = {"merged", "skipped", "cancelled"}
PHASE_ROW = re.compile(r"^\|\s*(\d+)\s*\|")


class RunnerError(RuntimeError):
    """Fatal runner error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NM V4 phases unattended (auto mode).")
    parser.add_argument("--agent", required=True, choices=("codex", "claude", "grok"))
    parser.add_argument(
        "--permissions",
        choices=("bypass", "sandbox"),
        help="Override the ROADMAP permission tier. Default comes from the ROADMAP, then bypass.",
    )
    parser.add_argument(
        "--mode",
        choices=("auto",),
        help="Override a staged ROADMAP to auto for this run (launch instruction precedence).",
    )
    parser.add_argument("--max-phases", type=int, default=0, help="Stop after N phases. 0 means no limit.")
    parser.add_argument("--spec", help="Spec path hint used when bootstrapping a missing ROADMAP.")
    parser.add_argument("--project-root", help="Project root. Defaults to the current git toplevel.")
    parser.add_argument("--timeout-minutes", type=int, default=0, help="Per-session timeout. 0 means no timeout.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without launching sessions.")
    return parser.parse_args()


def git_root(start: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=start, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RunnerError("not inside a git repository; use --project-root")
    return Path(result.stdout.strip())


def read_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def read_phases(text: str) -> list[dict[str, object]]:
    phases: list[dict[str, object]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not PHASE_ROW.match(line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        phases.append(
            {
                "number": int(cells[0]),
                "name": cells[1],
                "branch": cells[2],
                "status": cells[3].lower(),
            }
        )
    return phases


def load_roadmap(root: Path) -> tuple[dict[str, str], list[dict[str, object]]]:
    path = root / ROADMAP_REL
    if not path.is_file():
        return {}, []
    text = path.read_text(encoding="utf-8")
    return read_frontmatter(text), read_phases(text)


def needs_bootstrap(front: dict[str, str], phases: list[dict[str, object]]) -> bool:
    return not phases or not front.get("spec")


def bootstrap_prompt(spec: str | None) -> str:
    spec_hint = f"（Spec 路径：{spec}）" if spec else ""
    return (
        "按 NM V4 auto 模式初始化 ROADMAP：\n"
        "1. 读取 AGENTS.md、0c-workflow/WORKFLOW_V4.md 和 0a-docs/0a-spec/ 下 "
        f"status: confirmed 的 Spec{spec_hint}。\n"
        "2. 按 Spec 已有实施阶段（没有则自行拆分）生成 0b-goals/ROADMAP.md：填写 frontmatter"
        "（spec 路径、execution_mode: auto、permissions、current_phase、overall_status）、"
        "Phase Table 和每阶段小节。\n"
        "3. 只生成 ROADMAP，不要开始实现任何阶段。\n"
        "4. ROADMAP 属于工作流簿记，直接提交到 dev。\n"
    )


def phase_prompt(number: int, name: str) -> str:
    return (
        "按 NM V4 auto 模式执行单个阶段：\n"
        "1. 读取 AGENTS.md、0b-goals/ROADMAP.md 和其引用的 Spec。\n"
        f"2. 执行 Phase {number}（{name}）：从最新 dev 新建任务分支，实现该阶段，"
        "运行 ./0d-scripts/verify.sh 和该阶段的 Verify 命令，失败则修复重跑。\n"
        "3. 验证通过后：push 任务分支；按 0c-workflow/BRANCHING.md 合并回 dev 并 push；"
        "更新 ROADMAP（状态 merged、Result、Handoff，Manual 项追加到待人工验收清单）；"
        "调用 ./0d-scripts/notify-admin.sh 发阶段完成通知。\n"
        "4. 只执行这一个阶段，完成后结束会话。\n"
        "5. 遇到阻塞、需要管理员决策、安全风险或同类验证失败连续 5 次：把阶段状态置为 blocked，"
        "通知管理员并结束会话。\n"
    )


def agent_command(agent: str, permissions: str, prompt: str, root: Path) -> list[str]:
    if agent == "codex":
        cmd = ["codex", "exec", "--cd", str(root)]
        cmd.append("--dangerously-bypass-approvals-and-sandbox" if permissions == "bypass" else "--full-auto")
        cmd.append(prompt)
        return cmd
    if agent == "claude":
        cmd = ["claude", "-p", prompt]
        if permissions == "bypass":
            cmd.append("--dangerously-skip-permissions")
        else:
            cmd.extend(["--permission-mode", "acceptEdits"])
        return cmd
    if agent == "grok":
        cmd = ["grok", "--cwd", str(root), "-p", prompt]
        if permissions == "bypass":
            cmd.append("--always-approve")
        return cmd
    raise RunnerError(f"unsupported agent: {agent}")


def notify(root: Path, level: str, title: str, message: str, dry_run: bool) -> None:
    script = root / NOTIFY_REL
    if dry_run:
        print(f"DRY-RUN notify [{level}] {title}: {message}")
        return
    if not script.exists():
        print(f"WARN: notify script missing: {script}", file=sys.stderr)
        return
    result = subprocess.run(
        [str(script), "--level", level, "--title", title, "--message", message],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        print(f"WARN: notification failed ({title}): {detail}", file=sys.stderr)


def run_session(cmd: list[str], root: Path, log_path: Path, timeout_minutes: int, dry_run: bool) -> int:
    if dry_run:
        print(f"DRY-RUN command: {cmd}")
        return 0
    print(f"==> Launching {cmd[0]} session (log: {log_path})")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = timeout_minutes * 60 if timeout_minutes > 0 else None
    with log_path.open("w", encoding="utf-8") as log_file:
        try:
            result = subprocess.run(cmd, cwd=root, stdout=log_file, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return -1
        except FileNotFoundError as exc:
            raise RunnerError(f"agent CLI not found: {cmd[0]}") from exc
    return result.returncode


def next_phase(phases: list[dict[str, object]]) -> dict[str, object] | None:
    for phase in sorted(phases, key=lambda item: item["number"]):
        if phase["status"] not in DONE_STATUSES:
            return phase
    return None


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).resolve() if args.project_root else git_root(Path.cwd())
    log_dir = root / "logs" / "run-goals"
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    front, phases = load_roadmap(root)
    permissions = args.permissions or front.get("permissions") or "bypass"

    if needs_bootstrap(front, phases):
        print("==> ROADMAP not initialized; running bootstrap session")
        rc = run_session(
            agent_command(args.agent, permissions, bootstrap_prompt(args.spec), root),
            root,
            log_dir / f"{stamp}-bootstrap.log",
            args.timeout_minutes,
            args.dry_run,
        )
        if args.dry_run:
            return 0
        if rc != 0:
            notify(root, "error", "Auto run bootstrap failed", f"agent={args.agent} exit={rc}; see logs/run-goals.", args.dry_run)
            return 1
        front, phases = load_roadmap(root)
        if needs_bootstrap(front, phases):
            notify(root, "error", "Auto run bootstrap incomplete", "ROADMAP is still empty after the bootstrap session.", args.dry_run)
            return 1

    if front.get("execution_mode", "staged") != "auto" and args.mode != "auto":
        print(
            "ERROR: ROADMAP execution_mode is not auto. "
            "Rerun with --mode auto to override it for this run.",
            file=sys.stderr,
        )
        return 2

    executed = 0
    while True:
        front, phases = load_roadmap(root)
        phase = next_phase(phases)
        if phase is None:
            summary = (
                f"All {len(phases)} phases merged. "
                "Check the ROADMAP manual acceptance backlog for final review."
            )
            print(f"==> {summary}")
            notify(root, "success", "Auto run completed", summary, args.dry_run)
            return 0
        if phase["status"] == "blocked":
            notify(
                root,
                "blocked",
                f"Phase {phase['number']} blocked",
                f"{phase['name']}: see the ROADMAP and logs/run-goals.",
                args.dry_run,
            )
            return 1
        if args.max_phases and executed >= args.max_phases:
            print(f"==> Reached --max-phases {args.max_phases}; stopping.")
            notify(
                root,
                "info",
                "Auto run paused",
                f"Executed {executed} phase(s); next is Phase {phase['number']} {phase['name']}.",
                args.dry_run,
            )
            return 0

        print(f"==> Phase {phase['number']}: {phase['name']} [{phase['status']}]")
        rc = run_session(
            agent_command(args.agent, permissions, phase_prompt(phase["number"], phase["name"]), root),
            root,
            log_dir / f"{stamp}-phase{phase['number']}.log",
            args.timeout_minutes,
            args.dry_run,
        )
        executed += 1
        if args.dry_run:
            return 0
        if rc == -1:
            notify(
                root,
                "error",
                f"Phase {phase['number']} timed out",
                f"{phase['name']}: session exceeded {args.timeout_minutes} minutes.",
                args.dry_run,
            )
            return 1
        if rc != 0:
            notify(
                root,
                "error",
                f"Phase {phase['number']} session failed",
                f"{phase['name']}: agent={args.agent} exit={rc}; see logs/run-goals.",
                args.dry_run,
            )
            return 1

        front, phases = load_roadmap(root)
        current = next((item for item in phases if item["number"] == phase["number"]), None)
        if current is None or current["status"] not in DONE_STATUSES:
            status = current["status"] if current else "missing"
            notify(
                root,
                "blocked",
                f"Phase {phase['number']} did not complete",
                f"{phase['name']}: status is '{status}' after the session; auto run stopped.",
                args.dry_run,
            )
            return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
