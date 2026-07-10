# NM V6 Project Structure

```text
AGENTS.md                         permanent safety/correctness invariants
AGENTS.zh-CN.md                   administrator mirror
project.json                      versioned project/action configuration
0a-docs/0a-spec/                  immutable project Specs and signed records
0a-docs/0b-design/                durable design inputs
0a-docs/DECISIONS.md              durable project decisions
0c-workflow/                      workflow, protocol, adapter, recovery docs
0d-scripts/nm-v6.py               deterministic CLI entry
0d-scripts/nmv6/                  vendored core used by the same CLI
.nm/runtime/v6/state.sqlite3      ignored transactional authority
.nm/runtime/v6/evidence/          ignored redacted content-addressed blobs
.nm/runtime/v6/projections/       ignored rebuildable human views
.nm/workspaces/                   ignored standalone candidate clones
.delete-pending/                  reversible project-file removal quarantine
```

No Task Markdown file contains mutable runtime status. Deleting projections
must not lose workflow state; the core rebuilds them from the append-only event
journal and materialized SQLite records.
