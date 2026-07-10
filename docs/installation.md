# Installation

English | [中文](installation.zh-CN.md)

## Administrator-accepted V6 implementation

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

V4 and V3 installation tools remain available for existing projects:

```bash
bash tools/nm-v4/install-skill.sh --target-dir "$HOME/.agents/skills"
bash tools/nm-v3/install-skill.sh --target-dir "$HOME/.agents/skills"
```
