"""Reusable, fail-closed protocol kernel for T21 blind evaluations.

The package deliberately contains no experiment-specific constants.  Every
public operation accepts a validated master contract (or paths derived from
one), so authoring, construction, sealing, evaluation, and scoring share the
same source of truth.
"""

from .contract import Contract, load_contract, validate_master_contract
from .ledger import ConstructionLedger, EvaluationLedger
from .state_machine import Phase, ProtocolStateMachine

__all__ = [
    "ConstructionLedger",
    "Contract",
    "EvaluationLedger",
    "Phase",
    "ProtocolStateMachine",
    "load_contract",
    "validate_master_contract",
]

__version__ = "1.0.0"
