#!/usr/bin/env python3
"""Locate and run the NM V5 tool from nm-docs."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

RAW_TOOL_URL = "https://raw.githubusercontent.com/notmaster/nm-docs/main/tools/nm-v5/nm_v5.py"


def candidate_repos() -> list[Path]:
    values: list[Path] = []
    if os.environ.get("NM_DOCS_DIR"):
        values.append(Path(os.environ["NM_DOCS_DIR"]).expanduser())
    values.extend(
        [
            Path.cwd(),
            Path.home() / "code/mine/nm-docs",
            Path("/Users/jango/code/mine/nm-docs"),
        ]
    )
    return values


def find_tool() -> Path | None:
    for start in candidate_repos():
        current = start.resolve()
        for path in [current, *current.parents]:
            tool = path / "tools" / "nm-v5" / "nm_v5.py"
            if tool.is_file():
                return tool
    return None


def download_tool() -> Path:
    target = Path(tempfile.gettempdir()) / "nm_v5.py"
    with urllib.request.urlopen(RAW_TOOL_URL, timeout=30) as response:
        target.write_bytes(response.read())
    target.chmod(0o755)
    return target


def main() -> int:
    tool = find_tool() or download_tool()
    return subprocess.call([sys.executable, str(tool), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
