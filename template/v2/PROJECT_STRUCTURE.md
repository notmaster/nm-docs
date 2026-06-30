# PROJECT_STRUCTURE

> 本文档供 AI 理解项目结构，请保持简洁
> 项目结构必须使用文件树结构进行展示
> 给必要的文件夹和文件添加备注

## 项目文件树结构

```text
{{PROJECT_NAME}}/
├── .delete-pending/            # 待管理员确认删除的文件
├── .github/
│   ├── workflows/
│   │   └── ci.yml              # Markdown 与协同流程检查
│   └── pull_request_template.md
├── 0a-docs/
│   ├── agent-workflows/
│   │   ├── templates/          # TODO、PR 和审查模板
│   │   └── multi-agent-coding-v2.md
│   └── prompts/                # 各角色提示词模板
├── 0b-todo/                    # 开发任务清单和执行记录（无需展开具体任务文件）
│   └── done/                   # 已完成任务归档
├── 0c-tools/
│   └── agent-workflow/         # 协同流程校验脚本
├── .gitignore
├── .markdownlint.json
├── .markdownlintignore
├── .nm-template-state.json     # 模板版本和受管理文件哈希
├── AGENTS.md
├── CLAUDE.md
├── package.json
├── PROJECT_STRUCTURE.md
└── README.md
```
