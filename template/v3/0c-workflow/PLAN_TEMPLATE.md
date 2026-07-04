---
plan_id: PlanID001
status: planned
administrator_review_required: true
auto_execute_goals: false
auto_merge_to_dev: false
auto_push: true
execution_mode: serial
---

# Plan: <title>

文件命名必须使用：

```text
Plan-<YYYYMMDD>-PlanID<001>-<slug>.md
```

## Objective

说明本 Plan 要完成的项目阶段、功能集合、重构或修复目标。

## Inputs

- Requirements: `0a-docs/0a-product/REQUIREMENTS.md`
- Acceptance: `0a-docs/0a-product/ACCEPTANCE.md`
- Prototype: `0a-docs/0b-design/prototype/`
- Design: `0a-docs/0b-design/DESIGN.md`

## Scope

- 本 Plan 必须完成的范围。

## Out of Scope

- 本 Plan 明确不做的范围。

## Execution Policy

- `administrator_review_required: true`
- `auto_execute_goals: false`
- `auto_merge_to_dev: false`
- `auto_push: true`
- `execution_mode: serial`
- `status: planned`

默认需要管理员验收，默认不自动合并。只有管理员明确授权，并将相关字段设置为允许时，Agent 才能自动拆分、执行、验证、push、合并和归档 Goal。

## Goal List

每个 Goal 文件命名必须使用：

```text
Goal-<YYYYMMDD>-PlanID<001>-<GoalID001>-<slug>.md
```

| Goal | File | Depends On | Summary | Verification | Status |
| --- | --- | --- | --- | --- | --- |
| GoalID001 | `Goal-<YYYYMMDD>-PlanID001-GoalID001-<slug>.md` | none | 待填写 | `./0d-scripts/verify.sh` | planned |

## Dependency Rules

- 0 到 1 产品研发阶段默认串行执行。
- 后续 Goal 依赖前序 Goal 的输出时，不得并行。
- 只有在 API 契约、数据边界、文件边界和分支策略清晰时，才允许并行子 Agent。
- 前后端分离项目可以在 API contract 经管理员确认后并行执行前端和后端 Goal。

## Verification Strategy

- 每个 Goal 完成前必须运行 `./0d-scripts/verify.sh`。
- 同一类验证失败连续 5 次仍无法修复时，停止并通知管理员。
- Plan 完成前必须确保所有 Goal 已完成、归档，并且最终本地验证通过。

## Stop Conditions

遇到以下情况必须暂停并通知管理员：

- requirements、acceptance 和 design 之间存在无法保守决策的冲突。
- 需要扩大本 Plan 的 Scope。
- 需要真实外部账号、付费资源、生产密钥或生产数据。
- 涉及破坏性迁移、数据删除、权限安全策略或不可逆操作。
- `dev` 合并冲突无法安全解决。
- 自动化验收通过，但结果高度依赖管理员主观判断。

## Completion

Plan 完成时必须说明：

- 完成的 Goal 列表。
- 每个 Goal 的验证结果。
- 是否已 push。
- 是否已合并到 `dev`。
- 是否仍需管理员验收。
- 遗留问题和建议的后续 Plan。
