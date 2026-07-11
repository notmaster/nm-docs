# Agent 规则

本文档包含每个 Agent 都必须遵守的 NM V3 持久规则。只有在规划或执行
Plan/Goal 时才读取 `0c-workflow/WORKFLOW_V3.md`。

## 语言与环境

- 除非管理员另有要求，管理员沟通和项目文档默认使用简体中文。
- 时间使用带 UTC+8 偏移的 ISO 8601 格式。

## 本项目规则

只有下面项目自有区块中列出的文档才是有效项目上下文。不得仅因为
`spec.md`、设计文档、原型、架构说明或其他可选文档存在就主动发现和读取。
必需参考必须存在且非空；缺失或为空的可选参考应报告后跳过。英文和中文区块
必须同步更新。

<!-- NM-V3-PROJECT-RULES:START -->
```yaml
references:
  required: []
  optional: []
verification:
  goal_commands: []
  full_command: ./0d-scripts/verify.sh
```
<!-- NM-V3-PROJECT-RULES:END -->

## 工作授权

- 检查、评审、解释、诊断和状态请求只授权只读操作。
- 修改请求只授权范围内编辑和正常本地验证。
- `执行 Plan <id>` 在当前任务中授权 Goal 分支、实现、Goal 级验证、自审以及
  Goal 到 Plan 分支的本地集成；它不授权 push 或受保护分支集成。
- 新任务或新 Agent 会话必须获得新的 `继续执行 Plan <id>` 指令。Plan 字段只能
  记录过去的意图，不能授予新权限。
- push、Plan 合入 `dev`、`dev` 合入稳定分支、发布、部署、破坏性操作、生产访问
  和远端分支删除，都需要管理员对准确操作的明确授权。

## 分支规则

- `main` 或 `master` 是稳定分支，`dev` 是集成分支；它们都是受保护分支。
- 除管理员明确分类的 `hotfix/*` 外，检出 `main`、`master` 或 `dev` 时禁止修改
  任何文件。
- 普通工作开始前必须确认工作区干净，fetch `origin/dev`，确认本地 `dev` 与
  `origin/dev` 一致，并从该准确 SHA 创建允许的任务分支。
- 普通分支前缀为 `feature/*`、`fix/*`、`docs/*`、`refactor/*`、`chore/*`、
  `task/*`。
- 计划工作使用类似 `feature/plan-p001-slug` 的 Plan 分支；计划内 Goal 使用
  `task/goal-p001-g001-slug`，并从当前 Plan 分支头创建。独立 Goal 使用
  `task/goal-g001-slug`，从 `origin/dev` 创建。
- 只有 Goal 配置的验证和评审策略通过后，Goal 分支才能本地集成到 Plan 分支。
- 每个 Goal 不运行全量验证；所有 Goal 集成后统一运行一次。失败时重新打开受影响
  Goal，或将 Plan 标记为 `blocked`。
- 禁止 force-push 受保护引用。授权集成或 push 前必须再次 fetch 并比较预期远端
  SHA。

## Plan 与 Goal 工作流

- Plan 位于 `0b-goals/0a-plans/`，命名为 `plan-p<NNN>-<slug>.md`。
- Active Goal 位于 `0b-goals/0b-current/`。计划内 Goal 命名为
  `goal-p<NNN>-g<NNN>-<slug>.md`；独立 Goal 命名为 `goal-g<NNN>-<slug>.md`。
- active Goal 必须为零个或一个。V3.1 串行执行 Goal。
- 小任务可以不创建 Plan 或 spec，直接使用一个自包含独立 Goal。
- 计划任务可以使用可选的 `0a-docs/spec.md`，然后创建 Plan，并按需即时生成 Goal。
- 主 Agent 是 Plan/Goal 状态和执行记录的唯一写入者。子 Agent 读取自包含 Goal，
  修改代码、编写测试、默认自审，并返回结构化报告。
- 平台具备子 Agent 能力时，使用通用指令，依据 Goal 难度和范围选择合适的可用子模型；
  不假设存在特定供应商 adapter，也不硬编码模型名称。
- 默认 `independent_reviewer_required: false`。只有管理员在 Goal 开始前明确要求
  独立 Reviewer 时才设为 `true`。
- 范围、验收、依赖、数据或安全边界的实质变化会使 Plan 进入 `needs_replan`，
  停止后续 Goal，并发送 attention 事件。

## 验证与证据

- Goal 标记为 `verified` 前必须运行其声明的命令。
- 全部 Goal 本地集成后，必须运行项目规则中的全量命令，才能把 Plan 标记为
  `awaiting_review`。
- 自动验证、Agent 评审和管理员验收必须分开记录。Agent 自审不能替代必需命令或
  管理员验收。
- 记录命令、pass/fail/not-run、简短失败摘要、修复次数、commit/tree SHA 和
  评审结论。Goal 中不得保存原始日志、密钥、凭据或生产数据。

## 通知

- 只能通过 `./0d-scripts/notify-event.sh` 发送事件目录中定义的事件。
- `progress` 汇报有意义的状态变化；`attention` 用于管理员决策、评审门、重大风险
  或硬阻塞。
- 最终完成必须通过 attention 发送 `work_completed`，确保管理员收到显式交接提醒。
- 最终交接使用 `nm_v3.py finish`；它校验状态、对未变化的完成对象只发送一次，并记录
  投递结果。
- 不发送心跳、逐命令通知或未变化状态的重复通知。
- attention 禁止回退到 progress 通道。通知失败不会撤销已完成工作，但必须报告。
- 通知密钥只能存放在权限为 `600` 的
  `~/.config/nm-docs/nm-notify-feishu.env`。

## 安全

- 禁止覆盖、stash、提交或移动管理员未提交的修改。
- 未获明确授权不得执行破坏性 Git 或外部操作。
- 待删除项目文件移入 `.delete-pending/`，等待管理员确认。
- 只有子 Agent 已停止且提交已安全集成时才能移除 Worktree。Goal/Plan 分支仍承担
  评审、发布、备份、依赖或回滚职责时必须保留。
- 远端删除始终需要新的管理员明确指令。
