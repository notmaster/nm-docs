# 提示词：首次提交普通 Bug

复制下面内容并替换占位符。

```text
这是一个普通开发 Bugfix，不是生产稳定分支 Hotfix。

如果当前环境可用，请使用 nm-collab-workflow-v2 管理 TODO、项目锁、任务分支、PR、Reviewer 和执行记录；使用 nm-notify-feishu 处理后续状态通知。如果 skill 不可用，读取仓库内同名流程文档继续执行，并明确报告缺失能力，不得伪造结果。

输入：
- 项目根目录：<PROJECT_ROOT>
- 总 TODO：<TOTAL_TODO>
- TODO ID：<TODO_ID 或 AUTO>
- 当前 TODO：<CURRENT_TODO 或 AUTO>
- Bug 标题：<BUG_TITLE>
- 严重程度：<P0 | P1 | P2 | P3>
- 发现环境：<TEST_ENVIRONMENT>
- 实际结果：<ACTUAL_RESULT>
- 预期结果：<EXPECTED_RESULT>
- 复现步骤：
  1. <STEP_1>
  2. <STEP_2>
- 错误信息、日志或截图：<EVIDENCE>
- 已知影响范围：<KNOWN_SCOPE>
- 飞书目标：<FEISHU_TARGET 或 NONE>

本次授权范围：
1. 先执行只读核查；核查通过前不要写文件、切换分支、提交、推送或创建 PR。
2. 核查当前分支、工作区、dev/main/远端关系、项目锁、已有 TODO、同一 Bug 分支/PR 和其他 active PR。
3. 若已经位于同一 Bug 的任务分支，继续原任务；不要新建 TODO、分支或 PR。
4. 普通 Bug 必须从最新 dev 创建 `bugfix/<TODO-ID>-<slug>` 任务分支，即使当前位于 main/master；项目有缺陷分支命名约定时沿用。
5. 如果当前状态不安全或有歧义，停止写入，列出事实，并提供 2—4 个数字编号选项；收到我的选择前不要继续。
6. 编码前创建或更新单 TODO，比较至少两种修复方案并说明最终选择、允许范围、禁止范围、测试和人工验收。
7. 修复 Bug，编写或更新能够复现问题的回归测试，只运行本轮必要的针对性测试和受影响模块测试。
8. 针对性测试通过后，提交并推送候选版本，创建或更新同一个 Draft PR 到 dev。
9. 更新 TODO 执行记录，将锁切换为 needs-human，然后停止继续修改，等待我人工测试。
10. 本提示词不授权合并 dev，也不授权合并 main/master。
11. 不得直接删除文件、覆盖未知修改、强制推送或使用破坏性 Git 命令。

人工验收是本任务的阻塞门禁。即使项目采用全自动模式，在我明确确认指定候选 SHA 通过前，也不得进入最终 Reviewer、完整合并门禁或自动合并。

完成候选版本后输出：
- TODO ID 和路径
- 任务分支
- 候选代码提交 SHA
- Draft PR URL
- 变更摘要
- 针对性测试命令和结果
- 测试环境与可直接执行的人工验收步骤
- 敏感文件、高风险、测试风险和剩余风险
- 当前锁状态与下一步
```
