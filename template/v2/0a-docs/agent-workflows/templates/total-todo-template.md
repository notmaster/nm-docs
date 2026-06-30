# 总 TODO 模板

```yaml
project:
  name: ""
  requirementDoc: ""
  baseBranch: "{{INTEGRATION_BRANCH}}"
  stableBranch: "{{STABLE_BRANCH}}"
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
- 开发集成分支：`{{INTEGRATION_BRANCH}}`
- 稳定分支：`{{STABLE_BRANCH}}`

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

## 敏感文件变更表

| TODO | PR  | 文件 | 原因 | 管理员已读 | 备注 |
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

## {{INTEGRATION_BRANCH}} 到 {{STABLE_BRANCH}} 发布检查表

- [ ] 目标 TODO 均已完成
- [ ] 自动检查通过
- [ ] 文档已更新
- [ ] 敏感文件变更已读
- [ ] 人工验收已完成
- [ ] 非阻塞建议已处理或确认延期

## 执行记录（机器可解析）

```yaml
runs: []
```
