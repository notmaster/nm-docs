# Verification

## 入口

默认本地验证入口：

```bash
./0d-scripts/verify.sh
```

也可以通过 npm 调用：

```bash
npm run verify
```

轻量工作流结构检查入口：

```bash
./0d-scripts/check-workflow.sh
```

也可以通过 npm 调用：

```bash
npm run workflow:check
```

## 配置

项目验证要求声明在：

```text
0c-workflow/project-profile.yml
```

早期模板保持简单：`project-profile.yml` 只声明项目类型和验证要求，`verify.sh` 手动实现具体命令，不要求自动解析 yml。

## 完成标准

Goal 未通过必需本地验证前，不得视为完成。

`verify.sh` 默认先调用 `check-workflow.sh`，检查 v3 目录、Plan/Goal 命名、active Goal 数量、必要文档、脚本执行权限和 `DESIGN.md` 规范。

## 验证分层

通用项目可以按类型选择验证层：

- `common`：格式、lint、类型检查、单元测试、构建。
- `docs`：Markdown lint、链接检查。
- `web`：构建、浏览器 smoke、关键页面和响应式检查。
- `backend`：单元测试、集成测试、API smoke、迁移检查。
- `cli`：命令 smoke、`--help`、`--version`。
- `mobile`：构建、核心路径自动化或人工验收清单。
- `desktop`：启动检查、核心路径自动化或人工验收清单。

## 失败分类

同一类验证失败连续 5 次仍无法修复时，Agent 必须停止并通知管理员。

失败类别使用以下粗粒度分类：

- `dependency/install`
- `lint/format`
- `typecheck`
- `unit-test`
- `integration-test`
- `e2e/browser`
- `build`
- `runtime/startup`
- `migration/database`
- `external-service`
- `unknown`

通知管理员时必须说明：

- 失败类别。
- 已运行的命令。
- 最近的错误摘要。
- 已尝试的修复。
- 当前建议的下一步。

## 远端 CI

0 到 1 开发阶段不强制远端 CI。首版稳定后，远端 CI 应调用同一个本地验证入口，避免两套质量标准。
