# {{PROJECT_NAME}}

This project includes NM V6: a Python 3.11+ transactional workflow with SQLite
runtime authority, deterministic gates, isolated workers, signed administrator
authorization records, and recoverable external operations. The upstream V6
implementation is administrator-accepted only for the exact source snapshot
bound by its valid canonical administrator-acceptance record; it remains
`recommended=false` and `production_ready=false`.

Upstream acceptance does not accept this project's configuration, Spec, gates,
grants, commands, environments, credentials, or delivery. Configure
`project.json`, write and confirm a project Spec under `0a-docs/0a-spec/`, pass
the required project gates, obtain valid scoped grants for protected or
external effects, and keep private signing capabilities and secret values
outside the repository and all agent contexts.

## First checks

```bash
npm install
npm run workflow:check
npm run workflow:test
npm run verify
```

## Lifecycle

```bash
./0d-scripts/python311.sh 0d-scripts/nm-v6.py status --target . --json
./0d-scripts/python311.sh 0d-scripts/nm-v6.py plan --target . --run-id RUN_ID
./0d-scripts/python311.sh 0d-scripts/nm-v6.py spec confirmation request --target . --run-id RUN_ID --expires-at RFC3339_TIME
./0d-scripts/python311.sh 0d-scripts/nm-v6.py spec confirm --target . --run-id RUN_ID --record /path/to/signed-confirmation.json
./0d-scripts/python311.sh 0d-scripts/nm-v6.py run --target . --run-id RUN_ID
```

Only signed confirmation, grant, and revocation records from the configured
trusted control plane can authorize the corresponding transitions. Technical
gate evidence remains mandatory after approval.

Read `AGENTS.md` for permanent invariants and
`0c-workflow/WORKFLOW_V6.md` for the lifecycle. Load provider and recovery
references only when needed.
