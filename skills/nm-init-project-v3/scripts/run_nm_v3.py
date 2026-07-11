#!/usr/bin/env python3
"""Run an exact bundled NM V3 tool or a tool from a local nm-docs checkout."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
BINDING = SKILL_ROOT / ".nm-v3-binding.json"
BUNDLED_TOOL = SKILL_ROOT / "scripts/vendor/nm_v3.py"


def bundled_tool() -> Path:
    if not BINDING.is_file() or not BUNDLED_TOOL.is_file():
        raise SystemExit("NM V3 Skill binding is incomplete; reinstall the Skill")
    try:
        binding = json.loads(BINDING.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"NM V3 Skill binding is invalid: {exc}") from exc
    if binding.get("schemaVersion") != 2 or binding.get("distributionVersion") != 1:
        raise SystemExit("NM V3 Skill binding schema is unsupported; reinstall the Skill")
    if binding.get("distributionMode") not in {"repository-source", "local-installer"}:
        raise SystemExit("NM V3 Skill distribution mode is unsupported; reinstall the Skill")
    if binding.get("toolPath") != "scripts/vendor/nm_v3.py":
        raise SystemExit("NM V3 Skill tool path is invalid; reinstall the Skill")
    expected = binding.get("toolSha256")
    actual = hashlib.sha256(BUNDLED_TOOL.read_bytes()).hexdigest()
    if expected != actual:
        raise SystemExit("NM V3 bundled tool digest drifted; reinstall the Skill")
    if binding.get("templateVersion") != "3.1.0":
        raise SystemExit("NM V3 Skill binding version is unsupported; reinstall the Skill")
    return BUNDLED_TOOL


def main() -> int:
    return subprocess.call([sys.executable, "-I", str(bundled_tool()), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
