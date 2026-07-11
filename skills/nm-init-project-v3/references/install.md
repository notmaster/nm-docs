# NM V3 Skill Installation

The repository Skill is a self-contained, versioned distribution compatible
with `vercel-labs/skills`. It includes the exact V3 tool and a binding that the
wrapper verifies before every run.

## vercel-labs/skills

From the root of a trusted local checkout, open the interactive installer:

```bash
npx skills add . --global
```

After the immutable `v3.1.0` release tag is published, the equivalent remote
installation is:

```bash
npx skills add notmaster/nm-docs@v3.1.0 --global
```

Select `nm-init-project-v3` and the target agents in the prompt. `--global`
selects the user-level canonical root at `~/.agents/skills`; without it, the
default scope is the current project's `.agents/skills`. Keep the default
single-copy installation behavior and let the CLI manage compatibility links
when an agent-specific path is required.

List and remove the managed installation with:

```bash
npx skills list --global
npx skills remove nm-init-project-v3 --global
```

Use only an administrator-reviewed immutable tag for remote installs.
Do not update this Skill from mutable `main`. To adopt a reviewed release, rerun
`skills add` with its new immutable tag. The installed artifact remains runnable
without an `nm-docs` checkout and fails closed if its bound tool changes.

## Built-in installer

Default installation target:

```text
~/.agents/skills
```

Install from a local `nm-docs` checkout:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py install-skill --target-dir "$HOME/.agents/skills"
```

The installer copies the same repository distribution used by
`vercel-labs/skills`, then records its source commit and dirty status in the
installed binding. It refuses to install when the repository bundle has drifted
from `tools/nm-v3/nm_v3.py`. Reinstall it to adopt a reviewed update.

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

## Repository maintenance

After changing `tools/nm-v3/nm_v3.py`, regenerate and validate the committed
distribution before review:

```bash
npm run skill:v3:sync
npm run skill:v3:check
npm run skill:v3:vercel:check
```
