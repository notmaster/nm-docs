# nm-docs

[English](../README.md) | 中文

`nm-docs` 维护用于 AI 辅助项目交付的 NotMaster 工作流模板、Skills 和确定性工具。

## 推荐工作流：NM V3.1

**NM V3.1（`3.1.0`）是新项目的推荐工作流。** 它通过少量可读文件保持项目控制，同时支持快速修改和多 Goal 计划开发，不要求重量级运行时。

推荐 V3.1 的主要原因：

- 可选的 `0a-docs/spec.md`，统一记录需求与验收标准；
- `AGENTS.md` 中由项目维护的参考文档白名单，只有项目启用后，Agent 才读取可选的设计、原型或 Spec 文档；
- 小修改使用独立 Goal，大型工作使用 Plan 到 Goals 的两条路径；
- Goal 文件自包含，可以直接交给实现 Agent；
- 每个 Goal 串行独立测试和自审，Plan 全部 Goal 集成后再执行一次全量验证；
- 基于精确 Git SHA 的受保护分支规则，以及 Plan 和 Goal 分支；
- 严格区分飞书进度与重要通知通道，最终完成通过重要通知显式交接；
- 事务化的初始化、更新、迁移、状态、校验、精确工具 Skill 安装和幂等完成命令。

“推荐”只表示默认工作流选择；它不授权更新受保护分支、推送、发布、部署、生产访问或其他外部影响。

## V3.1 工作流

选择能够覆盖任务的最小路径：

```text
小型需求
  -> 独立 Goal
  -> Goal 实现、测试和自审
  -> 管理员决定是否集成

计划型工作
  -> 可选 spec.md
  -> Plan
  -> 按需创建自包含 Goals
  -> 每个 Goal：implemented -> verified -> integrated
  -> 一次项目全量验证
  -> 管理员审核 Plan
```

实现 Agent 默认自行编写测试并自审。只有管理员在执行前要求独立 Reviewer 时，才在 Goal 中设置 `independent_reviewer_required: true`。

## 开始一个项目

从当前 checkout 初始化新项目：

```bash
python3 tools/nm-v3/nm_v3.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

然后校验生成的项目：

```bash
cd /absolute/path/to/project
npm install
npm run workflow:check
npm run verify
```

对于已有 V3 项目，先查看状态并预览更新，再实际写入：

```bash
python3 tools/nm-v3/nm_v3.py status --target /absolute/path/to/project
python3 tools/nm-v3/nm_v3.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

如果要转换仍然使用独立 Requirements 和 Acceptance 文档的 V3 3.0 项目，应使用 `migrate --dry-run` 代替 `update --dry-run`。Updater 和 migrator 要求 Git 仓库干净并位于当前远端 `dev` 基线，且必须在修改文件前创建允许的任务分支。

为本地 Agent 安装 V3 Skill：

```bash
python3 tools/nm-v3/nm_v3.py install-skill \
  --target-dir "$HOME/.agents/skills"
```

## 在生成项目中工作

- 首先读取 `AGENTS.md`；其中的项目自有区块决定该项目启用了哪些可选文档。
- 小修改或后期修改从 `0c-workflow/GOAL_TEMPLATE.md` 创建一个独立 Goal；除非管理员要求，否则不需要 Spec。
- 较大工作可以先创建 `0a-docs/spec.md`，再从 `0c-workflow/PLAN_TEMPLATE.md` 创建 Plan，并按需创建 Goals。
- 每个 Goal 都应是完整执行包，包含所需上下文、TODO、验收标准、命令和执行记录。
- Goal 进入 `verified -> integrated` 前运行自身测试；Plan 的全部 Goal 集成后，只运行一次项目全量验证。
- 对受保护分支执行集成或推送前，等待管理员明确指令。

## 仓库 V3 命令

修改 V3 模板、工具或 Skill 后必须通过：

```bash
npm run lm
npm run v3:check
npm run v3:test
npm run skill:v3:check
```

## 其他工作流版本

- **V6**：有效记录所绑定的精确源码快照已在独立证据审阅后获管理员接受，但 V6 仍为 `recommended=false`、`production_ready=false`。
- **V5**：继续保留为有人监督的实验性试用工作流，不属于推荐版本。
- **V7**：设计工作已封存，没有实现、模板、工具、已接受快照或活动控制器。
- **V1、V2 和 V4**：为兼容、存量项目和历史参考继续保留。

其他版本的接受或验证状态不代表它是推荐工作流，也不会向生成项目转移权限。

## 仓库结构

```text
template/v3/                  # 推荐的自包含 V3.1 模板
tools/nm-v3/                  # 确定性 V3.1 CLI 与测试
skills/nm-init-project-v3/    # V3.1 Agent 入口与参考文档
template/v6/                  # 管理员已接受且记录绑定的 V6 快照
template/v5/                  # 实验性 V5 试用工作流
template/v4/ … template/v1/  # 保留的早期版本
docs/                         # 用户文档与中文镜像
```

## 文档

- [NM V3.1 升级说明（英文）](nm-v3-3.1-upgrade.md) / [中文](nm-v3-3.1-upgrade.zh-CN.md)
- [V3.1 生命周期（英文）](../skills/nm-init-project-v3/references/v3-lifecycle.md)
- [V3.1 生成项目工作流（英文）](../template/v3/0c-workflow/WORKFLOW_V3.md)
- [模板版本（英文）](template-versions.md) / [中文](template-versions.zh-CN.md)
- [安装说明（英文）](installation.md) / [中文](installation.zh-CN.md)
- [仓库工作通知（英文）](repository-notifications.md) / [中文](repository-notifications.zh-CN.md)
- [V6 规范工作流 Spec（英文执行源）](nm-v6-workflow-spec.md) / [中文管理员镜像](nm-v6-workflow-spec.zh-CN.md)
