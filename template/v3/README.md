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
