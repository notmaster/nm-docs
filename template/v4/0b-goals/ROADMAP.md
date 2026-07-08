---
spec: ""
execution_mode: staged
permissions: bypass
current_phase: 0
overall_status: not_started
---

# Roadmap

本文件是 V4 工作流的唯一运行时状态文件，由 Agent 生成和维护。

`spec` 为空表示尚未初始化。初始化方式：Agent 读取 `0a-docs/0a-spec/` 下
`status: confirmed` 的 Spec，按 `0c-workflow/WORKFLOW_V4.md` 生成阶段表和阶段小节；
`staged` 模式下必须经管理员确认后才能开始执行。

阶段状态机：`pending -> in_progress -> verified -> accepted -> merged`，异常为 `blocked`。
`auto` 模式下 `verified` 通过后直接合并进入 `merged`；`accepted` 仅用于 `staged` 模式。

## Phase Table

| Phase | Name | Branch | Status | Verify | Merged |
| --- | --- | --- | --- | --- | --- |

## Phases

生成 ROADMAP 时，为每个阶段在本节下追加一个小节，格式如下：

```text
### Phase <n>: <name>

- Objective: <一句话目标>
- Spec ref: <Spec 章节引用，例如 "14. 推荐实施阶段 / Phase 1">
- Branch: <feature|fix|docs|refactor|chore>/<slug>
- Verify:
  - <机器可验命令 1>
- Manual:
  - <人工验收项；没有则写 none>
- Result: <完成后填写：改了什么、验证结果、遗留问题>
- Handoff: <给下一个会话的交接备注；没有则写 none>
```

## Manual Acceptance Backlog

`auto` 模式下累积的人工验收项。全部阶段完成后，管理员按本清单做最终验收：

- 暂无
