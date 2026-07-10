#!/usr/bin/env python3
"""Credential-free, stateful fake provider for the complete V6 fixture."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


STATE_PATH = Path(".nm-v6-fake-provider.json")
ENVIRONMENT = "project-production"
FINGERPRINT = "fake-project-production-v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_state() -> dict[str, object]:
    if STATE_PATH.exists():
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    return {
        "deployed_version": "v1",
        "healthy": True,
        "operations": {},
    }


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.write_text(
        json.dumps(state, sort_keys=True) + "\n", encoding="utf-8"
    )


def release_binding() -> dict[str, str]:
    fields = {
        "release_source_kind": "NM_V6_RELEASE_SOURCE_KIND",
        "release_source_commit": "NM_V6_RELEASE_SOURCE_COMMIT",
        "release_source_tree": "NM_V6_RELEASE_SOURCE_TREE",
        "tag": "NM_V6_RELEASE_TAG",
        "published_version": "NM_V6_RELEASE_VERSION",
        "release_metadata_digest": "NM_V6_RELEASE_METADATA_DIGEST",
        "stable_commit": "NM_V6_STABLE_COMMIT",
        "stable_tree": "NM_V6_STABLE_TREE",
        "artifact_digest": "NM_V6_ARTIFACT_DIGEST",
        "spec_hash": "NM_V6_SPEC_HASH",
        "config_hash": "NM_V6_CONFIG_HASH",
    }
    return {name: os.environ[source] for name, source in fields.items()}


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    operation = os.environ.get("NM_V6_OPERATION_ID")
    started = now()
    state = load_state()
    operations = state.setdefault("operations", {})
    if not isinstance(operations, dict):
        raise SystemExit(2)

    status = "succeeded"
    artifact = None
    environment = None
    fingerprint = None
    effect = None
    observed: dict[str, object] = {"action": action}

    if action in {"task_verify", "phase_verify", "full_verify"}:
        observed["verified"] = True
    elif action == "build":
        source = os.environ["NM_V6_SOURCE_COMMIT"]
        artifact = hashlib.sha256(source.encode("utf-8")).hexdigest()
        observed["release_source_commit"] = source
    elif action == "release_metadata":
        metadata_binding = {
            "release_source_kind": os.environ["NM_V6_RELEASE_SOURCE_KIND"],
            "release_source_commit": os.environ["NM_V6_RELEASE_SOURCE_COMMIT"],
            "release_source_tree": os.environ["NM_V6_RELEASE_SOURCE_TREE"],
            "spec_hash": os.environ["NM_V6_SPEC_HASH"],
            "config_hash": os.environ["NM_V6_CONFIG_HASH"],
        }
        changelog_digest = hashlib.sha256(
            json.dumps(metadata_binding, sort_keys=True).encode("utf-8")
        ).hexdigest()
        observed = {
            **metadata_binding,
            "tag": "v0.1.0",
            "published_version": "0.1.0",
            "changelog_digest": changelog_digest,
        }
    elif action in {"release", "publish"}:
        if not operation:
            raise SystemExit(2)
        binding: dict[str, object] = release_binding()
        if action == "publish":
            binding.update(
                {
                    "tag": "v0.1.0",
                    "tag_target": binding["stable_commit"],
                    "published_version": "0.1.0",
                }
            )
        artifact = str(binding["artifact_digest"])
        effect = f"fake-{action}-{operation}"
        binding.update(
            {
                "action": action,
                "classification": "completed",
                "effect_id": effect,
            }
        )
        operations[operation] = binding
        save_state(state)
        observed = binding
        if Path(f"force-{action}-partial").exists():
            status = "partial"
        elif Path(f"force-{action}-unknown").exists():
            status = "unknown"
    elif action in {
        "observe_release",
        "reconcile_release",
        "observe_publish",
        "reconcile_publish",
    }:
        record = operations.get(operation or "")
        if isinstance(record, dict):
            observed = dict(record)
            observed["classification"] = (
                "unknown"
                if action.startswith("observe_")
                and Path(f"force-{action}-unknown").exists()
                else "completed"
            )
            artifact_value = record.get("artifact_digest")
            artifact = str(artifact_value) if artifact_value else None
        else:
            observed = {"action": action, "classification": "not_started"}
    elif action == "identity_probe":
        environment = ENVIRONMENT
        fingerprint = FINGERPRINT
        observed = {
            "deployed_version": state.get("deployed_version", "v1"),
            "artifact_digest": state.get("artifact_digest"),
        }
    elif action == "preflight":
        environment = ENVIRONMENT
        fingerprint = FINGERPRINT
        observed = {"ready": True}
    elif action == "deploy":
        if not operation:
            raise SystemExit(2)
        artifact = os.environ["NM_V6_ARTIFACT_DIGEST"]
        environment = os.environ["NM_V6_ENVIRONMENT_ID"]
        fingerprint = os.environ["NM_V6_ENVIRONMENT_FINGERPRINT"]
        effect = f"fake-deploy-{operation}"
        record = {
            "action": action,
            "classification": "completed",
            "effect_id": effect,
            "artifact_digest": artifact,
            "environment_id": environment,
            "environment_fingerprint": fingerprint,
            "deployed_version": "v2",
        }
        operations[operation] = record
        state.update(
            {
                "deployed_version": "v2",
                "artifact_digest": artifact,
                "healthy": not Path("force-unhealthy").exists(),
            }
        )
        save_state(state)
        observed = record
        if Path("force-deploy-partial").exists():
            status = "partial"
        elif Path("force-deploy-unknown").exists():
            status = "unknown"
    elif action == "rollback":
        if not operation:
            raise SystemExit(2)
        target = os.environ["NM_V6_ROLLBACK_TARGET"]
        environment = os.environ["NM_V6_ENVIRONMENT_ID"]
        fingerprint = os.environ["NM_V6_ENVIRONMENT_FINGERPRINT"]
        effect = f"fake-rollback-{operation}"
        failed = Path("force-rollback-failure").exists()
        record = {
            "action": action,
            "classification": "failed" if failed else "completed",
            "effect_id": effect,
            "environment_id": environment,
            "environment_fingerprint": fingerprint,
            "deployed_version": target,
        }
        operations[operation] = record
        if not failed:
            state.update({"deployed_version": target, "healthy": True})
        save_state(state)
        observed = record
        if failed:
            status = "failed"
        elif Path("force-rollback-partial").exists():
            status = "partial"
        elif Path("force-rollback-unknown").exists():
            status = "unknown"
    elif action in {"observe_deploy", "reconcile_deploy"}:
        environment = ENVIRONMENT
        fingerprint = FINGERPRINT
        record = operations.get(operation or "")
        if isinstance(record, dict):
            observed = dict(record)
            observed["classification"] = (
                "unknown"
                if action == "observe_deploy"
                and Path("force-observe-deploy-unknown").exists()
                else str(record.get("classification", "completed"))
            )
            artifact_value = record.get("artifact_digest")
            artifact = str(artifact_value) if artifact_value else None
        else:
            observed = {"action": action, "classification": "not_started"}
    elif action == "health":
        environment = ENVIRONMENT
        fingerprint = FINGERPRINT
        artifact_value = state.get("artifact_digest")
        artifact = str(artifact_value) if artifact_value else None
        observed = {
            "healthy": bool(state.get("healthy", True))
            and not Path("force-unhealthy").exists(),
            "deployed_version": state.get("deployed_version", "v1"),
            "artifact_digest": artifact,
        }
    elif action == "post_rollback_verify":
        environment = ENVIRONMENT
        fingerprint = FINGERPRINT
        observed = {
            "healthy": not Path("force-post-rollback-failure").exists(),
            "deployed_version": state.get("deployed_version", "v1"),
        }
    else:
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "protocol_version": "nm-v6/action-result-v1",
                "action_id": action,
                "operation_id": operation,
                "status": status,
                "effect_id": effect,
                "artifact_digest": artifact,
                "environment_id": environment,
                "environment_fingerprint": fingerprint,
                "observed_state": observed,
                "started_at": started,
                "finished_at": now(),
                "diagnostics": {},
                "redactions": [],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
