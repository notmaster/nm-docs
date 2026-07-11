#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const rootReal = fs.realpathSync(root);
const failures = [];
const warnings = [];

function fail(message) {
  failures.push(message);
}

function warn(message) {
  warnings.push(message);
}

function relativeFiles(directory) {
  const absolute = path.join(root, directory);
  if (!fs.existsSync(absolute)) return [];
  return fs
    .readdirSync(absolute, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name !== ".gitkeep")
    .map((entry) => path.join(directory, entry.name));
}

function read(relative) {
  return fs.readFileSync(path.join(root, relative), "utf8");
}

function frontmatter(relative) {
  const text = read(relative);
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!match) {
    fail(`${relative}: missing YAML frontmatter`);
    return { data: {}, body: text };
  }
  try {
    const data = parseYaml(match[1]);
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      fail(`${relative}: frontmatter must be a mapping`);
      return { data: {}, body: match[2] };
    }
    return { data, body: match[2] };
  } catch (error) {
    fail(`${relative}: invalid YAML frontmatter: ${error.message}`);
    return { data: {}, body: match[2] };
  }
}

function bodyHash(body) {
  return crypto.createHash("sha256").update(body.replace(/\r\n/g, "\n")).digest("hex");
}

function sectionBody(body, heading) {
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`^## ${escaped}\\s*$`, "m").exec(body);
  if (!match) return "";
  const remainder = body.slice(match.index + match[0].length);
  const next = remainder.search(/^## /m);
  return (next >= 0 ? remainder.slice(0, next) : remainder).trim();
}

function validateReadyBody(relative, body, sections) {
  if (/<[^>\n]+>/.test(body)) fail(`${relative}: executable packet still contains placeholders`);
  for (const section of sections) {
    if (!sectionBody(body, section)) fail(`${relative}: required section is empty or missing: ${section}`);
  }
}

function projectRules(relative) {
  const text = read(relative);
  const match = text.match(
    /<!-- NM-V3-PROJECT-RULES:START -->\s*```yaml\s*([\s\S]*?)\s*```\s*<!-- NM-V3-PROJECT-RULES:END -->/,
  );
  if (!match) {
    fail(`${relative}: missing project-owned rules block`);
    return null;
  }
  try {
    return parseYaml(match[1]);
  } catch (error) {
    fail(`${relative}: invalid project rules YAML: ${error.message}`);
    return null;
  }
}

function projectReference(value, label) {
  if (typeof value !== "string" || value.length === 0 || path.isAbsolute(value)) {
    fail(`${label} must be a non-empty project-relative path`);
    return null;
  }
  const parts = value.split(/[\\/]+/);
  if (parts.includes("..") || parts.includes(".")) {
    fail(`${label} must not contain . or .. path segments: ${value}`);
    return null;
  }
  const absolute = path.resolve(root, value);
  if (absolute !== rootReal && !absolute.startsWith(`${rootReal}${path.sep}`)) {
    fail(`${label} escapes the project root: ${value}`);
    return null;
  }
  if (fs.existsSync(absolute)) {
    const real = fs.realpathSync(absolute);
    if (real !== rootReal && !real.startsWith(`${rootReal}${path.sep}`)) {
      fail(`${label} resolves outside the project root: ${value}`);
      return null;
    }
  }
  return absolute;
}

function requireCore() {
  const files = [
    "AGENTS.md",
    "AGENTS.zh-CN.md",
    ".nm-template-state.json",
    "0c-workflow/WORKFLOW_V3.md",
    "0c-workflow/BRANCHING.md",
    "0c-workflow/VERIFY.md",
    "0c-workflow/SPEC_TEMPLATE.md",
    "0c-workflow/PLAN_TEMPLATE.md",
    "0c-workflow/GOAL_TEMPLATE.md",
    "0c-workflow/NOTIFY_EVENTS.md",
    "0d-scripts/check-workflow.mjs",
    "0d-scripts/verify.sh",
    "0d-scripts/notify-event.sh",
    "0d-scripts/notify-admin.sh",
    "0d-scripts/nm-notify-feishu.sh",
  ];
  for (const file of files) {
    if (!fs.existsSync(path.join(root, file))) fail(`missing core file: ${file}`);
  }
  for (const directory of ["0a-docs", "0b-goals/0a-plans", "0b-goals/0b-current", "0b-goals/0c-archive"]) {
    if (!fs.existsSync(path.join(root, directory))) fail(`missing core directory: ${directory}`);
  }
}

function validateReferences() {
  const english = projectRules("AGENTS.md");
  const chinese = projectRules("AGENTS.zh-CN.md");
  if (!english || !chinese) return;
  if (JSON.stringify(english) !== JSON.stringify(chinese)) {
    fail("AGENTS.md and AGENTS.zh-CN.md project rules differ");
  }
  const references = english.references ?? {};
  if (!Array.isArray(references.required) || !Array.isArray(references.optional)) {
    fail("AGENTS.md project rules references.required and references.optional must be arrays");
    return;
  }
  for (const value of references.required) {
    const file = String(value);
    const absolute = projectReference(value, "required project reference");
    if (!absolute) continue;
    if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) {
      fail(`required project reference is missing: ${file}`);
    } else if (fs.readFileSync(absolute).length === 0) {
      fail(`required project reference is empty: ${file}`);
    }
  }
  for (const value of references.optional) {
    const file = String(value);
    const absolute = projectReference(value, "optional project reference");
    if (!absolute) continue;
    if (!fs.existsSync(absolute) || fs.readFileSync(absolute).length === 0) {
      warn(`optional project reference skipped because it is missing or empty: ${file}`);
    }
  }
  if (!english.verification || typeof english.verification.full_command !== "string") {
    fail("AGENTS.md project rules must declare verification.full_command");
  }
}

function validateSpec() {
  const relative = "0a-docs/spec.md";
  if (!fs.existsSync(path.join(root, relative))) return;
  const { data, body } = frontmatter(relative);
  for (const key of ["schema_version", "spec_version", "workflow_version", "body_sha256", "status", "authors", "reviewers", "administrator_acceptance"]) {
    if (!(key in data)) fail(`${relative}: missing ${key}`);
  }
  if (data.schema_version !== 2) fail(`${relative}: schema_version must be 2`);
  if (data.workflow_version !== "3.1.0") fail(`${relative}: workflow_version must be 3.1.0`);
  if (!["draft", "in_review", "accepted", "superseded"].includes(data.status)) fail(`${relative}: invalid status`);
  const actualHash = bodyHash(body);
  if (data.body_sha256 !== actualHash) fail(`${relative}: body_sha256 does not match the Markdown body`);
  if (!Array.isArray(data.authors) || data.authors.length === 0) fail(`${relative}: authors must be non-empty`);
  for (const actor of [...(data.authors ?? []), ...(data.reviewers ?? [])]) {
    if (!actor || !["human", "agent"].includes(actor.type)) fail(`${relative}: actor type must be human or agent`);
    if (actor?.type === "human" && !actor.name) fail(`${relative}: human actor requires name`);
    if (actor?.type === "agent") {
      for (const key of ["provider", "product", "model"]) if (!actor[key]) fail(`${relative}: agent actor requires ${key}`);
    }
  }
  for (const reviewer of data.reviewers ?? []) {
    if (!reviewer.decision || !reviewer.reviewed_at) fail(`${relative}: reviewer requires decision and reviewed_at`);
    if (!["approved", "changes_requested", "commented"].includes(reviewer.decision)) fail(`${relative}: invalid reviewer decision`);
    if (reviewer.reviewed_spec_version !== data.spec_version) warn(`${relative}: historical reviewer does not cover current spec_version`);
    if (reviewer.reviewed_body_sha256 !== actualHash) warn(`${relative}: historical reviewer does not cover current body hash`);
  }
  const acceptance = data.administrator_acceptance ?? {};
  if (!["pending", "accepted", "changes_requested"].includes(acceptance.status)) {
    fail(`${relative}: invalid administrator_acceptance.status`);
  }
  if (acceptance.status === "accepted") {
    if (
      acceptance.accepted_spec_version !== data.spec_version ||
      acceptance.accepted_body_sha256 !== actualHash ||
      !acceptance.accepted_at ||
      !acceptance.accepted_by
    ) {
      fail(`${relative}: accepted administrator record must bind the current spec version and body hash`);
    }
  }
  if (data.status === "accepted" && acceptance.status !== "accepted") {
    fail(`${relative}: status accepted requires current administrator acceptance`);
  }
  const statePath = path.join(root, ".nm-template-state.json");
  if (fs.existsSync(statePath)) {
    try {
      const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
      const recorded = state.documents?.spec;
      if (!recorded) {
        fail(`${relative}: spec is not stamped in ${path.basename(statePath)}`);
      } else if (recorded.version !== data.spec_version || recorded.bodySha256 !== actualHash) {
        fail(`${relative}: version/body differs from template state; run nm_v3.py spec-stamp after versioning the change`);
      }
    } catch (error) {
      fail(`${relative}: cannot read template state: ${error.message}`);
    }
  }
}

function validatePlans() {
  const states = new Set(["draft", "ready", "in_progress", "awaiting_review", "completed", "needs_replan", "blocked", "cancelled"]);
  const pattern = /^plan-(p[0-9]{3})-[a-z0-9][a-z0-9._-]*\.md$/;
  const plans = new Map();
  for (const relative of relativeFiles("0b-goals/0a-plans")) {
    const match = path.basename(relative).match(pattern);
    if (!match) fail(`${relative}: invalid Plan file name`);
    const { data, body } = frontmatter(relative);
    if (!states.has(data.status)) fail(`${relative}: invalid Plan status`);
    if (match && data.plan_id !== match[1]) fail(`${relative}: plan_id does not match file name`);
    if (match && !new RegExp(`^feature/plan-${match[1]}-[a-z0-9][a-z0-9._-]*$`).test(data.plan_branch ?? "")) {
      fail(`${relative}: plan_branch does not match plan_id`);
    }
    if (data.status !== "draft") validateReadyBody(relative, body, ["Objective", "Scope", "Goal List", "Verification Strategy"]);
    if (["awaiting_review", "completed"].includes(data.status) && data.full_verification_status !== "pass") {
      fail(`${relative}: ${data.status} requires full_verification_status=pass`);
    }
    if (["awaiting_review", "completed"].includes(data.status) && !/^[0-9a-f]{40}$/.test(data.full_verification_commit ?? "")) {
      fail(`${relative}: ${data.status} requires full_verification_commit`);
    }
    if (data.status === "completed" && data.administrator_review_status !== "accepted") {
      fail(`${relative}: completed requires administrator_review_status=accepted`);
    }
    if (match) plans.set(match[1], { relative, data });
  }
  return plans;
}

function validateGoals(plans) {
  const states = new Set(["planned", "in_progress", "reviewing", "verified", "integrated", "archived", "blocked", "cancelled"]);
  const planned = /^goal-(p[0-9]{3})-(g[0-9]{3})-[a-z0-9][a-z0-9._-]*\.md$/;
  const standalone = /^goal-(g[0-9]{3})-[a-z0-9][a-z0-9._-]*\.md$/;
  const files = [...relativeFiles("0b-goals/0b-current"), ...relativeFiles("0b-goals/0c-archive")];
  const goalsByPlan = new Map();
  if (relativeFiles("0b-goals/0b-current").length > 1) fail("0b-goals/0b-current contains more than one active Goal");
  for (const relative of files) {
    const name = path.basename(relative);
    const plannedMatch = name.match(planned);
    const standaloneMatch = name.match(standalone);
    if (!plannedMatch && !standaloneMatch) fail(`${relative}: invalid Goal file name`);
    const { data, body } = frontmatter(relative);
    if (!states.has(data.status)) fail(`${relative}: invalid Goal status`);
    const expectedGoal = plannedMatch?.[2] ?? standaloneMatch?.[1];
    const expectedPlan = plannedMatch?.[1] ?? null;
    if (expectedGoal && data.goal_id !== expectedGoal) fail(`${relative}: goal_id does not match file name`);
    if ((data.plan_id ?? null) !== expectedPlan) fail(`${relative}: plan_id does not match file name`);
    if (data.status !== "planned") validateReadyBody(relative, body, ["Objective", "Scope", "TODO", "Acceptance Criteria", "Verification"]);
    if (expectedPlan) {
      if (!plans.has(expectedPlan)) fail(`${relative}: parent Plan does not exist`);
      if (!new RegExp(`^feature/plan-${expectedPlan}-[a-z0-9][a-z0-9._-]*$`).test(data.base_branch ?? "")) {
        fail(`${relative}: base_branch does not match parent Plan`);
      }
      if (!new RegExp(`^task/goal-${expectedPlan}-${expectedGoal}-[a-z0-9][a-z0-9._-]*$`).test(data.working_branch ?? "")) {
        fail(`${relative}: working_branch does not match Plan/Goal IDs`);
      }
      const list = goalsByPlan.get(expectedPlan) ?? [];
      list.push(data);
      goalsByPlan.set(expectedPlan, list);
    } else {
      if (!new RegExp(`^task/goal-${expectedGoal}-[a-z0-9][a-z0-9._-]*$`).test(data.working_branch ?? "")) {
        fail(`${relative}: standalone working_branch does not match goal_id`);
      }
    }
    if (typeof data.review?.independent_reviewer_required !== "boolean") {
      fail(`${relative}: review.independent_reviewer_required must be boolean`);
    }
    if (["verified", "integrated", "archived"].includes(data.status)) {
      if (data.verification_status !== "pass") fail(`${relative}: ${data.status} requires verification_status=pass`);
      if (data.self_review_status !== "pass") fail(`${relative}: ${data.status} requires self_review_status=pass`);
      if (!/^[0-9a-f]{40}$/.test(data.verification_commit ?? "")) {
        fail(`${relative}: ${data.status} requires verification_commit`);
      }
      if (data.review?.independent_reviewer_required && data.independent_review_status !== "pass") {
        fail(`${relative}: configured independent review must pass before ${data.status}`);
      }
    }
    if (["integrated", "archived"].includes(data.status) && data.integration_status !== "integrated") {
      fail(`${relative}: ${data.status} requires integration_status=integrated`);
    }
    if (["integrated", "archived"].includes(data.status) && !/^[0-9a-f]{40}$/.test(data.integration_commit ?? "")) {
      fail(`${relative}: ${data.status} requires integration_commit`);
    }
  }
  for (const [planId, plan] of plans) {
    if (!["awaiting_review", "completed"].includes(plan.data.status)) continue;
    const goals = goalsByPlan.get(planId) ?? [];
    if (goals.length === 0) fail(`${plan.relative}: reviewable Plan requires at least one Goal`);
    if (goals.some((goal) => !["integrated", "archived"].includes(goal.status))) {
      fail(`${plan.relative}: all Goals must be integrated before Plan review`);
    }
  }
}

function validateProtectedBranch() {
  try {
    const options = { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] };
    const branch = execFileSync("git", ["branch", "--show-current"], options).trim();
    const status = execFileSync("git", ["status", "--short"], options).trim();
    if (["main", "master", "dev"].includes(branch) && status) fail(`working tree is dirty on protected branch ${branch}`);
  } catch {
    warn("Git branch protection check skipped because Git state is unavailable");
  }
}

requireCore();
validateReferences();
validateSpec();
const plans = validatePlans();
validateGoals(plans);
validateProtectedBranch();

for (const message of warnings) console.warn(`WARN: ${message}`);
for (const message of failures) console.error(`FAIL: ${message}`);
if (failures.length > 0) {
  console.error(`Workflow check failed with ${failures.length} issue(s).`);
  process.exit(1);
}
console.log("Workflow check passed.");
