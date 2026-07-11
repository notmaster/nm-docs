# Installation

English | [中文](installation.zh-CN.md)

## Recommended V3.1 workflow

Install the V3.1 Skill from a trusted local checkout:

```bash
python3 tools/nm-v3/nm_v3.py install-skill \
  --target-dir "$HOME/.agents/skills" \
  --source-dir .
```

The installer bundles the exact V3 tool and records its template version,
SHA-256, source commit, and source dirty status. The installed wrapper verifies
that binding on every run and never downloads an unchecked executable from a
mutable branch. Reinstall the Skill to adopt a reviewed update.

Initialize and validate a new project:

```bash
python3 tools/nm-v3/nm_v3.py init \
  --target /absolute/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
cd /absolute/project
npm install
npm run workflow:check
npm run verify
```

For an existing project, use `status`, then `update --dry-run`. V3 3.0 projects
use `migrate --dry-run`. The tool requires a clean exact `origin/dev` baseline,
creates an allowed task branch, validates staged output, and rolls back an
interrupted file transaction. Remote template refs are resolved to one immutable
commit before files are read.

Published V3.1 source should have the immutable release tag `v3.1.0`. Creating
or pushing that tag remains a separately authorized release action.

## Administrator-accepted, non-recommended V6 implementation

V6 requires Python 3.11 or newer. The exact source snapshot bound by a valid
`tools/nm-v6/administrator-acceptance.json` record is
administrator-accepted after independent evidence review. That status fails
closed after source drift; V6 remains `recommended=false` and
`production_ready=false`. Installing its Skill or passing checks does not
confirm a project Spec, sign an approval, or authorize a protected or external
mutation.

Install the thin Skill from a trusted local checkout:

```bash
bash tools/nm-v6/install-skill.sh --target-dir "$HOME/.agents/skills"
```

For a Codex-specific directory:

```bash
bash tools/nm-v6/install-skill.sh --target-dir "$HOME/.codex/skills"
```

Installation writes a mode-0600 binding to the exact reviewed checkout and its
V6 executable sources. If `NM_DOCS_DIR` is set later, it must name that same
checkout:

```bash
export NM_DOCS_DIR=/absolute/path/to/nm-docs
```

The V6 Skill never downloads an unchecked executable or searches the current
directory for one. It invokes Python in isolated mode and fails closed when the
bound source digest changes, the checkout moves, or Python 3.11+ is unavailable.
Review a V6 source update and reinstall the Skill before using the new core.
The upstream implementation's accepted status does not transfer to a generated
project. Each project must independently confirm its Spec, pass its gates, and
present valid scoped grants for protected or external effects.

## Initialize V6

Use an empty target:

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py init \
  --target /absolute/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

Initialization renders and validates outside the target, creates a bootstrap
commit on an allowed task branch, creates distinct `main` and `dev` refs, and
leaves a clean working tree. It does not make an implementation commit directly
on a protected branch.

## Update V6

Preview first:

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py update \
  --target /absolute/project \
  --source-dir . \
  --dry-run
```

An update requires:

- the target is a clean Git repository root;
- `git fetch --prune origin dev` succeeds;
- local `dev`, when present, equals the fetched remote-tracking revision;
- an allowed new task branch starts at that exact revision;
- all output is staged and validated before application;
- project-owned create-only content and changed managed guidance are preserved
  or reported as conflicts;
- an interrupted transaction can be resumed or aborted deterministically.

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py update --target /absolute/project --source-dir . --resume
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py update --target /absolute/project --source-dir . --abort
```

## Validate V6

Repository:

```bash
npm run lm
npm run v6:check
npm run v6:test
npm run skill:v6:check
```

Generated project:

```bash
npm install
npm run workflow:check
npm run workflow:test
npm run verify
```

## Trusted control plane and secrets

The CLI can create confirmation and authorization requests. A separate
administrator-controlled signer produces a record that the core verifies with a
configured public key. Private signing capabilities and secret values must
remain outside the repository, worker workspaces, agent context, command lines,
logs, evidence, and notifications.

## V5 retained for supervised trials

V5 remains available for existing supervised experiments:

```bash
bash tools/nm-v5/install-skill.sh --target-dir "$HOME/.agents/skills"
python3 tools/nm-v5/nm_v5.py init --target /absolute/project --source-dir .
python3 tools/nm-v5/nm_v5.py update --target /absolute/project --source-dir . --dry-run
```

V5 remains experimental. Its `auto` mode, runner, notification success, and
checks do not authorize unattended merge, release, deployment, production
credentials, or production data. V6 never resumes its mutable INDEX/Task-card
runtime.

## Repository Feishu notifications

Long-running `nm-docs` maintenance uses the repository's existing dual-channel
Feishu adapter and machine-local configuration:

```text
~/.config/nm-docs/nm-notify-feishu.env
```

See [Repository work notifications](repository-notifications.md). This root
adapter reports repository task progress only; it is not the V6 runtime durable
outbox or an authorization channel.

## Earlier versions

The V4 installation tool remains available for existing projects:

```bash
bash tools/nm-v4/install-skill.sh --target-dir "$HOME/.agents/skills"
```
