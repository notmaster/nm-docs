"""Typed fail-closed errors used by the NM V6 core."""


class NmV6Error(RuntimeError):
    """Base class for deterministic workflow failures."""


class ContractError(NmV6Error):
    """A versioned input or result contract is invalid."""


class TransitionError(NmV6Error):
    """A reducer transition is stale, unauthorized, or invalid."""


class AuthorizationError(NmV6Error):
    """A trusted-control-plane record is missing or invalid."""


class EvidenceError(NmV6Error):
    """Evidence cannot be stored or validated safely."""


class IsolationError(NmV6Error):
    """A worker or gate action cannot be isolated safely."""


class GitPolicyError(NmV6Error):
    """A Git operation conflicts with V6 branch policy."""


class ActionError(NmV6Error):
    """A configured action or structured result failed."""


class RecoveryError(NmV6Error):
    """An interrupted operation cannot yet be reconciled."""
