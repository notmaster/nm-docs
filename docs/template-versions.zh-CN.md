# 模板版本

## 推荐：V4

新项目和工作流更新请使用 `template/v4`。

V4 是 Spec 驱动工作流，运行状态收敛在两份文件中：

- `0a-docs/0a-spec/SPEC-<slug>-V<n>.md`：管理员拥有的 Spec 合约
  （需求、决策、阶段、验收），顶部为 YAML frontmatter。
- `0b-goals/ROADMAP.md`：唯一运行时状态文件（阶段表、进度、交接备注、待人工验收清单）。

每个阶段在全新 Agent 会话中执行。执行模式有 `staged`（每阶段停等管理员验收）
和 `auto`（无人值守 runner `0d-scripts/run-goals.py`，支持 Claude Code、Codex、Grok）。

使用 `skills/nm-init-project-v4` 或 `tools/nm-v4/nm_v4.py` 初始化和更新项目。
`update` 命令同时支持 V3 项目迁移：被取代的 V3 框架文件移入
`.delete-pending/v3-superseded/`，旧需求文档原位保留作为 Spec 输入素材。

## 上一代：V3

`template/v3` 是 Goal 驱动工作流，使用 `REQUIREMENTS.md`、`ACCEPTANCE.md`、
`DESIGN.md` 和 `0b-goals/` 下的 Plan/Goal 文件。

尚未迁移的存量项目可以继续使用 V3；新项目请优先使用 V4。
使用 `skills/nm-init-project-v3` 或 `tools/nm-v3/nm_v3.py`。

## 旧版：V2

`template/v2` 包含较早的多 Agent 协同工作流，使用 TODO 文件、PR review gate 和更重的编排规则。

如果已有项目依赖 V2，可以继续保留。

## 遗留：V1

`template/v1` 包含旧版基础模板，这些文件此前位于 `template/temp-*`。

V1 仅为兼容和参考而保留，目前几乎不再用于当前工作；除非已有项目明确依赖 V1，新项目请优先使用 V4。
