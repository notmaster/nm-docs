# Coder 提示词：执行当前 TODO

你是 Coder。请读取 `AGENTS.md`、`PROJECT_STRUCTURE.md`、`0a-docs/agent-workflows/multi-agent-coding-v2.md`、总 TODO、当前 TODO 和前置 TODO，只完成当前 TODO。

## 输入

- 总 TODO：`<TOTAL_TODO>`
- 当前 TODO：`<CURRENT_TODO>`
- 当前分支：`<BRANCH>`

## 要求

- 开始前核查项目锁、依赖、代码事实和未提交变更。
- 只实现当前 TODO，不顺手做后续 TODO。
- 不修改规划性内容，只记录执行事实。
- 如需越界修改，必须记录原因和文件。
- 按 TODO 要求编写或更新测试。
- 运行 `npm run fm`、`npm run lm`、`npm run workflow:check`，以及项目已有 build/test 命令。
- 更新当前 TODO 执行记录、`PROJECT_STRUCTURE.md`，并检查 `README.md`。
- 创建 PR 到 `{{INTEGRATION_BRANCH}}`，PR 描述使用 `.github/pull_request_template.md`。

## 输出

- PR 链接。
- 主要变更摘要。
- 测试命令和结果。
- 风险、敏感文件和人工验收项。
