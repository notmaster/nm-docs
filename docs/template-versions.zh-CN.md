# 模板版本

[English](template-versions.md) | 中文

## 管理员已接受的实现：V6

`template/v6` 实现 `docs/nm-v6-workflow-spec.md` 中的合同。有效的 `tools/nm-v6/administrator-acceptance.json` 记录所绑定的精确源码快照，在完成独立证据审阅后已获管理员接受。源码漂移后该状态会失败关闭，也不能转移到其他快照。V6 仍为 `recommended=false`、`production_ready=false`。

V6 用单一事务性 SQLite 权威替代可变 Markdown/YAML 运行时模型，并提供确定性 reducer、独立门禁与证据、签名管理员控制记录、隔离 candidate、受保护 Git 集成、可恢复交付 Operation、审计链和持久 outbox。V6 需要 Python 3.11 或更高版本，不强制引入非标准运行时服务或 Python 依赖。

工具：

- `template/v6`
- `tools/nm-v6/nm_v6.py`
- `skills/nm-init-project-v6`

V6 有意不兼容 V5 运行时状态。它拒绝自动导入或恢复 V5 的 `0b-runtime/INDEX.yaml` 与 Task card。项目需求与长期决策只能通过显式、经过审阅的新 V6 Spec 转换。

仓库接受状态不代表生成项目的配置或交付已获接受。每个生成项目仍须具备自身已确认的 Spec、技术门禁和有效且范围明确的 grant。

## 实验性：V5

`template/v5` 继续保留用于有人监督的试用和仓库维护。它未获准用于无人值守合并、发布、部署、生产凭据或生产数据。

V5 是混合编排实验：

- `0a-docs/0a-spec/` 下的已确认 Spec
- `0b-runtime/INDEX.yaml` 与 Task card 作为运行时事实
- Runner、短命 orchestrator session 与最小上下文 Worker
- `staged` 和 `auto` 试验模式
- 事件通知以及 CLI/Skill 安装

工具：`skills/nm-init-project-v5` 与 `tools/nm-v5/nm_v5.py`。

## 早期版本：V4

`template/v4` 是此前采用 `ROADMAP.md` 与逐 Phase 新 session 的 Spec 驱动工作流。为已有项目保留；不得根据版本号或检查结果推断生产授权。

工具：`skills/nm-init-project-v4` 与 `tools/nm-v4/nm_v4.py`。

## 早期版本：V3

`template/v3` 是目标驱动工作流，包含 `REQUIREMENTS.md`、`ACCEPTANCE.md`、`DESIGN.md`，以及 `0b-goals/` 下的 Plan/Goal 文件。

工具：`skills/nm-init-project-v3` 与 `tools/nm-v3/nm_v3.py`。

## 早期版本：V2

`template/v2` 是更早的多 Agent 协作工作流，使用 TODO 文件、PR 评审门禁和较重的编排规则。

## 遗留版本：V1

`template/v1` 为兼容与历史参考继续保留。
