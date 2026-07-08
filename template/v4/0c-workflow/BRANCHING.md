# Branching

## 分支职责

- `main`：稳定发布分支。
- `dev`：开发集成分支。
- `feature/*`：新功能。
- `fix/*`：普通 bug 修复。
- `docs/*`：文档变更。
- `refactor/*`：重构。
- `chore/*`：工程配置、依赖、脚本等。
- `hotfix/*`：生产紧急修复。

## 常规开发

1. 从最新 `dev` 新建任务分支。
2. 执行 ROADMAP 中的当前阶段。
3. 运行本地验证。
4. push 当前任务分支做备份。
5. `staged` 模式停等管理员验收；验收通过后合并回 `dev` 并同步远端。
6. `auto` 模式验证通过后直接合并回 `dev` 并同步远端。
7. 合并完成后按"分支清理"规则评估是否删除短期任务分支。

常规开发不得直接从 `main` 新建分支，`hotfix/*` 除外。
ROADMAP 的创建与状态更新属于工作流簿记，允许直接提交到 `dev`。

## 自动合并

`staged` 模式默认禁止自动合并。只有管理员明确授权，或当前执行模式为 `auto`
（Spec frontmatter 或启动指令声明）时才允许自动合并：

```yaml
execution_mode: auto
```

自动合并仍必须满足：

- 本地验证通过。
- 当前任务分支已 push。
- 没有未解决的阻塞或安全问题。

## 合并策略

如果管理员指定合并方式，按管理员要求执行。

如果管理员未指定，Agent 可按项目情况选择：

- `squash merge`：适合功能型阶段、提交较碎、希望历史干净的任务。
- `merge --no-ff`：适合需要保留完整开发过程、多人协作或审计价值高的任务。

Agent 在合并说明中必须说明选择的合并方式。

## 分支清理

分支合并后必须评估是否清理该分支。清理只适用于已经合并且不再承担发布、灰度、回滚、review 或验收职责的短期任务分支，例如已完成的 `feature/*`、`fix/*`、`docs/*`、`refactor/*`、`chore/*`。

删除前必须满足：

- 当前工作区干净，没有未提交变更、未完成 merge、rebase 或 cherry-pick。
- 已用 `git merge-base --is-ancestor <branch> dev` 确认该分支已合并到 `dev`。
- 如果分支曾直接面向稳定发布、hotfix 同步或 main 侧验收，必要时再用 `git merge-base --is-ancestor <branch> main` 确认已合并到 `main`。
- 分支不再承担发布、灰度、回滚、review 或验收职责。
- 删除前向管理员报告删除依据，包括已合并判定、分支职责判断、本地/远端存在情况和将执行的命令。

不得自动删除：

- `main`
- `dev`
- `release/*`
- `hotfix/*`
- 未合并分支
- 仍在 review、验收、灰度、发布或回滚职责中的分支

本地短期分支确认可删除时，使用：

```bash
git branch -d <branch>
```

远端同名短期分支存在且确认可删除时，使用：

```bash
git push origin --delete <branch>
```

恢复方式：

- 已知提交时，用 `git branch <branch> <commit>` 恢复分支名。
- 未合并分支误删时，优先通过 `git reflog` 查找原提交，再用 `git branch <branch> <commit>` 恢复。

## Hotfix

1. 从最新 `main` 新建 `hotfix/*`。
2. 修复并执行本地验证。
3. 管理员验收后合并回 `main`。
4. 将修复同步回 `dev`。

`hotfix/*` 只用于生产紧急修复，不用于普通 bugfix。
