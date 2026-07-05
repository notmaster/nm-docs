# PROJECT_STRUCTURE

> 本文档供 AI 快速理解项目结构，请保持简洁。
> 项目结构必须使用文件树结构展示，并给关键目录添加备注。

## 项目文件树结构

```text
{{PROJECT_NAME}}/
├── .codex/
│   ├── config.toml                 # Codex 项目级配置和轻量 hook 配置
│   └── hooks/
│       └── stop-status.sh           # Stop hook 状态提醒
├── .delete-pending/                 # 待管理员确认删除的文件
├── 0a-docs/
│   ├── DECISIONS.md                 # 产品、设计、技术和部署关键决策记录
│   ├── 0a-product/
│   │   ├── REQUIREMENTS.md          # 需求和产品决策主文档
│   │   └── ACCEPTANCE.md            # 管理员验收标准
│   ├── 0b-design/
│   │   ├── prototype/               # 原型版本根目录，使用 v1、v2、v3 自增长目录
│   │   │   └── v1/                  # 第 1 版原型；后续新原型使用 v2、v3 ...
│   │   └── DESIGN.md                # 设计规范
│   └── 0c-prompts/
│       ├── discover-requirements.md # 需求挖掘提示词模板
│       ├── plan-goals-from-requirements.md # 基于需求和设计拆分 Plan/Goal
│       ├── security-review.md       # 上线前安全审查提示词模板
│       └── write-design-md.md       # 生成 DESIGN.md 的提示词模板
├── 0b-goals/
│   ├── 0a-plans/                    # 执行计划，命名为 Plan-<YYYYMMDD>-PlanID<001>-<slug>.md
│   ├── 0b-current/                  # 当前 active Goal，默认只能有一个
│   └── 0c-archive/                  # 已完成关键 Goal 归档
├── 0c-workflow/
│   ├── WORKFLOW_V3.md               # V3 主流程
│   ├── BRANCHING.md                 # 分支和合并规范
│   ├── VERIFY.md                    # 本地验证规范
│   ├── RELEASE_CHECKLIST.md         # 上线前发布检查清单
│   ├── GOAL_TEMPLATE.md             # Goal 文档模板
│   ├── PLAN_TEMPLATE.md             # Plan 文档模板
│   └── project-profile.yml          # 项目类型和验证要求声明
├── 0d-scripts/
│   ├── check-workflow.sh            # V3 结构和命名轻量检查
│   ├── verify.sh                    # 本地验证总入口
│   ├── notify-admin.sh              # 管理员通知入口
│   └── nm-notify-feishu.sh          # 飞书通知底层脚本
├── .gitignore
├── .markdownlint.json
├── .markdownlintignore
├── .nm-template-state.json          # 模板版本和受管理文件哈希
├── AGENTS.md                        # Agent 英文极简硬规则
├── AGENTS.zh-CN.md                  # 管理员查看用中文规则
├── package.json
├── PROJECT_STRUCTURE.md
└── README.md
```
