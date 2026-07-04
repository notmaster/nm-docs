# 提示词：门禁失败或范围扩大的人工决策

当 Agent 给出数字选项时可以只回复数字；需要明确授权边界时使用本模板。

```text
这是对当前 Bugfix 异常状态的人工决策，不是新任务。

输入：
- TODO ID：<TODO_ID>
- 当前 TODO：<CURRENT_TODO>
- 任务分支：<TASK_BRANCH>
- PR：<PR_URL>
- Agent 报告的阻塞摘要：<BLOCKER_SUMMARY>
- 我选择的选项编号：<OPTION_NUMBER>
- 选项原文：<OPTION_TEXT>
- 补充授权范围：<ADDITIONAL_SCOPE 或 NONE>
- 明确禁止范围：<FORBIDDEN_SCOPE 或沿用原 TODO>

请先复述我的选择及其影响，再按以下规则执行：
1. 如果选择继续扩围，先由 Planner/Supervisor 更新 TODO 的方案、允许范围、风险、测试和验收，再继续修改；不得让 Coder自行重写规划决定。
2. 如果选择 needs-replan，保留原 TODO、分支、PR 和 runs 历史，暂停当前 PR，创建替代 TODO 和映射关系。
3. 如果选择暂停，保存完整检查点，将锁切换为 needs-human，不继续写文件、提交、推送或合并。
4. 如果选择终止当前方案，保留分支、PR、diff 和执行记录；只有我明确要求时才关闭 PR，不得删除文件或改写 Git 历史。
5. 新方案若改变运行时代码，原人工验收自动失效，必须产生新候选 SHA 并重新验收。

完成本次决策动作后，输出新的状态、已更新记录、下一步以及是否需要我再次输入。
```
