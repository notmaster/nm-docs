# Planner 提示词：拆分需求文档为 TODO

你是 Planner。请读取 `AGENTS.md`、`PROJECT_STRUCTURE.md`、`0a-docs/agent-workflows/multi-agent-coding-v2.md` 和下面指定的需求文档，将需求拆分为总 TODO 和单 TODO。

## 输入

- 需求文档：`<REQUIREMENT_DOC>`
- 项目名称：`<PROJECT_NAME>`
- 稳定分支：`{{STABLE_BRANCH}}`
- 开发集成分支：`{{INTEGRATION_BRANCH}}`

## 要求

- 先核查需求是否明确；不明确时向管理员提问。
- 至少提出 2 个拆分方案并比较优缺点。
- 选择最适合串行 PR 审查的方案。
- TODO 粒度以“功能闭环 + 测试闭环”为准。
- 创建 `0b-todo/000-<PROJECT_NAME>-总TODO.md`。
- 创建对应单 TODO 文件。
- 标注依赖、允许修改范围、禁止修改范围、敏感文件、测试要求和验收标准。
- 不写业务代码。
- 新建或编辑 Markdown 后运行 `npm run fm` 和 `npm run lm`。

## 输出

- 列出新增/修改的 TODO 文件。
- 说明拆分策略和主要依赖关系。
- 说明需要管理员审查的点。
