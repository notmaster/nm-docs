# 提示词：明确授权合并稳定分支

本模板是 `main` / `master` 合并的独立人工授权。只有生产验收和发布前置条件完成后才能使用。

```text
我明确授权当前 Hotfix/发布 PR 在以下条件全部满足后合并到稳定分支。

输入：
- 项目根目录：<PROJECT_ROOT>
- 总 TODO：<TOTAL_TODO>
- TODO ID：<TODO_ID>
- 当前 TODO：<CURRENT_TODO>
- 稳定分支：<main | master>
- Hotfix/发布 PR：<PR_URL>
- 我实际验收的候选代码提交：<CANDIDATE_SHA>
- 生产或预发布验收摘要：<ACCEPTANCE_SUMMARY>
- 备份与恢复验证：<BACKUP_AND_RESTORE_STATUS>
- migration 状态：<MIGRATION_STATUS 或 NOT_APPLICABLE>
- 回滚方案：<ROLLBACK_PLAN>
- 飞书目标：<FEISHU_TARGET 或 NONE>

执行要求：
1. 先核对 PR 目标确为指定稳定分支、候选 SHA、最终 PR HEAD、CI、Reviewer、人工验收、备份恢复、migration、回滚和未解决评论。
2. 如果候选 SHA 后运行时代码、配置、依赖、迁移或数据处理发生变化，授权失效；停止并要求重新验收。
3. 重新执行稳定分支要求的最终门禁和核心发布前冒烟检查。
4. 只有全部前置条件通过时才允许按仓库约定合并稳定分支；任何条件缺失都必须停止并提供数字编号选项，不得带风险默认继续。
5. 合并后验证稳定分支提交，执行生产核心冒烟和监控检查。
6. 通过独立 PR 将 Hotfix 同步回 dev；如果 dev 已包含等价修复，提供代码事实证明并记录决定，不得静默跳过同步核查。
7. 更新总 TODO、当前 TODO、高风险记录、发布记录和项目锁。
8. 如果 FEISHU_TARGET 不是 NONE，使用 nm-notify-feishu 发送结果卡片；不得泄露 Webhook、签名密钥、完整请求体或授权值。

本授权只针对上面列出的 PR、稳定分支和候选代码事实，不授权其他 PR、后续提交或再次发布。

最终输出稳定分支合并提交、门禁与冒烟结果、dev 同步 PR/结论、高风险摘要和飞书投递结果。
```
