# Project Structure (NM V5)

```text
AGENTS.md                 # Agent hard rules (English source)
AGENTS.zh-CN.md           # Admin mirror
CLAUDE.md / GROK.md       # Thin CLI pointers
0a-docs/
  0a-spec/                # Confirmed Spec contracts
  0b-design/prototype/    # Optional prototypes v1, v2, ...
  0c-prompts/             # Optional Spec helpers
  DECISIONS.md
0b-runtime/
  INDEX.yaml              # Thin runtime index
  issues-ledger.md
  tasks/TASK-*.md         # Task cards
0c-workflow/              # Workflow contracts (English + ZH mirrors where required)
  resolutions/            # Ratified design resolutions
0d-scripts/               # verify, check, runner, notify
.delete-pending/          # Pending deletions (admin removes)
```

Extend this file with product-specific source trees as the project grows.
