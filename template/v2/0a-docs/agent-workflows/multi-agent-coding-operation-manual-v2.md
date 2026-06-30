# 多模型协同编程操作手册 V2

## 1. 目的与适用范围

本文说明如何由管理员手动编排多个大语言模型完成同一个软件项目。默认组合为：

- Codex 客户端中的 GPT 模型负责 Planner、Supervisor 和 Reviewer。
- GrokBuild CLI 中的 Grok 模型负责 Coder 和 Fixer。
- GitHub PR 保存代码差异、检查结果、审查意见和合并记录。
- Human Admin 负责跨模型传递信息、批准敏感操作和决定合并。

该流程属于“人工编排、Agent 内自动执行”：单个 Agent 可以自动读取文件、修改代码、运行测试和操作 Git，但角色切换、提示词传递、PR 审查和稳定分支合并均由管理员控制。不要假设 Codex 和 GrokBuild 能直接互相发送消息。

本文可用于 JavaScript、用户脚本、服务端程序或其他 Git 项目。示例使用“某双语翻译用户脚本”，不包含真实账号、令牌、会话 ID、私有仓库地址或本机绝对路径。

## 2. 术语和占位符

| 占位符              | 含义                | 脱敏示例                          |
| ------------------- | ------------------- | --------------------------------- |
| `<PROJECT_ROOT>`    | 本地项目根目录      | `/path/to/project`                |
| `<REQUIREMENT_DOC>` | 已确认的需求文档    | `scripts/<translator>/需求.md`    |
| `<TOTAL_TODO>`      | 项目总 TODO         | `0b-todo/000-<project>-总TODO.md` |
| `<CURRENT_TODO>`    | 当前单 TODO         | `0b-todo/<date>-01-feat-xxx.md`   |
| `<TODO_ID>`         | 当前任务标识        | `TODO-001`                        |
| `<TASK_BRANCH>`     | 当前任务分支        | `agent/coder/TODO-001`            |
| `<PR_URL>`          | 当前 PR 地址        | `https://github.com/.../pull/1`   |
| `<GROK_SESSION_ID>` | GrokBuild 会话 UUID | 仅保存在私有执行记录中            |
| `<REVIEW_COMMENTS>` | Reviewer 阻塞意见   | 从审查输出或 PR 评论复制          |

公开教程中保留占位符。内部执行时替换为真实值，但不得把令牌、Cookie、私钥、完整用户目录或未公开仓库地址写入提示词模板和公开截图。

## 3. 角色与责任边界

| 角色        | 推荐载体       | 主要职责                         | 禁止事项                       |
| ----------- | -------------- | -------------------------------- | ------------------------------ |
| Human Admin | 人工           | 编排、审批、暂停、恢复、最终合并 | 跳过记录直接切换任务           |
| Planner     | Codex GPT      | 理解需求、拆分 TODO、定义验收    | 编写业务代码                   |
| Supervisor  | Codex GPT      | 锁、分支、PR 状态和角色调度      | 代替 Coder 实现当前 TODO       |
| Coder       | GrokBuild Grok | 实现一个 TODO、测试、创建 PR     | 越界实现后续 TODO              |
| Reviewer    | Codex GPT      | 独立审查 diff、测试、边界和风险  | 未审查即批准，顺手重写业务代码 |
| Fixer       | GrokBuild Grok | 修复 Reviewer 指出的阻塞问题     | 增加新功能或重写规划           |

同一个模型可以承担多个角色，但每次提示词必须明确当前角色。Reviewer 推荐使用新的 Codex 对话，减少被 Coder 解释和历史结论影响的风险。

## 4. 一次性准备

### 4.1 项目基础设施

项目至少需要：

- `AGENTS.md` 和 `CLAUDE.md`。
- `0a-docs/agent-workflows/multi-agent-coding-v2.md`。
- `0a-docs/agent-workflows/templates/`。
- `0a-docs/prompts/`。
- `0b-todo/`。
- `0c-tools/agent-workflow/`。
- `.github/pull_request_template.md`。
- `.github/workflows/ci.yml`。
- `dev` 开发集成分支。

缺少这些内容时，先使用 `nm-init-project-v2` 初始化或审计，不要在业务开发过程中临时拼装流程文件。

### 4.2 GitHub

管理员手动确认：

1. 本地仓库已配置 `origin`。
2. `dev` 已推送到 GitHub。
3. 任务分支从 `dev` 创建，PR 目标分支是 `dev`。
4. `main` 或 `master` 只接收管理员确认的发布 PR。
5. PR 模板、CI 和协同状态 labels 可用。

同一项目默认只保留一个 active 编码 PR。GitHub PR 是“提议把来源分支合并到目标分支”的审查载体，正式合并前应查看 `Files changed`、检查结果和未解决评论。参考 [GitHub Pull Request 文档](https://docs.github.com/en/pull-requests)。

### 4.3 Skill 安装

多模型共享 Skill 时，以以下目录为单一安装位置：

```text
~/.agents/skills/
├── nm-collab-workflow-v2/
├── nm-init-project/
└── nm-init-project-v2/
```

如果 Skill 仍在 `~/.codex/skills/`，先移动到 `~/.agents/skills/`，修正 Skill 内旧路径，再重启客户端或创建新会话。不要在两个目录维护重复副本。

Codex 中通过自然语言或 `$nm-collab-workflow-v2` 触发 Skill。GrokBuild 会读取 `AGENTS.md`，并能发现 `~/.agents/skills/`；进入 TUI 后使用 `/skills` 检查，再使用 `/nm-collab-workflow-v2` 或在提示词中明确要求遵循该 Skill。参考 [xAI Skills 文档](https://docs.x.ai/build/features/skills-plugins-marketplaces)。

`nm-init-project` 和 `nm-init-project-v2` 只负责初始化、审计和同步基础设施，不负责实现业务 TODO。

### 4.4 GrokBuild CLI 预检

每次开始一个项目阶段前运行：

```bash
cd "<PROJECT_ROOT>"
command -v grok
grok --version
grok --help
grok inspect --json
grok models
git status --short --branch
```

本手册基于本地 `grok 0.2.72` 验证。CLI 可能更新，版本相关选项必须以当前 `grok --help` 为准。

首次使用建议保留默认询问权限，不启用 `--always-approve`。管理员应逐项批准写文件、执行命令、提交和推送。只有风险边界已验证且明确需要无人值守时，才临时启用自动批准。GrokBuild 权限模式说明见 [xAI Modes and Commands](https://docs.x.ai/build/modes-and-commands)。

### 4.5 启动前基线

开始拆分需求前确认：

```bash
git status --short --branch
git branch --all
npm run lm
npm run workflow:check
```

工作区存在与当前流程无关的未提交改动时，先由管理员处理。不要让 Coder 在来源不明的脏工作区开始编码。

## 5. 提示词模板的使用和维护

### 5.1 单次使用

1. 打开 `0a-docs/prompts/` 下对应角色模板。
2. 复制内容到目标 Agent。
3. 替换 `<...>` 占位符。
4. 在末尾追加本轮特有约束。
5. 不为一次性差异修改模板源文件。

本轮覆盖指令示例：

```text
本轮补充约束：
- Reviewer 首轮只读，不修改项目文件。
- 审查结果由 Supervisor 写入 TODO。
- 不输出本机绝对路径、令牌或会话 ID。
```

### 5.2 持久修改

当同一补充约束连续多次需要手动追加时：

1. 修改项目内对应提示词模板。
2. 更新流程文档和模板版本说明。
3. 运行 `npm run fm`、`npm run lm` 和 `npm run workflow:check`。
4. 通过 PR 更新 `nm-docs/template/v2/` 唯一模板源。
5. 其他项目使用 `nm-init-project-v2 --mode audit/sync` 获取更新。

项目内模板用于当前仓库，`nm-docs` 用于跨项目分发；不要只改个人聊天记录。

## 6. 标准执行流程

### 阶段 A：Planner 拆分需求

#### Planner 人工操作

1. 在 Codex 客户端打开项目根目录。
2. 新建 Planner 对话。
3. 复制 `planner-split-todo.md`。
4. 填入需求文档、项目名称、稳定分支和 `dev`。
5. 明确要求使用 `$nm-collab-workflow-v2`。

脱敏示例：

```text
使用 $nm-collab-workflow-v2，以 Planner 身份工作。
读取 AGENTS.md、PROJECT_STRUCTURE.md、协同流程和：
<REQUIREMENT_DOC>

将“某双语翻译用户脚本”需求拆分为总 TODO 和单 TODO。
只创建规划文档，不编写脚本代码。
```

在本仓库内部执行时，`<REQUIREMENT_DOC>` 可替换为：

```text
scripts/NM-Bilingual-Translator/NM-Bilingual-Translator-需求文档-V1.0.md
```

公开教程应改成泛化路径，例如 `scripts/<translator>/requirements-v1.md`。

#### Planner 自动执行

- 读取规则和需求。
- 比较至少两种拆分方案。
- 创建总 TODO 和单 TODO。
- 定义依赖、允许范围、禁止范围、测试和验收标准。
- 运行 Markdown 检查。

#### Planner 审查门禁

- TODO 是否按“功能闭环 + 测试闭环”拆分。
- 是否能做到一个 TODO 对应一个 PR。
- 是否包含后续 TODO 才应实现的内容。
- 测试和人工验收是否可操作。
- 敏感文件和公开发布风险是否已标记。

未通过时，只让 Planner 修改 TODO；不要启动 Coder。

### 阶段 B：Supervisor 启动一个 TODO

#### Supervisor 人工启动

1. 选择依赖已满足的 `todo-ready` TODO。
2. 在 Codex 中复制 `supervisor-start.md`。
3. 填入总 TODO、当前 TODO、Coder 和 Reviewer。

示例角色映射：

```text
Coder：GrokBuild CLI / Grok
Reviewer：Codex 客户端 / GPT
```

#### Supervisor 自动执行

- 核对 `currentLock`。
- 核对 TODO 依赖和代码事实。
- 检查 `dev`、工作区和 active PR。
- 把锁更新为 `coding`。
- 从最新 `dev` 创建 `<TASK_BRANCH>`。
- 输出已经填好的 Coder 提示词。

#### Supervisor 管理员门禁

```bash
git status --short --branch
git log -1 --oneline
gh pr list --state open
```

确认当前分支、锁和 TODO 一致后，再启动 GrokBuild。

### 阶段 C：GrokBuild 执行 Coder

#### Coder 人工启动

```bash
cd "<PROJECT_ROOT>"
git status --short --branch
grok inspect --json
grok
```

进入 TUI 后：

1. 使用 `/skills` 确认 `nm-collab-workflow-v2` 可见。
2. 必要时使用 `/model <name>` 选择模型。
3. 保持默认询问权限。
4. 粘贴 Supervisor 生成的 Coder 提示词。
5. 对每次工具调用检查路径、命令和影响范围。

推荐在 Coder 提示词末尾增加：

```text
只处理 <CURRENT_TODO>。
开始前报告当前分支、工作区状态和计划修改文件。
遇到规划错误时停止并请求 Reviewer 判断，不自行扩大范围。
完成后必须给出 PR URL、测试结果、变更文件和剩余风险。
```

#### Coder 自动执行

- 读取规则、总 TODO、当前 TODO 和依赖。
- 实现当前 TODO。
- 更新必要测试和文档。
- 追加当前 TODO 执行记录。
- 运行 lint、workflow、build 和测试。
- 提交并推送任务分支。
- 创建目标为 `dev` 的 PR。

管理员不能只看 Coder 的“完成”消息，必须检查：

```bash
git status --short --branch
git diff dev...HEAD --stat
gh pr view "<PR_URL>" --json state,baseRefName,headRefName,url
```

### 阶段 D：Codex Reviewer 独立审查

#### Reviewer 人工启动

1. 在 Codex 客户端新建 Reviewer 对话。
2. 打开同一项目，但不要与 GrokBuild 同时写文件。
3. 复制 `reviewer-pr.md`。
4. 填入总 TODO、当前 TODO 和 `<PR_URL>`。
5. 明确使用 `$nm-collab-workflow-v2` 的 Reviewer 模式。
6. 首轮建议追加“只读审查，不修改项目文件”。

#### Reviewer 自动执行

- 读取 TODO、PR diff、评论和检查结果。
- 核对唯一 TODO、允许范围和禁止范围。
- 检查删除、敏感文件、测试、文档和人工验收。
- 给出唯一明确结论。

结论处理：

| 结论              | 下一步                                                 |
| ----------------- | ------------------------------------------------------ |
| `approve`         | Supervisor 记录结论并执行最终门禁                      |
| `request changes` | 复制阻塞意见，恢复同一 GrokBuild 会话进入 Fixer        |
| `comment`         | 管理员要求 Reviewer 明确是否阻塞，不得直接合并         |
| `needs-replan`    | 暂停 PR，锁切到 `replanning`，交 Planner 创建替代 TODO |

Reviewer 首轮只读时，由 Supervisor 把审查摘要追加到总 TODO 和当前 TODO。记录提交进入 PR 后，Reviewer 再快速核查新增文档 diff，避免出现“批准后又加入未经审查内容”。

### 阶段 E：GrokBuild Fixer

`request changes` 时，优先恢复当前 TODO 的原 GrokBuild 会话。进入 TUI 后使用 `/resume` 或 `/sessions` 选择会话；命令行恢复时先取得真实 UUID：

```bash
grok sessions list
grok --cwd "<PROJECT_ROOT>" --resume "<GROK_SESSION_ID>" \
  -p "<filled-fixer-prompt>"
```

本机 `grok 0.2.72` 中，`--session-id` 用于创建新的 UUID 会话，不用于恢复已有会话；恢复必须使用 `--resume`。`--continue` 只适合当前目录只有一个明确的最近会话时。参考 [xAI Headless and Scripting](https://docs.x.ai/build/cli/headless-scripting)。

Fixer 提示词必须包含 Reviewer 的原始阻塞意见，并明确：

- 只修复阻塞问题。
- 不处理非阻塞建议。
- 不实现后续 TODO。
- 修复后重新运行相关检查。
- 推送到原 PR 分支，不创建第二个 PR。

修复完成后回到阶段 D，由 Reviewer 重新审查。

### 阶段 F：合并到 dev

Reviewer `approve` 后，Supervisor 和管理员执行最终门禁：

```bash
npm run lm
npm run workflow:check
gh pr view "<PR_URL>" --json state,mergeStateStatus,reviewDecision,statusCheckRollup
```

还必须确认：

- 总 TODO 和当前 TODO 已更新。
- 敏感文件变更已由管理员确认已读。
- 人工验收已完成或有明确延期记录。
- 没有真实删除文件。
- 没有未解决阻塞评论。
- PR 目标分支是 `dev`。

合并动作由管理员执行，或在管理员明确授权后由 Supervisor 执行。合并后：

1. 更新 TODO 状态为 `merged-to-dev`。
2. 释放 `currentLock`。
3. 拉取最新 `dev`。
4. 再选择下一个 `todo-ready` TODO。

### 阶段 G：发布到稳定分支

所有目标 TODO 完成后，由管理员创建 `dev` 到 `main` 或 `master` 的发布 PR。重新检查完整 diff、自动检查、人工验收、文档和敏感变更。任何 Agent 都不得在没有管理员明确确认时自动合并稳定分支。

## 7. 暂停、恢复和终止

### 7.1 暂停前必须保存的检查点

无论暂停 Codex 还是 GrokBuild，先记录：

```text
当前角色：
总 TODO：
当前 TODO：
当前锁状态：
当前分支：
最后提交：
PR URL：
已完成检查：
未完成动作：
下一步：
Grok 会话 UUID（仅内部保存）：
```

同时运行：

```bash
git status --short --branch
git diff --stat
git log -1 --oneline
```

在总 TODO 中把锁切为 `needs-human` 或 `blocked`，写明“管理员主动暂停”、工作区状态和恢复条件。不要新增未定义的 `paused` 状态。

### 7.2 正常暂停

- Codex：发送“完成当前原子步骤后停止，不再调用工具；输出检查点”，或使用客户端停止按钮。
- GrokBuild：在模型可响应时发送“停止继续修改，输出检查点并等待”；在权限询问处拒绝下一项操作也可以阻止继续执行。
- GitHub：不要关闭仍需恢复的 PR；在 TODO 或 PR 评论中记录暂停原因。

“关闭窗口”不是完整暂停。未记录分支、锁、PR 和下一步时，不得切换到其他 TODO。

### 7.3 紧急中断

当 Agent 越界修改、运行危险命令或持续失控时：

1. Codex 使用客户端停止按钮。
2. GrokBuild 终端发送标准中断 `Ctrl+C`。
3. 不要假设中断会回滚已完成的文件和命令。
4. 立即运行 `git status` 和 `git diff`。
5. 将锁切为 `needs-human`。
6. 管理员审查后决定继续、人工修复或放弃当前 PR。

不要使用 `git reset --hard`、直接删除文件或自动清理未知改动。

### 7.4 恢复

Codex 恢复方式：

- 优先继续原对话。
- 无法继续时新建对话，粘贴完整检查点，并要求 Agent 先核查代码事实。

GrokBuild 恢复方式：

- TUI 使用 `/resume` 或 `/sessions`。
- CLI 使用 `grok --cwd "<PROJECT_ROOT>" --resume "<UUID>" -p "..."`。
- 只有确定当前目录最近会话唯一时才使用 `--continue`。

恢复提示词第一段应为：

```text
这是暂停后的恢复，不是新任务。
先读取总 TODO、当前 TODO、当前分支、PR 和 git diff，核对检查点是否仍成立。
在确认前不要写文件、提交或推送。
```

核对一致后，把锁恢复为原角色状态：`coding`、`reviewing` 或 `fixing`。

### 7.5 终止

正常结束 GrokBuild 使用 `/quit` 或 `/exit`。终止会话不等于撤销文件修改。

决定永久终止当前任务时：

1. 保存检查点和完整 diff。
2. 把 TODO 标记为阻塞、`replanned` 或管理员终止。
3. 在总 TODO 记录分支和 PR 的处理决定。
4. 关闭 PR 时说明不合并原因。
5. 文件删除仍按 `.delete-pending/` 流程处理。

## 8. 人工介入规则

### 8.1 Agent 请求权限

- 读取文件和只读 Git 命令：核对范围后批准。
- 修改允许范围内文件：核对当前 TODO 后批准。
- 修改敏感文件、推送、合并、删除或安装全局依赖：暂停并由管理员判断。
- 命令同时包含安全与危险操作时，拒绝并要求拆分命令。

### 8.2 Agent 越界

发现 Agent 修改禁止范围或实现后续 TODO：

1. 立即停止 Agent。
2. 记录越界文件和命令。
3. 不让同一 Agent自行掩盖问题。
4. 交 Reviewer 判断是 `request changes` 还是 `needs-replan`。

### 8.3 工作区出现来源不明的修改

- 不覆盖、不还原。
- 使用 `git status`、`git diff` 和执行记录确认来源。
- 无法确认时切到 `needs-human`，禁止继续自动执行。

### 8.4 会话丢失

新会话只信任仓库事实、TODO、PR 和 Git 历史，不信任管理员凭记忆复述的“应该已经完成”。先核查，再恢复。

### 8.5 测试失败

- 当前 TODO 引入的失败：Coder/Fixer 必须修复。
- 基线已有失败：记录复现命令、日志摘要和与当前 diff 的关系，由 Reviewer 判断是否阻塞。
- 没有测试框架：记录风险和人工验收，不能把“未测试”写成“测试通过”。

### 8.6 合并冲突

暂停自动合并，由 Supervisor 确认最新 `dev`。Coder/Fixer 在任务分支解决冲突并重新运行检查；Reviewer 必须重新检查冲突解决后的 diff。

## 9. Skill 使用速查

| 场景                  | Skill                   | 推荐角色            |
| --------------------- | ----------------------- | ------------------- |
| 初始化项目            | `nm-init-project-v2`    | 管理员或 Supervisor |
| 审计/同步流程基础设施 | `nm-init-project-v2`    | 管理员              |
| 拆分需求              | `nm-collab-workflow-v2` | Planner             |
| 启动 TODO             | `nm-collab-workflow-v2` | Supervisor          |
| 编码/修复             | `nm-collab-workflow-v2` | Coder/Fixer         |
| 审查 PR               | `nm-collab-workflow-v2` | Reviewer            |
| Codex 代调用 Grok     | `nm-use-grok`           | Codex               |

本手册采用管理员手动启动 GrokBuild 的方式，因此不要求 Reviewer 使用 `nm-use-grok`。只有希望 Codex 以 headless 命令委派 Grok 时才使用该 Skill。

## 10. 公开发布脱敏检查

发布教程、需求文档、PR 截图或执行日志前检查：

- [ ] 本机路径已替换为 `<PROJECT_ROOT>`。
- [ ] GitHub 用户名、私有仓库和组织名已泛化。
- [ ] API key、Cookie、OAuth 信息和环境变量值未出现。
- [ ] Grok/Codex 会话 ID 未公开。
- [ ] 用户数据、网页内容和测试样本不含个人信息。
- [ ] 截图未包含浏览器标签、终端历史或通知中的敏感信息。
- [ ] 示例分支、PR、TODO 和域名为泛化值。
- [ ] 第三方 API、模型和依赖说明符合其公开许可与服务条款。

## 11. 管理员执行检查表

### 开始整个项目

- [ ] 需求文档已确认。
- [ ] 基础设施检查通过。
- [ ] `dev` 和 GitHub 配置正常。
- [ ] Skill 在 `~/.agents/skills/` 可被两个模型发现。
- [ ] 工作区无来源不明的修改。

### 启动每个 TODO

- [ ] Planner 拆分已人工审查。
- [ ] TODO 依赖满足。
- [ ] 项目锁允许启动。
- [ ] 没有其他 active 编码 PR。
- [ ] 任务分支从最新 `dev` 创建。
- [ ] Coder 提示词已填入正确路径和边界。

### 合并每个 PR

- [ ] Reviewer 明确 `approve`。
- [ ] 阻塞评论已解决。
- [ ] 自动检查和相关测试通过。
- [ ] TODO、文档和人工验收已更新。
- [ ] 敏感文件已读。
- [ ] 没有真实删除。
- [ ] PR 目标为 `dev`。

### 中断后恢复

- [ ] 检查点完整。
- [ ] 分支、PR、TODO 和锁一致。
- [ ] 已检查未提交 diff。
- [ ] Agent 先只读核查，没有立即继续写入。
- [ ] 恢复后第一条执行记录已追加。

## 12. 版本和事实来源

- 项目流程以 `AGENTS.md` 和 `multi-agent-coding-v2.md` 为准。
- 角色提示词以 `0a-docs/prompts/` 为准。
- TODO、PR 和审查格式以 `0a-docs/agent-workflows/templates/` 为准。
- GrokBuild CLI 选项以本机 `grok --help` 和 [xAI Build 文档](https://docs.x.ai/build/overview) 为准。
- GitHub 操作以仓库实际分支保护、CI 和 [GitHub Pull Request 文档](https://docs.github.com/en/pull-requests) 为准。

流程文档和工具发生冲突时，先暂停自动执行，核查代码与 GitHub 事实，再由管理员决定是否更新流程。
