# 提示词：验收通过并授权合并 dev

只有实际测试指定候选代码提交通过后才能使用本模板。

```text
我已完成人工验收，并授权当前 Bugfix 在满足全部条件后合并到 dev。

输入：
- 项目根目录：<PROJECT_ROOT>
- 总 TODO：<TOTAL_TODO>
- TODO ID：<TODO_ID>
- 当前 TODO：<CURRENT_TODO>
- 任务分支：<TASK_BRANCH>
- PR：<PR_URL>
- 我实际验收的候选代码提交：<CANDIDATE_SHA>
- 测试环境：<TEST_ENVIRONMENT>
- 人工验收结果：<ACCEPTANCE_SUMMARY>
- 飞书目标：<FEISHU_TARGET 或 NONE>

授权边界：
1. 先核对 CANDIDATE_SHA 属于当前任务分支和 PR，并核对自该 SHA 之后的全部变更。
2. 只有 TODO、文档或测试结果记录变化时，可保留本次人工验收。若运行时代码、配置、依赖、迁移或数据处理逻辑发生变化，本次验收失效：生成新候选 SHA，切回 needs-human，等待我重新测试，不得合并。
3. 记录人工验收事实，并在总 TODO 高风险操作总表和人工验收表中按项目规则留痕。
4. 在最终 PR 代码事实上运行完整门禁：当前 TODO 专项测试、lint、typecheck、test、build、fm、lm、workflow:check，以及范围要求的集成测试或 E2E。
5. 创建独立只读 Reviewer 审查最终 PR HEAD。Reviewer 必须给出 approve、request changes、comment 或 needs-replan，不允许当前 Coder 自我批准。
6. 对明确由当前修改引入且不越界的问题可以在原分支修复；任何运行时代码变化都必须回到人工验收，不能沿用本次授权。
7. 只有人工验收仍有效、完整门禁全部通过、Reviewer approve、PR 无阻塞评论、TODO/高风险记录完整且不存在真实删除时，才允许 squash 合并 PR 到 dev。
8. 合并后更新总 TODO、当前 TODO、合并提交和项目锁，同步本地 dev；高风险修复按 TODO 执行合并后冒烟测试。
9. 如果 FEISHU_TARGET 不是 NONE，使用 nm-notify-feishu 发送绿色结果卡片；首次实际使用或投递失败时先 doctor，使用 list 核对目标。不得输出 Webhook、签名密钥、完整请求体或授权值。
10. 飞书投递失败不回滚已经成功的合并，但必须只报告目标名称、执行阶段和飞书错误信息。

本提示词明确授权满足条件后合并 dev，但不授权创建、合并或推送 main/master。任何稳定分支操作必须使用单独的稳定分支授权提示词。

如果最终门禁出现需要扩大范围、基线失败无法判断、根因变化、冲突或其他高风险，不要自行扩大修改或带风险合并；说明错误、原因、影响和建议，提供数字编号选项并等待我决定。

最终输出：
- 人工验收绑定的代码 SHA 是否仍有效
- 完整门禁结果
- Reviewer 结论
- PR 与 squash 合并提交
- TODO 和项目锁最终状态
- 高风险新增记录摘要
- 合并后冒烟结果（如适用）
- 飞书投递结果或安全的失败摘要
```
