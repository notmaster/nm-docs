# 仓库工作通知

`nm-docs` 在自身的长时间 AI 维护工作中复用 V5 模板维护的飞书双通道通知适配器。根目录入口是稳定的薄封装；复用该适配器不代表本仓库成为 V5 runtime，也不改变 V5 的实验性状态。

## 调用入口

Agent 必须通过根目录事件命令发送结构化事件：

```bash
npm run notify:event -- \
  --event stage_completed \
  --severity progress \
  --title "Repository stage completed" \
  --message "branch=feature/example completed=implementation next=verification risk=none"
```

`./0d-scripts/notify-admin.sh` 是事件适配器使用的内部兼容层。Agent 不应直接调用它，也不应使用自由格式通知绕过事件语义。

## 仓库事件表

| 事件 | 严重度 | 发送时机 |
| --- | --- | --- |
| `work_started` | `progress` | 预检完成且非平凡工作已经开始 |
| `stage_completed` | `progress` | 有意义的发现、实现或验证阶段发生状态变化 |
| `work_completed` | `attention` | 请求的工作和全部必要本地验证均已完成，并向管理员显式交接 |
| `attention_required` | `attention` | 需要管理员决策、验收或新的授权 |
| `blocked` | `attention` | 安全、Git 状态、依赖或重复技术失败阻止安全推进 |
| `validation_failed` | `attention` | 必要检查仍失败且工作必须停止 |
| `notify_test` | 由调用方选择 | 管理员明确要求真实投递测试 |

每次状态转换只发送一个事件，并选择最具体的事件。最终阶段使用 `work_completed` 而不是 `stage_completed`；必要检查失败使用 `validation_failed` 而不是 `blocked`；`attention_required` 用于非错误的人工门禁，`blocked` 用于不安全状态或技术性硬停止。

最终完成并通过验证不属于普通进度；即使没有错误，也必须使用 attention，确保管理员收到显式交接提醒。

路由严重度与卡片语义彼此独立：`work_completed` 走 attention 通道但显示绿色完成卡片，`attention_required` 显示黄色，只有阻塞或验证失败显示红色。

不要发送定时心跳、每条 shell 命令一条事件，或对未变化状态重复发送事件。阶段汇报应标识任务或分支，并说明已完成内容、当前状态、下一步和重大风险。

## 配置与路由

适配器只读取本机文件：

```text
~/.config/nm-docs/nm-notify-feishu.env
```

该文件权限必须为 `600`。根仓库使用 V5 默认变量名：

- `FEISHU_WEBHOOK_PROGRESS` 与可选的 `FEISHU_SIGN_SECRET_PROGRESS`
- `FEISHU_WEBHOOK_ATTENTION` 与可选的 `FEISHU_SIGN_SECRET_ATTENTION`
- `FEISHU_WEBHOOK_URL` 与 `FEISHU_SIGN_SECRET` 作为单通道 fallback

不得把真实 webhook URL 或签名 secret 写入仓库、命令、报告、测试或通知。完整飞书配置与签名行为继续由 [V5 通知参考](../template/v5/0c-workflow/NOTIFY_EVENTS.md)说明。

## 验证

修改根目录封装或被复用的 V5 适配器后，运行隔离的本地检查：

```bash
npm run notify:check
```

该检查使用临时 home 目录、虚拟 webhook 值、恶意 `.curlrc` 和假 `curl`，在不进行网络投递、也不访问真实本机配置的情况下，验证仓库事件表、progress/attention 路由、签名 payload 结构、有界 curl 参数、不安全配置拒绝、传输失败和飞书错误处理。

真实 `notify_test` 会发送外部消息，只有管理员明确要求验证投递时才应运行。

## 边界

- 通知只报告状态，绝不授予验收或授权。
- 通知失败必须报告，但不回滚或使已完成的工程工作失效。
- 未经管理员明确授权，不得 fallback 到系统级 `nm-notify-feishu` skill；它使用另一套配置，并绕过仓库事件入口。
- 投递由事件触发。每次尝试都会禁用用户 curl 配置，通过非 argv 通道传递 webhook URL 与 payload，连接超时为 10 秒、总超时为 30 秒，且不会自动重试。本集成没有定时心跳、崩溃监督、重试队列、去重或持久 outbox。
