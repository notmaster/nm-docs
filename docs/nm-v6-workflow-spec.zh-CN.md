---
spec_id: SPEC-NM-WORKFLOW-V6-V1
document_title: NM V6 工作流
status: review-ready
version: 1
workflow: v6
language: zh-CN
normative: false
source: nm-v6-workflow-spec.md
implementation_authorized: false
---

# NM V6 工作流规范

[English](nm-v6-workflow-spec.md) | 中文

## 1. 文档控制与权威性

本文档是 NM V6 的完整简体中文管理员评审副本。英文版是提供给实现 AI 和独立验收 AI 的规范性执行源。

英文版中的 **MUST**、**MUST NOT**、**SHOULD** 和 **MAY** 均为规范性用语。

- 英文文档是 Agent 执行源；本文件必须与其语义完整对齐。
- Requirement 和 Acceptance ID 必须稳定。删除的 ID 必须标为 `retired`，不得复用。
- 行为变化必须递增 `version` 并产生新的内容哈希。
- 生成文件、提示词、适配器、项目配置和运行记录均不得削弱本 Spec。
- 当 `status` 为 `review-ready` 且 `implementation_authorized` 为 `false` 时，Agent 可以评审本文档，但不得仅因文件存在便开始实现 V6。
- 只有管理员把状态改为 `confirmed` 并授权实现，或在实现任务中给出等价的明确指令后，才能开始实现。
- Spec 确认后，若实现与 Spec 冲突，必须硬停并申请版本化修订，不得静默选择新行为。

### 1.1 规范 Spec 哈希

规范性 `spec_hash` 是对以下字节计算的小写 SHA-256：

1. 解析英文 frontmatter，构造一个名为 `metadata` 的 mapping，其中只包含 `spec_id`、`document_title`、`version`、`workflow`、`language`、`normative` 与 `admin_mirror` 及其 parsed value。任一选定 key 缺失，或英文 frontmatter 出现这七项及 `status`、`implementation_authorized`、`content_hash` 之外的 key 时，验证失败。
2. 令 `metadata_bytes` 等于 `json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")`。
3. body 从 closing frontmatter `---` 行的 line terminator 之后第一个字符开始。把 CRLF 与 lone CR 转为 LF，移除结尾所有 LF，再追加恰好一个 LF；以不带 BOM 的 UTF-8 编码，不进行 Unicode normalization，结果命名为 `body_bytes`。
4. 对 `metadata_bytes + b"\n---body---\n" + body_bytes` 计算哈希。

`status`、`implementation_authorized`、展示用 `content_hash` 以及所有 confirmation/authorization record 均不参与哈希，因此这些字段变化不会改变规范内容身份。validator 必须自行计算哈希，不得信任复制进文档的哈希。

Spec confirmation 与 implementation authorization 是独立、不可变、可信的 control-plane record，引用 `spec_id`、`version` 和 `spec_hash`。frontmatter 状态只用于评审提示，不足以授权 runtime core。

confirmation record 包含 `confirmation_id`、`spec_id`、`version`、`spec_hash`、`decision: confirmed`、管理员身份、签发时间、nonce、authenticator ID 与 signature/MAC。implementation-authorization record 还需要指定 implementation task/scope 与 expiry。两者均使用第 12.1 节 trust boundary。

## 2. 问题与目标

NM V6 必须为长周期、可中断的 AI 辅助项目提供最小可靠闭环工作流。闭环覆盖：

1. 目标挖掘与需求澄清；
2. Spec 确认与实现规划；
3. 隔离实现；
4. 独立验证与验收；
5. 集成到 `dev`；
6. 从 `dev` 晋升到稳定分支；
7. 发布与制品分发；
8. 部署与部署后验证；
9. 失败对账与回滚。

同一套平台中立语义必须支持：

- Codex、GrokBuild 和 Claude Code；
- `staged` 与 `auto`；
- 单 Agent 与多 Agent；
- 前台与后台执行。

V6 从目标结果重新设计，不受 V5 文件、命令、运行状态或生成项目兼容性的约束。

## 3. 范围

### 3.1 范围内

- 版本化的 Goal、Requirement、Acceptance、Decision、Phase、Task、Attempt、Evidence、Gate、Operation 和批准记录。
- 事务性磁盘状态机、确定性 reducer、scheduler、门禁评估器、证据存储和恢复控制器。
- Codex、GrokBuild 和 Claude Code 的薄适配器。
- 隔离候选工作区、单/多 Agent 调度、后台监管、并发控制和过期结果拒绝。
- Git 分支保护、集成、晋升、推送策略、合并策略决策和分支清理决策。
- 项目提供的验证、构建、发布、分发、部署、健康检查和回滚动作。
- 环境确认、凭据边界、幂等、审计记录、通知 outbox 和外部状态对账。
- 静态契约检查，以及正常、异常、并发和崩溃恢复场景的可执行验收。
- V6 模板、确定性 CLI/核心、薄 Skill、简洁英文 Agent 规则和完整简体中文管理员文档。

### 3.2 非目标

- 兼容 V5 运行文件、命令或生成项目。
- 自动迁移或恢复执行中的 V5 run。
- 构建通用 Agent 操作系统或托管编排服务。
- 把每个平台的原生子 Agent 能力重新实现成一个虚构的统一 API。
- 为项目提供基础设施、命令、环境、凭据或回滚目标。项目负责提供，V6 负责验证和编排。
- 把模型判断、进程退出码或提示词指令当作确定性门禁已通过的证据。
- 穷举所有模型版本与运行模式组合。
- 把平台手册、恢复流程、历史报告或完整仓库常驻在模型上下文。
- 物理删除项目文件。除非后续管理员决议修改，仓库继续采用 `.delete-pending/` 策略。
- 在 V6 强制验收套件中使用真实生产发布、部署、通知或凭据。

## 4. 假设与已固定的设计决策

| ID | 决策 |
| --- | --- |
| `V6-DEC-001` | 项目提供具体命令动作、环境身份探针、配置和凭据引用；V6 负责执行顺序、授权、门禁、证据和恢复。 |
| `V6-DEC-002` | 参考核心使用 Python 3.11 或更新版本，并使用标准库 `sqlite3`。若增加强制运行服务或非标准库运行依赖，必须先获得管理员批准的 Spec 修订。 |
| `V6-DEC-003` | 权威 checkout 中的一份本地 SQLite 数据库是事务性运行权威。数据库内部只追加的生命周期事件是规范记录；当前状态表在同一事务更新，且必须可重建。JSON、YAML、Markdown、提示词、通知和对话均不是运行真相。 |
| `V6-DEC-004` | `main` 或 `master` 是可配置稳定分支，新项目默认 `main`；集成分支固定为 `dev`。稳定分支与 `dev` 不得相同。 |
| `V6-DEC-005` | 即使是 hotfix，AI 也不得直接在稳定分支编辑或提交。hotfix 必须从稳定分支精确 revision 创建 `hotfix/*`，通过门禁合回稳定分支，再对账回 `dev`。 |
| `V6-DEC-006` | 普通工作分支默认只在本地。远端通常只保留稳定分支与 `dev`；其他分支仅在管理员明确授权备份或评审时推送。 |
| `V6-DEC-007` | 只有在有证据支撑的清理决策后，才可自动删除本地分支。删除远端分支始终需要管理员明确授权。 |
| `V6-DEC-008` | 默认集成单元是 Phase candidate。Task candidate 可以汇总到临时 Phase 集成分支；staged 下未验收的内容不得进入 `dev`。仅当仍能强制相同 Phase 验收语义时，项目才可配置 Task 级集成。 |
| `V6-DEC-009` | 选择 `auto` 即管理员对已持久化、已展示范围的授权。所需门禁通过后，确定性控制器只可在该范围内自动合并、发布、分发、部署或回滚。 |

## 5. 规范性不变量

| ID | 不变量 |
| --- | --- |
| `V6-INV-001` | 单一事务性核心存储是唯一可变工作流真相。 |
| `V6-INV-002` | 只有确定性 reducer 可以提交工作流状态转换；Agent 和适配器只能返回提案或观察。 |
| `V6-INV-003` | 硬门禁只能由核心独立收集或复验的证据通过；Agent 自述仅供参考。 |
| `V6-INV-004` | `staged` 与 `auto` 共用一套状态图、门禁、证据规则、Git 规则、权限模型和动作适配器，仅批准来源与继续策略不同。 |
| `V6-INV-005` | `auto` 授权必须明确、持久化、可撤销，并限制到一个 run、Spec 哈希、配置哈希、动作集合、受保护 ref 集合和环境集合。 |
| `V6-INV-006` | AI Worker 不得获得受保护分支写权限、远端推送凭据、发布/部署凭据或状态库直接写权限。 |
| `V6-INV-007` | 除 hotfix 外，每个实现分支必须来自为该工作单元记录的最新已验证 `dev` revision。 |
| `V6-INV-008` | AI Worker 不得编辑、提交、reset、rebase 或 force-push `main`、`master`、`dev`。只有获授权的确定性动作在门禁通过后才能更新受保护 ref。 |
| `V6-INV-009` | 普通发布必须记录一个独立验证过的精确 source `dev` revision，并让 stable tree 与该 verified tree 完全相同；普通工作分支不得直接合入稳定分支。 |
| `V6-INV-010` | 并发工作必须使用隔离工作区、lease、fencing token、预期 revision、幂等键和串行的受保护分支集成。 |
| `V6-INV-011` | 外部操作中断后，重试前必须先与观测到的外部状态对账；仅退出码 0 不能证明进展。 |
| `V6-INV-012` | 发布与部署证据必须绑定 confirmed Spec 哈希、源码 commit、制品 digest、配置哈希、目标环境身份和 Operation ID。 |
| `V6-INV-013` | secret 只能按名称引用，并只注入确实需要它的最小确定性动作；不得进入 Agent 上下文、投影、通知或普通日志。 |
| `V6-INV-014` | 常驻指令只包含正确性与安全不变量；平台操作说明、诊断和恢复流程按需加载。 |
| `V6-INV-015` | 仍有强制 Acceptance 缺少有效证据，或必要交付阶段被静默跳过时，run 不得进入 `COMPLETED`。 |
| `V6-INV-016` | `AGENTS.md`、`CLAUDE.md`、提示词、Skill 和模型记忆只是上下文，不是强制边界；Agent 忽略它们时核心策略仍必须有效。 |

## 6. 必需架构

平台中立实现必须包含：

1. **契约验证器**：验证 Spec、项目配置、适配器配置、ID、追踪关系、动作定义、manifest 和中英文文档契约。
2. **事务性状态存储**：管理 SQLite schema、migration、只追加事件日志、当前物化状态、lease、grant、证据元数据和 outbox。
3. **Reducer**：唯一状态转换写入者；在同一事务中验证预期 run revision、转换类型、actor、授权、幂等键、前置条件、证据引用及 fencing token。
4. **Scheduler**：从 Task DAG 选择 ready 工作，并遵守依赖、write set、并发、lease 和集成约束。
5. **Agent 适配器宿主**：把统一版本化请求/结果协议映射到各 CLI，不让平台特定 flag 泄漏到核心。
6. **工作区管理器**：创建一次性隔离候选工作区，仅在策略验证后导入候选输出。
7. **门禁执行器**：独立运行配置的检查并生成证据回执，不信任 Worker 报告。
8. **Git 集成控制器**：验证 ancestry 和 candidate，接收 AI 的 merge strategy 提案，强制策略，执行获授权操作，记录集成与清理回执。
9. **交付控制器**：构建不可变制品，调用项目的 release、publish、deploy、health 与 rollback 动作。
10. **恢复控制器**：将中断的 Agent、Git、远端、发布、部署和回滚操作与观测到的外部状态对账。
11. **审计与通知 outbox**：先持久化审计事件和通知意图再投递；通知失败不得改变业务门禁。

Worker 不得调用 reducer、修改其数据库、更新受保护 Git ref、推送远端或运行带凭据的交付动作。

## 7. ID 与追踪关系

### 7.1 ID 类型

| 实体 | 格式 |
| --- | --- |
| Goal | `GOAL-<NNN>` |
| Requirement | `REQ-<NNN>` |
| Acceptance criterion | `AC-<NNN>` |
| Decision | `DEC-<NNN>` |
| Phase | `PHASE-<NNN>` |
| Task | `TASK-<NNN>` |
| Attempt | `ATTEMPT-<run-id>-<NNN>` |
| Evidence | `EVID-<run-id>-<NNN>` |
| Gate decision | `GATE-<run-id>-<NNN>` |
| External operation | `OP-<run-id>-<NNN>` |
| Approval 或 grant | `AUTH-<run-id>-<NNN>` |

文本编辑时 ID 必须保持稳定。被替代的实体保留原 ID 并记录替代者。

以上格式适用于项目 Spec。本工作流 meta-Spec 使用独立的 `V6-DEC-*`、`V6-INV-*`、`V6-REQ-*` 与 `V6-AC-*` 命名空间。

### 7.2 必需追踪关系

- 每个 confirmed Requirement 必须追踪到至少一个 Goal。
- 每个 mandatory Acceptance 必须追踪到至少一个 Requirement。
- 每个 Acceptance 必须把 `required_by_stage` 声明为 `task`、`phase`、`dev_integration`、`release`、`deploy` 或 `completion` 之一。较早 gate 只检查在该阶段到期的 mandatory criterion；`COMPLETION_GATE` 检查全部 mandatory criterion。
- 每个 Task 必须追踪到一个或多个 Acceptance，或明确标识的使能 Requirement。
- 每个通过的 gate 必须引用有效 evidence receipt。
- `COMPLETED` 要求每个 mandatory Acceptance 都有有效证据覆盖。
- 跳过 optional Task 时必须证明不会留下未覆盖的 mandatory Acceptance。
- Spec 修订产生新哈希，并使主体、假设、命令或预期结果已变化的证据失效。
- 每个 `V6-DEC-*` 与 `V6-INV-*` 都必须通过至少一个 `V6-REQ-*` 追踪到可执行 Acceptance 证据。第 27 节 coverage table 为规范性内容。

## 8. 需求挖掘与 Spec 生命周期

工作流必须支持需求挖掘，而不是假定请求已经完整。

```text
DISCOVERING
  -> SPEC_DRAFT
  -> SPEC_REVIEW
  -> SPEC_AWAITING_CONFIRMATION
  -> SPEC_CONFIRMED
  -> PLANNING
```

需求挖掘记录必须包含：

- 请求结果；
- 约束与假设；
- 开放问题和管理员决策；
- 已识别风险；
- 成功与失败条件。

confirmed 项目 Spec 必须包含：

- 不可变文档版本和内容哈希；
- 管理员确认身份和时间；
- Goal、Requirement 与 Acceptance ID；
- 每个 Acceptance 的 mandatory/optional 分类与 `required_by_stage`；
- 必要交付阶段；
- 目标环境，或明确的 `not_applicable` 决策；
- 安全约束与非目标；
- 验收动作或项目 profile 引用。

confirmed Spec 不可修改。语义变化必须产生新版本，并在恢复执行前进行影响分析。

## 9. 规范状态与持久化

### 9.1 存储规则

- 参考数据库位于权威 checkout 的 `.nm/runtime/v6/state.sqlite3`。`.nm/runtime/` 必须被 Git 忽略，并排除在 Worker 工作区之外。
- 必须启用 SQLite Write-Ahead Logging、foreign key、`synchronous=FULL` 与有界 busy timeout。启动与崩溃恢复在推进状态前必须执行 integrity check。
- 数据库中的只追加生命周期事件是规范记录。一次转换事务必须恰好写入一个逻辑事件，并原子更新物化状态、审计引用和 outbox 意图。
- 人类可读 status、issue、Task 报告和 audit export 都是一次性投影；必须声明最后 event sequence，并可从数据库重建。
- 项目 Spec 和不可变 Task 定义是版本化输入，不是可变运行真相。
- 每个 run 都有单调递增 revision；状态写入使用 compare-and-swap。
- 每个外部 Operation 都有全局唯一 idempotency key。
- 过期 revision、lease、Operation 结果或 fencing token 必须被拒绝。
- schema migration 必须版本化、事务化、只向前；执行前备份，并以 fixture 测试覆盖。
- 脱敏后的 evidence blob 必须先写到同一文件系统的临时路径，flush 并 fsync，再原子 rename 到 digest path，之后数据库事务才能提交引用它的 receipt。平台支持时还必须 fsync 目录元数据。blob 缺失或 digest 不符时 receipt 无效。未引用 blob 先 quarantine，只有超过配置 grace period 后才能清理；恢复过程不得为 orphan 虚构 receipt。

### 9.2 最小逻辑记录

schema 至少必须表达：

- run 与 revision；
- 不可变 Spec/配置快照及哈希；
- Goal、Requirement、Acceptance、Decision、Phase 与 Task；
- dependency 与声明的 write set；
- Attempt、session、process、workspace、lease 与 fencing token；
- evidence receipt 与内容寻址原始输出引用；
- gate decision 与 approval/auto grant；
- Git branch、commit、merge proposal、integration、push 与 cleanup decision；
- artifact、release、deployment、environment observation、health check 与 rollback；
- 只追加 event、reconciliation record、audit record 与 notification outbox item。

### 9.3 Run 状态

```text
DISCOVERING
SPEC_DRAFT
SPEC_REVIEW
SPEC_AWAITING_CONFIRMATION
SPEC_CONFIRMED
PLANNING
READY
IMPLEMENTING
PHASE_VERIFYING
PHASE_AWAITING_ACCEPTANCE
INTEGRATING_DEV
INTEGRATION_VERIFYING
HOTFIX_IMPLEMENTING
HOTFIX_VERIFYING
HOTFIX_INTEGRATING_STABLE
HOTFIX_STABLE_VERIFYING
HOTFIX_RECONCILING_DEV
HOTFIX_DEV_VERIFYING
RELEASE_READY
RELEASING
RELEASE_VERIFIED
DEPLOY_READY
DEPLOYING
POST_DEPLOY_VERIFYING
COMPLETED

PAUSED
ATTENTION_REQUIRED
ROLLBACK_REQUIRED
ROLLING_BACK
POST_ROLLBACK_VERIFYING
ROLLED_BACK
FAILED
CANCELLED
```

允许的成功路径转换为：

```text
DISCOVERING -> SPEC_DRAFT -> SPEC_REVIEW -> SPEC_AWAITING_CONFIRMATION
SPEC_AWAITING_CONFIRMATION -> SPEC_CONFIRMED -> PLANNING -> READY
READY -> IMPLEMENTING -> PHASE_VERIFYING
PHASE_VERIFYING -> PHASE_AWAITING_ACCEPTANCE -> INTEGRATING_DEV  # staged
PHASE_VERIFYING -> INTEGRATING_DEV                               # auto
INTEGRATING_DEV -> INTEGRATION_VERIFYING
INTEGRATION_VERIFYING -> IMPLEMENTING                            # 仍有 Phase
INTEGRATION_VERIFYING -> RELEASE_READY                           # 全部 Phase 完成
RELEASE_READY -> RELEASING -> RELEASE_VERIFIED                   # 需要 release
RELEASE_READY -> RELEASE_VERIFIED                                # release 不适用
RELEASE_VERIFIED -> DEPLOY_READY
DEPLOY_READY -> DEPLOYING -> POST_DEPLOY_VERIFYING -> COMPLETED  # 需要 deploy
DEPLOY_READY -> COMPLETED                                        # deploy 不适用

READY -> HOTFIX_IMPLEMENTING -> HOTFIX_VERIFYING                 # hotfix run
HOTFIX_VERIFYING -> HOTFIX_INTEGRATING_STABLE
HOTFIX_INTEGRATING_STABLE -> HOTFIX_STABLE_VERIFYING
HOTFIX_STABLE_VERIFYING -> HOTFIX_RECONCILING_DEV
HOTFIX_RECONCILING_DEV -> HOTFIX_DEV_VERIFYING -> RELEASE_READY
```

`SPEC_REVIEW` 可以返回 `SPEC_DRAFT`，被拒绝的确认可以返回 `SPEC_REVIEW`。Phase 检查失败时，只有通过已记录的 repair decision 才能返回 `IMPLEMENTING`。hotfix 路径要求 `run_kind: hotfix` 以及管理员可信 hotfix authorization。两个直接“不适用”边要求对应阶段 gate 记录 `not_applicable`；所有进入 `COMPLETED` 的边还必须通过 `COMPLETION_GATE`。

任何非终态运行状态都可以在隔离 active actor 并记录 resume state 后请求进入 `PAUSED` 或 `ATTENTION_REQUIRED`。release、deployment 或 rollback 等外部变更状态必须先到达已对账的安全点，才能真正进入 `PAUSED`。完成对账后只能恢复到该 validated state。部署失败遵循 `ROLLBACK_REQUIRED -> ROLLING_BACK -> POST_ROLLBACK_VERIFYING -> ROLLED_BACK`；不可恢复失败进入 `FAILED`。`COMPLETED`、`ROLLED_BACK`、`FAILED` 和 `CANCELLED` 为终态。只有 active external Operation 已取消或对账后，取消流程才能进入 `CANCELLED`。

实现必须编码版本化 transition table，每行包含 `from_state`、`event`、`guard`、`required_gate`、`required_authorization` 和 `to_state`。所有未列入表中的转换均无效。该表必须覆盖 confirmation rejection、Phase acceptance/rejection、repair、lease loss、pause request、attention/resume、cancellation、external-operation unknown 与 rollback outcome。被拒绝的 Phase 只有通过已记录的 repair decision 才能返回实现；被拒绝的 Spec 返回 review。只有 fencing 成功且没有未对账 external mutation 时，lease loss 才能让 Task 重新 ready。

`ATTENTION_REQUIRED` 必须保留已验证的恢复状态、原因、所需决策和当前外部观察；它不是成功状态。

不得绕过正常阶段顺序。只有 confirmed Spec 与对应 gate 明确记录 `not_applicable` 时才能跳过交付阶段；缺少配置并不构成跳过授权。

### 9.4 Phase 状态

```text
PLANNED -> ACTIVE -> VERIFYING
VERIFYING -> AWAITING_ACCEPTANCE -> ACCEPTED -> INTEGRATED   # staged
VERIFYING -> ACCEPTED -> INTEGRATED                          # auto
ACTIVE|VERIFYING -> BLOCKED|CANCELLED
```

Phase `INTEGRATED` 表示精确 accepted Phase candidate 已通过 `DEV_INTEGRATION_GATE`、controller 已更新受保护 ref，并且 `DEV_INTEGRATION_RESULT_GATE` 已证明 local 与 configured-remote `dev` 均等于授权结果。

### 9.5 Task 状态

```text
PLANNED -> READY -> LEASED -> RUNNING -> CANDIDATE
CANDIDATE -> VERIFYING -> VERIFIED -> INTEGRATED
RUNNING|VERIFYING -> RETRYABLE_FAILURE -> READY
RUNNING|VERIFYING -> BLOCKED|CANCELLED
READY|BLOCKED -> SKIPPED    # 仅 optional
```

Agent 不得直接产生 `VERIFIED`、`INTEGRATED` 或 `SKIPPED`。
Task `INTEGRATED` 表示 verified Task candidate 已并入 Phase candidate；它本身不表示该 Task 已进入 `dev`。

### 9.6 Attempt 状态

```text
CREATED -> DISPATCHED -> RUNNING -> COLLECTING
COLLECTING -> SUCCEEDED|FAILED|TIMED_OUT|CANCELLED|LOST
```

进程成功退出但缺少有效结构化结果时，必须进入 `FAILED` 而不是 `SUCCEEDED`。

## 10. 门禁模型

### 10.1 门禁回执

每个决策必须记录：

- gate 类型与版本；
- subject ID；
- Spec 和配置哈希；
- 适用时的 source、candidate 与 target commit；
- 适用时的制品 digest 与目标环境身份；
- 前置 decision ID 与 evidence ID；
- gate 授权受保护或外部变更时记录 staged approval 或 auto grant ID；纯技术 gate 记录 `null`；
- evaluator 身份与版本；
- 结果、原因、时间与 run revision。

### 10.2 必需门禁

只有 confirmed Spec 包含对应明确决策时，delivery gate 才能返回 `not_applicable`。此时 gate 验证该决策与阶段追踪关系，而不要求 action-specific artifact 或 environment。缺少配置绝不表示 `not_applicable`。

| Gate | 最小前置条件 |
| --- | --- |
| `SPEC_GATE` | schema 有效；ID 唯一；stage annotation 与 mandatory traceability 完整；存在 canonical Spec hash 和可信管理员 confirmation record。 |
| `PLAN_GATE` | Task DAG 有效且无环；mandatory Acceptance 已覆盖；path bound、action、dependency 与 write set 已声明。 |
| `TASK_GATE` | candidate diff 符合策略；candidate commit 已确定；独立重跑 Task 验收；没有违规状态或受保护 ref 修改。 |
| `PHASE_GATE` | mandatory Phase Task 均已验证；允许的 skip 已记录；组合 candidate 通过 Phase 验证。 |
| `DEV_INTEGRATION_GATE` | proposed target 正是 `dev`；candidate lineage 合法；预期 remote-tracking target 未移动；simulated result tree 与 merge proposal 有效；隔离 candidate 通过完整验证。 |
| `DEV_INTEGRATION_RESULT_GATE` | 观测到的 local/remote `dev` ref 等于授权结果；resulting tree 等于 verified simulated tree；push receipt 与 post-update check 通过。 |
| `HOTFIX_STABLE_GATE` | 存在可信 hotfix authorization；`hotfix/*` base 等于预期 stable；simulated stable tree、proposal、独立验证、rollback ref 与未移动 target 均通过。 |
| `HOTFIX_STABLE_RESULT_GATE` | 观测到的 local 与 configured-remote stable ref 均等于授权 CAS 结果；push receipt、resulting tree 与 post-update check 通过。 |
| `HOTFIX_RECONCILIATION_GATE` | simulated `dev` reconciliation 包含精确 hotfix effect；当前 remote `dev` 符合预期；受影响验证与 proposal 通过。 |
| `HOTFIX_RECONCILIATION_RESULT_GATE` | 观测到的 local 与 configured-remote `dev` ref 均等于授权 CAS 结果；push receipt 证明其包含精确 hotfix effect、匹配授权 tree，并通过受影响 post-update verification。 |
| `RELEASE_GATE` | `release_source_kind`、commit 与 tree 已固定：普通 release 使用 verified `dev`，hotfix release 使用 verified hotfix stable；所有 release 前到期 criterion 已覆盖；immutable artifact、stable-result tree、metadata、idempotency、observe/reconcile、rollback target 与任何必需 hotfix-reconciliation receipt 有效。 |
| `RELEASE_RESULT_GATE` | 观测到的 stable ref、tag、published release 与 artifact digest 匹配授权回执；partial/unknown effect 已对账。 |
| `DEPLOY_GATE` | 所有 `required_by_stage <= deploy` 的 mandatory criterion 已覆盖；artifact 固定；environment 已确认；credential 使用引用；preflight、idempotency、observe/reconcile 与 rollback readiness 完备。 |
| `POST_DEPLOY_GATE` | 对精确 artifact 与 environment 的 health、smoke 和项目观察均通过。 |
| `ROLLBACK_GATE` | rollback target 存在；environment 已确认；rollback 与 post-rollback verify action 可用。 |
| `POST_ROLLBACK_GATE` | 观测到的 environment 等于 rollback target，且 post-rollback verification 通过；否则 run 不能进入 `ROLLED_BACK`。 |
| `COMPLETION_GATE` | 每个 mandatory Acceptance 都有有效证据；每个 Phase 已集成；release/deployment 成功或明确不适用；没有 mandatory work 或 rollback responsibility 悬而未决。 |

Agent 报告、重试次数、通知、模式、批准或进程退出码都不能把失败门禁变成成功。批准只允许执行动作，不能替代技术门禁。

## 11. 证据模型

核心生成的 evidence receipt 至少包含：

```yaml
evidence_id:
evidence_type:
producer:
run_id:
subject_ids: []
spec_hash:
config_hash:
source_commit:
candidate_commit:
release_source_kind:
release_source_commit:
release_source_tree:
hotfix_reconciliation_gate_id:
artifact_digest:
environment_id:
environment_fingerprint:
operation_id:
attempt_id:
command_action_id:
argv_digest:
working_directory:
started_at:
finished_at:
exit_code:
result:
stdout_digest:
stderr_digest:
tool_versions: {}
redaction_version:
```

- 只有成功脱敏的输出可以持久化到内容寻址证据目录；`stdout_digest` 与 `stderr_digest` 标识实际保存的脱敏字节。
- 实现可以在流式处理时另行计算命名明确的 `raw_stream_digest`，但不得保留或导出原始字节；raw digest 不能替代 stored-content digest。
- 如果不能可靠脱敏输出，核心必须丢弃输出，把 evidence collection 标为失败，并阻止 gate 通过。
- 与当前 Spec、配置、commit、artifact、environment、action definition 或相关 toolchain fingerprint 不同的证据无效。
- Agent 输出可以记录为 `advisory_observation`，但不能单独满足确定性硬门禁。
- gate 评估必须在状态转换时重新检查证据有效性。
- evidence retention 与 redaction 策略必须在项目配置中声明。只有所有必需 binding field、stored-content digest、producer/evaluator version 与 redaction version 均存在且有效时，receipt 才完整。

## 12. `staged` 与 `auto` 模式

### 12.1 可信管理员控制平面

管理员批准必须来自 Agent、Worker workspace、adapter、project action 与 Agent context 均无法取得的 control-plane capability。调用方自己填写的 `created_by` 字符串不能作为证明。

参考本地流程采用 challenge：

1. `authorize request` 写入包含 nonce、request digest、Spec/config hash、精确 scope、expected state revision 与 expiry 的 immutable request。
2. 管理员通过独立 authenticated TTY、受 OS 保护 helper 或预先创建的 signed grant 批准该 digest；Agent 不得取得签名能力。
3. `authorize approve` 在存储 one-time 或 scoped authorization record 前，验证 signature/MAC、identity、nonce、expiry、request digest 与 current revision。
4. `authorize revoke` 创建可信 revocation record。

`auto` 的强制顺序是 `SPEC_GATE -> PLAN_GATE -> 展示精确 scope -> 可信管理员批准`。受保护变更前的纯技术 gate 不要求 authorization ID。

启动受保护或外部 Operation 时，必须原子绑定 current grant revision，并消费任何 one-time authorization。撤销会阻止尚未开始的 Operation；已开始 Operation 必须被隔离后对账到安全观测状态，不能仅因 grant 被撤销便报告 cancelled。

### 12.2 共享语义

模式不得改变：

- 状态转换或门禁顺序；
- 证据要求或验收命令；
- 重试分类；
- Git 保护或合并验证；
- secret 访问或环境确认；
- 回滚就绪性。

### 12.3 `staged`

`staged` 要求在每个配置的批准点持久化管理员批准。至少在以下动作前需要批准：

- 把已接受的 Phase candidate 集成到 `dev`；
- 把 `dev` 晋升到稳定分支、打 tag 或发布；
- 部署到每个受保护环境；
- 回滚，除非此前批准的紧急策略已经覆盖。

对应批准存在前，不得改变受保护 ref 或外部环境。

### 12.4 `auto`

通过可信 control plane 选择 `auto` 就是管理员授权事件。批准前 CLI 必须展示精确范围；verified grant 包含：

```yaml
grant_id:
run_id:
spec_hash:
config_hash:
allowed_actions: []
allowed_environments: []
allowed_protected_refs: []
created_by:
created_at:
expires_at:
revoked_at:
request_digest:
nonce:
grant_revision:
authenticator_id:
authenticator_signature:
```

该 grant：

- 仅限一个 run、Spec 哈希、配置哈希及指定 action、environment 和 protected ref；
- 在完成、取消、撤销、超时、Spec 变化或相关配置变化时失效；
- 仅在对应 gate 通过后，才允许自动 merge、promotion、release、publish、deploy 和 rollback；
- 永远不得把这些凭据或操作能力授予 AI Worker；
- 超出范围的动作必须进入 `ATTENTION_REQUIRED`，不得静默扩大权限。

切换模式是持久化状态转换。必须先取消在途动作或完成对账；仅 CLI 参数覆盖但未落库的模式无效。

## 13. 角色与权限边界

| 角色或组件 | 允许 | 禁止 |
| --- | --- | --- |
| Inspector | 读取声明的仓库路径和投影 | 写入、凭据、状态转换 |
| Planner Agent | 提议 plan、Task、context 与风险 | 运行状态转换、受保护 ref |
| Worker Agent | 修改一次性 candidate workspace，运行无特权 Task action | 状态数据库、受保护 ref、push、发布/部署凭据 |
| Review Agent | 检查 candidate，返回参考性发现 | 让确定性 gate 通过 |
| Gate executor | 在一次性 candidate 中运行无特权配置检查并返回 evidence | 受保护 ref、交付凭据、直接状态写入、任意实现编辑 |
| Git integrator | 获授权后执行已验证 proposal | 任意实现编辑、部署 |
| Release action | 构建、tag、publish 精确获授权 artifact | 通用仓库编辑、部署 |
| Deploy action | 把精确获授权 artifact 部署到精确 environment | 仓库实现编辑 |
| Rollback action | 恢复已记录 rollback target | 扩大 environment 或 artifact 范围 |
| Core reducer | 验证并记录状态转换 | 发明 requirement、command 或 credential |

Worker 隔离必须保证，即使执行原始 Git 命令也不能改变权威仓库中的受保护 ref。仅提示词指令不能满足此要求。

项目提供的 verification script 与 Worker 同样不可信。gate executor 只能暴露 action env allowlist，不得提供 delivery credential 或可写 authoritative Git metadata；默认禁止网络，只有 action 明确声明且 gate policy 允许时例外。脚本尝试 `git update-ref`、push、访问状态库或未声明凭据时必须失败，且不能改变权威状态。

## 14. Agent 适配器契约

### 14.1 必需操作

每个适配器必须暴露以下逻辑操作：

```text
probe
start
poll
cancel
collect
```

内部可以使用子进程、session 或平台原生能力。

### 14.2 能力探测

`probe` 必须以结构化数据返回：

- adapter 与 CLI 版本；
- 可用性和认证就绪状态，但不暴露凭据；
- headless 与 structured output 支持；
- resume 与 cancel 支持；
- 原生 subagent 与 background task 支持；
- 可用 sandbox 与 permission mode；
- 可探测时的真实项目指令源及相关大小限制。

缺少可选能力时核心必须优雅降级。原生子 Agent、平台 resume、hook 和后台任务只能是优化，不能成为正确性依赖。

### 14.3 请求信封

```yaml
protocol_version:
operation_id:
run_id:
attempt_id:
role:
workspace:
context_manifest:
expected_output_schema:
deadline:
fencing_token:
allowed_capabilities: []
```

信封不得包含 push、release、deployment 或生产 secret。

### 14.4 结果信封

```yaml
protocol_version:
operation_id:
attempt_id:
status:
session_id:
candidate_commit:
changed_paths: []
observations: []
requested_followups: []
usage: {}
adapter_diagnostics: {}
```

结果格式错误、缺失、过期、不匹配或不受支持时必须失败。

平台特定 command flag、permission name、event format、session behavior 和 rule discovery 必须只存在于薄适配器中。核心不得按 Codex、Grok 或 Claude 的 CLI 细节分支。

每个适配器必须有确定性 fake conformance test。安装的真实 CLI 可以由 opt-in smoke job 测试，测试时查阅当时的官方平台文档；真实 CLI smoke test 不得改变核心预期或执行高影响动作。

## 15. 调度、Agent 与并发

- 单 Agent 模式就是 worker concurrency 为 `1` 的普通 scheduler。
- 只有 dependency、声明 write set 和 workspace isolation 允许时，多 Agent 模式才可并发执行多个 ready Task。
- 默认串行执行 Phase；一个 Phase 内 ready Task 可以并发。
- 受保护分支集成始终通过 merge queue 串行执行。
- 声明 write set 重叠时必须串行，除非存在经过评审的 conflict-safe strategy。
- candidate diff 暴露的未声明重叠必须在集成前被检测。
- 每个已认领 Task 都有 lease owner、heartbeat、expiry、fencing token 和 Attempt ID。
- 即使平台报告成功，也必须拒绝过期 Worker 结果。
- 使用相同 idempotency key 的重复 dispatch 只能产生一次逻辑效果。
- candidate 记录 base 后若 `dev` 移动，集成前必须重新同步，并重跑所有受影响 gate。
- merge conflict 必须进入 `ATTENTION_REQUIRED`；不得 force-push、静默选择一侧或丢弃改动。

## 16. 前台、后台与恢复

前台和后台执行共用相同状态存储、reducer 与 gate。PID 或存活对话不是运行真相。

CLI 必须提供等价生命周期操作：

```text
run
run --detach
status
pause
resume
cancel
reconcile
```

控制器重启、进程丢失或 SIGKILL 后，恢复控制器必须：

1. 获取新 lease 与 fencing token；
2. 找到非终态 Attempt 与外部 Operation；
3. 按需检查真实平台 session、process、workspace、Git ref、remote、artifact registry、deployment 与 environment 状态；
4. 把每个 Operation 分类为 `completed`、`not_started`、`partial`、`failed` 或 `unknown`；
5. 附加 reconciliation evidence；
6. resume、幂等 retry、rollback 或进入 `ATTENTION_REQUIRED`。

核心只能加载与观测失败类型相应的恢复流程。恢复不得依赖对话记忆。

## 17. 上下文管理

每次 Agent Attempt 必须收到一个内容寻址 context manifest，其中只包含：

- 常驻安全与正确性不变量；
- 当前 Goal、Requirement 与 Acceptance 片段；
- 当前 Phase 与 Task 定义；
- 允许和禁止的路径；
- Task 所需 dependency 与 interface 事实；
- 相关持久 Decision；
- acceptance action；
- 预期 result schema；
- 可选按需资料的引用。

每个文件或片段都带 digest。manifest 记录字节数和估算 token。按需追加必须通过引用、预算检查并进入审计。

平台操作说明、恢复手册、历史报告、无关 Task 和完整仓库不得默认加载。平台入口文件可以指向同一个不变量源，但不得复制或削弱它。

## 18. 项目配置与动作契约

项目提供命令与 secret 引用；V6 负责验证、授权、执行顺序、证据和恢复。

配置文件使用版本化 JSON，使 Python 标准库核心无需额外运行依赖即可解析。以下 topology fragment 展示必需引用；它不是完整实例，省略字段不构成默认值：

```json
{
  "schema_version": "nm-v6/project-v1",
  "project": {"name": "example"},
  "git": {
    "remote": "origin",
    "stable_branch": "main",
    "integration_branch": "dev",
    "protected_branches": ["main", "dev"],
    "work_branch_prefixes": ["feature/", "fix/", "docs/", "refactor/", "chore/", "task/"],
    "hotfix_prefix": "hotfix/",
    "other_branch_push": "administrator_grant_only",
    "remote_branch_delete": "administrator_grant_only",
    "force_push": "forbidden",
    "integration_unit": "phase",
    "merge_strategies": ["fast_forward", "squash", "merge_commit"]
  },
  "scheduler": {"max_workers": 1, "lease_seconds": 120},
  "context": {"max_manifest_bytes": 131072, "max_estimated_tokens": 24000},
  "actions": {
    "task_verify": "task_verify",
    "phase_verify": "phase_verify",
    "full_verify": "full_verify",
    "build": "build",
    "release": "release",
    "publish": "publish"
  },
  "delivery": {
    "artifact_digest_result_field": "artifact_digest",
    "environments": {
      "production": {
        "expected_identity": "project-production",
        "identity_probe": "identity_probe",
        "preflight": "preflight",
        "deploy": "deploy",
        "health": "health",
        "rollback": "rollback",
        "post_rollback_verify": "post_rollback_verify"
      }
    }
  },
  "action_definitions": {},
  "secret_references": {},
  "notifications": {"routes": []}
}
```

`actions` 与 `delivery` 中的每个条目必须解析到恰好一个包含以下全部字段的 `nm-v6/action-v1` definition；不允许隐式默认值：

| 字段 | 契约 |
| --- | --- |
| `schema_version` | 字面量 `nm-v6/action-v1`。 |
| `action_id` | 与配置 key 匹配的唯一稳定 ID。 |
| `kind` | `pure`、`external_observe` 或 `external_mutation`。 |
| `argv` | 非空字符串数组；不得使用 raw shell string 或 interpolation。 |
| `cwd` | 声明的仓库相对目录。 |
| `timeout_seconds` | 正整数且有上限。 |
| `accepted_exit_codes` | 非空整数数组。 |
| `env_allowlist` | 可以从 controller environment 继承的名称。 |
| `core_injected_env` | 由核心提供的名称，需要时包含 Operation ID。 |
| `secret_refs` | 只能是命名引用，不能是值。 |
| `result_schema` | 版本化 structured-result schema ID。 |
| `idempotency` | `not_applicable`、`read_only` 或 `required`；`required` 声明精确 Operation-ID 注入方式。 |
| `observe_action_id` | `external_mutation` 必需；指向 `external_observe` action。 |
| `reconcile_action_id` | `external_mutation` 必需；指向幂等 reconciliation action。 |

release、publish、deploy 与 rollback 始终属于 `external_mutation`。build 属于 `pure`，且必须返回 artifact digest。identity probe 与 health check 属于 `external_observe`。项目可以用 script 表达复杂行为，但调用仍遵守 argv contract。

每个 action result 必须通过 `nm-v6/action-result-v1` 验证，并包含：

```json
{
  "protocol_version": "nm-v6/action-result-v1",
  "action_id": "release",
  "operation_id": "OP-example-001",
  "status": "succeeded",
  "effect_id": "provider-effect-id-or-null",
  "artifact_digest": "sha256-or-null",
  "environment_id": "environment-or-null",
  "environment_fingerprint": "fingerprint-or-null",
  "observed_state": {},
  "started_at": "RFC3339",
  "finished_at": "RFC3339",
  "diagnostics": {},
  "redactions": []
}
```

`status` 只能是 `succeeded`、`failed`、`partial` 或 `unknown`。必需 identity/digest/effect field 按 action kind 由 JSON Schema 定义；空或 malformed success result 必须失败。

核心按声明精确注入持久化 Operation ID，在记录进展前验证 result；timeout、process loss、malformed result 或 ambiguous provider response 后调用 observe/reconcile。identity probe 的 structured result 必须同时匹配 configured expected identity 与 authorization scope。

`template/v6/project.example.json` 必须是完整实例，定义每个引用 action 与 fake secret provider。它必须通过 `v6:check` 并驱动 mandatory fake end-to-end suite；以上缩略 topology 不能替代该 fixture。

配置验证必须拒绝：

- integration branch 不是字面量 `dev`，或 stable 等于 `dev`；
- protected branch 声明不完整；
- environment identity 未确认或有歧义；
- deployment 缺少 identity、health、rollback、post-rollback verification、observe 或 reconciliation action；
- 使用 credential value 而不是 reference；
- raw shell interpolation；
- release、publish、deploy 或 rollback action 缺少 idempotency、structured-result、observe 或 reconciliation metadata；
- 缺少 full verification；
- 未知 schema 或 adapter protocol version。

## 19. Git 工作流

### 19.1 受保护分支与普通工作

远端通常包含一个配置的稳定分支和 `dev`。

1. AI Worker 不得修改、提交、reset、rebase 或 force-push 稳定分支或 `dev`。
2. 普通工作前，核心在不向 Agent 提供凭据的情况下执行 `git fetch --prune <remote> dev`，解析 `refs/remotes/<remote>/dev`，记录精确 SHA 与 fetch 时间。local `dev` 必须与其相等，或由 controller 干净地 fast-forward；`dev` 分叉、含本地独有 commit、fetch 失败或 remote state 未知时必须停止。work branch 使用允许的 prefix，并从该精确 remote-tracking SHA 创建。
3. 只有确定性 Git integrator 可以在 `DEV_INTEGRATION_GATE` 和对应 staged approval 或 auto grant 后更新 `dev`。
4. 只有确定性 release controller 可以在 `RELEASE_GATE` 后把 verified `dev` 晋升到 stable。
5. 普通工作分支不得直接合入 stable。
6. stable 与 `dev` 可以在对应 gate 与授权后推送到配置的 remote；必须记录远端 ref 的精确前后值。
7. 其他分支留在本地。只有管理员针对指定 branch 与 remote 明确授权备份或评审发布时，才可推送重要分支。
8. 禁止对 protected ref force-push。其他 force-push 需要管理员明确授权，且不属于默认 V6 工作流。
9. 权威工作树 dirty、异常或含用户修改时，Git mutation 前必须硬停。
10. 集成前一刻，核心再次 fetch，并对预期 remote `dev` 执行 compare-and-swap。若其移动，candidate 必须重新同步并重跑所有受影响 gate；旧 receipt 不得授权 merge。

非受保护 remote-ref action 的 authorization 至少包含以下 scope：

```yaml
grant_id:
action: push_backup | delete_remote
remote:
ref:
expected_sha:
force: false
one_time: true
expires_at:
administrator_authorization_id:
```

controller 验证精确 ref 与 SHA，并记录 execution receipt。backup-push grant 不能授权删除；remote deletion 必须始终消费一项新的 grant。

### 19.2 Hotfix

hotfix 是唯一以 stable 为 base 的流程：

1. 管理员明确把工作分类或授权为 hotfix。
2. fetch 配置的 remote stable ref，要求 local stable 与其一致或可干净 fast-forward，记录 SHA，并在该精确 SHA 创建 `hotfix/*`。
3. 在 hotfix branch 实现，绝不直接修改 stable。
4. 独立验证，通过 `HOTFIX_STABLE_GATE`/`HOTFIX_STABLE_RESULT_GATE` 集成到 stable。
5. 通过 `HOTFIX_RECONCILIATION_GATE`/`HOTFIX_RECONCILIATION_RESULT_GATE` 把精确 hotfix effect 对账回 `dev`；冲突需要 attention，并重跑受影响验证。
6. release 与 rollback 责任关闭前保留该分支。

### 19.3 合并策略决策

work/Phase 集成到 `dev`、普通晋升到 stable、hotfix 集成或 hotfix 对账前，AI Reviewer 必须基于 branch purpose、sharing status、topology、commit quality、audit need、conflict risk 和 rollback need 提议一种允许的策略：

- **fast-forward**：target 是 ancestor，commit 已适合保留，并且不需要单独 integration boundary；
- **squash**：branch 是一个逻辑变更，中间 commit 嘈杂或可丢弃；
- **merge commit**：应保留有意义的 commit、shared history、auditability 或清晰 integration/rollback boundary。

rebase 是 source branch 准备动作，不是 protected branch merge strategy；只允许用于未发布的一次性 source branch。重写已推送或需保留的 branch 必须获得管理员明确授权。

proposal 必须记录：

- source/target ref 与 commit；
- branch purpose 与 sharing/publication status；
- topology 与 candidate tree digest；
- 选择的 strategy 与理由；
- 预期 resulting tree；
- rollback reference；
- 使用的 gate 与 authorization。

确定性 controller 负责验证并执行 proposal。strategy 无效、target 意外移动、tree 不匹配或 evidence 缺失时必须停止集成。

### 19.4 分支清理决策

集成后，AI Reviewer 必须判断 source branch 是否可以删除。确定性核心验证事实性声明，并记录下列一种清理结果：

```text
delete_local
retain
request_administrator
```

决策记录：

- source branch head 与 integration receipt；
- graph ancestry，或 squash 后的 patch/tree equivalence proof；
- review、backup、dependent work、release、rollback 与 audit responsibility；
- protected pattern 与 remote branch 状态；
- local/remote recommendation 与理由。

只有精确 branch head 已安全集成且不再承担任何责任时，才允许自动删除本地分支。该 branch 还不得存在 linked worktree、checkout、live lease、provider session 或 dependent disposable workspace。controller 在删除 ref 前先清理安全 candidate workspace，并记录 deletion receipt。

系统不得自动删除：

- `main`、`master` 或 `dev`；
- `release/*` 或 `hotfix/*`；
- 未合并或只部分集成的分支；
- 正在 review 或 acceptance 的分支；
- dependent work 需要的分支；
- 位于 release 或 rollback retention window 内的分支；
- 明确标记为 retain 或 remote backup 的分支。

即使本地删除已经安全，删除远端分支也始终需要一项新的管理员明确授权。

`request_administrator` 得到答复后会创建新的 input revision。执行任何删除前，AI Reviewer 与核心必须重新评估当前 branch 事实；旧 recommendation 永远不是 execution authorization。

## 20. 发布、部署与回滚

### 20.1 发布与分发

每次 release 都必须把 `release_source_kind` 声明为 `dev` 或 `hotfix_stable`，并指定精确 source commit 与 tree digest。普通 release 使用精确 verified `dev`；hotfix release 使用 `HOTFIX_STABLE_RESULT_GATE` 验证的 stable 结果，即使 `dev` 包含无关未发布工作也不例外。
从 `dev` 晋升到 stable、hotfix 集成和 hotfix 对账均使用第 19.3 节 merge-proposal contract。对于普通晋升，无论选择哪一种允许的 strategy，最终 stable tree 都必须与 verified `dev` tree 完全相同。

改变 stable、tag 或 publish 前：

- 所有在 `release` 前到期的 mandatory Acceptance 均有有效证据；
- repository 与 remote relationship 已知且未变化；
- integration candidate 通过 full verification；
- build 产生 immutable artifact digest；
- version、tag、changelog 与 release metadata 通过项目 action；
- rollback target 与 Operation idempotency key 已记录；
- staged approval 或 auto grant 覆盖每个 action 与 protected ref。

release receipt 绑定 source kind/commit/tree、resulting stable commit/tree、version/tag、artifact digest、action output 与 remote-ref 结果。普通 receipt 绑定 verified source `dev` commit；hotfix receipt 绑定 verified hotfix stable commit，同时引用对应 hotfix reconciliation result receipt，不得把当前 `dev` head 虚假标为 build source。

`RELEASE_GATE` 授权精确 planned effect；`RELEASE_RESULT_GATE` 独立观察它们。stable update、tag、release 或 publication 发生 timeout、partial 或 unknown 时，重试前必须先 observe 并 reconcile。source tree digest、build artifact digest、resulting stable tree、tag target、published version 与 provider effect ID 构成一条绑定链；任何不匹配都会停止交付。

### 20.2 部署

部署前：

- 项目 identity probe 识别目标 environment；
- observed identity 等于 configured 且 authorized identity；
- 精确 artifact digest 已固定；
- credential 只注入 deploy action；
- preflight 与 rollback-readiness gate 通过；
- idempotency key 存在；
- 当前 deployed version 已记录为 rollback target。

使用同一 idempotency key 重复调用不得产生重复逻辑部署。

### 20.3 部署后与回滚

`DEPLOYING` 不是成功。run 必须继续到 `POST_DEPLOY_VERIFYING`。

health 或 smoke 失败时：

- 有有效 rollback path 时进入 `ROLLBACK_REQUIRED`；
- 只有 auto grant 覆盖精确 environment 与 rollback action 时才可自动回滚；
- 否则进入 `ATTENTION_REQUIRED`。

成功回滚的终态是 `ROLLED_BACK`，不是 `COMPLETED`。回滚失败必须进入 `FAILED` 或 `ATTENTION_REQUIRED`，并保留证据与当前环境观察。

rollback success 在 `post_rollback_verify` 产生结构化证据且 `POST_ROLLBACK_GATE` 通过前只是 provisional。该验证失败时不得进入 `ROLLED_BACK`；必须保留 `POST_ROLLBACK_VERIFYING` observation，并等待 attention 或另一项获授权 recovery action。

## 21. 失败、重试、可选工作与取消

失败至少必须分类为：

- 确定性验收失败；
- Spec 冲突；
- 策略或权限违规；
- merge conflict；
- 瞬态基础设施故障；
- Agent 或 adapter protocol 失败；
- 外部 Operation 为 `partial` 或 `unknown`；
- 环境健康失败。

只有配置为可重试的类型才能自动重试。重试必须有上限与 backoff。输入、命令、环境和实现均未改变时，禁止重复相同的确定性失败。

只有同时满足以下条件才能跳过 optional work：

- confirmed Spec 将它标为 optional；
- 不会留下未覆盖的 mandatory Acceptance；
- 记录 skip decision 与原因；
- staged approval 或 auto policy 允许。

取消是一项状态转换。它必须请求取消、隔离过期 actor、对账外部 Operation 并保留证据。只杀死进程不等于取消。

## 22. 审计、通知与供应链

### 22.1 审计与通知 outbox

只追加 audit record 必须包含：

- 状态转换；
- 管理员 approval 与 auto grant；
- adapter request/result metadata；
- evidence receipt 与 gate decision；
- merge proposal 与 branch-cleanup decision；
- protected ref change 与 push；
- release、deployment、health 与 rollback Operation；
- reconciliation result；
- secret redaction event；
- notification delivery Attempt。

每条 audit row 都包含 monotonic sequence、previous-row digest、canonical event digest、event type、actor、run revision 与 timestamp。普通 API 不提供 update/delete 路径。启动、导出与验收验证都会检查 sequence continuity 与 digest chain；不匹配时进入 `ATTENTION_REQUIRED` 并阻止高影响动作。

notification 必须消费 durable outbox。投递失败独立重试，不得推进或回滚工作流业务状态。重复投递使用稳定 notification idempotency key。

### 22.2 供应链控制

- 运行与测试依赖必须声明并约束版本。
- 下载的 adapter/tool artifact 必须来自 allowlist origin，并验证 digest 或 signature。
- 核心必须在证据中记录 Python、SQLite、Git、adapter、CLI、schema 和 evaluator 版本。
- 平台允许时，run 期间必须禁用 provider CLI 自动更新；观测到版本变化时，相关证据失效。
- 生成模板文件必须被 `template/v6/manifest.json` 覆盖，install/update plan 中包含确定性 content hash。
- mandatory CI 必须在没有真实 provider、remote、notification、release 或 deployment credential 的情况下运行。

## 23. CLI、更新安全与生成项目行为

确定性 CLI 必须提供等价操作：

```text
init
update
check
status [--json]
spec confirmation request
spec confirm                 # 仅可信 control plane
plan
mode set
authorize request
authorize approve
authorize revoke
run [--detach]
pause
resume
cancel
reconcile
adapter probe
evidence show
audit export
notify-test
```

要求：

- `init` 创建或验证配置的 stable 与 `dev`，并留下 clean repository；不得在两者上直接产生 implementation commit。
- `update` 要求 Git root、clean-tree preflight、成功 fetch、从精确 remote-tracking `dev` 创建允许的新分支、在目标外 staging、应用前验证，并支持事务性 resume 或 abort。
- 不得覆盖现有用户改动与项目特有 guidance。
- `check` 验证所有 schema、traceability、state-source uniqueness、instruction、bilingual pair、manifest coverage、branch policy、adapter config、action contract 与 delivery contract。
- `status` 是 canonical state 的投影，提供 human text 与 versioned JSON。
- Skill 只是同一 CLI 的薄入口，不得通过 prose 或 script 实现第二套工作流。
- Agent 可访问的调用只能创建 authorization request；只有可信 control plane 可以 approve 或 revoke。`mode set auto` 若没有 verified grant，run 仍保持等待授权。
- Spec confirmation 使用相同边界：Agent 可以 request，只有可信 `spec confirm` 才能产生 `SPEC_GATE` 使用的 confirmation record。

仓库实现必须提供稳定验收命令：

```bash
npm run lm
npm run v6:check
npm run v6:test
npm run skill:v6:check
```

生成的 V6 项目必须提供：

```bash
npm run workflow:check
npm run workflow:test
npm run verify
```

## 24. 指令与文档布局

实现必须提供：

- 只包含常驻不变量的简洁英文仓库规则；
- 完整同步的简体中文管理员镜像；
- 本规范性实现 Spec 与管理员镜像；
- 项目配置、协议和 schema reference；
- 只由 adapter 选择的平台特定 reference；
- 按失败类型选择的 recovery reference；
- 生成的 status、audit 与 evidence view；
- Task Markdown 中不得包含可变运行状态。

平台入口文件必须指向同一个不变量源，不得声称模型指令发现机制是强制执行边界。

## 25. 实现要求

| ID | 要求 |
| --- | --- |
| `V6-REQ-001` | 实现 discovery、Spec review、canonical Spec hash、可信明确 confirmation、带 stage annotation 的 Acceptance 与 stable traceability ID。 |
| `V6-REQ-002` | 实现唯一 SQLite runtime authority，以及包含 transactional event、CAS、idempotency、migration 与 rebuildable view 的确定性 reducer。 |
| `V6-REQ-003` | 通过版本化 transition table 强制执行 Run、Phase、Task、Attempt、hotfix、rollback 与 failure state machine。 |
| `V6-REQ-004` | 实现完整的核心 evidence receipt、原子脱敏 content-addressed output、validity rule 与 evidence-backed gate decision。 |
| `V6-REQ-005` | 实现从 Spec 到 normal/hotfix integration、post-deployment、completion 与 post-rollback 的全部 mandatory pre-action/observed-result gate。 |
| `V6-REQ-006` | 通过一套 state/gate model 和 Agent 无法访问的可信 control plane，实现持久化 approval、grant 与 revocation 下的 `staged`/`auto`。 |
| `V6-REQ-007` | 实现带 capability probe 与 structured result 的版本化 Codex、Grok、Claude 薄适配器。 |
| `V6-REQ-008` | 强制 role、Worker/gate workspace、protected ref、credential、network 与 state write isolation。 |
| `V6-REQ-009` | 为单/多 Agent 与前台/后台使用实现同一个 scheduler。 |
| `V6-REQ-010` | 实现 lease、heartbeat、fencing、write-set conflict detection、stale-result rejection 与 serialized integration。 |
| `V6-REQ-011` | 为 Agent、Git、release、deployment 与 rollback Operation 实现 crash recovery 和 observed-state reconciliation。 |
| `V6-REQ-012` | 实现 content-addressed minimum context manifest、budget 与 audited on-demand loading。 |
| `V6-REQ-013` | 强制精确 remote-tracking `dev` 与 hotfix ancestry、branch prefix、protected ref、promotion、push grant、target CAS 与 dirty-tree rule。 |
| `V6-REQ-014` | 实现经过验证的 AI merge proposal 与 evidence-backed local/remote branch-cleanup decision。 |
| `V6-REQ-015` | 实现 source/artifact/tag-bound release、environment-bound deployment、结构化 observe/reconcile、post-deployment verify 与 verified rollback。 |
| `V6-REQ-016` | 实现版本化 JSON project config 与完整确定性 argv/action-result/idempotency contract。 |
| `V6-REQ-017` | 强制 environment identity、secret reference、minimum injection 与 redaction rule。 |
| `V6-REQ-018` | 实现 classified retry、optional-work skip constraint、attention 与 cancellation。 |
| `V6-REQ-019` | 实现只追加 audit record 与 durable idempotent notification outbox。 |
| `V6-REQ-020` | 实现安全 `init`、`update`、`check`、`status`、lifecycle command 与薄安装 Skill。 |
| `V6-REQ-021` | 最小化常驻模型指令，平台/恢复细节只按需加载；维护完整中英文文档对。 |
| `V6-REQ-022` | 保留 V1–V5，并拒绝自动导入或恢复 V5 可变运行状态。 |
| `V6-REQ-023` | 实现 dependency、downloaded artifact、version drift、template manifest 与 credential-free CI 供应链控制。 |
| `V6-REQ-024` | 把每个 Decision 与 Invariant 经 Requirement 追踪到证据，并为每个 mandatory `V6-AC-*` 产出有明确文件范围的 implementation traceability report。 |

## 26. 验收标准

除非后续 confirmed resolution 修改，否则每个 `V6-AC-*` 都是 mandatory。`V6-AC-044` 属于 independent-review criterion，其余均为 automated。自动化测试必须使用 disposable repository、local bare remote、isolated HOME/config、fake secret、fake Agent CLI 与 fake release/deployment/notification target。不得发送真实通知、推送真实远端或修改真实环境。

| ID | 验收 |
| --- | --- |
| `V6-AC-001` | 有效 confirmed Spec 通过；缺少 ID、stage annotation、trusted confirmation、unique ID、acyclic link 或 mandatory coverage 时失败。 |
| `V6-AC-002` | confirmed Spec 的语义变化产生新 canonical hash，并在任何后续转换前使受影响证据失效。 |
| `V6-AC-003` | 删除所有一次性投影后，能从 SQLite authority 重建相同逻辑状态。 |
| `V6-AC-004` | 拒绝 stale expected revision、重复 non-idempotent request 或 stale fencing token。 |
| `V6-AC-005` | Agent 退出码为零但缺少有效 structured result 时，不产生进展状态转换。 |
| `V6-AC-006` | Agent 声称测试通过，但核心独立重跑 action 失败时，不能满足 `TASK_GATE`。 |
| `V6-AC-007` | Agent 尝试写 runtime state 或 protected ref 时，无法影响 authority state 或 ref。 |
| `V6-AC-008` | 版本化 transition table 拒绝所有省略或 guard 不满足的转换，包括直接 `READY -> COMPLETED` 或未通过 `COMPLETION_GATE` 的完成。 |
| `V6-AC-009` | `staged` 下，对应 approval 存在前，`dev`、stable、release 和 deployment target 保持不变。 |
| `V6-AC-010` | `auto` 下，可信授权的 merge、release、deployment 在 gate 通过后无需再次询问即可执行；gate 失败或 target 超出范围时阻止动作。 |
| `V6-AC-011` | mode 选择与切换在重启后保留；Spec/config 变化、可信撤销、取消、完成或过期会使旧 auto grant 失效。 |
| `V6-AC-012` | Codex、Grok、Claude fake adapter 通过同一 protocol suite；malformed、stale、mismatched 与 unsupported response 均干净失败。 |
| `V6-AC-013` | adapter 缺少原生 subagent、resume 或 background 支持时，能通过 fallback session 以相同核心语义完成。 |
| `V6-AC-014` | 同一 fixture 的 single-worker 与 multi-worker run 产生等价 accepted tree 和 mandatory Acceptance coverage。 |
| `V6-AC-015` | 非重叠 Task 可以并发；声明或实际 write overlap 在集成前被串行化或停止。 |
| `V6-AC-016` | 两个 controller 不能同时持有同一个 lease；lease takeover 后到达的旧结果被拒绝。 |
| `V6-AC-017` | 在 state write、verification、integration、release、deployment 与 rollback 前后立即 SIGKILL，恢复后不得产生重复逻辑效果。 |
| `V6-AC-018` | detached run 能跨 controller 重启恢复，不依赖 conversation 或 PID memory；pause 会持久化、阻止新 dispatch，并且只能恢复到记录的状态。 |
| `V6-AC-019` | 普通工作位于 `main`、`master`、`dev`、invalid prefix，或 base 不是记录的 remote-tracking `dev` 时，在实现前被拒绝。 |
| `V6-AC-020` | hotfix 从 fetched stable 开始，只修改 `hotfix/*`，通过 stable 与 dev-reconciliation pre/result gate；直接编辑 stable、发生 conflict，或 configured-remote stable/dev 任一未更新到授权结果时均被拒绝。 |
| `V6-AC-021` | 只有 deterministic controller 可更新 `dev`；stable 只能接收 tree 与 verified `dev` 完全相同的结果或 gated hotfix，并产生 observed-result receipt。 |
| `V6-AC-022` | stable/`dev` push 遵循授权；普通 branch push 在可信 grant 指定 action、branch、SHA、remote 与 expiry 前被拒绝。 |
| `V6-AC-023` | fast-forward、squash、merge-commit fixture 产生 decision receipt 与预期 tree；invalid proposal 或 moved target 被拒绝。 |
| `V6-AC-024` | cleanup 删除 eligible local branch，但保留 protected、unmerged、in-review、dependent、backed-up、hotfix、release、rollback-retained、checked-out 或 active branch。 |
| `V6-AC-025` | squash cleanup 必须记录 patch/tree equivalence，不能错误声称 graph-merged；remote deletion 仍需要新管理员 grant。 |
| `V6-AC-026` | fake secret 不得出现在 prompt、projection、log、evidence output、audit export 或 notification 中。 |
| `V6-AC-027` | 配置包含 secret value、raw shell interpolation、ambiguous environment、incomplete action/result schema，或 delivery 缺少 observe/reconcile/verified rollback 时被拒绝。 |
| `V6-AC-028` | environment identity mismatch 在部署前停止，并以证据产生 `ATTENTION_REQUIRED`。 |
| `V6-AC-029` | 使用同一 idempotency key 重复部署，只产生一次 fake external deployment。 |
| `V6-AC-030` | partial 或 unknown deployment 在重试前先根据 observed state 对账。 |
| `V6-AC-031` | post-deployment failure 只有在 grant 覆盖 environment 与 action 时自动 rollback，否则等待 attention。 |
| `V6-AC-032` | rollback 只有通过 `POST_ROLLBACK_GATE` 后才能进入 `ROLLED_BACK`；rollback 或 post-rollback verify 失败时保留证据，绝不报告 `COMPLETED`。 |
| `V6-AC-033` | context manifest 在预算内，包含所需 invariant 与 Acceptance slice，并审计每次 on-demand addition。 |
| `V6-AC-034` | retryable transient failure 在预算内重试；未改变的 deterministic failure 不循环；预算耗尽时需要 attention。 |
| `V6-AC-035` | skip optional Task 会导致 mandatory Acceptance 未覆盖时，必须拒绝 skip。 |
| `V6-AC-036` | notification failure 不改变 gate/business state，持久化 outbox item，并以同一 identity 去重重试。 |
| `V6-AC-037` | `init` 产生含不同 stable 与 `dev` 的 clean repository；不得直接在两者产生 implementation commit。 |
| `V6-AC-038` | 注入 `update` 失败后保留 user file，并可在允许的 work branch 上确定性 resume 或 abort。 |
| `V6-AC-039` | `check` 拒绝 Markdown 中重复的可变运行事实，并检测缺失 manifest entry、instruction conflict 或中英文文档缺失。 |
| `V6-AC-040` | 端到端 fake scenario 覆盖 staged 单 Agent 前台、auto 多 Agent 后台、crash/resume、Worker 假成功、merge conflict、partial deployment 与 rollback。 |
| `V6-AC-041` | clean generated V6 project 通过 `workflow:check`、`workflow:test` 与 `verify`。 |
| `V6-AC-042` | V1–V5 继续存在，V5 继续标记为 experimental；尝试恢复 V5 INDEX/task-card runtime 时被拒绝并说明边界。 |
| `V6-AC-043` | 对 dependency constraint、downloaded-artifact verification、provider-version drift、manifest hash 与 credential-free CI 控制注入违规时均 fail closed。 |
| `V6-AC-044` | 自动结构检查加独立语义评审确认英文规范 Spec 和简中镜像具有相同 ID、status、decision、requirement 与 acceptance criterion。 |
| `V6-AC-045` | 生成 traceability report，把每个 `V6-REQ-*` 映射到范围内实现文件与 passing evidence，并把每个范围内改动文件映射到至少一个 Requirement。 |
| `V6-AC-046` | hash fixture 证明 LF/CRLF、trailing-LF 与 frontmatter-key-order normalization 下的精确 canonical algorithm；改变排除的控制字段不改变哈希，canonicalized normative byte 的任何变化都会改变哈希并使旧 confirmation 失效。 |
| `V6-AC-047` | Agent 创建或篡改的 approval data、replayed nonce、expanded scope、wrong revision、expired grant 与 unauthorized revoke 均被拒绝；revoke/start race 精确满足第 12.1 节原子语义。 |
| `V6-AC-048` | mandatory deploy-stage Acceptance 不阻塞 `RELEASE_GATE`，但在满足前阻塞 `COMPLETION_GATE`；缺失或无效 `required_by_stage` 导致 Spec validation 失败。 |
| `V6-AC-049` | 表驱动测试逐一删除或破坏每个 gate 的每项前置条件，包括所有 pre-action/result-gate pair；对应 gate 失败且 target 不变。 |
| `V6-AC-050` | 完整 example JSON 通过验证；强制每个 action/result field；partial/unknown release 与 publish 在幂等重试前先 observe/reconcile。 |
| `V6-AC-051` | evidence fixture 拒绝缺失 binding field 或错误 digest；只有脱敏 stored byte 可读取并计算 digest；无法脱敏的 secret output 不持久化且 evidence collection 失败。 |
| `V6-AC-052` | dirty authoritative tree、stale/divergent local `dev`、fetch 失败、invalid prefix、moved remote ref 与 result-tree mismatch 均 fail closed；重新同步会使旧 Git evidence 失效。 |
| `V6-AC-053` | normal 与 hotfix fixture 证明 release-source-kind/commit/tree -> artifact -> stable-tree -> tag -> published-version 是完整绑定链，并在每个环节拒绝替换；hotfix fixture 的 `dev` 含额外未发布 commit，必须从 verified hotfix stable 构建并引用 dev-reconciliation receipt。 |
| `V6-AC-054` | 每种 external mutation 期间发生 pause、cancel 或 grant revocation 时，会隔离新步骤并对账 active effect，且不能过早进入 `PAUSED`/`CANCELLED`。 |
| `V6-AC-055` | audit fixture 覆盖每个必需事件类型，拒绝 update/delete 或 sequence tampering，并在重启后重建等价有序 export。 |
| `V6-AC-056` | 恶意 verify action 尝试 `git update-ref`、push、state write、network 或访问 delivery secret 时失败，不影响 authority 也不泄露 credential。 |
| `V6-AC-057` | 非受保护 ref grant 强制精确 action/ref/SHA/remote、one-time、expiry 与 `force: false`；backup-push grant 不能删除，remote deletion 需要新 grant。 |
| `V6-AC-058` | 在 evidence-blob write/fsync/rename/receipt 每个边界 SIGKILL，结果只能是一项有效 receipt+blob 或 quarantined orphan；missing/corrupt blob 使 gate 无效，integrity check 能发现数据库损坏。 |
| `V6-AC-059` | 静态 traceability validation 证明每个 `V6-DEC-*` 与 `V6-INV-*` 都到达至少一个 Requirement 与可执行 Acceptance。 |
| `V6-AC-060` | branch cleanup 拒绝 linked worktree、checkout、live lease/session 与 dependent workspace；管理员输入后重新评估事实并记录新的 execution receipt。 |

对 `V6-AC-045` 而言，范围内 implementation file 是任何为 V6 新建或修改且被 Git 追踪的 source、configuration、schema、manifest、template、Skill、script、test 或 documentation，包括根级集成文件。generated runtime/evidence output、cache、vendored dependency 与 disposable test repository 不在范围内，且不得提交。翻译文件映射到 `V6-REQ-021`，同时映射其镜像行为对应的 Requirement。

## 27. Requirement-to-Acceptance 映射

### 27.1 Requirement 覆盖

| Requirement | Acceptance ID |
| --- | --- |
| `V6-REQ-001` | `V6-AC-001`、`V6-AC-002`、`V6-AC-035`、`V6-AC-046`、`V6-AC-048` |
| `V6-REQ-002` | `V6-AC-003`、`V6-AC-004`、`V6-AC-017`、`V6-AC-058` |
| `V6-REQ-003` | `V6-AC-005`、`V6-AC-008`、`V6-AC-018`、`V6-AC-054` |
| `V6-REQ-004` | `V6-AC-006`、`V6-AC-029`、`V6-AC-030`、`V6-AC-051`、`V6-AC-058` |
| `V6-REQ-005` | `V6-AC-006`、`V6-AC-009`、`V6-AC-010`、`V6-AC-031`、`V6-AC-032`、`V6-AC-048`、`V6-AC-049` |
| `V6-REQ-006` | `V6-AC-009`、`V6-AC-010`、`V6-AC-011`、`V6-AC-047`、`V6-AC-054` |
| `V6-REQ-007` | `V6-AC-012`、`V6-AC-013` |
| `V6-REQ-008` | `V6-AC-007`、`V6-AC-019`、`V6-AC-021`、`V6-AC-026`、`V6-AC-056` |
| `V6-REQ-009` | `V6-AC-014`、`V6-AC-018`、`V6-AC-040` |
| `V6-REQ-010` | `V6-AC-015`、`V6-AC-016`、`V6-AC-052` |
| `V6-REQ-011` | `V6-AC-017`、`V6-AC-018`、`V6-AC-030`、`V6-AC-050`、`V6-AC-054`、`V6-AC-058` |
| `V6-REQ-012` | `V6-AC-033` |
| `V6-REQ-013` | `V6-AC-019`、`V6-AC-020`、`V6-AC-021`、`V6-AC-022`、`V6-AC-052`、`V6-AC-057` |
| `V6-REQ-014` | `V6-AC-023`、`V6-AC-024`、`V6-AC-025`、`V6-AC-060` |
| `V6-REQ-015` | `V6-AC-028`、`V6-AC-029`、`V6-AC-030`、`V6-AC-031`、`V6-AC-032`、`V6-AC-050`、`V6-AC-053` |
| `V6-REQ-016` | `V6-AC-027`、`V6-AC-037`、`V6-AC-038`、`V6-AC-050` |
| `V6-REQ-017` | `V6-AC-026`、`V6-AC-027`、`V6-AC-028`、`V6-AC-051` |
| `V6-REQ-018` | `V6-AC-034`、`V6-AC-035`、`V6-AC-054` |
| `V6-REQ-019` | `V6-AC-036`、`V6-AC-055` |
| `V6-REQ-020` | `V6-AC-037`、`V6-AC-038`、`V6-AC-039`、`V6-AC-041` |
| `V6-REQ-021` | `V6-AC-033`、`V6-AC-039`、`V6-AC-044` |
| `V6-REQ-022` | `V6-AC-042` |
| `V6-REQ-023` | `V6-AC-043` |
| `V6-REQ-024` | `V6-AC-045`、`V6-AC-059` |

### 27.2 Decision 覆盖

| Decision | Requirement |
| --- | --- |
| `V6-DEC-001` | `V6-REQ-005`、`V6-REQ-015`、`V6-REQ-016`、`V6-REQ-017` |
| `V6-DEC-002` | `V6-REQ-002`、`V6-REQ-020`、`V6-REQ-023` |
| `V6-DEC-003` | `V6-REQ-002`、`V6-REQ-004`、`V6-REQ-019` |
| `V6-DEC-004` | `V6-REQ-013`、`V6-REQ-020` |
| `V6-DEC-005` | `V6-REQ-013`、`V6-REQ-014` |
| `V6-DEC-006` | `V6-REQ-013` |
| `V6-DEC-007` | `V6-REQ-014` |
| `V6-DEC-008` | `V6-REQ-009`、`V6-REQ-013` |
| `V6-DEC-009` | `V6-REQ-006` |

### 27.3 Invariant 覆盖

| Invariant | Requirement |
| --- | --- |
| `V6-INV-001` | `V6-REQ-002` |
| `V6-INV-002` | `V6-REQ-002`、`V6-REQ-003` |
| `V6-INV-003` | `V6-REQ-004`、`V6-REQ-005` |
| `V6-INV-004` | `V6-REQ-006` |
| `V6-INV-005` | `V6-REQ-006` |
| `V6-INV-006` | `V6-REQ-008`、`V6-REQ-017` |
| `V6-INV-007` | `V6-REQ-013` |
| `V6-INV-008` | `V6-REQ-008`、`V6-REQ-013` |
| `V6-INV-009` | `V6-REQ-013`、`V6-REQ-015` |
| `V6-INV-010` | `V6-REQ-009`、`V6-REQ-010` |
| `V6-INV-011` | `V6-REQ-011`、`V6-REQ-015` |
| `V6-INV-012` | `V6-REQ-004`、`V6-REQ-015`、`V6-REQ-017` |
| `V6-INV-013` | `V6-REQ-008`、`V6-REQ-017` |
| `V6-INV-014` | `V6-REQ-012`、`V6-REQ-021` |
| `V6-INV-015` | `V6-REQ-003`、`V6-REQ-005` |
| `V6-INV-016` | `V6-REQ-008`、`V6-REQ-021` |

## 28. 代表性场景矩阵

| 场景 | 模式 | Agent | 控制器 | 适配器覆盖 | 必需结果 |
| --- | --- | --- | --- | --- | --- |
| 从需求挖掘到 Phase 接受 | staged | 单 | 前台 | Codex fake | 在 `dev` 前停止；批准后恢复精确 candidate |
| 完整交付 | auto | 多 | 后台 | Grok fake | 安全 Task 并发、串行集成、release、deploy、health、complete |
| 能力降级 | staged | 单 | 后台 | 无 subagent/resume 的 Claude fake | 通过新 session 保持相同核心语义 |
| 不可信 Worker | 两者 | 单 | 前台 | 每种 fake adapter | 假通过、path violation、protected-ref attempt、malformed result 均不能过 gate |
| 授权攻击 | 两者 | 混合 | 前台 | fake trusted control plane | forgery、replay、scope expansion、expiry 与 revoke/start race 均 fail closed |
| 并发与过期工作 | auto | 多 | 两个 controller | 混合 fake adapter | 只有一个 lease owner；overlap 与 late result 被拒绝 |
| 崩溃矩阵 | 两者 | 混合 | 重启 | fake adapter/action | 每个 transition/external-action 边界均可幂等恢复 |
| Git 策略 | 两者 | 混合 | 前台 | fake reviewer | normal、hotfix、所有 merge strategy、push rule 与 cleanup retention 均通过 |
| 交付失败 | auto | 混合 | 后台 | fake release/deployment | partial release/publish/deploy、wrong environment、health failure 与 verified rollback outcome 均正确分类 |

mandatory CI 使用 fake adapter 与 fake delivery system。可选 real-CLI smoke job 覆盖当前支持的 Codex、GrokBuild 与 Claude Code 版本，但不得改变核心语义或外部状态。

## 29. 实现顺序与交付物

### 29.1 实现协议

实现 Agent 必须：

1. 确认本 Spec 已 confirmed 且实现已授权；
2. fetch 配置的 remote，从最新 `dev` 创建允许的工作分支；不得在 `main`、`master` 或 `dev` 实现；
3. 在实质性实现前创建 Requirement-to-file/test plan；
4. 按下方优先级实现，不得为了让早期测试通过而削弱后续 gate；
5. 在 clean disposable fixture 中运行验收并生成 traceability report；
6. 遇到 Spec 冲突时停止，不得编辑 confirmed Spec；
7. `staged` 下集成前请求管理员验收，`auto` 下只能使用精确 confirmed auto grant；
8. 集成后生成 evidence-backed branch-cleanup decision 并据此执行。

### 29.2 优先级顺序

| 优先级 | 交付物 |
| --- | --- |
| P0 | canonical Spec/traceability schema、可信 authorization control plane、SQLite authority、transition table/reducer、原子脱敏 evidence、pre/result gate、permission boundary、protected Git ref/hotfix、完整 action validator、fake adapter 与 fail-closed test。 |
| P1 | scheduler/concurrency、background lifecycle、blob/external-operation crash reconciliation、merge decision/cleanup、release/publish/deploy/verified-rollback fake action、audit/outbox 与异常路径测试。 |
| P2 | 真实薄适配器、context budget、supply-chain check、template/init/update/Skill、中英文文档、generated-project verify 与可选 real-CLI smoke test。 |

P0、P1 和 P2 只是实现顺序，不是可选范围。所有 mandatory Acceptance 通过前，不得宣布 V6 完成。

### 29.3 必需仓库产物

实现至少创建：

- `template/v6/`：包含 `manifest.json`、简洁 Agent rule、project config example、generated-project script 与中英文文档；
- `tools/nm-v6/`：包含确定性 CLI/core、schema、adapter host、可信 authorization interface、provider/fake adapter 与 test；
- `skills/nm-init-project-v6/`：薄 CLI 入口，含有效 `SKILL.md`；
- project Spec、configuration、adapter request/result、action/result、transition table、context manifest、evidence、gate、approval/grant/revocation、status JSON 与 audit export 的版本化 schema；
- unit、integration、invalid transition、concurrency、crash、delivery 与 Git-policy fixture；
- 映射 file、Requirement、Acceptance 与 evidence 的 implementation traceability report。

实现不得：

- 为了让 V6 通过而修改或删除 V1–V5；
- 把 V5 可变运行文件重新解释为 V6 真相；
- 在 mandatory CI 中要求真实 provider CLI、remote push、notification、release 或 production deployment；
- 在没有 executable evidence 或明确的 administrator-only review record 时把 Acceptance 标为通过；
- 在全部自动化证据齐备且管理员明确接受实现前，把 V6 标为推荐或 production-ready。

## 30. 完成定义

只有同时满足以下条件，V6 实现才算完成：

1. 每个 `V6-REQ-*` 均已实现，或由更新的 confirmed 管理员决议明确修改；
2. 每个 mandatory `V6-AC-*` 都有来自 clean checkout 的可复现证据；
3. 静态验证、非法转换、并发、中断恢复和代表性长周期场景均通过；
4. 关键门禁不能通过直接改文件、Agent 自述、退出码、模式、通知失败或过期结果绕过；
5. 受保护 Git ref、凭据、发布、部署和回滚权限始终在 AI Worker 能力之外；
6. 生成模板通过自身检查与验证；
7. 中英文文档解释剩余运行风险与项目责任；
8. 独立验收 Agent 审查证据，并把每个 `V6-AC-*` 报告为 `pass`、`fail` 或 `not_run`，不得把实现者自述当证据；
9. 管理员明确接受实现后，才能把 V6 标为推荐或 production-ready。
