# 提示词：中断后恢复 Bugfix

用于继续原对话、切换 Agent 或会话丢失后的恢复。

```text
这是暂停或中断后的 Bugfix 恢复，不是新任务。

输入：
- 项目根目录：<PROJECT_ROOT>
- 总 TODO：<TOTAL_TODO>
- TODO ID：<TODO_ID>
- 当前 TODO：<CURRENT_TODO>
- 已知任务分支：<TASK_BRANCH>
- 已知 PR：<PR_URL 或 NONE>
- 最后已知候选 SHA：<CANDIDATE_SHA 或 NONE>
- 最后已知锁状态：<LOCK_STATUS>
- 最后已知人工验收状态：<ACCEPTANCE_STATUS>
- 未完成动作：<PENDING_ACTIONS>

请先只读核查仓库、TODO、Git、远端分支、PR、CI 和执行记录。核查完成前不要写文件、切换分支、提交、推送、派发 Coder/Reviewer 或合并。

恢复规则：
1. 只信任当前仓库、TODO、PR 和 Git 历史事实，不直接信任本提示词中的“最后已知”状态。
2. 如果事实一致，恢复原 TODO、原任务分支、原 PR 和原角色状态，不创建新分支或第二个 PR。
3. 如果已有未提交修改或新提交，先说明来源和与当前 TODO 的关系。
4. 如果事实不一致、存在外部合并或修改来源不明，切换 needs-human，提供 2—4 个数字编号选项，收到选择前不要继续写入。
5. 人工验收只能绑定已记录的准确代码 SHA；无法证明时视为未验收。
6. 恢复动作必须向 runs 追加新记录，不覆盖历史检查点。

只读核查后先输出：当前分支、HEAD、工作区、PR、CI、项目锁、人工验收有效性、差异和建议下一步。事实一致时再继续原流程。
```
