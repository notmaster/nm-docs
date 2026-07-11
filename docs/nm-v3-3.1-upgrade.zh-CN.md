# NM V3.1 升级说明

[English](nm-v3-3.1-upgrade.md) | 中文

NM V3.1 简化了被保留的 V3 Goal 工作流，并成为新项目的推荐工作流。推荐状态不代表
生产就绪，不授予受保护操作或外部影响权限，也不采用 V5 Runner 或授权模型。

## 版本

- 工作流家族：V3
- 模板版本：`3.1.0`
- 状态 Schema：`2`
- 可直接迁移来源：`3.0.0`

生成项目在 `.nm-template-state.json` 中记录模板版本、来源 ref、可获得时的来源
commit 和 dirty 状态、准确渲染来源快照哈希、受管理文件哈希、时间，以及可选
spec 版本和正文哈希。使用
`nm_v3.py status` 查看。

## 主要变化

- 可选项目 spec 位于 `0a-docs/spec.md`；项目需求和验收标准写在同一文档。
- 最小模板不再强制 Requirements、Acceptance、Design、原型、发布、项目结构、
  决策或 project-profile 文档。
- `AGENTS.md` 包含项目自有参考白名单。可选文档未列出时，不得仅因其存在而读取。
- 小任务可以使用一个独立 Goal；计划任务使用 Plan 分支和按需创建的自包含 Goal。
- Goal 实现子 Agent 默认编写测试并自审。只有管理员在执行前明确要求，并在 Goal
  配置中启用时才使用独立 Reviewer。
- 每个 Goal 运行自身验证；所有 Goal 集成后统一运行一次全量项目验证。
- 受保护分支要求准确远端 SHA 检查和管理员对集成/push 的明确授权。
- 飞书 progress 与 attention 必须使用不同 Webhook，attention 禁止回退到 progress，
  最终完成始终通过 attention 显式提醒管理员。
- Spec 验收同时绑定版本与正文哈希；同版本正文变化不能 stamp。
- 更新、迁移和 Spec 创建使用经过校验且可回滚的文件事务；远程 ref 先解析为单一
  不可变 commit。
- 安装的 Skill 捆绑并校验精确 V3 工具，不下载可变 executable。
- Goal 串行执行，Plan/Goal 证据绑定 commit SHA。
- 最终完成使用幂等 `finish` 命令和持久投递记录。

## 迁移

始终先检查：

```bash
python3 tools/nm-v3/nm_v3.py status --target /project
python3 tools/nm-v3/nm_v3.py migrate --target /project --source-dir . --dry-run
```

显式迁移会从准确的 `origin/dev` 创建任务分支，把旧 Requirements 与 Acceptance
内容合并成 spec 草案，保留无标记旧 AGENTS 指导供管理员审阅，安装新的项目自有
规则区块，并把两个来源文档移入
`.delete-pending/v3-3.1.0-migration/`。管理员必须审阅迁移结果；迁移不会验收 spec，
也不会授权受保护或外部操作。

旧的 Design、发布、决策、结构、提示词或 project-profile 文件不会被静默删除。
只有仍有价值时才保留，并在 `AGENTS.md` 中列为有效参考。

## 验证

仓库中的 V3 变更必须通过：

```bash
npm run lm
npm run v3:check
npm run v3:test
npm run skill:v3:check
```

生成项目运行 `npm run workflow:check` 和完整 `npm run verify`。这些检查是技术证据，
不是管理员验收或授权。
