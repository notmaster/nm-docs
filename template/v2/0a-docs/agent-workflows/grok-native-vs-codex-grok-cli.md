# Grok 原生多角色 vs Codex + Grok CLI

本文说明两种多模型协同编排方式的区别、适用场景，以及 `0a-docs/prompts/` 下各模板在全自动流程中的角色。

## 1. 两种编排模型

### 1.1 Codex + Grok CLI（原默认）

```text
Human Admin（可选编排）
    ↓
Codex GPT = Planner / Supervisor / Reviewer
    ↓ nm-use-grok
GrokBuild CLI（独立进程）= Coder / Fixer
    ↓
GitHub PR → dev
```

- **Supervisor 载体**：Codex 客户端中的 GPT 模型。
- **Coder / Fixer 载体**：本机 `grok` CLI 进程（TUI 或 headless）。
- **会话连续性**：`--session-id` 创建 UUID；Fixer 用 `--resume <UUID>` 恢复。
- **监督方式**：Supervisor 轮询 Grok 进程输出（如 streaming-json），60 秒增量检查。
- **入口提示词**：[`supervisor-start.md`](../prompts/supervisor-start.md) + 操作手册中的 GrokBuild 章节。

### 1.2 Grok 原生多角色（本方案）

```text
Human Admin（事后审计高风险总表；异常接管）
    ↓
Grok 主会话 = Supervisor（+ 必要时 Planner）
    ↓ Task 子 agent
Grok 子 agent = Coder / Reviewer / Fixer
    ↓
GitHub PR → dev
```

- **Supervisor 载体**：Cursor 中的 Grok 主会话。
- **Coder / Reviewer / Fixer 载体**：同一 Grok 环境内的 Task 子 agent。
- **会话连续性**：Task 返回的 `agentId`；Fixer 用 `resume: <coderAgentId>`。
- **监督方式**：等待子 agent 完成 + 事件驱动事实核查（HEAD、PR、CI 变化）。
- **入口提示词**：[`supervisor-start-grok.md`](../prompts/supervisor-start-grok.md)。
- **明确禁止**：Supervisor 或子 agent 使用 `$nm-use-grok` / `grok` CLI 调用自身。

## 2. 对照表

| 维度                     | Codex + Grok CLI                                                                                    | Grok 原生多角色                                                   |
| ------------------------ | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Supervisor               | Codex GPT                                                                                           | Grok 主会话                                                       |
| Coder                    | `grok -p` 外部进程                                                                                  | `Task(generalPurpose)`                                            |
| Reviewer                 | Codex 新对话（推荐）                                                                                | `Task(code-reviewer, readonly=true)`                              |
| Fixer                    | `grok --resume <UUID>`                                                                              | `Task(resume=coderAgentId)`                                       |
| 流程 SKILL               | `nm-collab-workflow-v2` + `nm-use-grok`                                                             | 仅 `nm-collab-workflow-v2`                                        |
| 会话 ID                  | Grok CLI UUID                                                                                       | Task `agentId`                                                    |
| 进度可见性               | 轮询 CLI stdout                                                                                     | 子 agent 完成后一次性返回                                         |
| 卡住恢复                 | 停进程 + `--resume`                                                                                 | 记录检查点 + `resume` 子 agent                                    |
| 角色隔离                 | 不同客户端 / 不同进程                                                                               | 主会话 vs 子 agent 上下文隔离                                     |
| 操作手册                 | [`multi-agent-coding-operation-manual-v2.md`](./multi-agent-coding-operation-manual-v2.md) 全文适用 | 跳过「阶段 C/E GrokBuild」；改用 Task 调度                        |
| 全自动 Supervisor 提示词 | 含 Grok CLI 参数与轮询规则                                                                          | [`supervisor-start-grok.md`](../prompts/supervisor-start-grok.md) |
| 合并到 `dev`             | 门禁通过后须管理员或明确授权                                                                        | Reviewer `approve` 且门禁通过后 Supervisor **自动合并**           |
| 敏感文件                 | 合并前须管理员**事前**确认已读                                                                      | **不阻塞合并**；须在总 TODO 完整留痕，管理员**事后**复审总表      |
| 高风险留痕               | 分散在专表、PR、单 TODO                                                                             | 总 TODO「**高风险操作总表**」为唯一汇总入口，只追加不重写         |

## 3. 共用的部分（两种方案一致）

以下契约 **不因编排方式改变**：

- `AGENTS.md` / `CLAUDE.md` 核心规则
- [`multi-agent-coding-v2.md`](./multi-agent-coding-v2.md) 锁状态、串行 PR、`dev` 集成、Reviewer 审查与测试门禁
- 总 TODO / 单 TODO 结构与 `runs` 追加规则
- `.delete-pending/` 删除流程（禁止 Agent 直接删除）
- `needs-replan` / `needs-human` 处理
- Reviewer 两轮审查（首轮只读 + 文档 diff 复核）
- Fixer 只修阻塞项、更新原 PR、不建第二个 PR
- `npm run fm` / `npm run lm` / `npm run workflow:check` 及项目测试
- 敏感文件与高风险须在总 TODO 留痕（见下文「合并与审计策略」）

## 3.1 合并与审计策略（两种方案差异）

详见 [`multi-agent-coding-v2.md` 编排模式与合并策略](./multi-agent-coding-v2.md#编排模式与合并策略)。

### Codex + Grok CLI / 人工编排

- 敏感文件变更须管理员事前确认已读，未确认前不得合并到 `dev`。
- 合并动作通常由管理员执行或明确授权后执行。

### Grok 原生全自动

- 高度自动化：修改、门禁、合并到 `dev` 均由 Supervisor 推进，无需逐步等待管理员审核。
- 敏感文件与越界修改等**不阻塞**合并，但必须在 `<TOTAL_TODO>` 的「高风险操作总表」追加一行，并同步写入敏感文件、测试风险、人工验收、待删除文件等专表。
- 单 TODO 与 PR 可写详情，但总 TODO 总表是管理员事后一眼审查的**唯一汇总入口**；合并时将「管理员复审」标为 `待审查`。
- `dev` → `master` / `main` 仍只由管理员确认，不受全自动影响。

## 4. `0a-docs/prompts/` 模板是否必须修改？

### 4.1 设计定位

根据 [`multi-agent-coding-operation-manual-v2.md`](./multi-agent-coding-operation-manual-v2.md) 第 5 节和 [`README.md`](../../README.md)：

- `coder-task.md`、`reviewer-pr.md`、`fixer-request-changes.md`、`planner-split-todo.md`、`supervisor-start.md` 的**首要用途**是：**管理员手动复制粘贴**到对应 Agent（Codex 或 GrokBuild TUI）。
- `0c-tools/agent-workflow/check-workflow.mjs` 只校验这些文件**是否存在**，**不会**在运行时自动加载或执行它们。
- **没有任何脚本**会在全自动流程中隐式调用这些模板。

### 4.2 全自动流程中如何使用

| 模板                       | Codex+Grok CLI 全自动                          | Grok 原生全自动                             | 是否必须改模板          |
| -------------------------- | ---------------------------------------------- | ------------------------------------------- | ----------------------- |
| `supervisor-start.md`      | Codex Supervisor 入口；内嵌或生成 Coder 提示词 | **不使用**；改用 `supervisor-start-grok.md` | 否（保留给 Codex 方案） |
| `supervisor-start-grok.md` | 不适用                                         | Grok Supervisor 入口                        | 已新建，无需改旧文件    |
| `coder-task.md`            | Supervisor 填占位符后给 Grok CLI               | Supervisor 读模板 → 拼 Task prompt          | **否**                  |
| `reviewer-pr.md`           | 管理员粘贴到 Codex Reviewer                    | Supervisor 读模板 → 拼 Task prompt          | **否**                  |
| `fixer-request-changes.md` | 管理员粘贴到 Grok Fixer                        | Supervisor `resume` Coder 时追加            | **否**                  |
| `planner-split-todo.md`    | 管理员粘贴到 Codex Planner                     | `needs-replan` 时主会话或子 agent 参考      | **否**                  |

**结论：**

1. **`coder-task.md` / `reviewer-pr.md` / `fixer-request-changes.md` 不必须修改**即可支持 Grok 原生全自动流程。
2. 它们在全自动中的角色是 **角色契约参考文档**，由 Supervisor **读取内容、替换占位符、追加本轮约束**后写入 Task 的 `prompt` 参数。
3. 仅当某条 Grok 特有约束（例如「禁止再派 Task」）需要**长期、反复**出现时，才考虑：
   - 修改对应角色模板（影响 Codex 手动流程），或
   - 新建 `coder-task-grok.md` 等并行变体（推荐，避免破坏原手册路径）。

### 4.3 何时新建 `-grok` 变体

建议在以下情况新建并行模板，而不是改原文件：

- Grok 子 agent 专有约束与 Codex/GrokBuild TUI 场景冲突。
- 同一约束已连续多次在 `supervisor-start-grok.md` 末尾手动追加。
- 需要把 Task `subagent_type`、`readonly`、`resume` 等参数写进角色契约本身。

当前阶段：**只需 `supervisor-start-grok.md` + 本对照文档**；角色模板保持通用即可。

## 5. 选型建议

| 场景                                                    | 推荐方案                                |
| ------------------------------------------------------- | --------------------------------------- |
| 管理员希望 Codex 审查、Grok 编码，且习惯 GrokBuild TUI  | Codex + Grok CLI + 操作手册             |
| 管理员只在 Cursor 使用 Grok，希望单入口全自动合并 `dev` | Grok 原生 + `supervisor-start-grok.md`  |
| 敏感文件合并前必须人工签字                              | Codex + Grok CLI + 操作手册             |
| 接受自动合并，事后在总 TODO 总表审计高风险              | Grok 原生 + `supervisor-start-grok.md`  |
| 需要 streaming 级进程监督、headless `grok -p`           | Codex + Grok CLI                        |
| Reviewer 必须与 Coder 不同模型（如 GPT）                | Codex + Grok CLI（Reviewer 仍在 Codex） |
| Reviewer 可与 Coder 同 Grok，靠 readonly 子 agent 隔离  | Grok 原生                               |

## 6. 相关文件索引

- Codex Supervisor 入口：[`0a-docs/prompts/supervisor-start.md`](../prompts/supervisor-start.md)
- Grok Supervisor 入口：[`0a-docs/prompts/supervisor-start-grok.md`](../prompts/supervisor-start-grok.md)
- 角色契约（通用）：[`coder-task.md`](../prompts/coder-task.md)、[`reviewer-pr.md`](../prompts/reviewer-pr.md)、[`fixer-request-changes.md`](../prompts/fixer-request-changes.md)
- 流程契约：[`multi-agent-coding-v2.md`](./multi-agent-coding-v2.md)
- 人工编排手册：[`multi-agent-coding-operation-manual-v2.md`](./multi-agent-coding-operation-manual-v2.md)
