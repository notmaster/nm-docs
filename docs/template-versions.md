# Template Versions

English | [中文](template-versions.zh-CN.md)

## Administrator-accepted implementation: V6

`template/v6` implements the contract in `docs/nm-v6-workflow-spec.md`. The
exact source snapshot bound by a valid
`tools/nm-v6/administrator-acceptance.json` record is
administrator-accepted after independent evidence review. The status fails
closed after source drift and is not transferable to another snapshot. V6 is
still `recommended=false` and `production_ready=false`.

V6 replaces the mutable Markdown/YAML runtime model with one transactional
SQLite authority, a deterministic reducer, independent gates and evidence,
signed administrator control records, isolated candidates, protected Git
integration, recoverable delivery Operations, audit chaining, and a durable
outbox. V6 requires Python 3.11 or newer and no mandatory non-standard runtime
service or Python dependency.

Tools:

- `template/v6`
- `tools/nm-v6/nm_v6.py`
- `skills/nm-init-project-v6`

V6 is intentionally incompatible with V5 runtime state. It refuses automatic
import or resumption of V5 `0b-runtime/INDEX.yaml` and Task cards. Project
requirements and durable decisions may be translated only through an explicit,
reviewed new V6 Spec.

Repository acceptance does not accept a generated project's configuration or
delivery. Each generated project still requires its own confirmed Spec,
technical gates, and valid scoped grants.

## Experimental: V5

`template/v5` is retained for supervised trials and repository maintenance. It
is not approved for unattended merge, release, deployment, production
credentials, or production data.

V5 is a hybrid orchestration experiment:

- Confirmed Spec under `0a-docs/0a-spec/`
- Runtime truth in `0b-runtime/INDEX.yaml` plus Task cards
- Runner, short orchestrator sessions, and minimum-context workers
- `staged` and `auto` trial modes
- Event notifications and CLI/Skill installation

Tools: `skills/nm-init-project-v5` and `tools/nm-v5/nm_v5.py`.

## Previous: V4

`template/v4` is the prior Spec-driven workflow with `ROADMAP.md` and fresh
per-Phase sessions. Keep it for existing projects; do not infer production
authorization from its version or checks.

Tools: `skills/nm-init-project-v4` and `tools/nm-v4/nm_v4.py`.

## Previous: V3

`template/v3` contains the goal-driven workflow with `REQUIREMENTS.md`,
`ACCEPTANCE.md`, `DESIGN.md`, and Plan/Goal files under `0b-goals/`.

Tools: `skills/nm-init-project-v3` and `tools/nm-v3/nm_v3.py`.

## Previous: V2

`template/v2` contains the earlier multi-agent collaboration workflow with TODO
files, PR review gates, and heavier orchestration rules.

## Legacy: V1

`template/v1` is retained for compatibility and historical reference.
