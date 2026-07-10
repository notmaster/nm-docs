#!/usr/bin/env python3
"""Mechanically vendor the V6 core/schemas and regenerate the hashed manifest."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "template/v6"
CORE_SOURCE = ROOT / "tools/nm-v6/nmv6"
CORE_TARGET = TEMPLATE / "0d-scripts/nmv6"
SCHEMA_SOURCE = ROOT / "tools/nm-v6/schemas"
SCHEMA_TARGET = TEMPLATE / "0c-workflow/schemas"

CREATE_ONLY = {
    ".gitignore",
    ".markdownlint.json",
    ".markdownlintignore",
    "README.md",
    "PROJECT_STRUCTURE.md",
    "project.example.json",
    "0a-docs/DECISIONS.md",
    "0a-docs/0a-spec/SPEC.md",
    "0a-docs/0a-spec/SPEC.zh-CN.md",
    "0a-docs/0a-spec/traceability.json",
    "0a-docs/0a-spec/spec.example.json",
    "0a-docs/0b-design/prototype/.gitkeep",
    "0a-docs/0c-prompts/write-spec.md",
    "0a-docs/0c-prompts/review-spec.md",
}


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(path: Path) -> dict[str, object]:
    relative = path.relative_to(TEMPLATE).as_posix()
    target = "project.json" if relative == "project.example.json" else relative
    if relative == "package.json":
        policy = "json-merge"
    elif relative in CREATE_ONLY:
        policy = "create-only"
    else:
        policy = "managed"
    executable = os.access(path, os.X_OK)
    item: dict[str, object] = {
        "target": target,
        "source": f"template/v6/{relative}",
        "sourceSha256": sha256(path),
        "policy": policy,
        "mode": "0755" if executable else "0644",
    }
    if relative == "package.json":
        item["mergeRoots"] = ["scripts", "devDependencies"]
    return item


def main() -> None:
    copy_tree(CORE_SOURCE, CORE_TARGET)
    copy_tree(SCHEMA_SOURCE, SCHEMA_TARGET)
    files = sorted(
        path
        for path in TEMPLATE.rglob("*")
        if path.is_file()
        and path.name not in {"manifest.json", ".DS_Store"}
        and "__pycache__" not in path.parts
    )
    directories = sorted(
        {
            parent.relative_to(TEMPLATE).as_posix()
            for path in files
            for parent in path.parents
            if parent != TEMPLATE and TEMPLATE in parent.parents
        }
    )
    manifest = {
        "schemaVersion": 2,
        "templateVersion": "6.0.0-rc.1",
        "maturity": "accepted",
        "recommended": False,
        "productionReady": False,
        "specId": "SPEC-NM-WORKFLOW-V6-V1",
        "specVersion": 1,
        "specHash": "62196ab27c2be08ea1c716081903a009185f1d518ba7a53ed9b3d8485236cb7f",
        "python": ">=3.11,<4",
        "stateFile": ".nm-template-state.json",
        "runtimeAuthority": ".nm/runtime/v6/state.sqlite3",
        "directories": directories,
        "templates": [entry(path) for path in files],
        "git": {
            "integrationBranch": "dev",
            "stableBranch": "main",
            "protectedBranches": ["main", "dev"],
        },
    }
    output = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    temporary = TEMPLATE / ".manifest.json.tmp"
    temporary.write_text(output, encoding="utf-8")
    os.replace(temporary, TEMPLATE / "manifest.json")


if __name__ == "__main__":
    main()
