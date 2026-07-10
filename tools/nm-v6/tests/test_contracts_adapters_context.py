from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from nmv6.adapters import ClaudeAdapter, CodexAdapter, FakeAdapter, GrokAdapter, MemoryBackend
from nmv6.actions import ActionDefinition, ActionResult
from nmv6.context import (
    ContextItem,
    apply_on_demand_proposal,
    build_context_manifest,
    propose_on_demand_addition,
)
from nmv6.contracts import (
    validate_action_result,
    validate_adapter_result,
    validate_audit_export,
    validate_context_manifest,
    validate_project_config,
    validate_status_document,
    validate_version_record,
)
from nmv6.errors import ContractError
from nmv6.merge_review import (
    MERGE_REVIEW_CONTEXT_SOURCE,
    OBSERVATION_SCHEMA_VERSION,
    REQUEST_SCHEMA_VERSION,
    deterministic_fake_merge_review,
    merge_review_context_item,
    seal_merge_review_observation,
    seal_merge_review_request,
    validate_merge_review_observation,
    validate_merge_review_observations,
    validate_merge_review_request,
    validate_merge_reviewer_adapter_result,
)
from nmv6.specs import (
    canonical_spec_hash,
    criteria_due_by_stage,
    validate_optional_task_skip,
    validate_spec,
    validate_traceability,
)
from nmv6.supply_chain import (
    CONFIGURED_RUNTIME_EVALUATOR_VERSION,
    collect_project_runtime_versions,
    detect_version_drift,
    reject_v5_runtime,
    validate_bilingual_pair,
    validate_credential_free_environment,
    validate_dependency_constraints,
    validate_install_plan_hashes,
    validate_legacy_preservation,
    validate_no_mutable_runtime_markdown,
    validate_provider_update_policy,
    validate_schema_catalog,
    validate_template_manifest,
    verify_downloaded_artifact,
)
from nmv6.util import canonical_json, sha256_bytes


REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "docs" / "nm-v6-workflow-spec.md"
PROJECT_EXAMPLE = REPO_ROOT / "template" / "v6" / "project.example.json"


def valid_graph() -> dict:
    return {
        "goals": [{"goal_id": "GOAL-001"}],
        "requirements": [{"requirement_id": "REQ-001", "goal_ids": ["GOAL-001"]}],
        "acceptance_criteria": [
            {
                "acceptance_id": "AC-001",
                "requirement_ids": ["REQ-001"],
                "mandatory": True,
                "required_by_stage": "task",
            },
            {
                "acceptance_id": "AC-002",
                "requirement_ids": ["REQ-001"],
                "mandatory": True,
                "required_by_stage": "deploy",
                "action_id": "health",
            },
        ],
        "phases": [
            {"phase_id": "PHASE-001", "depends_on": []},
            {"phase_id": "PHASE-002", "depends_on": ["PHASE-001"]},
        ],
        "tasks": [
            {
                "task_id": "TASK-001",
                "phase_id": "PHASE-001",
                "acceptance_ids": ["AC-001"],
                "enabling_requirement_ids": [],
                "dependencies": [],
                "optional": False,
            }
        ],
        "acceptance_actions": {"AC-002": "health"},
        "required_delivery_stages": {
            "release": "required",
            "deploy": "required",
            "environments": ["production"],
        },
    }


def context_items() -> list[ContextItem]:
    return [
        ContextItem("invariant", "AGENTS.md#safety", "Never mutate protected refs."),
        ContextItem("goal", "SPEC#GOAL-001", "GOAL-001 deliver the change."),
        ContextItem("requirement", "SPEC#REQ-001", "REQ-001 preserve behavior."),
        ContextItem("acceptance", "SPEC#AC-001", "AC-001 tests pass."),
        ContextItem("phase", "SPEC#PHASE-001", "PHASE-001 implementation."),
        ContextItem("task", "SPEC#TASK-001", "TASK-001 edit assigned paths."),
        ContextItem("acceptance_action", "project.json#full_verify", "Run full_verify."),
    ]


def build_manifest(tmp: str, *, on_demand: tuple[ContextItem, ...] = ()) -> dict:
    return build_context_manifest(
        attempt_id="ATTEMPT-run-001",
        items=context_items(),
        on_demand_items=on_demand,
        allowed_paths=["src"],
        prohibited_paths=[".nm/runtime"],
        max_manifest_bytes=100_000,
        max_estimated_tokens=10_000,
    )


def adapter_request(workspace: str, manifest: dict) -> dict:
    return {
        "protocol_version": "nm-v6/adapter-request-v1",
        "operation_id": "OP-run-001",
        "run_id": "run",
        "attempt_id": "ATTEMPT-run-001",
        "role": "worker",
        "workspace": workspace,
        "context_manifest": manifest,
        "expected_output_schema": "nm-v6/adapter-result-v1",
        "deadline": "2030-01-01T00:00:00Z",
        "fencing_token": 1,
        "allowed_capabilities": ["workspace_write"],
    }


def version_record(*, core: str = "6.0.0") -> dict:
    return {
        "schema_version": "nm-v6/version-record-v1",
        "python": "3.12.13",
        "sqlite": "3.45.0",
        "git": "git version 2.45.0",
        "core_cli": core,
        "schemas": {"project": "nm-v6/project-v1"},
        "evaluator": "nm-v6/evaluator-v1",
        "adapters": {"fake": "nm-v6/fake-adapter-v1"},
    }


def merge_review_request_document() -> dict:
    source_commit = "a" * 40
    target_commit = "b" * 40
    source_tree = "c" * 40
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "review_id": "REVIEW-run-001",
        "run_id": "run",
        "spec_hash": "d" * 64,
        "config_hash": "e" * 64,
        "route": "work_to_dev",
        "source_kind": "work_branch",
        "target_kind": "dev",
        "source_ref": "refs/heads/task/example",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "target_ref": "refs/heads/dev",
        "target_commit": target_commit,
        "target_tree": "f" * 40,
        "purpose": "integrate one verified Phase",
        "sharing_status": "local-unpublished",
        "topology": {
            "merge_base": target_commit,
            "target_is_ancestor": True,
            "source_is_ancestor": False,
            "source_only_commits": 1,
            "target_only_commits": 0,
        },
        "commit_quality": {
            "commit_count": 1,
            "merge_commit_count": 0,
            "fixup_commit_count": 0,
            "commits_suitable": True,
            "single_logical_change": True,
            "disposable": True,
        },
        "audit_boundary_required": False,
        "rollback_boundary_required": False,
        "rollback_ref": "refs/nm-v6/rollback/run/dev",
        "allowed_strategies": ["fast_forward", "squash", "merge_commit"],
        "strategy_results": {
            "fast_forward": {
                "valid": True,
                "conflict": False,
                "expected_result_tree": source_tree,
            },
            "squash": {
                "valid": True,
                "conflict": False,
                "expected_result_tree": source_tree,
            },
            "merge_commit": {
                "valid": True,
                "conflict": False,
                "expected_result_tree": source_tree,
            },
        },
        "exact_source_tree_required": False,
        "future_gate_id": "GATE-run-001",
        "authorization_id": "AUTH-run-001",
    }


def proposed_merge_observation(
    request: dict, *, strategy: str, expected_tree: str
) -> dict:
    return seal_merge_review_observation(
        {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "review_id": request["review_id"],
            "request_digest": request["request_digest"],
            "route": request["route"],
            "source_commit": request["source_commit"],
            "target_commit": request["target_commit"],
            "candidate_tree": request["source_tree"],
            "decision": "propose",
            "strategy": strategy,
            "rationale": "fixture reviewer proposal",
            "expected_result_tree": expected_tree,
            "risk_flags": [],
        }
    )


def merge_reviewer_adapter_request(workspace: str) -> tuple[dict, dict]:
    review_request = seal_merge_review_request(merge_review_request_document())
    manifest = build_context_manifest(
        attempt_id="ATTEMPT-run-001",
        items=(*context_items(), merge_review_context_item(review_request)),
        allowed_paths=[],
        prohibited_paths=[".nm/runtime"],
        max_manifest_bytes=100_000,
        max_estimated_tokens=10_000,
    )
    request = adapter_request(workspace, manifest)
    request["role"] = "merge_reviewer"
    request["allowed_capabilities"] = []
    return review_request, request


class SpecTests(unittest.TestCase):
    def test_repository_spec_hash_matches_confirmed_fixture(self) -> None:
        self.assertEqual(
            canonical_spec_hash(SPEC_PATH),
            "62196ab27c2be08ea1c716081903a009185f1d518ba7a53ed9b3d8485236cb7f",
        )
        self.assertEqual(validate_spec(SPEC_PATH).metadata["workflow"], "v6")

    def test_hash_normalizes_line_endings_trailing_lf_and_frontmatter_order(self) -> None:
        fields = [
            "spec_id: SPEC-X-V1",
            "document_title: Example",
            "version: 1",
            "workflow: v6",
            "language: en",
            "normative: true",
            "admin_mirror: example.zh-CN.md",
            "status: review-ready",
            "implementation_authorized: false",
        ]
        lf = "---\n" + "\n".join(fields) + "\n---\nBody\n\n"
        crlf = "---\r\n" + "\r\n".join(reversed(fields)) + "\r\n---\r\nBody\r\n"
        self.assertEqual(canonical_spec_hash(lf), canonical_spec_hash(crlf))
        changed_control = lf.replace("review-ready", "confirmed").replace("false", "true")
        self.assertEqual(canonical_spec_hash(lf), canonical_spec_hash(changed_control))
        self.assertNotEqual(canonical_spec_hash(lf), canonical_spec_hash(lf.replace("Body", "Body!")))

    def test_hash_rejects_unknown_missing_duplicate_and_bom_frontmatter(self) -> None:
        source = SPEC_PATH.read_text(encoding="utf-8")
        with self.assertRaises(ContractError):
            canonical_spec_hash(source.replace("status: review-ready", "extra: nope"))
        with self.assertRaises(ContractError):
            canonical_spec_hash(source.replace("workflow: v6\n", ""))
        with self.assertRaises(ContractError):
            canonical_spec_hash(source.replace("workflow: v6", "workflow: v6\nworkflow: v6"))
        with self.assertRaises(ContractError):
            canonical_spec_hash("\ufeff" + source)

    def test_traceability_and_stage_due_semantics(self) -> None:
        report = validate_traceability(valid_graph())
        self.assertEqual(report.mandatory_acceptance_ids, ("AC-001", "AC-002"))
        acceptance = valid_graph()["acceptance_criteria"]
        self.assertEqual(criteria_due_by_stage(acceptance, "release"), ("AC-001",))
        self.assertEqual(criteria_due_by_stage(acceptance, "completion"), ("AC-001", "AC-002"))

    def test_traceability_rejects_missing_coverage_invalid_stage_and_cycles(self) -> None:
        graph = valid_graph()
        graph["tasks"][0]["acceptance_ids"] = []
        with self.assertRaisesRegex(ContractError, "trace|coverage"):
            validate_traceability(graph)
        graph = valid_graph()
        graph["acceptance_criteria"][0]["required_by_stage"] = "later"
        with self.assertRaisesRegex(ContractError, "required_by_stage"):
            validate_traceability(graph)
        graph = valid_graph()
        graph["phases"][0]["depends_on"] = ["PHASE-002"]
        with self.assertRaisesRegex(ContractError, "cycle"):
            validate_traceability(graph)

    def test_traceability_requires_canonical_delivery_stage_decisions(self) -> None:
        graph = valid_graph()
        graph["required_delivery_stages"]["environments"] = ["staging", "production"]
        validate_traceability(graph)

        invalid_cases = (
            (["release", "deploy"], "must be an object"),
            ({"deploy": "required", "environments": ["production"]}, "missing required fields"),
            ({"release": "required", "environments": []}, "missing required fields"),
            ({"release": "required", "deploy": "required"}, "missing required fields"),
            (
                {
                    "release": "later",
                    "deploy": "not_applicable",
                    "environments": [],
                },
                "release is invalid",
            ),
            (
                {
                    "release": "required",
                    "deploy": "required",
                    "environments": ["production", "production"],
                },
                "must not contain duplicates",
            ),
            (
                {
                    "release": "required",
                    "deploy": "required",
                    "environments": [],
                },
                "at least one target environment",
            ),
            (
                {
                    "release": "required",
                    "deploy": "not_applicable",
                    "environments": ["production"],
                },
                "must declare no target environments",
            ),
            (
                {
                    "release": "not_applicable",
                    "deploy": "required",
                    "environments": ["production"],
                },
                "cannot be required",
            ),
        )
        for delivery_stages, message in invalid_cases:
            with self.subTest(delivery_stages=delivery_stages):
                graph = valid_graph()
                graph["required_delivery_stages"] = delivery_stages
                with self.assertRaisesRegex(ContractError, message):
                    validate_traceability(graph)

        graph = valid_graph()
        graph["required_delivery_stages"] = {
            "release": "not_applicable",
            "deploy": "not_applicable",
            "environments": [],
        }
        validate_traceability(graph)

    def test_cross_phase_task_dependency_accepts_direct_phase_ancestor(self) -> None:
        graph = valid_graph()
        graph["tasks"].append(
            {
                "task_id": "TASK-002",
                "phase_id": "PHASE-002",
                "acceptance_ids": ["AC-001"],
                "dependencies": ["TASK-001"],
                "optional": False,
            }
        )

        validate_traceability(graph)

    def test_cross_phase_task_dependency_accepts_transitive_phase_ancestor(self) -> None:
        graph = valid_graph()
        graph["phases"].append(
            {"phase_id": "PHASE-003", "depends_on": ["PHASE-002"]}
        )
        graph["tasks"].append(
            {
                "task_id": "TASK-003",
                "phase_id": "PHASE-003",
                "acceptance_ids": ["AC-001"],
                "dependencies": ["TASK-001"],
                "optional": False,
            }
        )

        validate_traceability(graph)

    def test_cross_phase_task_dependency_rejects_unordered_phase(self) -> None:
        graph = valid_graph()
        graph["phases"][1]["depends_on"] = []
        graph["tasks"].append(
            {
                "task_id": "TASK-002",
                "phase_id": "PHASE-002",
                "acceptance_ids": ["AC-001"],
                "dependencies": ["TASK-001"],
                "optional": False,
            }
        )

        with self.assertRaisesRegex(
            ContractError,
            "PHASE-001 is not a declared ancestor of PHASE-002",
        ):
            validate_traceability(graph)

    def test_cross_phase_task_dependency_rejects_descendant_phase(self) -> None:
        graph = valid_graph()
        graph["tasks"].append(
            {
                "task_id": "TASK-002",
                "phase_id": "PHASE-002",
                "acceptance_ids": ["AC-001"],
                "dependencies": [],
                "optional": False,
            }
        )
        graph["tasks"][0]["dependencies"] = ["TASK-002"]

        with self.assertRaisesRegex(
            ContractError,
            "PHASE-002 is not a declared ancestor of PHASE-001",
        ):
            validate_traceability(graph)

    def test_optional_skip_requires_remaining_mandatory_coverage(self) -> None:
        graph = valid_graph()
        graph["tasks"][0]["optional"] = True
        with self.assertRaisesRegex(ContractError, "leaves mandatory"):
            validate_optional_task_skip(graph, skipped_task_id="TASK-001")
        graph["tasks"].append(
            {
                "task_id": "TASK-002",
                "phase_id": "PHASE-002",
                "acceptance_ids": ["AC-001"],
                "dependencies": [],
                "optional": False,
            }
        )
        validate_optional_task_skip(graph, skipped_task_id="TASK-001")


class MergeReviewContractTests(unittest.TestCase):
    def test_deterministic_fake_reviewer_covers_every_decision(self) -> None:
        cases: list[tuple[str, dict, str, str | None]] = []

        fast_forward = merge_review_request_document()
        cases.append(("fast_forward", fast_forward, "propose", "fast_forward"))

        squash = merge_review_request_document()
        squash["topology"]["source_only_commits"] = 2
        squash["commit_quality"].update(
            {
                "commit_count": 2,
                "fixup_commit_count": 1,
                "commits_suitable": False,
            }
        )
        cases.append(("squash", squash, "propose", "squash"))

        merge_commit = merge_review_request_document()
        merge_commit["audit_boundary_required"] = True
        cases.append(("merge_commit", merge_commit, "propose", "merge_commit"))

        cannot = merge_review_request_document()
        cannot["topology"] = {
            "merge_base": "9" * 40,
            "target_is_ancestor": False,
            "source_is_ancestor": False,
            "source_only_commits": 1,
            "target_only_commits": 1,
        }
        cannot["strategy_results"] = {
            "fast_forward": {
                "valid": False,
                "conflict": False,
                "expected_result_tree": None,
            },
            "squash": {
                "valid": False,
                "conflict": True,
                "expected_result_tree": None,
            },
            "merge_commit": {
                "valid": False,
                "conflict": True,
                "expected_result_tree": None,
            },
        }
        cases.append(("cannot_propose", cannot, "cannot_propose", None))

        for name, document, expected_decision, expected_strategy in cases:
            with self.subTest(decision=name):
                request = seal_merge_review_request(document)
                observation = deterministic_fake_merge_review(request)
                self.assertEqual(observation["decision"], expected_decision)
                self.assertEqual(observation["strategy"], expected_strategy)
                self.assertEqual(
                    validate_merge_review_observations(request, [observation]),
                    observation,
                )

    def test_request_digest_route_topology_and_exact_tree_fail_closed(self) -> None:
        request = seal_merge_review_request(merge_review_request_document())
        request["purpose"] = "tampered after sealing"
        with self.assertRaisesRegex(ContractError, "digest mismatch"):
            validate_merge_review_request(request)

        invalid_route = merge_review_request_document()
        invalid_route["route"] = "dev_to_stable"
        with self.assertRaisesRegex(ContractError, "kinds do not match"):
            seal_merge_review_request(invalid_route)

        invalid_topology = merge_review_request_document()
        invalid_topology["topology"]["merge_base"] = invalid_topology["source_commit"]
        with self.assertRaisesRegex(ContractError, "target-ancestor topology"):
            seal_merge_review_request(invalid_topology)

        missing_exact_tree = merge_review_request_document()
        missing_exact_tree.update(
            {
                "route": "dev_to_stable",
                "source_kind": "dev",
                "target_kind": "stable",
            }
        )
        with self.assertRaisesRegex(ContractError, "exact verified source tree"):
            seal_merge_review_request(missing_exact_tree)

        wrong_exact_tree = copy.deepcopy(missing_exact_tree)
        wrong_exact_tree["exact_source_tree_required"] = True
        other_tree = "7" * 40
        for strategy in ("squash", "merge_commit"):
            wrong_exact_tree["strategy_results"][strategy][
                "expected_result_tree"
            ] = other_tree
        with self.assertRaisesRegex(ContractError, "exact-source-tree"):
            seal_merge_review_request(wrong_exact_tree)

    def test_observation_fail_closed_matrix(self) -> None:
        request = seal_merge_review_request(merge_review_request_document())
        valid = deterministic_fake_merge_review(request)

        malformed = {**valid, "unexpected": True}
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            validate_merge_review_observation(malformed)

        digest_tampered = {**valid, "rationale": "changed after sealing"}
        with self.assertRaisesRegex(ContractError, "digest mismatch"):
            validate_merge_review_observation(digest_tampered)

        stale = seal_merge_review_observation(
            {**{key: value for key, value in valid.items() if key != "observation_digest"},
             "request_digest": "0" * 64}
        )
        with self.assertRaisesRegex(ContractError, "stale request_digest"):
            validate_merge_review_observations(request, [stale])

        with self.assertRaisesRegex(ContractError, "exactly one"):
            validate_merge_review_observations(request, [valid, valid])

        disabled_document = merge_review_request_document()
        disabled_document["allowed_strategies"] = ["fast_forward"]
        disabled_request = seal_merge_review_request(disabled_document)
        disabled = proposed_merge_observation(
            disabled_request,
            strategy="squash",
            expected_tree=disabled_request["source_tree"],
        )
        with self.assertRaisesRegex(ContractError, "disabled"):
            validate_merge_review_observations(disabled_request, [disabled])

        wrong_tree = proposed_merge_observation(
            request, strategy="fast_forward", expected_tree="8" * 40
        )
        with self.assertRaisesRegex(ContractError, "core simulation"):
            validate_merge_review_observations(request, [wrong_tree])

    def test_merge_review_schemas_are_catalogued_and_strict(self) -> None:
        catalog = validate_schema_catalog(REPO_ROOT / "tools/nm-v6/schemas")
        for name in (
            "merge-review-request-v1.schema.json",
            "merge-review-observation-v1.schema.json",
        ):
            identifier = f"https://notmaster.dev/nm-v6/schemas/{name}"
            self.assertEqual(catalog[identifier], name)
            schema = json.loads(
                (REPO_ROOT / "tools/nm-v6/schemas" / name).read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]))

    def test_merge_reviewer_adapter_envelope_is_read_only_and_exact(self) -> None:
        request = seal_merge_review_request(merge_review_request_document())
        with tempfile.TemporaryDirectory() as directory:
            manifest = build_context_manifest(
                attempt_id="ATTEMPT-run-001",
                items=(*context_items(), merge_review_context_item(request)),
                allowed_paths=[],
                prohibited_paths=[".nm/runtime"],
                max_manifest_bytes=100_000,
                max_estimated_tokens=10_000,
            )
            envelope = adapter_request(str(Path(directory).resolve()), manifest)
            envelope["role"] = "merge_reviewer"
            envelope["allowed_capabilities"] = []
            session_id = "SESSION-fake-merge-review"
            result = {
                "protocol_version": "nm-v6/adapter-result-v1",
                "operation_id": envelope["operation_id"],
                "attempt_id": envelope["attempt_id"],
                "status": "succeeded",
                "session_id": session_id,
                "candidate_commit": None,
                "changed_paths": [],
                "observations": [deterministic_fake_merge_review(request)],
                "requested_followups": [],
                "usage": {},
                "adapter_diagnostics": {"backend": "fixture"},
            }
            validated = validate_merge_reviewer_adapter_result(
                result,
                adapter_request=envelope,
                review_request=request,
                expected_session_id=session_id,
            )
            self.assertEqual(validated["status"], "succeeded")

            wrong_role = {**envelope, "role": "worker"}
            with self.assertRaisesRegex(ContractError, "wrong role"):
                validate_merge_reviewer_adapter_result(
                    result,
                    adapter_request=wrong_role,
                    review_request=request,
                    expected_session_id=session_id,
                )
            writable = {**envelope, "allowed_capabilities": ["workspace_write"]}
            with self.assertRaisesRegex(ContractError, "zero capabilities"):
                validate_merge_reviewer_adapter_result(
                    result,
                    adapter_request=writable,
                    review_request=request,
                    expected_session_id=session_id,
                )
            missing_context = {
                **envelope,
                "context_manifest": build_context_manifest(
                    attempt_id="ATTEMPT-run-001",
                    items=context_items(),
                    allowed_paths=[],
                    prohibited_paths=[".nm/runtime"],
                    max_manifest_bytes=100_000,
                    max_estimated_tokens=10_000,
                ),
            }
            with self.assertRaisesRegex(ContractError, "exactly one request entry"):
                validate_merge_reviewer_adapter_result(
                    result,
                    adapter_request=missing_context,
                    review_request=request,
                    expected_session_id=session_id,
                )
            invalid_results = (
                ({**result, "status": "failed"}, "did not succeed"),
                ({**result, "session_id": "SESSION-other"}, "stale session_id"),
                ({**result, "candidate_commit": "1" * 40}, "candidate commit"),
                ({**result, "changed_paths": ["changed.txt"]}, "changed paths"),
                (
                    {**result, "requested_followups": [{"kind": "retry"}]},
                    "follow-up",
                ),
            )
            for invalid, message in invalid_results:
                with self.subTest(adapter_result=message), self.assertRaisesRegex(
                    ContractError, message
                ):
                    validate_merge_reviewer_adapter_result(
                        invalid,
                        adapter_request=envelope,
                        review_request=request,
                        expected_session_id=session_id,
                    )


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = json.loads(PROJECT_EXAMPLE.read_text(encoding="utf-8"))

    def test_complete_project_example_validates(self) -> None:
        validate_project_config(self.project)
        self.assertNotIn("required_delivery_stages", self.project)
        release_metadata = self.project["action_definitions"][
            self.project["actions"]["release_metadata"]
        ]
        self.assertEqual(release_metadata["kind"], "pure")
        self.assertEqual(release_metadata["secret_refs"], [])
        required_metadata_env = {
            "NM_V6_RELEASE_TAG",
            "NM_V6_RELEASE_VERSION",
            "NM_V6_RELEASE_METADATA_DIGEST",
        }
        for logical_name in ("release", "publish"):
            definition = self.project["action_definitions"][
                self.project["actions"][logical_name]
            ]
            self.assertTrue(
                required_metadata_env.issubset(definition["core_injected_env"])
            )
        project = copy.deepcopy(self.project)
        project["action_definitions"]["full_verify"]["env_allowlist"] = [
            "PATH",
            "LANG",
            "LC_ALL",
            "TZ",
            "TERM",
            "NO_COLOR",
            "CI",
        ]
        validate_project_config(project)
        action_schema = json.loads(
            (TOOLS_ROOT / "schemas" / "action-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            {"PATH", "LANG", "LC_ALL", "TZ", "TERM", "NO_COLOR", "CI"},
            set(
                action_schema["$defs"]["inheritedEnvNames"]["items"]["enum"]
            ),
        )
        for field in ("observe_action_id", "reconcile_action_id"):
            with self.subTest(required_nullable_field=field):
                project = copy.deepcopy(self.project)
                del project["action_definitions"]["full_verify"][field]
                with self.assertRaisesRegex(ContractError, "missing"):
                    validate_project_config(project)

    def test_project_rejects_stage_authority_and_unsafe_release_metadata(self) -> None:
        project = copy.deepcopy(self.project)
        project["required_delivery_stages"] = {
            "release": "required",
            "deploy": "required",
            "environments": ["production"],
        }
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            validate_project_config(project)

        project = copy.deepcopy(self.project)
        del project["actions"]["release_metadata"]
        with self.assertRaisesRegex(ContractError, "release_metadata"):
            validate_project_config(project)

        project = copy.deepcopy(self.project)
        metadata = project["action_definitions"]["release_metadata"]
        metadata["kind"] = "external_observe"
        metadata["idempotency"] = "read_only"
        with self.assertRaisesRegex(ContractError, "release_metadata must resolve to a pure"):
            validate_project_config(project)

        project = copy.deepcopy(self.project)
        project["action_definitions"]["release_metadata"]["secret_refs"] = [
            "release_token"
        ]
        with self.assertRaisesRegex(ContractError, "release_metadata must not reference secrets"):
            validate_project_config(project)

        for logical_name in ("release", "publish"):
            with self.subTest(logical_action=logical_name):
                project = copy.deepcopy(self.project)
                definition = project["action_definitions"][
                    project["actions"][logical_name]
                ]
                definition["core_injected_env"].remove("NM_V6_RELEASE_TAG")
                with self.assertRaisesRegex(
                    ContractError, f"{logical_name} must declare release metadata injection"
                ):
                    validate_project_config(project)

    def test_fake_release_metadata_action_returns_bound_metadata(self) -> None:
        metadata_environment = {
            "NM_V6_RELEASE_SOURCE_KIND": "dev",
            "NM_V6_RELEASE_SOURCE_COMMIT": "a" * 40,
            "NM_V6_RELEASE_SOURCE_TREE": "b" * 40,
            "NM_V6_SPEC_HASH": "c" * 64,
            "NM_V6_CONFIG_HASH": "d" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "template/v6/0d-scripts/fake-action.py"),
                    "release_metadata",
                ],
                cwd=directory,
                env={**os.environ, **metadata_environment},
                check=True,
                capture_output=True,
                text=True,
            )
        result = json.loads(completed.stdout)
        validate_action_result(
            result,
            definition=self.project["action_definitions"]["release_metadata"],
        )
        observed = result["observed_state"]
        self.assertEqual(observed["tag"], "v0.1.0")
        self.assertEqual(observed["published_version"], "0.1.0")
        self.assertRegex(observed["changelog_digest"], r"^[0-9a-f]{64}$")
        for key, value in metadata_environment.items():
            observed_key = key.removeprefix("NM_V6_").lower()
            self.assertEqual(observed[observed_key], value)

    def test_project_rejects_branch_shell_secret_and_incomplete_delivery(self) -> None:
        project = copy.deepcopy(self.project)
        project["git"]["integration_branch"] = "integration"
        with self.assertRaises(ContractError):
            validate_project_config(project)
        project = copy.deepcopy(self.project)
        project["action_definitions"]["full_verify"]["argv"] = ["bash", "-c", "echo ok"]
        with self.assertRaisesRegex(ContractError, "shell"):
            validate_project_config(project)
        for environment_name in (
            "DELIVERY_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "SSH_AUTH_SOCK",
        ):
            with self.subTest(sensitive_environment=environment_name):
                project = copy.deepcopy(self.project)
                project["action_definitions"]["full_verify"]["env_allowlist"] = [
                    environment_name
                ]
                with self.assertRaisesRegex(ContractError, "env_allowlist"):
                    validate_project_config(project)
        project = copy.deepcopy(self.project)
        project["secret_references"]["deploy_token"]["reference"] = "https://secret.example/token"
        with self.assertRaisesRegex(ContractError, "value instead of a reference"):
            validate_project_config(project)
        project = copy.deepcopy(self.project)
        del project["delivery"]["environments"]["production"]["health"]
        with self.assertRaisesRegex(ContractError, "missing"):
            validate_project_config(project)

    def test_external_mutation_requires_idempotency_and_observe_reconcile(self) -> None:
        project = copy.deepcopy(self.project)
        project["action_definitions"]["deploy"]["idempotency"] = "not_applicable"
        with self.assertRaisesRegex(ContractError, "idempotency"):
            validate_project_config(project)
        project = copy.deepcopy(self.project)
        project["action_definitions"]["deploy"]["observe_action_id"] = None
        with self.assertRaisesRegex(ContractError, "observe_action_id"):
            validate_project_config(project)

    def test_action_result_enforces_success_conditionals_and_operation_binding(self) -> None:
        build_definition = self.project["action_definitions"]["build"]
        result = {
            "protocol_version": "nm-v6/action-result-v1",
            "action_id": "build",
            "operation_id": None,
            "status": "succeeded",
            "effect_id": None,
            "artifact_digest": "a" * 64,
            "environment_id": None,
            "environment_fingerprint": None,
            "observed_state": {},
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "diagnostics": {},
            "redactions": [],
        }
        validate_action_result(result, definition=build_definition)
        prefixed = dict(result, artifact_digest="sha256:" + "a" * 64)
        validate_action_result(prefixed, definition=build_definition)
        parsed_definition = ActionDefinition.from_mapping(build_definition)
        self.assertEqual(
            ActionResult.from_mapping(
                prefixed,
                definition=parsed_definition,
                operation_id=None,
            ).artifact_digest,
            prefixed["artifact_digest"],
        )
        invalid = dict(result, artifact_digest=None)
        with self.assertRaisesRegex(ContractError, "artifact_digest"):
            validate_action_result(invalid, definition=build_definition)
        invalid_operation = dict(result, operation_id="not-an-operation")
        with self.assertRaisesRegex(ContractError, "identifier format"):
            validate_action_result(invalid_operation, definition=build_definition)
        mutation = dict(
            result,
            action_id="deploy",
            operation_id=None,
            effect_id="effect-1",
            environment_id="production",
            environment_fingerprint="fixture",
        )
        with self.assertRaisesRegex(ContractError, "requires a canonical operation_id"):
            validate_action_result(
                mutation,
                definition=self.project["action_definitions"]["deploy"],
            )

    def test_status_audit_and_version_contracts(self) -> None:
        status = {
            "schema_version": "nm-v6/status-v1",
            "run_id": "run",
            "revision": 1,
            "state": "READY",
            "mode": "staged",
            "spec_hash": "a" * 64,
            "config_hash": "b" * 64,
            "last_event_sequence": 1,
            "updated_at": "2026-01-01T00:00:00Z",
            "attention_required": False,
        }
        validate_status_document(status)
        audit = {
            "schema_version": "nm-v6/audit-export-v1",
            "run_id": "run",
            "exported_at": "2026-01-01T00:00:00Z",
            "first_sequence": 1,
            "last_sequence": 1,
            "head_digest": "c" * 64,
            "records": [
                {
                    "sequence": 1,
                    "previous_digest": None,
                    "event_digest": "c" * 64,
                    "event_type": "run_created",
                    "actor": "controller",
                    "run_revision": 1,
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {},
                }
            ],
        }
        validate_audit_export(audit)
        validate_version_record(version_record())
        broken = copy.deepcopy(audit)
        broken["last_sequence"] = 2
        with self.assertRaises(ContractError):
            validate_audit_export(broken)


class AdapterAndContextTests(unittest.TestCase):
    def test_all_provider_adapters_share_one_conformance_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            manifest = build_manifest(workspace)
            request = adapter_request(workspace, manifest)
            for adapter_type in (CodexAdapter, GrokAdapter, ClaudeAdapter, FakeAdapter):
                with self.subTest(adapter=adapter_type.__name__):
                    adapter = adapter_type(backend=MemoryBackend())
                    probe = adapter.probe()
                    self.assertTrue(probe["available"])
                    self.assertIn("native_subagents", probe["capabilities"])
                    session = adapter.start(request)
                    self.assertEqual(adapter.poll(session["session_id"])["status"], "finished")
                    result = adapter.collect(session["session_id"])
                    self.assertEqual(result.operation_id, request["operation_id"])
                    self.assertEqual(result.status, "succeeded")

    def test_adapter_rejects_stale_result_and_supports_capability_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            request = adapter_request(workspace, build_manifest(workspace))

            def stale(req: dict, session_id: str) -> dict:
                result = MemoryBackend._default_result(req, session_id)
                return dict(result, operation_id="OP-other-001")

            adapter = CodexAdapter(
                backend=MemoryBackend(
                    stale,
                    capabilities_override={"native_subagents": False, "resume": False},
                )
            )
            self.assertFalse(adapter.probe()["capabilities"]["native_subagents"])
            session = adapter.start(request)["session_id"]
            adapter.poll(session)
            with self.assertRaisesRegex(ContractError, "mismatched"):
                adapter.collect(session)

    def test_adapter_cancel_and_prohibited_capability(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            request = adapter_request(workspace, build_manifest(workspace))
            adapter = FakeAdapter()
            session = adapter.start(request)["session_id"]
            adapter.cancel(session)
            self.assertEqual(adapter.collect(session).status, "cancelled")
            request["allowed_capabilities"] = ["push_dev"]
            with self.assertRaisesRegex(ContractError, "prohibited"):
                FakeAdapter().start(request)

    def test_fake_merge_reviewer_uses_canonical_context_and_preserves_worker_default(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            review_request, request = merge_reviewer_adapter_request(workspace)
            adapter = FakeAdapter(backend=MemoryBackend())
            session_id = adapter.start(request)["session_id"]
            self.assertEqual(adapter.poll(session_id)["status"], "finished")
            result = adapter.collect_dict(session_id)
            validate_merge_reviewer_adapter_result(
                result,
                adapter_request=request,
                review_request=review_request,
                expected_session_id=session_id,
            )
            self.assertEqual(len(result["observations"]), 1)
            self.assertEqual(result["observations"][0]["decision"], "propose")

            worker_request = adapter_request(workspace, build_manifest(workspace))
            worker_result = MemoryBackend._default_result(
                worker_request, "SESSION-fake-worker"
            )
            self.assertEqual(worker_result["status"], "succeeded")
            self.assertIsNone(worker_result["candidate_commit"])
            self.assertEqual(worker_result["changed_paths"], [])
            self.assertEqual(worker_result["observations"], [])
            self.assertEqual(worker_result["requested_followups"], [])

    def test_fake_merge_reviewer_durable_journal_restarts_and_collects_once(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            state_root = root / "adapter-sessions"
            review_request, request = merge_reviewer_adapter_request(
                str(workspace.resolve())
            )
            first = FakeAdapter(state_root=state_root)
            session_id = first.start(request)["session_id"]

            restarted = FakeAdapter(state_root=state_root)
            self.assertEqual(restarted.poll(session_id)["status"], "finished")
            result = restarted.collect_dict(session_id)
            validate_merge_reviewer_adapter_result(
                result,
                adapter_request=request,
                review_request=review_request,
                expected_session_id=session_id,
            )
            self.assertEqual(
                [path.name for path in state_root.iterdir()], [session_id]
            )

    def test_fake_merge_reviewer_malformed_and_stale_context_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = str(Path(directory).resolve())
            missing = adapter_request(workspace, build_manifest(workspace))
            missing["role"] = "merge_reviewer"
            missing["allowed_capabilities"] = []
            with self.assertRaisesRegex(ContractError, "exactly one canonical"):
                FakeAdapter().start(missing)

        with tempfile.TemporaryDirectory() as directory:
            workspace = str(Path(directory).resolve())
            stale = seal_merge_review_request(merge_review_request_document())
            stale["purpose"] = "changed without resealing"
            stale_item = ContextItem(
                "decision",
                MERGE_REVIEW_CONTEXT_SOURCE,
                canonical_json(stale).decode("utf-8"),
            )
            stale_manifest = build_context_manifest(
                attempt_id="ATTEMPT-run-001",
                items=(*context_items(), stale_item),
                allowed_paths=[],
                prohibited_paths=[".nm/runtime"],
                max_manifest_bytes=100_000,
                max_estimated_tokens=10_000,
            )
            stale_request = adapter_request(workspace, stale_manifest)
            stale_request["role"] = "merge_reviewer"
            stale_request["allowed_capabilities"] = []
            with self.assertRaisesRegex(ContractError, "digest mismatch"):
                FakeAdapter().start(stale_request)

        with tempfile.TemporaryDirectory() as directory:
            workspace = str(Path(directory).resolve())
            review_request = seal_merge_review_request(
                merge_review_request_document()
            )
            duplicate_manifest = build_context_manifest(
                attempt_id="ATTEMPT-run-001",
                items=(
                    *context_items(),
                    merge_review_context_item(review_request),
                    ContextItem(
                        "decision",
                        MERGE_REVIEW_CONTEXT_SOURCE,
                        canonical_json(review_request).decode("utf-8"),
                        entry_id="CTX-MERGE-REVIEW-DUPLICATE",
                    ),
                ),
                allowed_paths=[],
                prohibited_paths=[".nm/runtime"],
                max_manifest_bytes=100_000,
                max_estimated_tokens=10_000,
            )
            duplicate = adapter_request(workspace, duplicate_manifest)
            duplicate["role"] = "merge_reviewer"
            duplicate["allowed_capabilities"] = []
            with self.assertRaisesRegex(ContractError, "exactly one canonical"):
                FakeAdapter().start(duplicate)

    def test_context_digest_budget_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            manifest = build_manifest(workspace)
            validate_context_manifest(manifest)
            tampered = copy.deepcopy(manifest)
            tampered["entries"][0]["content"] += " changed"
            with self.assertRaisesRegex(ContractError, "content address"):
                validate_context_manifest(tampered)
            with self.assertRaisesRegex(ContractError, "token budget"):
                build_context_manifest(
                    attempt_id="ATTEMPT-run-001",
                    items=context_items(),
                    allowed_paths=["src"],
                    prohibited_paths=[".nm/runtime"],
                    max_manifest_bytes=100_000,
                    max_estimated_tokens=1,
                )

    def test_on_demand_addition_is_budget_checked_audited_and_stale_safe(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            optional = ContextItem("reference", "docs/recovery.md", "Recovery details.")
            manifest = build_manifest(workspace, on_demand=(optional,))
            entry_id = manifest["on_demand"][0]["entry_id"]
            proposal = propose_on_demand_addition(
                manifest,
                entry_id=entry_id,
                content=optional.content,
                reason="failure class requires recovery guidance",
                requested_by="controller",
                max_manifest_bytes=100_000,
                max_estimated_tokens=10_000,
                timestamp="2026-01-01T00:00:00Z",
            )
            self.assertEqual(proposal["audit_event"]["entry_digest"], manifest["on_demand"][0]["digest"])
            updated = apply_on_demand_proposal(manifest, proposal)
            self.assertFalse(updated["on_demand"])
            with self.assertRaisesRegex(ContractError, "stale"):
                apply_on_demand_proposal(updated, proposal)


class SupplyChainTests(unittest.TestCase):
    def test_manifest_coverage_and_hash_plan(self) -> None:
        real_manifest = REPO_ROOT / "template" / "v6" / "manifest.json"
        real_plan = validate_template_manifest(real_manifest, repository_root=REPO_ROOT)
        validate_install_plan_hashes(real_plan, real_manifest.parent)
        self.assertGreater(len(real_plan["entries"]), 50)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template" / "v6"
            template.mkdir(parents=True)
            (template / "A.txt").write_text("A\n", encoding="utf-8")
            manifest = {
                "schemaVersion": 2,
                "templateVersion": "6.0.0",
                "maturity": "accepted",
                "recommended": False,
                "productionReady": False,
                "specId": "SPEC-NM-WORKFLOW-V6-V1",
                "specVersion": 1,
                "specHash": "62196ab27c2be08ea1c716081903a009185f1d518ba7a53ed9b3d8485236cb7f",
                "python": ">=3.11,<4",
                "stateFile": ".nm-template-state.json",
                "runtimeAuthority": ".nm/runtime/v6/state.sqlite3",
                "directories": [],
                "templates": [
                    {
                        "target": "A.txt",
                        "source": "template/v6/A.txt",
                        "sourceSha256": sha256_bytes(b"A\n"),
                        "policy": "managed",
                        "mode": "0644",
                    }
                ],
                "git": {
                    "integrationBranch": "dev",
                    "stableBranch": "main",
                    "protectedBranches": ["main", "dev"],
                },
            }
            manifest_path = template / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            plan = validate_template_manifest(manifest_path, repository_root=root)
            validate_install_plan_hashes(plan, template)
            (template / "extra.txt").write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "missing from manifest"):
                validate_template_manifest(manifest_path, repository_root=root)

    def test_real_supply_chain_policy_and_catalog_fail_closed(self) -> None:
        project = json.loads(PROJECT_EXAMPLE.read_text(encoding="utf-8"))
        validate_project_config(project)
        unsafe_cases = (
            {"require_download_digest_or_signature": False},
            {"disable_provider_auto_update": False},
            {"mandatory_ci_credentials": "allowed"},
            {"allowed_download_origins": ["http://example.test/tool"]},
            {"unexpected_policy": True},
        )
        for mutation in unsafe_cases:
            with self.subTest(mutation=mutation):
                invalid = copy.deepcopy(project)
                invalid["supply_chain"].update(mutation)
                with self.assertRaises(ContractError):
                    validate_project_config(invalid)
        schema = json.loads(
            (REPO_ROOT / "tools/nm-v6/schemas/supply-chain-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            set(project["supply_chain"]),
        )
        validate_dependency_constraints(REPO_ROOT)
        validate_dependency_constraints(REPO_ROOT / "template/v6", require_lock=False)
        validate_schema_catalog(REPO_ROOT / "tools/nm-v6/schemas")

    def test_bilingual_semantic_ids_and_mutable_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            english = root / "RULES.md"
            chinese = root / "RULES.zh-CN.md"
            english.write_text("# Rules\nV6-REQ-001 and V6-AC-001\n", encoding="utf-8")
            chinese.write_text("# 规则\nV6-REQ-001 与 V6-AC-001\n", encoding="utf-8")
            validate_bilingual_pair(english, chinese)
            chinese.write_text("# 规则\nV6-REQ-001\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "semantic IDs"):
                validate_bilingual_pair(english, chinese)
            runtime_doc = root / "task.md"
            runtime_doc.write_text("runtime_status: running\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "runtime facts"):
                validate_no_mutable_runtime_markdown([runtime_doc])

    def test_legacy_boundary_dependency_and_artifact_controls(self) -> None:
        self.assertEqual(validate_legacy_preservation(REPO_ROOT)["v5_maturity"], "experimental")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "0b-runtime").mkdir()
            (root / "0b-runtime" / "INDEX.yaml").write_text("workflow: v5\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "cannot be imported"):
                reject_v5_runtime(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps({"devDependencies": {"tool": "^3.9.0"}}), encoding="utf-8"
            )
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            validate_dependency_constraints(root)
            (root / "package.json").write_text(
                json.dumps({"devDependencies": {"tool": "latest"}}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ContractError, "not version constrained"):
                validate_dependency_constraints(root)
        data = b"verified artifact"
        digest = sha256_bytes(data)
        self.assertEqual(
            verify_downloaded_artifact(
                data,
                origin="https://example.test/releases/tool",
                expected_sha256=digest,
                allowed_origins=["https://example.test/releases"],
            ),
            digest,
        )
        with self.assertRaisesRegex(ContractError, "digest mismatch"):
            verify_downloaded_artifact(
                data,
                origin="https://example.test/releases/tool",
                expected_sha256="0" * 64,
                allowed_origins=["https://example.test/releases"],
            )

    def test_version_drift_credentials_provider_policy_and_schema_catalog(self) -> None:
        baseline = version_record()
        current = version_record(core="6.0.1")
        self.assertEqual(set(detect_version_drift(baseline, current)), {"core_cli"})
        with self.assertRaisesRegex(ContractError, "credential variables"):
            validate_credential_free_environment({"PATH": "/bin", "API_TOKEN": "not-empty"})
        validate_provider_update_policy({"codex": {"auto_update": False}})
        with self.assertRaisesRegex(ContractError, "auto-update"):
            validate_provider_update_policy({"codex": {"auto_update": True}})
        catalog = validate_schema_catalog(REPO_ROOT / "tools" / "nm-v6" / "schemas")
        self.assertGreaterEqual(len(catalog), 20)

        project = validate_project_config(
            json.loads(PROJECT_EXAMPLE.read_text(encoding="utf-8"))
        )
        collected = collect_project_runtime_versions(PROJECT_EXAMPLE.parent, project)
        self.assertEqual(
            CONFIGURED_RUNTIME_EVALUATOR_VERSION, collected["evaluator"]
        )
        self.assertEqual(
            {"claude", "codex", "fake", "grok"},
            set(collected["adapters"]),
        )
        self.assertTrue(collected["schemas"])


if __name__ == "__main__":
    unittest.main()
