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
- 分支合并后必须按 `0c-workflow/BRANCHING.md` 评估是否清理。不得自动删除
  `main`、`dev`、`release/*`、`hotfix/*`、未合并分支，或仍在 review、验收、灰度、发布、回滚职责中的分支。

## Goal 工作流

- Plan 放在 `0b-goals/0a-plans/`，命名必须使用 `Plan-<YYYYMMDD>-PlanID<001>-<slug>.md`。
- Active Goal 放在 `0b-goals/0b-current/`，命名必须使用 `Goal-<YYYYMMDD>-PlanID<001>-<GoalID001>-<slug>.md`。
- 原型产物必须放在 `0a-docs/0b-design/prototype/` 下的版本目录中，目录名使用 `v<number>`，例如 `v1`、`v2`、`v3`。
- 创建新原型前必须扫描已有 `v<number>` 目录，并使用当前最大数字加 1；如果还没有版本目录，则从 `v1` 开始。每个版本目录必须自包含该版原型文件和资产，除非管理员明确要求，不得覆盖旧版本。
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
- 项目通知入口是本仓库的权威入口。项目中存在通知脚本时，必须优先使用项目自带脚本。
- 不得绕过或替换项目通知行为，直接改用系统级飞书工具，例如 `~/.agents/skills/nm-notify-feishu/scripts/notify.sh`。
- 只有管理员针对当前任务明确授权后，才允许使用系统级飞书通知作为 fallback。
- 项目飞书配置路径固定为 `~/.config/nm-docs/nm-notify-feishu.env`。
- 项目飞书通知必须包含稳定的来源项目标识。默认使用 Git 仓库根目录名；需要覆盖时使用 `--project`、`FEISHU_PROJECT_NAME` 或 `PROJECT_NAME`。
- 如果项目飞书通知不可用，必须说明失败原因属于项目脚本行为、项目配置缺失或权限不安全、本地依赖缺失、网络发送失败，还是飞书拒收；随后停止并询问管理员，不得自行改用系统级通知。
- 飞书通知送达是推荐能力，不影响已完成开发工作的有效性，但通知失败不得被静默视为成功。

## 安全规则

- 不得覆盖用户未提交改动。
- 不得执行破坏性 git 操作，除非管理员明确要求。
- 删除任何本地或远端分支前，必须确认工作区干净，并报告已合并依据、分支职责和将执行的删除命令。
- 需要删除文件时，优先移动到 `.delete-pending/` 并等待管理员确认。
- 遇到验收标准不清、验证命令缺失、外部服务不可用或安全风险时，停止并询问管理员。
