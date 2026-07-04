# Agent Rules

本文档只保留 Agent 每次执行都必须遵守的硬规则。完整流程见
`0c-workflow/WORKFLOW_V3.md`。

## 语言与环境

- 默认使用简体中文沟通、编写项目文档和必要代码注释。
- 默认时区为 UTC+8。

## 分支规则

- 默认开发集成分支是 `dev`。
- 禁止直接在 `main` 上进行常规开发。
- 常规任务必须从 `dev` 新建分支，分支前缀使用 `feature/*`、`fix/*`、
  `docs/*`、`refactor/*` 或 `chore/*`。
- `hotfix/*` 只用于生产紧急修复，并且从 `main` 新建。
- 合并回 `dev` 前必须完成本地验证，并获得管理员验收通过，除非当前 Plan 和当前 Goal
  都设置 `auto_merge_to_dev: true`。

## Goal 工作流

- Plan 放在 `0b-goals/0a-plans/`，命名必须使用 `Plan-<YYYYMMDD>-PlanID<001>-<slug>.md`。
- Active Goal 放在 `0b-goals/0b-current/`，命名必须使用 `Goal-<YYYYMMDD>-PlanID<001>-<GoalID001>-<slug>.md`。
- 实现前必须读取 `0b-goals/0b-current/` 下的 active Goal 及其引用的 Plan。
- `0b-goals/0b-current/` 默认只允许存在一个 active Goal；如果存在多个，必须停止并询问管理员。
- 没有 active Goal 时，不得开始大规模实现；应先询问管理员是否需要创建 Goal。
- 管理员提出新增功能、行为修改或复杂 bugfix 时，默认先创建或更新 Goal，并等待管理员确认后执行。
- 如果管理员明确要求自动实现、自动修复或无需确认，Agent 可以创建 Goal 后直接执行。
- 默认执行字段是 `administrator_review_required: true`、`auto_execute_goals: false`、
  `auto_merge_to_dev: false` 和 `auto_push: true`。
- 当 `auto_push: true` 时，Goal 完成后可以 push 当前任务分支做备份。
- 除非管理员明确批准，或当前 Plan 和当前 Goal 都设置 `auto_merge_to_dev: true`，不得合并到 `dev`。
- 管理员通过 Plan 字段明确授权全自动时，Agent 才能拆分 Plan、串行执行 Goal、验证、push、合并、归档并继续下一个 Goal。
- 自动执行完成或阻塞时，必须调用 `0d-scripts/notify-admin.sh` 通知管理员。

## 执行质量

- 非平凡任务开始前，先明确假设、风险和成功标准。
- 如果需求存在多种解释，不得静默选择；必须询问管理员或写入 Goal 等待确认。
- 优先选择能满足需求的最简单实现，不添加未要求的功能、抽象或配置。
- 修改必须保持局部化；不要顺手重构、格式化或清理无关代码。
- 每一处变更都应能追溯到当前 Goal 或管理员请求。
- 重要的产品、设计、架构、部署或流程决策必须记录到 `0a-docs/DECISIONS.md`。

## 验证规则

- 完成 Goal 前必须按照 `0c-workflow/VERIFY.md` 执行本地验证。
- 默认验证入口是 `./0d-scripts/verify.sh`。
- 轻量工作流检查入口是 `./0d-scripts/check-workflow.sh`。
- `0c-workflow/project-profile.yml` 用于声明项目类型和验证要求；早期不要求
  `verify.sh` 自动解析该文件。
- 同一类验证失败连续 5 次仍无法修复时，必须停止修复循环并通知管理员。
- 0 到 1 开发阶段不依赖远端 CI 作为质量门。

## 通知规则

- 需要管理员确认的问题或重要状态必须调用 `0d-scripts/notify-admin.sh`。
- 飞书通知是推荐能力，不是阻塞能力。
- 飞书配置路径固定为 `~/.config/nm-docs/nm-notify-feishu.env`。
- 缺少飞书配置时，脚本必须打印清晰提示并成功退出，不得阻塞开发流程。

## 安全规则

- 不得覆盖用户未提交改动。
- 不得执行破坏性 git 操作，除非管理员明确要求。
- 需要删除文件时，优先移动到 `.delete-pending/` 并等待管理员确认。
- 遇到验收标准不清、验证命令缺失、外部服务不可用或安全风险时，停止并询问管理员。
