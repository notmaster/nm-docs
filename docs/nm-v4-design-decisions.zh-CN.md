# NM V4 工作流设计定稿决议

- 定稿日期：2026-07-08
- 决策人：管理员（NotMaster）
- 讨论方式：两轮结构化问答（问题 1-16），全部结论经管理员逐条确认
- 用途：V4 实现的依据存档，供后续复查与 V5 升级参考

## 背景与目标

把管理员意图浓缩为一份 spec 合约，让任意一家 CLI Agent（Claude / Codex / Grok）
以尽可能小的固定上下文开销，分阶段可靠地把 spec 落地；质量由本地确定性验证兜底，
人只在验收点或关键节点介入。

两个方向性判断（作为 V4 设计前提）：

1. V4 的本质是做减法：V3 已有全自动路径，V4 的真实增量是单一 spec 文档模型、
   砍掉 Plan/Goal 双层模板、规则面瘦身、跨 agent 可移植。
2. 上下文退化的主因是单会话跑长任务：解法是每个阶段用全新会话执行，
   靠 spec + 极小状态文件交接，每阶段满血上下文。

关于各家 "goal 模式" 的事实核查：三家没有统一的官方 goal 模式，差异集中在
指令文件名、headless 启动语法、权限旗标、自定义命令位置四点，
全部可以用 "agent 中立核心 + 薄适配文件 + 每家一条启动配方" 抹平。

## 已确认决议（按问题编号）

| # | 决议 |
| --- | --- |
| 1 | 新建 `template/v4` + `tools/nm-v4` + `skills/nm-init-project-v4`，v3 原样保留 |
| 2 | 上下文策略：模式 1 用混合（拆分/确认/收尾在交互会话，各阶段执行开新会话）；模式 2 每阶段全新会话，靠 spec + 状态文件交接 |
| 3 | 会话编排：模式 1 由管理员手动开新会话粘贴固定短指令；模式 2 由 runner 脚本用各家 headless CLI 自动逐阶段拉起 |
| 4 | 文档模型：SPEC 唯一需求合约 + 极小状态文件 ROADMAP.md + DECISIONS.md 记录执行期决策；不再有 REQUIREMENTS/ACCEPTANCE/DESIGN 三件套和 Plan/Goal 双层模板 |
| 5 | 阶段来源：spec 预写阶段则采用（可微调），没有则 Agent 自拆；模式 1 下 roadmap 须管理员确认后执行 |
| 6 | 模式 1（staged）为硬门禁：每阶段完成 -> 本地验证 -> 通知 -> 停等验收 -> 继续 |
| 7 | 执行模式声明：spec frontmatter 定默认值，启动指令可覆盖 |
| 8 | 模式 2（auto）每阶段验证通过即自动合并 `dev` 并 push |
| 9 | 多 agent：核心完全 agent 中立（AGENTS.md + 文档 + 脚本），init 生成 CLAUDE.md/GROK.md 一行指针文件 + 每家启动配方 |
| 10 | spec 定稿后放项目仓库 `0a-docs/0a-spec/`，Obsidian 只做草稿；顶部 YAML frontmatter |
| 11 | 不生成独立 Plan/Goal 文件；单一 `0b-goals/ROADMAP.md` 承载阶段总表 + 进度 + 每阶段小节 |
| 12 | 保留 v3 编号目录骨架微调（0a-docs / 0b-goals / 0c-workflow / 0d-scripts） |
| 13 | 模式 2 默认完全绕过审批（`--yolo` / `--dangerously-skip-permissions` 一类），靠 spec 安全边界 + AGENTS.md 硬规则 + git 兜底；配方保留 sandbox 降级档，frontmatter 可按项目声明 |
| 14 | 模式 2 遇人工验收项不阻塞：累积到 ROADMAP 待人工验收清单，最终通知汇总 |
| 15 | 模式 2 每阶段完成发进度通知（不停等），另有阻塞/需决策/全部完成通知 |
| 16 | `nm_v4.py update` 支持 v3 项目升级：叠加 v4 骨架、替换规则文件，旧文档原位保留标注为 spec 输入素材；spec 内容由管理员与 Agent 协作生成 |

备注：问题 13 管理员在知晓风险后选择完全绕过审批档（偏离推荐的 sandbox 档），
已按管理员决定执行；启动配方中保留 sandbox 降级档以便按项目回退。

## 细节决议

### A. spec 编写规范（SPEC_TEMPLATE.md）

- 命名：`0a-docs/0a-spec/SPEC-<slug>-V<n>.md`。
- frontmatter 必填：`project`、`version`、`status: draft|confirmed`、
  `execution_mode: staged|auto`（默认 staged）；可选：`permissions: bypass|sandbox`
  （默认 bypass）、`verify_entry`（默认 `./0d-scripts/verify.sh`）。
- 只有 `status: confirmed` 的 spec 才允许执行。
- 正文章节：背景/总目标、非目标、已确认决策、架构（可选）、关键流程与规则、
  实施阶段（可选）、最终验收标准、待执行前环境确认项。
- 每阶段验收拆两栏标注：`Verify:`（机器可验命令）与 `Manual:`（人工验收项）。

### B. ROADMAP.md 结构

- frontmatter：spec 路径、execution_mode、permissions、当前阶段指针、整体状态。
- 阶段总表：编号/名称/分支/状态/验证结果/合并状态；
  状态机 `pending -> in_progress -> verified -> accepted -> merged`，异常 `blocked`。
- 每阶段小节：objective、spec 章节引用、verify 命令、manual 项、完成记录、交接备注。
- 待人工验收清单（auto 模式用）。
- 新会话交接只读三件套：AGENTS.md + spec + ROADMAP.md。

### C. 运行语义

- staged：交互会话生成 ROADMAP -> 管理员确认 -> 每阶段新会话（固定短指令）->
  建分支 -> 实现 -> verify -> push -> 通知 -> 停等 -> 验收后合并 dev -> 下一阶段。
- auto：`0d-scripts/run-goals.py --agent claude|codex|grok` 串行逐阶段拉起
  headless 会话；会话内自治修复；verify -> push -> 自动合并 dev -> 更新 ROADMAP ->
  通知 -> 下一阶段。
- 停止条件承袭 v3：阻塞、需决策、范围扩大、安全风险、同类验证失败连续 5 次 ->
  停止 + 通知。

### D. 多 agent 适配（AGENT_RECIPES.md）

- 指针文件：CLAUDE.md、GROK.md 引向 AGENTS.md。
- 每家两条配方：staged 启动语 + auto runner 命令（bypass 档与 sandbox 降级档旗标）。
- headless 适配：`claude -p` / `codex exec` / `grok --cwd DIR -p`。
- 不依赖各家私有 slash 命令；v3 的 `.codex/` hooks 承袭为可选。

### E. AGENTS.md 瘦身

- 目标 60 行以内硬规则：语言时区、分支纪律、三件套交接规则、两种模式门禁语义、
  验证入口、5 次失败停、通知入口、安全条款。
- 原型版本规则、通知细节、发布清单移入 `0c-workflow/` 按需读。

### F. template/v4 目录

```text
0a-docs/{0a-spec/, 0b-design/prototype/, 0c-prompts/, DECISIONS.md}
0b-goals/ROADMAP.md
0c-workflow/{WORKFLOW_V4.md, SPEC_TEMPLATE.md, AGENT_RECIPES.md, BRANCHING.md,
             VERIFY.md, RELEASE_CHECKLIST.md, project-profile.yml}
0d-scripts/{verify.sh, check-workflow.sh, notify-admin.sh, nm-notify-feishu.sh,
            run-goals.py}
AGENTS.md, AGENTS.zh-CN.md, CLAUDE.md, GROK.md, PROJECT_STRUCTURE.md, README.md,
manifest.json, package.json, .codex/
```

### G. 工具与 skill

- `tools/nm-v4/nm_v4.py`：init / update / check / install-skill，manifest 驱动，
  沿用 v3 模式；update 走 git clean 检查 + `chore/sync-nm-workflow-v4-YYYYMMDD` 分支。
- v3 升级时被 v4 取代的框架文件移入 `.delete-pending/v3-superseded/` 等管理员确认。
- `skills/nm-init-project-v4`：SKILL.md + wrapper 脚本 + references，
  默认装到 `~/.agents/skills`。

### H. 仓库层面收尾

- README 推荐版本改为 V4（保留 v3 链接）；`docs/template-versions*.md`、
  `docs/installation.md` 增补 v4；仓库 AGENTS.md 与 AGENTS.zh-CN.md 同步加入
  v4 manifest 为 source of truth。
- 验证：`npm run lm`、`nm_v4.py check`、skill validator 全部通过。
