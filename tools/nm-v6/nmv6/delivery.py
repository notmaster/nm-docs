"""Artifact-bound release, environment-bound deployment, and verified rollback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from .actions import ActionDefinition, ActionExecutor, ActionResult
from .errors import ActionError, ContractError, RecoveryError
from .failpoints import checkpoint
from .gates import validate_gate_decision
from .git_controller import GitController
from .recovery import AmbiguousOperationError, ReconciliationResult, RecoveryController
from .util import canonical_json, sha256_bytes
from .workspace import Workspace


_RELEASE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReleaseSource:
    kind: str
    commit: str
    tree: str
    spec_hash: str
    config_hash: str
    hotfix_reconciliation_gate_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"dev", "hotfix_stable"}:
            raise ContractError("release source kind must be dev or hotfix_stable")
        for field in ("commit", "tree", "spec_hash", "config_hash"):
            if not getattr(self, field):
                raise ContractError(f"release source {field} must not be empty")
        if self.kind == "hotfix_stable" and not self.hotfix_reconciliation_gate_id:
            raise ContractError("hotfix release must cite its dev-reconciliation result gate")
        if self.kind == "dev" and self.hotfix_reconciliation_gate_id is not None:
            raise ContractError("normal dev release cannot cite a hotfix reconciliation gate")


@dataclass(frozen=True)
class ReleaseReceipt:
    source: ReleaseSource
    artifact_digest: str
    stable_commit: str
    stable_tree: str
    stable_ref: str
    observed_remote_stable_commit: str
    tag: str
    tag_target: str
    published_version: str
    release_result: ActionResult
    release_observation: ReconciliationResult
    publish_result: ActionResult
    publish_observation: ReconciliationResult


@dataclass(frozen=True)
class ReleaseMetadata:
    tag: str
    published_version: str
    changelog_digest: str
    metadata_digest: str
    result: ActionResult


@dataclass(frozen=True)
class EnvironmentTarget:
    environment_id: str
    expected_identity: str
    expected_fingerprint: str | None
    identity_probe_action: str
    preflight_action: str
    deploy_action: str
    health_action: str
    rollback_action: str
    post_rollback_verify_action: str


@dataclass(frozen=True)
class RollbackReceipt:
    environment_id: str
    rollback_target: str
    rollback_result: ActionResult
    rollback_observation: ReconciliationResult
    verification: ActionResult
    state: str


@dataclass(frozen=True)
class DeploymentReceipt:
    environment_id: str
    environment_fingerprint: str
    artifact_digest: str
    previous_version: str
    deploy_result: ActionResult
    deploy_observation: ReconciliationResult
    health_result: ActionResult
    state: str
    rollback: RollbackReceipt | None = None


class DeliveryController:
    def __init__(
        self,
        definitions: Mapping[str, ActionDefinition],
        executor: ActionExecutor,
        recovery: RecoveryController,
        *,
        git: GitController | None = None,
    ) -> None:
        self.definitions = dict(definitions)
        self.executor = executor
        self.recovery = recovery
        self.git = git

    def build(
        self,
        *,
        workspace: Workspace,
        action_id: str,
        source_commit: str | None = None,
    ) -> ActionResult:
        definition = self._action(action_id)
        if definition.kind != "pure":
            raise ContractError("build action must be pure")
        core_env: dict[str, str] = {}
        if "NM_V6_SOURCE_COMMIT" in definition.core_injected_env:
            if not source_commit:
                raise ContractError("build action requires the exact release source commit")
            core_env["NM_V6_SOURCE_COMMIT"] = source_commit
        result = self.executor.execute(
            definition,
            workspace=workspace,
            operation_id=None,
            core_env=core_env,
        )
        if result.status != "succeeded" or not result.artifact_digest:
            raise ActionError("build did not produce an immutable artifact digest")
        return result

    def release_metadata(
        self,
        *,
        workspace: Workspace,
        action_id: str,
        source: ReleaseSource,
    ) -> ReleaseMetadata:
        """Collect provider-neutral release metadata from one pure project action."""

        definition = self._action(action_id)
        if definition.kind != "pure" or definition.secret_refs:
            raise ContractError("release metadata action must be pure and credential-free")
        core_env = {
            "NM_V6_SPEC_HASH": source.spec_hash,
            "NM_V6_CONFIG_HASH": source.config_hash,
            "NM_V6_RELEASE_SOURCE_KIND": source.kind,
            "NM_V6_RELEASE_SOURCE_COMMIT": source.commit,
            "NM_V6_RELEASE_SOURCE_TREE": source.tree,
        }
        if set(definition.core_injected_env) != set(core_env):
            raise ContractError(
                "release metadata action must declare the complete source binding environment"
            )
        result = self.executor.execute(
            definition,
            workspace=workspace,
            operation_id=None,
            core_env=core_env,
        )
        state = result.observed_state
        tag = state.get("tag")
        version = state.get("published_version")
        changelog_digest = state.get("changelog_digest")
        if (
            result.status != "succeeded"
            or not isinstance(tag, str)
            or not _RELEASE_TEXT.fullmatch(tag)
            or not isinstance(version, str)
            or not _RELEASE_TEXT.fullmatch(version)
            or not isinstance(changelog_digest, str)
            or not _SHA256.fullmatch(changelog_digest)
        ):
            raise ActionError(
                "release metadata action must return valid tag, published_version, and changelog_digest"
            )
        normalized_changelog = changelog_digest.removeprefix("sha256:")
        metadata_digest = sha256_bytes(
            canonical_json(
                {
                    "changelog_digest": normalized_changelog,
                    "config_hash": source.config_hash,
                    "published_version": version,
                    "release_source_commit": source.commit,
                    "release_source_kind": source.kind,
                    "release_source_tree": source.tree,
                    "spec_hash": source.spec_hash,
                    "tag": tag,
                }
            )
        )
        return ReleaseMetadata(
            tag,
            version,
            normalized_changelog,
            metadata_digest,
            result,
        )

    def release(
        self,
        *,
        workspace: Workspace,
        source: ReleaseSource,
        build_action: str,
        release_action: str,
        publish_action: str,
        stable_commit: str,
        stable_tree: str,
        release_operation_id: str,
        publish_operation_id: str,
        grant_id: str,
        grant_revision: int,
        expected_tag: str,
        expected_version: str,
        expected_release_metadata_digest: str,
        expected_artifact_digest: str,
        hotfix_reconciliation_decision: Mapping[str, object] | None = None,
    ) -> ReleaseReceipt:
        _, observed_remote_stable = self._verify_release_source(
            source, stable_commit=stable_commit, stable_tree=stable_tree
        )
        self._verify_hotfix_reconciliation(
            source, decision=hotfix_reconciliation_decision
        )
        build = self.build(
            workspace=workspace,
            action_id=build_action,
            source_commit=source.commit,
        )
        artifact = build.artifact_digest or ""
        if (
            not expected_artifact_digest
            or artifact.removeprefix("sha256:")
            != expected_artifact_digest.removeprefix("sha256:")
        ):
            raise RecoveryError(
                "release build differs from the immutable artifact approved by RELEASE_GATE"
            )
        if not _SHA256.fullmatch(expected_release_metadata_digest):
            raise RecoveryError(
                "release metadata digest differs from the metadata approved by RELEASE_GATE"
            )
        release_metadata_digest = expected_release_metadata_digest.removeprefix(
            "sha256:"
        )
        common_env = {
            "NM_V6_SPEC_HASH": source.spec_hash,
            "NM_V6_CONFIG_HASH": source.config_hash,
            "NM_V6_RELEASE_SOURCE_KIND": source.kind,
            "NM_V6_RELEASE_SOURCE_COMMIT": source.commit,
            "NM_V6_RELEASE_SOURCE_TREE": source.tree,
            "NM_V6_RELEASE_TAG": expected_tag,
            "NM_V6_RELEASE_VERSION": expected_version,
            "NM_V6_RELEASE_METADATA_DIGEST": release_metadata_digest,
            "NM_V6_ARTIFACT_DIGEST": artifact,
            "NM_V6_STABLE_COMMIT": stable_commit,
            "NM_V6_STABLE_TREE": stable_tree,
        }
        release_result, release_observation = self._mutate_and_observe(
            release_action,
            workspace=workspace,
            operation_id=release_operation_id,
            grant_id=grant_id,
            grant_revision=grant_revision,
            core_env=common_env,
        )
        self._require_artifact_binding(release_result, artifact, "release")
        self._require_release_binding(
            release_observation.observation,
            source=source,
            stable_commit=stable_commit,
            stable_tree=stable_tree,
            artifact_digest=artifact,
            effect_id=release_result.effect_id or "",
            action="release observation",
            release_tag=expected_tag,
            published_version=expected_version,
            release_metadata_digest=release_metadata_digest,
        )
        publish_result, publish_observation = self._mutate_and_observe(
            publish_action,
            workspace=workspace,
            operation_id=publish_operation_id,
            grant_id=grant_id,
            grant_revision=grant_revision,
            core_env=common_env,
        )
        self._require_artifact_binding(publish_result, artifact, "publish")
        self._require_release_binding(
            publish_observation.observation,
            source=source,
            stable_commit=stable_commit,
            stable_tree=stable_tree,
            artifact_digest=artifact,
            effect_id=publish_result.effect_id or "",
            action="publish observation",
            release_tag=expected_tag,
            published_version=expected_version,
            release_metadata_digest=release_metadata_digest,
        )
        tag, tag_target, version = self._publication_identity(
            publish_observation.observation,
            mutation=publish_result,
            stable_commit=stable_commit,
            expected_tag=expected_tag,
            expected_version=expected_version,
        )
        return ReleaseReceipt(
            source,
            artifact,
            stable_commit,
            stable_tree,
            (
                f"refs/heads/{self.git.stable_branch}"
                if self.git is not None
                else "stable-result"
            ),
            observed_remote_stable,
            tag,
            tag_target,
            version,
            release_result,
            release_observation,
            publish_result,
            publish_observation,
        )

    def deploy(
        self,
        *,
        workspace: Workspace,
        target: EnvironmentTarget,
        artifact_digest: str,
        deploy_operation_id: str,
        grant_id: str,
        grant_revision: int,
        rollback_operation_id: str | None = None,
        rollback_authorized: bool = False,
    ) -> DeploymentReceipt:
        if not artifact_digest:
            raise ContractError("deployment requires an artifact digest")
        identity = self.confirm_environment(workspace=workspace, target=target)
        previous_version = _result_text(identity, "deployed_version")
        if not previous_version:
            raise ActionError("environment observation did not provide a rollback target")
        preflight = self._execute_observation_or_pure(
            target.preflight_action,
            workspace=workspace,
            operation_id=f"{deploy_operation_id}:preflight",
        )
        if preflight.status != "succeeded":
            raise ActionError("deployment preflight failed")
        core_env = {
            "NM_V6_ARTIFACT_DIGEST": artifact_digest,
            "NM_V6_ENVIRONMENT_ID": target.expected_identity,
            "NM_V6_ENVIRONMENT_FINGERPRINT": identity.environment_fingerprint or "",
        }
        deploy_result, deploy_observation = self._mutate_and_observe(
            target.deploy_action,
            workspace=workspace,
            operation_id=deploy_operation_id,
            grant_id=grant_id,
            grant_revision=grant_revision,
            core_env=core_env,
        )
        self._require_environment_binding(deploy_result, target, identity)
        self._require_artifact_binding(deploy_result, artifact_digest, "deploy")
        self._require_environment_binding(deploy_observation.observation, target, identity)
        self._require_artifact_binding(
            deploy_observation.observation, artifact_digest, "deploy observation"
        )
        health = self.executor.execute(
            self._action(target.health_action),
            workspace=workspace,
            operation_id=None,
            allow_network=True,
        )
        healthy = health.status == "succeeded" and health.observed_state.get("healthy") is True
        if health.status == "succeeded":
            self._require_environment_binding(health, target, identity)
            observed_artifact = _result_text(health, "artifact_digest")
            if observed_artifact is not None and observed_artifact != artifact_digest:
                raise RecoveryError("health result observed a substituted artifact")
        if healthy:
            return DeploymentReceipt(
                target.environment_id,
                identity.environment_fingerprint or "",
                artifact_digest,
                previous_version,
                deploy_result,
                deploy_observation,
                health,
                "POST_DEPLOY_VERIFIED",
            )
        if not rollback_authorized or not rollback_operation_id:
            return DeploymentReceipt(
                target.environment_id,
                identity.environment_fingerprint or "",
                artifact_digest,
                previous_version,
                deploy_result,
                deploy_observation,
                health,
                "ATTENTION_REQUIRED",
            )
        rollback = self.rollback(
            workspace=workspace,
            target=target,
            rollback_target=previous_version,
            operation_id=rollback_operation_id,
            grant_id=grant_id,
            grant_revision=grant_revision,
        )
        return DeploymentReceipt(
            target.environment_id,
            identity.environment_fingerprint or "",
            artifact_digest,
            previous_version,
            deploy_result,
            deploy_observation,
            health,
            rollback.state,
            rollback,
        )

    def confirm_environment(
        self,
        *,
        workspace: Workspace,
        target: EnvironmentTarget,
    ) -> ActionResult:
        result = self.observe_environment(workspace=workspace, target=target)
        if result.status != "succeeded":
            raise ActionError("environment identity probe failed")
        if result.environment_id != target.expected_identity:
            raise ActionError("environment identity does not match configured/authorized target")
        if target.expected_fingerprint is not None and (
            result.environment_fingerprint != target.expected_fingerprint
        ):
            raise ActionError("environment fingerprint does not match authorization scope")
        if not result.environment_fingerprint:
            raise ActionError("environment identity probe did not produce a fingerprint")
        return result

    def observe_environment(
        self,
        *,
        workspace: Workspace,
        target: EnvironmentTarget,
    ) -> ActionResult:
        """Return a structured identity observation before policy comparison."""

        definition = self._action(target.identity_probe_action)
        if definition.kind != "external_observe" or definition.secret_refs:
            raise ContractError("environment identity probe must be credential-free observe action")
        return self.executor.execute(
            definition,
            workspace=workspace,
            operation_id=None,
            allow_network=True,
        )

    def rollback(
        self,
        *,
        workspace: Workspace,
        target: EnvironmentTarget,
        rollback_target: str,
        operation_id: str,
        grant_id: str,
        grant_revision: int,
    ) -> RollbackReceipt:
        if not rollback_target:
            raise ContractError("rollback target must not be empty")
        identity = self.confirm_environment(workspace=workspace, target=target)
        result, observation = self._mutate_and_observe(
            target.rollback_action,
            workspace=workspace,
            operation_id=operation_id,
            grant_id=grant_id,
            grant_revision=grant_revision,
            core_env={
                "NM_V6_ROLLBACK_TARGET": rollback_target,
                "NM_V6_ENVIRONMENT_ID": target.expected_identity,
                "NM_V6_ENVIRONMENT_FINGERPRINT": identity.environment_fingerprint or "",
            },
        )
        self._require_environment_binding(result, target, identity)
        self._require_environment_binding(observation.observation, target, identity)
        verification = self.executor.execute(
            self._action(target.post_rollback_verify_action),
            workspace=workspace,
            operation_id=None,
            allow_network=True,
        )
        observed_target = _result_text(verification, "deployed_version")
        verified = (
            verification.status == "succeeded"
            and verification.observed_state.get("healthy") is True
            and observed_target == rollback_target
            and verification.environment_id == target.expected_identity
            and verification.environment_fingerprint == identity.environment_fingerprint
        )
        state = "ROLLED_BACK" if verified else "ATTENTION_REQUIRED"
        return RollbackReceipt(
            target.environment_id,
            rollback_target,
            result,
            observation,
            verification,
            state,
        )

    def _mutate_and_observe(
        self,
        action_id: str,
        *,
        workspace: Workspace,
        operation_id: str,
        grant_id: str,
        grant_revision: int,
        core_env: Mapping[str, str],
    ) -> tuple[ActionResult, ReconciliationResult]:
        checkpoint(f"delivery.{action_id}.before")
        try:
            result = self.recovery.execute_mutation(
                action_id,
                workspace=workspace,
                operation_id=operation_id,
                grant_id=grant_id,
                grant_revision=grant_revision,
                core_env=core_env,
                allow_network=True,
            )
        except AmbiguousOperationError as exc:
            result = exc.result
        observed = self.recovery.observe_reconcile(
            action_id,
            workspace=workspace,
            operation_id=operation_id,
            allow_network=True,
        )
        if observed.classification != "completed":
            raise RecoveryError(
                f"{action_id} result was not independently observed as completed"
            )
        checkpoint(f"delivery.{action_id}.after")
        return result, observed

    def _verify_release_source(
        self,
        source: ReleaseSource,
        *,
        stable_commit: str,
        stable_tree: str,
    ) -> tuple[str, str]:
        if self.git is not None:
            if self.git.resolve_commit(source.commit) != source.commit:
                raise ContractError("release source commit is not canonical")
            if self.git.tree_of(source.commit) != source.tree:
                raise ContractError("release source commit/tree binding failed")
            if self.git.tree_of(stable_commit) != stable_tree:
                raise ContractError("stable commit/tree binding failed")
            stable_ref = f"refs/heads/{self.git.stable_branch}"
            observed_local_stable = self.git.resolve_commit(stable_ref)
            if observed_local_stable != stable_commit:
                raise ContractError("local stable ref does not equal the claimed stable commit")
            observed_remote_stable = self.git.remote_head(self.git.stable_branch)
            if observed_remote_stable != stable_commit:
                raise ContractError("remote stable ref does not equal the claimed stable commit")
            if source.kind == "dev":
                dev_ref = f"refs/heads/{self.git.integration_branch}"
                if self.git.resolve_commit(dev_ref) != source.commit:
                    raise ContractError("normal release source does not equal local dev")
                if self.git.remote_head(self.git.integration_branch) != source.commit:
                    raise ContractError("normal release source does not equal remote dev")
        else:
            observed_local_stable = stable_commit
            observed_remote_stable = stable_commit
        if source.kind == "dev" and stable_tree != source.tree:
            raise ContractError("normal stable tree must exactly equal verified dev tree")
        if source.kind == "hotfix_stable" and stable_commit != source.commit:
            raise ContractError("hotfix release must build from verified hotfix stable")
        return observed_local_stable, observed_remote_stable

    @staticmethod
    def _verify_hotfix_reconciliation(
        source: ReleaseSource,
        *,
        decision: Mapping[str, object] | None,
    ) -> None:
        if source.kind == "dev":
            if decision is not None:
                raise ContractError("normal release cannot cite hotfix reconciliation evidence")
            return
        if decision is None:
            raise ContractError("hotfix release requires its reconciliation result decision")
        validate_gate_decision(decision)
        if (
            decision.get("gate_id") != source.hotfix_reconciliation_gate_id
            or decision.get("gate_type") != "HOTFIX_RECONCILIATION_RESULT_GATE"
            or decision.get("result") != "passed"
            or decision.get("spec_hash") != source.spec_hash
            or decision.get("config_hash") != source.config_hash
            or decision.get("source_commit") != source.commit
        ):
            raise ContractError("hotfix reconciliation decision is not bound to the release source")

    def _execute_observation_or_pure(
        self,
        action_id: str,
        *,
        workspace: Workspace,
        operation_id: str,
    ) -> ActionResult:
        definition = self._action(action_id)
        if definition.kind == "external_mutation":
            raise ContractError("preflight action cannot mutate external state")
        return self.executor.execute(
            definition,
            workspace=workspace,
            operation_id=None,
            allow_network=definition.kind == "external_observe",
        )

    def _require_artifact_binding(
        self, result: ActionResult, artifact_digest: str, action: str
    ) -> None:
        observed = result.artifact_digest or _result_text(result, "artifact_digest")
        if (
            observed is None
            or observed.removeprefix("sha256:")
            != artifact_digest.removeprefix("sha256:")
        ):
            raise RecoveryError(f"{action} result is not bound to the authorized artifact")

    def _require_release_binding(
        self,
        result: ActionResult,
        *,
        source: ReleaseSource,
        stable_commit: str,
        stable_tree: str,
        artifact_digest: str,
        effect_id: str,
        action: str,
        release_tag: str | None = None,
        published_version: str | None = None,
        release_metadata_digest: str | None = None,
    ) -> None:
        expected = {
            "release_source_kind": source.kind,
            "release_source_commit": source.commit,
            "release_source_tree": source.tree,
            "stable_commit": stable_commit,
            "stable_tree": stable_tree,
            "artifact_digest": artifact_digest,
            "effect_id": effect_id,
        }
        optional = {
            "tag": release_tag,
            "published_version": published_version,
            "release_metadata_digest": release_metadata_digest,
        }
        expected.update(
            {field: value for field, value in optional.items() if value is not None}
        )
        for field, value in expected.items():
            if _result_text(result, field) != value:
                raise RecoveryError(f"{action} {field} binding mismatch")
        self._require_artifact_binding(result, artifact_digest, action)

    @staticmethod
    def _publication_identity(
        observation: ActionResult,
        *,
        mutation: ActionResult,
        stable_commit: str,
        expected_tag: str,
        expected_version: str,
    ) -> tuple[str, str, str]:
        tag = _result_text(observation, "tag") or _result_text(mutation, "tag")
        tag_target = _result_text(observation, "tag_target") or _result_text(
            mutation, "tag_target"
        )
        version = _result_text(observation, "published_version") or _result_text(
            mutation, "published_version"
        )
        if not tag or not version or not tag_target:
            raise RecoveryError(
                "observed release result lacks tag, tag target, or published version"
            )
        if tag_target != stable_commit:
            raise RecoveryError("published tag target differs from the authorized stable commit")
        if tag != expected_tag or version != expected_version:
            raise RecoveryError("published tag or version differs from authorized release metadata")
        return tag, tag_target, version

    @staticmethod
    def _require_environment_binding(
        result: ActionResult,
        target: EnvironmentTarget,
        identity: ActionResult,
    ) -> None:
        if result.environment_id != target.expected_identity:
            raise RecoveryError("delivery result environment identity mismatch")
        if result.environment_fingerprint != identity.environment_fingerprint:
            raise RecoveryError("delivery result environment fingerprint mismatch")

    def _action(self, action_id: str) -> ActionDefinition:
        try:
            return self.definitions[action_id]
        except KeyError as exc:
            raise ContractError(f"unknown delivery action: {action_id}") from exc


def _result_text(result: ActionResult, field: str) -> str | None:
    value = result.observed_state.get(field)
    return value if isinstance(value, str) and value else None
