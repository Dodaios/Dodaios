"""The Jarvis surface's runner: Jarvis' own brain, driven by text.

This is what the front page's chat runs on when its seat is an API row (a
provider API behind a key, or a server on this machine). A seat on a vendor CLI
(Claude Code and the others, ``surface_kits`` ``cli_seats``) runs on
``runner_cli`` as Jarvis instead. A typed turn is the same turn a spoken one is
-- ``BrainManager.generate`` with its router, its tools, its memory, its wiki
and its safety tiers -- with the keyboard in place of the microphone. Nothing
here spawns a coding CLI or a second agent loop; there is one assistant in
this app and this is how you type at it (maintainer, 2026-08-25).

What the composer's pick changes is which model Jarvis thinks with FOR THIS
CHAT, and how hard: provider, model and effort travel as a
:class:`dodaios.brain.turn_override.TurnOverride` on the one ``generate``
call, and nothing else. The live brain the voice runs on — its active
provider, its config, its dead-lists — is never touched; the first version
of this runner (2026-08-24) switched it and was reverted for exactly that.

The chat's folder is Jarvis' working folder for the turn: the folder tools
(:mod:`dodaios.agent_chat.folder_tools`) join Jarvis' own tools on the turn's
surface, every call goes through ``ToolExecutor``, and the chat's permission
stance decides what asks — through a clickable card, not a spoken "yes"
(:mod:`dodaios.agent_chat.approval_bridge`).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, get_args

from dodaios.agent_chat.approval_bridge import ChatApprovalBridge, ChatGrant, approval_ref
from dodaios.agent_chat.effort import normalize_effort
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.folder_tools import PLAN_STANCE, folder_tools, plan_filter
from dodaios.agent_chat.lead_turn_contract import explicit_skill, resolve_skill_pick
from dodaios.agent_chat.runner_api import messages_from_events
from dodaios.agent_chat.surface_kits import kit_for
from dodaios.agent_chat.tool_catalog import ToolChoice
from dodaios.agent_chat.tools import summarize_call
from dodaios.brain.turn_override import TurnOverride
from dodaios.core.protocols import BrainMessage, ReasoningEffort, Tool, current_chat_turn
from dodaios.i18n import is_known_language, is_supported_locale

if TYPE_CHECKING:
    from uuid import UUID

    from dodaios.agent_chat.runner_api import TurnHandle
    from dodaios.agent_chat.store import AgentChatSession

log = logging.getLogger(__name__)

#: The runner id this module answers to, in the catalog and in ``turn_started``.
RUNNER: Final[str] = "brain"

#: ``MessageSent.source_layer`` for a turn typed into the chat surface. The
#: brain's router reads it; it is a conversational layer, so the router may
#: still spawn a worker on an explicit request (``_NON_SPAWN_SOURCE_LAYERS``
#: does not list it — typing at Jarvis is not a background channel).
SOURCE_LAYER: Final[str] = "ui.chat.typed"

#: How long a card may stay open. A person reading a chat is not on a spoken
#: turn's clock; the executor clamps this to its own ceiling.
APPROVAL_TIMEOUT_S: Final[float] = 600.0

#: The tool-loop ceiling of a chat turn — the API runner's own round budget.
MAX_TURNS: Final[int] = 40

#: How much of the chat's own log rides along as history.
_HISTORY_MAX: Final[int] = 40

_EFFORTS: Final[frozenset[str]] = frozenset(get_args(ReasoningEffort))


def brain_manager() -> Any | None:
    """The live BrainManager, or ``None`` before the brain finished building."""
    from dodaios.core import runtime_refs

    return runtime_refs.get_brain_manager()


# ------------------------------------------------------------------ history


def brain_history_from_events(
    events: list[dict[str, Any]], *, max_messages: int | None = _HISTORY_MAX
) -> list[BrainMessage]:
    """The chat's own log as the turn's history: what was said, in prose.

    User and assistant TEXT only, so no foreign provider's ``tool_use`` ids are
    replayed into a different provider (that fails its validation). A turn's
    tool rounds become one labelled tool record at the top of that turn's
    assistant message: each call with a short, bounded result, errors kept.

    The record is worded as data on purpose. An older format wrote each call
    as an assistant line ("[used tool X]") and dropped the results; smaller
    local models then copied that line instead of making a real tool call
    (issue #978). Capped to the last ``_HISTORY_MAX`` messages.
    """
    # A "[used tool …]" line inside the model's own TEXT is an imitation of a
    # call marker, never a call; replaying it teaches the next turn to type the
    # marker instead of calling the tool, and the made-up answer behind it gets
    # copied (live 2026-10-28). Such an answer is replayed as withdrawn.
    from dodaios.brain.tool_marker import replay_text

    out: list[BrainMessage] = []
    prose: list[str] = []
    calls: list[dict[str, str]] = []
    by_id: dict[str, dict[str, str]] = {}

    def flush_turn() -> None:
        parts = ([_tool_record(calls)] if calls else []) + prose
        text = "\n".join(parts)
        if text.strip():
            out.append(BrainMessage(role="assistant", content=text))
        prose.clear()
        calls.clear()
        by_id.clear()

    for message in messages_from_events(events, max_events=None if max_messages is None else 600):
        if message.role == "user":
            text = message.content if isinstance(message.content, str) else ""
            if text.strip():
                flush_turn()
                out.append(BrainMessage(role="user", content=text))
        elif message.role == "assistant":
            # One answer per turn: the tool rounds and the prose after them
            # are several provider messages but one thing Jarvis said.
            if isinstance(message.content, str):
                text = replay_text(message.content)
                if text.strip():
                    prose.append(text)
                continue
            for block in message.content:
                kind = block.get("type")
                if kind == "text":
                    text = replay_text(str(block.get("text") or ""))
                    if text.strip():
                        prose.append(text)
                elif kind == "tool_use":
                    name = str(block.get("name") or "tool")
                    args = block.get("input") or {}
                    entry = {
                        "name": name,
                        "summary": summarize_call(name, args) if isinstance(args, dict) else "",
                    }
                    calls.append(entry)
                    by_id[str(block.get("id") or "")] = entry
        elif message.role == "tool":
            entry = by_id.get(str(message.tool_call_id or ""))
            if entry is not None:
                entry["result"] = message.content if isinstance(message.content, str) else ""
    flush_turn()
    return out[-max_messages:] if max_messages else out


#: How much of one tool result the record keeps, and how many calls it lists.
_RECORD_RESULT_CHARS: Final[int] = 300
_RECORD_MAX_CALLS: Final[int] = 8

_RECORD_HEADER: Final[str] = (
    "Tool record of this turn (already executed; historical data, not a format "
    "for new calls; new tool calls go through the tool interface):"
)


def _tool_record(calls: list[dict[str, str]]) -> str:
    """The labelled data block for one turn's tool calls and their results."""
    lines = [_RECORD_HEADER]
    for entry in calls[:_RECORD_MAX_CALLS]:
        target = f"{entry['name']} ({entry['summary']})" if entry["summary"] else entry["name"]
        if "result" not in entry:
            lines.append(f"- {target}: no result recorded")
            continue
        result = entry["result"]
        failed = result.startswith("[error]")
        if failed:
            result = result[len("[error]") :]
        result = " ".join(result.split())
        if len(result) > _RECORD_RESULT_CHARS:
            result = result[:_RECORD_RESULT_CHARS] + "…"
        verb = "failed" if failed else "returned"
        lines.append(f"- {target} {verb}: {result}" if result else f"- {target} {verb} nothing")
    if len(calls) > _RECORD_MAX_CALLS:
        lines.append(f"- … and {len(calls) - _RECORD_MAX_CALLS} more calls")
    return "\n".join(lines)


# ----------------------------------------------------------------- override


def build_override(
    session: AgentChatSession,
    brain: Any,
    *,
    stance: str,
    cwd: Path,
    ref: str,
    kit_tools: Mapping[str, Tool] | None = None,
    system_extra: str = "",
) -> TurnOverride:
    """The pick for this turn: the session's provider / model / effort, the
    surface's hands (its kit's tools, else the folder's), and the tool context
    that routes approvals to the card."""
    kit = kit_for(session.surface)
    provider = session.provider
    model = (session.model or "").strip() or _default_model(brain, provider)
    effort = normalize_effort(provider, session.effort)
    reasoning_effort: ReasoningEffort | None = (
        effort if effort in _EFFORTS else None  # type: ignore[assignment]
    )
    return TurnOverride(
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        tools_extra=(
            dict(kit_tools) if kit_tools is not None else folder_tools(cwd, stance=stance)
        ),
        tool_filter=_compose_filters(
            kit.tool_filter,
            kit.session_tool_filter(session) if kit.session_tool_filter is not None else None,
            plan_filter if stance == PLAN_STANCE else None,
        ),
        tools_direct=(
            kit.session_direct_tools(session) if kit.session_direct_tools is not None else None
        ),
        credential_scope=kit.credential_scope,
        system_extra=system_extra,
        tool_context={
            # A typed answer is read, not heard: no spoken two-liners.
            "delivery": "written",
            # The executor asks the card, never the voice sentinel.
            "approval_surface": "interactive",
            "approval_ref": ref,
            "approval_timeout_s": APPROVAL_TIMEOUT_S,
            "tool_origin": kit.tool_origin,
            # The seat the calibration of its predictions is kept for.
            "brain_seat": provider,
            **({"chat_read_only": True} if stance == PLAN_STANCE else {}),
            "cwd": str(cwd),
        },
        max_turns=kit.max_turns or MAX_TURNS,
    )


def _compose_filters(
    *filters: Callable[[dict[str, Tool]], dict[str, Tool]] | None,
) -> Callable[[dict[str, Tool]], dict[str, Tool]] | None:
    """The kit's filter first, then the stance's; ``None`` when neither applies."""
    active = [f for f in filters if f is not None]
    if not active:
        return None

    def _apply(tools: dict[str, Tool]) -> dict[str, Tool]:
        for f in active:
            tools = f(tools)
        return tools

    return _apply


async def kit_payload(session: AgentChatSession, brain: Any) -> tuple[dict[str, Tool] | None, str]:
    """The surface kit's per-turn hands and briefing: ``(tools, system_extra)``.

    ``(None, "")`` on a surface without its own kit tools (the folder tools
    then apply). A kit builder that fails loses only its part — the turn
    still runs, and the failure is in the log.
    """
    kit = kit_for(session.surface)
    if brain is not None:
        from dodaios.brain.tool_surface import reconcile_tool_surface_async

        await reconcile_tool_surface_async(brain)
    cfg = getattr(brain, "_config", None)
    tools: dict[str, Tool] | None = None
    extra = ""
    coding_tool: Tool | None = None
    if session.surface == "jarvis":
        from dodaios.society.surface import coding_tool_for_session

        try:
            coding_tool = await coding_tool_for_session(session.session_id)
            if coding_tool is not None:
                tools = folder_tools(Path(session.cwd), stance=session.permission_mode or "ask")
                tools[coding_tool.name] = coding_tool
        except Exception:
            log.warning("Dodaios chat: coding-session capability unavailable", exc_info=True)
    if kit.session_tools is not None:
        try:
            tools = kit.session_tools(cfg, brain, session)
        except Exception as exc:  # noqa: BLE001 - the turn runs without the kit's hands
            log.warning("surface %s: kit tools not built: %s", session.surface, exc, exc_info=True)
            tools = {}
        if coding_tool is not None:
            # The kit's own hands replace the folder set; the granted
            # coding-session control must survive that replacement.
            tools = {**(tools or {}), coding_tool.name: coding_tool}
    elif kit.tools is not None:
        try:
            tools = kit.tools(cfg, brain)
        except Exception as exc:  # noqa: BLE001 — the turn runs without the kit's hands
            log.warning("surface %s: kit tools not built: %s", session.surface, exc, exc_info=True)
            tools = {}
    if kit.session_system_extra is not None:
        try:
            extra = await kit.session_system_extra(cfg, brain, session)
        except Exception as exc:  # noqa: BLE001 - the turn runs without the briefing
            log.warning(
                "surface %s: kit briefing not built: %s", session.surface, exc, exc_info=True
            )
    elif kit.system_extra is not None:
        try:
            extra = await kit.system_extra(cfg, brain)
        except Exception as exc:  # noqa: BLE001 — the turn runs without the briefing
            log.warning(
                "surface %s: kit briefing not built: %s", session.surface, exc, exc_info=True
            )
    return tools, extra


def _default_model(brain: Any, provider: str) -> str | None:
    fast = getattr(brain, "_fast_model", None)
    if callable(fast):
        try:
            return fast(provider) or None
        except Exception:  # noqa: BLE001 — the provider's own default then
            return None
    return None


# ------------------------------------------------------------- step mirror


def _receipt_of(event: Any) -> dict[str, str] | None:
    """The action receipt an executed call carries (``trust/receipts``), or ``None``."""
    receipt_id = str(getattr(event, "receipt_id", "") or "")
    if not receipt_id:
        return None
    return {
        "id": receipt_id,
        "state": str(getattr(event, "receipt_state", "") or ""),
        "summary": str(getattr(event, "receipt_summary", "") or ""),
        "link": str(getattr(event, "receipt_link", "") or ""),
    }


class _StepMirror:
    """Turns THIS turn's bus events into the timeline's step rows.

    The brain does not report its work to the chat; it publishes it on the
    app bus, where the voice lane and the run inspector read it too. This
    subscribes for the length of one turn and translates — for the events
    that carry this turn's trace only, so a voice turn running alongside
    never draws rows in the chat:

    * ``ActionProposed`` -> a tool row, plus its ``rationale`` as reasoning
      text. That sentence is the model's OWN words for why it reaches for the
      tool — never a second "explain yourself" call.
    * ``ActionExecuted`` / ``ActionDenied`` -> that row's result.
    * ``ToolCallStarted`` / ``ToolCallCompleted`` -> the same for the paths
      that publish those instead.

    Rows are paired per tool name, oldest open first. Read-only and
    defensive: a malformed event never reaches the brain (AP-18).
    """

    __slots__ = ("_bus", "_children", "_emit", "_open", "_seen_text", "_trace_id", "_turn_id")

    def __init__(self, emit: Any, turn_id: str, bus: Any | None, trace_id: UUID) -> None:
        self._emit = emit
        self._turn_id = turn_id
        self._bus = bus
        self._trace_id = trace_id
        self._open: list[tuple[str, str]] = []  # (tool name, call id)
        self._children: set[UUID] = set()
        self._seen_text: set[str] = set()

    def start(self) -> None:
        if self._bus is not None and hasattr(self._bus, "subscribe_all"):
            self._bus.subscribe_all(self._on_event)

    def stop(self) -> None:
        if self._bus is not None and hasattr(self._bus, "unsubscribe_all"):
            try:
                self._bus.unsubscribe_all(self._on_event)
            except Exception:  # noqa: BLE001 — detaching must never raise
                log.debug("brain runner: could not detach the step mirror", exc_info=True)

    def open_call_id(self, tool_name: str) -> str:
        """The open row for ``tool_name`` (the bridge's card hangs off it), else ""."""
        for name, call_id in self._open:
            if name == tool_name:
                return call_id
        return ""

    async def _on_event(self, event: Any) -> None:
        try:
            await self._translate(event)
        except Exception:  # noqa: BLE001 — AP-18: never leave a subscriber
            log.debug("brain runner: step mirror skipped an event", exc_info=True)

    def _mine(self, event: Any) -> bool:
        return getattr(event, "trace_id", None) == self._trace_id

    async def _open_call(self, tool_name: str, args: Any) -> None:
        call_id = uuid.uuid4().hex
        self._open.append((tool_name, call_id))
        if isinstance(args, dict):
            payload_in: Any = args
        elif args:
            payload_in = {"arguments": str(args)}
        else:
            payload_in = {}
        await self._emit(
            "tool_call",
            {"turn_id": self._turn_id, "call_id": call_id, "name": tool_name, "input": payload_in},
        )

    async def _close_call(
        self,
        tool_name: str,
        *,
        ok: bool,
        output: str,
        duration_ms: Any,
        receipt: dict[str, str] | None = None,
    ) -> None:
        index = next((i for i, (name, _) in enumerate(self._open) if name == tool_name), None)
        if index is None:
            # A result with no row of its own (another path's, or a report
            # without a start) would draw a headless row; drop it.
            return
        _, call_id = self._open.pop(index)
        await self._emit(
            "tool_result",
            {
                "turn_id": self._turn_id,
                "call_id": call_id,
                "output": str(output)[:2000],
                "is_error": not ok,
                "duration_ms": int(duration_ms or 0),
                **({"receipt": receipt} if receipt else {}),
            },
        )

    async def _translate(self, event: Any) -> None:
        name = type(event).__name__
        if name == "ActionProposed" and self._mine(event):
            text = (getattr(event, "rationale", "") or "").strip()
            if text and text not in self._seen_text:
                self._seen_text.add(text)
                await self._emit("reasoning_delta", {"turn_id": self._turn_id, "text": text})
            await self._open_call(
                getattr(event, "tool_name", "") or "tool", getattr(event, "args", None)
            )
        elif name == "ActionExecuted" and self._mine(event):
            await self._close_call(
                getattr(event, "tool_name", "") or "tool",
                ok=bool(getattr(event, "success", False)),
                output=getattr(event, "error", None) or getattr(event, "output_preview", "") or "",
                duration_ms=getattr(event, "duration_ms", 0),
                receipt=_receipt_of(event),
            )
        elif name == "ActionDenied" and self._mine(event):
            await self._close_call(
                getattr(event, "tool_name", "") or "tool",
                ok=False,
                output=str(getattr(event, "reason", "") or "denied"),
                duration_ms=0,
            )
        elif (
            name == "ToolCallStarted" and getattr(event, "parent_trace_id", None) == self._trace_id
        ):
            self._children.add(event.trace_id)
            await self._open_call(
                getattr(event, "tool_name", "") or "tool", getattr(event, "args_preview", "") or ""
            )
        elif name == "ToolCallCompleted" and getattr(event, "trace_id", None) in self._children:
            self._children.discard(event.trace_id)
            tool_name = getattr(event, "tool_name", "") or (
                self._open[0][0] if self._open else "tool"
            )
            await self._close_call(
                tool_name,
                ok=bool(getattr(event, "success", False)),
                output=getattr(event, "error", None) or getattr(event, "output_preview", "") or "",
                duration_ms=getattr(event, "duration_ms", 0),
            )


# ------------------------------------------------------------------- turn


async def run_brain_turn(
    handle: TurnHandle,
    text: str,
    *,
    bridge: ChatApprovalBridge | None,
    always_allowed: set[str],
    tool_choices: list[ToolChoice] | None = None,
) -> None:
    """Run one typed turn on Jarvis' brain, streaming it into the timeline."""
    started = time.monotonic()
    turn_id = handle.turn_id
    message_id = uuid.uuid4().hex
    session = handle.session

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        await handle.emit(make_event(kind, payload))

    mirror = _StepMirror(emit, turn_id, handle.bus, handle.trace_id)
    ref = approval_ref(session.session_id)

    async def finish(status: str, usage: dict[str, Any], error: str | None = None) -> None:
        await emit(
            "turn_finished",
            {
                "turn_id": turn_id,
                "status": status,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "usage": usage,
                "error": error,
            },
        )

    brain = brain_manager()
    if brain is None or not callable(getattr(brain, "generate", None)):
        await finish(
            "error", {}, "Dodaios' brain is still starting up. Give it a moment and send again."
        )
        return

    cwd = Path(session.cwd or Path.home())
    stance = handle.stance or "ask"
    kit_tools, system_extra = await kit_payload(session, brain)
    from dodaios.agent_chat.delegation_wait import CONTINUE_TURN, is_continuation_prompt

    person_request = ""
    if is_continuation_prompt(text):
        # The brain reads the turn's text for deterministic routes: which
        # coding pane is addressed, what to cancel, where to navigate. A
        # continuation quotes the original order and the agents' reports, so
        # read as the person's words it would send that order to the pane
        # again. It is this turn's briefing instead.
        system_extra += "\n\n" + text
        text = CONTINUE_TURN
        from dodaios.core.protocols import current_chat_turn

        origin = current_chat_turn.get()
        person_request = origin.user_text if origin is not None else ""
        if person_request and not handle.output_language:
            # The answer follows the request it continues, not the neutral
            # English line above — in any language, not only the four with
            # translated system phrases.
            from dodaios.core.turn_language import (
                conversation_language_from_history,
                resolve_conversation_language,
            )

            language = resolve_conversation_language(
                getattr(brain, "reply_language", "auto") or "auto",
                "unknown",
                person_request,
                conversation_language=conversation_language_from_history(
                    brain_history_from_events(handle.history)
                ),
            )
            if is_known_language(language):
                handle.output_language = language
    board = getattr(getattr(handle, "control_service", None), "parked_work", None)
    background = board.context_note(session.session_id) if board is not None else ""
    if background:
        system_extra += "\n\n" + background
    if tool_choices:
        from dodaios.agent_chat.tool_catalog import (
            live_catalog,
            resolve_choices,
            selection_briefing,
            selection_tools,
        )

        try:
            current = await asyncio.to_thread(live_catalog, brain, cwd=str(cwd), stance=stance)
            choices = resolve_choices([row.id for row in tool_choices], current)
            base = dict(getattr(brain, "_tools", {}) or {})
            extra = dict(kit_tools) if kit_tools is not None else folder_tools(cwd, stance=stance)
            base.update(extra)
            extra.update(selection_tools(choices, base))
            kit_tools = extra
            system_extra += selection_briefing(choices)
        except ValueError as exc:
            await finish("error", {}, str(exc))
            return
    override = build_override(
        session,
        brain,
        stance=stance,
        cwd=cwd,
        ref=ref,
        kit_tools=kit_tools,
        system_extra=system_extra,
    )
    if session.surface == "jarvis" and _is_lead(session.session_id):
        # The lead conversation gets the lead doctrine and the ecosystem map.
        override = replace(override, lead=True)
    if person_request:
        # Tools that check a call against what the person asked for (a task
        # unrelated to the turn, an authorized fan-out) read the request, not
        # the neutral continue line.
        override = replace(
            override, tool_context={**override.tool_context, "person_request": person_request}
        )
    _note_skill_trigger(brain, text)

    # The lead's turn verifies its answer against the tool log and takes typed
    # messages that arrive mid-turn (the CLI seat's steering, for the brain).
    steer_inbox: list[str] = []
    steer_open = False
    if session.surface == "jarvis" and _is_lead(session.session_id):
        from dodaios.agent_chat.turn_verify import lead_loop_control

        def _drain_steer() -> list[str]:
            taken, steer_inbox[:] = list(steer_inbox), []
            return taken

        async def _steer(message: str) -> bool:
            if not steer_open or handle.cancel.is_set():
                return False
            steer_inbox.append(message)
            return True

        override = replace(override, loop_control=lead_loop_control(_drain_steer))
        if handle.on_steer is not None:
            steer_open = True
            handle.on_steer(_steer)

    if bridge is not None:
        from dodaios.society.surface import requires_explicit_approval

        bridge.arm(
            ref,
            ChatGrant(
                session_id=session.session_id,
                turn_id=turn_id,
                stance=stance,
                always_allowed=always_allowed,
                ask=handle.request_approval,
                call_id_for=mirror.open_call_id,
                force_ask=(
                    lambda name, args: requires_explicit_approval(session.session_id, name, args)
                )
                if session.surface == "society"
                else lambda _name, _args: False,
            ),
        )

    # The "thinking" line the timeline shows until the first words arrive,
    # and the watcher that fills it: every tool Jarvis reaches for and every
    # sentence it writes next to one lands in the timeline as it happens.
    await emit("reasoning_started", {"turn_id": turn_id, "message_id": message_id})
    mirror.start()

    loop = asyncio.get_running_loop()
    seen: list[str] = []

    def feed(chunk: str) -> None:
        """Called by the brain as the answer is produced — a CHUNK, not the whole so far."""
        if not chunk:
            return
        seen.append(chunk)
        # The consumer is synchronous (the brain's contract); hand the emit
        # back to the loop rather than blocking the producer.
        asyncio.run_coroutine_threadsafe(
            emit("text_delta", {"turn_id": turn_id, "message_id": message_id, "text": chunk}),
            loop,
        )

    status = "done"
    error: str | None = None
    reply = ""
    try:
        reply = await _generate(brain, text, handle, override, feed)
    except asyncio.CancelledError:
        status = "cancelled"
    except Exception as exc:  # noqa: BLE001 — the timeline must never spin forever
        log.exception("brain chat turn %s failed", turn_id)
        status, error = "error", f"{type(exc).__name__}: {exc}"
    finally:
        steer_open = False
        if handle.on_steer is not None:
            handle.on_steer(None)
        if bridge is not None:
            bridge.disarm(ref)
        mirror.stop()
    if steer_inbox:
        # Typed as the answer was being closed: say so instead of dropping it.
        await emit(
            "notice",
            {
                "kind": "steer_arrived_late",
                "turn_id": turn_id,
                "text": "This message arrived as the turn ended and was not read. "
                "Send it again: " + " / ".join(steer_inbox)[:600],
            },
        )

    if status == "done" and handle.cancel.is_set():
        status = "cancelled"
    if status == "done" and override.receipt.provider_down:
        # Every provider failed: the apology the brain returns is a spoken
        # courtesy, not an answer. Fail the turn (failed-turn card, "send
        # again") and keep the apology out of the stored conversation.
        from dodaios.agent_chat.turn_errors import provider_down_reason

        log.warning(
            "brain chat turn %s: every provider failed (%s)",
            turn_id,
            override.receipt.provider_down_cause,
        )
        status, error = "error", provider_down_reason(override.receipt.provider_down_cause)
    elif status == "done":
        answer = (reply or "").strip() or "".join(seen).strip()
        if answer:
            await emit(
                "assistant_text", {"turn_id": turn_id, "message_id": message_id, "text": answer}
            )
        # Keep the safe explanation visible, but distinguish provider success
        # from an answer rejected by the execution/evidence backstop.
        if override.receipt.guard_failure:
            status = "error"
            error = override.receipt.failure_reason or "guarded_response"
    await finish(status, override.receipt.usage(), error)


async def _generate(
    brain: Any,
    text: str,
    handle: TurnHandle,
    override: TurnOverride,
    feed: Callable[[str], None],
) -> str:
    """The one ``generate`` call, under the chat's credentials, cancellable.

    ``allow_voice_confirm=False`` is load-bearing: the executor must never
    park a chat's consequential action in the manager-wide voice slot that
    the NEXT spoken turn would consume. The chat's stance and card decide
    (``approval_surface`` in the tool context).
    """
    from dodaios.core.config import get_jarvis_agent_secret, override_provider_secrets

    session = handle.session
    history = brain_history_from_events(handle.history)
    output_language = getattr(handle, "output_language", "")
    if session.surface == "society" and not handle.continuation:
        from dodaios.society.reply_preference import resolve_agent_reply_language

        output_language = await resolve_agent_reply_language(
            session.session_id, text, output_language
        )
    handle.output_language = output_language
    kwargs: dict[str, Any] = {
        "use_history": False,
        "history_override": history,
        "conversation_id": session.session_id,
        "source_layer": SOURCE_LAYER,
        "trace_id": handle.trace_id,
        "allow_voice_confirm": False,
        "emit_tool_ack": False,
        "publish_response": False,
        "text_consumer": feed,
        "turn_override": override,
    }
    if output_language:
        kwargs["force_output_language"] = output_language
    from dodaios.agent_chat.delegation_wait import CONTINUE_TURN

    if text == CONTINUE_TURN:
        # The neutral English "continue" line is not the person's words: the
        # conversation keeps its own language (a Turkish chat flipped to
        # English on every delegated result, forensic 2026-10-19).
        origin = current_chat_turn.get()
        kwargs["language_text"] = origin.user_text if origin is not None else ""
    secret = _agent_secret(get_jarvis_agent_secret, session.provider)
    overrides = {session.provider: secret} if secret else {}
    pending_before = set(getattr(brain, "_ide_background_tasks", ()))
    # The task inherits the credential override through its context copy, so
    # the scoped brain instance resolves the Agents-tab key on first use.
    with override_provider_secrets(overrides):
        lead_thread = session.surface == "jarvis" and _is_lead(session.session_id)
        if session.surface == "society" or lead_thread:
            from dodaios.society.conversation import prepare_history
            from dodaios.society.runtime import current_runtime

            runtime = current_runtime()
            getter = getattr(brain, "_get_brain", None)
            if runtime is not None and callable(getter):
                provider = getter(
                    session.provider,
                    session.model or None,
                    scope=f"society-compaction:{session.session_id}",
                )
                hint = (
                    {"recall_hint": "older details are summarized, ask if one is missing"}
                    if lead_thread
                    else {}
                )
                prompt_chars = len(override.system_extra) + 16000
                try:
                    kwargs["history_override"] = await prepare_history(
                        runtime,
                        session,
                        handle.history,
                        text,
                        provider,
                        prompt_chars=prompt_chars,
                        **hint,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — compaction must never brick the chat
                    # The same input would fail every following turn, so answer
                    # from the last saved summary plus the newest tail and say so.
                    log.warning(
                        "compaction failed for %s: %s; answering from the last summary",
                        session.session_id,
                        exc,
                    )
                    from dodaios.society.conversation import fallback_history

                    kwargs["history_override"] = await fallback_history(
                        runtime,
                        session,
                        handle.history,
                        provider,
                        prompt_chars=prompt_chars,
                        **hint,
                    )
                    await handle.emit(
                        make_event(
                            "notice",
                            {
                                "kind": "context_compaction_failed",
                                "turn_id": handle.turn_id,
                                "text": "Older parts of this conversation could not be "
                                "summarized this time, so this answer uses the last saved "
                                "summary and the newest messages. Nothing was deleted.",
                                "reason": f"{type(exc).__name__}: {exc}"[:300],
                            },
                        )
                    )
        task: asyncio.Task[str] = asyncio.create_task(
            brain.generate(text, **kwargs), name=f"agent-chat-brain-{handle.turn_id[:8]}"
        )
    waiter = asyncio.create_task(handle.cancel.wait())
    try:
        done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            result = await task
            from dodaios.core.delegated_work import register_dispatch

            for delivery in set(getattr(brain, "_ide_background_tasks", ())) - pending_before:
                register_dispatch(delivery, ["Coding agent delivery"])
            # Reuse the brain's authoritative decision while still holding its
            # turn lock; do not detect language from an English result prompt.
            if not handle.output_language:
                pin = getattr(brain, "reply_language", "")
                language = (
                    pin if is_supported_locale(pin) else getattr(brain, "conversation_language", "")
                )
                if is_known_language(language):
                    handle.output_language = language
            return result
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001 — the turn is over
            log.debug("brain runner: cancelled turn ended with %r", exc)
        raise asyncio.CancelledError
    finally:
        waiter.cancel()


def _is_lead(session_id: str) -> bool:
    """True when ``session_id`` is the lead's one endless conversation."""
    try:
        from dodaios.agent_chat.lead import is_lead
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        svc = runtime.chat_service() if runtime is not None else None
    except Exception:  # noqa: BLE001 — no service: keep the plain window
        return False
    return svc is not None and is_lead(svc, session_id)


def _agent_secret(resolver: Callable[[str], str | None], provider: str) -> str | None:
    try:
        return resolver(provider)
    except Exception:  # noqa: BLE001 — no dedicated key: the brain resolves as usual
        log.debug("brain runner: no agent-tier secret for %s", provider, exc_info=True)
        return None


def _note_skill_trigger(brain: Any, text: str) -> None:
    """The desktop text path's pre-brain hook, verbatim in effect: a skill
    whose trigger matches is noted on the brain, which injects its
    instructions into this turn (desktop_app._on_user_message). A leading
    ``/slug`` names the skill outright and wins over the trigger matcher. The
    resolution is the lead turn contract's, shared with the CLI seats."""
    note = getattr(brain, "note_skill_trigger", None)
    if not callable(note):
        return
    pick = resolve_skill_pick(text)
    if pick is None:
        return
    try:
        note(pick.name, content=pick.content, source=pick.source)
    except Exception:  # noqa: BLE001 — the hook is defensive; a crash must never cost the turn
        log.debug("brain runner: skill pre-hook skipped", exc_info=True)


__all__ = [
    "APPROVAL_TIMEOUT_S",
    "MAX_TURNS",
    "RUNNER",
    "SOURCE_LAYER",
    "brain_history_from_events",
    "brain_manager",
    "build_override",
    "explicit_skill",
    "kit_payload",
    "run_brain_turn",
]
