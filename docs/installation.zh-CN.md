# 安装

[English](installation.md) | 中文

## 推荐的 V3.1 工作流

从受信本地 checkout 安装 V3.1 Skill：

```bash
python3 tools/nm-v3/nm_v3.py install-skill \
  --target-dir "$HOME/.agents/skills" \
  --source-dir .
```

安装器会捆绑精确的 V3 工具，并记录模板版本、SHA-256、来源 commit 和来源 dirty
状态。安装后的 wrapper 每次运行都校验该绑定，绝不从可变分支下载未经检查的可执行
文件。采用经过审阅的更新时需要重新安装 Skill。

初始化并校验新项目：

```bash
python3 tools/nm-v3/nm_v3.py init \
  --target /absolute/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
cd /absolute/project
npm install
npm run workflow:check
npm run verify
```

已有项目先使用 `status`，再执行 `update --dry-run`；V3 3.0 项目使用
`migrate --dry-run`。工具要求工作区干净并精确位于 `origin/dev` 基线，创建允许的
任务分支，校验暂存结果，并在文件事务中断时回滚。远程模板 ref 会在读取文件前解析
为一个不可变 commit。

正式发布的 V3.1 源码应具有不可变发布标签 `v3.1.0`。创建或推送该标签仍属于需要
单独授权的发布操作。

## 管理员已接受但非推荐的 V6 实现

V6 需要 Python 3.11 或更高版本。有效的 `tools/nm-v6/administrator-acceptance.json` 记录所绑定的精确源码快照，在完成独立证据审阅后已获管理员接受。源码漂移后该状态会失败关闭；V6 仍为 `recommended=false`、`production_ready=false`。安装 Skill 或通过检查不会确认项目 Spec、签署批准，也不会授权受保护或外部变更。

从受信本地 checkout 安装薄 Skill：

```bash
bash tools/nm-v6/install-skill.sh --target-dir "$HOME/.agents/skills"
```

安装到 Codex 专用目录：

```bash
bash tools/nm-v6/install-skill.sh --target-dir "$HOME/.codex/skills"
```

安装过程会以 mode-0600 记录精确的已审查 checkout 及其 V6 可执行源码绑定。之后如设置 `NM_DOCS_DIR`，它必须指向同一 checkout：

```bash
export NM_DOCS_DIR=/absolute/path/to/nm-docs
```

V6 Skill 绝不下载未经校验的可执行文件，也不会从当前目录搜索可执行文件。它以 Python 隔离模式运行；绑定源码摘要变化、checkout 移动或缺少 Python 3.11+ 时都会失败关闭。使用新 core 前必须先审查 V6 源码更新并重新安装 Skill。
上游实现的接受状态不会转移到生成项目。每个项目必须独立确认自己的 Spec、通过自身门禁，并为受保护或外部影响提供有效且范围明确的 grant。

## 初始化 V6

使用空目标目录：

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py init \
  --target /absolute/project \
  --project-name "My Project" \
  --package-name "my-project" \
  --source-dir .
```

初始化会在目标外渲染和验证，在允许的任务分支上创建 bootstrap commit，创建名称不同的 `main` 与 `dev` ref，并留下干净工作树。它不会直接在受保护分支上创建实现 commit。

## 更新 V6

先预览：

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py update \
  --target /absolute/project \
  --source-dir . \
  --dry-run
```

更新要求：

- 目标是干净的 Git 仓库根目录；
- `git fetch --prune origin dev` 成功；
- 本地 `dev` 存在时必须等于 fetch 后的远端跟踪版本；
- 允许的新任务分支从该精确版本开始；
- 所有输出在应用前完成 staging 与验证；
- 项目拥有的 create-only 内容和已修改的 managed 指导被保留或报告冲突；
- 中断事务可以确定性 resume 或 abort。

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py update --target /absolute/project --source-dir . --resume
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py update --target /absolute/project --source-dir . --abort
```

## 验证 V6

仓库：

```bash
npm run lm
npm run v6:check
npm run v6:test
npm run skill:v6:check
```

生成项目：

```bash
npm install
npm run workflow:check
npm run workflow:test
npm run verify
```

## 受信控制面与 secret

CLI 可以创建 confirmation 和 authorization request。独立的管理员控制 signer 生成记录，核心使用配置公钥验证。私有签名能力与 secret 值必须位于仓库、Worker workspace、Agent 上下文、命令行、日志、证据和通知之外。

## 为有人监督试用保留 V5

V5 继续供已有监督实验使用：

```bash
bash tools/nm-v5/install-skill.sh --target-dir "$HOME/.agents/skills"
python3 tools/nm-v5/nm_v5.py init --target /absolute/project --source-dir .
python3 tools/nm-v5/nm_v5.py update --target /absolute/project --source-dir . --dry-run
```

V5 仍是实验性版本。其 `auto` 模式、runner、通知成功和检查不授权无人值守合并、发布、部署、生产凭据或生产数据。V6 绝不恢复 V5 的可变 INDEX/Task-card 运行时。

## 仓库飞书通知

长时间运行的 `nm-docs` 维护使用仓库现有双通道飞书 adapter 和机器本地配置：

```text
~/.config/nm-docs/nm-notify-feishu.env
```

参见[仓库工作通知](repository-notifications.zh-CN.md)。根 adapter 只汇报仓库任务进度；它不是 V6 运行时持久 outbox，也不是授权通道。

## 早期版本

V4 安装工具继续供已有项目使用：

```bash
bash tools/nm-v4/install-skill.sh --target-dir "$HOME/.agents/skills"
```
