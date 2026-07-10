---
workflow_version: V7
decision_revision: rev9
supersedes_decision_revision: rev8
status: p0_implementation_input
experimental: true
recommended: false
production_ready: false
decision_id_namespace: V7-DEC
next_decision_id: V7-DEC-142
language: zh-CN
normative: false
source: nm-v7-workflow-decisions.md
implementation_authorized: false
rev8_source_sha256: d3648c96e19a37d4f26f001b21922f3b4964c6a8ec5483e1717d284039c18bb2
rev8_zh_source_sha256: da5ebc441ee57904d154c3571c7b351c9d573519057e84f2e23297c657e2c1f1
rev7_source_sha256: 25560b30b604808dd4b43d2707e46b942022793ebbecfb11e7c5eac9aeea0c84
rev5_source_sha256: 8e059ef378b313a7d0eb3a0e20f863c5852e0c7286f61b9a97379483687b2d58
rev5_zh_registry_sha256: 0943e27357ea7bc7403f34cbd54d1812a4c6ec5467c4c7bc95f59dd1a53516ac
rev7_zh_111_119_registry_sha256: aedb76949bb0bd449226b0c47dc4aa150144646f88946a2f290ed3f0ae57ecbc
---

# V7 版工作流最终决议清单（决议修订 rev9）

[English（规范执行源）](nm-v7-workflow-decisions.md) | 简体中文管理员镜像

`V7`、`V6` 等大写编号只表示工作流版本；`rev9`、`rev8` 等小写编号只表示
V7 决议修订。两者使用不同命名空间。

`status: p0_implementation_input` 只表示本文可用于规划 P0，不授权实施、集成、
推送、接受、激活、发布、部署或任何其他受保护/外部影响。控制会话仍须针对下一步精确
范围提供 P0 合作式来源记录，或由未来真实 provider 产生精确认证 authority。

## 1. 问题本质与目标

- 以最低日常流程和上下文成本，让 Agent 在完整任务契约、明确授权边界和可观察
  验收标准下自主实施。
- 不规定具体实现方法，只约束授权、Git、安全、证据、验收、恢复和重要记录。
- 为简单任务保留真实快路径：P0 中围绕实施只有两次成功 CLI 调用、零阶段、零额外
  角色。稳定的 `integrate` 兼容命令仍存在并在 P0 无副作用失败关闭，但不进入默认 P0
  Agent 流程或上下文；完整三命令集成路径属于 P1。
- 把 digest、journal、租约和恢复细节封装在 CLI 内部，不进入默认 Agent 上下文。
- 让管理员能够回溯契约与候选 revision、重要决策、文件变化、验证、修复、审查和
  集成事实。
- 严格绑定被验收候选、实际集成树和目标基线。
- 本地运行时以 `P0-core` 交付，安全安装以 `P0-install` 交付；Standard 编排不进入
  Simple 默认上下文。
- 保护集成栈推迟到选定真实可信 provider 后的 `P1-core`。

## 2. 约束与假设

### 硬约束

- 保留 V1–V6；V7 独立实现，不能为了让 V7 通过而修改旧版本。
- 首个 V7 仍受仓库当前规则约束，不能接受、授权、激活或集成自身。
- `plan | supervised | auto` 仅表示意图，不构成实施、删除、保护 ref、外部、发布或
  部署授权。
- P0 `auto` 只能执行管理员精确指令及其合作式来源记录范围内的本地 action；保护或外部
  `auto` 需要真实 P1 provider grant，P0 来源记录不是该 grant。
- 同一系统账户下的文档、YAML、本地记录、租约和本地 CLI 只提供合作式约束与
  确定性检测，不是对抗性安全边界。
- P0 没有真实外部适配器、认证 authority provider、保护目标变更或控制器激活；P0
  authority record 只是合作式来源记录。`task integrate` 必须在创建 journal、租约、
  planned commit、claim 或更新 ref 前返回 `integration_unavailable`。
- P0 停留在任务聚合分支，不更新 `dev`，也不激活 V7。
- P0 恰有三个公开、项目持久化的核心 Schema：project/config、work-item envelope、
  receipt。不得增加第四个核心 Schema。Manifest、锁、租约、journal、authority 和
  CLI 结果的内部版本化记录格式不属于核心 Schema，也不得形成第二套用户可见状态机。
- 用户可见任务状态只能是 `draft | ready | in_progress | verifying | blocked |
  accepted | cancelled | superseded`。
- 不增加常驻 Runner、数据库、事件溯源系统、心跳服务、风险评分引擎或默认用户步骤。
- 普通受保护集成只以 `dev` 为目标；稳定分支集成、push、发布和部署在 P1 中分别授权。
- 模型、token、费用或精确版本不可获得时记录 `unknown`，不得推测。

### 关键假设

- 管理员或控制会话可以为外部实施指令提供 P0 合作式来源记录。本地 CLI 可校验其冻结
  字段和绑定，但不能证明 issuer 的密码学身份，也不能抵抗同账户恶意进程。
- 无可信控制面时，保护 ref 和外部影响一律失败关闭。
- V7 不承诺约束已经获准运行的恶意本地程序。P0 在 spawn 前依据可信基线 action
  catalog 拒绝 unknown/external 动作，并在 spawn 后检测限定范围内的 Git 变更。
- Simple 内联请求 4 KiB（`4096` bytes）和 V7 自有初始强制上下文 16 KiB（`16384`
  bytes）是实验默认值；可信基线可降低，后续决议可修订。
- 有远端的普通任务首次网络 fetch 需要项目常设策略加适用的 P0 合作式来源记录，或未来
  精确 provider-backed authority。Fetch 是外部读取，也会更新 remote-tracking refs，
  不能静默归类为纯本地动作。
- 记录的 rev5 source 与 registry digest 只标识历史输入。Digest 能证明文本身份，不能
  证明语义等价。

## 3. 已确认决议

### 稳定决议注册表：V7-DEC-001–110

以下语义从 rev5 原样继承。Rev6 未有效地重新分配这些 ID。若摘要与展开规则之间存在
歧义或冲突，以本清单后续 `amends` 决议为准。

#### 执行模式与 Git

- `V7-DEC-001`：`plan | supervised | auto` 只表达意图，不构成授权。
- `V7-DEC-002`：`auto` 只执行可信 grant 明确允许的动作。
- `V7-DEC-003`：每个主任务使用聚合分支；阶段分支串行合回。
- `V7-DEC-004`：子 Agent 报告只是证据索引；主 Agent 必须直接验证。
- `V7-DEC-005`：文档和工具提供合作式约束与确定性检测，不提供权限隔离。
- `V7-DEC-006`：P0 不实现真实外部适配器；本地 Git 属于核心能力。
- `V7-DEC-007`：每个主任务默认使用独立 worktree 和单写入者租约。
- `V7-DEC-008`：任务、稳定分支、远端和发布分别流转。
- `V7-DEC-009`：语义完成边界使用 `--no-ff`；基线同步使用普通 merge。
- `V7-DEC-010`：只有真实验收边界才拆分；简单任务使用 simple profile。

#### 文档、状态与记录

- `V7-DEC-011`：Spec 原文通过秘密预检后才可逐字冻结。
- `V7-DEC-012`：Front Matter 保存机器声明；Markdown 保存契约、理由和人工说明。
- `V7-DEC-013`：主 Agent 管理分支拓扑；Executor 不得自行切换、合并、rebase 或推送。
- `V7-DEC-014`：`accepted` 只表示当前候选绑定有效，不是不可逆终态。
- `V7-DEC-015`：任务记录永久保留原路径。
- `V7-DEC-016`：阶段顺序表达默认依赖；特殊依赖才填写 `depends_on`。
- `V7-DEC-017`：产品删除同时需要可信基线策略和冻结契约授权。
- `V7-DEC-018`：任务使用固定状态词汇和受控转换。
- `V7-DEC-019`：无 Git 项目通过安全检查后才能初始化。
- `V7-DEC-020`：hotfix 使用远端稳定基线和分离授权。
- `V7-DEC-021`：任务路径为 `0b-tasks/<task-id>-<slug>/`。
- `V7-DEC-022`：任务 ID 使用项目时区时间戳和短随机后缀。
- `V7-DEC-023`：阶段 Front Matter 保存当前声明；主任务进度表是派生区。
- `V7-DEC-024`：项目时区在 `AGENTS.md` 配置，精确时间使用 ISO 8601 偏移。
- `V7-DEC-025`：一次 Agent attempt 是一次实现、修复或审查 episode。
- `V7-DEC-026`：只记录影响范围、架构、风险、兼容性或验收的重要决策。
- `V7-DEC-027`：区分 origin、validation、stage baseline 及 candidate SHA。

#### 验收、恢复与通知

- `V7-DEC-028`：验收标准使用稳定 ID、可观察结果、方法和证据。
- `V7-DEC-029`：同一契约 revision 默认最多两轮普通修复。
- `V7-DEC-030`：高风险或不确定任务要求独立 Reviewer。
- `V7-DEC-031`：通知必须具有项目级窄范围 grant；失败不改变工程验收。
- `V7-DEC-032`：任务 YAML、`mode=auto` 和 Agent 自述都不是 durable grant。
- `V7-DEC-033`：任务租约保存在 Git common dir，不纳入版本控制。
- `V7-DEC-034`：持久恢复只保证提交或显式 checkpoint。
- `V7-DEC-035`：单文件/ref 可原子；多资源操作必须可重入、失败关闭并可恢复。
- `V7-DEC-036`：worktree 使用可配置的仓库外路径，不记录本机绝对路径。
- `V7-DEC-037`：按可理解单元提交；只允许未共享、未交接的阶段分支整理历史。
- `V7-DEC-038`：有集成证明且责任关闭后才清理本地资源；远端分支不自动删除。

#### Spec、模板与模型

- `V7-DEC-039`：任意 Markdown 只能导入为 `draft`。
- `V7-DEC-040`：实现、修复和审查交接必须持久化。
- `V7-DEC-041`：工具证明结构和绑定；主 Agent 与 Reviewer 负责语义正确性。
- `V7-DEC-042`：提供单一 `nm-v7` CLI，不提供常驻 Runner。
- `V7-DEC-043`：Spec 格式化生成新候选，不覆盖或静默改变原文。
- `V7-DEC-044`：`difficulty` 与 `risk` 是独立字段。
- `V7-DEC-045`：提供只读模型比较报告，不默认重复实施。
- `V7-DEC-046`：推荐 Spec 只强制最小语义核心。
- `V7-DEC-047`：阶段文件是自足局部契约，Agent 只加载相关上下文。
- `V7-DEC-048`：work-item envelope 管机器字段，Markdown 管语义章节。
- `V7-DEC-049`：根 `AGENTS.md` 保持精简，详细规则按需加载。
- `V7-DEC-050`：产品候选为 C，验收记录头为 A，集成提交为 M。
- `V7-DEC-051`：验证命令必须显式调用并绑定候选 revision。
- `V7-DEC-052`：任务类型使用固定小枚举并允许附加标签。
- `V7-DEC-053`：提供简短的 Formatter、Executor、Reviewer、Fixer 提示词。

#### 版本与项目治理

- `V7-DEC-054`：分支采用扁平命名。
- `V7-DEC-055`：未开始阶段可在契约不变时调整；历史不静默改写。
- `V7-DEC-056`：V7 保持实验状态并保留 V1–V6。
- `V7-DEC-057`：采用场景化验收，并约束 simple profile 开销。
- `V7-DEC-058`：飞书适配器留在 P1，不依赖 V5 Runner。
- `V7-DEC-059`：项目可携带固定版本 CLI，但未激活候选不能成为信任根。
- `V7-DEC-060`：非秘密项目配置位于 `AGENTS.md` Front Matter。
- `V7-DEC-061`：管理员接受记录绑定 source manifest digest，不进入被绑定源码集合。
- `V7-DEC-062`：区分源码管理、模板生成和项目安装所有权。
- `V7-DEC-063`：P0 只保留三个核心机器 Schema。
- `V7-DEC-064`：本地目标更新使用 clone-local 租约及 expected-old-SHA CAS。
- `V7-DEC-065`：C 到 A 只允许受控记录和证据变化。
- `V7-DEC-066`：完整范围保留，但实施分 P0/P1。
- `V7-DEC-067`：一个项目同时只能有一个活动控制版本。

#### 授权与候选闭环

- `V7-DEC-068`：V7 采用合作式威胁模型。
- `V7-DEC-069`：验收绑定契约 revision、验证基线、候选 revision、支持证据和 Reviewer 收据。
- `V7-DEC-070`：事实来源使用字段级 authority matrix；冲突 fail closed。
- `V7-DEC-071`：区分本地集成、远端可见、稳定化及发布/部署。
- `V7-DEC-072`：Reviewer 必须独立并绑定当前候选 revision。
- `V7-DEC-073`：状态词汇为 `draft | ready | in_progress | verifying | blocked | accepted | cancelled | superseded`。
- `V7-DEC-074`：默认删除策略为 `quarantine_unless_contract`。
- `V7-DEC-075`：未决项清零、契约完整且 revision digest 固定后才能进入 `ready`。
- `V7-DEC-076`：初始化、更新和迁移必须先 dry-run。
- `V7-DEC-077`：当前门禁使用 B 或仓库外已接受控制器。
- `V7-DEC-078`：hotfix 分类、稳定集成、push、release 和回流 `dev` 分别授权。
- `V7-DEC-079`：生成项目默认关闭通知。
- `V7-DEC-080`：难度影响模型与拆分；风险影响权限和门禁。
- `V7-DEC-081`：继续 P1、快照接受、控制器激活和集成 `dev` 是独立管理员决定。

#### 精确不变量

- `V7-DEC-082`：修复计数绑定契约 revision；新 C 不重置，目标同步不计修复。
- `V7-DEC-083`：B/C/A/M 强制祖先、父提交、tree 相等和 CAS 不变量。
- `V7-DEC-084`：`evidence_set_digest` 只摘要显式选择的支持证据。
- `V7-DEC-085`：Grant 必须绑定项目、任务、目标、契约、控制器、候选、动作和防重放数据。
- `V7-DEC-086`：未激活 P0 产物不能验收、授权、激活或集成自身。
- `V7-DEC-087`：工具不得自动破坏 dirty worktree。
- `V7-DEC-088`：持久化前进行已知秘密模式检查，但不承诺识别全部秘密。
- `V7-DEC-089`：自动删除排除越界、ignored、未跟踪、符号链接逃逸和信任根。
- `V7-DEC-090`：simple profile 具有文件、提交和暂停硬上限。
- `V7-DEC-091`：角色只加载最小上下文；工具不扫描全部任务历史。
- `V7-DEC-092`：source、template、ownership manifest 是三个不同概念。
- `V7-DEC-093`：决议使用顺序修订号和稳定 `V7-DEC-NNN`。
- `V7-DEC-094`：`ready → in_progress` 必须验证实施授权；blocked 使用 `resume_status`。
- `V7-DEC-095`：候选 revision 绑定契约 revision、B 和 C。
- `V7-DEC-096`：simple receipt 内嵌支持证据，硬上限只适用于首次成功 happy path。
- `V7-DEC-097`：Grant provider 使用 nonce 与 operation digest 支持幂等恢复。
- `V7-DEC-098`：候选 CLI 可作为产品测试，但不能成为自身信任根。
- `V7-DEC-099`：验证使用结构化 argv、受限环境、副作用分类和完整秘密处理。
- `V7-DEC-100`：P0 删除只允许 B 中已跟踪普通文件的管理员确认精确路径。
- `V7-DEC-101`：Template manifest、ownership manifest 和安全 init 基础能力属于 P0。

#### rev5 新增边界

- `V7-DEC-102`：`contract_revision_digest` 覆盖所有语义及门禁字段。
- `V7-DEC-103`：`implementation_authority_ref` 是管理员实施指令的可信 provenance。
- `V7-DEC-104`：当前候选不能改变负责审查自己的安全配置或 action catalog。
- `V7-DEC-105`：Grant 使用 `not_before/expires_at` 和固定 write-ahead journal 顺序。
- `V7-DEC-106`：租约使用 owner token、expected head 和 fencing generation。
- `V7-DEC-107`：Manifest 使用 domain-separated canonical digest；P0 实现安全 `init apply`。
- `V7-DEC-108`：Simple 短请求默认不超过 4 KiB，预加载工作流上下文不超过 16 KiB。
- `V7-DEC-109`：P0 没有真实外部适配器；fake provider 不计生产适配器。
- `V7-DEC-110`：审查新增的安全、恢复、租约、初始化及复杂度场景全部进入 P0 测试。

### rev6–rev9 新增与修订决议

- `V7-DEC-111`（`amends: V7-DEC-100, V7-DEC-107`）：Init transaction rollback/cleanup 是独立事务清理域，不属于产品删除；只允许清理 journal 证明属于当前事务且仍完全匹配的创建物。
- `V7-DEC-112`（`superseded_by: V7-DEC-119`）：工作流版本与决议修订必须分开表示；当时目标决议稿标记为 `workflow_version: V7 / decision_revision: rev6`。
- `V7-DEC-113`（`amends: V7-DEC-093`）：决议 ID 一经分配不得改义。语义补充使用新 ID 和 `amends`；完整取代使用 `superseded_by`；章节移动不得改变 ID。
- `V7-DEC-114`（`amends: V7-DEC-014, V7-DEC-018, V7-DEC-073, V7-DEC-094`）：只有 `draft | ready | in_progress | verifying` 可以进入 `blocked`；`accepted` 不直接进入 `blocked`。
- `V7-DEC-115`（`amends: V7-DEC-069, V7-DEC-082, V7-DEC-095, V7-DEC-102`）：`contract_revision_digest` 同时绑定 revision 身份、来源身份和全部语义/门禁字段。
- `V7-DEC-116`（`amends: V7-DEC-021, V7-DEC-022, V7-DEC-060, V7-DEC-061, V7-DEC-062, V7-DEC-067, V7-DEC-092, V7-DEC-107`）：Source manifest 是中性的源码 inventory，并明确进入 P0；同时恢复规范任务路径、任务 ID、唯一 project/config 位置和单一活动控制版本。
- `V7-DEC-117`（`amends: V7-DEC-022, V7-DEC-024`）：默认项目时区使用 IANA `Asia/Shanghai`；事件时间保存带实际 offset 的 ISO 8601/RFC 3339。
- `V7-DEC-118`（`amends: V7-DEC-057, V7-DEC-079, V7-DEC-086, V7-DEC-088, V7-DEC-089, V7-DEC-099, V7-DEC-100, V7-DEC-101, V7-DEC-109, V7-DEC-110`）：恢复 P0 强制验证命令、独立 Reviewer及安全测试矩阵；通知运行测试保留到 P1。
- `V7-DEC-119`（`supersedes: V7-DEC-112`）：管理员确认所附全文为决议修订 rev6；当前清单为 `workflow_version: V7 / decision_revision: rev7`，并取代决议修订 rev6。工作流版本与决议修订继续使用不同命名空间。
- `V7-DEC-120`（`supersedes: V7-DEC-119`）：本清单全文为
  `workflow_version: V7 / decision_revision: rev8` 并取代 rev7；不得静默重新分配
  V7-DEC-001–119 的既有文本与历史关系。
- `V7-DEC-121`（`amends: V7-DEC-030, V7-DEC-041, V7-DEC-057,
  V7-DEC-069, V7-DEC-072, V7-DEC-090, V7-DEC-096, V7-DEC-118`）：普通任务
  Reviewer 门禁仅在冻结契约 `review_required=true` 时生效。Simple 必须由可信基线
  判定 `review_required=false`，因此缺少 Reviewer 不阻止其 accepted。
  `task_candidate_review` 与 P0 强制的 `controller_source_technical_review` 分开；
  后者只证明技术审查，不产生 source acceptance、activation 或 integration
  authority。两者复用现有 receipt Schema 中不同的 `receipt_kind`。
- `V7-DEC-122`（`amends: V7-DEC-063, V7-DEC-073`）：三个核心 Schema 是唯一
  公开、项目持久化的契约 Schema，八个任务状态是唯一用户可见状态词汇。内部错误、
  manifest 格式、锁、租约、journal phase、authority record 和 receipt kind 不是
  额外核心 Schema，也不构成第二套任务状态机。
- `V7-DEC-123`（`amends: V7-DEC-011, V7-DEC-022, V7-DEC-039, V7-DEC-043,
  V7-DEC-046, V7-DEC-048, V7-DEC-075, V7-DEC-094, V7-DEC-103,
  V7-DEC-108, V7-DEC-116`）：可信主控制会话先在独立常设或精确 fetch authority 下
  获取 B，再根据管理员请求生成 Simple 紧凑契约、预分配有效且未使用的 task ID、计算
  digest，并签发绑定 B 的实施授权，不增加用户可见命令。`task start` 重新检查 clean
  baseline 与 B，在任何项目写入前从 B 创建允许的非保护任务分支，然后只执行内存秘密
  预检、封闭 Schema 校验、digest 计算、实施授权校验、
  持久化、冻结和受控状态转换；不得编造 AC、推断风险、消除歧义或充当 Formatter。
  缺失或不确定语义保持 `draft`，等待可信控制面澄清；只有契约完整但不满足 Simple
  条件时才升级 Standard。实施授权绑定 repository/project、task、target ref、B、
  精确 contract digest、允许的本地动作与路径范围、active controller digest、
  issuer、control session、`not_before`、`expires_at` 和 nonce。任务文件、环境变量或
  候选分支都不能签发授权。
- `V7-DEC-124`（`amends: V7-DEC-018, V7-DEC-029, V7-DEC-034,
  V7-DEC-035, V7-DEC-073, V7-DEC-094, V7-DEC-105, V7-DEC-106,
  V7-DEC-114`）：`blocked → resume_status` 不是直接赋值；resume 必须重跑目标状态的
  全部入口门禁。恢复 `in_progress` 重新验证实施授权；恢复 `verifying` 重新验证 B、
  C、HEAD、候选绑定和所需证据。普通修复轮次耗尽后进入 `blocked`。
  `revise-contract` 可冻结该 revision 并执行 `blocked → draft`；否则必须先有认证的同
  revision `additional_repair_allowance`，绑定 contract digest、当前 attempt count、新的
  有限上限、issuer 和 expiry，受控 resume 才能允许额外修复。它由候选之外的认证管理员
  控制会话签发，经独立完整门禁执行 `blocked → in_progress`，且不改写 `resume_status`。
  P1 中每次 claim 都有
  `claim_attempt_id`；已确认无效果的失败终止为
  `aborted_pre_effect`；效果未知或证据冲突终止为 `reconcile_required`；完成 reconciliation
  前禁止新保护动作。同 nonce/同 operation 可幂等重新 claim，同 nonce/不同 operation
  必须拒绝。
- `V7-DEC-125`（`amends: V7-DEC-027, V7-DEC-051, V7-DEC-064,
  V7-DEC-068, V7-DEC-076, V7-DEC-077, V7-DEC-087, V7-DEC-099,
  V7-DEC-104, V7-DEC-110`）：验证只观察当前 HEAD/index/tracked tree、当前 task 或
  aggregate ref、提供 B 的 target/tracking ref，以及显式绑定的 controller/trust-root
  refs；其他任务的无关 ref 可并发变化。这些检查只能检测，不能阻止同账户变更。安全
  策略与 action catalog 来自 B 或仓库外已接受控制器，不得来自 C。有远端的普通任务
  开始前，获授权的 `git fetch --prune origin dev` 必须成功，B 必须精确等于
  `origin/dev`，local `dev` 不得 diverge，任务分支从 B 创建。P1 紧接集成保护目标前再次
  fetch；push 若为独立动作，紧接 push 前再检查一次。目标移动会使旧 validation、
  review、acceptance 和 grant 失效。
- `V7-DEC-126`（`amends: V7-DEC-012, V7-DEC-028, V7-DEC-046,
  V7-DEC-048, V7-DEC-069, V7-DEC-095, V7-DEC-102, V7-DEC-107,
  V7-DEC-115`）：`task.md` 内只有一个机器可定位且不可变的 contract block。目标、范围、
  非目标、约束、冻结假设和全部 AC 等人工语义均位于 block 内；可变状态、进度和 receipts
  位于 block 外。摘要编码固定为：

  ```text
  frame(x) = uint64_be(byte_length(x)) || x

  contract_revision_digest =
    SHA-256(
      "nm-v7.contract-revision.v1\0" ||
      frame(canonical_gate_json) ||
      frame(contract_block_utf8)
    )
  ```

  Block 必须是无 BOM 的严格 UTF-8、LF 换行、Unicode NFC，起止标记也进入摘要；工具
  拒绝而不是静默规范化非规范输入。封闭 gate object 使用 Spec 固定的 canonical JSON：
  数组保持顺序、`null` 显式编码，拒绝重复 key、浮点值和未知门禁字段。Spec 固定 domain
  bytes、framing、digest bytes 和小写十六进制表示。
- `V7-DEC-127`（`amends: V7-DEC-093, V7-DEC-113, V7-DEC-118`）：机械检查只能
  证明 bytes、digest、ID 和声明关系，不能证明语义等价。Rev5 完整 source digest 为
  `8e059ef378b313a7d0eb3a0e20f863c5852e0c7286f61b9a97379483687b2d58`。
  提取其中 V7-DEC-001–110 的 110 条定义行，仅把粗体 ID 标记改为反引号，按原顺序
  以单个 LF 连接 UTF-8 行并追加恰好一个最终 LF，所得历史中文 registry digest 为
  `0943e27357ea7bc7403f34cbd54d1812a4c6ec5467c4c7bc95f59dd1a53516ac`，
  与 rev7 相同。对 rev7 中文 V7-DEC-111–119 定义行不做格式替换，使用相同的原序单 LF
  连接与一个最终 LF 规则，所得
  `aedb76949bb0bd449226b0c47dc4aa150144646f88946a2f290ed3f0ae57ecbc`；本中文镜像
  精确保留这些行。英文翻译、决议语义及 amendments 仍需独立语义审查；后续工具只能
  证明已审文本未漂移。
- `V7-DEC-128`（`amends: V7-DEC-032, V7-DEC-033, V7-DEC-061,
  V7-DEC-067, V7-DEC-069, V7-DEC-070, V7-DEC-077, V7-DEC-085,
  V7-DEC-086, V7-DEC-097, V7-DEC-103, V7-DEC-104`）：补全 authority matrix：Git
  对 tree、commit、ref 和拓扑事实权威；权威 task ref 上的 envelope 对当前声明和冻结
  契约权威；A 对不可变技术 evidence、普通任务 review 和 task acceptance receipts
  权威；候选之外的认证控制会话对 implementation authority 权威；P1 认证 provider 对
  integration grant/claim 权威；候选之外的认证管理员控制面对 source acceptance、
  activation、active controller digest、task recovery authority、additional repair
  allowance 和 lease takeover authority 权威。Git common dir 中的 lease/journal 只
  是恢复状态，永不构成授权。普通任务 `accepted` 可由 active controller 的确定性门禁
  产生；控制器源码接受和激活只能来自认证管理员控制面。冲突失败关闭。
- `V7-DEC-129`（`amends: V7-DEC-050, V7-DEC-065, V7-DEC-083,
  V7-DEC-128`）：候选拓扑收紧为
  `parent(A) = C`、`parents(M) = [B, A]`、`tree(M) = tree(A)`。A 是只有 C 一个 parent
  的单父提交，禁止中间提交临时改变后恢复信任根。A 在永久任务路径保存普通 task acceptance
  receipt。P1 CAS 后的 integration receipt 不写回 A 或 M；它以 create-once 方式保存到
  `$GIT_COMMON_DIR/nm-v7/receipts/integration/<operation-digest>.json`，绑定实际观察到的
  target SHA，并在 task worktree/branch 清理后仍存在。它只是 clone-local 恢复证据，不
  保证跨 clone 持久化；删除整个 clone 或关闭远端交付责任前，认证 provider 或外部审计
  存储必须保留 finalized receipt。Target ref 与 M 拓扑仍是集成事实的权威；receipt 从不
  授权或覆盖 Git。
- `V7-DEC-130`（`amends: V7-DEC-047, V7-DEC-049, V7-DEC-057,
  V7-DEC-090, V7-DEC-091, V7-DEC-096, V7-DEC-108, V7-DEC-110`）：16 KiB 只
  验收 `nm-v7 context render` 输出的精确 UTF-8 bytes。Simple bundle 包含 V7 精简角色
  规则、完整 canonical contract block（其中包含 AC，inline request 只出现一次）、相关
  文件索引、
  delimiters 和最小绑定 digest。它不包含 raw source 审计副本、Schema、历史 receipts、
  已完成任务、恢复手册、platform/system prompt、对话、renderer 外自动加载的根规则或
  Agent 后续读取。`context render --report` 记录每项输入的 path、section、digest 和
  byte count，并单独报告 ambient 根 `AGENTS.md` bytes。测试只断言 renderer 输出和读取，
  不声称约束 Agent 后续行为。
- `V7-DEC-131`（`amends: V7-DEC-006, V7-DEC-031, V7-DEC-035,
  V7-DEC-042, V7-DEC-050, V7-DEC-058, V7-DEC-064, V7-DEC-066,
  V7-DEC-071, V7-DEC-077, V7-DEC-078, V7-DEC-081, V7-DEC-083,
  V7-DEC-085, V7-DEC-097, V7-DEC-105, V7-DEC-106, V7-DEC-109,
  V7-DEC-110, V7-DEC-118`）：P0 只实现本地候选闭环
  `start → implementation → verify → A`，保留 B/C/A、实施授权、条件式审查、契约
  digest、验证、安全 Init、manifest、删除守卫和 context render。P0 必须暴露
  `task integrate`，但必须在 planned M、claim、保护 journal、target lease 或 ref 变更
  前无副作用返回 `integration_unavailable`。Integration grant/provider 接口、fake/real
  provider、claim/nonce 恢复、保护 journal、target lease、planned M、CAS、integration
  receipt、source acceptance、保护集成和 activation 整体移到 P1，相应完整测试也一起
  移动；P0 改测无副作用拒绝。
- `V7-DEC-132`（`amends: V7-DEC-003, V7-DEC-007, V7-DEC-010,
  V7-DEC-025, V7-DEC-033, V7-DEC-036, V7-DEC-040, V7-DEC-045,
  V7-DEC-051, V7-DEC-057, V7-DEC-090, V7-DEC-096, V7-DEC-106`）：Simple 使用当前
  clean 且 eligible 的 worktree；`task start` 在任何项目写入前，于该 worktree 从精确 B
  创建允许的非保护任务分支；
  CLI 变更使用命令级原子锁和 expected-head CAS，默认不增加 worktree 或长生命周期租约。
  只有并行顶层任务、真实多写入者、跨会话交接或明确隔离需要时，才使用额外 worktree
  和 Standard task-writer lease。租约过期后，接管同时要求 clean、head 精确匹配、没有
  effect-unknown operation、generation CAS，以及显式释放、可信 session 终止证据或范围
  明确的管理员恢复授权三者之一。Simple 仅在 eligibility、语义范围、风险、删除/迁移/
  外部/信任根动作、并发、真实阶段/审查/子 Agent/交接边界或硬上限要求时升级。项目
  常设策略要求且已获授权的基线 freshness fetch 属于 preflight，本身不触发升级；第二份
  receipt 也不触发升级。首次成功 happy path 在 A 前任务目录只有一个文件，A 后最多两个；
  B..C 最多一个实现 commit，A 恰增加一个 acceptance commit，直至 A 不发生管理员暂停；
  调用 `integrate` 可在 A 后产生一次决策停点。一次验证失败可增加一个 repair commit 并
  保持 Simple；超过这些 commit、文件或暂停上限则升级 Standard。阶段只做 scoped checks，
  最终 C 做一次完整验证。P0 只保存
  模型标识或 `unknown`；详细 model episodes 和比较移到 P1。
- `V7-DEC-133`（`amends: V7-DEC-019, V7-DEC-060, V7-DEC-076,
  V7-DEC-101, V7-DEC-107, V7-DEC-111`）：P0 Init 只接受空目标，或全部 managed path
  均不存在/已由同一 manifest 精确拥有的目标。既有 `AGENTS.md` 或其他 managed path
  冲突时，必须在写入前返回 `update_required`；已有项目的事务化更新属于 P1。每次创建前，
  外部 journal 必须持久写入并 sync transaction ID、规范路径、`absent_before`、type、mode
  和预期 digest，之后才允许创建。Rollback 仅依据该 write-ahead 证明执行。只有 ownership
  manifest 和全部 managed digest 精确匹配时，二次 apply 才只读成功。
- `V7-DEC-134`（`supersedes: V7-DEC-120`）：本清单全文为
  `workflow_version: V7 / decision_revision: rev9` 并取代 rev8。冻结 rev8 英文与中文
  全文 SHA-256 digest 分别为
  `d3648c96e19a37d4f26f001b21922f3b4964c6a8ec5483e1717d284039c18bb2` 和
  `da5ebc441ee57904d154c3571c7b351c9d573519057e84f2e23297c657e2c1f1`；它们只证明
  bytes 身份。不得静默重新分配 V7-DEC-001–133 的既有文本与历史关系。
- `V7-DEC-135`（`amends: V7-DEC-050, V7-DEC-083, V7-DEC-087,
  V7-DEC-089, V7-DEC-095, V7-DEC-099, V7-DEC-104, V7-DEC-110,
  V7-DEC-123, V7-DEC-125, V7-DEC-129, V7-DEC-131, V7-DEC-132`）：候选闭包同时
  覆盖历史和验证工作树。令 `candidate_commits = Reachable(C) \ Reachable(B)`；
  `candidate_touched_entries` 是每个候选 commit 的每条 parent edge 上递归 leaf-entry delta
  的并集。Regular file、symlink 和 gitlink 的 OID/mode/type 变化计入，隐式 directory-tree
  OID 不计。关闭 rename/copy 推断，旧路径删除和新路径新增分别检查。Spec 使用大小写敏感、
  strict UTF-8 NFC、repository-relative path bytes，scope 只允许有类型的 exact-path 或
  directory-prefix entry；拒绝 glob/negation、绝对/空/dot-segment、不可表示和大小写冲突
  path。受控工作流记录必须精确匹配 Spec 固定、CLI 管理的 path/field/content 白名单。
  Candidate history 中触及的每个产品 path 和非 cleanup action 必须同时获得冻结契约、适用
  implementation-scope record（P0 合作式来源记录或 P1 provider-backed authority）及
  B-bound action catalog 允许。最终 `tree(B) → tree(C)` delta 定义产品 action。Product
  deletion 是 B 中存在且最终 C 中不存在的
  entry，并继续要求额外双授权。删除经该 path 最近一次 scope-admission gate 证明原本
  不存在、在该 gate 后首次引入、且 B 与最终 C 中都不存在的 history-only entry，属于
  `candidate_cleanup`，不是 product deletion；
  只有原 addition 已获允许时，它才是
  implicit recovery action，并需要相同 path scope，且不授予 deletion capability。Simple
  触及任何 trust root 都失败；Standard 还必须具有 B/外部控制器
  绑定且可用的扩展、精确 path/action 绑定和适用审查；当前门禁仍使用 B 或仓库外已接受
  控制器，C 只能影响后续任务。Verify 入场及整套 validation 完成后，HEAD 与 task ref
  必须等于 C，index 与 tracked worktree 必须等于 `tree(C)`；不得存在 non-ignored
  untracked entry，product scope、受控记录 path 或 trust-root path 下也不得存在任何
  ignored/non-ignored untracked entry。Entry 递归枚举并包含 directory 与 symlink。
  Validation 临时输出位于 worktree 与 Git common dir 之外。失败使 evidence 无效、阻止
  A，并保留现场而不 clean 或删除。Scope 外 ignored dependency/cache 不做 hash，P0 也不
  宣称 hermetic validation。
- `V7-DEC-136`（`amends: V7-DEC-002, V7-DEC-005, V7-DEC-032,
  V7-DEC-068,
  V7-DEC-077, V7-DEC-094, V7-DEC-103, V7-DEC-109, V7-DEC-123,
  V7-DEC-124, V7-DEC-128, V7-DEC-131, V7-DEC-132`）：P0 的 implementation、fetch、
  additional-repair、task-recovery 和 lease-takeover authority record 是外部管理员指令的
  合作式控制来源记录，不是密码学 capability、issuer 认证证明或对抗性安全边界。每个 record
  绑定 authority class、规范 encoding/digest、声明 issuer/session、适用 controller、本机
  wall clock 下的 `not_before`/`expires_at` 及 class-scoped nonce。Fetch provenance 绑定
  repository/project、规范 remote identity、target ref/refspec、fetch action/policy，并可选
  绑定管理员预先给出的 expected remote SHA；不能强制绑定尚未取得的 B、task 或 contract。
  Implementation provenance 在 fetch 后产生，绑定精确 B、task、contract digest、controller、
  action 和 path scope。Additional-repair、recovery、lease-takeover record 分别使用固定的
  current-state binding；各 class 不可互换。CLI 维护持久
  `{authority_class, nonce} → record_digest` claim，用于同 pair 幂等复用。该 claim 在同一
  class 内拒绝不同 digest；同一 nonce literal 可以在另一 class 中
  独立存在，但 record 永远不能作为或转换成另一 class。该 claim 是位于
  `$GIT_COMMON_DIR/nm-v7/` 下、候选外的
  internal record；全部只读门禁通过后、首次获授权 mutation 前，在既有命令作用域锁下写入并
  sync。它跨进程重启持久化、串行化并发使用、支持同 pair 恢复、拒绝不同 digest，并保留到
  bound operation 或 task responsibility 关闭。Task 文件、环境变量及 candidate-controlled ref/path 不能充当
  来源记录的签发来源。P0 local `auto` action 需要管理员精确指令和该合作式门禁；它不是
  trusted/durable grant。P1 保护或外部 `auto` action 需要真实 provider grant。P0 没有
  可信时钟、异步撤销或 issuer 密码学验证；同账户恶意进程可
  伪造、改变或绕过本地记录。只有 class 适用的 cancel、supersede、contract revision、
  binding mismatch 和 expiry 才使记录失效；无关 task/contract event 不使 fetch provenance
  失效。认证且不可伪造的 authority 需要具有明确 trust、clock、replay 和 revocation
  语义的真实 P1 provider。
- `V7-DEC-137`（`amends: V7-DEC-090, V7-DEC-096, V7-DEC-102,
  V7-DEC-115, V7-DEC-123, V7-DEC-124, V7-DEC-130, V7-DEC-132`）：Profile 在
  contract digest、authority 来源记录和 S 之前选定，并在该 contract revision 内不可变；
  `task start` 只校验、不改变 profile。4096-byte request 和 16384-byte initial-context
  继续作为 start-time eligibility gate。Commit/pause 预算超限，以及只由其他方面合法的
  controller record 构成的超限，只设置可变 `observed_complexity=over_budget`；不改变
  profile、digest 或 authority，也不授予能力。未获允许的 task/product path 仍是候选闭包
  失败，不是预算超限。运行中新增 deletion、migration、external/protected action、
  trust-root action、high-risk review、stage、sub-Agent、handoff、concurrency 或更宽权限，
  进入既有 `blocked` 并记录 `profile_upgrade_required`；继续前必须取得新的 Standard
  contract revision、digest 和 authority。不得静默修改 profile，也不增加第九种状态。
- `V7-DEC-138`（`amends: V7-DEC-003, V7-DEC-013, V7-DEC-018,
  V7-DEC-034, V7-DEC-035, V7-DEC-039, V7-DEC-043, V7-DEC-050,
  V7-DEC-073, V7-DEC-075, V7-DEC-083, V7-DEC-094, V7-DEC-123,
  V7-DEC-124, V7-DEC-125, V7-DEC-128, V7-DEC-129, V7-DEC-132`）：`task start` 在任何项目写入、ref mutation、
  branch creation、worktree switch 或消耗 task ID 前，完成 secret、closed-Schema、
  completeness、profile consistency、digest、合作式来源记录、ID/ref uniqueness、B、
  cleanliness 和 baseline 检查。S 前还要求全局没有 non-ignored untracked entry，且
  product scope、受控记录 path 或 trust-root path 下没有 ignored/non-ignored untracked
  entry，并使用 V7-DEC-135 的递归 entry 规则。任何 `revise-contract` revision-start commit
  或新 authority 生效前，也必须对完整 replacement scope 执行相同 scope-admission gate，并在
  受控 revision record 中保存 scope 与 empty-set digest。确定性 preflight 失败不产生上述
  副作用。请求不完整时返回
  `contract_incomplete` 和有界 missing-field 摘要，不在项目中持久化 draft。Standard
  Formatter 或可信控制在项目外准备 draft，start 只接受完整候选。成功 start 创建 CLI
  管理的启动契约提交 S，`parent(S)=B`；S 只包含受控 task envelope、冻结契约，以及
  ready/in-progress 门禁通过后的 `state=in_progress`。它创建并附着 task ref，且只有在
  `HEAD=task_ref=S`、index 与 tracked worktree 等于 `tree(S)`、eligible worktree clean 时
  才成功返回。Agent 通过 implementation commit 推进该 ref。预算内 Simple 首次成功拓扑为
  `B-S-C-A`；一次失败候选为 `B-S-I-C-A`，其中 I 是失败 implementation，C 始终是最终
  候选。S 和 A 不计 implementation commit；这两个预算内案例在 B 后分别有 3 或 4 个
  commit。额外但已获授权的 implementation commit 只设置 observed complexity。所有情况下
  S 都是 C 的祖先；verify 要求 `HEAD=task_ref=C`，不 stage 或 commit Agent 产品修改，并且
  只在全部门禁通过后通过 `CAS(task_ref, old=C, new=A)` 创建 A，满足 `parent(A)=C`。
  P0 `verifying` 是命令作用域锁下绑定精确 C 的 command-local 派生状态；不提交，也不保存为
  `resume_status`。Task-ref envelope 对持久声明保持权威；Git common dir 中唯一 command
  checkpoint 只是 recovery state，不增加状态词汇。中断丢弃全部 partial evidence；绑定仍
  有效时返回此前持久状态，否则报告 `blocked` 且 `resume_status=in_progress`。下次 verify
  重跑完整集合。A 不重写；accepted 后返工通过 descendant C 和新 A 推进。预算内
  implementation、repair 或 verify 路径不增加 state-only commit。相同 S 只有在 clean
  eligible worktree 已附着 S 后才幂等；B、digest、ref 或 worktree 冲突失败关闭。
  `revise-contract` 同样只在完整 replacement revision 与新 authority 通过 preflight 后写入
  一个 revision-start commit，不持久化半成品 draft。
- `V7-DEC-139`（`amends: V7-DEC-030, V7-DEC-041, V7-DEC-044,
  V7-DEC-069, V7-DEC-072, V7-DEC-075, V7-DEC-080, V7-DEC-121,
  V7-DEC-123`）：Closed Schema 与 start/revision gate 强制
  `risk=high ⇒ review_required=true`；low risk 仍可显式要求 review，Simple 则必须为
  `risk=low` 且 `review_required=false`。V7 不增加 uncertainty Boolean 或 risk engine。
  未解决语义不确定性使契约不完整；管理员接受的重大剩余不确定性归类为 high risk。CLI
  不推断风险，但在写入前拒绝无效字段组合。运行中风险变化使用 V7-DEC-137 的新 revision
  路径。
- `V7-DEC-140`（`amends: V7-DEC-047, V7-DEC-049, V7-DEC-057,
  V7-DEC-091, V7-DEC-096, V7-DEC-099, V7-DEC-108, V7-DEC-110,
  V7-DEC-125, V7-DEC-130`）：V7 自有初始强制上下文是精确 renderer 输出，加上角色首次
  task action 前自动注入或强制读取的全部 V7-owned rule bytes。V7 ownership 只能来自
  ownership manifest 或精确 managed-section marker，不得把混合项目文本推断为 V7-owned。
  V7 生成的 root-rule bytes 计入；platform/system prompt 与项目自有非 V7 guidance 排除并
  单独报告。Simple 与每个已实现 Standard role 使用相同 16384-byte UTF-8 上限，happy path
  不要求读取其他 V7 Spec、Schema、历史或恢复文档。后续业务文件和异常触发读取不计入
  initial 指标。Redaction 先于 digest、显示和持久化。每个 validation action 记录
  exit/signal、raw/redacted byte count、redacted stdout/stderr 各自 domain-framed SHA-256
  digest，以及 truncation flag。每个 stream 固定分配 2048-byte excerpt，拆成 1024-byte
  UTF-8-safe head/tail，不跨 stream 重分配。一个 P0 structured CLI result 和一个 canonical
  receipt 分别最多 16384 bytes。必需 identity、binding、status、digest 和 AC-result 字段
  永不截断；excerpt 按冻结 AC/action 顺序分配，只允许缩短或省略 excerpt。若必需字段本身
  超限，则不创建 A，并以有界结果返回 `receipt_budget_exceeded`。Exception 与
  scope-violation 摘要使用同一策略。P0 不保存 raw digest 或完整逐命令日志，receipt/history
  不进入默认 bundle。
- `V7-DEC-141`（`amends: V7-DEC-006, V7-DEC-031, V7-DEC-045,
  V7-DEC-053, V7-DEC-057, V7-DEC-058, V7-DEC-066, V7-DEC-071,
  V7-DEC-076, V7-DEC-078, V7-DEC-081, V7-DEC-100, V7-DEC-101,
  V7-DEC-104, V7-DEC-107, V7-DEC-109, V7-DEC-110, V7-DEC-118,
  V7-DEC-131, V7-DEC-133`）：交付使用分别
  授权、分别报告的 slices。`P0-core` 是 Simple 与零阶段 Standard 的 aggregate runtime：
  contract、不可变逐字 Standard source、合作式来源记录、S/task branch、Agent C、history
  scope、untracked gate、structured validation、条件式 Reviewer、A、context 和失败关闭
  integrate stub。
  `P0-install` 包含三类 manifest、init dry-run/apply、external journal、rollback/recovery、
  template 和 Init Skill；宣称完整 P0 前两者都必须完成。`P0-standard-extension` 增加
  Formatter、stages、sub-Agent/handoff、可选 worktree/lease，以及正向
  deletion/trust-root 工作流；需要未实现扩展的请求失败关闭。`P1-core` 是 real
  provider-backed authority 和受保护 `dev` 的 grant、claim、journal、lease、planned M、
  CAS、integration receipt。Updater/migration、hotfix/stable/push、release/deploy、通知、
  模型比较和 controller-lifecycle 能力是具有独立授权与验收的可选扩展。Availability 只能
  来自绑定 B 或已接受外部控制器的 capability catalog；C、task 或 environment 不能启用
  slice。完成一个 slice 不代表完成另一个。P0 默认 bundle 只显示
  `task start → implementation → task verify`；integrate stub 仍可调用并测试，但从默认
  bundle 中省略。Verify 返回 `task_status=accepted`、
  `candidate_scope=local`、`integration_available=false`，不增加 `accepted_local` 状态。

## 4. 范围

### P0：本地候选闭环

`P0-core` 包含日常运行时：

- V7 英文实施 Spec 与完整中文管理员镜像、精简根规则、推荐 Spec、紧凑契约输入、主任务/
  receipt 模板、不可变逐字 Standard source 存储，以及恰好三个既有核心 Schema。
- 内存秘密预检、规范化契约 revision、冻结 profile、合作式控制来源记录、受控状态/revision
  转换及受控 resume。
- Simple 与零阶段 Standard aggregate 执行、具有合作式来源记录的基线 fetch、S/task branch、命令作用域锁、
  Agent C、history/path/action scope、worktree/untracked 闭包和 B/S/C/A 拓扑。
- 结构化最终验证、可信 action 分类、秘密处理、条件式普通任务 Reviewer、有界 evidence/
  output、A，以及带 V7 自有初始上下文核算的 `context render`。
- 单个模型标识或 `unknown`、V7 源码候选的独立技术 Reviewer，以及可调用但默认隐藏的
  `task integrate` 无副作用拒绝。

`P0-install` 包含安全分发路径：

- `template/v7`、中性 source/template/project-ownership manifests、`init --dry-run`、
  无冲突 `init apply`、目标外 write-ahead init journal、rollback/recovery 和 Init Skill。

宣称完整 P0 前两个 slice 都必须完成。所有安装保持未激活，P0 不更新 `dev`。

`P0-standard-extension` 单独交付，包含 Standard Formatter、stage template/branch、
sub-Agent/handoff、可选 worktree/lease/checkpoint，以及正向 deletion/trust-root 工作流。
需要未实现扩展的请求失败关闭；availability 只能来自绑定 B/外部控制器的 capability
catalog，这些内容均不进入 Simple 默认 bundle。

### P1：保护与外部闭环

`P1-core` 只包含受保护 `dev` 闭包：

- 管理员选定的首个真实 provider，为 implementation/control 与 integration authority 提供
  认证；以及对应测试专用 fake。
- Grant/claim/nonce 恢复、带失败/处置结果的保护 journal、target lease、planned M、CAS 和
  持久 integration receipt。
- 该 provider 所需的独立源码审查与 source acceptance、单独授权集成和最终位置 digest
  复算。

已有项目 update/migration、hotfix/stable/push、release/deployment、飞书通知、详细模型
episode/comparison 及最终 controller activation 是分别交付的可选扩展。每项具有独立
authority 与 acceptance，不阻塞 `P1-core`，也不会由其自动产生。

### 不做

- 修改或删除 V1–V6 来迁就 V7。
- 常驻 Runner、数据库、事件系统、心跳服务、第四个核心 Schema 或第二套用户可见任务
  状态机。
- Simple happy path 的额外角色、阶段或暂停。
- 默认 push、发布、部署、通知或生产访问。
- 通过 CLI、环境变量或项目配置启用 P1 fake provider。
- 把测试成功视为真实授权、接受或激活。
- 保存完整对话、逐命令日志或未脱敏秘密。
- 从 P0 检查宣称 issuer 密码学身份或 hermetic validation。
- 自动多模型重复实施。

## 5. 运行设计

### 5.1 输入、契约与权威

- 正式 Spec 和 Simple 内联请求在持久化前先做不落盘的已知秘密预检。
- Standard 保存不可变逐字 source snapshot，其中命令永久 inert；Simple 只在 immutable
  contract block 内保存一次短请求。
- `task.md` 是唯一规范任务契约；原始输入只是不可变证据，不形成第二契约权威。
- 具有合作式 fetch 来源记录的 preflight 取得 B 后，管理员或控制会话提供完整紧凑契约、
  预分配的未使用 task ID、冻结 profile，以及绑定 B 的合作式 implementation-authority
  来源记录。Profile 在 digest 与来源记录产生前选定。
- Fetch provenance 使用其 remote/ref/policy binding，永不作为 implementation provenance。
  Implementation provenance 只在 B 与精确 contract digest 存在后产生；其他 provenance
  class 使用各自固定的 class-specific binding matrix。
- `task start` 在项目/ref 变更前完成全部确定性预检，只接受完整契约，不编造语义或改变
  profile。失败以 `contract_incomplete` 等有界错误返回，不消耗 task ID，也不持久化 draft。
- Scope 已知后，start 以及每个纳入新 path/trust-root scope 的 revision，都在 claim 新
  provenance 或写 start record 前，递归执行与 verify 相同的全局 non-ignored 和 scoped
  ignored/non-ignored untracked gate。
- 上述只读门禁通过后，start 在首次 mutation 前于命令作用域锁下持久 claim 来源记录 nonce。崩溃
  可以只留下该 recovery claim；精确重试复用它，不同 binding 必须拒绝。
- Standard Formatter 或可信控制可在项目外准备、更新 draft candidate，并报告字段映射和
  未决缺口。只有完整且由 start 或 `revise-contract` 成功持久化后才成为权威；Simple
  bundle 不包含该准备流程。
- Start 成功时创建 `parent(S)=B` 的 S，在受控 task envelope 中冻结契约，在两个入口
  门禁通过后记录 `state=in_progress`，创建并附着 S 上的 task ref，并以
  `HEAD=task_ref=S`、tracked state 等于 `tree(S)` 成功返回。相同 S 只有在 clean eligible
  worktree 上才幂等；identity、B、digest、ref 或 worktree 冲突失败关闭。

### 5.2 状态、revision 与 digest

任务状态图为：

```text
draft → ready → in_progress → verifying → accepted
verifying → in_progress
accepted → verifying
draft|ready|in_progress|verifying → blocked
blocked → 受控恢复到 resume_status
blocked --[revise-contract]→ draft
blocked --[additional_repair_allowance]→ in_progress
draft|ready|in_progress|verifying|blocked → cancelled|superseded
accepted --[无集成事实 AND 无未决恢复事实]→ cancelled|superseded
```

- `ready → in_progress` 以及任何恢复进入 `in_progress` 的路径，都验证当前 P0 合作式来源
  记录，或在 P1 provider 实现后验证其 provider-backed authority。
- 进入 `blocked` 时原子保存受控恢复目标。P0 从不把 `verifying` 存为该目标；验证中断会
  丢弃 partial evidence，只能从 `in_progress` 重跑完整集合。
- 等待集成授权或目标复核时保持 `accepted`。
- P0 中 `verifying` 是绑定精确 C 的 command-local 派生状态，不是 task-ref commit。Git
  common dir 中的 command checkpoint 只是 recovery state。Accepted 后绑定失效进入该
  派生状态；中断时若绑定仍有效则返回此前持久状态，否则进入 `blocked` 且
  `resume_status=in_progress`。后续 candidate 从旧 A 继续，A 永不重写。
- 集成前的 `accepted` 只有在没有 local/remote integration fact，也没有 prepared、
  claimed 或 effect-unknown operation 时才能进入 `cancelled | superseded`。已集成产品问题
  建立 successor、hotfix 或 rollback task。
- Profile 在 contract revision 内不可变。使 profile 失效的新能力、权限或重大风险进入
  `blocked(profile_upgrade_required)`；只有完整新 revision、digest 和 authority 才可继续。
- 契约语义变化使用 `revise-contract` 并冻结旧 revision。完整 replacement、full-scope
  admission gate 与新 authority 必须先通过 preflight，再由一个 revision-start commit 记录
  逻辑上的 `blocked → draft → ready → in_progress` gate 顺序及 empty-set digest；不持久化
  半成品项目 draft。任务身份或核心目标变化建立 successor。
- `cancelled`、`superseded` 是任务终态；其不可变 receipts 保留此前状态、理由、actor
  provenance 和时间。

候选摘要为：

```text
candidate_revision_digest =
  SHA-256(
    "nm-v7.candidate-revision.v1\0" ||
    frame(contract_revision_digest_bytes) ||
    frame(B_bytes) ||
    frame(C_bytes)
  )
```

Canonical gate object 包含 project、task、revision、parent identity、source snapshot
digest、profile、difficulty、risk、`review_required`、target/target ref、请求动作类别、
路径范围、`delete_allow` 和封闭 Schema 的其他机器门禁字段。目标、成功标准、scope、
non-goals、约束、冻结假设和全部 AC 只出现于 contract block 的精确 bytes。可变
status/time、attempt、handoff、`observed_complexity`、模型元数据、evidence/review/
receipts、authority/grant/lease/journal 以及 B/S/C/A/M 从两项摘要输入中排除。

### 5.3 候选、证据与验收

P0 强制：

```text
B is an ancestor of C
parent(S) = B
S is an ancestor of C
HEAD = task_ref = C before acceptance
parent(A) = C
CAS(task_ref, old=C, new=A)
candidate_commits = Reachable(C) \ Reachable(B)
candidate_touched_entries =
  每个 candidate commit 的每条 parent edge 上递归 leaf-entry delta 的并集
tree(A) 与 tree(C) 的差异只允许 C-to-A 白名单
```

- S 是 CLI 管理的启动契约提交；C 是最终产品候选；A 只增加受控 accepted 状态、
  C/revision 绑定、有界摘要和不可变 receipts。
- C 不记录自己的 SHA 或 candidate digest；A 不记录自己的 SHA。
- 检查递归 regular-file、symlink、gitlink 的 OID/mode/type delta，不检查隐式
  directory-tree OID。关闭 rename/copy 推断，分别检查删除和新增路径。V7-DEC-135 的固定
  exact/prefix matcher 拒绝全部不支持 path。CLI 管理的工作流记录必须精确匹配固定 B-to-C
  path/field/content 白名单。History 中触及的每个产品 path 和非 cleanup action 必须满足
  contract scope、适用的 P0 合作式或 P1 provider-backed implementation scope 及 B-bound
  action catalog。Product deletion authority 依据最终 B-to-C delta 判断。删除 candidate
  创建、且 B 与最终 C 都不存在的 entry，只有原 addition 已获允许时才是同 path scope 内
  允许的 `candidate_cleanup`，不授予 deletion power。
- Simple 禁止触及 trust root；Standard 还必须由 capability catalog 启用扩展、具有精确
  path/action 绑定和适用审查，且变更后的 trust root 不能管理改变它的当前任务。
- 路径与字段白名单禁止在 C 到 A 之间改变契约、AC、risk、删除授权、project config、
  Schema、provider、action catalog 或 trust root。
- 最终聚合 C 上执行一次全部必需 AC；阶段只做 scoped checks，证据用于历史。
- `evidence_set_digest` 只覆盖显式选择的支持证据，不含 acceptance/integration receipt。
- `review_required=true` 时，Reviewer 不得参与当前候选的实现或修复，并绑定 contract
  revision、B、C、candidate digest 和 findings。缺失、过期、非独立、`unable`、
  `changes_required` 或未解决 blocking finding 均阻止 accepted。
  `review_required=false` 时不需要普通 task Reviewer receipt；`risk=high` 且
  `review_required=false` 在任务持久化前拒绝。

### 5.4 Simple、Standard 与上下文

Simple 要求单一目标、单一写入者、`difficulty=low`、`risk=low`、
`review_required=false`，且无删除、迁移、契约
请求的外部/保护动作、信任根变更、Reviewer、交接、子 Agent 或真实阶段边界，并满足
4096/16384-byte 上限。项目常设策略要求且具有合作式来源记录的基线 freshness fetch 属于
preflight，本身不使任务升级 Standard。

P0 成功路径为：

```text
nm-v7 task start
→ 启动契约提交 S
→ Agent 实现并提交最终候选 C
→ nm-v7 task verify
→ accepted candidate A
→ task_status=accepted, candidate_scope=local,
  integration_available=false
```

- `task integrate` 仍可调用并测试；P0 中无副作用返回 `integration_unavailable`，但不进入
  默认 rendered workflow。P1 只在精确 provider-backed grant 下执行。
- 在预算内 Simple 路径中，验收前任务目录只有 `task.md`，验收最多增加一个 receipt。
  其他方面合法的 controller-record 超限只做观测；未声明 path 使闭包失败。这不限制 scope
  内其他位置的产品文件变化。
- Simple 不创建 stage、evidence directory、普通日志、默认额外 worktree、持久租约，
  也不调用 Formatter、Subagent、Fixer 或 Reviewer。
- 预算内首次成功为 `B-S-C-A`；一次实际修复为 `B-S-I-C-A`，I 是失败候选，C 是最终
  候选。S 与 A 不计 implementation commit。额外已授权 commit 只做观测；所有拓扑仍要求
  S 是 C 的祖先、`task_ref=C`，并从 C CAS 到 A。Verify 不 stage 或 commit Agent 产品修改。
- Commit/pause 或仅由其他方面合法的 controller record 构成的预算超限，只设置可变
  `observed_complexity=over_budget`，不改变 profile。未声明文件仍使闭包失败；新能力仍要求
  新 Standard revision。
- V7 自有初始强制上下文是 renderer 输出加自动注入或首次 action 前的 V7 rule bytes。
  Simple happy path 自足，并与每个已实现 Standard role 一样保持在 16384 bytes 内。
  Platform、system 和项目自有非 V7 上下文单独报告；后续业务读取不计入该指标。

### 5.5 Git、验证、锁与恢复

- 有远端的普通任务由合作式控制来源记录允许 preflight fetch `origin/dev` 并记录精确 B。
  契约与 authority 绑定后，`task start` 确认工作树与 scoped ignored path 满足
  V7-DEC-135 entry gate、local `dev` 未 diverge 且 tracking ref 仍等于 B；只有其他 start
  gate 与持久 nonce claim 全部通过后才创建 S、附着允许的 task ref，并以 clean
  `HEAD=task_ref=S` 返回。
- 主 Agent 管理拓扑；Worker 只在指定分支提交，不得切换、合并、rebase、push 或更新
  保护 ref。
- 并行顶层任务可用独立 worktree；同一任务内部默认串行。
- P0 CLI 写操作使用命令级锁和 expected-head CAS。只有可用的 `P0-standard-extension` 才能在
  并行、交接或隔离确有需要时使用持久 writer lease。
- 持久恢复只保证 commit 或显式 checkpoint。Dirty/未知状态保留现场；工具不得自动
  reset、clean、stash、checkout、删除或覆盖。
- 验证使用结构化 argv、`shell=false`、固定 cwd、严格环境白名单，且不提供 grant、
  webhook、SSH 或生产凭据。
- 只允许 B 或外部 accepted action catalog 标记 local 的动作 spawn；unknown/external
  在 spawn 前拒绝。
- Verify 入场和整套 validation 结束后，要求 `HEAD=task_ref=C`、index 与 tracked worktree
  等于 `tree(C)`、全局没有 non-ignored untracked entry，且 product scope、受控记录 path、
  trust-root path 下没有 ignored/non-ignored untracked entry；V7-DEC-125 的限定 refs 也不得
  变化。递归枚举包含 directory 与 symlink。不一致使 evidence 无效并保留现场，不自动清理。
- Validation 使用 worktree 与 Git common dir 之外的 `TMPDIR` 和声明临时输出。P0 不扫描
  全部 ignored dependency，也不宣称 hermetic execution。
- 输出与异常在 digest、显示或持久化前先脱敏。每个 action 保存 raw/redacted byte count、
  redacted stream 各自的 framed digest、每个 stream 固定 1024-byte head/tail 及 truncation
  flag。必需 receipt 字段永不截断；若其本身超过 16384 bytes，
  `receipt_budget_exceeded` 阻止 A。P0 不保存 raw digest 或完整 log。

### 5.6 删除、Manifest 与 Init

- 产品删除始终同时需要 B 的可信策略和冻结契约的管理员确认精确路径。`P0-core` 拒绝正向
  action；只有 capability catalog 启用的 `P0-standard-extension` 才可允许 B 中已跟踪普通
  文件。Glob、目录、submodule、symlink、ignored/untracked、越界、trust root 及
  quarantine 绕过仍拒绝。
- V7-DEC-135 的 `candidate_cleanup` 与此分离：只能删除 scope 内 candidate 创建、且 B 与
  最终 C 都不存在的 entry，永不授权最终 product deletion。
- Source、template、ownership manifest 是不同对象。Source manifest 是中性精确
  inventory，其存在不产生 acceptance 或 activation。
- Manifest 不把自身或管理员接受记录列入 entries，不保存 self-digest，由调用方对
  domain-separated canonical bytes 计算摘要。
- P0 Init 不覆盖或事务化编辑冲突的 managed path；此类目标必须使用 P1 updater。
- Init journal 位于目标外，绑定 controller/source manifest、target root 和 transaction
  ID，并在每次创建前持久 sync create intent。
- Rollback 只清理当前事务创建、apply 前不存在且 type/mode/digest 仍完全匹配的普通文件；
  目录只能逐项安全清理后逆序删除空目录。
- 漂移、替换、symlink、未知内容、越界或不完整 journal 均保留现场并返回
  `recovery_required`。
- Ownership manifest 完全匹配时，二次 apply 才只读成功。

### 5.7 P1 集成与控制器生命周期

P1 恢复完整集成不变量：

```text
B is an ancestor of C
parent(A) = C
parents(M) = [B, A]
tree(M) = tree(A)
CAS(target_ref, old=B, new=M)
```

- Grant 绑定 repository/project、task、target、contract/candidate revision、active
  controller source digest、B、A、acceptance receipt、action、planned M、control session、
  nonce、`not_before` 和 `expires_at`。
- 选定的真实 provider 定义并强制 verifier 或 trusted IPC、issuer trust root、clock/skew、
  replay 行为及 revocation policy。只有该 provider-backed 路径可以宣称认证或不可伪造的
  implementation、recovery、source 或 integration authority。
- Provider claim 使用 `{nonce, operation_digest}`；相同组合幂等，不同 operation 复用
  nonce 必须拒绝。
- 保护 journal 顺序为 planned M、prepared、claim attempt、claimed、target/time 复核、
  CAS、`cas_applied`、finalized，并包含 `aborted_pre_effect`、`reconcile_required` 处置结果。
- CAS 前过期必须取得新 grant；已证明 CAS 后的恢复只补记录，不重复保护影响。
- Target lease 与 task-writer lease 分离，包含 owner token、expected head、generation、
  expiry。
- 本地集成、远端可见、稳定化、release 和 deployment 是不同事实与授权。
- `P1-core` source 闭包终止于：最终独立源码审查 → 认证管理员接受精确 source digest →
  单独精确集成授权 → 最终 target fetch 与最终位置 digest 复算 → CAS 与 receipt finalized。
  实现 controller-lifecycle extension 后，才进一步要求单独激活该精确 accepted 且已集成
  digest。
- 候选对 controller、Schema、provider、action catalog、删除策略或保护分支配置的修改只
  从后续任务生效。

## 6. 风险与已解决阻塞项

- 同账户 Agent 可以绕过本地工具；真实隔离仍需仓库外权限、分支保护或 OS/network
  sandbox。
- P0 合作式来源记录只检测确定性字段与绑定不匹配；不认证 issuer、不提供可信时钟或异步
  撤销，也不能阻止恶意本地进程伪造或绕过。
- 候选历史与 worktree 检查可以检测 scoped Git 闭包失败，但不 hash 全部 scope 外 ignored
  dependency/cache，也不提供 hermetic execution。
- 秘密检测是启发式。
- P0 没有保护集成或真实 provider，所有此类动作均失败关闭。
- 最终候选完整验证比选择性证据复用成本高；P0 有意选择更简单规则。
- Init 漂移时保留可恢复残留，不做猜测。
- 历史 digest 证明注册表文本身份，不证明机器理解的语义等价。
- Rev9 已处理候选 scope、合作式 authority 声明、profile revision、start 拓扑、
  risk/reviewer 映射及工作流自有 context/output 核算等已识别 P0 规范缺口，并拆分交付
  slices。该结论不授权实施、source acceptance、integration 或任何受保护/外部影响。

## 7. 验收标准

### P0 完成门

未来 P0 实施必须通过并报告：

```console
npm run v7:check
npm run v7:test
npm run skill:v7:check
git diff --check
npm run lm
```

同时满足：

- 英文规范 Spec 与中文管理员镜像在决议 ID、授权、状态、不变量、范围和验收语义上
  一致。
- 中文镜像的 V7-DEC-001–110 定义行匹配已绑定 rev5 中文 registry digest，其
  V7-DEC-111–119 定义行匹配已绑定 rev7 中文 registry digest。英文执行源使用相同
  ID 顺序并经过独立语义翻译审查，不要求匹配这两个中文 bytes digest。
  Rev8 英文与中文全文 digest 匹配冻结输入，V7-DEC-120–141 的关系和 revision metadata
  可机械核对；不从 hash 推断语义等价。
- `P0-core` 与 `P0-install` 分别报告 acceptance；只有两者都通过后才可宣称完整 P0。可选
  扩展单独报告状态，不得从任一 slice 推断。
- P0 最终候选有独立 `controller_source_technical_review`，且无未解决 blocking finding。
- 该审查不接受 source snapshot、不激活 controller、不授权集成。
- P0 只形成未激活候选，等待另行决定是否继续 P1。

### P0 必测场景

- 有效合作式来源记录只能执行精确绑定 operation。Missing/malformed record、authority class
  或适用 binding 不匹配（包括 fetch 的 remote/ref 及 implementation 的
  B/task/contract/action/path）、本机时钟过期、绑定后改变及同一 class 内跨 binding nonce 复用均失败；
  相同 nonce 与 record digest 幂等复验。进程重启及并发 same-pair/
  different-digest 场景证明持久、加锁的 claim 行为。同一 nonce literal 可在另一 class 中
  独立 claim，但把 record 当作另一 class 使用必须失败。测试不宣称 issuer 密码学身份。
- 完整 eligible Simple 无 Reviewer 也可 accepted；`risk=high, review_required=false` 在
  写入前失败，required、旧绑定、非独立或有 blocking finding 的审查阻止 accepted。
- `task start` 不编造语义或改变 profile。输入不完整/不确定时返回
  `contract_incomplete`，不消耗预分配 task ID，也不创建 ref、branch、worktree 或项目
  写入。成功重试在 B 创建并附着精确 S，以 `HEAD=task_ref=S` 返回；相同 S 仅在 clean
  eligible worktree 上幂等，冲突失败关闭。Product、受控记录或 trust-root scope 下已有的
  ignored/non-ignored entry 在 S 前失败，之后不能被 `candidate_cleanup` 吸收。
- 预算内首次成功 Simple 生成 `B-S-C-A`；一次实际修复生成 `B-S-I-C-A`；额外已授权 commit
  只设置 observed complexity。C 始终是最终候选，S 必须为其祖先；verify 要求
  `HEAD=task_ref=C`，A 满足 `parent(A)=C` 并从 C CAS。Detached C、task-ref mismatch、
  缺少 S ancestry、stale CAS 和未提交 Agent 变更均失败；verify 不自行创建 C。
- Profile 在 digest 与来源记录前固定。纯 commit/pause 预算超限只改变
  `observed_complexity`；新能力或更宽 scope 进入 `blocked(profile_upgrade_required)`，并
  要求新 Standard revision 与来源记录。
- Resume 重跑全部目标门禁，不能绕过 authority 来源记录、candidate binding、scope 或
  review。
- P0 验证中断会丢弃 partial evidence，从不恢复 `verifying`，并从 `in_progress` 重跑完整
  集合；失效的 accepted 工作通过 descendant C 推进，不重写旧 A。
- Contract identity、gate 或 immutable block 变化改变 contract digest；可变状态、时间、
  `observed_complexity`、证据和运行元数据不改变。
- B 或 C 变化改变 candidate digest，并使绑定 evidence、review、acceptance 失效。
- Candidate-history scope 必须发现越界修改后还原。测试覆盖递归 leaf entry 而不含
  directory-tree OID、rename 两端、mode/type/symlink/gitlink、exact/prefix matcher 及拒绝
  path、受控工作流记录、适用 P0/P1 implementation scope、action catalog 和删除 authority。
  P0-core 拒绝所有 Simple trust-root touch，以及 Standard extension 不可用时的全部正向请求；
  扩展实现后由其独立验收 exact-binding 正向案例。
- 失败候选可以执行已获允许的 in-scope 文件新增，修复后的 C 可以在该 path 不存在于 B 和最终 C 时将其作为
  `candidate_cleanup` 删除；这不要求或产生 product-deletion authority。最终删除 B entry
  仍要求双门禁。Scope 扩张覆盖已有 ignored entry 时，revision admission gate 必须失败，
  不得把该 entry 转成 cleanup。
- Verify 拒绝 pre-existing/validation-created non-ignored untracked entry，也拒绝 scope、受控
  path 或 trust-root path 下 ignored entry，包括递归 directory/symlink 场景；接受仓库外声明
  临时输出，并在失败时保留现场。继续强制 C-to-A path/field 白名单。
- 无关并发 refs 不导致验证失败；限定 task、target 或 trust-root refs 变化必须失败。
- Standing fetch provenance 可在 B/task/contract 尚不存在时执行，但绑定精确 repository、
  remote、ref/refspec、policy 和 action。错误 binding、failed/stale fetch 及冒充
  implementation provenance 均失败；成功 fetch 记录 B，分支祖先从精确 `origin/dev` 开始。
- Validation 拒绝 shell injection、环境泄露、unknown/external action 及限定 candidate/ref
  变更。测试固定 redaction-before-digest、分离 framed redacted-stream digest、raw/redacted
  count、冻结顺序 1024-byte head/tail 分配、16384-byte result/receipt、必需字段保留和
  `receipt_budget_exceeded`；P0 不保存 raw digest 或完整 command log。
- Core 删除守卫拒绝缺少双授权和全部排除路径。Standard extension 不可用时，正向删除或
  trust-root 工作流失败关闭；扩展实现后另行测试。
- `P0-install` Init 不覆盖既有内容、不修改保护 ref、不创建 remote、不 push；冲突在写入前
  返回 `update_required`。Journal 严格 write-ahead；rollback 只处理当前事务精确创建物；
  漂移时保留现场。
- Source manifest 单独存在不产生 acceptance/activation；self-entry、遗漏/额外 runtime
  文件以及 path/type/mode/content drift 均失败。
- P0 不暴露 activation 能力，并拒绝声明多个 active control version 的 project/config。
- Simple 零阶段、零额外角色，默认 task-record 拓扑在预算内；request 与 V7 自有初始强制
  上下文满足 4096/16384-byte 上限。每个已实现 Standard role 使用相同 initial 上限，
  Simple happy path 不读取其他 V7 工作流文档。
- `task integrate` 不进入默认 bundle，并在 planned M、provider call、journal、target
  lease、receipt 或 ref 变化前返回 `integration_unavailable`。Verify 报告
  `task_status=accepted`、`candidate_scope=local`、`integration_available=false`。
- 生成项目在 P0 静态保证通知默认关闭。

### P1 验收

- 选定的真实 provider 对其拥有的 authority class 拒绝 forged/tampered capability、错误
  authenticated issuer，以及 provider 定义的 replay、clock、expiry 和 revocation 失败；
  有效 provider-backed implementation record 通过与 P0 相同的 candidate-closure scope gate。
- Grant/provider、nonce/claim、journal 崩溃点、有效期边界、target lease fencing、
  planned M、CAS 和 integration receipt 场景通过，包括一个成功 fixture CAS 和
  effect-unknown reconciliation。
- 第二次 target freshness 检查使旧 evidence/authority 失效；push 若分离则立即另检。
- `P1-core` acceptance 只证明 provider-backed authority 和受保护 `dev` 闭包。
  Updater/migration、hotfix/stable/push、release/deploy、通知、模型比较和 controller
  lifecycle 分别报告扩展结果；选定真实适配器前只使用受控 fixtures。
- Notification extension 实现后仍默认关闭，要求窄范围 grant，且不改变工程验收。
- `P1-core` 要求最终 source snapshot 重新完成独立审查、认证管理员接受、分离授权集成和
  最终位置 digest 验证；controller-lifecycle extension 实现后再要求分离 activation。
- Activation extension 实现后拒绝第二个 active control version，失败时保留此前认证
  activation record。
- Acceptance 后仍保持 `experimental=true`、`recommended=false`、
  `production_ready=false`，直至后续独立决议改变。
