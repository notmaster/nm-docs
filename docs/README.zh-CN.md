# nm-docs

[English](../README.md) | 中文

`nm-docs` 维护用于 AI 辅助项目交付的 NotMaster 工作流模板、Skills 和确定性工具。

## 当前工作流状态

- **V7**：rev9 决议清单已基本定稿，但管理员侧的任务与控制流程对于本仓库的“简单工作流”目标仍然过于复杂。因此 V7 暂时封存；该清单不授权任何实施工作，除非管理员明确重新启动，否则不进入实施阶段。本仓库尚无 V7 实现、模板、工具、已接受快照或活动控制器；V7 继续保持 `experimental=true`、`recommended=false`、`production_ready=false`。
- **V6**：有效的 `tools/nm-v6/administrator-acceptance.json` 记录所标识的精确源码快照，在完成独立证据审阅后已获管理员接受。接受状态不能转移到已修改或未被记录的快照。V6 仍为 `recommended=false`、`production_ready=false`。
- **V5**：继续保留为有人监督的实验性试用工作流。其 runner 与检查不授权、也不能独立证明无人值守合并、发布、部署、生产访问或生产就绪性。
- **V4 及更早版本**：为存量项目和历史参考继续保留。

V6 使用单一 SQLite 运行时权威、确定性 reducer 与 gate engine、带签名的受信控制面记录、独立 candidate workspace、Codex/GrokBuild/Claude 薄 adapter、内容寻址的脱敏证据、受保护 Git 集成、可恢复交付 action、审计链和持久通知 outbox。Staged 与 auto 模式共用同一状态图和技术门禁。

V6 不导入或恢复 V5 的可变 `INDEX.yaml` 或 Task-card 运行时。
仓库级接受只覆盖记录所绑定的 V6 实现快照。每个生成项目仍须定义并确认自己的 Spec、通过自身门禁，并在执行受保护或外部影响前提供有效且范围明确的 grant。

## V6 仓库命令

V6 核心需要 Python 3.11 或更高版本。仓库 wrapper 会查找符合要求的运行时，也可使用 `NM_V6_PYTHON` 指定。

```bash
npm run lm
npm run v6:check
npm run v6:test
npm run skill:v6:check
```

从当前 checkout 初始化一次性或新项目：

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

预览安全的已有项目更新：

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

Updater 要求目标是干净 Git 根目录、fetch 成功、精确匹配远端跟踪 `dev`、创建允许的新分支、在目标外 staging、应用前验证，并在注入或真实失败后支持确定性 resume 或 abort。

从当前 checkout 安装薄 Skill：

```bash
bash tools/nm-v6/install-skill.sh --target-dir "$HOME/.agents/skills"
```

安装器会将 Skill 绑定到已审查 checkout 及其 V6 可执行源码。审查 core 更新后需重新安装；摘要漂移会失败关闭。

## 生成的 V6 项目

在生成项目内：

```bash
npm install
npm run workflow:check
npm run workflow:test
npm run verify
```

这些命令产生技术证据；它们不会确认项目 Spec、签署批准、授予受保护或外部权限，也不会把上游仓库快照的管理员接受状态转移到生成项目。

## 仓库结构

```text
template/v6/                  # 自包含 V6 实现
tools/nm-v6/                  # 确定性 CLI/core、schema 与验收测试
skills/nm-init-project-v6/    # 委托同一 CLI 的薄 Agent 入口
template/v5/                  # 实验性 V5 试用工作流
skills/nm-init-project-v5/    # V5 维护 Skill
tools/nm-v5/                  # V5 维护工具
template/v4/ … template/v1/  # 保留的早期版本
docs/                         # 用户文档与管理员镜像
```

## 文档

- [V7 工作流决议清单（英文执行源）](nm-v7-workflow-decisions.md) / [中文管理员镜像](nm-v7-workflow-decisions.zh-CN.md)
- [V6 规范工作流 Spec（英文执行源）](nm-v6-workflow-spec.md) / [中文管理员镜像](nm-v6-workflow-spec.zh-CN.md)
- [V6 实现追踪报告（英文）](nm-v6-implementation-traceability.md)
- [模板版本（英文）](template-versions.md) / [中文](template-versions.zh-CN.md)
- [安装说明（英文）](installation.md) / [中文](installation.zh-CN.md)
- [仓库工作通知（英文）](repository-notifications.md) / [中文](repository-notifications.zh-CN.md)
- [V6 模板工作流（英文）](../template/v6/0c-workflow/WORKFLOW_V6.md) / [中文](../template/v6/0c-workflow/WORKFLOW_V6.zh-CN.md)
