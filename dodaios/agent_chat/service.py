"""Sessions in flight: who is running, who is listening, who is waiting.

:class:`AgentChatService` is the one object the routes talk to. It owns the
store, keeps at most ONE running turn per session, fans every event out to
the session's live subscribers (the WebSocket handlers) after persisting it,
and parks a turn on an ``asyncio.Future`` while the person decides on an
approval card. Cancel sets the turn's event and awaits the task; a runner
that is mid-tool or mid-stream ends at the next boundary (the API loop
between deltas, the CLI by killing the child).

The runner is picked per turn from the provider row AND the session's
surface. On the agent surface a CLI-backed provider uses :mod:`runner_cli`,
``claude-api`` uses the CLI when the ``claude`` binary is on PATH and the API
otherwise, and everything else uses :mod:`runner_api`. On the Jarvis surface
(the front page's chat) every API-key or local row runs on Jarvis' own brain
instead (``brain``), and a CLI seat runs as Jarvis. The choice is recorded in
``turn_started`` so the timeline can say what answered.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sqlite3
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from dodaios.agent_chat import attachments as chat_attachments
from dodaios.agent_chat import (
    lead_compaction,
    plan_review,
    seat_outcomes,
    thread_clear,
    token_efficiency,
    turn_errors,
    turn_prompts,
)
from dodaios.agent_chat.approval_bridge import ChatApprovalBridge
from dodaios.agent_chat.approval_defer import DEFER_NOTICE, Deferred, DeferredApprovals
from dodaios.agent_chat.approval_memory import PersistedBags
from dodaios.agent_chat.catalog import PROVIDER_ROWS, api_seat, offers, provider_row
from dodaios.agent_chat.credential_requests import (
    CREDENTIAL_TIMEOUT_S,
    CredentialRequests,
    CredentialSpec,
)
from dodaios.agent_chat.effort import normalize_effort
from dodaios.agent_chat.events import CLEARED_KIND, is_transient, make_event, shown_text
from dodaios.agent_chat.parked_work import BACKGROUND_ORIGIN, ParkedWorkBoard
from dodaios.agent_chat.permissions import (
    PLAN_MODES,
    ladder_key,
    mode_after_plan,
    normalize_permission,
    permission_ids,
)
from dodaios.agent_chat.plan_review import PlanReview
from dodaios.agent_chat.questions import (
    CANCELLED,
    MAX_ASKS_PER_TURN,
    MESSAGE,
    MOVED_ON,
    QUESTION_TIMEOUT_S,
    RECALL_WINDOW_S,
    SKIPPED,
    TIMEOUT,
    QuestionAnswer,
    QuestionSpec,
    TooManyQuestions,
    answer_from,
    answer_json,
    declined_answer,
    note_answers,
    person_answers,
    recall,
    recommended_answer,
)
from dodaios.agent_chat.runner_api import TurnHandle, run_api_turn, supports_api_runner
from dodaios.agent_chat.runner_brain import brain_history_from_events, run_brain_turn
from dodaios.agent_chat.runner_cli import run_cli_turn, supports_cli_runner
from dodaios.agent_chat.service_parts.approvals import ApprovalsMixin
from dodaios.agent_chat.service_parts.cancel import CancelMixin
from dodaios.agent_chat.service_parts.credentials import CredentialsMixin
from dodaios.agent_chat.service_parts.events import EventsMixin
from dodaios.agent_chat.service_parts.questions import QuestionsMixin
from dodaios.agent_chat.service_parts.restore import RestoreMixin
from dodaios.agent_chat.service_parts.send import SendMixin
from dodaios.agent_chat.service_parts.sessions import SessionsMixin
from dodaios.agent_chat.service_parts.turn_prompts import TurnPromptsMixin
from dodaios.agent_chat.service_parts.voice import VoiceMixin
from dodaios.agent_chat.speed import normalize_speed
from dodaios.agent_chat.store import (
    DEFAULT_SURFACE,
    SURFACES,
    AgentChatSession,
    AgentChatStore,
)
from dodaios.agent_chat.surface_kits import kit_for
from dodaios.agent_chat.turn_host_client import TurnHandedOver
from dodaios.brain.assistant_name import DEFAULT_ASSISTANT_NAME
from dodaios.core.protocols import ChatCompletion, ChatTurn, current_chat_turn
from dodaios.society.delivery import IncomingMessage

log = logging.getLogger(__name__)
#: A ``[tools: a, b]`` capability-pin line. The list starts with a
#: non-space character, so the padding and the list cannot both claim the
#: same spaces: matching stays linear on long lines of spaces.
_TOOL_PIN_LINE = re.compile(r"(?m)^\[tools:[ \t]*([^\]\s][^\]\r\n]*)\][ \t\r]*$")


def _stop_caller() -> str:
    """The code that asked a turn to stop, as ``module:function`` hops.

    A stopped turn otherwise only says "cancelled"; this names the path that
    ended it (HTTP stop, goal pause, society runtime, browser cancel).
    """
    frames = traceback.extract_stack(limit=6)[:-2]
    return " <- ".join(f"{Path(frame.filename).stem}:{frame.name}" for frame in reversed(frames))


#: What a turn cut off by a restart says (``_seal_orphaned_turns``).
_ORPHANED_TURN_ERROR: Final = turn_errors.APP_RESTARTED

Subscriber = asyncio.Queue[dict[str, Any]]
#: The last item a subscriber that fell too far behind receives: its reader
#: closes and re-syncs from the store (``AgentChatService._drop_subscriber``).
SUBSCRIBER_DROPPED: Final[dict[str, Any]] = {"kind": "subscriber_dropped", "payload": {}}
#: How long a send waits for a finished turn's cleanup before it is busy.
_FINISHING_WAIT_S: Final[float] = 10.0


#: The app's loop, resolved by the route layer BEFORE it takes its build lock
#: (``remember_app_loop``). Asking the loop from inside that lock deadlocked
#: the whole app (2026-10-07): the worker waited for the loop while the loop
#: waited for the lock in an ``async`` route.
_KNOWN_LOOP: asyncio.AbstractEventLoop | None = None


def remember_app_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Find and record the app's loop, so building the service never asks it.

    Call it without holding any lock the loop could be waiting for: from a
    worker thread, finding the loop waits until the loop answers. A caller on
    the loop passes it: the boot reattach builds the service in a plain
    ``asyncio.to_thread`` thread, where asking finds no loop at all.
    """
    global _KNOWN_LOOP  # one process-wide reference, set before the service is built
    if loop is None:
        loop, _on_loop = _app_loop()
    if loop is not None:
        _KNOWN_LOOP = loop


def _app_loop() -> tuple[asyncio.AbstractEventLoop | None, bool]:
    """The app's event loop, and whether this code runs on it.

    The service is built on first use, and the first use is often a plain
    ``def`` route that the web framework runs in a worker thread, where no
    loop is running. Finding no loop there sealed every thread turn the turn
    host still held as "Jarvis restarted" (2026-10-06): the worker thread asks
    the loop it was dispatched from instead.
    """
    try:
        return asyncio.get_running_loop(), True
    except RuntimeError:  # no loop on this thread: fall through to the dispatching loop
        pass
    known = _KNOWN_LOOP
    if known is not None and known.is_running():
        return known, False
    try:
        from anyio.from_thread import run_sync

        return run_sync(asyncio.get_running_loop), False
    except Exception:  # noqa: BLE001 - not a framework worker: no loop to reach
        log.debug("agent chat: built outside any event loop")
        return None, False


def _orphan_event(turn_id: str, started_ms: int, last_ms: int) -> dict[str, Any]:
    """The ``turn_finished`` that closes a turn a restart cut off."""
    return {
        **make_event(
            "turn_finished",
            {
                "turn_id": turn_id,
                "status": "error",
                "duration_ms": max(0, last_ms - started_ms),
                "usage": {},
                "error": _ORPHANED_TURN_ERROR,
                "cost_usd": None,
            },
        ),
        "ts_ms": last_ms,
    }


def _questions_left_open(
    turn_id: str, history: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """The live question cards of ``turn_id`` an app restart left open.

    Only the previous process waited on them, so their buttons could only
    answer "no such open question". The CLI in the turn host asks again on a
    new card once the turn is carried on. Each card maps to the answers its
    ``question_resolved`` carries: what the person already picked stays, every
    other question reads ``cancelled``. An end-of-turn card (``deferred``)
    lives in the event log and stays open.
    """
    open_cards: dict[str, list[dict[str, Any] | None]] = {}
    for event in history:
        payload = event.get("payload") or {}
        if str(payload.get("turn_id") or "") != turn_id:
            continue
        question_id = str(payload.get("question_id") or "")
        if not question_id:
            continue
        kind = event.get("kind")
        if kind == "question_required" and not payload.get("deferred"):
            asked = payload.get("questions")
            open_cards[question_id] = [None] * (len(asked) if isinstance(asked, list) else 1)
        elif kind == "question_progress" and question_id in open_cards:
            rows = payload.get("answers")
            if isinstance(rows, list) and len(rows) == len(open_cards[question_id]):
                open_cards[question_id] = [r if isinstance(r, dict) else None for r in rows]
        elif kind == "question_resolved":
            open_cards.pop(question_id, None)
    cancelled = QuestionAnswer("", None, CANCELLED).to_payload()
    return {
        question_id: [row if row is not None else dict(cancelled) for row in rows]
        for question_id, rows in open_cards.items()
    }


DECISIONS: tuple[str, ...] = ("allow", "allow_always", "deny")
#: Where a rule from the approval card lives: the agent's own rules or this chat.
RULE_SCOPES: tuple[str, ...] = ("agent", "chat")
#: How far an agent rule from the card reaches: this action, or the whole app.
RULE_BREADTHS: tuple[str, ...] = ("action", "app")
#: How narrow a chat rule from the card is: only this folder, only this command
#: (approval_card.narrow_options). Empty: the whole tool, as before.
RULE_NARROWS: tuple[str, ...] = ("folder", "command")


class SessionBusy(RuntimeError):
    """A turn is already running in this session."""


class NoSuchSession(KeyError):
    pass


def _claude_cli_installed() -> bool:
    return bool(shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe"))


#: Society agent runtimes that replace the provider's runner (``AgentRuntime``
#: minus ``jarvis``), each answered by its ACP driver in ``runner_cli``.
EXTERNAL_RUNTIME_RUNNERS: Final[dict[str, str]] = {
    "hermes": "hermes-cli",
    "openclaw": "openclaw-cli",
}


async def society_execution_environment(session_id: str) -> str | None:
    """Where a society agent's tools execute; ``None`` when it cannot be read."""
    from dodaios.society.runtime import current_runtime
    from dodaios.society.surface import agent_id_of

    runtime = current_runtime()
    if runtime is None:
        return None
    agent = await runtime.roster.get(agent_id_of(session_id) or "")
    return None if agent is None else str(getattr(agent, "execution_environment", "local"))


def resolve_runner(
    provider: str, *, surface: str = "agent", runtime: str = "", account_id: str = ""
) -> str:
    """Which runner answers for ``provider`` on this machine, right now.

    ``claude-api`` is dual: Claude Code (the CLI) when it is installed — that
    is the subscription path and the one with the CLI's own tools — else the
    Anthropic API. Every other provider row names its runner outright.

    On the Jarvis surface the API path is Jarvis' own brain (``brain``): the
    same set of providers, driven by ``BrainManager.generate`` instead of the
    coding agent's tool loop. That surface also seats vendor CLIs
    (``SurfaceKit.cli_seats`` is on): a CLI-backed row, and the dual Claude row
    while Claude Code is installed, answers through its CLI runner as Jarvis
    (``runner_cli`` with the identity). A surface whose kit has no CLI seats
    answers on its API runner only.

    ``account_id`` is the seat's login, or a reserved access value
    (``catalog.ACCESS_ACCOUNTS``) that pins the dual Claude row to its API key
    or to its subscription for one agent, over the API Keys page's setting.
    """
    if runtime in EXTERNAL_RUNTIME_RUNNERS and surface == "society":
        # A Hermes / OpenClaw agent: that runtime's loop answers every turn and
        # the provider only names the model it is configured with.
        return EXTERNAL_RUNTIME_RUNNERS[runtime]
    kit = kit_for(surface)
    api_runner = "brain" if kit.brain_runner else "api"
    row = provider_row(provider)
    if row is None:
        return api_runner if supports_api_runner(provider) else "unknown"
    if not kit.cli_seats:
        # No vendor process here: the provider's own API answers, or nothing
        # does. ``rows_for`` keeps the picker to the same set, so "unknown"
        # is only reachable through a stale session or a hand-made request.
        return api_runner if supports_api_runner(row.id) else "unknown"
    if row.id == "claude-api":
        # The API Keys page can set the agents' Claude to its key instead of
        # the subscription; that choice narrows the agents' surface only.
        from dodaios.agent_chat.agent_provider_prefs import forces_api
        from dodaios.agent_chat.catalog import API_KEY_ACCOUNT, SUBSCRIPTION_ACCOUNT

        if account_id == API_KEY_ACCOUNT:
            return api_runner
        if account_id != SUBSCRIPTION_ACCOUNT and forces_api(row.id, surface):
            return api_runner
        return "claude-cli" if _claude_cli_installed() else api_runner
    if row.runner == "api":
        return api_runner
    return row.runner


def session_runner(session: Any) -> str:
    """:func:`resolve_runner` for a stored chat session (its runtime included)."""
    return resolve_runner(
        session.provider,
        surface=session.surface,
        runtime=str(getattr(session, "runtime", "") or ""),
        account_id=str(getattr(session, "account_id", "") or ""),
    )


#: Seats whose CLI takes a message with files into its running turn: Claude
#: Code and GLM read a picture as an image block of a stream-json message.
_STEER_FILE_RUNNERS: Final[frozenset[str]] = frozenset({"claude-cli", "glm-cli"})


def _seen_directly(cwd: str, attached: list[Any], images: tuple[str, ...]) -> list[Any]:
    """``attached`` with every picture in ``images`` marked as sent to the CLI itself.

    The CLI looks at such a picture directly, so its vision description is
    dropped; the file path stays in the text for the CLI's tools.
    """
    from dodaios.agentic_ide import drops

    sent = set(images)
    return [
        replace(
            a,
            detail="",
            described_by="none",
            note="Attached to this message as an image; look at it directly.",
        )
        if getattr(a, "kind", "") == "image"
        and str(Path(cwd) / drops.dereference(str(a.reference))) in sent
        else a
        for a in attached
    ]


def _opened_by(session: Any, author: dict[str, str] | None, history: list[Any]) -> str:
    """The agent that opened a coding thread, ``""`` when the person did.

    The store names it from the thread's first message on (``started_by``). On
    that first turn the session object is older than the message, so the
    author of a message into an empty thread stands in: the same value on
    every turn, which keeps the thread's system prompt the same.
    """
    if str(getattr(session, "surface", "") or "") != "agent":
        return ""
    from dodaios.briefs import settings as brief_settings

    if not brief_settings.current().standing_rules:
        return ""
    known = str(getattr(session, "started_by", "") or "")
    if known or history or not author:
        return known
    return str(author.get("agent_id") or "")


def _attachment_receipts(attached: list[Any]) -> list[dict[str, Any]]:
    """What a ``user_message`` event keeps of the files that came with it."""
    return [
        {
            "name": item.name,
            "reference": item.reference,
            "kind": item.kind,
            "described_by": item.described_by,
            "note": item.note,
        }
        for item in attached
    ]


#: ``AgentChatStore.data_version`` after the front page's chat gave up its
#: CLI seats (2026-08-26) and its sessions moved to the API row of the same
#: brand. Bump — and add a branch in ``_retire_cli_seats``' caller — only for
#: another migration that rewrites what a person picked.
_CLI_SEATS_RETIRED: Final[int] = 1


#: Words in a coding agent CLI's executable or script name (``claude.exe``,
#: ``codex.js``, ``gemini.cmd``, ...).
_AGENT_CLI_WORDS: Final[tuple[str, ...]] = (
    "claude",
    "codex",
    "gemini",
    "grok",
    "opencode",
    "kimi",
    "qwen",
    "glm",
    "antigravity",
    "cursor-agent",
    "copilot",
)


def _is_agent_cli(cmdline: list[str]) -> bool:
    """Whether a command line runs a coding agent CLI: its program or the script node runs."""
    for part in cmdline[:3]:
        name = part.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if any(word in name for word in _AGENT_CLI_WORDS):
            return True
    return False


def stop_cli_at_cwd(cwd: str) -> int:
    """Stop a leftover chat CLI whose working folder is exactly ``cwd``.

    Used when the stop button finds no in-memory turn. The match is one
    command-line argument, not a substring of the prompt, so a mention of
    the folder inside the task text does not count — and only a coding
    agent's process counts: a shell, editor or dev server the person runs
    in that folder is never Stop's to end.
    """
    root = Path(cwd).expanduser()
    try:
        root = root.resolve()
    except OSError:  # An unresolvable workspace cannot match a running process.
        return 0
    if not root.is_dir():
        return 0
    needles = {str(root).rstrip("\\/"), str(root).replace("\\", "/").rstrip("/")}
    if all(len(item) < 16 for item in needles):
        return 0
    try:
        import psutil
    except ImportError:
        log.warning("agent chat: cannot stop a leftover CLI without psutil")
        return 0
    import os

    me = {os.getpid(), os.getppid()}
    stopped = 0
    for proc in psutil.process_iter(["pid", "cmdline"]):
        pid = proc.info.get("pid")
        if pid in me:
            continue
        parts = [str(part).rstrip("\\/") for part in (proc.info.get("cmdline") or [])]
        if not any(needle in parts for needle in needles):
            continue
        if not _is_agent_cli(parts):
            continue
        try:
            for child in proc.children(recursive=True):
                child.terminate()
            proc.terminate()
            stopped += 1
        except Exception:
            log.warning("agent chat: could not stop leftover CLI %s", pid, exc_info=True)
    return stopped


class _OpenQuestion:
    """A card waiting on the person: one answer slot per question in the series.

    It lives independently of the tool call that opened it: a CLI drops an
    MCP call after a minute or so, while the card may stay open for five.
    ``result`` resolves once the card closes; callers wait on it in slices.
    """

    __slots__ = (
        "answers",
        "closing",
        "delivered",
        "result",
        "session_id",
        "specs",
        "touched",
        "turn_id",
        "wake",
    )

    def __init__(
        self,
        session_id: str,
        turn_id: str,
        specs: tuple[QuestionSpec, ...],
        result: asyncio.Future[list[QuestionAnswer]],
    ) -> None:
        self.session_id = session_id
        self.turn_id = turn_id
        self.specs = specs
        self.answers: list[QuestionAnswer | None] = [None] * len(specs)
        #: Set by a skip or a cancel: the source every open slot resolves to.
        self.closing = ""
        self.wake = asyncio.Event()
        self.result = result
        self.delivered = False
        #: The person is working through the card (picks not sent yet):
        #: the watcher restarts its quiet window once.
        self.touched = False

    @property
    def done(self) -> bool:
        return bool(self.closing) or all(a is not None for a in self.answers)


def _message_answer(spec: QuestionSpec, text: str) -> QuestionAnswer:
    """A chat message as the answer to ``spec``: a reply that names an option
    (its label, or its letter on its own) picks it; anything else is the
    person's own words."""
    typed = text.strip()
    folded = typed.casefold().rstrip(".!")
    for index, option in enumerate(spec.options):
        letter = "ABCD"[index] if index < 4 else ""
        if folded == option.label.casefold() or (letter and folded == letter.casefold()):
            if spec.kind == "multi":
                return answer_from(
                    spec, option_index=None, text=None, option_indices=[index], source=MESSAGE
                )
            return answer_from(spec, option_index=index, text=None, source=MESSAGE)
    return answer_from(spec, option_index=None, text=typed, source=MESSAGE)


#: Said of a voice call's tool when the call event carries no result text.
_VOICE_TOOL_NOTE: Final[str] = "(ran during the voice call; its result was not recorded here)"
_VOICE_TOOL_OUTPUT_CAP: Final[int] = 400


def _voice_tool_records(tool_calls: Sequence[str | dict[str, Any]]) -> list[tuple[str, str]]:
    """``(name, short output)`` of each tool a voice turn ran, in order."""
    records: list[tuple[str, str]] = []
    for item in tool_calls or ():
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            output = str(item.get("output") or "").strip()[:_VOICE_TOOL_OUTPUT_CAP]
        else:
            name, output = str(item or "").strip(), ""
        if name:
            records.append((name, output or _VOICE_TOOL_NOTE))
    return records


def _first_open(answers: list[QuestionAnswer | None] | tuple[QuestionAnswer | None, ...]) -> int:
    return next((i for i, a in enumerate(answers) if a is None), -1)


def _expires_ms(timeout_s: float | None) -> int | None:
    """When a card closes by itself; ``None`` for a card that waits as long as it takes."""
    if timeout_s is None:
        return None
    return int(time.time() * 1000 + timeout_s * 1000)


async def _redact_credentials(
    session_id: str,
    event: dict[str, Any],
    agent_id: str | None = None,
) -> dict[str, Any]:
    """``event`` with the stored credential values of the chat's owner masked.

    A command that prints a token shows ``[credential ENV]`` in the chat, its
    log and the live stream instead of the value (dodaios/society/credentials.py).
    ``agent_id`` is whose vault applies: a society seat's own, or for the lead's
    chat the owner's vault the lead keeps; by default the society chat's agent.
    """
    try:
        # Logins a running browser task holds for the credential broker (a
        # password-manager value the vault never stored) are masked first.
        from dodaios.credential_broker import redact_active

        masked = redact_active(event.get("payload"))
        if masked is not event.get("payload"):
            event = {**event, "payload": masked}
        from dodaios.society.credentials import current_vault
        from dodaios.society.surface import agent_id_of

        vault = current_vault()
        if agent_id is None:
            agent_id = agent_id_of(session_id)
        if vault is None or agent_id is None:
            return event
        if not vault.is_loaded(agent_id):
            await asyncio.to_thread(vault.values, agent_id)
        payload = event.get("payload")
        redacted = vault.redact_payload(agent_id, payload)
    except Exception:  # noqa: BLE001 — fails closed: the text is withheld, the event stays
        log.warning("agent chat: credential redaction failed for %s", session_id, exc_info=True)
        return {**event, "payload": _withheld(event.get("payload"))}
    return event if redacted is payload else {**event, "payload": redacted}


#: Payload keys that name an event, never carry printed text.
_EVENT_IDS: Final[frozenset[str]] = frozenset(
    {"turn_id", "call_id", "message_id", "agent_id", "name", "request_id", "question_id"}
)


def _withheld(payload: Any) -> Any:
    """``payload`` with all its text replaced: what an unmaskable event shows."""
    if isinstance(payload, dict):
        return {k: v if k in _EVENT_IDS else _withheld(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_withheld(item) for item in payload]
    if isinstance(payload, str):
        return "[hidden: the credential check failed]" if payload else payload
    return payload


def _current_task() -> asyncio.Task[Any] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:  # Synchronous routes may inspect status off the event loop.
        return None


class _Running:
    __slots__ = ("asks", "task", "cancel", "turn_id", "setup_task", "ready", "detached", "finished")

    def __init__(self, turn_id: str, cancel: asyncio.Event) -> None:
        self.turn_id = turn_id
        self.cancel = cancel
        self.task: asyncio.Task[None] | None = None
        self.setup_task: asyncio.Task[Any] | None = _current_task()
        self.ready = asyncio.Event()
        #: Question cards this turn has shown (MAX_ASKS_PER_TURN).
        self.asks = 0
        #: The app is shutting down and this turn's CLI keeps running in the
        #: turn host: the task ends without closing the turn.
        self.detached = False
        #: The turn's ``turn_finished`` is published; only its cleanup runs.
        self.finished = False


class AgentChatService(
    RestoreMixin,
    SessionsMixin,
    EventsMixin,
    SendMixin,
    VoiceMixin,
    CancelMixin,
    ApprovalsMixin,
    QuestionsMixin,
    CredentialsMixin,
    TurnPromptsMixin,
):
    supports_turn_completion = True

    def __init__(
        self,
        store: AgentChatStore,
        *,
        assistant_name: Callable[[], str] | None = None,
        default_cwd: Callable[[], str] | None = None,
        bus: Callable[[], Any | None] | None = None,
    ) -> None:
        self.store = store
        self._assistant_name = assistant_name or (lambda: DEFAULT_ASSISTANT_NAME)
        self._default_cwd = default_cwd or (lambda: str(Path.home()))
        # The app bus, resolved late (the server builds this service before
        # the brain is up). The brain runner reads its tool events off it and
        # the approval bridge answers the executor on it; without a bus the
        # Jarvis surface still answers, just without tool rows and cards.
        self._bus = bus or (lambda: None)
        self._bridge: ChatApprovalBridge | None = None
        # Brain-runner turns run one at a time PER SESSION, never across
        # sessions: the lead's typed turn must not wait behind a society
        # agent's or a routine's long turn. The prompt inputs a turn reads
        # (evidence directive, recall, provider identity) are ContextVar state
        # of the manager's ``generate`` call, so concurrent sessions do not see
        # each other's. Voice is NOT held by these locks either.
        self._brain_locks: dict[str, asyncio.Lock] = {}
        self._running: dict[str, _Running] = {}
        # Reserved before control state is marked running. The runner has not
        # started yet, but a competing send and Stop must both see this owner.
        self._preparing: dict[str, _Running] = {}
        #: Running turns whose CLI takes a message mid-turn: session -> (turn, writer).
        self._steerers: dict[str, tuple[str, Callable[..., Awaitable[bool]]]] = {}
        self._subscribers: dict[str, set[Subscriber]] = {}
        # Synchronous observers of every stored event (add_event_listener).
        self._event_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._approvals: dict[str, asyncio.Future[str]] = {}
        self._approval_session: dict[str, str] = {}
        # Cards a restart left unanswered on a thread turn the turn host kept
        # running, by (session, turn, call): the CLI asks again and that card
        # answers it (_hold_unanswered_approvals).
        self._unanswered: dict[tuple[str, str, str], str] = {}
        # Questions an agent is waiting on (questions.py), by question id.
        self._questions: dict[str, _OpenQuestion] = {}
        self._question_tasks: set[asyncio.Task[None]] = set()
        # Credential cards (credential_requests.py): the value never enters a chat event.
        self._credentials = CredentialRequests(
            self._emit,
            self._running_turn_id,
            history=self.store.credential_events,
            restore_save=self._restore_field_save,
        )
        # "Always allow" on the Jarvis surface: the tools a person waved through
        # for the rest of the session, per session. Claude Code's "don't ask
        # again for this tool" rather than a mode flip — the unified ladder has
        # no word for "auto" and flipping to bypass would silence every later
        # card, a mail send included.
        # Every "always" bag below saves itself (approval_memory.py): the
        # person's choices stick across restarts, with the scope they had.
        self._always_allowed: dict[str, set[str]] = PersistedBags(self.store, "always", "set")
        # Where an "Always allow" from the card is to live, by approval id:
        # ``(scope, breadth, narrow)`` as the card's rule editor sent it.
        self._approval_choice: dict[str, tuple[str, str, str]] = {}
        # What the person typed on a declined card, by approval id; handed to
        # the agent as the deny message (see :meth:`take_deny_feedback`).
        self._approval_feedback: dict[str, str] = {}
        self._deny_feedback: dict[tuple[str, str], str] = {}
        # The call each open card asks about (tool, arguments), and the inline
        # edits the person sent with their answer (approval_preview.py).
        self._approval_call: dict[str, tuple[str, dict[str, Any]]] = {}
        self._approval_edits: dict[str, dict[str, Any]] = {}
        # Claude Code "Always allow" rules, per session: the rules the CLI
        # offered, kept across turns like its own session rules in a terminal.
        self._cli_rules: dict[str, list[dict[str, Any]]] = PersistedBags(self.store, "cli", "list")
        # Tools a coding session's person waved through ("Always allow") on a
        # runner that has no rule language of its own; the mode stays as it is.
        self._tool_always: dict[str, set[str]] = PersistedBags(self.store, "tool", "set")
        # Narrow chat rules from the card ("only this folder", "only this
        # command"), per session: a matching call runs without a card. They
        # are saved like the chat's other "always" and revocable on the Trust page.
        self._narrow_rules: dict[str, list[dict[str, str]]] = PersistedBags(
            self.store, "narrow", "list"
        )
        self._load_approval_memory()
        # A reversible action the executor ran for one of these chats leaves
        # its inverse in the undo ledger; the chat posts the undo notice.
        from dodaios.trust.undo import undo_ledger

        self._stop_undo_notices = undo_ledger().on_recorded(self._on_undo_recorded)
        # Tools whose "Always allow" the card just saved on the society agent,
        # by session: the approval bridge must not also wave the whole tool
        # through for the chat (a rule for one action would read wider).
        self._ruled_on_agent: dict[str, set[str]] = {}
        # Voice turn ids already mirrored into a chat timeline (see
        # import_voice_turn): the bus may deliver a turn twice across
        # reconnects, and a second copy in the chat would read as if the
        # person said everything twice. Bounded below in import_voice_turn.
        # The store keeps the ids (a unique row each); this set is only the
        # fallback of a store without that table.
        self._mirrored_voice_turns: set[str] = set()
        # The Jarvis chat a voice call continues (bind_voice_chat): the chat
        # the front page shows. ``_voice_chat_fresh`` = a blank page is open,
        # so the next call starts a new chat instead of joining the newest.
        # ``_voice_call_chats`` pins each running call to the chat its first
        # turn landed in, so opening another chat mid-call never splits it.
        self._voice_chat_id: str | None = None
        self._voice_chat_fresh = False
        self._voice_call_chats: dict[str, str] = {}
        # The archived voice chat's history while one is continued (bind_voice_chat).
        self._voice_archive_history: Callable[[], list[Any]] | None = None
        # Sessions whose restart turn is held while the turn host is asked
        # (``_seal_orphaned_turns``): a shutdown in that window leaves them
        # open for the next process instead of stopping their CLI.
        self._held_for_reattach: set[str] = set()
        self._reattach_task: Any = None
        self._retire_cli_seats()
        self._seal_orphaned_turns()
        self._restart_recovery_task: Any = None

    def _load_approval_memory(self) -> None:
        """Read the saved "always" choices and narrow rules into their bags."""
        try:
            rows = self.store.approval_memory()
        except Exception:  # noqa: BLE001 - the person is asked again; nothing breaks
            log.warning("agent chat: saved approval choices could not be read", exc_info=True)
            return
        bags = {
            "always": self._always_allowed,
            "tool": self._tool_always,
            "cli": self._cli_rules,
            "narrow": self._narrow_rules,
        }
        for name, bag in bags.items():
            bag.load([(sid, entry) for sid, b, entry in rows if b == name])  # type: ignore[attr-defined]


__all__ = [
    "AgentChatService",
    "TooManyQuestions",
    "DECISIONS",
    "NoSuchSession",
    "SessionBusy",
    "Subscriber",
    "resolve_runner",
    "session_runner",
]
