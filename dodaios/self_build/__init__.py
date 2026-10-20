"""The self-building loop: Dodaios builds what the person keeps needing.

Doc: docs/self-build.md. This package holds the parts every stage
shares: the build ledger (:mod:`.ledger`), the lifecycle (:mod:`.records`),
the hard limits (:mod:`.policy`), one undo for every kind (:mod:`.undo`), cost
attribution (:mod:`.cost`) and the in-app entry point (:mod:`.service`).
"""

from .ledger import BuildLedger, DuplicateBuild
from .policy import Admission, Autonomy
from .records import BuildRecord, Kind, Outcome, State, TransitionError
from .service import NoBuilder, SelfBuild, current, start
from .undo import UndoRegistry, UndoUnavailable

__all__ = [
    "Admission",
    "Autonomy",
    "BuildLedger",
    "BuildRecord",
    "DuplicateBuild",
    "Kind",
    "NoBuilder",
    "Outcome",
    "SelfBuild",
    "State",
    "TransitionError",
    "UndoRegistry",
    "UndoUnavailable",
    "current",
    "start",
]
