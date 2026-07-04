# 提示词：人工复测失败

复制下面内容并替换占位符。继续原对话时，已知字段仍建议填写，以便绑定准确候选版本。

```text
这是当前 Bugfix 的人工复测失败反馈，不是新任务。

输入：
- 项目根目录：<PROJECT_ROOT>
- 总 TODO：<TOTAL_TODO>
- TODO ID：<TODO_ID>
- 当前 TODO：<CURRENT_TODO>
- 原任务分支：<TASK_BRANCH>
- 原 Draft PR：<PR_URL>
- 本次测试的候选 SHA：<TESTED_SHA>
- 测试环境：<TEST_ENVIRONMENT>
- 实际结果：<ACTUAL_RESULT>
- 预期结果：<EXPECTED_RESULT>
- 新复现步骤：
  1. <STEP_1>
  2. <STEP_2>
- 新错误信息、日志或截图：<EVIDENCE>

请先核对 Git、TODO 和 PR 事实，确认反馈对应原 Bug 和原候选 SHA，然后：
1. 将项目锁从 needs-human 切回 fixing，并向 runs 追加本轮失败事实，不覆盖历史。
2. 在原任务分支继续修复，恢复原 Coder/Fixer 上下文；不得创建新 TODO、分支或第二个 PR。
3. 只修复本次反馈对应的问题，不顺手增加功能。
4. 编写或更新回归测试，运行本 Bug 针对性测试和受影响模块测试。
5. 测试通过后提交并推送到原分支，更新原 Draft PR。
6. 生成新的候选 SHA，将锁切回 needs-human，然后停止修改，等待我再次测试。

如果反馈实际属于独立 Bug、改变验收标准、需要越界修改或扩大为架构调整，不要直接修改；请列出证据并提供数字编号选项，让我决定继续扩围、needs-replan、暂停或终止当前方案。

输出新的候选 SHA、修改摘要、测试结果、人工复测步骤、风险和当前锁状态。本提示词不授权合并任何分支。
```
