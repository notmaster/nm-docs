# 总 TODO 模板

```yaml
project:
  name: ""
  requirementDoc: ""
  baseBranch: "dev"
  stableBranch: "master"
  status: "planning"
roles:
  planner: ""
  supervisor: ""
  coder: ""
  reviewer: ""
  fixer: ""
currentLock:
  status: "idle"
  todo: null
  branch: null
  pr: null
  ownerRole: null
  ownerModel: null
  acquiredAt: null
  lastHeartbeatAt: null
  timeoutMinutes: 30
  lockReason: "无 active 编码 PR"
  nextAction: "领取下一个 todo-ready 任务"
```

## 项目信息

- 项目名称：
- 需求文档：
- 开发集成分支：`dev`
- 稳定分支：`master`

## 编排模式

- 当前模式：`人工编排 / Codex + Grok CLI` 或 `Grok 原生全自动`（见 `supervisor-start.md` / `supervisor-start-grok.md`）
- **Grok 原生全自动**：Reviewer `approve` 且门禁通过后 Supervisor 自动合并到 `dev`；敏感文件与高风险**不阻塞**合并。
- **高风险审计**：本文件「高风险操作总表」为管理员事后一眼审查的**唯一汇总入口**；只追加行，不重写历史。合并时将「管理员复审」标为 `待审查`。

## Agent 角色映射

| 角色       | 模型/Agent | 说明                       |
| ---------- | ---------- | -------------------------- |
| Planner    |            | 需求理解、方案和 TODO 拆分 |
| Supervisor |            | 锁、分支、PR 和状态调度    |
| Coder      |            | 编码和自测                 |
| Reviewer   |            | PR 审查                    |
| Fixer      |            | 修复审查意见               |

## 当前项目锁

```yaml
currentLock:
  status: idle
  todo: null
  branch: null
  pr: null
  ownerRole: null
  ownerModel: null
  acquiredAt: null
  lastHeartbeatAt: null
  timeoutMinutes: 30
  lockReason: "无 active 编码 PR"
  nextAction: "领取下一个 todo-ready 任务"
```

## TODO 总表

| TODO     | 标题 | 状态       | 依赖 | PR  | 备注 |
| -------- | ---- | ---------- | ---- | --- | ---- |
| TODO-001 |      | todo-ready | 无   |     |      |

## TODO 依赖关系

```text
TODO-001
```

## PR 状态表

| PR  | TODO | 分支 | 状态 | Reviewer 结论 | 测试 | 文档 | 备注 |
| --- | ---- | ---- | ---- | ------------- | ---- | ---- | ---- |

## 高风险操作总表

管理员事后审计入口。Supervisor 发现敏感文件、越界修改、待删除、测试风险、人工验收或其他高风险时**必须**在此追加一行，并视类型同步写入下方专表。

| 时间 | TODO | PR  | 类型 | 摘要 | 涉及文件/路径 | 风险说明 | 管理员复审 |
| ---- | ---- | --- | ---- | ---- | ------------- | -------- | ---------- |

类型取值：`sensitive-file` / `scope-overflow` / `delete-pending` / `test-risk` / `manual-acceptance` / `other`。管理员复审取值：`待审查` / `已阅` / `需跟进`。

## 敏感文件变更表

与「高风险操作总表」同步维护；Grok 原生全自动模式下**不阻塞**合并到 `dev`。

| TODO | PR  | 文件 | 原因 | 管理员复审 | 备注 |
| ---- | --- | ---- | ---- | ---------- | ---- |

## 测试风险表

| TODO | 风险 | 原因 | 缓解方式 | 管理员确认 |
| ---- | ---- | ---- | -------- | ---------- |

## 人工验收表

| TODO | 验收项 | 步骤 | 状态 | 备注 |
| ---- | ------ | ---- | ---- | ---- |

## 非阻塞建议表

| 来源 | 建议 | 是否转 TODO | 处理决定 |
| ---- | ---- | ----------- | -------- |

## needs-replan 历史

| 时间 | 原 TODO | 原 PR | 原因 | 替代 TODO | Reviewer |
| ---- | ------- | ----- | ---- | --------- | -------- |

## 待删除文件表

| 原路径 | 新路径 | 原因 | 关联 PR | 验证方式 | 建议删除命令 | 管理员确认 |
| ------ | ------ | ---- | ------- | -------- | ------------ | ---------- |

## dev 到 master 发布检查表

- [ ] 目标 TODO 均已完成
- [ ] 自动检查通过
- [ ] 文档已更新
- [ ] 「高风险操作总表」已事后复审（敏感文件、测试风险等待删项无遗漏 `需跟进`）
- [ ] 人工验收已完成
- [ ] 非阻塞建议已处理或确认延期

## 执行记录（机器可解析）

```yaml
runs: []
```
