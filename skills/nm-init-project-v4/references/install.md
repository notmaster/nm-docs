# NM V4 Skill Installation

Default installation target:

```text
~/.agents/skills
```

Install from a local `nm-docs` checkout:

```bash
python3 /path/to/nm-docs/tools/nm-v4/nm_v4.py install-skill --target-dir "$HOME/.agents/skills"
```

Install with the convenience wrapper:

```bash
/path/to/nm-docs/tools/nm-v4/install-skill.sh --target-dir "$HOME/.agents/skills"
```

Use another target directory when a tool expects a different skill root:

```bash
python3 /path/to/nm-docs/tools/nm-v4/nm_v4.py install-skill --target-dir "$HOME/.codex/skills"
```

After installing, start a new agent thread and invoke:

```text
Use $nm-init-project-v4 to initialize or update this project.
```
