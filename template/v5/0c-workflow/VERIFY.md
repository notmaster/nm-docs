# Verification (NM V5)

## Entries

| Command | Role |
| --- | --- |
| `./0d-scripts/verify.sh` | Full project quality gate (Phase gate) |
| `./0d-scripts/check-workflow.sh` | Workflow structure / contract checks |
| Task `acceptance` list | Worker gate before task `done` |

## Task vs Phase

- **Task**: run acceptance commands on the task card (may be narrower than full verify).
- **Phase**: must pass full `verify.sh` plus any phase-level commands recorded in the index/notes.

## Self-repair

- Worker may repair and re-run acceptance up to **`repair_max`** (default **10**).
- After exhaustion: see stop/skip rules in `AGENTS.md`.

## 0-to-1

Local verify is the quality gate. Do not depend on remote CI until the admin enables it; remote CI should call the same `verify.sh`.
