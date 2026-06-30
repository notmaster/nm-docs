import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

export const repoRoot = process.cwd();

export function readText(path) {
  return readFileSync(path, "utf8");
}

export function walkFiles(dir, matcher, result = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    const stat = statSync(path);
    if (stat.isDirectory()) {
      walkFiles(path, matcher, result);
      continue;
    }
    if (matcher(path)) {
      result.push(path);
    }
  }
  return result;
}

export function rel(path) {
  return relative(repoRoot, path);
}

export function git(args, options = {}) {
  const output = execFileSync("git", args, {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    ...options,
  });
  return typeof output === "string" ? output.trim() : "";
}

export class Reporter {
  constructor(title) {
    this.title = title;
    this.errors = [];
    this.warnings = [];
  }

  error(message) {
    this.errors.push(message);
  }

  warn(message) {
    this.warnings.push(message);
  }

  finish() {
    console.log(`\n== ${this.title} ==`);
    for (const warning of this.warnings) {
      console.log(`WARN ${warning}`);
    }
    for (const error of this.errors) {
      console.error(`ERROR ${error}`);
    }
    if (this.errors.length > 0) {
      console.error(`FAILED ${this.errors.length} error(s), ${this.warnings.length} warning(s)`);
      process.exit(1);
    }
    console.log(`OK ${this.warnings.length} warning(s)`);
  }
}
