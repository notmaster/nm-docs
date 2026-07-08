# Workflow V4

## 核心原则

V4 是 Spec 驱动的目标工作流：管理员把意图收敛成一份 Spec 合约，Agent 据此拆分阶段并
逐阶段落地，本地确定性验证兜底，人只在验收点或关键节点介入。

- 单一 Spec 合约：需求、决策、架构、阶段和验收收敛在一份 Spec 中。
- 极小交接面：执行只依赖三件套（`AGENTS.md` + Spec + `ROADMAP.md`），避免固定规则挤占上下文。
- 每阶段新会话：长任务按阶段切分到独立会话执行，阶段之间靠 ROADMAP 交接，避免单会话上下文退化。
- 本地验证兜底：0 到 1 阶段以 `./0d-scripts/verify.sh` 与阶段验收为质量门，不依赖远端 CI。
- 通知留痕：关键节点通过 `./0d-scripts/notify-admin.sh` 通知管理员。

## 目录产物

- `0a-docs/0a-spec/`：Spec 合约，命名 `SPEC-<slug>-V<n>.md`，规范见 `SPEC_TEMPLATE.md`。
- `0b-goals/ROADMAP.md`：唯一运行时状态文件（阶段表、进度、交接、待人工验收清单）。
- `0a-docs/DECISIONS.md`：影响后续实现、验收或发布的关键决策记录。
- `0a-docs/0b-design/prototype/`：原型版本目录（`v1`、`v2` ... 自增长，按需使用）。
- `0a-docs/0c-prompts/`：Spec 撰写、Spec 评审、安全审查提示词。
- `0c-workflow/`：工作流、Spec 模板、启动配方、分支、验证、发布清单。
- `0d-scripts/`：本地确定性脚本与 auto 模式 runner。

## 两种执行模式

| 模式 | 阶段门禁 | 合并 | 通知 |
| --- | --- | --- | --- |
| `staged`（默认） | 每阶段停等管理员验收 | 验收通过后合并 `dev` | 阶段完成、阻塞、全部完成 |
| `auto` | 无人值守连续执行 | 验证通过即合并 `dev` 并 push | 每阶段完成与合并、阻塞、需决策、全部完成 |

模式声明：Spec frontmatter `execution_mode` 提供默认值，启动指令可以覆盖。

权限档（仅 `auto` 模式生效）：默认 `permissions: bypass`，即完全绕过审批
（各家旗标见 `AGENT_RECIPES.md`），依赖 Spec 安全边界 + `AGENTS.md` 硬规则 + git 兜底；
需要收紧时声明 `permissions: sandbox`，将自动执行限制在工作区内。

## 阶段 0：撰写并确认 Spec

1. 草稿可以在任意地方（例如 Obsidian）撰写，定稿副本必须放入 `0a-docs/0a-spec/` 并由 git 管理。
2. 使用 `0a-docs/0c-prompts/write-spec.md` 辅助撰写；可用 `review-spec.md` 做多模型评审。
3. 管理员确认后将 frontmatter `status` 改为 `confirmed`。只有 confirmed 的 Spec 允许执行。

## 阶段 1：生成 ROADMAP

1. Agent 读取 confirmed Spec：Spec 已写实施阶段则直接采用并可微调；没有则自行拆分。
2. 拆分要求：每个阶段可独立执行、独立验证；机器可验命令写入 `Verify:`，人工项写入 `Manual:`；
   不要把验收标准差异很大的内容塞进同一阶段。
3. `staged` 模式：ROADMAP 生成后必须经管理员确认才能进入执行。
   `auto` 模式：runner 的首个会话生成 ROADMAP 后直接开始执行。
4. ROADMAP 的创建与状态更新属于工作流簿记，允许直接提交到 `dev`；
   阶段执行中的状态更新也可以在任务分支内修改并随合并回到 `dev`。

## 阶段 2：逐阶段执行

### staged 模式（默认）

每个阶段在一个全新会话中执行。管理员开新会话并粘贴固定短指令
（见 `AGENT_RECIPES.md`），Agent 依次：

1. 读三件套，定位 ROADMAP 中下一个待执行阶段，将状态置为 `in_progress`。
2. 从最新 `dev` 新建任务分支。
3. 实现该阶段，运行 `./0d-scripts/verify.sh` 与阶段 `Verify:` 命令，失败则修复重跑。
4. 验证通过后 push 任务分支，状态置为 `verified`，填写 Result 与 Handoff。
5. 调用 `notify-admin.sh` 发阶段完成通知，然后停等管理员验收，不得继续下一阶段。
6. 验收通过后（同一会话或新会话执行）：按 `BRANCHING.md` 合并回 `dev` 并 push，
   状态置为 `merged`，评估分支清理。验收不通过则按反馈在原任务分支继续修复。

### auto 模式

由 runner 逐阶段拉起无人值守会话：

```bash
python3 0d-scripts/run-goals.py --agent codex   # 或 claude / grok
```

每个阶段会话内，Agent 依次：建分支 -> 实现 -> 验证 -> push -> 合并 `dev` 并 push ->
更新 ROADMAP（状态 `merged`、Result、Handoff，`Manual:` 项追加到待人工验收清单）->
发阶段进度通知。runner 校验阶段状态推进到 `merged` 后拉起下一阶段；
状态未推进或会话异常退出时，通知管理员并停止。

人工验收项不阻塞 auto 执行。全部阶段完成后发总结通知，
管理员按 ROADMAP 的待人工验收清单做最终验收。

## 验证

- 入口与分层见 `VERIFY.md`；默认入口 `./0d-scripts/verify.sh`，
  轻量结构检查 `./0d-scripts/check-workflow.sh`。
- 阶段完成的定义：`verify.sh` 通过且该阶段 `Verify:` 命令全部通过。
- 同一类验证失败连续 5 次仍无法修复：停止并通知管理员（auto 模式下 runner 一并停止）。

## 通知节点

| 事件 | staged | auto |
| --- | --- | --- |
| 阶段完成 | 必发，随后停等验收 | 必发，不停等 |
| 阻塞 / 需决策 | 必发并停止 | 必发并停止 |
| 全部完成 | 必发 | 必发，附待人工验收清单 |

通知调用方式与飞书卡片格式见项目 `README.md` 与 `0d-scripts/notify-admin.sh`。

## 原型版本规则

- 原型产物放在 `0a-docs/0b-design/prototype/v<number>/`。
- 创建新原型前扫描已有 `v<number>` 目录并使用当前最大数字加 1；没有则从 `v1` 开始。
- 每个版本目录自包含该版原型文件和资产；未经管理员明确要求，不得覆盖、移动或删除旧版本。

## 发布与维护

- 首版上线前完成 `RELEASE_CHECKLIST.md`，并用 `0a-docs/0c-prompts/security-review.md`
  完成至少一轮安全审查。
- 首版稳定后再启用远端 CI/CD；远端 CI 调用同一个本地验证入口，避免两套质量标准。
- `main` 只保存稳定可发布版本；发布合并由管理员明确触发。

## 与 V3 的差异

- REQUIREMENTS / ACCEPTANCE / DESIGN 与 Plan / Goal 双层文档族，收敛为 Spec + ROADMAP 两份。
- 固定规则面收窄为 `AGENTS.md` 硬规则，其余文档按需加载。
- 每阶段强制新会话执行，用文件交接进度，解决长任务上下文退化。
- 提供跨 Claude / Codex / Grok 的启动配方与无人值守 runner。
