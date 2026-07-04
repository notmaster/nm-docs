---
plan_id: PlanID001
goal_id: GoalID001
status: planned
administrator_review_required: true
auto_execute_goals: false
auto_merge_to_dev: false
auto_push: true
---

# Goal: <title>

## Objective

一句话说明最终要达成什么。

## Inputs

- Requirements: `0a-docs/0a-product/REQUIREMENTS.md`
- Acceptance: `0a-docs/0a-product/ACCEPTANCE.md`
- Prototype: `0a-docs/0b-design/prototype/`
- Design: `0a-docs/0b-design/DESIGN.md`
- Plan: `0b-goals/0a-plans/Plan-<YYYYMMDD>-PlanID001-<slug>.md`

## Scope

- 本次必须完成的内容。

## Out of Scope

- 本次明确不做的内容。

## Branch

- Base: `dev`
- Working branch: `<feature|fix|docs|refactor|chore>/<slug>`
- `administrator_review_required: true`
- `auto_execute_goals: false`
- `auto_merge_to_dev: false`
- `auto_push: true`
- `status: planned`

## Steps

1. 待填写。
2. 待填写。
3. 待填写。

## Verification

必须运行：

```bash
./0d-scripts/verify.sh
```

项目类型附加检查：

- common:
- docs:
- web:
- backend:
- cli:
- mobile:
- desktop:

## Manual Acceptance

管理员需要检查：

- 待填写。

## Stop Conditions

遇到以下情况必须暂停并通知管理员：

- active Goal 不唯一。
- 验收标准不清。
- 必需工具或外部服务缺失。
- 同一类验证失败连续 5 次仍无法修复。
- 需要扩大 Scope。
- 存在安全、数据破坏或破坏性 git 操作风险。

## Completion

完成时必须说明：

- 改了什么。
- 运行了哪些验证。
- 当前分支。
- 是否已 push。
- 是否等待管理员验收。
- 是否合并到 `dev`。

## Result

归档关键 Goal 时填写：

- Status: `<completed|cancelled|blocked>`
- Verification:
- Review:
- Plan:
- Working branch:
- Merged to dev: `<yes|no>`
- Pushed: `<yes|no>`
- Notes:
