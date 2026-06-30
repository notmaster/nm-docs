import { existsSync } from "node:fs";
import { basename, join } from "node:path";
import yaml from "js-yaml";
import { Reporter, readText, rel, repoRoot, walkFiles } from "./shared.mjs";

const reporter = new Reporter("agent-workflow todo check");
const todoDir = join(repoRoot, "0b-todo");

const requiredFields = [
  "taskId",
  "type",
  "title",
  "profile",
  "deps",
  "developer",
  "reviewer",
  "maxRounds",
  "timeoutMinutes",
];

const requiredSections = [
  "## 需求概述",
  "## 方案对比",
  "## 最终选择",
  "## 风险提示",
  "## 任务列表",
  "## 执行记录（机器可解析）",
];

const allowedTypes = new Set(["feat", "fix", "refactor", "style", "docs", "test", "perf", "chore"]);
const allowedStatuses = new Set([" ", ">", "x", "!"]);

function parseFrontMatter(content, file) {
  if (!content.startsWith("---\n")) {
    return null;
  }
  const end = content.indexOf("\n---", 4);
  if (end === -1) {
    reporter.error(`${file}: Front Matter 缺少结束分隔符`);
    return null;
  }
  const raw = content.slice(4, end);
  try {
    return yaml.load(raw) ?? {};
  } catch (error) {
    reporter.error(`${file}: Front Matter YAML 无法解析：${error.message}`);
    return null;
  }
}

function parseExecutionRecord(content, file) {
  const heading = "## 执行记录（机器可解析）";
  const index = content.indexOf(heading);
  if (index === -1) {
    reporter.error(`${file}: 缺少执行记录小节`);
    return;
  }
  const afterHeading = content.slice(index + heading.length);
  const match = afterHeading.match(/```ya?ml\n([\s\S]*?)\n```/);
  if (!match) {
    reporter.error(`${file}: 执行记录下缺少 yaml 代码块`);
    return;
  }
  try {
    const record = yaml.load(match[1]) ?? {};
    if (!Array.isArray(record.runs)) {
      reporter.error(`${file}: 执行记录 YAML 必须包含 runs 数组`);
    }
  } catch (error) {
    reporter.error(`${file}: 执行记录 YAML 无法解析：${error.message}`);
  }
}

function checkTaskList(content, file) {
  const matches = content.matchAll(/^- \[([^\]])\]/gm);
  for (const match of matches) {
    if (!allowedStatuses.has(match[1])) {
      reporter.error(`${file}: 不支持的任务状态 [${match[1]}]`);
    }
  }
}

function checkTodoFile(path) {
  const file = rel(path);
  const content = readText(path);
  const frontMatter = parseFrontMatter(content, file);

  if (!frontMatter) {
    reporter.warn(`${file}: 旧格式 TODO，未执行 Front Matter 强校验`);
    return;
  }

  for (const field of requiredFields) {
    if (!(field in frontMatter)) {
      reporter.error(`${file}: Front Matter 缺少 ${field}`);
    }
  }
  if (!allowedTypes.has(frontMatter.type)) {
    reporter.error(`${file}: type 必须是 ${Array.from(allowedTypes).join("|")} 之一`);
  }
  if (!Array.isArray(frontMatter.deps)) {
    reporter.error(`${file}: deps 必须是数组`);
  }
  for (const field of ["maxRounds", "timeoutMinutes"]) {
    if (!Number.isInteger(frontMatter[field]) || frontMatter[field] <= 0) {
      reporter.error(`${file}: ${field} 必须是正整数`);
    }
  }
  for (const section of requiredSections) {
    if (!content.includes(section)) {
      reporter.error(`${file}: 缺少固定小节 ${section}`);
    }
  }

  parseExecutionRecord(content, file);
  checkTaskList(content, file);
}

if (!existsSync(todoDir)) {
  reporter.error("缺少 0b-todo/ 目录");
} else {
  const files = walkFiles(todoDir, (path) => path.endsWith(".md"));
  if (files.length === 0) {
    reporter.warn("0b-todo/ 下没有 TODO Markdown 文件");
  }
  for (const file of files) {
    if (basename(file).startsWith(".")) {
      continue;
    }
    checkTodoFile(file);
  }
}

reporter.finish();
