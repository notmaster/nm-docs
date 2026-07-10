# NM V6 恢复索引

[English](RECOVERY.md) | 简体中文

只加载与已观察失败类别对应的参考：

- Agent、lease、结果异常或 candidate 丢失：`recovery/agent.zh-CN.md`
- 受保护 ref、fetch、merge、push 或 workspace 不明确：`recovery/git.zh-CN.md`
- Release、publish、deploy、health 或 rollback 不明确：`recovery/delivery.zh-CN.md`

恢复过程始终获取新的 fencing token，读取规范状态，观察相关外部系统，附加 reconciliation evidence，并提出确定性的下一转换。不得根据 PID 消失、会话记忆或退出码推断成功。观察未知或冲突时进入 `ATTENTION_REQUIRED`，不得扩大权限范围。
