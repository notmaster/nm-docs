# NM V6 Recovery Index

English | [简体中文](RECOVERY.zh-CN.md)

Load only the reference matching the observed failure class:

- Agent, lease, malformed result, or candidate loss: `recovery/agent.md`
- Protected ref, fetch, merge, push, or workspace ambiguity:
  `recovery/git.md`
- Release, publish, deploy, health, or rollback ambiguity:
  `recovery/delivery.md`

Recovery always acquires a new fencing token, reads canonical state, observes
the relevant external system, attaches reconciliation evidence, and proposes a
deterministic next transition. It never infers success from a missing PID,
conversation memory, or exit code. An unknown or conflicting observation enters
`ATTENTION_REQUIRED` without broadening authority.
