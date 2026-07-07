# {{PROJECT_NAME}}

一句话介绍项目的核心用途或价值。

## 项目简介

本项目用于……，主要解决……问题。适用于……场景。

## V3 工作流

本模板采用 Goal 驱动的轻量工作流：

1. 管理员手动准备需求文档、验收标准、原型和设计规范。
2. Agent 基于这些文档生成 Plan，并从 Plan 拆分 Goal，等待管理员确认。
3. Agent 从 `dev` 新建任务分支，在 Goal 模式下实现当前 Goal。
4. Agent 执行本地验证，通过后 push 当前任务分支做备份。
5. 默认等待管理员验收；管理员批准后才合并回 `dev`。

0 到 1 开发阶段以本地验证为质量门，GitHub 主要用于分支备份。首版稳定后再启用远端 CI/CD。

原型文件统一放在 `0a-docs/0b-design/prototype/v<number>/` 中。创建新原型前先扫描已有
`v<number>` 目录并使用最大数字加 1；每个版本目录自包含该版 HTML、图片、CSS、说明等资产。

## 基础命令

安装依赖：

```bash
npm install
```

检查 Markdown：

```bash
npm run lm
```

格式化 Markdown：

```bash
npm run fm
```

运行本地验证：

```bash
npm run verify
```

检查 V3 工作流结构：

```bash
npm run workflow:check
```

发送管理员通知：

```bash
./0d-scripts/notify-admin.sh --level info --title "Status" --message "Message"
```

通知默认使用飞书卡片格式，并按 `--level` 映射标题颜色：

- `success` / `completed` / `merged_to_dev`：绿色。
- `error` / `failed` / `blocked`：红色。
- `warning` / `action_required` / `needs_human` / `needs_replan`：黄色。
- `info`：蓝色。
- `no_change` / `skipped`：灰色。

通知卡片使用两档布局：

- 默认紧凑模式：`info`、`success`、`no_change` 等普通状态只展示一行元信息加一段正文，避免在手机端占用过多屏幕空间。
- 诊断模式：`warning`、`action_required`、`needs_replan`、`error`、`blocked` 等需要处理的通知会额外展示 `下一步`。

所有卡片都会自动包含 `sent YYYY-MM-DD HH:mm:ss UTC+8`，用于判断通知投递是否延迟。

飞书频控注意事项：

- 自定义机器人限制为单租户单机器人 `100 次/分钟`、`5 次/秒`，达到任一窗口上限都会触发限流。
- 飞书从 2022-01-05 起严格执行自定义机器人 `100 次/分钟` 频控，超出频率的消息会发送失败。
- 错误码 `11232` 表示创建消息触发服务级频控，`11233` 表示创建消息触发会话级频控，`11247` 表示内部发送消息触发频控。
- 官方建议发送消息尽量避开整点和半点，例如 `10:00`、`17:30`，否则可能因系统压力触发 `11232`。
- 人工测试通知不要连续快速发送大量卡片；如果出现 `11232 frequency limited`，应等待至少 60 秒后重试，整点/半点附近建议等待 2-3 分钟。

校验设计规范：

```bash
npm run design:lint
```

## 相关文档

- [项目结构说明](./PROJECT_STRUCTURE.md)
- [Agent 英文规则](./AGENTS.md)
- [Agent 中文规则](./AGENTS.zh-CN.md)
- [V3 工作流](./0c-workflow/WORKFLOW_V3.md)
- [分支规范](./0c-workflow/BRANCHING.md)
- [验证规范](./0c-workflow/VERIFY.md)
- [发布检查清单](./0c-workflow/RELEASE_CHECKLIST.md)
- [Goal 模板](./0c-workflow/GOAL_TEMPLATE.md)
- [Plan 模板](./0c-workflow/PLAN_TEMPLATE.md)
- [项目验证配置](./0c-workflow/project-profile.yml)
- [关键决策记录](./0a-docs/DECISIONS.md)
- [需求挖掘提示词](./0a-docs/0c-prompts/discover-requirements.md)
- [DESIGN.md 生成提示词](./0a-docs/0c-prompts/write-design-md.md)
- [Plan 和 Goal 拆分提示词](./0a-docs/0c-prompts/plan-goals-from-requirements.md)
- [安全审查提示词](./0a-docs/0c-prompts/security-review.md)

项目功能、技术栈、启动命令、测试命令和发布规则由管理员根据实际项目补充。
