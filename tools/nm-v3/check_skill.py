#!/usr/bin/env python3
"""Portable structural validation for the repository-maintained V3 Skill."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/nm-init-project-v3"


def main() -> int:
    failures: list[str] = []
    skill_md = SKILL / "SKILL.md"
    openai_yaml = SKILL / "agents/openai.yaml"
    wrapper = SKILL / "scripts/run_nm_v3.py"
    for path in (skill_md, openai_yaml, SKILL / "references/v3-lifecycle.md", SKILL / "references/install.md", wrapper):
        if not path.is_file():
            failures.append(f"missing: {path.relative_to(ROOT)}")
    if skill_md.is_file():
        text = skill_md.read_text(encoding="utf-8")
        match = re.match(r"^---\n([\s\S]*?)\n---\n", text)
        if not match:
            failures.append("SKILL.md has invalid frontmatter delimiters")
        else:
            frontmatter = match.group(1)
            if not re.search(r"^name:\s*nm-init-project-v3\s*$", frontmatter, re.MULTILINE):
                failures.append("SKILL.md name is invalid")
            description = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
            if not description or len(description.group(1).strip()) < 80:
                failures.append("SKILL.md description is not trigger-oriented enough")
        for stale in (
            "0a-docs/0a-product/REQUIREMENTS.md",
            "0a-docs/0a-product/ACCEPTANCE.md",
            "0a-docs/0b-design/DESIGN.md",
        ):
            if stale in text:
                failures.append(f"SKILL.md contains stale V3.0 instruction: {stale}")
        if "idempotent" not in text or "finish" not in text:
            failures.append("SKILL.md must document the idempotent finish command")
    if openai_yaml.is_file():
        text = openai_yaml.read_text(encoding="utf-8")
        if "$nm-init-project-v3" not in text:
            failures.append("agents/openai.yaml default_prompt must name $nm-init-project-v3")
        if "Manage the lightweight NM V3.1 Goal workflow" not in text:
            failures.append("agents/openai.yaml short_description is stale")
    if wrapper.is_file():
        text = wrapper.read_text(encoding="utf-8")
        if "urllib" in text or "raw.githubusercontent.com" in text:
            failures.append("Skill wrapper must not download an unchecked executable")
        for required in (".nm-v3-binding.json", "toolSha256", "scripts/vendor/nm_v3.py"):
            if required not in text:
                failures.append(f"Skill wrapper is missing exact-tool binding logic: {required}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("NM V3 Skill structure is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
