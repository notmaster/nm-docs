# nm-docs

[English](../README.md) | 中文

`nm-docs` 用于维护 NotMaster 的工作流模板、Agent skills 和确定性工具。

当前推荐使用 **NM V5**。V5 是混合编排的 Spec 驱动工作流：

```text
SPEC（已确认）
-> 运行时 INDEX + Task 卡（磁盘为真相）
-> runner + 短命编排会话 + Worker
-> staged（阶段验收）或 auto（硬停 / 授权 skip）
-> 按工作单元合并到 dev
```

## 推荐版本

新项目和工作流更新推荐使用 [template/v5](../template/v5)。

V5 的重点：

- 磁盘状态机：瘦索引 `0b-runtime/INDEX.yaml` + 每任务卡。
- 混合编排：确定性 runner、短命编排会话、带最小上下文包的 Worker。
- 两种模式：`staged` / `auto`；未指定则强制选择；恢复时可切换并提示冲突。
- 自修默认 **10** 轮；仅显式 `skip_on_fail` 可在 auto 下跳过。
- 事件化通知（可插拔渠道，首期飞书）。
- **Agent 文档英文**；管理员中文对照；设计决议 v1 保存在模板内。
- CLI + Skill 双入口。

设计决议（v1）：[RESOLUTION-V5-DESIGN-v1.md](../template/v5/0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md)  
中文对照：[RESOLUTION-V5-DESIGN-v1.zh-CN.md](../template/v5/0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.zh-CN.md)

## 快速开始

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
template/v5/                  # 当前推荐的 NM V5 模板
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
- [安装说明](installation.md)
- [V4 设计决策（中文）](nm-v4-design-decisions.zh-CN.md)
