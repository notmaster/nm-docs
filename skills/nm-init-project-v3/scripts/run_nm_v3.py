#!/usr/bin/env python3
"""Run an exact bundled NM V3 tool or a tool from a local nm-docs checkout."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
BINDING = SKILL_ROOT / ".nm-v3-binding.json"
BUNDLED_TOOL = SKILL_ROOT / "scripts/vendor/nm_v3.py"


def candidate_repos() -> list[Path]:
    values: list[Path] = []
    if os.environ.get("NM_DOCS_DIR"):
        values.append(Path(os.environ["NM_DOCS_DIR"]).expanduser())
    values.extend(
        [
            Path.cwd(),
            Path.home() / "code" / "nm-docs",
            Path.home() / "code" / "mine" / "nm-docs",
            Path.home() / "src" / "nm-docs",
        ]
    )
    return values


def find_tool() -> Path | None:
    for start in candidate_repos():
        current = start.resolve()
        for path in [current, *current.parents]:
            tool = path / "tools" / "nm-v3" / "nm_v3.py"
            if tool.is_file():
                return tool
    return None


def bundled_tool() -> Path | None:
    if not BINDING.exists() and not BUNDLED_TOOL.exists():
        return None
    if not BINDING.is_file() or not BUNDLED_TOOL.is_file():
        raise SystemExit("NM V3 Skill binding is incomplete; reinstall the Skill")
    try:
        binding = json.loads(BINDING.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"NM V3 Skill binding is invalid: {exc}") from exc
    expected = binding.get("toolSha256")
    actual = hashlib.sha256(BUNDLED_TOOL.read_bytes()).hexdigest()
    if expected != actual:
        raise SystemExit("NM V3 bundled tool digest drifted; reinstall the Skill")
    if binding.get("templateVersion") != "3.1.0":
        raise SystemExit("NM V3 Skill binding version is unsupported; reinstall the Skill")
    return BUNDLED_TOOL


def main() -> int:
    tool = bundled_tool() or find_tool()
    if tool is None:
        raise SystemExit(
            "NM V3 tool is unavailable; reinstall the Skill from a trusted nm-docs checkout "
            "or set NM_DOCS_DIR"
        )
    return subprocess.call([sys.executable, "-I", str(tool), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
