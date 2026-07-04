# Bugfix 人工提示词索引

本目录中的模板供 Human Admin 直接粘贴给 Codex、Grok 或其他 Agent。使用前替换 `<...>` 占位符；不适用的可选字段填写“无”。

完整规则见 [`Bugfix 修复流程`](../../agent-workflows/bugfix-workflow.md)。

## 使用顺序

| 节点               | 模板                                                               | 用途                                        |
| ------------------ | ------------------------------------------------------------------ | ------------------------------------------- |
| 普通 Bug 首次提交  | [`01-start-dev-bugfix.md`](./01-start-dev-bugfix.md)               | 建立 TODO、任务分支、候选提交和 Draft PR    |
| 人工复测失败       | [`02-manual-test-failed.md`](./02-manual-test-failed.md)           | 在原分支和原 PR 继续修复                    |
| 人工验收通过       | [`03-accept-and-merge-dev.md`](./03-accept-and-merge-dev.md)       | 授权完整门禁、Reviewer 和合并 `dev`         |
| Agent 请求异常决策 | [`04-gate-or-scope-decision.md`](./04-gate-or-scope-decision.md)   | 对范围扩大、基线失败或替代方案作出选择      |
| 中断或切换 Agent   | [`05-resume.md`](./05-resume.md)                                   | 从 TODO、Git 和 PR 事实恢复原任务           |
| 暂停或终止方案     | [`06-pause-or-terminate.md`](./06-pause-or-terminate.md)           | 保存检查点，不删除或改写历史                |
| 生产紧急故障       | [`07-start-production-hotfix.md`](./07-start-production-hotfix.md) | 从稳定分支启动 Hotfix，但不授权合并稳定分支 |
| 稳定分支最终合并   | [`08-approve-stable-merge.md`](./08-approve-stable-merge.md)       | 单独明确授权合并 `main` / `master`          |

## 通用约束

- 模板中的 skill 采用“可用则使用”语义；Agent 缺少 skill 时按仓库规则执行并报告限制。
- 首次模板授权创建 TODO、任务分支、候选提交、推送和 Draft PR，但不授权合并。
- 复测失败继续原 TODO、原分支和原 PR。
- 合并 `dev` 和合并稳定分支使用不同授权模板。
- 飞书通知送达不构成验收或合并授权。
- Agent 返回数字选项时，Human Admin 可以直接回复选项编号；需要补充边界时使用第 4 个模板。

## 常用占位符

| 占位符               | 含义                                  |
| -------------------- | ------------------------------------- |
| `<PROJECT_ROOT>`     | 项目根目录                            |
| `<TOTAL_TODO>`       | 总 TODO 文件路径                      |
| `<TODO_ID>`          | 当前 Bugfix 任务标识；首次可填 `AUTO` |
| `<CURRENT_TODO>`     | 单 TODO 文件路径；首次可填 `AUTO`     |
| `<BUG_TITLE>`        | Bug 简短标题                          |
| `<CANDIDATE_SHA>`    | 用户实际验收的候选代码提交            |
| `<PR_URL>`           | 当前 Draft/Ready PR                   |
| `<TEST_ENVIRONMENT>` | 本地、测试环境或生产环境说明          |
| `<FEISHU_TARGET>`    | 飞书通知目标名称；不通知时填 `NONE`   |
