# 模板版本

## 推荐：V3

新项目和工作流更新请使用 `template/v3`。

V3 是 Goal 驱动工作流，会把持久项目事实保存在以下文件中：

- `0a-docs/0a-product/REQUIREMENTS.md`
- `0a-docs/0a-product/ACCEPTANCE.md`
- `0a-docs/0b-design/DESIGN.md`
- `0b-goals/0a-plans/`
- `0b-goals/0b-current/`
- `0b-goals/0c-archive/`

使用 `skills/nm-init-project-v3` 或 `tools/nm-v3/nm_v3.py` 初始化和更新项目。

## 旧版：V2

`template/v2` 包含较早的多 Agent 协同工作流，使用 TODO 文件、PR review gate 和更重的编排规则。

如果已有项目依赖 V2，可以继续保留。新项目默认优先使用 V3，除非项目明确需要 V2 的多 Agent PR 工作流。

## 遗留：V1

`template/v1` 包含旧版基础模板，这些文件此前位于 `template/temp-*`。

V1 仅为兼容和参考而保留，目前几乎不再用于当前工作；除非已有项目明确依赖 V1，新项目请优先使用 V3。
