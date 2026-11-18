"""The event vocabulary of an agent-chat session.

One shape for the persisted log and the live WebSocket stream: every event is
a plain dict ``{"seq", "ts_ms", "kind", "payload"}``. The UI rebuilds a
session's timeline by folding the persisted events, then keeps folding live
ones — the same reducer for both, so a reopened session looks exactly like
it did while it ran (``src/components/agentchat/reduce.ts``).

Kinds (``payload`` keys in brackets):

``agent_message``      [IncomingMessage fields] — trusted internal sender, initially queued
``agent_message_status`` [message_id, status, turn_id, error] — durable delivery receipt
``user_message``       [text]                          — the person's turn
``turn_started``       [turn_id, provider, model, effort, runner]
``text_delta``         [turn_id, message_id, text]     — live only, never stored
``assistant_text``     [turn_id, message_id, text]     — the finished block
``reasoning_started``  [turn_id, message_id]           — live only: the model began
                        to think (its thinking may be redacted, so this is the
                        only sign of it until the finished block arrives)
``reasoning_delta``    [turn_id, text]                 — live only
``reasoning``          [turn_id, text, duration_ms]    — the finished block; text
                        may be "" when the vendor redacts thinking — the
                        duration still says how long it thought
``usage_delta``        [turn_id, usage, context?]      — live only: tokens so far
                        (cumulative {input_tokens, output_tokens, …}); ``context`` is
                        the main agent's newest message as a ``context_usage`` reading
``context_usage``      [turn_id, used, window, model]  — once per answer: the tokens in
                        the context window (``context_window.py``), ``window`` null
                        when the CLI named no size
``tool_call``          [turn_id, call_id, name, input]
``tool_result``        [turn_id, call_id, output, is_error, duration_ms]
``tool_summary``       [turn_id, summary, call_ids]    — the CLI's short title for
                                                         the tool calls it just made
``approval_required``  [turn_id, approval_id, call_id, name, input, summary]
``approval_resolved``  [turn_id, approval_id, decision]   decision: allow |
                        allow_always | deny | cancel | expired (nothing waits
                        on the card any more: a restart, or the call asked again)
                        ``edited`` (when the person changed the action's text before
                        allowing it): ``{field: {before, after}}``; ``deferred`` when the
                        card had been set aside while the person wrote on
``approval_deferred``  [turn_id, approval_id]   the chat moved on to a new message: the
                        card stays open, the call was refused with that reason, and an
                        Allow later runs the call (approval_defer.py)
``question_required``  [turn_id, question_id, asker, questions, deferred?] — a question
                        card; ``deferred`` = an end-of-turn card (turn_prompts)
                        whose answers go to the agent as the next message
``question_progress``  [turn_id, question_id, answers]
``question_resolved``  [turn_id, question_id, answers]
``credential_required`` [turn_id, request_id, asker, env, label, description, placeholder,
                        replace, expires_ms] — a secure field for a secret the agent
                        needs (credential_requests.py); the value never appears in any event
``credential_resolved`` [turn_id, request_id, env, status]   status: saved | declined |
                        timeout | cancelled | superseded (a later turn shows it again)
``plan_ready``         [turn_id, build_mode]           — a coding agent's plan card
``plan_resolved``      [turn_id, decision]             decision: build | keep
``subagent_started``   [turn_id, agent_id, description, agent_type, prompt, background,
                        task_id?, thread_id?] — a coding agent spawned a sub-agent;
                        ``agent_id`` is the spawning tool call's id
``subagent_progress``  [turn_id, agent_id, activity, last_tool, tokens?, tool_uses?,
                        duration_ms?, model?] — live only: what the sub-agent is doing
                        now; ``model`` is the model its own messages report
``subagent_finished``  [turn_id, agent_id, status, summary?, tokens?, tool_uses?,
                        duration_ms?]   status: done | failed | stopped
``background_wait``    [turn_id, tasks] — the agent ended its message but the CLI
                        still runs background tasks (shells, agents) and will wake
                        it when they finish; ``tasks`` names them, [] = no longer
                        waiting. A turn held open for its delegates says the same
                        (delegation_wait.py): ``tasks`` names the agents it waits for
``setup_step``         [turn_id, step, where?, host?, cli?] — a thread placed on another
                        computer: which setup step began (connect | fetch | send | unpack |
                        start), shown until the agent's first output
``compaction``         [turn_id, call_id, phase, trigger?, tokens_before?, tokens_after?,
                        duration_ms?, error?] — the coding agent compacts its own
                        conversation: ``phase`` is started | done | failed, ``trigger``
                        auto | manual; one ``call_id`` per compaction
``turn_finished``      [turn_id, status, duration_ms, usage, error, cost_usd]
                        status: done | cancelled | error
``session_updated``    [title?, provider?, model?, effort?, cwd?, permission_mode?,
                        build_mode?]
``error``              [turn_id?, message]
``notice``              [kind, ...]                      — a system line outside a turn

A sub-agent's own text, thoughts and calls are the ordinary kinds with an
``agent_id`` in the payload: they belong to that sub-agent's conversation,
never to the main agent's answer.

A coding agent's own to-do list is a ``tool_call`` like any other: the thread
reads the list from the call's input and draws it as a checklist
(``src/components/agentchat/agentPlan.ts``). A runtime that reports its list
as a notification instead of a call is told as one (:func:`plan_update_events`).

``text_delta`` / ``reasoning_delta`` / ``reasoning_started`` / ``usage_delta`` /
``subagent_progress`` are the transient kinds: the finished block carries the whole text and the
``turn_finished`` event the whole usage, so the log never stores token dust.
"""

from __future__ import annotations

import time
from typing import Any, Final

TRANSIENT_KINDS: Final[frozenset[str]] = frozenset(
    {"text_delta", "reasoning_delta", "reasoning_started", "usage_delta", "subagent_progress"}
)


def now_ms() -> int:
    return int(time.time() * 1000)


def make_event(kind: str, payload: dict[str, Any] | None = None, *, seq: int = 0) -> dict[str, Any]:
    """Build one event dict. ``seq`` is assigned by the store on persist."""
    return {"seq": seq, "ts_ms": now_ms(), "kind": kind, "payload": dict(payload or {})}


#: The tool a runtime's own to-do list is filed under when the runtime reports
#: it as a notification, not as a tool call (Codex's name for that tool).
PLAN_TOOL: Final[str] = "update_plan"

_PLAN_STATUS: Final[dict[str, str]] = {
    "completed": "completed",
    "complete": "completed",
    "done": "completed",
    "in_progress": "in_progress",
    "inprogress": "in_progress",
    "active": "in_progress",
}


def plan_steps(raw: Any) -> list[dict[str, str]]:
    """A runtime's to-do list as ``[{"step", "status"}]``, the shape of ``update_plan``.

    Takes the entries as the runtimes send them: Codex's ``todo_list`` item
    (``{"text", "completed"}``) and ACP's ``plan`` update (``{"content",
    "status"}``). ``status`` is ``pending``, ``in_progress`` or ``completed``;
    an entry is in progress only when the runtime said so.
    """
    steps: list[dict[str, str]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        text = ""
        for key in ("text", "content", "step", "title"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                text = " ".join(value.split())
                break
        if not text:
            continue
        status = _PLAN_STATUS.get(str(entry.get("status") or "").strip().lower(), "pending")
        if entry.get("completed") is True:
            status = "completed"
        steps.append({"step": text, "status": status})
    return steps


def plan_update_events(
    turn_id: str, call_id: str, steps: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """An agent's to-do list as it stands now, told as one finished tool call.

    ``call_id`` must be unique in the conversation, not only in the turn: the
    thread keys the list by it.
    """
    return [
        make_event(
            "tool_call",
            {
                "turn_id": turn_id,
                "call_id": call_id,
                "name": PLAN_TOOL,
                "input": {"plan": steps},
                "summary": "",
            },
        ),
        make_event(
            "tool_result",
            {
                "turn_id": turn_id,
                "call_id": call_id,
                "output": "done",
                "is_error": False,
                "duration_ms": 0,
            },
        ),
    ]


def shown_text(payload: dict[str, Any]) -> str:
    """What the person sent, as a chat shows it: never the composed prompt.

    ``text`` is the prompt the turn received; with files it also carries the
    note and the ``<attachment>`` blocks written for the model. ``typed`` is
    the person's own sentence. A message of files alone has an empty sentence,
    and its files' names stand for it. A message without ``typed`` (no files,
    no separate display text) is its ``text``.
    """
    typed = payload.get("typed")
    if not isinstance(typed, str):
        return str(payload.get("text") or "")
    if typed.strip():
        return typed
    rows = payload.get("attachments")
    names = ", ".join(
        str(row["name"])
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and row.get("name")
    )
    return names or str(payload.get("text") or "")


def person_words(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The person's own sentences in a thread, oldest first, as ``user`` messages.

    This is what the person's language is read from. A ``user_message`` is not
    always their words: ``text`` is the prompt the turn received, so with files
    it also carries the English note and the files' contents (``typed`` is the
    sentence), and a message with an ``origin`` (a control command, a
    delegate's result handed back) or an ``author`` (another agent wrote it)
    was composed by the app. Read as their words, those turned a German
    conversation English after every screenshot and every agent result
    (forensic 2026-11-13).
    """
    out: list[dict[str, str]] = []
    for event in events:
        if event.get("kind") != "user_message":
            continue
        payload = event.get("payload") or {}
        if payload.get("origin") or payload.get("author"):
            continue
        typed = payload.get("typed")
        text = typed if isinstance(typed, str) else str(payload.get("text") or "")
        if text.strip():
            out.append({"role": "user", "content": text})
    return out


def is_transient(event: dict[str, Any]) -> bool:
    return event.get("kind") in TRANSIENT_KINDS


#: Notice kinds that only record background work (see :func:`is_background_notice`).
#: A routine's start card and a memory write receipt are log lines, not
#: messages: the run is in the routine's history, the note on the Memory page
#: (maintainer, 2026-11-18: proactive messages read as messages, not logs).
BACKGROUND_NOTICE_KINDS: Final[frozenset[str]] = frozenset(
    {"memory_learned", "watchdog", "routine_run", "memory_updated"}
)


def is_background_notice(payload: dict[str, Any]) -> bool:
    """Whether a ``notice`` records work that went on in the background.

    The conversation's log keeps such a notice, but no chat view draws it and
    no phone is told about it. Each has a place of its own: what the assistant
    learned or noted is on the Memory page, a watchdog finding is in the status
    light, a routine's start is in its run history, and an unattended routine
    run that failed, was skipped or waits is in the routine's run history. A
    routine's finished result is an answer the person asked for and stays in
    the chat. The page applies the same rule
    (``src/components/agentchat/backgroundNotices.ts``).
    """
    kind = str(payload.get("kind") or "")
    if kind in BACKGROUND_NOTICE_KINDS:
        return True
    return (
        kind == "society_result"
        and payload.get("source") == "routine"
        and str(payload.get("status") or "") not in ("", "done")
    )
