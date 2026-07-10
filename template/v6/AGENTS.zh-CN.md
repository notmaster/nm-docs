# NM V6 Agent 永久约束

`AGENTS.md` 是英文执行源；`AGENTS.zh-CN.md` 是完整的简体中文管理员镜像。如两者不一致，停止执行并同步修复。

- `.nm/runtime/v6/state.sqlite3` 中的 SQLite 数据库是唯一可变工作流权威。Markdown、JSON 投影、prompt、通知、会话和 Agent 报告都不是状态。
- 只有确定性 reducer 可以提交状态转换。Worker 只返回带版本的 proposal 或 observation，绝不写数据库。
- 硬门禁只能由核心采集或核验的证据通过。退出码为零和 Agent 自报只具有参考性。
- Worker 绝不获得受保护 ref 写权限、远端推送凭据、发布或部署凭据、受信签名能力或权威 Git 元数据。
- 普通工作从精确 fetch 的 `origin/dev` 创建允许的任务分支。稳定分支和 `dev` 均受保护。hotfix 需要明确的受信授权，并从精确 fetch 的稳定分支版本开始。
- 受保护或外部变更必须同时具备技术门禁，以及有效的 staged approval 或范围明确的 auto grant。模式或 prompt 不构成授权。
- Secret 只以命名引用存在，仅注入最小确定性 action，并从 prompt、投影、通知、证据和普通日志中排除。
- 中断的外部 operation 必须先观察并对账，之后才能重试、暂停、取消或恢复。状态未知时必须请求介入。
- Agent 不得物理删除项目文件；拟删除内容移入 `.delete-pending/` 等待管理员审阅。
- 请求验收前运行 `npm run workflow:check`、`npm run workflow:test` 和 `npm run verify`。这些检查只是证据输入，不等于管理员验收。

详细工作流、协议和恢复参考位于 `0c-workflow/`，只在当前任务或失败类别需要时加载。
