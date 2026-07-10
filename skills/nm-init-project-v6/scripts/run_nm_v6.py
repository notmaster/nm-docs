#!/usr/bin/env python3
"""Run the V6 CLI only from the checkout bound at Skill installation."""

from __future__ import print_function

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


BINDING_SCHEMA = "nm-v6/skill-source-binding-v1"
BINDING_PATH = Path(__file__).resolve().parents[1] / "source-binding.json"
EXPECTED_SPEC_SHA256 = (
    "24137bd389b40e5a017e50f8e271494a41d23641781d49c03d5a7aad098e0e02"
)
REQUIRED_BOUND_FILES = {
    "docs/nm-v6-workflow-spec.md",
    "template/v6/manifest.json",
    "tools/nm-v6/nm_v6.py",
}
ISOLATED_RUNNER = (
    "import runpy,sys; root=sys.argv.pop(1); script=sys.argv.pop(1); "
    "sys.argv[0]=script; sys.path.insert(0,root); "
    "runpy.run_path(script,run_name='__main__')"
)


def fail(message):
    raise SystemExit(message)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def repository_root(path):
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def validate_checkout(root, files):
    root = root.expanduser().resolve()
    if repository_root(root) != root:
        fail("Bound NM V6 source is not the exact Git checkout root; reinstall the Skill.")
    if not isinstance(files, dict) or not REQUIRED_BOUND_FILES.issubset(files):
        fail("NM V6 Skill source binding is incomplete; reinstall the Skill.")
    actual = set(REQUIRED_BOUND_FILES)
    for directory in (root / "tools/nm-v6", root / "skills/nm-init-project-v6"):
        for path in directory.rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
                and path.name != "source-binding.json"
            ):
                actual.add(path.relative_to(root).as_posix())
    if set(files) != actual:
        fail(
            "Bound NM V6 executable source inventory changed after Skill installation; "
            "review the update and reinstall the Skill."
        )
    for relative, expected in sorted(files.items()):
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(expected, str)
            or len(expected) != 64
        ):
            fail("NM V6 Skill source binding contains an invalid path or digest.")
        candidate = root / relative
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            fail("A bound NM V6 source file is missing or escapes its checkout.")
        if candidate.is_symlink() or not resolved.is_file() or digest(resolved) != expected:
            fail(
                "Bound NM V6 source changed after Skill installation; "
                "review the update and reinstall the Skill."
            )
    return root / "tools" / "nm-v6" / "nm_v6.py"


def bound_tool():
    if not BINDING_PATH.is_file():
        return None
    try:
        binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fail("NM V6 Skill source binding is unreadable; reinstall the Skill.")
    required = {"schema_version", "source_root", "files"}
    if not isinstance(binding, dict) or set(binding) != required:
        fail("NM V6 Skill source binding fields are incomplete or unknown.")
    if binding.get("schema_version") != BINDING_SCHEMA:
        fail("NM V6 Skill source binding version is unsupported.")
    raw_root = binding.get("source_root")
    if not isinstance(raw_root, str) or not Path(raw_root).is_absolute():
        fail("NM V6 Skill source binding must name an absolute checkout root.")
    root = Path(raw_root).resolve()
    configured = os.environ.get("NM_DOCS_DIR")
    if configured and Path(configured).expanduser().resolve() != root:
        fail(
            "NM_DOCS_DIR differs from the Skill's reviewed source binding; "
            "reinstall from the intended checkout."
        )
    return validate_checkout(root, binding.get("files"))


def source_tree_tool():
    """Permit direct execution from this repository, never CWD discovery."""

    here = Path(__file__).resolve()
    for candidate in here.parents:
        if repository_root(candidate) != candidate:
            continue
        spec = candidate / "docs/nm-v6-workflow-spec.md"
        tool = candidate / "tools/nm-v6/nm_v6.py"
        if (
            spec.is_file()
            and not spec.is_symlink()
            and digest(spec) == EXPECTED_SPEC_SHA256
            and tool.is_file()
            and not tool.is_symlink()
        ):
            return tool
    fail(
        "Installed NM V6 Skill has no reviewed source binding. "
        "Install it with tools/nm-v6/install-skill.sh from a trusted checkout."
    )


def find_tool():
    return bound_tool() or source_tree_tool()


def version(binary):
    try:
        result = subprocess.run(
            [binary, "-I", "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return (0, 0)
    if result.returncode != 0:
        return (0, 0)
    try:
        return tuple(int(item) for item in result.stdout.strip().split(".", 1))
    except ValueError:
        return (0, 0)


def find_python():
    names = []
    if os.environ.get("NM_V6_PYTHON"):
        names.append(os.environ["NM_V6_PYTHON"])
    names.append(sys.executable)
    names.extend(
        filter(
            None,
            (shutil.which(name) for name in ("python3.13", "python3.12", "python3.11")),
        )
    )
    names.append(
        str(
            Path.home()
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
        )
    )
    for binary in names:
        if binary and version(binary) >= (3, 11):
            resolved = binary if Path(binary).is_absolute() else shutil.which(binary)
            if resolved:
                return str(Path(resolved).resolve())
    fail("NM V6 requires Python 3.11 or newer; set NM_V6_PYTHON to a trusted runtime")


def main():
    binary = find_python()
    tool = find_tool()
    # Isolated mode ignores PYTHONPATH, user site packages, and unsafe Python
    # startup customization while retaining project action environment values.
    os.environ["PATH"] = str(Path(binary).parent) + os.pathsep + os.environ.get(
        "PATH", os.defpath
    )
    os.environ["NM_V6_PYTHON"] = binary
    os.execv(
        binary,
        [
            binary,
            "-I",
            "-c",
            ISOLATED_RUNNER,
            str(tool.parent),
            str(tool),
            *sys.argv[1:],
        ],
    )


if __name__ == "__main__":
    main()
