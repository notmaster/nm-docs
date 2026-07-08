# nm-docs

[English](../README.md) | 中文

`nm-docs` 用于维护 NotMaster 的工作流模板、Agent skills 和确定性工具。

当前推荐使用 **NM V3**。V3 是一个轻量的 Goal 驱动工作流：

```text
REQUIREMENTS.md
-> ACCEPTANCE.md
-> DESIGN.md
-> Plan
-> Goal
-> 本地验证
-> 管理员验收
-> 合并
```

## 推荐版本

新项目和工作流更新推荐使用 [template/v3](../template/v3)。

V3 的重点：

- 管理员负责需求、验收标准和设计文档。
- 使用 Plan 和 Goal 控制 `/goal` 执行。
- 0 到 1 阶段主要依赖本地确定性验证，不强制重 CI/CD。
- 通过飞书通知脚本处理管理员决策提醒。
- 提供需求挖掘、DESIGN.md、Plan/Goal 拆分、安全审查等提示词模板。
- 使用精简的 `AGENTS.md` 作为 Agent 执行规则。

## 快速开始

从本地仓库初始化新项目：

```bash
python3 tools/nm-v3/nm_v3.py init \
  --target /absolute/path/to/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

更新已有 Git 项目：

```bash
python3 tools/nm-v3/nm_v3.py update \
  --target /absolute/path/to/project \
  --source-dir . \
  --dry-run
```

确认 dry-run 输出后，去掉 `--dry-run` 正式执行。

安装 V3 skill：

```bash
bash tools/nm-v3/install-skill.sh --target-dir "$HOME/.agents/skills"
```

安装后，在新的 Agent 线程中使用：

```text
Use $nm-init-project-v3 to initialize or update this project.
```

## 仓库结构

```text
template/v3/                 # 当前推荐的 NM V3 工作流模板
skills/nm-init-project-v3/    # V3 初始化/更新的 Agent skill
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
python3 tools/nm-v3/nm_v3.py check --target template/v3 --source-dir .
```

生成的 V3 项目中运行：

```bash
npm install
npm run workflow:check
npm run verify
```

## 更多文档

- [模板版本](template-versions.zh-CN.md)
- [Skill and tool installation](installation.md)
- [V3 template README](../template/v3/README.md)
- [V3 manifest](../template/v3/manifest.json)
