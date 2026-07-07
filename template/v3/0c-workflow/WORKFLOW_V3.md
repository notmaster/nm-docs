# Workflow V3

## 核心原则

V3 工作流采用“管理员定义目标，Agent 在 Goal 合约内实现，本地确定性验证兜底”的模式。

- 管理员负责需求文档、原型、设计规范、多模型评审和最终验收。
- Agent 负责基于确认后的 Goal 执行实现、验证、修复和状态汇报。
- 质量主要由本地脚本、测试、验收标准和轻量 hook 兜底。
- 0 到 1 开发阶段不强制远端 CI/CD，GitHub 主要用于分支备份。
- 首版稳定后再启用远端 CI/CD，并复用本地验证入口。

## 目录产物

- `0a-docs/0a-product/REQUIREMENTS.md`：需求和产品决策主文档。
- `0a-docs/0a-product/ACCEPTANCE.md`：管理员验收标准。
- `0a-docs/DECISIONS.md`：影响后续实现、验收或发布的关键决策记录。
- `0a-docs/0b-design/prototype/`：原型版本根目录，原型放在 `v1`、`v2`、`v3` 等自增长目录。
- `0a-docs/0b-design/DESIGN.md`：设计规范。
- `0b-goals/0a-plans/`：执行计划，可有多个。
- `0b-goals/0b-current/`：当前 active Goal，默认只能有一个。
- `0b-goals/0c-archive/`：关键 Goal 完成后归档。
- `0c-workflow/`：工作流、分支、验证、发布清单和 Plan/Goal 模板。
- `0d-scripts/`：本地确定性脚本。

## 原型版本目录

- 所有新原型必须创建在 `0a-docs/0b-design/prototype/v<number>/` 下。
- 创建新原型前，先扫描已有 `v<number>` 目录，并使用当前最大数字加 1。
- 如果还没有版本目录，从 `v1` 开始。
- 每个版本目录必须自包含该版原型文件、图片、CSS、说明和其他资产。
- 除非管理员明确要求，不得覆盖、移动或删除旧版本原型。

## 阶段 1：管理员规划

管理员手动准备或确认以下内容：

1. 需求文档。
2. 验收标准。
3. 原型。
4. 设计规范。
5. 关键决策记录。
6. 可选的多模型评审结果。

多模型评审由管理员手动操作，并由管理员决定是否保存评审记录。

## 阶段 2：生成 Plan 和 Goal

Agent 读取管理员确认的文档，先生成 Plan，再从 Plan 拆出可验收的 Goal。

Plan 文件命名必须使用：

```text
Plan-<YYYYMMDD>-PlanID<001>-<slug>.md
```

Goal 文件命名必须使用：

```text
Goal-<YYYYMMDD>-PlanID<001>-<GoalID001>-<slug>.md
```

Plan 应定义里程碑顺序、依赖关系、是否允许自动执行、是否允许自动合并。Goal 必须包含：

- Objective。
- Inputs。
- Scope。
- Out of Scope。
- Branch。
- Steps。
- Verification。
- Manual Acceptance。
- Stop Conditions。
- Completion。

管理员确认 Goal 后，Agent 才能进入实现阶段。

## 阶段 3：实现

1. 从 `dev` 新建任务分支。
2. 在 Goal 模式下执行任务。
3. 按 `0c-workflow/VERIFY.md` 执行本地验证。
4. 验证失败时修复并重跑。
5. 同一类失败连续 5 次仍无法修复时，停止并通知管理员。
6. 验证通过后 push 当前任务分支做备份。

默认执行字段：

```yaml
administrator_review_required: true
auto_execute_goals: false
auto_merge_to_dev: false
auto_push: true
```

默认允许 Agent push 当前任务分支做备份，但禁止自动合并。

## 阶段 4：管理员验收

默认情况下，任务完成后等待管理员验收。

- 验收通过：管理员明确要求后，Agent 合并回 `dev`、同步远端，并按 `0c-workflow/BRANCHING.md` 评估是否清理已合并的短期任务分支。
- 验收不通过：Agent 继续在当前任务分支修复。
- 管理员要求新增功能：从 `dev` 新建新分支处理。

只有管理员明确授权，或者当前 Plan 和 Goal 都设置 `auto_merge_to_dev: true` 时，Agent 才能在验证通过后自动合并回 `dev`。

当 Plan 设置 `administrator_review_required: false`、`auto_execute_goals: true`、
`auto_merge_to_dev: true` 时，Agent 可以按 Plan 串行拆分、执行、验证、push、合并、评估已合并短期分支清理并归档所有 Goal。遇到阻塞、范围扩大、安全风险或同类验证失败连续 5 次时，必须停止并通知管理员。

## 阶段 5：维护与发布

首版稳定后再启用远端 CI/CD：

- 远端 CI 调用同一个本地验证入口。
- PR 或合并前必须通过 CI。
- CD 单独配置，不绑定普通功能开发。
- `main` 只保存稳定可发布版本。
- 正式上线前必须完成 `0c-workflow/RELEASE_CHECKLIST.md`。
- 上线前安全审查可使用 `0a-docs/0c-prompts/security-review.md`。

## 通知

出现需要管理员确认的问题或重要状态时，Agent 应调用：

```bash
./0d-scripts/notify-admin.sh --level action_required --title "Title" --message "Message"
```

通知卡片必须包含项目来源标识。项目通知脚本默认使用当前 Git 仓库根目录名；需要覆盖时使用 `--project`，或在 `~/.config/nm-docs/nm-notify-feishu.env` 中设置 `FEISHU_PROJECT_NAME` / `PROJECT_NAME`。

飞书通知是推荐能力。缺少 `~/.config/nm-docs/nm-notify-feishu.env` 时，脚本会报告项目配置缺失并失败退出；Agent 必须说明失败原因，不得自行改用系统级通知。
