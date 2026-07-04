# Decisions

本文档记录项目过程中重要的产品、设计、技术、部署和流程决策。不要把所有讨论都写进来，只记录会影响后续实现和验收的关键决定。

## 记录格式

```md
## YYYY-MM-DD - <decision title>

- Decision:
- Reason:
- Alternatives:
- Impact:
- Owner:
- Related files:
```

## Decision Log

## 2026-07-05 - Project notification boundary

- Decision: Project notification scripts are authoritative. When project Feishu notification is unavailable, agents must report the concrete cause and wait for administrator authorization before using system-level Feishu notification.
- Reason: The repository and the local agent environment can both provide Feishu notification. Silent fallback to a system-level notifier hides project configuration or script problems and violates project-local ownership.
- Alternatives: Always use the system-level Feishu helper; keep project notification failures as successful fallbacks.
- Impact: `0d-scripts/nm-notify-feishu.sh` now reports unavailable project notification as a nonzero failure instead of silently falling back. `AGENTS.md` and `AGENTS.zh-CN.md` define the required operator behavior.
- Owner: Administrator.
- Related files: `AGENTS.md`, `AGENTS.zh-CN.md`, `0d-scripts/nm-notify-feishu.sh`.
