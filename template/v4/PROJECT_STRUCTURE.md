# PROJECT_STRUCTURE

> 本文档供 AI 快速理解项目结构，请保持简洁。
> 项目结构必须使用文件树结构展示，并给关键目录添加备注。

## 项目文件树结构

```text
{{PROJECT_NAME}}/
├── .codex/
│   ├── config.toml                 # Codex 项目级配置和轻量 hook 配置（可选）
│   └── hooks/
│       └── stop-status.sh           # Stop hook 状态提醒
├── .delete-pending/                 # 待管理员确认删除的文件
├── 0a-docs/
│   ├── DECISIONS.md                 # 影响后续实现、验收或发布的关键决策记录
│   ├── 0a-spec/                     # Spec 合约目录，命名 SPEC-<slug>-V<n>.md
│   ├── 0b-design/
│   │   └── prototype/               # 原型版本根目录，使用 v1、v2、v3 自增长目录
│   └── 0c-prompts/
│       ├── write-spec.md            # 需求挖掘并生成 Spec 的提示词
│       ├── review-spec.md           # Spec 多模型评审提示词
│       └── security-review.md       # 上线前安全审查提示词
├── 0b-goals/
│   └── ROADMAP.md                   # 唯一运行时状态文件：阶段表、进度、交接、待人工验收清单
├── 0c-workflow/
│   ├── WORKFLOW_V4.md               # V4 主流程（staged / auto 两种模式）
│   ├── SPEC_TEMPLATE.md             # Spec 编写规范与 frontmatter 定义
│   ├── AGENT_RECIPES.md             # Claude / Codex / Grok 启动配方与固定短指令
│   ├── BRANCHING.md                 # 分支和合并规范
│   ├── VERIFY.md                    # 本地验证规范
│   ├── RELEASE_CHECKLIST.md         # 上线前发布检查清单
│   └── project-profile.yml          # 项目类型和验证要求声明
├── 0d-scripts/
│   ├── check-workflow.sh            # V4 结构和命名轻量检查
│   ├── verify.sh                    # 本地验证总入口
│   ├── run-goals.py                 # auto 模式无人值守 runner
│   ├── notify-admin.sh              # 管理员通知入口
│   └── nm-notify-feishu.sh          # 飞书通知底层脚本
├── .gitignore
├── .markdownlint.json
├── .markdownlintignore
├── .nm-template-state.json          # 模板版本和受管理文件哈希
├── AGENTS.md                        # Agent 英文极简硬规则（唯一规则面）
├── AGENTS.zh-CN.md                  # 管理员查看用中文规则
├── CLAUDE.md                        # Claude Code 入口指针，引向 AGENTS.md
├── GROK.md                          # Grok 入口指针，引向 AGENTS.md
├── package.json
├── PROJECT_STRUCTURE.md
└── README.md
```
