# 模板版本说明

## 设计中：V6

V6 尚未实现。待评审的实现契约为 `docs/nm-v6-workflow-spec.md`。管理员确认该 Spec 并授权实现前，不得创建 `template/v6`。

## 实验性：V5

`template/v5` 仅保留用于有人监督的试用和仓库维护，不得用于无人值守合并、发布、部署，也不得接触生产凭据或生产数据。

V5 为混合编排工作流：磁盘 INDEX + Task 卡、runner/编排/Worker、staged/auto、自修 10、事件通知、CLI+Skill、Agent 英文文档 + 中文对照。

设计决议 v1：`template/v5/0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md`。

工具：`skills/nm-init-project-v5` 或 `tools/nm-v5/nm_v5.py`。

## 上一代：V4

`template/v4`：Spec + ROADMAP，每阶段新会话。存量项目可继续使用。不得仅因 V5 的版本号更高而把新项目迁移到 V5。

## 更早：V3 / V2 / V1

分别保留 Goal 驱动、多 Agent 协同与遗留基础模板。除非明确要求，不删除旧版本。
