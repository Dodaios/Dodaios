"""The name a person or a model sees for a society agent.

The roster stores the lead under its seeded name: the row's id, its session
and its workspace all derive from it, so the stored name never changes. The
lead IS the assistant, though, and the assistant is called what the wake
phrase says. Everything that shows, speaks or sends an agent's name therefore
asks here, per call: the lead wears the resolved assistant name (the neutral
default while no wake phrase is set), every other agent its stored name.

Read-time only: nothing here writes, so a changed wake word shows on the next
read without a restart. Frontend twin: ``frontend/src/lib/societyDisplayName.ts``.

Looking an agent up by the name a model or a person wrote goes through
``agent_names.resolve_shown``: a stored id, name or slug of a live agent wins
first, then the lead's displayed name means the lead.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from dodaios.brain.assistant_name import DEFAULT_ASSISTANT_NAME, resolve_assistant_name

from .roster import LEAD_AGENT_ID

log = logging.getLogger(__name__)

__all__ = [
    "LIVE",
    "display_name",
    "display_row",
    "is_lead",
    "lead_display_name",
    "names_the_lead",
]

#: "Read the config of the running society" — the default wherever the caller
#: has no config of its own at hand.
LIVE: Final[Any] = object()


def _live_config() -> Any:
    from .runtime import current_runtime

    runtime = current_runtime()
    if runtime is None:
        return None
    try:
        return runtime.config()
    except Exception:  # noqa: BLE001 - a name is cosmetic: the neutral default shows instead
        log.debug("society: live config unavailable for a display name", exc_info=True)
        return None


def is_lead(agent: Any) -> bool:
    return (
        getattr(agent, "agent_id", None) == LEAD_AGENT_ID
        or str(getattr(agent, "tier", "")) == "lead"
    )


def lead_display_name(config: Any = LIVE) -> str:
    """What the lead is called right now; never empty, never the stored name."""
    cfg = _live_config() if config is LIVE else config
    return resolve_assistant_name(cfg).strip() or DEFAULT_ASSISTANT_NAME


def display_name(agent: Any, config: Any = LIVE) -> str:
    """The name to show, speak or send for ``agent``."""
    return lead_display_name(config) if is_lead(agent) else str(agent.name)


def display_row(agent: Any, config: Any = LIVE) -> dict[str, Any]:
    """``agent.to_dict()`` as a person or a model may read it."""
    row = agent.to_dict()
    row["name"] = display_name(agent, config)
    return row


def _key(text: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", str(text or "").casefold()).split())


def names_the_lead(text: str, config: Any = LIVE) -> bool:
    """Whether ``text`` is the lead's displayed name (case, spacing and hyphens aside)."""
    wanted = _key(text)
    return bool(wanted) and wanted == _key(lead_display_name(config))
