---
name: nm-init-project-v6
description: Initialize, update, check, inspect, or operate projects that use the NotMaster NM V6 transactional workflow. Use when an agent needs to install the V6 template, run its lifecycle CLI, inspect status or evidence, prepare an authorization request, reconcile an interrupted run, or validate a generated V6 project without treating model output as gate evidence.
---

# NM Init Project V6

Use the deterministic V6 CLI. Do not reproduce workflow state, gates, approval,
Git integration, release, or deployment logic in this Skill.

## Entry point

Prefer the repository runtime selector in a trusted local `nm-docs` checkout:

```bash
bash /path/to/nm-docs/tools/nm-v6/python311.sh \
  /path/to/nm-docs/tools/nm-v6/nm_v6.py --help
```

After installation, use the bundled wrapper. The installer binds it to one
reviewed checkout; it never searches the current directory or downloads code:

```bash
python3 "$HOME/.agents/skills/nm-init-project-v6/scripts/run_nm_v6.py" --help
```

If `NM_DOCS_DIR` is set, it must equal the installed source binding. Reinstall
the Skill after a reviewed V6 core update or checkout move.

## Safe workflow

1. For an existing V6 project, run `check` before a lifecycle operation. For a
   first-time empty target, run `init --dry-run`, review the plan, then `init`.
2. Treat `status`, audit exports, worker reports, and process exit codes as
   observations. Only core gate receipts advance hard gates.
3. Agents may create confirmation or authorization requests. Import an approval
   only when it carries a signature from a configured trusted authenticator.
4. Use `staged` unless the administrator has approved an exact persisted `auto`
   scope through the trusted control plane.
5. Stop on a dirty authoritative tree, unknown remote state, moved protected
   ref, missing sandbox backend, invalid evidence, or reconciliation ambiguity.
6. Never expose secret values to an agent invocation or pass them on the command
   line.

## Common commands

```bash
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py init --target /absolute/project --source-dir /path/to/nm-docs --dry-run
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py init --target /absolute/project --source-dir /path/to/nm-docs
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py update --target /absolute/project --source-dir /path/to/nm-docs --dry-run
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py check --target /absolute/project
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py status --target /absolute/project --json
bash tools/nm-v6/python311.sh tools/nm-v6/nm_v6.py reconcile --target /absolute/project
```

Run generated-project verification inside the project:

```bash
npm run workflow:check
npm run workflow:test
npm run verify
```

## References

- Read `references/install.md` only for checkout discovery or Skill installation.
- Read `references/trusted-control-plane.md` only for confirmation, grants,
  revocation, or an administrator approval handoff.
