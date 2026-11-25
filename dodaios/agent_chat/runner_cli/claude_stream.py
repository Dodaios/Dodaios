"""Claude-shaped NDJSON stream: usage, sub-agent tracking, compaction, and the line translator."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Final

from dodaios.agent_chat.context_window import reading as context_reading
from dodaios.agent_chat.context_window import tokens_in_context, window_from_result
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.model_fallback import (
    LimitSignal,
    limit_from_claude_line,
)
from dodaios.agent_chat.runner_cli.base import _cli_tool_summary
from dodaios.agent_chat.turn_host import claude_result_without_model_turn

# ------------------------------------------------------------ translation

#: The token fields a Claude CLI message reports. The two cache fields carry
#: the bulk of a real turn — a warm session reads tens of thousands of cached
#: tokens while ``input_tokens`` counts only the handful that were new — so a
#: counter that skips them under-reports by orders of magnitude (BUG-173).
_CLAUDE_USAGE_KEYS: Final[tuple[str, ...]] = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


@dataclass(slots=True)
class _ClaudeState:
    turn_id: str
    vendor_session: str | None = None
    current_message_id: str | None = None
    text_acc: dict[str, str] = field(default_factory=dict)
    thinking_acc: dict[str, str] = field(default_factory=dict)
    thinking_started: dict[str, float] = field(default_factory=dict)
    #: Message ids whose thinking block was announced live (one card each).
    thinking_announced: set[str] = field(default_factory=set)
    #: Per-message usage as the CLI reports it — summed into the live counter.
    usage_by_message: dict[str, dict[str, int]] = field(default_factory=dict)
    #: Characters streamed per message so far; a live floor for its output.
    stream_chars: dict[str, int] = field(default_factory=dict)
    #: The usage totals last sent, so an unchanged count sends nothing.
    usage_sent: dict[str, int] = field(default_factory=dict)
    #: The main agent's newest message: the tokens in its context window
    #: (``context_window.tokens_in_context``) and the model it named.
    context_used: int = 0
    context_model: str = ""
    emitted_tool_ids: set[str] = field(default_factory=set)
    emitted_text: bool = False
    status: str = "done"
    error: str | None = None
    #: What the stream said about a usage / rate limit (``model_fallback``).
    limit: LimitSignal = field(default_factory=LimitSignal)
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float | None = None
    result_text: str = ""
    #: The turn's ``result`` line arrived — stdin may close, the CLI exits.
    saw_result: bool = False
    #: The latest ``result`` is the turn's last word: no task ended and no
    #: message started since. A task that ends after a result wakes the
    #: agent again (Claude Code), so the turn is not over until it answers.
    answered: bool = False
    #: Last tool_result that came back as an error — used when the CLI then
    #: aborts the turn instead of thinking again (Grok print-mode cancel).
    last_tool_error: str | None = None
    #: The turn's ``CLAUDE_CONFIG_DIR`` ("" = the built-in seat) when this is a
    #: Claude Code turn: its ``rate_limit_event`` lines feed the plan meter
    #: (:func:`dodaios.agent_usage.note_claude_rate_limit`). None elsewhere.
    usage_home: str | None = None
    #: A sub-agent's own translator state, by the call that spawned it — its
    #: messages carry ``parent_tool_use_id`` and must never read as the main
    #: agent's words.
    agents: dict[str, _ClaudeState] = field(default_factory=dict)
    #: The CLI's task id -> the spawning call, for task updates that name only the task.
    agent_tasks: dict[str, str] = field(default_factory=dict)
    #: Tasks the CLI still runs (task id -> what it does): background shells
    #: and agents. They keep the CLI alive after the agent's message ended.
    open_tasks: dict[str, str] = field(default_factory=dict)
    #: The main agent ended its message; only open tasks can wake it again.
    idle: bool = False
    #: The task list the last ``background_wait`` event named.
    wait_sent: tuple[str, ...] = ()
    #: Grok Build: its stream has no task lines, so open background work is
    #: read from tool results instead (``_grok_track_tasks``).
    grok: bool = False
    #: Grok Build: what each tool call said it does (its ``description``), so
    #: a background shell's wait can name it.
    call_notes: dict[str, str] = field(default_factory=dict)
    #: Grok Build: the calls whose tool can start background work; only
    #: their results are read for a task id.
    background_calls: set[str] = field(default_factory=set)
    #: The model a sub-agent's messages last reported (sub-agent states only).
    reported_model: str = ""
    #: Task notices that arrived before the turn's first ``result``. On resume
    #: Claude Code delivers the notice of each task the previous process left
    #: unfinished as an input of its own and answers each with an empty
    #: ``result`` (no model turn) before the person's prompt runs. Those lines
    #: must not end the turn (``claude_result_without_model_turn``); two open
    #: tasks give two of them, so they are counted, not flagged.
    notices_pending: int = 0
    #: The conversation's compaction under way (``context_compaction`` call id),
    #: "" when none is; and how many compactions this turn has told.
    compaction_id: str = ""
    compactions: int = 0
    compaction_started: float = 0.0


#: Streamed characters per estimated output token (English and code average).
_CHARS_PER_TOKEN: Final = 4

#: A streamed estimate is sent once it has grown by this many output tokens,
#: so a long answer does not send one counter update per text fragment.
_LIVE_OUTPUT_STEP: Final = 20


def _claude_merge_usage(st: _ClaudeState, mid: str, usage: dict[str, Any]) -> bool:
    """Fold one usage report of message ``mid`` in; True when it changed.

    A message's first report is the ``message_start`` snapshot: the input side
    is final, ``output_tokens`` a placeholder that only becomes true at the
    message's end (``message_delta``). Keep the largest value seen so a
    placeholder can never walk a real count back down (BUG-173).
    """
    counted = {
        k: int(usage[k]) for k in _CLAUDE_USAGE_KEYS if isinstance(usage.get(k), int | float)
    }
    previous = st.usage_by_message.get(mid)
    if previous:
        counted = {k: max(counted.get(k, 0), previous.get(k, 0)) for k in (*counted, *previous)}
    if not counted or counted == previous:
        return False
    st.usage_by_message[mid] = counted
    # The newest message's context is the conversation as the next one sees
    # it; a sub-agent's messages never reach here (their own state counts them).
    st.context_used = tokens_in_context(counted) or st.context_used
    return True


def _claude_usage_totals(st: _ClaudeState) -> dict[str, int]:
    """The turn so far: reported usage, with streamed text as a floor for output."""
    totals: dict[str, int] = {}
    streamed_only = (m for m in st.stream_chars if m not in st.usage_by_message)
    for mid in (*st.usage_by_message, *streamed_only):
        per_message = dict(st.usage_by_message.get(mid, {}))
        estimate = st.stream_chars.get(mid, 0) // _CHARS_PER_TOKEN
        if estimate > per_message.get("output_tokens", 0):
            per_message["output_tokens"] = estimate
        for k, v in per_message.items():
            totals[k] = totals.get(k, 0) + v
    return totals


def _claude_usage_event(st: _ClaudeState, *, min_output_step: int = 0) -> dict[str, Any] | None:
    """A ``usage_delta`` when the totals moved (by ``min_output_step`` output tokens)."""
    totals = _claude_usage_totals(st)
    if not totals or totals == st.usage_sent:
        return None
    grown = totals.get("output_tokens", 0) - st.usage_sent.get("output_tokens", 0)
    only_output_moved = {k: v for k, v in totals.items() if k != "output_tokens"} == {
        k: v for k, v in st.usage_sent.items() if k != "output_tokens"
    }
    if min_output_step and only_output_moved and grown < min_output_step:
        return None
    st.usage_sent = totals
    payload: dict[str, Any] = {"turn_id": st.turn_id, "usage": totals}
    if st.context_used:
        payload["context"] = context_reading(st.context_used, st.context_model)
    return make_event("usage_delta", payload)


def _claude_request_summary(tool_name: str, tool_input: dict[str, Any]) -> str:
    for key in ("command", "file_path", "path", "pattern", "url", "query", "description"):
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().splitlines()[0][:200]
    return tool_name


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(
            isinstance(block, dict)
            and block.get("type")
            in {"image", "image_url", "input_image", "video", "audio", "resource", "resource_link"}
            for block in content
        ):
            # Preserve structured media for the common chat delivery layer.
            return json.dumps(content, ensure_ascii=False)
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif block.get("type") == "content":
                    nested = _content_text(block.get("content"))
                    if nested:
                        parts.append(nested)
                elif "text" in block:
                    parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        joined = "\n".join(p for p in parts if p)
        # Grok wraps a cancelled tool as ``[{type: content, content: {type: text}}]``
        # — keep the payload readable so recovery can see "User cancelled".
        return joined if joined else json.dumps(content, ensure_ascii=False)
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text") or "")
        if content.get("type") == "content":
            return _content_text(content.get("content"))
        if "text" in content and not any(
            key in content for key in ("type", "image", "image_url", "input_image")
        ):
            return str(content.get("text") or "")
        inner = content.get("content")
        if inner is not None and inner is not content:
            nested = _content_text(inner)
            if nested:
                return nested
        return json.dumps(content, ensure_ascii=False)
    return "" if content is None else str(content)


#: Claude Code's background-task lines; the agent ones become a sub-agent's card.
_CLAUDE_TASK_SUBTYPES: Final = frozenset(
    {"task_started", "task_progress", "task_updated", "task_notification"}
)

#: The ``task_updated`` statuses that mean a task is over. Anything else
#: (running, pending, a status this code does not know yet) keeps it open:
#: closing a live task early would end its turn under it.
_TASK_ENDED_STATUSES: Final = frozenset(
    {
        "completed",
        "complete",
        "done",
        "succeeded",
        "success",
        "failed",
        "failure",
        "error",
        "errored",
        "killed",
        "stopped",
        "cancelled",
        "canceled",
        "aborted",
        "interrupted",
        "timed_out",
        "timeout",
        "expired",
        "exited",
    }
)


def subagent_status(raw: str) -> str:
    """A vendor's word for how a sub-agent ended, as ``done`` | ``failed`` | ``stopped``."""
    word = raw.strip().lower()
    if word in {"completed", "complete", "done", "success", "succeeded"}:
        return "done"
    if word in {"failed", "error", "errored"}:
        return "failed"
    return "stopped"


def _task_usage(obj: dict[str, Any]) -> dict[str, int]:
    usage = obj.get("usage")
    if not isinstance(usage, dict):
        return {}
    keys = {"total_tokens": "tokens", "tool_uses": "tool_uses", "duration_ms": "duration_ms"}
    return {
        ours: int(usage[theirs])
        for theirs, ours in keys.items()
        if isinstance(usage.get(theirs), int | float)
    }


def _claude_subagent_line(
    obj: dict[str, Any], st: _ClaudeState, parent: str
) -> list[dict[str, Any]]:
    """A sub-agent's own message, filed under the call that spawned it.

    The CLI streams a sub-agent's turns on the parent's stdout, marked only by
    ``parent_tool_use_id``. Each sub-agent gets a translator state of its own,
    so its text, thoughts and calls never merge into the main agent's answer,
    and every event it yields names the agent (``agent_id``). Its partial
    stream and token counts stay out: the finished messages carry the words,
    and the live counter is the main agent's.
    """
    if str(obj.get("type") or "") not in {"assistant", "user"}:
        return []
    child = st.agents.get(parent)
    if child is None:
        child = st.agents[parent] = _ClaudeState(turn_id=st.turn_id)
    out: list[dict[str, Any]] = []
    # Every assistant message names the model that wrote it: the sub-agent's own,
    # which may differ from the main agent's (a Haiku explorer under an Opus thread).
    message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    model = str(message.get("model") or "") if obj.get("type") == "assistant" else ""
    if model and not model.startswith("<") and model != child.reported_model:
        child.reported_model = model
        out.append(
            make_event(
                "subagent_progress",
                {"turn_id": st.turn_id, "agent_id": parent, "model": model},
            )
        )
    for event in translate_claude_line({**obj, "parent_tool_use_id": None}, child):
        if event["kind"] == "usage_delta":
            continue
        event["payload"]["agent_id"] = parent
        out.append(event)
    return out


def _claude_track_task(obj: dict[str, Any], st: _ClaudeState) -> None:
    """Keep the set of tasks the CLI still runs, shells and agents alike."""
    subtype = str(obj.get("subtype") or "")
    task_id = str(obj.get("task_id") or "")
    if not task_id or subtype not in _CLAUDE_TASK_SUBTYPES:
        return
    if subtype == "task_started":
        what = str(obj.get("description") or "").strip().splitlines()
        st.open_tasks[task_id] = what[0][:120] if what else str(obj.get("task_type") or "task")
        return
    if subtype == "task_updated":
        patch = obj.get("patch") if isinstance(obj.get("patch"), dict) else {}
        if str(patch.get("status") or "").lower() not in _TASK_ENDED_STATUSES:
            return
    if subtype in {"task_updated", "task_notification"}:
        if st.open_tasks.pop(task_id, None) is not None and st.saw_result:
            # Claude Code wakes the agent with the task's outcome: the
            # result already sent is no longer the turn's last word.
            st.answered = False


#: Grok Build's own words for background work it started, as they read in a
#: tool result (grok 1.0.77): a background shell (``run_terminal_command``
#: with ``background: true``), a background sub-agent (``spawn_subagent``)
#: and a ``monitor``.
_GROK_TASK_STARTED: Final = (
    re.compile(r"<task-id>\s*([\w-]+)\s*</task-id>"),
    re.compile(r"Subagent started in background\.\s*subagent_id:\s*([\w-]+)"),
    re.compile(r"Monitor started \(task ([\w-]+)"),
)

#: A task's end as Grok reports it: the reminder it appends to a later tool
#: result, and the status block of ``get_command_or_subagent_output``.
_GROK_TASK_ENDED: Final = (
    re.compile(
        r"Background task \"([\w-]+)\" (?:completed|failed|was killed|killed|"
        r"cancelled|canceled|stopped|timed out|exited)"
    ),
)

_GROK_TASK_STATUS: Final = re.compile(r"=== Task ([\w-]+) ===.*?Status:\s*([\w-]+)", re.DOTALL)

_GROK_TASK_LIVE: Final = frozenset({"running", "pending", "in_progress", "queued", "started"})

#: Grok tools that may start background work (grok 1.0.77; ``task`` and
#: ``run_terminal_cmd`` are the older spellings). A file read that happens to
#: contain ``<task-id>`` never opens a task.
_GROK_BACKGROUND_TOOLS: Final = frozenset(
    {"run_terminal_command", "run_terminal_cmd", "spawn_subagent", "task", "monitor"}
)

#: Said while a Grok turn waits on work its tool results never named.
GROK_BACKGROUND_WORK: Final = "background work"


def _grok_track_tasks(text: str, st: _ClaudeState, call_id: str = "") -> None:
    """Keep Grok Build's open background tasks from what its tool results say.

    Grok's ``streaming-messages-json`` has no task lines (Claude Code's
    ``system`` ``task_*``): a background shell, sub-agent or monitor shows
    only as the tool result that started it, and its end only as words in a
    later result. These are read here. What they miss — a task whose end the
    model never reads back — is covered by Grok itself: a print-mode run
    holds its ``result`` line until every background task ended, so that
    line clears whatever is left (``translate_claude_line``), and a turn
    that went quiet before it gets a generic wait (``grok_idle_wait``).
    """
    if not text:
        return
    for pattern in _GROK_TASK_STARTED if call_id in st.background_calls else ():
        for match in pattern.finditer(text):
            task_id = match.group(1)
            what = ""
            if pattern is _GROK_TASK_STARTED[1]:
                described = re.search(r"description:\s*(.+)", text[match.end() :])
                what = described.group(1).strip() if described else ""
            what = what or st.call_notes.get(call_id, "")
            st.open_tasks[task_id] = (what.splitlines() or ["background task"])[0][:120]
    for pattern in _GROK_TASK_ENDED:
        for match in pattern.finditer(text):
            st.open_tasks.pop(match.group(1), None)
    for match in _GROK_TASK_STATUS.finditer(text):
        if match.group(2).lower() not in _GROK_TASK_LIVE:
            st.open_tasks.pop(match.group(1), None)


def grok_idle_wait(st: Any) -> list[dict[str, Any]]:
    """A Grok turn that ended its message, has no result yet and named no task.

    Grok holds its ``result`` line while background work it started still
    runs, so an idle Grok without a result is waiting on something, even
    when no tool result said what. Called by the drive loop once the stream
    has been quiet for a moment, so a normal turn end (``result`` follows at
    once) never flashes a wait.
    """
    if (
        not getattr(st, "grok", False)
        or not st.idle
        or st.saw_result
        or st.wait_sent
        or st.open_tasks
    ):
        return []
    st.wait_sent = (GROK_BACKGROUND_WORK,)
    return [make_event("background_wait", {"turn_id": st.turn_id, "tasks": [GROK_BACKGROUND_WORK]})]


def _claude_outstanding(st: Any) -> bool:
    """True while the CLI still runs background tasks or sub-agents."""
    if getattr(st, "open_tasks", None):
        return True
    children = getattr(st, "agents", None) or {}
    return any(getattr(child, "open_tasks", None) for child in children.values())


def _claude_wait_events(st: _ClaudeState) -> list[dict[str, Any]]:
    """``background_wait`` whenever what the idle agent waits for changes.

    Claude Code can end its message while background shells or agents still
    run: the CLI stays alive and wakes the agent again when they finish. The
    answer then reads finished while the turn is not, so the timeline says
    what it waits for. An empty list: it no longer waits (it works again,
    or nothing is left open).
    """
    tasks = tuple(st.open_tasks.values()) if st.idle else ()
    if tasks == st.wait_sent:
        return []
    st.wait_sent = tasks
    return [make_event("background_wait", {"turn_id": st.turn_id, "tasks": list(tasks)})]


def _claude_task_events(obj: dict[str, Any], st: _ClaudeState) -> list[dict[str, Any]]:
    """A sub-agent's life from Claude Code's task lines: started, working, finished.

    Background shell commands are tasks too; only agent tasks get a card.
    """
    subtype = str(obj.get("subtype") or "")
    if subtype not in _CLAUDE_TASK_SUBTYPES:
        return []
    task_id = str(obj.get("task_id") or "")
    if subtype == "task_started":
        call_id = str(obj.get("tool_use_id") or "")
        task_type = str(obj.get("task_type") or "")
        if not call_id or not (obj.get("subagent_type") or "agent" in task_type):
            return []
        if task_id:
            st.agent_tasks[task_id] = call_id
        return [
            make_event(
                "subagent_started",
                {
                    "turn_id": st.turn_id,
                    "agent_id": call_id,
                    "task_id": task_id,
                    "description": str(obj.get("description") or ""),
                    "agent_type": str(obj.get("subagent_type") or ""),
                    "prompt": str(obj.get("prompt") or ""),
                    "background": bool(obj.get("is_backgrounded")),
                },
            )
        ]
    call_id = st.agent_tasks.get(task_id) or ""
    if not call_id:
        named = str(obj.get("tool_use_id") or "")
        call_id = named if named in st.agents else ""
    if not call_id:
        return []
    if subtype == "task_progress":
        return [
            make_event(
                "subagent_progress",
                {
                    "turn_id": st.turn_id,
                    "agent_id": call_id,
                    "activity": str(obj.get("description") or ""),
                    "last_tool": str(obj.get("last_tool_name") or ""),
                    **_task_usage(obj),
                },
            )
        ]
    if subtype == "task_updated":
        patch = obj.get("patch") if isinstance(obj.get("patch"), dict) else {}
        status = str(patch.get("status") or "")
        if status.lower() not in _TASK_ENDED_STATUSES:
            return []
        return [
            make_event(
                "subagent_finished",
                {"turn_id": st.turn_id, "agent_id": call_id, "status": subagent_status(status)},
            )
        ]
    return [
        make_event(
            "subagent_finished",
            {
                "turn_id": st.turn_id,
                "agent_id": call_id,
                "status": subagent_status(str(obj.get("status") or "completed")),
                "summary": str(obj.get("summary") or ""),
                **_task_usage(obj),
            },
        )
    ]


def _claude_compaction_open(st: _ClaudeState, trigger: str = "") -> list[dict[str, Any]]:
    """The ``compaction`` start, once per compaction."""
    if st.compaction_id:
        return []
    st.compactions += 1
    st.compaction_id = f"compact-{st.turn_id}-{st.compactions}"
    st.compaction_started = time.perf_counter()
    payload: dict[str, Any] = {
        "turn_id": st.turn_id,
        "call_id": st.compaction_id,
        "phase": "started",
    }
    if trigger:
        payload["trigger"] = trigger
    return [make_event("compaction", payload)]


def _claude_compaction_close(
    st: _ClaudeState, meta: dict[str, Any], *, error: str = ""
) -> list[dict[str, Any]]:
    """The ``compaction`` end with what the CLI reported; nothing when none is open."""
    if not st.compaction_id:
        return []
    payload: dict[str, Any] = {
        "turn_id": st.turn_id,
        "call_id": st.compaction_id,
        "phase": "failed" if error else "done",
    }
    trigger = meta.get("trigger")
    if trigger in ("auto", "manual"):
        payload["trigger"] = trigger
    for theirs, ours in (("pre_tokens", "tokens_before"), ("post_tokens", "tokens_after")):
        value = meta.get(theirs)
        if isinstance(value, int | float) and value > 0:
            payload[ours] = int(value)
    took = meta.get("duration_ms")
    payload["duration_ms"] = (
        int(took)
        if isinstance(took, int | float) and took >= 0
        else int((time.perf_counter() - st.compaction_started) * 1000)
    )
    if error:
        payload["error"] = error[:300]
    st.compaction_id = ""
    return [make_event("compaction", payload)]


def _claude_compaction_events(obj: dict[str, Any], st: _ClaudeState) -> list[dict[str, Any]] | None:
    """A compaction line as ``compaction`` events; ``None`` for any other system line.

    Claude Code says ``status: "compacting"`` when it starts (and again every
    30 s while it runs), ``compact_boundary`` with the token counts once the
    summary replaced the history, and a ``status`` line with ``compact_result``
    at the end, ``compact_error`` when it failed.
    """
    subtype = obj.get("subtype")
    if subtype == "compact_boundary":
        raw = obj.get("compact_metadata")
        meta = raw if isinstance(raw, dict) else {}
        trigger = str(meta.get("trigger") or "")
        return _claude_compaction_open(st, trigger) + _claude_compaction_close(st, meta)
    if subtype != "status":
        return None
    if obj.get("status") == "compacting":
        return _claude_compaction_open(st)
    if obj.get("compact_result") == "failed" or obj.get("compact_error"):
        reason = str(obj.get("compact_error") or "The conversation could not be compacted.")
        return _claude_compaction_close(st, {}, error=reason)
    return []


def translate_claude_line(obj: dict[str, Any], st: _ClaudeState) -> list[dict[str, Any]]:
    """One Claude-shaped NDJSON object -> zero or more agent-chat events."""
    out: list[dict[str, Any]] = []
    kind = str(obj.get("type") or "")
    sid = obj.get("session_id") or obj.get("conversation_id")
    if sid and not st.vendor_session:
        st.vendor_session = str(sid)

    parent = obj.get("parent_tool_use_id")
    if parent:
        return _claude_subagent_line(obj, st, str(parent))
    if kind in {"rate_limit_event", "assistant", "result"}:
        limit_from_claude_line(st.limit, obj)
    if kind == "assistant" and str(obj.get("error") or "") == "rate_limit":
        # The CLI's own message for a refused request ("You've hit your Fable
        # limit · ..."), not the agent's words: the turn's error carries it,
        # and the thread notice says what happened next (``model_fallback``).
        return out

    if kind == "tool_use_summary":
        # The CLI's own short title for the tool calls it just made.
        summary = " ".join(str(obj.get("summary") or "").split())
        ids = [str(i) for i in (obj.get("preceding_tool_use_ids") or []) if i]
        if not summary or not ids:
            return []
        payload = {"turn_id": st.turn_id, "summary": summary[:200], "call_ids": ids}
        return [make_event("tool_summary", payload)]

    if kind == "rate_limit_event":
        # How much of the seat's plan is spent, from the provider's own
        # response headers: the thread's plan meter reads it.
        if st.usage_home is not None:
            from dodaios import agent_usage

            agent_usage.note_claude_rate_limit(st.usage_home, obj.get("rate_limit_info"))
        return []

    if kind == "system":
        # init / hooks are nothing the timeline shows; a sub-agent's life
        # (started, working, finished) is, a wait on open tasks is, and so is
        # the agent compacting its own conversation.
        compaction = _claude_compaction_events(obj, st)
        if compaction is not None:
            return compaction
        out = _claude_task_events(obj, st)
        _claude_track_task(obj, st)
        if obj.get("subtype") == "task_notification" and not st.saw_result:
            st.notices_pending += 1
        return out + _claude_wait_events(st)

    if kind == "stream_event":
        ev = obj.get("event") or {}
        et = ev.get("type")
        if et == "message_start":
            # The model answers again: a compaction still open has ended.
            out.extend(_claude_compaction_close(st, {}))
            mid = ((ev.get("message") or {}).get("id")) or uuid.uuid4().hex
            st.current_message_id = str(mid)
            # The agent works again (a finished task woke it): no longer waiting.
            st.idle = False
            st.answered = False
            out.extend(_claude_wait_events(st))
        elif et == "content_block_start":
            block = ev.get("content_block") or {}
            if block.get("type") == "thinking":
                mid = st.current_message_id or uuid.uuid4().hex
                st.current_message_id = mid
                st.thinking_started.setdefault(mid, time.perf_counter())
                # Claude Code redacts thinking text in its stream, so without
                # this the UI learned of eight seconds of thought only once it
                # was over. Announce the block the moment it opens.
                if mid not in st.thinking_announced:
                    st.thinking_announced.add(mid)
                    out.append(
                        make_event(
                            "reasoning_started",
                            {"turn_id": st.turn_id, "message_id": mid},
                        )
                    )
        elif et == "content_block_delta":
            delta = ev.get("delta") or {}
            mid = st.current_message_id or uuid.uuid4().hex
            st.current_message_id = mid
            if delta.get("type") == "text_delta" and delta.get("text"):
                # Streamed text counts as text the timeline already has. Without
                # this, a turn whose closing ``assistant`` message never arrives
                # (a kill, a crash, a truncated stream) fell through to the
                # ``result`` fallback below and emitted the SAME answer a second
                # time under a new message id — the duplicated output the
                # maintainer saw on 2026-08-25. The Codex shape already does it.
                st.emitted_text = True
                out.append(
                    make_event(
                        "text_delta",
                        {"turn_id": st.turn_id, "message_id": mid, "text": delta["text"]},
                    )
                )
            elif delta.get("type") == "thinking_delta" and delta.get("thinking"):
                st.thinking_started.setdefault(mid, time.perf_counter())
                out.append(
                    make_event(
                        "reasoning_delta",
                        {"turn_id": st.turn_id, "message_id": mid, "text": delta["thinking"]},
                    )
                )
            # Count what streams as it streams: text, a tool call's input and
            # readable thinking are all output. The CLI reports a message's
            # true output count only once the message ends, so between those
            # reports the counter would otherwise sit on the start-of-message
            # placeholder ("Working 28s · 39 tokens" on a turn that ended at
            # 11k). The estimate never overrides a real report.
            streamed = delta.get("text") or delta.get("partial_json") or delta.get("thinking")
            if isinstance(streamed, str) and streamed:
                st.stream_chars[mid] = st.stream_chars.get(mid, 0) + len(streamed)
                event = _claude_usage_event(st, min_output_step=_LIVE_OUTPUT_STEP)
                if event is not None:
                    out.append(event)
        elif et == "message_delta":
            if (ev.get("delta") or {}).get("stop_reason") == "end_turn":
                st.idle = True
                out.extend(_claude_wait_events(st))
            # The end of a message: its usage carries the true output count.
            usage_end = ev.get("usage")
            mid = st.current_message_id
            if mid and isinstance(usage_end, dict) and _claude_merge_usage(st, mid, usage_end):
                event = _claude_usage_event(st)
                if event is not None:
                    out.append(event)
        return out

    if kind == "assistant":
        message = obj.get("message") or {}
        mid = str(message.get("id") or st.current_message_id or uuid.uuid4().hex)
        st.current_message_id = mid
        named = message.get("model")
        if isinstance(named, str) and named and not named.startswith("<"):
            st.context_model = named
        usage_now = message.get("usage")
        if isinstance(usage_now, dict) and _claude_merge_usage(st, mid, usage_now):
            event = _claude_usage_event(st)
            if event is not None:
                out.append(event)
        content = message.get("content") or []
        if not isinstance(content, list):
            content = [{"type": "text", "text": str(content)}]
        text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
        snapshot = len(content) > 1
        visual_blocks = [
            block
            for block in content
            if isinstance(block, dict)
            and block.get("type")
            in {"image", "image_url", "input_image", "video", "audio", "resource", "resource_link"}
        ]
        if visual_blocks:
            st.emitted_text = True
            visual_content = [
                block
                for block in content
                if block in visual_blocks
                or (isinstance(block, dict) and block.get("type") == "text")
            ]
            out.append(
                make_event(
                    "assistant_text",
                    {
                        "turn_id": st.turn_id,
                        "message_id": mid,
                        "text": json.dumps({"content": visual_content}, ensure_ascii=False),
                    },
                )
            )
            text_blocks = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "thinking":
                thought = str(block.get("thinking") or "")
                if snapshot:
                    st.thinking_acc[mid] = thought
                else:
                    st.thinking_acc[mid] = st.thinking_acc.get(mid, "") + thought
                started = st.thinking_started.get(mid)
                out.append(
                    make_event(
                        "reasoning",
                        {
                            "turn_id": st.turn_id,
                            "message_id": mid,
                            "text": st.thinking_acc[mid],
                            "duration_ms": int((time.perf_counter() - started) * 1000)
                            if started
                            else None,
                        },
                    )
                )
            elif btype == "tool_use":
                call_id = str(block.get("id") or uuid.uuid4().hex)
                if call_id in st.emitted_tool_ids:
                    continue
                st.emitted_tool_ids.add(call_id)
                name = str(block.get("name") or "tool")
                args = block.get("input") or {}
                if st.grok and isinstance(args, dict):
                    note = str(args.get("description") or args.get("command") or "").strip()
                    if note:
                        st.call_notes[call_id] = note
                    if name in _GROK_BACKGROUND_TOOLS or args.get("background") is True:
                        st.background_calls.add(call_id)
                out.append(
                    make_event(
                        "tool_call",
                        {
                            "turn_id": st.turn_id,
                            "call_id": call_id,
                            "name": name,
                            "input": args if isinstance(args, dict) else {"input": args},
                            "summary": _cli_tool_summary(name, args),
                        },
                    )
                )
        if text_blocks:
            joined = "".join(str(b.get("text") or "") for b in text_blocks)
            if snapshot:
                st.text_acc[mid] = joined
            else:
                st.text_acc[mid] = st.text_acc.get(mid, "") + joined
            if st.text_acc[mid].strip():
                st.emitted_text = True
                out.append(
                    make_event(
                        "assistant_text",
                        {"turn_id": st.turn_id, "message_id": mid, "text": st.text_acc[mid]},
                    )
                )
        return out

    if kind == "user":
        message = obj.get("message") or {}
        content = message.get("content") or []
        if isinstance(content, list):
            for block in content:
                if st.grok and isinstance(block, dict) and block.get("type") == "text":
                    # A reminder Grok adds as its own user text (a task's end).
                    _grok_track_tasks(str(block.get("text") or ""), st)
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    output = _content_text(block.get("content"))
                    if st.grok:
                        _grok_track_tasks(output, st, str(block.get("tool_use_id") or ""))
                    is_error = bool(block.get("is_error"))
                    if is_error and output.strip():
                        st.last_tool_error = output.strip()
                    out.append(
                        make_event(
                            "tool_result",
                            {
                                "turn_id": st.turn_id,
                                "call_id": str(block.get("tool_use_id") or ""),
                                "output": output,
                                "is_error": is_error,
                                "duration_ms": None,
                            },
                        )
                    )
        elif st.grok and isinstance(content, str):
            _grok_track_tasks(content, st)
        if st.grok:
            out.extend(_claude_wait_events(st))
        return out

    if kind == "result":
        out.extend(_claude_compaction_close(st, {}))
        if st.notices_pending and claude_result_without_model_turn(obj):
            # The CLI's own empty answer to a task notice it found on resume:
            # the person's prompt runs after it, so this is not the turn's end.
            st.notices_pending -= 1
            return out
        st.notices_pending = 0
        st.saw_result = True
        st.answered = True
        st.idle = True
        if st.grok:
            # Grok prints its result only once all its background work ended
            # (headless mode waits for it): nothing it started is still open.
            st.open_tasks.clear()
        out.extend(_claude_wait_events(st))
        st.result_text = str(obj.get("result") or "")
        if obj.get("is_error"):
            st.status = "error"
            errors = obj.get("errors")
            detail = "; ".join(str(e) for e in errors if e) if isinstance(errors, list) else ""
            st.error = (
                st.result_text or detail or st.last_tool_error or str(obj.get("subtype") or "error")
            )
            if st.limit.hit:
                # A refused request: its sentence is the error, never an answer.
                st.result_text = ""
        usage = obj.get("usage") or {}
        if isinstance(usage, dict):
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ):
                if isinstance(usage.get(k), int | float):
                    st.usage[k] = int(usage[k])
            details = usage.get("output_tokens_details")
            if isinstance(details, dict) and isinstance(
                details.get("thinking_tokens"), int | float
            ):
                st.usage["thinking_tokens"] = int(details["thinking_tokens"])
        cost = obj.get("total_cost_usd", obj.get("cost_usd"))
        if isinstance(cost, int | float):
            st.cost_usd = float(cost)
        if st.context_used:
            # Once per answer, stored: a reopened thread shows its ring at once.
            model, window = window_from_result(obj.get("modelUsage"), st.context_model)
            out.append(
                make_event(
                    "context_usage",
                    {"turn_id": st.turn_id, **context_reading(st.context_used, model, window)},
                )
            )
        return out

    return out
