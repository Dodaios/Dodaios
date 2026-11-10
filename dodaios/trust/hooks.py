"""What the ``ToolExecutor`` tells the trust layer, in two calls.

:func:`before_execute` runs after the risk tier is known and before anyone is
asked: it names the hard limit the call touches and the outbound findings, so
the executor can insist on a person (or refuse a send that carries a secret).

:func:`after_execute` runs once a call succeeded: a send makes its recipients
known, and a reversible action leaves its inverse in the undo ledger.

Both never raise and never block: a trust check that fails is logged and the
call proceeds exactly as it would have without the layer. The hard limit and
the outbound block are the two exceptions by design — they are the layer's
reason to exist — and both are decided by pure pattern code that cannot fail
on a well-formed call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .hard_limits import hard_limit_for, is_outbound, recipients_of
from .outbound import OutboundFinding, asks, blocks, check_outbound

log = logging.getLogger(__name__)


@dataclass(slots=True)
class TrustVerdict:
    #: The hard limit the call touches (``hard_limits.HARD_LIMITS``), or "".
    hard_limit: str = ""
    findings: list[OutboundFinding] = field(default_factory=list)

    @property
    def needs_person(self) -> bool:
        """A person must decide: a hard limit, or an outbound finding that asks."""
        return bool(self.hard_limit) or asks(self.findings)

    @property
    def blocked(self) -> bool:
        return blocks(self.findings)

    def block_reason(self) -> str:
        codes = sorted({f.code for f in self.findings if f.severity == "block"})
        return "outbound-check: " + ", ".join(codes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hard_limit": self.hard_limit,
            "checks": [f.to_dict() for f in self.findings],
        }


def before_execute(tool_name: str, args: dict[str, Any] | None) -> TrustVerdict:
    verdict = TrustVerdict()
    try:
        verdict.hard_limit = hard_limit_for(tool_name, args) or ""
        verdict.findings = check_outbound(tool_name, args)
    except Exception:  # noqa: BLE001 — a failed check never changes what asks
        log.warning("trust: pre-execution check failed for %s", tool_name, exc_info=True)
    return verdict


def after_execute(
    tool_name: str,
    args: dict[str, Any] | None,
    result: Any,
    config_snapshot: dict[str, Any] | None,
) -> None:
    if not bool(getattr(result, "success", False)):
        return
    args = args if isinstance(args, dict) else {}
    try:
        if is_outbound(tool_name, args):
            recipients = recipients_of(tool_name, args)
            if recipients:
                from .recipients import known_recipients

                known_recipients().remember(recipients)
    except Exception:  # noqa: BLE001 — a ledger that cannot write never costs the call
        log.warning("trust: could not remember recipients of %s", tool_name, exc_info=True)
    try:
        from . import inverses  # noqa: F401 — registers the built-in inverses
        from .undo import undo_ledger

        undo_ledger().record(tool_name, args, getattr(result, "output", None), config_snapshot)
    except Exception:  # noqa: BLE001 — no undo is better than a failed call
        log.warning("trust: could not record an undo for %s", tool_name, exc_info=True)


__all__ = ["TrustVerdict", "after_execute", "before_execute"]
