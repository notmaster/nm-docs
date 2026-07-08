# Agent Recipes

本文档是各家 Agent CLI 的启动配方。核心规则完全 agent 中立：所有 CLI 共用根目录
`AGENTS.md`，`CLAUDE.md` 与 `GROK.md` 只是指向它的入口文件。

会话交接三件套：`AGENTS.md` + `0a-docs/0a-spec/` 下已确认的 Spec + `0b-goals/ROADMAP.md`。

## staged 模式固定短指令

每个阶段开一个全新会话，粘贴：

```text
执行 ROADMAP 的下一个阶段：读取 AGENTS.md、0b-goals/ROADMAP.md 和其引用的 Spec，
按 staged 模式完成当前待执行阶段，验证通过后 push、发通知并停等验收。
```

管理员验收通过后，在同一会话继续粘贴：

```text
验收通过：按 0c-workflow/BRANCHING.md 合并当前阶段分支回 dev 并 push，
更新 ROADMAP 阶段状态为 merged。
```

首次生成 ROADMAP（交互会话）：

```text
读取 0a-docs/0a-spec/ 下已确认的 Spec，按 0c-workflow/WORKFLOW_V4.md 生成
0b-goals/ROADMAP.md，先给我确认，不要开始实现。
```

## auto 模式（无人值守 runner）

```bash
python3 0d-scripts/run-goals.py --agent codex
python3 0d-scripts/run-goals.py --agent claude
python3 0d-scripts/run-goals.py --agent grok
```

常用参数：

- `--permissions bypass|sandbox`：覆盖 ROADMAP/Spec 中的权限档，缺省 `bypass`。
- `--mode auto`：当 ROADMAP 仍是 `staged` 时，以启动参数覆盖为 auto（决议 7）。
- `--max-phases N`：本次最多执行 N 个阶段。
- `--dry-run`：只打印将要执行的命令。
- `--spec PATH`：ROADMAP 未初始化时指定 Spec 路径。

runner 每个阶段拉起一个全新 headless 会话，会话内自治修复；
阶段状态未推进到 `merged` 或会话异常退出时，runner 通知管理员并停止。
日志写入 `logs/run-goals/`（已被 `.gitignore` 忽略）。

## 各家 CLI 差异速查

| 项 | Claude Code | Codex | Grok |
| --- | --- | --- | --- |
| 规则文件 | `CLAUDE.md`（指针） | `AGENTS.md`（原生） | `AGENTS.md` / `GROK.md` |
| headless 启动 | `claude -p "<prompt>"` | `codex exec "<prompt>"` | `grok --cwd DIR -p "<prompt>"` |
| bypass 档旗标 | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | `--always-approve` |
| sandbox 档旗标 | `--permission-mode acceptEdits` | `--full-auto` | 默认权限模式 |

注意：

- 各家旗标随版本漂移，使用前用 `--help` 核对；runner 已内置以上差异。
- 其他原生读取 `AGENTS.md` 的 CLI（例如 droid）可以直接以 staged 模式使用同一套短指令。
- bypass 档赋予完全执行权限，只应在受信任的项目目录使用；
  需要收紧时在 Spec 中声明 `permissions: sandbox`，或启动时加 `--permissions sandbox`。
