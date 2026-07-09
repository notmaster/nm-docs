# Agent 规则（NM V5）

> 管理员对照译文。**执行以 `AGENTS.md` 英文源为准。**

完整工作流：`0c-workflow/WORKFLOW_V5.md`（英文）/ `WORKFLOW_V5.zh-CN.md`。  
设计决议：`0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md`。

## 成熟度与安全覆盖规则

- **V5 是实验性版本**，仅保留用于受监督评估和已有试用。
- 不得将 V5 用于无人值守 `auto`、自动合并、发布、部署、生产变更，也不得接触生产凭据或生产数据。
- runner 成功退出、`workflow:check` 和 `verify` 通过仅是诊断信号，不是独立验收证据或生产就绪门禁。
- 以上限制管辖 V5 的当前使用方式，不改写已批准的历史设计决议。

## 语言与环境

- 与管理员沟通可用其使用的语言（默认可中文）。
- 工作流规则、任务卡、索引字段、Agent 提示骨架为**英文**。
- 默认时区：UTC+8。

## 执行合约

- 运行时真相在磁盘：`0b-runtime/INDEX.yaml`、任务卡、`issues-ledger.md`、已确认 Spec。
- 实质性工作前读 `AGENTS.md`、索引中的 Spec、索引本身；其它文档按需加载。
- 仅执行 `status: confirmed`（或 `final`）的 Spec。

## 角色

- **Runner**：实验性地推进阶段、门禁、通知和恢复检查。
- **编排会话（短命）**：拆 Phase/Task、最小上下文包、派 Worker。
- **Worker**：单 Task 实现、验收、自修、更新任务卡、精简汇报。
- 禁止把长对话当作项目记忆；决策落盘。

## 模式

- 索引 `mode` 未指定 → 强制管理员选 `staged` / `auto`。
- staged：每 Phase 验收后再合 `dev` 并继续。
- auto：仅可在一次性、非生产且无高影响能力的环境内试验；它不构成合并、发布、部署或生产访问授权，改变 `dev` 或任何受保护 ref 前必须停止。
- 终止后恢复可切换模式；冲突先说明再改文件。

## 停机与跳过

- 硬风险、验收门、Spec 冲突、自修满 10 且不可 skip → attention。
- 仅 `skip_on_fail: true` 可在满 10 轮后记账跳过（auto）。

## 分支与删除

- 基线 `dev`；不从 main 拉日常分支（hotfix 除外）；不直改 `dev`。
- 下一步前请求由管理员控制合回 `dev`；安全集成后的分支可评估删除。
- **禁止物理删除文件** → 移入 `.delete-pending/` 并汇报。

## 验证与通知

- Task：任务验收命令 + 自修 ≤10。Phase：全量 `verify.sh`。
- 通过 `notify-event.sh` 发事件；飞书为首个渠道。
