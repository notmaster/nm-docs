# {{PROJECT_NAME}}

一句话介绍项目的核心用途或价值。

## 项目简介

本项目用于……，主要解决……问题。  
适用于……场景。

## 协同开发

- 开发集成分支：`{{INTEGRATION_BRANCH}}`。
- 稳定分支：`{{STABLE_BRANCH}}`，仅由管理员确认后合并。
- 协同流程：[多模型协同编程流程](./0a-docs/agent-workflows/multi-agent-coding-v2.md)。
- TODO 与执行记录：[`0b-todo/`](./0b-todo/)。

## 基础检查

### 安装依赖

```bash
npm install
```

### 格式化 Markdown

```bash
npm run fm
```

### 检查 Markdown

```bash
npm run lm
```

### 检查协同流程

```bash
npm run workflow:check
```

## 相关文档

- [项目结构说明](./PROJECT_STRUCTURE.md)
- [多模型协同编程流程](./0a-docs/agent-workflows/multi-agent-coding-v2.md)
- [Planner 提示词](./0a-docs/prompts/planner-split-todo.md)
- [Supervisor 提示词](./0a-docs/prompts/supervisor-start.md)

项目功能、技术栈、启动命令、测试命令和许可证由管理员根据实际项目补充。
