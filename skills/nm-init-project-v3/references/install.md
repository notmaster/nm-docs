# NM V3 Skill Installation

Default installation target:

```text
~/.agents/skills
```

Install from a local `nm-docs` checkout:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py install-skill --target-dir "$HOME/.agents/skills"
```

The installer bundles the exact V3 tool, records its SHA-256, template version,
source commit, and source dirty status, and verifies the binding on every run.
The installed Skill does not download a mutable tool from `main`; reinstall it
to adopt a reviewed update.

Install with the convenience wrapper:

```bash
/path/to/nm-docs/tools/nm-v3/install-skill.sh --target-dir "$HOME/.agents/skills"
```

Use another target directory when a tool expects a different skill root:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py install-skill --target-dir "$HOME/.codex/skills"
```

After installing, start a new agent thread and invoke:

```text
Use $nm-init-project-v3 to initialize a new project.
```
