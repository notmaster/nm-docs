# 工作流 V5

> 管理员对照。执行以 `WORKFLOW_V5.md` 为准。  
> 设计决议：`resolutions/RESOLUTION-V5-DESIGN-v1.md`。

## 成熟度状态

> **实验性。** V5 仅保留用于受监督评估和已有试用。不得用于无人值守 `auto`、自动合并、发布、部署、生产变更，也不得接触生产凭据或生产数据。runner 成功及内建检查通过只是一项诊断信号，不是独立验收证据。已批准的决议仅记录历史设计意图，并不证明当前实现已满足该意图。

## 核心

Spec **confirmed** 后，经 **Phase → Task** 落地；**磁盘状态**为真相；**实验性 runner + 短命编排 + Worker**；模式 **staged / auto**。

## 目录

| 路径 | 作用 |
| --- | --- |
| `0a-docs/0a-spec/` | 定稿 Spec |
| `0b-runtime/INDEX.yaml` | 运行时瘦索引 |
| `0b-runtime/tasks/` | 任务卡 |
| `0b-runtime/issues-ledger.md` | 阻塞/跳过账本 |
| `0c-workflow/` | 契约（Agent 读英文） |
| `0d-scripts/` | 脚本 |

## 模式

- 未指定 → 管理员必选 staged / auto。
- staged：每 Phase 验收后合 `dev` 再继续。
- auto：仅在一次性、非生产且无高影响能力的环境中试验；不构成无人值守高影响合并授权。
- 恢复时可切换模式，冲突先说明。

受当前实验性限制约束，两种模式在改变 `dev` 或其他受保护 ref 前都必须停止并交由管理员控制。历史 auto 设计并未把该能力授予当前 runner。

## 生命周期（摘要）

0. Spec 定稿并校验  
1. 写索引与任务卡  
2. 每 Phase：任务分支 → Worker（自修≤10）→ candidate → 管理员控制集成到 dev → Phase 全量 verify
3. 全部完成通知；账本保留跳过/人工项；`workflow_completed` 不代表已经可以发布、部署或上线

runner 不会独立重验状态、证据或 Git 操作，因此其成功退出不能单独作为门禁证据。当前 V5 试用中，Task 成功后只准备 candidate 并请求管理员控制集成，不得自动合入 `dev`；其余生命周期仅描述历史设计意图，不会扩大当前 runner 的权限。

## 通知

`notify-event.sh` 发**事件**；飞书首期；progress / attention 可分 webhook。

## Git / 删除

基线 dev；不直改 dev；不从 main 拉日常分支；删除只进 `.delete-pending/`。
