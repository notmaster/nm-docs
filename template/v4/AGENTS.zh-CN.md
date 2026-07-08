# Agent Rules

本文档只保留 Agent 每次执行都必须遵守的硬规则。完整流程见 `0c-workflow/WORKFLOW_V4.md`，各家 CLI 启动配方见 `0c-workflow/AGENT_RECIPES.md`。

## 语言与环境

- 默认使用简体中文沟通、编写项目文档和必要代码注释。
- 默认时区为 UTC+8。

## 执行合约

- 会话交接三件套：`AGENTS.md`、`0a-docs/0a-spec/` 下已确认的 Spec、`0b-goals/ROADMAP.md`。开始实质工作前必须读完三件套；其他工作流文档按需加载。
- 只允许执行 frontmatter 为 `status: confirmed` 的 Spec。
- `0b-goals/ROADMAP.md` 是唯一运行时状态文件。阶段状态、结果和交接备注都记录在这里；影响后续的关键决策记录到 `0a-docs/DECISIONS.md`。
- 没有已确认 Spec 和对应 ROADMAP 阶段条目时，不得开始大规模实现，先询问管理员。

## 执行模式

- `staged`（默认）：每个会话只执行一个阶段。实现、验证、push、通知，然后停等管理员验收。验收通过后才允许合并回 `dev`。
- `auto`：仅当 Spec frontmatter 设置 `execution_mode: auto`，或管理员在启动指令中明确授权时允许。串行执行各阶段；验证通过后 push、合并回 `dev`、更新 ROADMAP、发通知并继续。
- 启动指令可以覆盖 Spec 中的默认模式。
- `auto` 模式下人工验收项不得阻塞执行，统一追加到 ROADMAP 的待人工验收清单。

## 分支规则

- 默认集成分支是 `dev`，禁止直接在 `main` 上常规开发。
- 每个阶段从最新 `dev` 新建任务分支，前缀使用 `feature/*`、`fix/*`、`docs/*`、`refactor/*` 或 `chore/*`。`hotfix/*` 只用于生产紧急修复并从 `main` 新建。
- ROADMAP 的创建与状态更新属于工作流簿记，允许直接提交到 `dev`；其余变更一律走任务分支。
- 合并与清理遵循 `0c-workflow/BRANCHING.md`。不得自动删除 `main`、`dev`、`release/*`、`hotfix/*`、未合并分支，或仍在 review、验收职责中的分支。

## 执行质量

- 非平凡任务开始前，先明确假设、风险和成功标准。
- 优先选择最简单实现；不添加未要求的功能、抽象，不顺手重构。
- 每一处变更都应能追溯到当前阶段或管理员请求。

## 验证规则

- 阶段完成的定义：`./0d-scripts/verify.sh` 与 ROADMAP 中该阶段的 `Verify:` 命令全部通过。
- 同一类验证失败连续 5 次仍无法修复时，必须停止修复循环并通知管理员。
- 0 到 1 开发阶段以本地验证为质量门，不依赖远端 CI。

## 通知规则

- 阶段完成、阻塞、需要决策和全部完成时，必须调用 `./0d-scripts/notify-admin.sh`。
- 项目通知脚本是权威入口。未经管理员明确授权，不得改用系统级通知工具。项目飞书配置：`~/.config/nm-docs/nm-notify-feishu.env`。
- 通知失败不得被静默视为成功。

## 安全与停止条件

- 不得覆盖用户未提交改动；不得执行破坏性 git 操作，除非管理员明确要求。
- 需要删除文件时，移动到 `.delete-pending/` 并等待管理员确认。
- 遇到以下情况必须停止并通知管理员：Spec 冲突无法保守决策、需要扩大范围、需要真实外部账号、付费资源、生产密钥或生产数据、涉及破坏性迁移或不可逆操作、`dev` 合并冲突无法安全解决。
