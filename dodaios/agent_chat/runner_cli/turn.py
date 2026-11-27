"""Turn orchestration: run_cli_turn, resume, seat and model fallbacks."""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Final

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat import runner_cli as _rc
from dodaios.agent_chat.approval_bridge import approval_ref
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.runner_api import TurnHandle, reply_language_line
from dodaios.agent_chat.runner_cli.base import (
    _CLAUDE_CODE_RUNNERS,
    _SEAT_CONVERSATIONS,
    _TURN_SEATS,
    ACCOUNT_OVERRIDE,
    CliPlan,
    _is_usage_limit,
    log,
)
from dodaios.agent_chat.runner_cli.claude import bridge_stance
from dodaios.agent_chat.runner_cli.drive import _SHAPES, _TURN_TIMEOUT_S, _Outcome
from dodaios.agent_chat.runner_cli.kimi import _kimi_session_after
from dodaios.agent_chat.tool_context import register_turn, unregister_turn
from dodaios.core.response_style import KEEP_GOING_ON_TOOL_FAILURE

# Error text the CLIs print when the conversation we try to resume is gone
# (a fresh install, a pruned session store, a first turn that died before
# the CLI wrote anything). The turn is then re-run once without resume.
_RESUME_LOST_MARKERS: Final[tuple[str, ...]] = (
    "no conversation found",
    "session not found",
    "no session found",
    "could not find session",
    "unknown session",
    "not found: ",
    "does not exist",
)


def _resume_was_lost(error: str | None, runner: str = "") -> bool:
    from dodaios.agent_chat.runner_acp import supports_runner

    if supports_runner(runner):
        # An ACP runtime says so explicitly; "model does not exist" from the
        # prompt itself must not buy a second, fresh (and paid) turn.
        from dodaios.agent_runtimes.acp import RESUME_LOST_ERROR

        return (error or "").startswith(RESUME_LOST_ERROR)
    low = (error or "").lower()
    return any(m in low for m in _RESUME_LOST_MARKERS)


#: How long a turn keeps sending its message again while an agent runtime is
#: still starting (or repairing its data) before the refusal stands.
_RUNTIME_READY_WAIT_S: Final[float] = 180.0

#: First pause between two sends, doubled up to the cap.
_RUNTIME_READY_FIRST_DELAY_S: Final[float] = 1.0

_RUNTIME_READY_MAX_DELAY_S: Final[float] = 10.0


async def _send_again_when_runtime_ready(
    handle: TurnHandle,
    outcome: _Outcome,
    runner: str,
    send: Callable[[], Awaitable[_Outcome]],
    recovery: Any,
) -> _Outcome:
    """Send the message again while an agent runtime refuses it as not ready yet.

    OpenClaw answers a message that arrives while its Gateway finishes its
    start-up inspection with UNAVAILABLE before any model call, and one whose
    stored data needs a migration until its restart ran it. The person's
    message is never dropped for that: it is sent again with a growing pause
    (the failed turn already marked a Gateway that needs repair for a restart)
    for at most :data:`_RUNTIME_READY_WAIT_S`. Nothing was billed by a refusal.
    """
    from dodaios.agent_chat.runner_acp import supports_runner
    from dodaios.agent_runtimes.base import not_ready_kind

    if not supports_runner(runner):
        return outcome
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _rc._RUNTIME_READY_WAIT_S
    delay = _rc._RUNTIME_READY_FIRST_DELAY_S
    repairs = 0
    while outcome.status == "error" and not recovery.had_tool_calls and not handle.cancel.is_set():
        kind = not_ready_kind(outcome.error)
        if not kind:
            break
        if kind == "repair":
            if repairs:
                break  # one restart (with its migration) per turn; its error stands
            repairs += 1
        left = deadline - loop.time()
        if left <= 0:
            log.warning(
                "agent chat %s: %s still not ready after %.0f s",
                handle.turn_id,
                runner,
                _rc._RUNTIME_READY_WAIT_S,
            )
            break
        log.info(
            "agent chat %s: %s not ready (%s: %s); sending again in %.0f s",
            handle.turn_id,
            runner,
            kind,
            (outcome.error or "")[:160],
            min(delay, left),
        )
        with suppress(TimeoutError):  # the pause ended; send again below
            await asyncio.wait_for(handle.cancel.wait(), timeout=min(delay, left))
        if handle.cancel.is_set():
            break
        delay = min(delay * 2, _rc._RUNTIME_READY_MAX_DELAY_S)
        outcome = await send()
    return outcome


# A print-mode CLI that cannot ask back treats an unanswered permission
# prompt as "the user cancelled this tool" and then *exits* — Grok
# StopCancelled / agy 1.1.26. The model never gets a second round. These
# markers are that abort, not a person hitting Stop on the chat.
_TOOL_ABORT_MARKERS: Final[tuple[str, ...]] = (
    "user cancelled the execution",
    "cancelled the execution of tool",
    "tool not found",
    "permission_cancelled",
    "permission_rejected",
    "permission denied",
    "hasn't granted permission",
    "has not granted permission",
    "requires approval",
    "declined this action",
    "the person declined",
)


def _tool_abort_is_recoverable(error: str | None) -> bool:
    low = (error or "").lower()
    return any(m in low for m in _TOOL_ABORT_MARKERS)


def _keep_going_prompt(
    user_text: str,
    error: str | None,
    *,
    receipt_hint: str | None = None,
) -> str:
    review = f"{receipt_hint}\n\n" if receipt_hint else ""
    # Only a real error names the last call; a receipt hint alone is about an
    # earlier call that no later call settled.
    head = (
        f"The last tool call was cancelled or failed:\n{error.strip()[:500]}"
        if error and error.strip()
        else "An earlier tool call failed and no later call settled it."
    )
    # The run before this one may already have answered, often with the very
    # blocker this note is about; told nothing about that, the model wrote the
    # same answer a second time (the Gmail turn of 2026-11-13).
    return (
        f"{head}\n\n"
        f"{KEEP_GOING_ON_TOOL_FAILURE}\n\n"
        f"{review}"
        f"{_ALREADY_SENT}\n\n"
        "Original request:\n"
        f"{user_text}"
    )


#: The recovery run continues a turn whose messages the person has already read.
_ALREADY_SENT: Final[str] = (
    "What you wrote earlier in this turn has already reached the person. Do not repeat "
    "it. If it already says what is blocked and what they need, end now without writing "
    "anything more; otherwise write only what is new, briefly."
)


def _merge_cli_outcome(first: _Outcome, second: _Outcome) -> _Outcome:
    usage = dict(first.usage)
    for key, value in second.usage.items():
        usage[key] = usage.get(key, 0) + value
    cost: float | None = None
    if first.cost_usd is not None or second.cost_usd is not None:
        cost = (first.cost_usd or 0.0) + (second.cost_usd or 0.0)
    return _Outcome(
        second.status,
        second.error,
        usage,
        cost,
        second.vendor_session or first.vendor_session,
        second.limit,
        second.tool_error,
    )


#: The thread notice that says a turn moved to the next subscription.
SEAT_SWITCH_NOTICE_KIND: Final[str] = "seat_switched"


def _ensure_seat_watch() -> None:
    """Start the seat watch, so the seats threads run on are watched too."""
    try:
        from dodaios.agentic_ide import seat_switch

        seat_switch.ensure_watch()
    except Exception as exc:  # noqa: BLE001 - watching seats is additive
        log.debug("Seat watch not started (%s)", type(exc).__name__)


async def _continue_on_next_seat(
    handle: TurnHandle,
    outcome: _Outcome,
    runner: str,
    turn_seats: dict[str, str],
    *,
    started_work: bool,
    run_again: Callable[[str, str | None], Awaitable[_Outcome]],
    user_text: str,
    resume: str | None,
) -> _Outcome:
    """Carry a turn its seat's usage limit cut off on to the next subscription.

    Only for CLIs whose conversation can follow a seat
    (``_SEAT_CONVERSATIONS``) and only with auto switch on
    (:func:`dodaios.agentic_ide.seat_switch.fail_over` decides the seat). The
    same conversation resumes on the new seat (``_carry_thread_conversation``
    copies it there): a turn that already worked is told to continue, one
    the provider refused before it started gets the person's message again.
    Once per turn; with no other seat left the refusal stands.
    """
    pair = _SEAT_CONVERSATIONS.get(runner)
    if pair is None or not _is_usage_limit(outcome.error):
        return outcome
    platform = pair[0]
    spent = turn_seats.get(platform)
    if not spent:
        return outcome
    if _model_fallback_takes(handle, outcome, runner, spent):
        # One model family is spent ("your Fable limit"), not the whole
        # subscription: the thread's other models still run on this seat.
        # Taking the seat out of rotation would move every pane off it.
        return outcome
    try:
        from dodaios.agentic_ide import seat_switch
        from dodaios.society.remote import placement_for_session

        if await placement_for_session(handle.session) is not None:
            return outcome  # another computer's CLI runs on that computer's own login
        target = await seat_switch.fail_over(platform, spent, error=outcome.error or "")
        if not target or target == spent:
            return outcome
        from_label, to_label = await asyncio.to_thread(
            lambda: (seat_switch._label(spent), seat_switch._label(target))
        )
    except Exception as exc:  # noqa: BLE001 - the refusal stays the honest answer
        log.warning("agent chat %s: no seat failover (%s)", handle.turn_id, exc)
        return outcome
    log.info(
        "agent chat %s: %s seat %s hit its usage limit; continuing on %s",
        handle.turn_id,
        platform,
        spent,
        target,
    )
    await handle.emit(
        make_event(
            "notice",
            {
                "kind": SEAT_SWITCH_NOTICE_KIND,
                "text": f"{from_label} reached its usage limit; continuing on {to_label}.",
                "platform": platform,
                "from_label": from_label,
                "to_label": to_label,
            },
        )
    )
    conversation = outcome.vendor_session or resume
    prompt = seat_switch.CONTINUE_PROMPT if started_work and conversation else user_text
    again = await run_again(prompt, conversation)
    return _merge_cli_outcome(outcome, again)


#: Surfaces whose threads switch models in place when one hits its limit:
#: the coding threads of the Agentic IDE. The lead's own chat and society
#: agents keep the model the person pinned.
_MODEL_FALLBACK_SURFACES: Final[frozenset[str]] = frozenset({"agent"})


def _model_fallback_takes(handle: TurnHandle, outcome: _Outcome, runner: str, seat: str) -> bool:
    """Whether the model switch, not the subscription switch, answers this limit.

    So when the limit names one model family and the thread has a model of
    another family left to go on with on the same seat.
    """
    from dodaios.agent_chat import model_fallback as mf

    session = handle.session
    if getattr(session, "surface", "") not in _MODEL_FALLBACK_SURFACES:
        return False
    current = str(getattr(session, "model", "") or "")
    hit = mf.detect(None if outcome.tool_error else outcome.error, outcome.limit, model=current)
    if hit is None or not mf.switch_helps(hit):
        return False
    chain = mf.chain_for(runner)
    if not chain or not mf.enabled():
        return False
    return bool(mf.candidates(runner, current, hit=hit, seat=seat, chain=chain))


def _on_model(handle: TurnHandle, model: str) -> TurnHandle:
    """``handle`` for a run on ``model``; the thread itself is not changed yet."""
    session = handle.session
    try:
        moved = _rc.replace(session, model=model)
    except TypeError:  # not a session record (a test double): a copy with the field set
        moved = copy.copy(session)
        moved.model = model
    return _rc.replace(handle, session=moved)


async def _switch_thread_model(handle: TurnHandle, model: str) -> TurnHandle:
    """Put the thread on ``model``: stored, told to the composer, used from here on."""
    session = handle.session
    store = getattr(handle.control_service, "store", None)
    update = getattr(store, "update_session", None)
    if callable(update):
        try:
            await asyncio.to_thread(update, session.session_id, model=model)
        except Exception as exc:  # noqa: BLE001 - this turn still ran on the new model
            log.warning("agent chat %s: model switch not stored (%s)", handle.turn_id, exc)
    await handle.emit(make_event("session_updated", {"model": model}))
    return _on_model(handle, model)


def _fallback_spent(runner: str, seat: str, spent: list[Any], chain: tuple[str, ...]) -> list[Any]:
    """``spent`` plus the chain's models already known to be out, each named once."""
    from dodaios.agent_chat import model_fallback as mf

    out = list(spent)
    named = {s.label for s in out} | {mf.family_of(s.model) or s.model for s in out}
    for model in chain:
        until = mf.limited_until(runner, seat, model)
        label = mf.family_of(model) or mf.model_label(model)
        if until is None or label in named or model in named:
            continue
        named.add(label)
        out.append(mf.Spent(model, mf.model_label(model), until))
    return out


async def _continue_on_fallback_model(
    handle: TurnHandle,
    outcome: _Outcome,
    runner: str,
    turn_seats: dict[str, str],
    *,
    started_work: Callable[[], bool],
    run_again: Callable[[TurnHandle, str, str | None], Awaitable[_Outcome]],
    user_text: str,
    resume: str | None,
) -> tuple[_Outcome, TurnHandle]:
    """Carry a thread whose model hit its limit on to the next model of the chain.

    Detection reads the stream's own limit signal first and the CLI's own
    error text only as a fallback (:func:`model_fallback.detect`), never a
    tool's output or the stderr tail (``_Outcome.tool_error``). Only a limit
    of one model family is switched around (:func:`model_fallback.switch_helps`):
    an account-wide limit or a short rate limit leaves the model alone. The
    SAME conversation resumes on the next model down the chain, with a
    ``model_fallback`` notice: a turn that already worked is told to continue,
    one refused before it started gets the person's message again. The thread
    keeps the new model (stored, ``session_updated`` for the composer) only
    once a run on it went through; a model the CLI cannot use at all is
    skipped. Each model is tried at most once per turn and models known to be
    out are skipped; when none is left the turn stops once, on the model it
    had, with a ``model_fallback_exhausted`` notice and an error that names
    the first reset. Off with ``[agentic_ide] model_fallback = false`` (the
    limit is still noted).
    """
    from dodaios.agent_chat import model_fallback as mf

    session = handle.session
    if getattr(session, "surface", "") not in _MODEL_FALLBACK_SURFACES:
        return outcome, handle
    current = str(getattr(session, "model", "") or "")
    hit = mf.detect(None if outcome.tool_error else outcome.error, outcome.limit, model=current)
    if hit is None:
        return outcome, handle
    pair = _SEAT_CONVERSATIONS.get(runner)
    seat = turn_seats.get(pair[0], "") if pair else ""
    until = mf.note_limited(runner, seat, current, hit)
    chain = mf.chain_for(runner)
    if not chain or not mf.enabled() or not mf.switch_helps(hit):
        return outcome, handle
    #: The thread as it is: it stays on its model unless a switch goes through.
    original = handle
    spent: list[mf.Spent] = [mf.Spent(current, mf.limit_label(hit, current), until)]
    tried: set[str] = {current}
    conversation = outcome.vendor_session or resume
    log.info(
        "agent chat %s: %s model %r hit its %s limit (%s signal, until %s)",
        handle.turn_id,
        runner,
        current,
        hit.kind,
        hit.source,
        mf.iso_utc(until) or "unknown",
    )
    while not handle.cancel.is_set():
        options = mf.candidates(runner, current, hit=hit, tried=tried, seat=seat, chain=chain)
        if not options:
            break
        target = options[0]
        tried.add(target)
        await handle.emit(
            make_event(
                "notice",
                {**mf.switch_notice(hit, current, target, until), "turn_id": handle.turn_id},
            )
        )
        log.info("agent chat %s: continuing on %r", handle.turn_id, target)
        prompt = (
            mf.CONTINUE_PROMPT.format(model=mf.model_label(target))
            if started_work() and conversation
            else user_text
        )
        again = await run_again(_on_model(original, target), prompt, conversation)
        outcome = _merge_cli_outcome(outcome, again)
        conversation = again.vendor_session or conversation
        if again.status != "error":
            return outcome, await _switch_thread_model(original, target)
        said = None if again.tool_error else again.error
        if again.limit is None and mf.model_unusable(said):
            # The CLI cannot run this model at all (not on this plan, a
            # retired id): the next one down may still work.
            log.info("agent chat %s: %r is not usable here; skipping it", handle.turn_id, target)
            current = target
            continue
        following = mf.detect(said, again.limit, model=target)
        if following is None:
            return outcome, original  # another failure: its own error stands
        until = mf.note_limited(runner, seat, target, following)
        spent.append(mf.Spent(target, mf.limit_label(following, target), until))
        if not mf.switch_helps(following):
            break  # the whole account is out: no other model helps
        current, hit = target, following
    if handle.cancel.is_set():
        return outcome, original
    spent = _fallback_spent(runner, seat, spent, chain)
    log.info(
        "agent chat %s: every fallback model of %s is limited (%s); stopping",
        handle.turn_id,
        runner,
        ", ".join(s.label for s in spent),
    )
    await handle.emit(
        make_event("notice", {**mf.exhausted_notice(spent), "turn_id": handle.turn_id})
    )
    return _rc.replace(outcome, error=mf.exhausted_error(spent), tool_error=False), original


async def _surface_identity(session: Any) -> str | None:
    """A surface whose identity is per session (an agent-society member's
    briefing) hands that text over; ``None`` keeps Jarvis' own layers."""
    from dodaios.agent_chat.surface_kits import kit_for

    kit = kit_for(getattr(session, "surface", "") or "")
    if kit.session_system_extra is None:
        return None
    try:
        from dodaios.agent_chat.runner_brain import brain_manager

        brain = brain_manager()
        cfg = getattr(brain, "_config", None)
        text = await kit.session_system_extra(cfg, brain, session)
    except Exception:  # noqa: BLE001 — the CLI then runs with Jarvis' layers, never fails
        log.warning("agent chat: surface identity unavailable this turn", exc_info=True)
        return None
    return text or None


def _held_conversation(session: Any) -> str | None:
    """The vendor conversation to resume: a provider switch stores ``""``, which is none."""
    return session.vendor_session or None


async def run_cli_turn(
    handle: TurnHandle,
    user_text: str,
    runner: str,
    *,
    identity: bool = False,
    bridge: Any | None = None,
    always_allowed: set[str] | None = None,
) -> str | None:
    """Run one CLI turn. Returns the vendor session id to persist (or None).

    A resume the CLI no longer knows is retried once as a fresh conversation
    (the person keeps typing; only the CLI-side memory is gone, the timeline
    here is intact).

    ``identity`` (the Jarvis surface): the CLI runs AS Jarvis — Jarvis' real
    prompt layers and the chat's transcript go in front of it, and the
    approval ``bridge`` is armed with the chat's stance so a Jarvis tool the
    CLI reaches over MCP asks the person on the chat's card (and a tool the
    CLI already asked about on its own channel is not asked about twice).
    """
    t0 = time.perf_counter()
    session = handle.session
    resume = _held_conversation(session)
    if (
        resume
        and identity
        and session.surface == "society"
        and dodaios_harness.society_rollover_due(handle.history)
    ):
        # One endless chat, bounded CLI conversations: start fresh from the
        # briefing, memory and recent transcript, and mark where it began.
        resume = None
        await handle.emit(
            make_event(
                "notice",
                {
                    "kind": dodaios_harness.ROLLOVER_NOTICE_KIND,
                    "text": "Started a fresh working context from memory and recent messages.",
                },
            )
        )
    from dodaios.agent_chat.task_recovery import ToolRecovery, blocks_automatic_recovery

    recovery = ToolRecovery()
    original_emit = handle.emit
    original_ask = handle.request_approval
    # A lead turn is kept with what the CLI was handed and its first move,
    # for the replay benchmark (``dodaios.rsi.lead_turns``).
    lead_record = _rc._lead_record(handle, user_text) if identity else None

    async def observe(event: dict[str, Any]) -> None:
        recovery.observe(event)
        if lead_record is not None:
            lead_record.observe(event)
        await original_emit(event)

    async def ask(call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
        answer = await original_ask(call_id, name, args, summary)
        if answer in {"deny", "cancel"}:
            recovery.declined = True
        return answer

    if session.surface == "society" and not handle.continuation:
        from dodaios.society.reply_preference import resolve_agent_reply_language

        handle.output_language = await resolve_agent_reply_language(
            session.session_id, user_text, getattr(handle, "output_language", "")
        )
    handle = _rc.replace(handle, emit=observe, request_approval=ask)
    if identity and session.surface == "jarvis":
        # The assistant's own chat: the reply's shape and where a question goes
        # are said beside the message, not only in the system prompt. One
        # function builds it, so a replay can rebuild it (``lead_model_input``).
        user_text = dodaios_harness.lead_message(
            user_text,
            continuation=handle.continuation,
            output_language=getattr(handle, "output_language", ""),
        )
    elif getattr(handle, "output_language", "") and not user_text.startswith("/goal"):
        user_text += reply_language_line(session.surface, handle.output_language)
    ident: dodaios_harness.Identity | None = None
    ref = approval_ref(session.session_id)
    # A society agent's seat: its own briefing is the identity (not Jarvis'
    # layers), and its pinned subscription account is the seat's login.
    prompt_override = await _rc._surface_identity(session) if identity else None
    if prompt_override and getattr(handle, "output_language", ""):
        # Only a seat with a briefing of its own takes the line there. The lead
        # has none: an override made of this line alone would stand in for its
        # whole identity (no prompt layers, no catch-up). Its message carries
        # the line already.
        prompt_override += reply_language_line(session.surface, handle.output_language)
    account_token = ACCOUNT_OVERRIDE.set(getattr(session, "account_id", "") or "")
    turn_seats: dict[str, str] = {}
    seats_token = _TURN_SEATS.set(turn_seats)
    _ensure_seat_watch()
    if identity:
        ident = await dodaios_harness.build_identity(
            session_id=session.session_id,
            turn_id=handle.turn_id,
            user_text=user_text,
            history=handle.history,
            resume=resume,
            with_file=(runner in _CLAUDE_CODE_RUNNERS),
            prompt_override=prompt_override,
        )
        if bridge is not None:
            from dodaios.agent_chat.approval_bridge import ChatGrant
            from dodaios.society.surface import requires_explicit_approval

            bridge.arm(
                ref,
                ChatGrant(
                    session_id=session.session_id,
                    turn_id=handle.turn_id,
                    stance=handle.stance or bridge_stance(runner, session),
                    always_allowed=always_allowed if always_allowed is not None else set(),
                    ask=handle.request_approval,
                    force_ask=(
                        lambda name, args: requires_explicit_approval(
                            session.session_id, name, args
                        )
                    )
                    if session.surface == "society"
                    else lambda _name, _args: False,
                ),
            )
    from dodaios.agent_chat.surface_kits import kit_for
    from dodaios.agent_chat.turn_prompts import ASK_PROTOCOL

    if (
        runner not in _CLAUDE_CODE_RUNNERS
        and kit_for(session.surface).turn_prompts
        and not user_text.lstrip().startswith("/")
    ):
        # No mid-turn channel to ask on: the agent asks at the end of its turn
        # and the chat shows the block as a question card (turn_prompts). The
        # thread also draws pictures, which a terminal CLI cannot know.
        from dodaios.agent_chat.thread_visuals import VISUALS_GUIDE

        user_text = ASK_PROTOCOL + VISUALS_GUIDE + "\n\n" + user_text
    if runner not in _CLAUDE_CODE_RUNNERS:
        from dodaios.briefs import standing

        # A thread an agent opened takes work orders. A CLI without a system
        # prompt reads the rules for them once, at the start of its conversation.
        user_text = standing.for_first_message(user_text, handle, new_conversation=resume is None)
    tool_context = register_turn(session.session_id) if identity else None
    record_token = _rc._LEAD_RECORD.set(lead_record)
    try:
        outcome = await _rc._run_cli_once(
            handle, user_text, runner, resume, identity=ident, bridge=bridge
        )
        # agy answers a lost conversation id with a NEW conversation and exit 0
        # (only a stderr warning) — the id that came back is the truth.
        if (
            outcome.status == "error"
            and resume
            and not recovery.had_tool_calls
            and _resume_was_lost(outcome.error, runner)
            and not handle.cancel.is_set()
        ):
            log.info(
                "agent chat %s: resume lost (%s) — starting fresh", handle.turn_id, outcome.error
            )
            if ident is not None:
                # Fresh conversation: the transcript belongs in front now.
                dodaios_harness.remove_identity_file(ident.path)
                ident = await dodaios_harness.build_identity(
                    session_id=session.session_id,
                    turn_id=handle.turn_id,
                    user_text=user_text,
                    history=handle.history,
                    resume=None,
                    with_file=(runner in _CLAUDE_CODE_RUNNERS),
                    prompt_override=prompt_override,
                )
            if runner not in _CLAUDE_CODE_RUNNERS:
                from dodaios.briefs import standing

                # The fresh conversation remembers nothing, its work-order rules included.
                user_text = standing.for_first_message(user_text, handle, new_conversation=True)
            outcome = await _rc._run_cli_once(
                handle, user_text, runner, None, identity=ident, bridge=bridge
            )
            resume = None
        if outcome.status == "error" and not recovery.had_tool_calls:
            outcome = await _send_again_when_runtime_ready(
                handle,
                outcome,
                runner,
                lambda: _rc._run_cli_once(
                    handle, user_text, runner, resume, identity=ident, bridge=bridge
                ),
                recovery,
            )
        receipt_hint = recovery.hint() if identity else None
        if (
            (
                (outcome.status == "error" and _tool_abort_is_recoverable(outcome.error))
                or (outcome.status in {"done", "error"} and receipt_hint is not None)
            )
            and not recovery.declined
            and not recovery.blocked
            and not blocks_automatic_recovery(outcome.error)
            and not handle.tools_disabled
            and not handle.cancel.is_set()
        ):
            # Print-mode Grok/agy abort the process after a cancelled tool
            # instead of thinking again. Resume the same vendor session once
            # with the error in front so the model can work around it.
            log.info(
                "agent chat %s: recovering from cancelled/failed tool (%s)",
                handle.turn_id,
                (outcome.error or "")[:180],
            )
            recovered = await _rc._run_cli_once(
                handle,
                _keep_going_prompt(user_text, outcome.error, receipt_hint=receipt_hint),
                runner,
                outcome.vendor_session or resume,
                identity=ident,
                bridge=bridge,
            )
            outcome = _merge_cli_outcome(outcome, recovered)
        if outcome.status == "error" and not handle.cancel.is_set():
            outcome = await _continue_on_next_seat(
                handle,
                outcome,
                runner,
                turn_seats,
                started_work=recovery.had_tool_calls,
                run_again=lambda prompt, conversation: _rc._run_cli_once(
                    handle, prompt, runner, conversation, identity=ident, bridge=bridge
                ),
                user_text=user_text,
                resume=resume,
            )
        if outcome.status == "error" and not handle.cancel.is_set():
            outcome, handle = await _continue_on_fallback_model(
                handle,
                outcome,
                runner,
                turn_seats,
                started_work=lambda: recovery.had_tool_calls,
                run_again=lambda moved, prompt, conversation: _rc._run_cli_once(
                    moved, prompt, runner, conversation, identity=ident, bridge=bridge
                ),
                user_text=user_text,
                resume=resume,
            )
    finally:
        _rc._LEAD_RECORD.reset(record_token)
        _TURN_SEATS.reset(seats_token)
        unregister_turn(session.session_id, tool_context)
        ACCOUNT_OVERRIDE.reset(account_token)
        if bridge is not None and identity:
            bridge.disarm(ref)
        if ident is not None:
            dodaios_harness.remove_identity_file(ident.path)
    await handle.emit(
        make_event(
            "turn_finished",
            {
                "turn_id": handle.turn_id,
                "status": outcome.status,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
                "usage": outcome.usage,
                "error": outcome.error,
                "cost_usd": outcome.cost_usd,
            },
        )
    )
    if lead_record is not None:
        # A turn that answered in text only is known now; a tool call was written at once.
        lead_record.finish()
    return outcome.vendor_session


def _lead_record(handle: TurnHandle, user_text: str) -> Any:
    """The recorder of a lead turn (the ``jarvis`` surface, no slash command), else ``None``."""
    session = handle.session
    if getattr(session, "surface", "") != "jarvis" or user_text.lstrip().startswith("/"):
        return None
    try:
        from dodaios.rsi.lead_turns import TurnRecorder

        return TurnRecorder(
            session.session_id,
            handle.turn_id,
            continuation=bool(handle.continuation),
            images=len(tuple(getattr(handle, "images", ()) or ())),
        )
    except Exception:  # noqa: BLE001 - without a recorder the turn runs exactly as before
        log.debug("agent chat %s: lead turn not recorded", handle.turn_id, exc_info=True)
        return None


async def resume_hosted_cli_turn(handle: TurnHandle, proc: Any) -> str | None:
    """Carry on a thread turn whose CLI kept running in the turn host.

    The app restarted while the turn ran; the CLI did not. ``proc`` is the
    reattached :class:`~dodaios.agent_chat.turn_host_client.HostedCli` (or a
    spooled one that ended meanwhile). Its ``meta`` holds what the plan said
    at spawn; the lines the old app already handled rebuild the translator,
    every later one is emitted, and the turn ends with its real outcome.
    Returns the vendor session id to persist, like :func:`run_cli_turn`.
    """
    meta = dict(getattr(proc, "meta", {}) or {})
    runner = str(meta.get("runner") or "")
    shape = str(meta.get("shape") or "text")
    started_at = float(meta.get("started_at") or time.time())
    codex_home = str(meta.get("codex_home") or "")
    plan = CliPlan(
        argv=[],
        env={"CODEX_HOME": codex_home} if codex_home else {},
        stdin_text=None,
        shape=shape if shape in _SHAPES else "text",
        vendor_session=str(meta.get("vendor_session") or "") or None,
        keep_stdin=bool(meta.get("keep_stdin")),
        # Only its presence matters from here on: control requests are answered.
        control_init="" if meta.get("control") else None,
        discover=_kimi_session_after if meta.get("discover") else None,
    )
    elapsed = max(0.0, time.time() - started_at)
    log.info(
        "agent chat %s: carrying on a %s turn the turn host kept running (%.0f s old)",
        handle.turn_id,
        runner,
        elapsed,
    )
    outcome = await _rc._drive_cli(
        handle,
        proc,
        plan,
        runner,
        cwd=Path(str(meta.get("cwd") or handle.session.cwd or Path.home())),
        started_at=started_at,
        placement=None,
        tree=None,
        bridge=None,
        timeout_s=_TURN_TIMEOUT_S,
    )
    await handle.emit(
        make_event(
            "turn_finished",
            {
                "turn_id": handle.turn_id,
                "status": outcome.status,
                "duration_ms": int((time.time() - started_at) * 1000),
                "usage": outcome.usage,
                "error": outcome.error,
                "cost_usd": outcome.cost_usd,
            },
        )
    )
    return outcome.vendor_session
