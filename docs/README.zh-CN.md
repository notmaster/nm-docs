# nm-docs

[English](../README.md) | 中文

`nm-docs` 用于维护 NotMaster 的工作流模板、Agent skills 和确定性工具。

当前推荐使用 **NM V4**。V4 是一个轻量的 Spec 驱动工作流：

```text
SPEC（已确认）
-> ROADMAP（阶段表）
-> 每阶段一个全新 Agent 会话
-> 本地验证
-> staged 停等验收 或 auto 无人值守 runner
-> 合并 dev
```

## 推荐版本

新项目和工作流更新推荐使用 [template/v4](../template/v4)。

V4 的重点：

- 用单一 Spec 合约取代需求、验收、设计三份文档。
- 用单一运行时状态文件 `0b-goals/ROADMAP.md` 取代 Plan/Goal 双层。
- 每阶段一个全新会话、靠文件交接，避免长任务上下文退化。
- 两种执行模式：`staged` 每阶段停等管理员验收；`auto` 无人值守 runner，验证通过即合并 `dev`。
- Agent 中立规则（`AGENTS.md`）+ Claude Code / Grok 指针文件 + 各家启动配方。
- 本地确定性验证与飞书通知脚本。

## 快速开始

从本地仓库初始化新项目：

```bash
python3 tools/nm-v4/nm_v4.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

更新已有 Git 项目（包括 NM V3 项目）：

```bash
python3 tools/nm-v4/nm_v4.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

确认 dry-run 输出后，去掉 `--dry-run` 正式执行。

安装 V4 skill：

```bash
bash tools/nm-v4/install-skill.sh --target-dir "$HOME/.agents/skills"
```

安装后，在新的 Agent 线程中使用：

```text
Use $nm-init-project-v4 to initialize or update this project.
```

## 仓库结构

```text
template/v4/                  # 当前推荐的 NM V4 Spec 驱动工作流模板
skills/nm-init-project-v4/    # V4 初始化/更新的 Agent skill
tools/nm-v4/                  # V4 确定性工具
template/v3/                  # 上一代 V3 Goal 驱动工作流
skills/nm-init-project-v3/    # V3 skill，供存量项目使用
tools/nm-v3/                  # V3 确定性工具
template/v2/                  # 旧版 V2 协同工作流
template/v1/                  # V1 基础模板，仅保留作参考
docs/                         # 用户文档和国际化文档
```

## 验证

仓库检查：

```bash
npm install
npm run lm
python3 tools/nm-v4/nm_v4.py check --target template/v4 --source-dir .
python3 tools/nm-v3/nm_v3.py check --target template/v3 --source-dir .
```

生成的 V4 项目中运行：

```bash
npm install
npm run workflow:check
npm run verify
```

## 更多文档

- [模板版本](template-versions.zh-CN.md)
- [Skill and tool installation](installation.md)
- [V4 设计定稿决议](nm-v4-design-decisions.zh-CN.md)
- [V4 template README](../template/v4/README.md)
- [V4 manifest](../template/v4/manifest.json)
- [V3 template README](../template/v3/README.md)
