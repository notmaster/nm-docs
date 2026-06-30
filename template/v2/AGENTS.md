# 核心规则-V7.0

## 环境

- 时区：UTC+8。
- 沟通、文档、代码注释使用简体中文。

## 基本原则

1. **先问后做**：需求不清晰时立即提问，不猜测。
2. **方案先行**：需求明确后提出至少 2 个方案，说明优缺点；存在明显最优方案时可直接选择并说明理由。
3. **文档先行**：任何编码或流程基础设施变更前，必须先创建或更新 `0b-todo/` 任务文档。
4. **实时追踪**：任务状态变化后立即同步任务文档和执行记录。
5. **禁止删除**：任务过程中禁止直接删除文件；确需删除时先移动到 `.delete-pending/` 并记录建议删除命令，等待管理员确认。

## TODO 规范

- 单个 TODO 文件路径：`0b-todo/{YYYYMMDD}-{编号}-{类型}-{描述}.md`。
- 总 TODO 文件路径：`0b-todo/000-{项目名}-总TODO.md`。
- 类型：`feat|fix|refactor|style|docs|test|perf|chore`。
- TODO 粒度以“功能闭环 + 测试闭环”为准，必须边界清晰、可审查、可验证；不再只按固定工时拆分。
- Front Matter 必填字段：
  - `taskId`, `type`, `title`, `profile`, `deps`, `developer`, `reviewer`, `maxRounds`, `timeoutMinutes`
- Front Matter 可选字段：
  - `baseBranch`, `priority`, `labels`, `allowedPaths`, `forbiddenPaths`, `noChangePolicy`, `expectsNoCodeChange`, `reviewTimeoutMinutes`
- 文件必须包含固定小节：
  - `## 需求概述`
  - `## 方案对比`
  - `## 最终选择`
  - `## 风险提示`
  - `## 任务列表`
  - `## 执行记录（机器可解析）`
- 执行记录要求：
  - 在 `## 执行记录（机器可解析）` 下包含 YAML 代码块，至少有 `runs: []`。
  - 运行过程中只能追加 `runs` 条目，不覆盖或重写历史轮次。

## 任务执行

- 按依赖顺序执行。
- 状态标记：`[ ]` 待开始，`[>]` 进行中，`[x]` 已完成，`[!]` 已阻塞。
- 每完成一个任务立即更新 TODO 文件。
- 阻塞时记录问题、影响范围、建议下一步，并判断是否需要管理员介入。

## 多模型协同流程

- 当用户要求拆分需求文档、启动监督 Agent、执行 Coder/Reviewer/Fixer、处理 PR、处理 `needs-replan` 或落地协同流程时，必须读取：
  - `0a-docs/agent-workflows/multi-agent-coding-v2.md`
- 如本机存在 `nm-collab-workflow-v2` skill，应优先使用该 skill。
- 协同开发默认使用 `{{INTEGRATION_BRANCH}}` 作为开发集成分支，任务分支从该分支创建，PR 合并回该分支。
- `{{STABLE_BRANCH}}` 是稳定分支，只能由管理员手动确认或明确要求后合并。
- 同一项目默认只允许一个 active 编码 PR；项目锁、PR 状态、敏感文件和测试风险记录在总 TODO 文件中。

## 文档检查

- 如果新建或编辑了 Markdown 文档，必须执行：
  1. `npm run fm`
  2. `npm run lm`
- 如有报错，修复后再次运行，直到无报错。

## 本项目规则

- 编码前先读 `PROJECT_STRUCTURE.md` 了解目录结构。
- 编码后必须更新 `PROJECT_STRUCTURE.md`，并检查 `README.md` 是否需要更新。
- 项目技术栈、命名约束、测试命令和发布规则由管理员在本节补充。
