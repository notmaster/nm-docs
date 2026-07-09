# 安装说明

[English](installation.md) | 中文

## 安装实验性 V5 Skill

> V5 仅保留用于受监督试用和维护。安装 Skill 不代表已授权无人值守合并、发布、部署，也不允许访问生产凭据或生产数据。Skill、runner、`workflow:check` 或 `verify` 成功只是一项诊断信号，不是独立验收证据。

默认目标目录：

```text
~/.agents/skills
```

从本仓库安装：

```bash
bash tools/nm-v5/install-skill.sh --target-dir "$HOME/.agents/skills"
```

安装到 Codex 专用 Skill 目录：

```bash
bash tools/nm-v5/install-skill.sh --target-dir "$HOME/.codex/skills"
```

开放 skills 生态可用时：

```bash
npx skills add notmaster/nm-docs --skill nm-init-project-v5
```

安装完成后，启动新的 Agent 线程并调用：

```text
Use $nm-init-project-v5 to initialize or update this project.
```

## 不通过 Skill 使用 V5 工具

```bash
python3 tools/nm-v5/nm_v5.py init --target /absolute/project --source-dir .
python3 tools/nm-v5/nm_v5.py update --target /absolute/project --source-dir . --dry-run
python3 tools/nm-v5/nm_v5.py update --target /absolute/project --source-dir .
python3 tools/nm-v5/nm_v5.py check --target /absolute/project --source-dir .
python3 tools/nm-v5/nm_v5.py status --target /absolute/project
python3 tools/nm-v5/nm_v5.py notify-test --target /absolute/project
```

## V5 更新安全规则

`update` 要求：

- 目标是 Git 仓库根目录；
- 工作树保持干净，除非使用 `--allow-dirty`；
- 能够创建新分支。

默认更新分支：

```text
chore/sync-nm-workflow-v5-YYYYMMDD
```

工具只覆盖 `managed` 框架文件；`create-only` 项目内容（例如 `README.md`、`0b-runtime/INDEX.yaml` 和 `DECISIONS.md`）会被保留。

## V4 对应命令

```bash
bash tools/nm-v4/install-skill.sh --target-dir "$HOME/.agents/skills"
python3 tools/nm-v4/nm_v4.py init --target /absolute/project --source-dir .
python3 tools/nm-v4/nm_v4.py update --target /absolute/project --source-dir . --dry-run
```

## V3 对应命令

```bash
bash tools/nm-v3/install-skill.sh --target-dir "$HOME/.agents/skills"
python3 tools/nm-v3/nm_v3.py init --target /absolute/project --source-dir .
python3 tools/nm-v3/nm_v3.py update --target /absolute/project --source-dir . --dry-run
```
