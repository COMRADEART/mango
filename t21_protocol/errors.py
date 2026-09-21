"""Protocol-kernel exception hierarchy."""


class ProtocolError(RuntimeError):
    """Base class for a closed protocol gate."""


class ContractError(ProtocolError):
    """The master contract is incomplete, unknown, or internally inconsistent."""


class GraphError(ProtocolError):
    """The artifact dependency graph is not closed."""


class LedgerError(ProtocolError):
    """A one-shot ledger operation is illegal."""


class StateTransitionError(ProtocolError):
    """A command attempted an illegal protocol transition."""


class SealError(ProtocolError):
    """A seal is incomplete, malformed, or does not match its inputs."""


class ValidationError(ProtocolError):
    """Gold/evaluation material is incompatible with the frozen protocol."""


class WriteGuardError(ProtocolError):
    """A command wrote outside its declared allowlist."""


class AuthorizationError(ProtocolError):
    """A phase API received the wrong authorization class or token."""


class ProvenanceError(ProtocolError):
    """Workspace, provider, or material provenance is not phase-compatible."""


class T21R15OfficialEvaluationPermanentlyRefused(ProtocolError):
    """R15's sealed holdout is not loadable by the frozen candidate runtime.

    The seal is preserved and never repaired or rewritten, so no official
    evaluation of R15 can ever run: every attempt fails closed here.
    """
