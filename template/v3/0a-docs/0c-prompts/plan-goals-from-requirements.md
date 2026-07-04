# Prompt: Plan Goals From Requirements

本提示词用于让 AI 基于 `REQUIREMENTS.md`、`ACCEPTANCE.md`、`DESIGN.md` 和原型，生成一个可执行 Plan，并从 Plan 拆分出适合 `/goal` 模式执行的 Goal 文档。

## 使用方式

将下面的提示词复制给 AI，并提供项目文档内容。管理员审阅 Plan 和首个 Goal 后，再决定是否进入执行。

默认策略：

- 默认需要管理员审核。
- 默认串行执行 Goal。
- 默认允许 push 当前任务分支做备份。
- 默认不自动合并到 `dev`。

只有管理员明确授权时，才允许 Plan 设置为自动拆分、自动执行、自动验证、自动合并和自动归档。

## 模板提示词

````text
你是一名资深技术负责人、产品工程师和 AI coding agent 编排者。

请基于我提供的项目文档，生成一个可执行 Plan，并从 Plan 拆分出适合 Codex 或 Grok `/goal` 模式执行的 Goal 文档。

你必须遵守以下规则：

1. 不要把整个项目写成一个单体 Goal。
2. 先生成 Plan，再从 Plan 拆分 Goal。
3. Plan 文件命名必须使用：
   `Plan-<YYYYMMDD>-PlanID<001>-<slug>.md`
4. Goal 文件命名必须使用：
   `Goal-<YYYYMMDD>-PlanID<001>-<GoalID001>-<slug>.md`
5. 0 到 1 产品研发阶段默认串行执行。
6. 只有 API 契约、文件边界、模块边界和分支策略清晰时，才允许并行子 Agent。
7. 每个 Goal 必须有清晰的完成条件、验证方式、停止条件和归档要求。
8. 不要把依赖后续功能才能验收的内容拆成独立 Goal。
9. 不要把多个验收标准差异很大的模块塞进同一个 Goal。
10. 自动执行不等于自动合并。默认不自动合并。

默认执行字段如下：

```yaml
administrator_review_required: true
auto_execute_goals: false
auto_merge_to_dev: false
auto_push: true
execution_mode: serial
```

如果管理员明确要求“自动拆分、自动执行、自动验收、自动合并”，才允许设置：

```yaml
administrator_review_required: false
auto_execute_goals: true
auto_merge_to_dev: true
auto_push: true
execution_mode: serial
```

即使处于全自动模式，遇到以下情况也必须停止并通知管理员：

- requirements、acceptance 和 design 之间存在无法保守决策的冲突。
- 需要扩大 Plan scope。
- 需要真实外部账号、付费资源、生产密钥或生产数据。
- 涉及破坏性迁移、数据删除、权限安全策略或不可逆操作。
- `dev` 合并冲突无法安全解决。
- 同一类验证失败连续 5 次仍无法修复。
- 自动化验收通过，但视觉、产品或业务结果高度依赖管理员主观判断。

请输出以下内容：

## 1. Plan 文件

输出完整 Plan 文档内容，格式参考 `0c-workflow/PLAN_TEMPLATE.md`。

Plan 必须包含：

- YAML front matter。
- Objective。
- Inputs。
- Scope。
- Out of Scope。
- Execution Policy。
- Goal List。
- Dependency Rules。
- Verification Strategy。
- Stop Conditions。
- Completion。

## 2. Goal 文件列表

列出所有 Goal 文件名，按执行顺序排序。

每个 Goal 需要说明：

- GoalID。
- 文件名。
- 目标。
- 依赖。
- 验收标准。
- 是否适合并行。
- 推荐分支名。

## 3. 当前首个 Goal 文件

输出第一个 Goal 的完整文档内容，格式参考 `0c-workflow/GOAL_TEMPLATE.md`。

第一个 Goal 必须能独立执行、独立验证，并且不依赖尚未完成的代码。

## 4. 管理员确认点

列出管理员开始执行前必须确认的问题，尤其是：

- Plan scope 是否正确。
- Goal 拆分是否过细或过粗。
- 是否允许自动执行。
- 是否允许自动合并到 `dev`。
- 哪些验收必须人工判断。

项目文档如下：

## REQUIREMENTS.md

<粘贴 0a-docs/0a-product/REQUIREMENTS.md>

## ACCEPTANCE.md

<粘贴 0a-docs/0a-product/ACCEPTANCE.md>

## DESIGN.md

<粘贴 0a-docs/0b-design/DESIGN.md>

## Prototype

<粘贴原型说明、截图说明或链接>

## 管理员补充要求

<粘贴本轮额外要求，例如是否允许自动执行、是否允许自动合并>
````
