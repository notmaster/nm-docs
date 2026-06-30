import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { Reporter, readText, repoRoot } from "./shared.mjs";

const reporter = new Reporter("agent-workflow infrastructure check");

const requiredFiles = [
  "AGENTS.md",
  "CLAUDE.md",
  "0a-docs/agent-workflows/multi-agent-coding-v2.md",
  "0a-docs/agent-workflows/templates/total-todo-template.md",
  "0a-docs/agent-workflows/templates/single-todo-template.md",
  "0a-docs/agent-workflows/templates/pr-body-template.md",
  "0a-docs/agent-workflows/templates/review-checklist-template.md",
  "0a-docs/prompts/planner-split-todo.md",
  "0a-docs/prompts/supervisor-start.md",
  "0a-docs/prompts/coder-task.md",
  "0a-docs/prompts/reviewer-pr.md",
  "0a-docs/prompts/fixer-request-changes.md",
  ".github/pull_request_template.md",
  ".github/workflows/ci.yml",
];

const prSections = [
  "## 对应 TODO",
  "## 本 PR 完成内容",
  "## 修改范围",
  "## 是否涉及敏感文件",
  "## 文档更新",
  "## 测试结果",
  "## 风险与未完成事项",
  "## 给 Reviewer 的重点",
];

function checkRequiredFiles() {
  for (const file of requiredFiles) {
    if (!existsSync(join(repoRoot, file))) {
      reporter.error(`缺少必要文件：${file}`);
    }
  }
}

function checkRulesSynced() {
  const agents = readText(join(repoRoot, "AGENTS.md"));
  const claude = readText(join(repoRoot, "CLAUDE.md"));
  if (agents !== claude) {
    reporter.error("AGENTS.md 与 CLAUDE.md 内容不一致");
  }
}

function checkPrTemplate() {
  const path = join(repoRoot, ".github/pull_request_template.md");
  if (!existsSync(path)) {
    return;
  }
  const content = readText(path);
  for (const section of prSections) {
    if (!content.includes(section)) {
      reporter.error(`PR 模板缺少小节：${section}`);
    }
  }
}

function runScript(script) {
  const result = spawnSync(process.execPath, [join(repoRoot, script)], {
    cwd: repoRoot,
    encoding: "utf8",
  });
  if (result.stdout) {
    process.stdout.write(result.stdout);
  }
  if (result.stderr) {
    process.stderr.write(result.stderr);
  }
  if (result.status !== 0) {
    reporter.error(`${script} 执行失败`);
  }
}

checkRequiredFiles();
checkRulesSynced();
checkPrTemplate();
runScript("0c-tools/agent-workflow/check-todo.mjs");
runScript("0c-tools/agent-workflow/check-git.mjs");

reporter.finish();
