# 提示词：暂停或终止当前 Bugfix 方案

本模板不会删除分支、文件或历史。

```text
请对当前 Bugfix 执行以下人工控制动作：<PAUSE | TERMINATE_PLAN>

输入：
- 项目根目录：<PROJECT_ROOT>
- 总 TODO：<TOTAL_TODO>
- TODO ID：<TODO_ID>
- 当前 TODO：<CURRENT_TODO>
- 任务分支：<TASK_BRANCH>
- PR：<PR_URL 或 NONE>
- 原因：<REASON>
- 是否关闭 PR：<YES | NO；默认 NO>

要求：
1. 完成当前不可分割的只读核查后停止，不再继续修复、测试、提交、推送或合并。
2. 记录当前角色、锁、分支、HEAD、工作区、PR、已完成测试、人工验收状态、未完成动作和下一步。
3. PAUSE 时将锁切换为 needs-human，保留 TODO、分支和 PR 供恢复。
4. TERMINATE_PLAN 时保留完整 diff、提交、PR 和 runs 历史，记录“管理员终止当前方案”及后续处理建议。
5. 只有“是否关闭 PR”为 YES 时才允许关闭 PR，并说明不合并原因。
6. 不得删除文件、删除分支、强制推送、reset --hard、覆盖未知修改或自动清理工作区。
7. 如果涉及待删除文件，继续遵守 .delete-pending/，等待管理员单独确认真实删除。

输出完整检查点和恢复时应使用的下一步提示，不执行飞书通知，除非我在本提示词末尾另行明确要求。
```
