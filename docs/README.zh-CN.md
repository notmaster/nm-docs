# nm-docs

[English](../README.md) | 中文

`nm-docs` 用于维护 NotMaster 的工作流模板、Agent skills 和确定性工具。

NM **V5** 目前保留为**实验性试用工作流**，同时开始设计 V6。V5 未获准用于无人值守的高影响自动化：

```text
SPEC（已确认）
-> 运行时 INDEX + Task 卡（磁盘为真相）
-> runner + 短命编排会话 + Worker
-> staged（阶段验收）或 auto（硬停 / 授权 skip）
-> 按工作单元生成 candidate；由管理员控制合并到 dev
```

## 当前工作流状态

- **V6**：尚未开始实现。待评审的实现 Spec 见
  [nm-v6-workflow-spec.md](nm-v6-workflow-spec.md)，完整中文管理员对照见
  [nm-v6-workflow-spec.zh-CN.md](nm-v6-workflow-spec.zh-CN.md)。
- **V5**：仅限实验性试用。当前 runner 不得用于无人值守合并、发布、部署，也不得接触生产凭据或生产数据。
- **V4 及更早版本**：仅供存量项目和历史参考继续保留。

V5 曾探索：

- 磁盘状态机：瘦索引 `0b-runtime/INDEX.yaml` + 每任务卡。
- 混合编排试验：runner、短命编排会话、带最小上下文包的 Worker。
- 两种模式：`staged` / `auto`；未指定则强制选择；恢复时可切换并提示冲突。
- 自修默认 **10** 轮；仅显式 `skip_on_fail` 可在 auto 下跳过。
- 事件化通知（可插拔渠道，首期飞书）。
- **Agent 文档英文**；管理员中文对照；设计决议 v1 保存在模板内。
- CLI + Skill 双入口。

设计决议（v1）：[RESOLUTION-V5-DESIGN-v1.md](../template/v5/0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md)  
中文对照：[RESOLUTION-V5-DESIGN-v1.zh-CN.md](../template/v5/0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.zh-CN.md)

## V5 试用命令

> V5 仅保留用于有人监督的实验和仓库维护；文档中的 `auto` 模式不构成高影响操作授权。

```bash
python3 tools/nm-v5/nm_v5.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

更新已有 Git 项目：

```bash
python3 tools/nm-v5/nm_v5.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

安装 V5 skill：

```bash
bash tools/nm-v5/install-skill.sh --target-dir "$HOME/.agents/skills"
```

开放 skills 生态（可用时）：

```bash
npx skills add notmaster/nm-docs --skill nm-init-project-v5
```

安装后，在新的 Agent 线程中：

```text
Use $nm-init-project-v5 to initialize or update this project.
```

## 仓库结构

```text
template/v5/                  # 实验性 NM V5 试用模板
skills/nm-init-project-v5/    # V5 skill
tools/nm-v5/                  # V5 工具
template/v4/ … template/v1/   # 历史版本保留
docs/                         # 用户文档与翻译
```

## 验证

```bash
npm install
npm run lm
python3 tools/nm-v5/nm_v5.py check --target template/v5 --source-dir .
```

生成的 V5 项目内：

```bash
npm install
npm run workflow:check
npm run verify
```

## 更多文档

- [模板版本说明](template-versions.md) / [中文](template-versions.zh-CN.md)
- [V6 工作流实现 Spec（英文执行源）](nm-v6-workflow-spec.md)
- [V6 工作流 Spec（中文管理员对照）](nm-v6-workflow-spec.zh-CN.md)
- [安装说明（英文）](installation.md) / [中文](installation.zh-CN.md)
- [V4 设计决策（中文）](nm-v4-design-decisions.zh-CN.md)
