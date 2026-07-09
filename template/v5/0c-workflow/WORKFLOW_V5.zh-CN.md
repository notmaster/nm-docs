# 工作流 V5

> 管理员对照。执行以 `WORKFLOW_V5.md` 为准。  
> 设计决议：`resolutions/RESOLUTION-V5-DESIGN-v1.md`。

## 核心

Spec **confirmed** 后，经 **Phase → Task** 落地；**磁盘状态**为真相；**runner + 短命编排 + Worker**；模式 **staged / auto**。

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
- auto：验证通过继续；硬停或授权 skip 例外。
- 恢复时可切换模式，冲突先说明。

## 生命周期（摘要）

0. Spec 定稿并校验  
1. 写索引与任务卡  
2. 每 Phase：任务分支 → Worker（自修≤10）→ 合 dev → Phase 全量 verify → 按模式停或继续  
3. 全部完成通知；账本保留跳过/人工项  

## 通知

`notify-event.sh` 发**事件**；飞书为首个渠道。

- 密钥：`~/.config/nm-docs/nm-notify-feishu.env`（权限 `600`，本机全局，多项目共用）
- 路由：`progress` → 进度 webhook；`attention` → 提醒 webhook；未配置分流时回落 `FEISHU_WEBHOOK_URL`
- `project-profile.yml` 只声明 **env 变量名**，不写 URL/secret
- 安静 / 弹窗靠飞书群通知设置（建议两群）；卡片模板内置，无需按事件配模板
- 完整说明：`NOTIFY_EVENTS.md`（英文，以之为准）

## Git / 删除

基线 dev；不直改 dev；不从 main 拉日常分支；删除只进 `.delete-pending/`。
