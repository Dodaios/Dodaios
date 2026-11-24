"""The standing text a live call starts from: identity, instructions, memory.

Built once per call by every live session (GPT-Live, the ChatGPT-subscription
transport and the native Gemini/local/Grok sessions). Each part degrades to
``""`` on a fault so a broken file never blocks a call.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _identity(config: Any) -> str:
    """Who the assistant is (wake-word name + SOUL.md) and what it remembers.

    ``""`` on an identity fault makes the session config fall back to the
    nameless directive, so an identity fault never blocks a call.
    """
    try:
        from dodaios.brain.identity import identity_block

        # maintain: the live tool set holds update_soul, so the call itself
        # keeps SOUL.md current (no separate review call for the character).
        identity = identity_block(config, maintain=True)
    except Exception:  # noqa: BLE001  # broad-except: never block a call on the identity block
        log.warning("live voice: identity block unavailable", exc_info=True)
        return ""
    return identity + _instructions(config) + _memory() + _initiative(config)


def _initiative(config: Any) -> str:
    """The initiative rule and the dated plans it may draw on; ``""`` on a fault.

    A call is short-lived, so the dated plans are read once at its start like
    the notebooks above (``dodaios.brain.proactivity``).
    """
    try:
        from dodaios.brain import proactivity

        level = proactivity.current_level(config)
        blocks = [proactivity.directive(level), proactivity.upcoming_block(level)]
    except Exception:  # noqa: BLE001  # broad-except: never block a call on the initiative rule
        log.warning("live voice: initiative rule unavailable", exc_info=True)
        return ""
    return "".join("\n\n" + block for block in blocks if block)


#: Same cap as the realtime engines' preferences block: a pathological file
#: must never bloat the session instructions.
_INSTRUCTIONS_MAX_CHARS = 64_000


def _instructions(config: Any) -> str:
    """The user's standing instructions (``<Name>.md``); ``""`` on a fault.

    The typed brain and the realtime engines already honour this file; a
    GPT-Live call did not, so the model could neither follow it nor say what
    was in it when asked (2026-10-02).
    """
    try:
        from dodaios.brain.agent_instructions import render_for_prompt

        block = render_for_prompt(config, max_chars=_INSTRUCTIONS_MAX_CHARS)
    except Exception:  # noqa: BLE001  # broad-except: never block a call on the instructions file
        log.warning("live voice: standing instructions unavailable", exc_info=True)
        return ""
    return "\n\n" + block if block else ""


def _memory() -> str:
    """The remember directive and Jarvis' notebooks; ``""`` on a fault.

    A GPT-Live call sees what earlier calls and chats saved to MEMORY.md and
    USER.md, and saves a new "remember this" while the call runs (through
    the remember tool) instead of only after it ends.
    """
    try:
        from dodaios.memory.learning.notebook import memory_block

        block = memory_block()
    except Exception:  # noqa: BLE001  # broad-except: never block a call on the notebooks
        log.warning("live voice: memory notebooks unavailable", exc_info=True)
        return ""
    return "\n\n" + block if block else ""

