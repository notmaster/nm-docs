# 核心规则-V6.2

## 环境

- UTC+8, 使用简体中文(沟通、文档、代码注释)

## 开发流程（4 阶段）

### 1. 需求确认

- 需求不清晰 → 立即提问，不猜测
- 需求明确 → 进入阶段 2

### 2. 方案设计

- 提出 ≥2 个方案，对比优缺点
- 有最优方案 → 直接选择并说明理由
- 难以抉择 → 请用户决策

### 3. 任务拆分（先写文档再编码）

- 拆分为 ≤2h 的独立任务，标记依赖关系
- 创建文件：`/0b-todo/{YYYYMMDD}-{编号}-{类型}-{描述}.md`
- 类型：feat|fix|refactor|style|docs|test|perf|chore
- Front Matter（必须，YAML）必填字段：
  - taskId, type, title, profile, deps, developer, reviewer, maxRounds, timeoutMinutes
- Front Matter（可选）字段：
  - baseBranch, priority, labels, allowedPaths, forbiddenPaths, noChangePolicy, expectsNoCodeChange, reviewTimeoutMinutes
- 文件必须包含固定小节：
  - `## 需求概述`
  - `## 方案对比`
  - `## 最终选择`
  - `## 风险提示`
  - `## 任务列表`
  - `## 执行记录（机器可解析）`
- 执行记录要求：
  - 在 `## 执行记录（机器可解析）` 下包含一个 YAML 块，至少有 `runs: []`
  - 运行过程中只能追加 runs 条目，不覆盖或重写历史轮次

### 4. 任务执行（实时更新）

- 按依赖顺序执行
- 状态标记：`[ ]` 待开始 → `[>]` 进行中 → `[x]` 已完成 / `[!]` 已阻塞
- **每完成一个任务立即更新文件**（最重要的规则）：同步勾选任务列表，并保持执行记录 YAML 可解析
- 阻塞时：记录问题，评估是否需调整方案或暂停执行

## 其他

- 如果新建或编辑了 Markdown 文档，请执行以下步骤：
  1. 运行 `npm run fm` 格式化所有 Markdown 文档。
  2. 运行 `npm run lm` 检查 Markdown 文档是否存在 lint 报错。
  3. 如有报错，请修复后再次运行检查，直到无报错。

## 核心原则

1. **先问后做** - 需求不明时提问，不猜测
2. **文档先行** - 任务清单必须先于代码存在，且符合 TODO 规范
3. **实时追踪** - 状态变更立即同步到任务文件与仓库内产物
4. **禁止删除** - 任务过程中禁止删除文件（比如测试文件），任务完成后列出需要删除的文件和命令，让用户决定是否执行

---

## 本项目规则

- **主要技术栈**：
- **项目类型**：
- **编码前**：先读 PROJECT_STRUCTURE.md 文档了解目录结构
- **编码后**：必须更新 PROJECT_STRUCTURE.md 文档，然后检查项目的 README.md 文档是否需要更新
