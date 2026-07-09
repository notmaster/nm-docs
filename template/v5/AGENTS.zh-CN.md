# Agent 规则（NM V5）

> 管理员对照译文。**执行以 `AGENTS.md` 英文源为准。**

完整工作流：`0c-workflow/WORKFLOW_V5.md`（英文）/ `WORKFLOW_V5.zh-CN.md`。  
设计决议：`0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md`。

## 语言与环境

- 与管理员沟通可用其使用的语言（默认可中文）。
- 工作流规则、任务卡、索引字段、Agent 提示骨架为**英文**。
- 默认时区：UTC+8。

## 执行合约

- 运行时真相在磁盘：`0b-runtime/INDEX.yaml`、任务卡、`issues-ledger.md`、已确认 Spec。
- 实质性工作前读 `AGENTS.md`、索引中的 Spec、索引本身；其它文档按需加载。
- 仅执行 `status: confirmed`（或 `final`）的 Spec。

## 角色

- **Runner**：阶段推进、门禁、通知、恢复检查。
- **编排会话（短命）**：拆 Phase/Task、最小上下文包、派 Worker。
- **Worker**：单 Task 实现、验收、自修、更新任务卡、精简汇报。
- 禁止把长对话当作项目记忆；决策落盘。

## 模式

- 索引 `mode` 未指定 → 强制管理员选 `staged` / `auto`。
- staged：每 Phase 验收后再合 `dev` 并继续。
- auto：验证通过则继续；仅硬停或授权 skip 时停/跳。
- 终止后恢复可切换模式；冲突先说明再改文件。

## 停机与跳过

- 硬风险、验收门、Spec 冲突、自修满 10 且不可 skip → attention。
- 仅 `skip_on_fail: true` 可在满 10 轮后记账跳过（auto）。

## 分支与删除

- 基线 `dev`；不从 main 拉日常分支（hotfix 除外）；不直改 `dev`。
- 下一步前先合回 `dev`；已合并分支可评估删除。
- **禁止物理删除文件** → 移入 `.delete-pending/` 并汇报。

## 验证与通知

- Task：任务验收命令 + 自修 ≤10。Phase：全量 `verify.sh`。
- 通过 `notify-event.sh` 发事件；飞书为首个渠道。
- 飞书密钥：`~/.config/nm-docs/nm-notify-feishu.env`（`600`，本机全局）。勿把 webhook/secret 写进仓库。
- 双通道：`FEISHU_WEBHOOK_PROGRESS` / `FEISHU_WEBHOOK_ATTENTION`（及对应 `FEISHU_SIGN_SECRET_*`）；未配置则回落 `FEISHU_WEBHOOK_URL`。
- `project-profile.yml` 只声明 env **变量名**。配置与签名说明见 `0c-workflow/NOTIFY_EVENTS.md`。
