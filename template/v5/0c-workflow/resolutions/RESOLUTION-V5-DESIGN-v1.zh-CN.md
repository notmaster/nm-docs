---
doc: RESOLUTION-V5-DESIGN
version: v1
status: ratified
ratified: 2026-07-09
workflow: v5
language: zh-CN
source: RESOLUTION-V5-DESIGN-v1.md
---

# NM V5 设计决议（v1）

> 管理员对照译文。Agent 执行以英文源 `RESOLUTION-V5-DESIGN-v1.md` 为准。  
> 修订须升版（如 v2），禁止静默改写 v1 已批准意图。

## 1. 问题本质与真实目标

**问题**：Spec 定稿后，在上下文有限、可中断下可靠实现设计；管理员只在必要时介入。

**结果**：可恢复的 staged/auto 闭环；磁盘状态可审计；通知可分级可扩展；CLI+Skill 可安装管理；上下文可控。

### 成功标准（摘要）

- 定稿 Spec 可校验并驱动 Phase → Task
- staged：Phase 门禁确认后合入并进入下一 Phase
- auto：无硬停则连续推进；显式可跳过项按规则处理
- 中断只靠磁盘状态恢复
- Worker 任务验收 + 自修 ≤10；Phase 全量 verify
- 通知事件可配置渠道；首期飞书
- CLI 为真源；Skill 薄入口；文档 EN 源 + 中文对照

## 2. 硬约束（摘要）

| 领域 | 规则 |
| --- | --- |
| 交付 | 模板 + 规则 + 契约 + 确定性 CLI/runner |
| 编排 | runner + 短命编排会话 + Worker |
| 真相源 | 瘦索引 + 每 Task 卡 |
| 语言 | Agent 文档英文；管理员中文对照；同步更新 |
| 模式 | 未指定则必选；恢复可切换；冲突先说明 |
| 停机 | 硬风险、验收门、Spec 冲突 → attention；自修 10 轮；仅 `skip_on_fail: true` 可跳过 |
| Git | 除 hotfix 外不从 main 拉日常分支；基线 dev；不直改 dev；合回再下一步 |
| 删除 | 仅移入 `.delete-pending/` |

## 3. 已批准决议编号

`1b 2c 3b 4b 5d 6c 7a 8b 9c 10c 11b 12c 13c` 及语言/自修 10/模式/Git/删除策略（全文见英文源 §3）。

## 4. 范围

**做**：V5 模板与工具、状态契约、通知抽象+飞书、Skill、本决议文档。  
**不做**：非飞书生产实现、绑死单一 CLI 多 Agent API、DB 状态、完整 i18n 引擎。

## 5. 方案要点

磁盘状态机；混合编排与最小上下文打包；staged/auto；失败与 skip 规则；事件通知；CLI+Skill；Git/删除纪律；EN 源 + ZH 对照。

## 6–7. 风险与验收

见英文源对应章节。本中文版不单独扩写，避免双源漂移。

## 8. 文档控制

| 字段 | 值 |
| --- | --- |
| 版本 | **v1** |
| 状态 | 已批准 2026-07-09 |
| 英文源 | `RESOLUTION-V5-DESIGN-v1.md` |
