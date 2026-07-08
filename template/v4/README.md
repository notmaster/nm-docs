# {{PROJECT_NAME}}

一句话介绍项目的核心用途或价值。

## 项目简介

本项目用于……，主要解决……问题。适用于……场景。

## V4 工作流

本模板采用 Spec 驱动的目标工作流：

1. 管理员用 `0a-docs/0c-prompts/write-spec.md` 收敛需求，产出 Spec 并确认
   （frontmatter `status: confirmed`），放入 `0a-docs/0a-spec/`。
2. Agent 读取 Spec 生成 `0b-goals/ROADMAP.md`（阶段表 + 每阶段验收）；
   `staged` 模式下须经管理员确认。
3. 每个阶段在全新会话中执行：建分支、实现、本地验证、push、更新 ROADMAP、通知。
4. `staged`（默认）：每阶段停等管理员验收，验收通过后合并回 `dev`。
   `auto`：runner 无人值守逐阶段执行，验证通过即自动合并 `dev` 并 push。
5. 会话交接三件套：`AGENTS.md` + Spec + `ROADMAP.md`，其他文档按需加载。

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

检查 V4 工作流结构：

```bash
npm run workflow:check
```

auto 模式无人值守执行（示例使用 Codex，可换 claude / grok）：

```bash
npm run goals:auto -- --agent codex
```

发送管理员通知：

```bash
./0d-scripts/notify-admin.sh --level info --title "Status" --message "Message"
```

通知卡片会自动包含项目来源，默认使用当前 Git 仓库根目录名。需要覆盖时可以使用 `--project`，或在项目飞书配置中设置 `FEISHU_PROJECT_NAME` / `PROJECT_NAME`：

```bash
./0d-scripts/notify-admin.sh --project "{{PROJECT_NAME}}" --level info --title "Status" --message "Message"
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

所有卡片都会自动包含 `项目：<project>` 和 `sent YYYY-MM-DD HH:mm:ss UTC+8`，用于区分多个项目共用同一飞书机器人时的消息来源，并判断通知投递是否延迟。

飞书频控注意事项：

- 自定义机器人限制为单租户单机器人 `100 次/分钟`、`5 次/秒`，达到任一窗口上限都会触发限流。
- 飞书从 2022-01-05 起严格执行自定义机器人 `100 次/分钟` 频控，超出频率的消息会发送失败。
- 错误码 `11232` 表示创建消息触发服务级频控，`11233` 表示创建消息触发会话级频控，`11247` 表示内部发送消息触发频控。
- 官方建议发送消息尽量避开整点和半点，例如 `10:00`、`17:30`，否则可能因系统压力触发 `11232`。
- 人工测试通知不要连续快速发送大量卡片；如果出现 `11232 frequency limited`，应等待至少 60 秒后重试，整点/半点附近建议等待 2-3 分钟。

## 相关文档

- [项目结构说明](./PROJECT_STRUCTURE.md)
- [Agent 英文规则](./AGENTS.md)
- [Agent 中文规则](./AGENTS.zh-CN.md)
- [V4 工作流](./0c-workflow/WORKFLOW_V4.md)
- [Spec 编写规范](./0c-workflow/SPEC_TEMPLATE.md)
- [Agent 启动配方](./0c-workflow/AGENT_RECIPES.md)
- [分支规范](./0c-workflow/BRANCHING.md)
- [验证规范](./0c-workflow/VERIFY.md)
- [发布检查清单](./0c-workflow/RELEASE_CHECKLIST.md)
- [项目验证配置](./0c-workflow/project-profile.yml)
- [运行状态文件](./0b-goals/ROADMAP.md)
- [关键决策记录](./0a-docs/DECISIONS.md)
- [Spec 撰写提示词](./0a-docs/0c-prompts/write-spec.md)
- [Spec 评审提示词](./0a-docs/0c-prompts/review-spec.md)
- [安全审查提示词](./0a-docs/0c-prompts/security-review.md)

项目功能、技术栈、启动命令、测试命令和发布规则由管理员根据实际项目补充。
