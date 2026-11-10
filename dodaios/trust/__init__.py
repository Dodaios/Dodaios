"""Trust & control: what the assistant may do without asking, and what it may never skip.

Four small pieces, each with one job:

``hard_limits``   the actions no standing rule, whitelist or bypass can lift —
                  moving money, handling credentials, deleting for good, writing
                  to someone the person never wrote to before. They always ask.
``rules``         the person's standing "always allow" rules, persisted and
                  listed on the Trust page, revocable there.
``outbound``      the second look before anything leaves in the person's name:
                  wrong recipient, leaked secret, tone.
``undo``          the inverse of a reversible action the assistant just took,
                  offered for a few seconds after it ran.

Nothing here owns an approval decision: the ``ToolExecutor`` and the chat's
approval bridge call in, and the Trust page reads the same stores.
"""

from __future__ import annotations

# Importing the package installs the app's own inverses (gmail, calendar, remember).
from . import inverses as _inverses  # noqa: E402, F401
from .hard_limits import HARD_LIMITS, hard_limit_for, is_outbound, recipients_of
from .outbound import OutboundFinding, check_outbound
from .recipients import KnownRecipients, known_recipients
from .rules import TrustRules, trust_rules
from .undo import UndoLedger, register_inverse, undo_ledger

__all__ = [
    "HARD_LIMITS",
    "KnownRecipients",
    "OutboundFinding",
    "TrustRules",
    "UndoLedger",
    "check_outbound",
    "hard_limit_for",
    "is_outbound",
    "known_recipients",
    "recipients_of",
    "register_inverse",
    "trust_rules",
    "undo_ledger",
]
