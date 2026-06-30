# 多模型协同编程流程 V2

## 适用场景

当管理员要求拆分需求文档、启动监督 Agent、执行 Coder/Reviewer/Fixer、创建或审查 PR、处理 `needs-replan` 时，按本文档执行。普通小改动仍遵守 `AGENTS.md` 的 TODO 和实时记录规则。

## 核心原则

- 文档先行：编码前必须存在需求文档、总 TODO 文件和当前单 TODO 文件。
- 串行 PR：同一项目同一时间默认只允许一个 active 编码 PR。
- `{{INTEGRATION_BRANCH}}` 集成：任务分支从该分支创建，PR 合并回该分支。
- 稳定分支人工合并：`{{STABLE_BRANCH}}` 只由管理员手动确认或明确要求后合并。
- 代码事实优先：文档状态与代码事实冲突时，先核查代码，再记录判断。
- 规划变更受控：Coder 只记录执行事实，不直接修改规划性内容。

## 角色职责

- Planner：理解需求、提出方案、拆分 TODO、定义依赖、测试和验收标准；在 `needs-replan` 时重新规划。
- Supervisor：维护项目锁、调度 Coder/Reviewer/Fixer、创建分支和 PR、更新总 TODO 状态。
- Coder：读取总 TODO 和当前 TODO，从 `{{INTEGRATION_BRANCH}}` 创建任务分支，只完成当前 TODO，提交 PR。
- Reviewer：审查 PR 是否满足当前 TODO、测试、文档和边界要求，给出 `approve`、`request changes` 或 `comment`。
- Fixer：只修复 Reviewer 指出的阻塞问题，记录修复摘要并重新请求审查。
- Human Admin：确认敏感文件已读、处理异常、决定是否合并到稳定分支、决定是否真正删除文件。

## 文件分层

- 需求文档：记录业务需求和验收背景。
- 总 TODO：项目级控制台，记录锁、依赖、PR、风险、敏感文件、人工验收和发布检查。
- 单 TODO：任务执行档案，记录当前任务目标、范围、测试、执行摘要、PR 摘要和最终状态。
- GitHub PR：记录完整 diff、CI、完整评论、修复互动和合并记录。

## TODO 粒度

TODO 以“功能闭环 + 测试闭环”为单位，不再只按固定工时拆分。

合理 TODO 应满足：

- 不跨多个独立业务目标。
- 不同时引入多个核心架构变化。
- 变更范围可审查。
- 有明确测试或人工验收方式。
- 可以合并为一个独立 PR。

如果 Reviewer 判断 TODO 过大、过细、边界不清或无法审查，可以触发 `needs-replan`。

## 分支策略

```text
{{STABLE_BRANCH}}
  ↓ 人工确认
{{INTEGRATION_BRANCH}}
  ↓
agent/coder/TODO-xxx
  ↓
PR → {{INTEGRATION_BRANCH}}
```

执行要求：

- `{{INTEGRATION_BRANCH}}` 是开发集成分支。
- 每个 Coder 分支必须从最新 `{{INTEGRATION_BRANCH}}` 创建。
- PR 目标分支必须是 `{{INTEGRATION_BRANCH}}`。
- `{{INTEGRATION_BRANCH}}` 到 `{{STABLE_BRANCH}}` 只能由管理员确认后执行。

## 项目锁

总 TODO 必须记录 `currentLock`。建议状态：

- `idle`
- `coding`
- `reviewing`
- `fixing`
- `replanning`
- `blocked`
- `ready-to-merge-{{INTEGRATION_BRANCH}}`
- `merged-to-{{INTEGRATION_BRANCH}}`
- `needs-human`

锁字段建议：

```yaml
currentLock:
  status: idle
  todo: null
  branch: null
  pr: null
  ownerRole: null
  ownerModel: null
  acquiredAt: null
  lastHeartbeatAt: null
  timeoutMinutes: 30
  lockReason: "无 active 编码 PR"
  nextAction: "领取下一个 todo-ready 任务"
```

只有 `idle` 或上一任务已 `merged-to-{{INTEGRATION_BRANCH}}` 时，才能领取新 TODO。

## 标准流程

1. Planner 基于需求文档创建总 TODO 和单 TODO。
2. Human Admin 审查 TODO 拆分。
3. Supervisor 检查锁、分支、依赖和 GitHub 状态。
4. Supervisor 给 Coder 发当前 TODO 提示词。
5. Coder 从最新 `{{INTEGRATION_BRANCH}}` 创建任务分支，完成当前 TODO。
6. Coder 运行验证、更新执行事实、提交 PR 到 `{{INTEGRATION_BRANCH}}`。
7. Supervisor 将锁切到 `reviewing`，给 Reviewer 发审查提示词。
8. Reviewer 给出 `approve`、`request changes` 或 `comment`。
9. `request changes` 时进入 Fixer 流程。
10. `needs-replan` 时暂停当前 PR，交 Planner 重规划。
11. `approve` 后进入最终门禁检查。
12. 门禁通过后合并到 `{{INTEGRATION_BRANCH}}`，更新总 TODO 和单 TODO。
13. 管理员决定何时把 `{{INTEGRATION_BRANCH}}` 合并到稳定分支。

## Coder 执行前检查

- 总 TODO 是否存在 active lock。
- 当前 TODO 是否允许开始。
- 依赖 TODO 是否已完成。
- 依赖能力是否在代码中真实存在。
- `{{INTEGRATION_BRANCH}}` 是否最新。
- 是否存在未提交变更。
- 是否已读 `PROJECT_STRUCTURE.md`。
- 是否缺少测试框架。
- 是否涉及敏感文件或人工验收。

## Reviewer 审查清单

- PR 是否对应唯一 TODO。
- PR 是否从 `{{INTEGRATION_BRANCH}}` 创建并合并回 `{{INTEGRATION_BRANCH}}`。
- 是否只完成当前 TODO。
- 是否偷偷实现后续 TODO。
- 是否修改禁止范围。
- 是否涉及敏感文件且已记录。
- 是否删除文件。
- lint、build、测试是否通过或记录合理风险。
- 文档是否更新。
- 是否需要人工验收。
- 是否需要 `needs-replan`。
- 结论是否明确。

## 最终门禁

合并到 `{{INTEGRATION_BRANCH}}` 前必须满足：

- Reviewer 结论为 `approve`。
- PR 状态为 `ready-to-merge-{{INTEGRATION_BRANCH}}`。
- `npm run lm` 通过。
- `npm run workflow:check` 通过。
- 有 build/test 命令时必须通过。
- 当前 TODO 和总 TODO 已更新。
- 文档已更新。
- 敏感文件变更已被管理员确认已读。
- 不存在真实删除文件。
- 不存在未解决阻塞评论。

## 敏感文件

敏感文件包括：

- `.github/`
- `package.json`
- lock 文件
- 构建、部署、权限和认证配置
- 环境变量示例
- 核心入口文件
- 全局配置文件

敏感文件变更必须：

- 在 PR 标题或标签标识。
- 在单 TODO 中记录。
- 在总 TODO 敏感文件变更表中记录。
- 通知管理员确认已读。
- 未确认前不得自动合并到 `{{INTEGRATION_BRANCH}}`。

## 禁止删除

Agent 不得直接删除文件。确需删除时：

1. 移动到 `.delete-pending/`。
2. 重命名为 `_delete_原文件名`。
3. 在总 TODO 记录原路径、新路径、原因、关联 PR、验证方式和建议删除命令。
4. 等待管理员最终确认。

## needs-replan

只有 Reviewer 可以标记 `needs-replan`。触发场景包括：

- TODO 边界错误。
- 依赖关系错误。
- 验收或测试标准缺失。
- 代码事实与规划严重不一致。
- 继续修复会产生大量越界修改。
- 当前 PR 不适合继续修复。

处理要求：

- 当前 PR 暂停。
- 总 TODO 锁切到 `replanning`。
- 旧 TODO 保留并标记 `replanned`。
- Planner 创建替代 TODO 并记录映射关系。

## 工具脚本

协同流程相关脚本放在 `0c-tools/agent-workflow/`。

建议常用命令：

```bash
npm run workflow:check
npm run workflow:check:todo
npm run workflow:check:git
```

脚本只做静态兜底，不替代 Planner、Reviewer 和 Human Admin 的判断。
