# NM V6 工作流

[English](WORKFLOW_V6.md) | 简体中文

## 权威来源

V6 只使用 `.nm/runtime/v6/state.sqlite3` 中的一份 SQLite 数据库。追加式生命周期事件是规范记录；当前状态表和人类可读投影均可重建。Reducer 是唯一状态写入者。Agent、adapter、action 进程、通知和退出码只提出或观察事实。

## 生命周期

```text
DISCOVERING -> SPEC_DRAFT -> SPEC_REVIEW -> SPEC_AWAITING_CONFIRMATION
-> SPEC_CONFIRMED -> PLANNING -> READY -> IMPLEMENTING
-> PHASE_VERIFYING -> [PHASE_AWAITING_ACCEPTANCE] -> INTEGRATING_DEV
-> INTEGRATION_VERIFYING -> RELEASE_READY -> [RELEASING]
-> RELEASE_VERIFIED -> DEPLOY_READY -> [DEPLOYING]
-> [POST_DEPLOY_VERIFYING] -> COMPLETED
```

方括号表示只有相应工作流规则允许时才能跳过的阶段：auto 下的 Phase 继续，或已确认的发布/部署 `not_applicable` 决策。所有进入 `COMPLETED` 的路径仍必须通过 `COMPLETION_GATE`。

Hotfix 使用独立的稳定分支路径，并必须把精确效果对账回 `dev`。部署失败进入回滚或请求介入；成功回滚结束于 `ROLLED_BACK`，绝不报告 `COMPLETED`。

## 门禁与证据

核心在隔离 candidate 中独立执行配置的检查。证据 receipt 绑定 Spec/配置 hash、commit、action、已保存脱敏输出 digest、artifact、环境、operation ID、evaluator 版本和时间。缺失或损坏的 blob 会使 receipt 失效。

受保护或外部变更同时需要：

1. 适用的技术前置门禁；
2. 已持久化的 staged approval 或范围精确的 auto grant。

结果门禁会重新观察受保护 ref、tag、release、artifact、deployment 和 rollback target。批准只允许 operation，不能把失败的技术门禁变成通过。

## 工作与 Git

- 普通工作从精确 fetch 的远端跟踪 `dev` 开始，使用 `feature/*`、`fix/*`、`docs/*`、`refactor/*`、`chore/*` 或 `task/*`。
- Worker 使用独立 clone，不接触权威 Git 元数据、受保护 ref 凭据或运行时数据库。
- Task candidate 经验证后合并为 Phase candidate。只有确定性 integrator 能在目标 CAS 与验证后更新 `dev`。
- AI reviewer 提议 fast-forward、squash 或 merge commit；controller 验证结果树，并只执行已授权提议。
- 清理采用证据支持的 `delete_local`、`retain` 或 `request_administrator` 决策。远端删除始终需要新 grant。

## 模式

`staged` 与 `auto` 共用转换、门禁、证据、重试、Git 策略和权限边界，只在批准来源与继续策略上不同。Auto grant 必须签名、持久化、可撤销、会过期，并绑定一个 run、Spec/配置 hash、action 集、受保护 ref 和环境。

## 中断

每个外部变更在调用前先持久化 Operation ID。发生超时、结果异常、进程丢失、controller 重启、暂停、取消或撤销后，recovery controller 观察外部状态并分类为 completed、not started、partial、failed 或 unknown。只有完成对账后才能重试；效果未知时进入 `ATTENTION_REQUIRED`。

## 运行时调度器与后台 controller

生成的 CLI 始终组合已配置的 dispatcher、持久 child launcher 和观察状态 reconciler。`run --once` 要么推进一个不需要门禁的确定性边，要么报告正在等待的精确门禁、授权、worker 结果或管理员输入。缺少 dispatcher 不是有效的等待状态。

`run --detach` 在启动外部 child 前，先把 controller 身份和状态写入规范 SQLite 事件链。`.nm/runtime/v6/controllers/` 下的文件是标有 `authoritative: false` 的可丢弃投影；删除或篡改这些文件不会改变启动、恢复或工作流状态语义。Thread 或 PID 都不是运行时真相。

`workflow:test` 会创建一次性的数据库、仓库、本地 bare remote 和隔离 workspace。它通过 scheduler、reducer、gate、Git、delivery 与 recovery controller 执行全部已配置 fake action，包括 partial/unknown 的观察与对账，以及独立验证的 rollback。它拒绝非 fake secret provider，并在任一 action 无法执行时失败。

## 项目责任

项目提供完整 JSON action 定义、验证命令、环境身份探针、命名 secret 引用，以及安全的发布、部署和回滚实现。V6 提供执行顺序、门禁、授权、证据、隔离、审计、恢复和持久通知 outbox。
