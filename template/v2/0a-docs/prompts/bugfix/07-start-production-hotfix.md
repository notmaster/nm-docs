# 提示词：启动生产 Hotfix

仅用于生产稳定分支上的紧急故障。普通开发 Bug 使用 `01-start-dev-bugfix.md`。

```text
这是生产稳定分支 Hotfix 请求。请使用 nm-collab-workflow-v2 管理 TODO、分支、PR、Reviewer 和高风险记录；如果可用，使用 nm-notify-feishu 处理状态通知。

输入：
- 项目根目录：<PROJECT_ROOT>
- 总 TODO：<TOTAL_TODO>
- 稳定分支：<main | master>
- 开发集成分支：dev
- Bug 标题：<BUG_TITLE>
- 严重程度：<P0 | P1>
- 生产影响：<PRODUCTION_IMPACT>
- 实际结果：<ACTUAL_RESULT>
- 预期结果：<EXPECTED_RESULT>
- 复现步骤和证据：<REPRODUCTION_AND_EVIDENCE>
- 当前缓解或回滚状态：<MITIGATION_OR_ROLLBACK_STATUS>
- 备份状态：<BACKUP_STATUS>
- 飞书目标：<FEISHU_TARGET 或 NONE>

本次授权范围：
1. 先只读核查稳定分支、dev、工作区、远端、项目锁、现有 Hotfix TODO/PR，以及该问题在 dev 是否已经修复或实现不同。
2. 核查完成前不要写文件、切换分支、创建分支、提交、推送或创建 PR。
3. 状态存在歧义、工作区不干净、备份缺失或已有 active 编码 PR 时，提供数字编号选项并等待我决定。
4. 确认确需生产 Hotfix 后，先创建 Hotfix TODO，再从最新稳定分支创建独立 Hotfix 分支。
5. 修复必须最小化，编写回归测试，执行针对性测试和完整门禁，创建 Draft PR 到稳定分支并等待人工验收。
6. 使用独立只读 Reviewer；记录生产风险、备份、回滚、人工验收和高风险项。
7. 本提示词授权创建 Hotfix 分支、候选提交、推送和 Draft PR，但不授权合并 main/master。
8. 稳定分支只能在我随后使用“稳定分支合并授权”模板后合并。
9. 不得直接删除文件、直接推送稳定分支、强制推送或改写共享历史。

候选版本就绪后停止并输出：Hotfix TODO、分支、候选 SHA、Draft PR、测试结果、生产验收步骤、回滚方案、dev 同步计划、风险和当前锁状态。

如果 FEISHU_TARGET 不是 NONE，可发送红色或黄色状态卡片；通知送达不构成稳定分支合并授权。
```
