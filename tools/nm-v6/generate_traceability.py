#!/usr/bin/env python3
"""Generate the V6 acceptance manifest and bilingual traceability report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT = ROOT / "tools/nm-v6"
sys.path.insert(0, str(TOOL_ROOT))

from nmv6.errors import ContractError  # noqa: E402
from nmv6.specs import canonical_spec_hash  # noqa: E402
from nmv6.traceability import (  # noqa: E402
    ADMINISTRATOR_ACCEPTANCE_RECORD_PATH,
    GENERATED_TRACEABILITY_PATHS,
    acceptance_requirement_map,
    administrator_acceptance_binding,
    current_changed_files,
    render_traceability_markdown,
    validate_administrator_acceptance_record,
    validate_acceptance_result,
    validate_bilingual_review,
    validate_test_selector,
)
from nmv6.util import canonical_json, dump_json, load_json, sha256_bytes  # noqa: E402


SPEC = ROOT / "docs/nm-v6-workflow-spec.md"
SPEC_HASH = "62196ab27c2be08ea1c716081903a009185f1d518ba7a53ed9b3d8485236cb7f"

C = "tools/nm-v6/tests/test_contracts_adapters_context.py"
S = "tools/nm-v6/tests/test_state_auth_evidence.py"
O = "tools/nm-v6/tests/test_operations.py"
T = "tools/nm-v6/tests/test_template_cli_traceability.py"
K = "tools/nm-v6/tests/test_crash_acceptance.py"
G = "tools/nm-v6/tests/test_git_delivery_audit_acceptance.py"
X = "tools/nm-v6/tests/test_security_crash_acceptance.py"
L = "tools/nm-v6/tests/test_lifecycle_e2e_acceptance.py"
N = "tools/nm-v6/tests/test_normal_runtime_generated.py"
H = "tools/nm-v6/tests/test_hotfix_runtime_generated.py"
Q = "tools/nm-v6/tests/test_cleanup_review_contract.py"


TESTS: dict[int, list[str]] = {
    1: [f"{C}::SpecTests.test_traceability_rejects_missing_coverage_invalid_stage_and_cycles", f"{C}::SpecTests.test_traceability_requires_canonical_delivery_stage_decisions", f"{S}::AuthorizationTests.test_signature_scope_replay_expiry_and_revocation"],
    2: [f"{C}::SpecTests.test_hash_normalizes_line_endings_trailing_lf_and_frontmatter_order", f"{S}::EvidenceGateTests.test_redacted_atomic_blobs_receipt_validation_and_orphans", f"{L}::LifecycleE2EAcceptanceTests.test_ac002_amendment_invalidates_confirmation_evidence_and_authorization"],
    3: [f"{S}::StoreReducerTests.test_sqlite_pragmas_cas_idempotency_tamper_and_rebuild", f"{S}::StoreReducerTests.test_v1_to_v2_migration_backup_is_atomic_and_crash_retryable"],
    4: [f"{S}::StoreReducerTests.test_sqlite_pragmas_cas_idempotency_tamper_and_rebuild", f"{S}::StoreReducerTests.test_lease_fencing_and_two_controller_exclusion", f"{S}::StoreReducerTests.test_persisted_write_conflicts_and_pause_fence_all_child_writes"],
    5: [f"{C}::AdapterAndContextTests.test_adapter_rejects_stale_result_and_supports_capability_fallback", f"{X}::SecurityAndCrashAcceptanceTests.test_ac005_exit_zero_without_structured_result_cannot_advance"],
    6: [f"{S}::EvidenceGateTests.test_every_gate_prerequisite_fails_closed", f"{X}::SecurityAndCrashAcceptanceTests.test_ac006_worker_success_is_advisory_and_failed_rerun_fails_gate"],
    7: [f"{O}::ActionAndWorkspaceTests.test_workspace_is_standalone_clone_without_remote", f"{O}::ActionAndWorkspaceTests.test_detected_os_sandbox_cannot_read_sibling_secret", f"{X}::SecurityAndCrashAcceptanceTests.test_ac007_ac056_malicious_verify_cannot_touch_authority_or_secrets"],
    8: [f"{S}::StoreReducerTests.test_transition_document_is_versioned_and_unique"],
    9: [f"{O}::GitControllerTests.test_merge_strategies_produce_expected_trees_and_enforce_guards", f"{S}::AuthorizationTests.test_signature_scope_replay_expiry_and_revocation"],
    10: [f"{S}::AuthorizationTests.test_signature_scope_replay_expiry_and_revocation", f"{O}::DeliveryAndControllerTests.test_environment_bound_deploy_and_verified_rollback", f"{L}::LifecycleE2EAcceptanceTests.test_ac010_auto_delivery_continues_without_prompt_and_fails_closed", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion"],
    11: [f"{S}::AuthorizationTests.test_cancelled_run_invalidates_old_and_pending_grants_but_allows_revocation", f"{S}::AuthorizationTests.test_all_terminal_states_reject_old_grant_operations_and_mode_change"],
    12: [f"{C}::AdapterAndContextTests.test_all_provider_adapters_share_one_conformance_boundary", f"{Q}::CleanupReviewContractTests.test_cleanup_reviewer_adapter_three_decisions_and_strict_envelope"],
    13: [f"{C}::AdapterAndContextTests.test_adapter_rejects_stale_result_and_supports_capability_fallback", f"{X}::SecurityAndCrashAcceptanceTests.test_adapter_session_survives_backend_restart_and_network_is_scoped", f"{X}::SecurityAndCrashAcceptanceTests.test_fake_adapter_exact_request_is_restart_safe_and_dispatched_once", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion", f"{Q}::CleanupReviewContractTests.test_cleanup_reviewer_context_and_durable_restart_are_exact"],
    14: [f"{O}::SchedulerTests.test_dag_lease_fencing_and_write_conflicts", f"{T}::TemplateAndCliAcceptanceTests.test_ac041_generated_project_commands_pass_cleanly", f"{L}::LifecycleE2EAcceptanceTests.test_ac014_single_and_multi_worker_have_equivalent_logical_results", f"{N}::GeneratedNormalRuntimeTests.test_max_workers_two_runs_one_real_overlapping_task_batch", f"{N}::GeneratedNormalRuntimeTests.test_single_and_multi_worker_task_batches_have_equivalent_trees"],
    15: [f"{O}::SchedulerTests.test_dag_lease_fencing_and_write_conflicts", f"{S}::StoreReducerTests.test_persisted_write_conflicts_and_pause_fence_all_child_writes", f"{N}::GeneratedNormalRuntimeTests.test_max_workers_two_runs_one_real_overlapping_task_batch", f"{N}::GeneratedNormalRuntimeTests.test_declared_overlap_is_split_into_serial_task_batches", f"{N}::GeneratedNormalRuntimeTests.test_actual_overlap_blocks_before_candidate_ref_update", f"{N}::GeneratedNormalRuntimeTests.test_task_batch_recovers_gate_before_candidate_cas_without_redispatch"],
    16: [f"{S}::StoreReducerTests.test_lease_fencing_and_two_controller_exclusion", f"{S}::StoreReducerTests.test_persisted_write_conflicts_and_pause_fence_all_child_writes", f"{N}::GeneratedNormalRuntimeTests.test_expired_batch_result_is_fenced_before_new_attempt"],
    17: [f"{K}::CrashRecoveryAcceptanceTests.test_ac017_state_sigkill_matrix_has_one_logical_effect", f"{O}::DeliveryAndControllerTests.test_interrupted_mutation_is_persisted_then_reconciled_once", f"{X}::SecurityAndCrashAcceptanceTests.test_ac017_state_and_verification_sigkill_resume_once", f"{X}::SecurityAndCrashAcceptanceTests.test_ac017_git_integration_sigkill_observes_or_executes_one_cas", f"{X}::SecurityAndCrashAcceptanceTests.test_ac017_release_deploy_rollback_sigkill_reconcile_one_effect", f"{X}::SecurityAndCrashAcceptanceTests.test_fake_adapter_exact_request_is_restart_safe_and_dispatched_once", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion", f"{N}::GeneratedNormalRuntimeTests.test_cleanup_reviewer_recovers_core_and_provenance_boundaries", f"{H}::GeneratedHotfixRuntimeTests.test_cli_hotfix_preserves_unreleased_dev_and_recovers_both_pushes", f"{Q}::CleanupReviewContractTests.test_cleanup_reviewer_context_and_durable_restart_are_exact", f"{S}::StoreReducerTests.test_v1_to_v2_migration_backup_is_atomic_and_crash_retryable"],
    18: [f"{O}::DeliveryAndControllerTests.test_retry_and_pause_fail_closed", f"{S}::StoreReducerTests.test_sqlite_pragmas_cas_idempotency_tamper_and_rebuild", f"{L}::LifecycleE2EAcceptanceTests.test_ac018_detached_restart_and_persistent_pause_resume", f"{X}::SecurityAndCrashAcceptanceTests.test_adapter_session_survives_backend_restart_and_network_is_scoped", f"{X}::SecurityAndCrashAcceptanceTests.test_fake_adapter_exact_request_is_restart_safe_and_dispatched_once", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion"],
    19: [f"{O}::GitControllerTests.test_merge_strategies_produce_expected_trees_and_enforce_guards"],
    20: [f"{O}::GitControllerTests.test_hotfix_uses_exact_stable_and_reconciles_into_dev", f"{H}::GeneratedHotfixRuntimeTests.test_cli_hotfix_preserves_unreleased_dev_and_recovers_both_pushes", f"{H}::GeneratedHotfixRuntimeTests.test_legacy_hotfix_action_aliases_do_not_authorize_canonical_actions"],
    21: [f"{O}::GitControllerTests.test_exact_dev_merge_cas_push_and_cleanup", f"{O}::ActionAndWorkspaceTests.test_workspace_is_standalone_clone_without_remote", f"{H}::GeneratedHotfixRuntimeTests.test_cli_hotfix_preserves_unreleased_dev_and_recovers_both_pushes"],
    22: [f"{O}::GitControllerTests.test_exact_dev_merge_cas_push_and_cleanup"],
    23: [
        f"{O}::GitControllerTests.test_merge_strategies_produce_expected_trees_and_enforce_guards",
        f"{O}::GitControllerTests.test_merge_review_request_derives_routes_and_git_facts",
        f"{O}::GitControllerTests.test_merge_review_helper_executes_all_three_strategy_choices",
        f"{O}::GitControllerTests.test_merge_review_helper_rejects_disabled_moved_and_stale_evidence",
        f"{O}::GitControllerTests.test_merge_review_helper_reports_conflicts_and_rejects_cannot_propose",
        f"{C}::MergeReviewContractTests.test_deterministic_fake_reviewer_covers_every_decision",
        f"{C}::MergeReviewContractTests.test_request_digest_route_topology_and_exact_tree_fail_closed",
        f"{C}::MergeReviewContractTests.test_observation_fail_closed_matrix",
        f"{C}::MergeReviewContractTests.test_merge_review_schemas_are_catalogued_and_strict",
        f"{C}::MergeReviewContractTests.test_merge_reviewer_adapter_envelope_is_read_only_and_exact",
        f"{N}::GeneratedNormalRuntimeTests.test_merge_reviewer_failures_precede_gate_operation_and_ref_mutation",
        f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion",
        f"{H}::GeneratedHotfixRuntimeTests.test_cli_hotfix_preserves_unreleased_dev_and_recovers_both_pushes",
    ],
    24: [f"{O}::GitControllerTests.test_cleanup_retention_matrix_and_squash_equivalence", f"{G}::GitPolicyAcceptanceTests.test_cleanup_ignores_false_caller_live_fact_claims_and_reads_store", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion", f"{H}::GeneratedHotfixRuntimeTests.test_cli_hotfix_preserves_unreleased_dev_and_recovers_both_pushes", f"{Q}::CleanupReviewContractTests.test_cleanup_reviewer_adapter_three_decisions_and_strict_envelope", f"{Q}::CleanupReviewContractTests.test_git_cleanup_review_rechecks_ai_core_and_preserves_remote", f"{Q}::CleanupReviewContractTests.test_git_cleanup_review_stale_facts_fail_closed", f"{Q}::CleanupReviewContractTests.test_exact_positive_request_allows_only_local_cleanup", f"{Q}::CleanupReviewContractTests.test_every_core_blocker_prevents_delete_local"],
    25: [f"{O}::GitControllerTests.test_cleanup_retention_matrix_and_squash_equivalence", f"{O}::GitControllerTests.test_exact_dev_merge_cas_push_and_cleanup", f"{G}::GitPolicyAcceptanceTests.test_cleanup_fails_closed_without_responsibility_evidence", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion", f"{Q}::CleanupReviewContractTests.test_git_cleanup_review_squash_proof_ignores_caller_boolean", f"{Q}::CleanupReviewContractTests.test_integration_source_and_proof_are_core_bound", f"{Q}::CleanupReviewContractTests.test_squash_requires_patch_or_tree_equivalence"],
    26: [f"{O}::ActionAndWorkspaceTests.test_action_contract_rejects_shell_interpolation_and_secret_output", f"{O}::ActionAndWorkspaceTests.test_detected_os_sandbox_cannot_read_sibling_secret"],
    27: [f"{C}::ContractTests.test_project_rejects_branch_shell_secret_and_incomplete_delivery", f"{C}::ContractTests.test_external_mutation_requires_idempotency_and_observe_reconcile", f"{C}::ContractTests.test_project_rejects_stage_authority_and_unsafe_release_metadata"],
    28: [f"{O}::DeliveryAndControllerTests.test_environment_mismatch_and_unhealthy_deploy_require_attention", f"{G}::AuditAndEnvironmentAcceptanceTests.test_ac028_environment_mismatch_persists_evidence_and_requires_attention", f"{N}::GeneratedNormalRuntimeTests.test_environment_mismatch_persists_evidence_and_requires_attention"],
    29: [f"{O}::DeliveryAndControllerTests.test_interrupted_mutation_is_persisted_then_reconciled_once"],
    30: [f"{O}::DeliveryAndControllerTests.test_partial_unknown_operation_is_observed_and_reconciled"],
    31: [f"{O}::DeliveryAndControllerTests.test_environment_mismatch_and_unhealthy_deploy_require_attention", f"{G}::DeliveryBindingAcceptanceTests.test_ac031_ac032_authorized_rollback_and_failure_paths_require_attention", f"{N}::GeneratedNormalRuntimeTests.test_rollback_authorization_and_verification_failures_require_attention"],
    32: [f"{O}::DeliveryAndControllerTests.test_environment_bound_deploy_and_verified_rollback", f"{G}::DeliveryBindingAcceptanceTests.test_ac031_ac032_authorized_rollback_and_failure_paths_require_attention", f"{N}::GeneratedNormalRuntimeTests.test_rollback_authorization_and_verification_failures_require_attention", f"{N}::GeneratedNormalRuntimeTests.test_successful_rollback_closes_resources_and_final_branch_cleanup"],
    33: [f"{C}::AdapterAndContextTests.test_context_digest_budget_and_tamper_detection", f"{C}::AdapterAndContextTests.test_on_demand_addition_is_budget_checked_audited_and_stale_safe"],
    34: [f"{O}::DeliveryAndControllerTests.test_retry_and_pause_fail_closed"],
    35: [f"{C}::SpecTests.test_optional_skip_requires_remaining_mandatory_coverage"],
    36: [f"{S}::StoreReducerTests.test_sqlite_pragmas_cas_idempotency_tamper_and_rebuild"],
    37: [f"{T}::TemplateAndCliAcceptanceTests.test_ac037_init_is_clean_and_protected_refs_are_not_the_commit_branch"],
    38: [f"{T}::TemplateAndCliAcceptanceTests.test_ac038_interrupted_update_can_abort_without_losing_user_file", f"{T}::TemplateAndCliAcceptanceTests.test_ac038_interrupted_update_resumes_from_durable_project_stage", f"{T}::TemplateAndCliAcceptanceTests.test_ac038_missing_stage_or_backup_fails_closed_without_deleting_prior_file", f"{T}::TemplateAndCliAcceptanceTests.test_ac038_journal_traversal_tamper_and_recovery_context_fail_closed"],
    39: [f"{T}::TemplateAndCliAcceptanceTests.test_ac039_and_ac042_installed_check_rejects_v5_runtime", f"{T}::TemplateAndCliAcceptanceTests.test_ac039_repository_check_rejects_tampered_traceability_report", f"{C}::SupplyChainTests.test_manifest_coverage_and_hash_plan"],
    40: [f"{T}::TemplateAndCliAcceptanceTests.test_ac041_generated_project_commands_pass_cleanly", f"{O}::DeliveryAndControllerTests.test_interrupted_mutation_is_persisted_then_reconciled_once", f"{O}::GitControllerTests.test_merge_strategies_produce_expected_trees_and_enforce_guards", f"{L}::LifecycleE2EAcceptanceTests.test_ac040_representative_end_to_end_scenario_matrix", f"{N}::GeneratedNormalRuntimeTests.test_delivery_not_applicable_decisions_use_real_gates_and_complete", f"{N}::GeneratedNormalRuntimeTests.test_multiple_delivery_environments_are_ordered_and_scoped", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion", f"{H}::GeneratedHotfixRuntimeTests.test_cli_hotfix_preserves_unreleased_dev_and_recovers_both_pushes"],
    41: [f"{T}::TemplateAndCliAcceptanceTests.test_ac041_generated_project_commands_pass_cleanly", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion", f"{H}::GeneratedHotfixRuntimeTests.test_cli_hotfix_preserves_unreleased_dev_and_recovers_both_pushes"],
    42: [f"{T}::TemplateAndCliAcceptanceTests.test_ac039_and_ac042_installed_check_rejects_v5_runtime", f"{C}::SupplyChainTests.test_legacy_boundary_dependency_and_artifact_controls"],
    43: [f"{C}::SupplyChainTests.test_legacy_boundary_dependency_and_artifact_controls", f"{C}::SupplyChainTests.test_real_supply_chain_policy_and_catalog_fail_closed", f"{C}::SupplyChainTests.test_version_drift_credentials_provider_policy_and_schema_catalog", f"{T}::TemplateAndCliAcceptanceTests.test_ac043_acceptance_and_self_test_reject_credential_environment", f"{T}::TemplateAndCliAcceptanceTests.test_ac043_installed_skill_binds_exact_source_and_ignores_hostile_cwd", f"{S}::SchemaRuntimeAlignmentTests.test_schema_required_fields_and_versions_match_runtime_outputs", f"{N}::GeneratedNormalRuntimeTests.test_runtime_version_provider_schema_and_core_drift_fail_before_effects"],
    44: [
        f"{C}::SupplyChainTests.test_bilingual_semantic_ids_and_mutable_markdown",
        f"{T}::TemplateAndCliAcceptanceTests.test_ac044_repository_bilingual_check_covers_workflow_and_missing_pairs",
        f"{T}::TemplateAndCliAcceptanceTests.test_ac044_repository_bilingual_check_rejects_id_and_structure_drift",
    ],
    45: [f"{T}::TemplateAndCliAcceptanceTests.test_ac045_implementation_plan_maps_every_requirement", f"{T}::TemplateAndCliAcceptanceTests.test_ac045_acceptance_binding_survives_evidence_commit_ref_move_and_clone", f"{T}::TemplateAndCliAcceptanceTests.test_ac045_acceptance_binding_rejects_source_drift_extra_and_nonancestor"],
    46: [f"{C}::SpecTests.test_hash_normalizes_line_endings_trailing_lf_and_frontmatter_order", f"{C}::SpecTests.test_hash_rejects_unknown_missing_duplicate_and_bom_frontmatter"],
    47: [f"{S}::AuthorizationTests.test_signature_scope_replay_expiry_and_revocation", f"{S}::AuthorizationTests.test_revoke_start_race_has_one_serial_order", f"{S}::AuthorizationTests.test_mode_change_requires_plan_and_consumes_one_time_approval"],
    48: [f"{C}::SpecTests.test_traceability_and_stage_due_semantics", f"{S}::EvidenceGateTests.test_every_gate_prerequisite_fails_closed", f"{S}::EvidenceGateTests.test_completion_gate_requires_each_mandatory_acceptance_assertion", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion"],
    49: [f"{S}::EvidenceGateTests.test_every_gate_prerequisite_fails_closed", f"{S}::EvidenceGateTests.test_completion_gate_requires_each_mandatory_acceptance_assertion"],
    50: [f"{C}::ContractTests.test_complete_project_example_validates", f"{C}::ContractTests.test_fake_release_metadata_action_returns_bound_metadata", f"{O}::DeliveryAndControllerTests.test_partial_unknown_operation_is_observed_and_reconciled", f"{G}::DeliveryBindingAcceptanceTests.test_ac050_release_publish_partial_unknown_are_observed_and_reconciled"],
    51: [f"{S}::EvidenceGateTests.test_redacted_atomic_blobs_receipt_validation_and_orphans"],
    52: [f"{T}::TemplateAndCliAcceptanceTests.test_ac052_update_rejects_dirty_authoritative_tree", f"{O}::GitControllerTests.test_merge_strategies_produce_expected_trees_and_enforce_guards", f"{G}::GitPolicyAcceptanceTests.test_ac052_git_failure_matrix_and_resync_invalidates_old_proposal"],
    53: [f"{O}::DeliveryAndControllerTests.test_build_binds_source_and_release_source_kinds", f"{O}::GitControllerTests.test_hotfix_uses_exact_stable_and_reconciles_into_dev", f"{G}::DeliveryBindingAcceptanceTests.test_ac053_normal_and_hotfix_release_binding_chain_rejects_substitution", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion", f"{H}::GeneratedHotfixRuntimeTests.test_cli_hotfix_preserves_unreleased_dev_and_recovers_both_pushes"],
    54: [f"{K}::CrashRecoveryAcceptanceTests.test_ac017_state_sigkill_matrix_has_one_logical_effect", f"{O}::DeliveryAndControllerTests.test_interrupted_mutation_is_persisted_then_reconciled_once", f"{S}::AuthorizationTests.test_revoke_start_race_has_one_serial_order", f"{L}::LifecycleE2EAcceptanceTests.test_ac054_pause_cancel_and_revoke_fence_every_external_mutation"],
    55: [f"{S}::StoreReducerTests.test_sqlite_pragmas_cas_idempotency_tamper_and_rebuild", f"{S}::SchemaRuntimeAlignmentTests.test_schema_required_fields_and_versions_match_runtime_outputs", f"{G}::AuditAndEnvironmentAcceptanceTests.test_ac055_every_audit_class_is_append_only_tamper_evident_and_restart_stable"],
    56: [f"{O}::ActionAndWorkspaceTests.test_detected_os_sandbox_cannot_read_sibling_secret", f"{O}::ActionAndWorkspaceTests.test_workspace_is_standalone_clone_without_remote", f"{X}::SecurityAndCrashAcceptanceTests.test_ac007_ac056_malicious_verify_cannot_touch_authority_or_secrets"],
    57: [f"{O}::GitControllerTests.test_exact_dev_merge_cas_push_and_cleanup", f"{G}::GitPolicyAcceptanceTests.test_ac057_nonprotected_grants_are_exact_one_time_and_action_separated"],
    58: [f"{K}::CrashRecoveryAcceptanceTests.test_ac058_blob_and_receipt_sigkill_boundaries_are_recoverable", f"{S}::EvidenceGateTests.test_receipt_failpoint_rolls_back_database_reference", f"{X}::SecurityAndCrashAcceptanceTests.test_ac058_missing_corrupt_blobs_fail_gates_and_db_tamper_fails_integrity"],
    59: [f"{T}::TemplateAndCliAcceptanceTests.test_ac059_decisions_and_invariants_reach_executable_acceptance"],
    60: [f"{O}::GitControllerTests.test_cleanup_retention_matrix_and_squash_equivalence", f"{G}::GitPolicyAcceptanceTests.test_ac060_cleanup_rechecks_current_facts_and_records_fresh_receipt", f"{G}::GitPolicyAcceptanceTests.test_cleanup_ignores_false_caller_live_fact_claims_and_reads_store", f"{G}::GitPolicyAcceptanceTests.test_cleanup_fails_closed_without_responsibility_evidence", f"{G}::GitPolicyAcceptanceTests.test_cleanup_persists_fresh_facts_digest_and_execution_receipt", f"{N}::GeneratedNormalRuntimeTests.test_cleanup_reviewer_window_allows_only_its_own_lifecycle", f"{N}::GeneratedNormalRuntimeTests.test_completion_terminal_snapshot_rejects_live_resources_and_remote_delete_consumption", f"{N}::GeneratedNormalRuntimeTests.test_signed_plan_and_grant_drive_ordinary_run_to_completion", f"{Q}::CleanupReviewContractTests.test_git_cleanup_review_rechecks_ai_core_and_preserves_remote", f"{Q}::CleanupReviewContractTests.test_git_cleanup_review_stale_facts_fail_closed", f"{Q}::CleanupReviewContractTests.test_stale_tampered_multiple_and_unknown_data_fail_closed"],
}


MODULE_REQUIREMENTS = {
    "specs.py": ["V6-REQ-001", "V6-REQ-015"],
    "store.py": ["V6-REQ-002", "V6-REQ-019"],
    "reducer.py": ["V6-REQ-002", "V6-REQ-003", "V6-REQ-006", "V6-REQ-009", "V6-REQ-010", "V6-REQ-018"],
    "transitions.py": ["V6-REQ-003"],
    "evidence.py": ["V6-REQ-004", "V6-REQ-017"],
    "gates.py": ["V6-REQ-005", "V6-REQ-014"],
    "authorization.py": ["V6-REQ-006"],
    "adapters.py": ["V6-REQ-007", "V6-REQ-014"],
    "workspace.py": ["V6-REQ-008"],
    "actions.py": ["V6-REQ-008", "V6-REQ-016", "V6-REQ-017"],
    "scheduler.py": ["V6-REQ-009", "V6-REQ-010"],
    "controller.py": ["V6-REQ-009", "V6-REQ-018"],
    "runtime.py": [
        "V6-REQ-003",
        "V6-REQ-005",
        "V6-REQ-006",
        "V6-REQ-007",
        "V6-REQ-009",
        "V6-REQ-010",
        "V6-REQ-011",
        "V6-REQ-013",
        "V6-REQ-014",
        "V6-REQ-015",
        "V6-REQ-018",
        "V6-REQ-020",
        "V6-REQ-023",
    ],
    "recovery.py": ["V6-REQ-011"],
    "context.py": ["V6-REQ-012"],
    "cleanup_review.py": ["V6-REQ-007", "V6-REQ-014"],
    "merge_review.py": ["V6-REQ-007", "V6-REQ-014"],
    "git_controller.py": ["V6-REQ-013", "V6-REQ-014"],
    "delivery.py": ["V6-REQ-015"],
    "contracts.py": ["V6-REQ-015", "V6-REQ-016"],
    "audit.py": ["V6-REQ-019"],
    "outbox.py": ["V6-REQ-019"],
    "cli.py": ["V6-REQ-020", "V6-REQ-023"],
    "template_sync.py": ["V6-REQ-020", "V6-REQ-022"],
    "repository_check.py": ["V6-REQ-020", "V6-REQ-021", "V6-REQ-023", "V6-REQ-024"],
    "supply_chain.py": ["V6-REQ-021", "V6-REQ-023"],
    "traceability.py": ["V6-REQ-024"],
    "failpoints.py": ["V6-REQ-011"],
    "models.py": ["V6-REQ-002", "V6-REQ-007"],
    "util.py": ["V6-REQ-002", "V6-REQ-016"],
    "errors.py": ["V6-REQ-020"],
    "__init__.py": ["V6-REQ-020"],
}


SCHEMA_REQUIREMENTS = {
    "action-result-v1.schema.json": ["V6-REQ-016"],
    "action-v1.schema.json": ["V6-REQ-016"],
    "adapter-config-v1.schema.json": ["V6-REQ-007"],
    "adapter-probe-v1.schema.json": ["V6-REQ-007"],
    "adapter-request-v1.schema.json": ["V6-REQ-007"],
    "adapter-result-v1.schema.json": ["V6-REQ-007"],
    "approval-v1.schema.json": ["V6-REQ-006"],
    "administrator-acceptance-v1.schema.json": ["V6-REQ-023", "V6-REQ-024"],
    "audit-export-v1.schema.json": ["V6-REQ-019"],
    "authorization-config-v1.schema.json": ["V6-REQ-006"],
    "authorization-request-v1.schema.json": ["V6-REQ-006"],
    "confirmation-v1.schema.json": ["V6-REQ-006"],
    "context-addition-proposal-v1.schema.json": ["V6-REQ-012"],
    "context-manifest-v1.schema.json": ["V6-REQ-012"],
    "evidence-config-v1.schema.json": ["V6-REQ-004", "V6-REQ-017"],
    "evidence-receipt-v1.schema.json": ["V6-REQ-004"],
    "gate-receipt-v1.schema.json": ["V6-REQ-005"],
    "grant-v1.schema.json": ["V6-REQ-006"],
    "implementation-authorization-v1.schema.json": ["V6-REQ-006"],
    "merge-proposal-v1.schema.json": ["V6-REQ-014"],
    "cleanup-review-request-v1.schema.json": ["V6-REQ-007", "V6-REQ-014"],
    "cleanup-review-observation-v1.schema.json": ["V6-REQ-007", "V6-REQ-014"],
    "merge-review-request-v1.schema.json": ["V6-REQ-007", "V6-REQ-014"],
    "merge-review-observation-v1.schema.json": ["V6-REQ-007", "V6-REQ-014"],
    "project-v1.schema.json": ["V6-REQ-015", "V6-REQ-016"],
    "revocation-v1.schema.json": ["V6-REQ-006"],
    "spec-v1.schema.json": ["V6-REQ-001", "V6-REQ-015"],
    "status-v1.schema.json": ["V6-REQ-020"],
    "supply-chain-v1.schema.json": ["V6-REQ-023"],
    "transition-table-v1.schema.json": ["V6-REQ-003"],
    "version-record-v1.schema.json": ["V6-REQ-023"],
}


def map_file(path: str) -> list[str]:
    name = Path(path).name
    if "/nmv6/" in path and name in MODULE_REQUIREMENTS:
        return MODULE_REQUIREMENTS[name]
    if "/nmv6/migrations/" in path and path.endswith(".sql"):
        return ["V6-REQ-002", "V6-REQ-019"]
    if path.startswith("tools/nm-v6/schemas/") or "/0c-workflow/schemas/" in path:
        if name not in SCHEMA_REQUIREMENTS:
            raise ContractError(f"unmapped V6 schema changed file: {path}")
        return SCHEMA_REQUIREMENTS[name]
    if path.startswith("tools/nm-v6/tests/"):
        if "contracts" in name:
            return ["V6-REQ-001", "V6-REQ-007", "V6-REQ-012", "V6-REQ-014", "V6-REQ-015", "V6-REQ-016", "V6-REQ-021", "V6-REQ-023"]
        if "state" in name:
            return ["V6-REQ-002", "V6-REQ-003", "V6-REQ-004", "V6-REQ-005", "V6-REQ-006", "V6-REQ-010", "V6-REQ-019"]
        if "operations" in name:
            return ["V6-REQ-008", "V6-REQ-009", "V6-REQ-010", "V6-REQ-011", "V6-REQ-013", "V6-REQ-014", "V6-REQ-015", "V6-REQ-018"]
        if "crash" in name:
            return ["V6-REQ-002", "V6-REQ-004", "V6-REQ-011"]
        if name == "test_git_delivery_audit_acceptance.py":
            return ["V6-REQ-005", "V6-REQ-010", "V6-REQ-013", "V6-REQ-014", "V6-REQ-015", "V6-REQ-017", "V6-REQ-019"]
        if name == "test_security_crash_acceptance.py":
            return ["V6-REQ-002", "V6-REQ-003", "V6-REQ-004", "V6-REQ-005", "V6-REQ-008", "V6-REQ-011", "V6-REQ-017"]
        if name == "test_lifecycle_e2e_acceptance.py":
            return ["V6-REQ-001", "V6-REQ-003", "V6-REQ-005", "V6-REQ-006", "V6-REQ-009", "V6-REQ-011", "V6-REQ-018"]
        if name == "test_normal_runtime_generated.py":
            return ["V6-REQ-005", "V6-REQ-006", "V6-REQ-007", "V6-REQ-009", "V6-REQ-011", "V6-REQ-013", "V6-REQ-014", "V6-REQ-015", "V6-REQ-018", "V6-REQ-020", "V6-REQ-023"]
        if name == "test_hotfix_runtime_generated.py":
            return ["V6-REQ-005", "V6-REQ-007", "V6-REQ-011", "V6-REQ-013", "V6-REQ-014", "V6-REQ-015", "V6-REQ-020"]
        if name == "test_cleanup_review_contract.py":
            return ["V6-REQ-007", "V6-REQ-011", "V6-REQ-013", "V6-REQ-014"]
        if name == "test_template_cli_traceability.py":
            return ["V6-REQ-020", "V6-REQ-021", "V6-REQ-022", "V6-REQ-024"]
        if name == "__init__.py":
            return ["V6-REQ-020", "V6-REQ-022", "V6-REQ-024"]
        raise ContractError(f"unmapped V6 test changed file: {path}")
    if path.startswith("skills/nm-init-project-v6/"):
        if name == "openai.yaml":
            return ["V6-REQ-020", "V6-REQ-023"]
        if name.endswith(".md"):
            return ["V6-REQ-020", "V6-REQ-021"]
        if name == "run_nm_v6.py":
            return ["V6-REQ-020", "V6-REQ-023"]
        raise ContractError(f"unmapped V6 Skill changed file: {path}")
    if path.startswith("template/v6/"):
        if path.endswith("manifest.json"):
            return ["V6-REQ-023"]
        if path.endswith("0a-spec/traceability.json"):
            return ["V6-REQ-001", "V6-REQ-015", "V6-REQ-021"]
        if "/0a-spec/" in path or "/0c-prompts/" in path or path.endswith("DECISIONS.md"):
            return ["V6-REQ-001", "V6-REQ-021"]
        if "/0b-design/prototype/" in path:
            return ["V6-REQ-001", "V6-REQ-021"]
        if "/recovery/" in path or path.endswith(("RECOVERY.md", "RECOVERY.zh-CN.md")):
            return ["V6-REQ-011", "V6-REQ-021"]
        if "/adapters/" in path:
            return ["V6-REQ-007", "V6-REQ-021"]
        if path.endswith(("WORKFLOW_V6.md", "WORKFLOW_V6.zh-CN.md", "PROTOCOLS.md", "PROTOCOLS.zh-CN.md")):
            return ["V6-REQ-008", "V6-REQ-021"]
        if path.endswith("project.example.json") or path.endswith("fake-action.py"):
            return ["V6-REQ-015", "V6-REQ-016"]
        if path.endswith("fixtures/fake-admin-public.pem"):
            return ["V6-REQ-006", "V6-REQ-023"]
        if path.endswith(("check-workflow.sh", "test-workflow.sh", "verify.sh")):
            return ["V6-REQ-008", "V6-REQ-020", "V6-REQ-023"]
        if path.endswith(("0d-scripts/nm-v6.py", "0d-scripts/python311.sh")):
            return ["V6-REQ-020", "V6-REQ-023"]
        if path.endswith(".codex/hooks/stop-status.sh"):
            return ["V6-REQ-008", "V6-REQ-019", "V6-REQ-020"]
        if path.endswith(".codex/config.toml"):
            return ["V6-REQ-008", "V6-REQ-020"]
        if path.endswith(".delete-pending/.gitkeep"):
            return ["V6-REQ-014"]
        if path.endswith(".gitignore"):
            return ["V6-REQ-002", "V6-REQ-008"]
        if path.endswith((".markdownlint.json", ".markdownlintignore")):
            return ["V6-REQ-020", "V6-REQ-021"]
        if name in {"AGENTS.md", "AGENTS.zh-CN.md", "CLAUDE.md", "GROK.md"}:
            return ["V6-REQ-008", "V6-REQ-021"]
        if name in {"README.md", "PROJECT_STRUCTURE.md"}:
            return ["V6-REQ-020", "V6-REQ-021"]
        if name == "package.json":
            return ["V6-REQ-016", "V6-REQ-020"]
        raise ContractError(f"unmapped V6 template changed file: {path}")
    if path in {"AGENTS.md", "AGENTS.zh-CN.md"}:
        return ["V6-REQ-008", "V6-REQ-021"]
    if path == "README.md":
        return ["V6-REQ-021", "V6-REQ-022"]
    if path in {"docs/README.zh-CN.md", "docs/template-versions.zh-CN.md"}:
        return ["V6-REQ-021", "V6-REQ-022"]
    if path == "docs/template-versions.md":
        return ["V6-REQ-022"]
    if path == "docs/installation.md":
        return ["V6-REQ-020", "V6-REQ-022"]
    if path == "docs/installation.zh-CN.md":
        return ["V6-REQ-020", "V6-REQ-021", "V6-REQ-022"]
    if path == "docs/nm-v6-bilingual-semantic-review.md":
        return ["V6-REQ-021"]
    if path == "docs/nm-v6-bilingual-semantic-review.zh-CN.md":
        return ["V6-REQ-021"]
    if path == "docs/nm-v6-implementation-traceability.md":
        return ["V6-REQ-024"]
    if path == "docs/nm-v6-implementation-traceability.zh-CN.md":
        return ["V6-REQ-021", "V6-REQ-024"]
    if path in {"package.json", "tools/nm-v6/nm_v6.py", "tools/nm-v6/python311.sh", "tools/nm-v6/install-skill.sh"}:
        return ["V6-REQ-020", "V6-REQ-023"]
    if path == "tools/nm-v6/generate_traceability.py":
        return ["V6-REQ-020", "V6-REQ-021", "V6-REQ-023", "V6-REQ-024"]
    if path == "tools/nm-v6/sync_template.py":
        return ["V6-REQ-020", "V6-REQ-023", "V6-REQ-024"]
    if path == ".gitignore":
        return ["V6-REQ-002", "V6-REQ-020"]
    if path == "tools/nm-v6/implementation-plan.json":
        return ["V6-REQ-024"]
    if path == "tools/nm-v6/acceptance-manifest.json":
        return ["V6-REQ-023", "V6-REQ-024"]
    if path == ADMINISTRATOR_ACCEPTANCE_RECORD_PATH:
        return ["V6-REQ-023", "V6-REQ-024"]
    raise ContractError(f"changed file has no explicit V6 Requirement mapping: {path}")


def _acceptance_status(selectors: list[str], outcomes: dict[str, str]) -> str:
    statuses = [outcomes.get(selector) for selector in selectors]
    if all(status == "pass" for status in statuses):
        return "pass"
    if any(status in {"fail", "error", "unexpected_success"} for status in statuses):
        return "fail"
    return "not_run"


def _implementation_state(
    administrator_binding: dict[str, object] | None,
) -> tuple[str, str]:
    """Never infer acceptance from a record merely existing on disk."""

    if administrator_binding is None:
        return "acceptance-candidate", "pending"
    return "accepted", "accepted"


def _digest_binding(result_bytes: bytes, result: dict[str, object]) -> dict[str, object]:
    source_change = result.get("source_change")
    inventory = result.get("test_inventory")
    return {
        "schema_version": "nm-v6/acceptance-result-digest-v1",
        "result_file_sha256": sha256_bytes(result_bytes),
        "spec_hash": result.get("spec_hash"),
        "source_change_digest": source_change.get("digest") if isinstance(source_change, dict) else None,
        "test_inventory_digest": inventory.get("digest") if isinstance(inventory, dict) else None,
        "command_digest": result.get("command_digest"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True, help="Machine result from acceptance-test --output.")
    parser.add_argument(
        "--administrator-acceptance-record",
        help=(
            "Explicit canonical administrator record; omitted always emits "
            "acceptance-candidate/pending."
        ),
    )
    args = parser.parse_args()
    result_path = Path(args.result).expanduser().resolve()
    result = load_json(result_path)
    if not isinstance(result, dict):
        raise ContractError("acceptance result must be a JSON object")
    result_bytes = result_path.read_bytes()
    if result_bytes != dump_json(result):
        raise ContractError("acceptance result must use canonical pretty JSON encoding")
    validate_acceptance_result(result, repository=ROOT)
    digest_binding = _digest_binding(result_bytes, result)
    sidecar_path = Path(f"{result_path}.sha256.json")
    if load_json(sidecar_path) != digest_binding:
        raise ContractError("acceptance result digest sidecar is missing, stale, or incomplete")
    actual_spec_hash = canonical_spec_hash(SPEC)
    if actual_spec_hash != SPEC_HASH:
        raise ContractError(f"confirmed V6 Spec hash changed: {actual_spec_hash}")
    requirements = acceptance_requirement_map(SPEC)
    outcomes = result["test_outcomes"]
    if not isinstance(outcomes, dict):
        raise ContractError("acceptance result lacks per-test outcomes")
    inventory = result["test_inventory"]
    for selectors in TESTS.values():
        for selector in selectors:
            validate_test_selector(selector, inventory=inventory)
    review = validate_bilingual_review(ROOT, spec_hash=SPEC_HASH)
    administrator_record_path: Path | None = None
    administrator_record: dict[str, object] | None = None
    administrator_binding: dict[str, object] | None = None
    if args.administrator_acceptance_record is not None:
        administrator_record_path = Path(
            args.administrator_acceptance_record
        ).expanduser().resolve()
        administrator_record = validate_administrator_acceptance_record(
            administrator_record_path,
            repository=ROOT,
            acceptance_result=result,
            acceptance_result_sha256=digest_binding["result_file_sha256"],
            independent_review=review,
        )
        administrator_binding = administrator_acceptance_binding(
            administrator_record_path,
            repository=ROOT,
            record=administrator_record,
        )
    acceptance: dict[str, object] = {}
    for index in range(1, 61):
        identifier = f"V6-AC-{index:03d}"
        row: dict[str, object] = {
            "requirements": requirements[identifier],
            "tests": TESTS[index],
            "status": _acceptance_status(TESTS[index], outcomes),
        }
        if index == 44:
            row["independent_review"] = review
        acceptance[identifier] = row
    source = result["source_change"]
    changed = sorted(
        set(
            current_changed_files(
                ROOT,
                base_ref=source["base_ref"],
                base_sha=source["base_ref_sha"],
            )
        )
        | GENERATED_TRACEABILITY_PATHS
    )
    files = {path: sorted(set(map_file(path))) for path in changed}
    requirement_evidence = {
        requirement: {
            "acceptance": sorted(
                acceptance_id
                for acceptance_id, record in acceptance.items()
                if requirement in record["requirements"]
            ),
            "files": sorted(path for path, links in files.items() if requirement in links),
        }
        for requirement in sorted({f"V6-REQ-{index:03d}" for index in range(1, 25)})
    }
    implementation_status, administrator_acceptance = _implementation_state(
        administrator_binding
    )
    evidence: dict[str, object] = {
        "automated": {
            "result_file_name": result_path.name,
            "result_file_sha256": sha256_bytes(result_bytes),
            "digest_binding": digest_binding,
            "result": result,
        },
        "independent_review": review,
    }
    if administrator_binding is not None:
        evidence["administrator_acceptance"] = administrator_binding
    manifest: dict[str, object] = {
        "schema_version": "nm-v6/acceptance-manifest-v2",
        "spec_id": "SPEC-NM-WORKFLOW-V6-V1",
        "spec_version": 1,
        "spec_hash": SPEC_HASH,
        "implementation_status": implementation_status,
        "administrator_acceptance": administrator_acceptance,
        "evidence": evidence,
        "acceptance": acceptance,
        "files": files,
        "requirements": requirement_evidence,
        "file_scope": {
            "base_ref": "origin/dev",
            "merge_base_sha": source["merge_base_sha"],
            "changed_files_digest": sha256_bytes(canonical_json(sorted(files))),
        },
    }
    (ROOT / "tools/nm-v6/acceptance-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (ROOT / "docs/nm-v6-implementation-traceability.md").write_text(
        render_traceability_markdown(manifest, chinese=False), encoding="utf-8"
    )
    (ROOT / "docs/nm-v6-implementation-traceability.zh-CN.md").write_text(
        render_traceability_markdown(manifest, chinese=True), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
