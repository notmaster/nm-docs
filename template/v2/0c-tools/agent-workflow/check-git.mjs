import { Reporter, git } from "./shared.mjs";

const reporter = new Reporter("agent-workflow git check");

const sensitivePatterns = [
  /^\.github\//,
  /^package\.json$/,
  /^package-lock\.json$/,
  /^pnpm-lock\.yaml$/,
  /^yarn\.lock$/,
  /^AGENTS\.md$/,
  /^CLAUDE\.md$/,
  /^PROJECT_STRUCTURE\.md$/,
  /^0c-tools\/agent-workflow\//,
];

function listChangedNameStatus() {
  try {
    const tracked = git(["diff", "--name-status", "HEAD"])
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const untracked = git(["ls-files", "--others", "--exclude-standard"])
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((path) => `A\t${path}`);
    return [...tracked, ...untracked];
  } catch (error) {
    reporter.error(`无法读取 git diff：${error.message}`);
    return [];
  }
}

function changedPathFromStatus(line) {
  const parts = line.split(/\t+/);
  if (parts[0]?.startsWith("R") || parts[0]?.startsWith("C")) {
    return parts[2];
  }
  return parts[1];
}

function checkDeletion(lines) {
  const deleted = lines.filter((line) => line.startsWith("D\t"));
  for (const line of deleted) {
    reporter.error(`检测到真实删除文件：${changedPathFromStatus(line)}。请改用 .delete-pending/ 机制`);
  }
}

function checkSensitive(lines) {
  const touched = new Set(lines.map(changedPathFromStatus).filter(Boolean));
  for (const path of touched) {
    if (sensitivePatterns.some((pattern) => pattern.test(path))) {
      reporter.warn(`敏感文件变更需在 TODO/PR 中记录并由管理员确认：${path}`);
    }
  }
}

function checkDevBranch() {
  try {
    git(["show-ref", "--verify", "--quiet", "refs/heads/{{INTEGRATION_BRANCH}}"], {
      stdio: "ignore",
    });
    return;
  } catch {
    try {
      git(["show-ref", "--verify", "--quiet", "refs/remotes/origin/{{INTEGRATION_BRANCH}}"], {
        stdio: "ignore",
      });
      return;
    } catch {
      reporter.warn(
        "未检测到本地或远端 {{INTEGRATION_BRANCH}} 分支；协同开发前需要创建并推送 {{INTEGRATION_BRANCH}}",
      );
    }
  }
}

function isGitRepository() {
  try {
    return git(["rev-parse", "--is-inside-work-tree"]) === "true";
  } catch {
    return false;
  }
}

if (!isGitRepository()) {
  reporter.warn(
    "当前目录尚未初始化 Git；已跳过删除、敏感文件和 {{INTEGRATION_BRANCH}} 分支检查",
  );
} else {
  const lines = listChangedNameStatus();
  checkDeletion(lines);
  checkSensitive(lines);
  checkDevBranch();
}

reporter.finish();
