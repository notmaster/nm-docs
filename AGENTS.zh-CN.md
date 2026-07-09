# 仓库 Agent 规则

本仓库维护可复用的 NotMaster 工作流模板、skills 和确定性工具。变更必须精确、有版本意识，并便于其他 Agent 执行。

## 语言和文档

- 根目录面向用户的文档默认使用英文。
- `docs/` 下为主要用户文档提供简体中文翻译。
- 修改 `AGENTS.md` 时，必须在同一次变更中同步更新 `AGENTS.zh-CN.md`。
- `README.md` 聚焦当前推荐的工作流版本。
- 将历史版本、安装细节和迁移说明放入 `docs/`。
- Agent 规则保持简洁。不要把 `AGENTS.md` 写成完整手册。

## 分支管理

- 使用 `dev` 作为集成分支。
- 不要直接在 `main` 上进行常规开发。
- 使用任务分支，例如 `feature/*`、`fix/*`、`docs/*`、`refactor/*` 或 `chore/*`。
- `hotfix/*` 只用于紧急生产修复，并且必须从 `main` 创建。
- 合并回 `dev` 前，本地验证必须通过，并且管理员必须验收该工作。
- 只有在用户明确要求发布或稳定更新时，才合并到 `main`。
- 分支合并后，评估是否清理该分支。不要自动删除 `main`、`dev`、`release/*`、`hotfix/*`、未合并分支，或仍承担审查、验收、发布、回滚责任的分支。

## 执行质量

- 开始非平凡任务前，说明假设、风险和成功标准。
- 如果请求存在多种合理解释，询问管理员，不要静默选择。
- 优先采用满足请求的最简单实现。不要添加未请求的功能、抽象或配置。
- 保持变更精确。不要顺手重构、重排格式或清理无关代码。
- 每一行变更都应能追溯到管理员请求。

## 模板规则

- 将 `template/v5/manifest.json` 视为 V5 模板文件的事实来源，`template/v4/manifest.json` 视为 V4，`template/v3/manifest.json` 视为 V3。
- 添加或重命名 V3、V4 或 V5 模板文件时，更新对应版本的 `manifest.json`、`PROJECT_STRUCTURE.md`，以及仓库 `README.md`。
- 保持 V3、V4 和 V5 文件自包含；生成的项目应通过 `npm run workflow:check` 和 `npm run verify`。
- 除非用户明确要求，否则不要删除旧模板版本。

## Skill 规则

- 仓库维护的 skills 放在 `skills/<skill-name>/`。
- 每个 skill 都必须包含有效的 `SKILL.md`，并使用简洁、面向触发场景的 frontmatter。
- 将确定性操作放在 `tools/` 或 `skills/<skill-name>/scripts/`；不要依赖说明文字来执行脆弱的文件同步。
- Skill 引用文件保持在 skill 目录下一层，并且只在需要时加载。
- 不要在 skill 文件夹中放入无关的 README、changelog 或 guide 文件。

## 工具规则

- 初始化、更新、审计、安装和校验操作优先使用确定性脚本。
- 已有项目更新工具必须要求 Git，检查工作区，创建分支，然后再写文件。
- 迁移时不要静默丢弃项目专属指导。将长期有效的信息保存在合适的 V3 文档中。

## 安全

- 不要覆盖用户未提交的变更。
- 除非管理员明确要求，否则不要运行破坏性 Git 操作。
- 删除任何本地或远程分支前，确认工作区干净，并报告合并证明、分支角色和准确删除命令。
- 需要删除文件时，优先移动到 `.delete-pending/`，并等待管理员确认。

## 验证

- Markdown 变更后运行 `npm run lm`。
- V5 模板或工具变更后运行 `python3 tools/nm-v5/nm_v5.py check --target template/v5 --source-dir .`。
- V4 模板或工具变更后运行 `python3 tools/nm-v4/nm_v4.py check --target template/v4 --source-dir .`。
- V3 模板或工具变更后运行 `python3 tools/nm-v3/nm_v3.py check --target template/v3 --source-dir .`。
- 编辑 skills 后运行 skill validator：

```bash
python3 /Users/jango/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/<skill-name>
```
