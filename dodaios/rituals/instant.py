"""A step for the moment itself that is one tool call: done without a model.

"Play my favourite music" said to the assistant is a turn: a model reads it,
picks the tool and calls it, seconds later. For a ritual that is started with
"good morning" the music should simply start. So a ``now`` step may carry the
call it comes down to (``tool``, ``args`` and ``says``, the call in plain
words). The assistant works it out once, when it writes the ritual on the
person's request; at the start the call is made directly.

Nothing here decides what may run. The call goes through the same gate as
every tool call of the app (``ToolExecutor``), on the surface where nobody can
be asked: a call that would need a question does not run, and its step is done
by an ordinary turn instead, where the usual approval applies. The same holds
for a call that fails or names a tool that is gone.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Final
from uuid import uuid4

log = logging.getLogger(__name__)

MAX_SAYS_CHARS: Final[int] = 160
#: How long one call may take before its step is left to a turn.
CALL_TIMEOUT_S: Final[float] = 20.0


def _gateway() -> Any | None:
    from dodaios.core import runtime_refs

    return runtime_refs.get_supervisor_tool_gateway()


def _descriptor(tool: str) -> Any | None:
    gateway = _gateway()
    if gateway is None:
        return None
    try:
        return next((d for d in gateway.catalog() if d.name == tool), None)
    except Exception:  # noqa: BLE001 — a catalog that cannot be read knows no tool
        log.debug("rituals: tool catalog unreadable", exc_info=True)
        return None


def clean(raw: Any) -> dict[str, Any] | None:
    """``raw`` as a stored call, or ``None`` for none; raises ``ValueError`` for a bad shape."""
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("call is an object with 'tool', 'args' and 'says'")
    tool = str(raw.get("tool") or "").strip()
    args = raw.get("args")
    if not tool:
        raise ValueError("call needs the name of the tool")
    if args is None:
        args = {}
    if not isinstance(args, Mapping):
        raise ValueError("call.args is an object")
    says = " ".join(str(raw.get("says") or "").split())[:MAX_SAYS_CHARS]
    return {"tool": tool, "args": dict(args), "says": says}


def problem(call: Mapping[str, Any]) -> str:
    """Why ``call`` cannot be made as it stands, or ``""`` when it can.

    Checked against the tools the app has right now. Without a running app
    (no tool gateway) nothing can be checked and nothing is refused: the start
    finds out, and leaves the step to a turn.
    """
    if _gateway() is None:
        return ""
    tool = str(call.get("tool") or "")
    descriptor = _descriptor(tool)
    if descriptor is None:
        return f"There is no tool named {tool!r}."
    if getattr(descriptor, "yields_instructions_only", False):
        return f"The tool {tool!r} only hands out instructions; it does nothing by itself."
    try:
        import jsonschema

        jsonschema.validate(dict(call.get("args") or {}), descriptor.input_schema)
    except ImportError:  # no validator installed: the tool itself checks its arguments
        return ""
    except Exception as exc:  # noqa: BLE001 — any schema complaint is the reason
        first = str(getattr(exc, "message", "") or exc).splitlines()[0]
        return f"The arguments do not fit the tool {tool!r}: {first}"
    return ""


def line(call: Mapping[str, Any]) -> str:
    """The call in plain words, for the person."""
    return str(call.get("says") or "").strip() or str(call.get("tool") or "")


async def run(call: Mapping[str, Any], *, sentence: str) -> tuple[bool, str]:
    """Make the call; ``(done, one line about it)``. Never raises.

    ``sentence`` is the step in the person's words: what they asked for.
    """
    import asyncio

    from dodaios.core.protocols import SupervisorToolRequest

    label = line(call)
    gateway = _gateway()
    if gateway is None:
        return False, f"{label}: the tools are not ready"
    request = SupervisorToolRequest(
        trace_id=uuid4(),
        origin="ritual",
        user_utterance=sentence,
        rationale="A step of a ritual the person started.",
        # Nobody can be asked in this moment: a call that needs a question
        # fails at once and its step goes to a turn.
        config_snapshot={"approval_surface": "unattended"},
    )
    try:
        result = await asyncio.wait_for(
            gateway.execute(str(call.get("tool") or ""), dict(call.get("args") or {}), request),
            timeout=CALL_TIMEOUT_S,
        )
    except TimeoutError:
        log.info("rituals: call %s gave no answer in %.0f s", call.get("tool"), CALL_TIMEOUT_S)
        return False, f"{label}: no answer in time"
    except Exception as exc:  # noqa: BLE001 — the step goes to a turn, with the reason kept
        log.warning("rituals: call %s failed", call.get("tool"), exc_info=True)
        return False, f"{label}: {type(exc).__name__}"
    if getattr(result, "success", False):
        return True, label
    reason = " ".join(str(getattr(result, "error", "") or "it did not work").split())[:200]
    return False, f"{label}: {reason}"


__all__ = ["CALL_TIMEOUT_S", "MAX_SAYS_CHARS", "clean", "line", "problem", "run"]
