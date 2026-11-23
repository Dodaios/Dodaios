"""Shared pieces of the CLI runner: binaries, per-turn environment and seats, the plan type."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dodaios.agent_chat import dodaios_harness

log = logging.getLogger("dodaios.agent_chat.runner_cli")


class CliUnavailable(RuntimeError):
    """The binary is not installed (or not on PATH) — the UI says so."""


# ------------------------------------------------------------ binaries


#: The binaries behind each CLI runner, in the order tried. One table for the
#: planners below, the catalog route's "installed" flag and the workspace
#: panes' launch picks — three readers of one fact, so a CLI added here is
#: offerable everywhere at once.
CLI_BINARIES: Final[dict[str, tuple[str, ...]]] = {
    "claude-cli": ("claude", "claude.cmd", "claude.exe"),
    "codex-cli": ("codex", "codex.cmd", "codex.exe"),
    "agy-cli": ("agy", "agy.exe"),
    "grok-cli": ("grok", "grok.exe", "grok.cmd"),
    "opencode-cli": ("opencode", "opencode.cmd", "opencode.exe"),
    "kimi-cli": ("kimi", "kimi.cmd", "kimi.exe"),
    # GLM Coding Plan IS Claude Code — Z.ai ships no binary of its own
    # (``dodaios.workspace.agents``), so its seat stands on Claude Code's.
    "glm-cli": ("claude", "claude.cmd", "claude.exe"),
    "dsh-cli": ("dsh", "dsh.cmd", "dsh.exe"),
    # Documented command is ``agent``; the Windows installer also drops
    # ``cursor-agent`` so the generic name does not collide with another
    # product. Prefer the unambiguous name when both are present.
    "cursor-cli": (
        "cursor-agent",
        "cursor-agent.exe",
        "agent",
        "agent.exe",
        "agent.cmd",
    ),
}


def _which(*names: str) -> str | None:
    if _REMOTE_PLANNING.get():
        return names[0] if names else None
    # The well-known install dirs a GUI-launched process does not inherit
    # (``~/.local/bin``, ``~/.grok/bin``, npm's prefix) — best-effort, and the
    # same augmentation a pane runs before it resolves its CLI.
    try:
        from dodaios.core.path_augment import ensure_cli_paths

        ensure_cli_paths()
    except Exception:  # noqa: BLE001, S110 — PATH augmentation is best-effort
        pass
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def cli_installed(runner: str) -> bool:
    """Whether ``runner``'s binary resolves from here (False for an unknown runner)."""
    if runner == "cursor-cli":
        from dodaios.workspace.cursor_cli import resolve_cursor_binary

        return resolve_cursor_binary() is not None
    return _which(*CLI_BINARIES.get(runner, ())) is not None


def _is_batch(binary: str) -> bool:
    return binary.lower().endswith((".cmd", ".bat"))


def _behind_shim(binary: str, agent: str) -> list[str]:
    """``binary``, or what its Windows ``.cmd`` shim would have launched.

    These CLIs take the prompt on argv, and through an npm shim argv passes
    ``cmd.exe``: a line break ends the command there, so a multi-line message
    reached the agent cut after its first line. The package layout the
    workspace registry declares (``WinShim``) launches the real program
    instead; an install laid out differently keeps the shim, and
    :func:`_argv_prompt` keeps the whole message on one line for it.
    """
    if not _is_batch(binary):
        return [binary]
    try:
        from dodaios.workspace import agents as workspace_agents

        spec = workspace_agents.get_agent(agent)
        direct = workspace_agents.behind_win_shim(spec, binary) if spec is not None else None
    except Exception:  # noqa: BLE001 — the shim still runs; only line breaks are at risk
        log.warning("agent chat: could not look behind the %s shim", agent, exc_info=True)
        direct = None
    return list(direct) if direct else [binary]


def _json_flag_value(prefix: list[str], payload: str) -> str:
    """``payload`` as a flag value that survives ``prefix``.

    Claude Code reads ``--settings`` and ``--mcp-config`` as inline JSON or as
    a file path. Behind an npm ``.cmd`` shim the line is re-parsed by
    ``cmd.exe``, which does not know the ``\\"`` escape ``list2cmdline`` writes:
    a ``|`` inside the JSON (a hook matcher such as ``Bash|Read``) then ends
    the command and ``cmd`` tries to run ``Read``. The JSON goes into a file
    named by its content (one file per distinct payload, rewritten never) and
    the path travels instead.
    """
    if not (prefix and _is_batch(prefix[0])):
        return payload
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    try:
        # Private per user: the file is handed to the CLI as its settings, so
        # nobody else may be able to put one there (the temp directory is
        # shared on Linux).
        from dodaios.core.private_tmp import private_temp_folder

        path = private_temp_folder("dodaios-claude-flags") / f"{digest}.json"
        if not path.is_file():
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
        return str(path)
    except OSError:
        log.warning("agent chat: could not write the flag file; passing JSON inline", exc_info=True)
        return payload


def _argv_prompt(prefix: list[str], prompt: str) -> str:
    """The prompt as one argv value that survives ``prefix``.

    A batch file still in front (an unknown install layout) would drop every
    line after the first, so the lines are joined with spaces instead: the
    agent loses the layout, never the words.
    """
    if prefix and _is_batch(prefix[0]):
        return " ".join(line.strip() for line in prompt.splitlines() if line.strip())
    return prompt


#: The subscription seat the CURRENT turn runs on, when its session names one
#: (an agent-society member pinned to a specific account). Empty = the
#: platform's active account, exactly as before the society existed.
ACCOUNT_OVERRIDE: ContextVar[str] = ContextVar("agent_chat.account_override", default="")


_CATALOG_IGNORE_CONFIG: ContextVar[bool] = ContextVar("cli_catalog.ignore_config", default=False)

#: Set while a turn is planned for ANOTHER computer (a society agent placed on
#: a VPS): binary lookups answer the bare name, since the CLI is found on the
#: remote PATH, not this one (``dodaios.agent_chat.remote_cli``).
_REMOTE_PLANNING: ContextVar[bool] = ContextVar("agent_chat.remote_planning", default=False)

_CATALOG_CWD: ContextVar[Path | None] = ContextVar("cli_catalog.cwd", default=None)

_ACCOUNT_ENVS: ContextVar[dict[str, dict[str, str]] | None] = ContextVar(
    "cli_catalog.envs", default=None
)

_PREPARED_MODELS: ContextVar[dict[str, list[dict[str, Any]] | None] | None] = ContextVar(
    "cli_catalog.models", default=None
)

#: platform -> the seat the CURRENT turn's CLI was started on. Set by
#: :func:`run_cli_turn`, filled by :func:`_account_env`; a refused turn reads
#: it to know which seat ran out (``_continue_on_next_seat``).
_TURN_SEATS: ContextVar[dict[str, str] | None] = ContextVar("agent_chat.turn_seats", default=None)


@contextmanager
def cli_catalog_scope(
    *, account_id: str | None = None, cwd: Path | None = None, ignore_user_config: bool = False
):
    """One request/turn uses one account environment for discovery and spawning."""
    account_token = ACCOUNT_OVERRIDE.set(account_id) if account_id is not None else None
    config_token = _CATALOG_IGNORE_CONFIG.set(ignore_user_config)
    cwd_token = _CATALOG_CWD.set(cwd)
    env_token = _ACCOUNT_ENVS.set({})
    model_token = _PREPARED_MODELS.set({})
    try:
        yield
    finally:
        _PREPARED_MODELS.reset(model_token)
        _ACCOUNT_ENVS.reset(env_token)
        _CATALOG_CWD.reset(cwd_token)
        _CATALOG_IGNORE_CONFIG.reset(config_token)
        if account_token is not None:
            ACCOUNT_OVERRIDE.reset(account_token)


def _catalog_cwd() -> Path:
    return _CATALOG_CWD.get() or Path.home()


def _remember_models(runner: str, rows: list[dict[str, Any]] | None) -> None:
    prepared = _PREPARED_MODELS.get()
    if prepared is not None:
        prepared[runner] = rows


def _login_id(account_id: str) -> str:
    """The login an account id names; ``""`` (the active one) for a reserved
    access value (``catalog.ACCESS_ACCOUNTS``), which names no login."""
    from dodaios.agent_chat.catalog import ACCESS_ACCOUNTS

    return "" if account_id in ACCESS_ACCOUNTS else account_id


#: Sessions whose CLI must start without these environment variables
#: (``drop_child_env``). In memory: a run that outlives the app keeps the
#: environment it was spawned with in the turn host.
_CHILD_ENV_DROPS: dict[str, frozenset[str]] = {}


def drop_child_env(session_id: str, names: Iterable[str]) -> None:
    """Spawn this session's CLI turns without ``names`` in their environment.

    For background work on a subscription (the self-building loop's coding
    runs): a key variable in the app's environment would make the CLI bill the
    key instead of the plan it is signed in with. Only the child's environment
    changes; the app's own is never touched.
    """
    cleaned = frozenset(str(name) for name in names if str(name).strip())
    if cleaned:
        _CHILD_ENV_DROPS[session_id] = cleaned


def release_child_env(session_id: str) -> None:
    _CHILD_ENV_DROPS.pop(session_id, None)


def apply_child_env_drops(session_id: str, env: dict[str, str] | None) -> None:
    """Remove the variables :func:`drop_child_env` named for ``session_id`` from ``env``."""
    names = _CHILD_ENV_DROPS.get(session_id)
    if not names or env is None:
        return
    upper = {name.upper() for name in names}
    for key in [key for key in env if key.upper() in upper]:
        env.pop(key, None)


def _account_env(platform: str) -> dict[str, str]:
    """The child environment for the subscription seat of ``platform`` — the
    turn's pinned account when its session names one, else the active one."""
    snapshot = _ACCOUNT_ENVS.get()
    if snapshot is not None and platform in snapshot:
        return dict(snapshot[platform])
    pinned_platform: str | None = None
    try:
        from dodaios import agent_accounts

        requested = _login_id(ACCOUNT_OVERRIDE.get())
        pinned = agent_accounts.resolve(requested or None)
        if requested and pinned is None:
            raise CliUnavailable(
                "The selected subscription account no longer exists. Choose an account and retry."
            )
        pinned_platform = pinned.platform if pinned is not None else None
        if pinned is not None and pinned.platform == platform:
            account = pinned
        else:
            account = agent_accounts.active_account(platform)  # type: ignore[arg-type]
        account = _seat_with_budget(platform, account)
        _note_turn_seat(platform, account.id)
        _share_user_setup(platform, account.id)
        env = agent_accounts.spawn_env(platform, account.id, base=os.environ)  # type: ignore[arg-type]
    except CliUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — unsupported platforms use native credentials
        if _login_id(ACCOUNT_OVERRIDE.get()) and pinned_platform in (None, platform):
            raise CliUnavailable("The selected subscription account could not be loaded.") from exc
        log.debug("CLI account layer unavailable for %s (%s)", platform, type(exc).__name__)
        env = dict(os.environ)
    env = _without_parent_session(env)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if snapshot is not None:
        snapshot[platform] = dict(env)
    return env


def _without_parent_session(env: dict[str, str]) -> dict[str, str]:
    """``env`` minus the markers of the agent session this app was started from.

    The same list a grid pane drops: left in, the CLI runs as a CHILD session
    (no saved transcript, so nothing to resume) and inherits the parent's
    effort and sandbox state.
    """
    from dodaios.agentic_ide.session import PARENT_AGENT_SESSION_VARS

    return {k: v for k, v in env.items() if k not in PARENT_AGENT_SESSION_VARS}


def _share_user_setup(platform: str, account_id: str) -> None:
    """Give a redirected account seat the user's own CLI setup, as a grid pane has.

    Skills, plugins, hooks, global instructions and the default operating mode
    live in the config directory the seat redirects; without this a thread on
    an added account ran a stripped CLI. Idempotent, a no-op for the built-in
    login, and never fatal.
    """
    try:
        from dodaios import agent_accounts, agent_config_parity

        report = agent_config_parity.ensure_parity(platform, account_id)  # type: ignore[arg-type]
        mode_file = agent_accounts.mode_file_name(platform)  # type: ignore[arg-type]
        if report.shared.get(str(mode_file)) not in {"mirrored", "current"}:
            agent_accounts.inherit_default_mode(platform, account_id)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 — parity is a convenience, never a gate
        log.debug("CLI setup sharing failed for %s (%s)", platform, type(exc).__name__)


def _seat_with_budget(platform: str, account: Any) -> Any:
    """``account``, or the active seat when ``account`` ran out of its plan.

    A thread pinned to a seat that refused for its usage limit would fail
    every turn until that seat refills; with automatic switching on, the turn
    runs on the seat the rest of the work already moved to
    (:mod:`dodaios.agentic_ide.seat_switch`). Its conversation follows it
    (``_carry_thread_conversation``).
    """
    try:
        from dodaios import agent_accounts
        from dodaios.agentic_ide import seat_switch

        replacement = seat_switch.preferred_seat(platform, account.id)
        if replacement is None:
            return account
        return agent_accounts.resolve(replacement) or account
    except Exception as exc:  # noqa: BLE001 - the pinned seat is still a valid answer
        log.debug("Seat failover unavailable for %s (%s)", platform, type(exc).__name__)
        return account


def _note_turn_seat(platform: str, account_id: str) -> None:
    """Remember the seat this turn runs on, and let the seat watch see it."""
    seats = _TURN_SEATS.get()
    if seats is None:  # model discovery, not a turn
        return
    seats[platform] = account_id
    try:
        from dodaios.agentic_ide import seat_switch

        seat_switch.note_in_use(platform, account_id)
    except Exception as exc:  # noqa: BLE001 - watching a seat is additive
        log.debug("Seat watch unavailable for %s (%s)", platform, type(exc).__name__)


def _is_usage_limit(error: str | None) -> bool:
    """Whether a failed turn's error says the seat's plan is used up."""
    if not error:
        return False
    from dodaios.brain import seat_health

    return seat_health.classify_seat_failure(error) == seat_health.CLASS_QUOTA


#: Runner -> (account platform, resume kind) for the CLIs whose conversations
#: can follow a seat switch (:mod:`dodaios.agentic_ide.seat_handoff`).
_SEAT_CONVERSATIONS: dict[str, tuple[str, str]] = {
    "claude-cli": ("claude", "claude_session"),
    "codex-cli": ("codex", "codex_rollout"),
    "grok-cli": ("grok-build", "grok_session"),
}


#: (runner, conversation id) -> the seat dir its last turn ran on. A thread
#: whose seat did not change since needs no search across the other seats —
#: for Codex that search is a sweep of every rollout folder.
_CARRIED_HOMES: dict[tuple[str, str], str] = {}


def _carry_thread_conversation(runner: str, resume: str | None, env: dict[str, str]) -> None:
    """Make a resumed thread find its conversation on the seat it runs on now.

    Each seat keeps its own history, so after a switch ``--resume <id>`` on
    the new seat would answer "no conversation found" and the thread would
    lose everything it knew. The newest copy across the CLI's seats is
    carried into the seat this turn runs on. Filesystem work: off the loop.
    """
    pair = _SEAT_CONVERSATIONS.get(runner)
    if resume and resume.startswith("fork:"):
        # A pending fork reads the source conversation on this seat.
        resume = resume[len("fork:") :]
    if not resume or pair is None:
        return
    platform, kind = pair
    try:
        from dodaios import agent_accounts
        from dodaios.agentic_ide import seat_handoff

        if platform not in agent_accounts.platforms():
            return
        variable = agent_accounts.env_var(platform)
        raw = env.get(variable or "", "").strip()
        home = Path(raw).expanduser() if raw else agent_accounts.native_dir(platform)
        key = (runner, resume)
        if _CARRIED_HOMES.get(key) == os.path.normcase(str(home)):
            return
        homes = [account.config_dir for account in agent_accounts.list_accounts(platform)]
        if seat_handoff.carry_conversation(kind, resume, home, homes):
            if len(_CARRIED_HOMES) > 512:
                _CARRIED_HOMES.clear()
            _CARRIED_HOMES[key] = os.path.normcase(str(home))
    except Exception as exc:  # noqa: BLE001 - a fresh start is the honest fallback
        log.warning("Conversation could not follow the seat for %s: %s", runner, exc)


def _registry_env(agent: str, base: dict[str, str]) -> dict[str, str]:
    """``base`` with the Agentic IDE registry's per-CLI environment on top.

    The same overlay a pane of ``agent`` gets (``dodaios.agentic_ide.session.
    agent_spawn_overlay``): the entry's fixed variables — an auto-updater
    switched off so the binary is not swapped under a running turn — and, for
    an entry whose environment is user configuration, its factory's answer.
    A factory that answers ``None`` says the CLI is not configured (GLM
    without a Z.ai key), and that stops the turn here rather than letting
    Claude Code answer from — and bill — the wrong vendor. An empty value
    removes the variable from the child, as it does for a pane.
    """
    env = _without_parent_session(dict(base))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        from dodaios.workspace import agents as workspace_agents

        spec = workspace_agents.get_agent(agent)
    except Exception:  # noqa: BLE001 — no registry, no overlay
        spec = None
    if spec is None:
        return env
    overlay = dict(spec.spawn_env)
    if spec.spawn_env_factory is not None:
        resolved = spec.spawn_env_factory()
        if resolved is None:
            raise CliUnavailable(
                f"{spec.display_name} is not configured yet — add its API key on "
                "the API Keys page, then send again."
            )
        overlay.update(resolved)
    for key, value in overlay.items():
        if value:
            env[key] = value
        else:
            env.pop(key, None)
    return env


# ------------------------------------------------------------ argv per CLI

#: Prepended to the prompt for a runner without a plan mode of its own: the
#: sandbox already forbids changes; this tells the model what to do instead.
_PLAN_PREAMBLE: Final[str] = (
    "PLAN MODE: do not change any files or run commands that write. Investigate "
    "(read, search, list), then answer with a concrete, numbered plan of the "
    "changes you would make — files, functions, the order — and the open "
    "questions. The person will switch to Build mode to have it carried out.\n\n"
)


@dataclass(slots=True)
class CliPlan:
    argv: list[str]
    env: dict[str, str]
    stdin_text: str | None
    shape: str  # a key of ``_SHAPES``: claude | codex | agy | opencode | kimi | text | cursor
    #: Vendor session id we chose up front (claude/grok --session-id), or None
    #: when the CLI assigns one (agy, codex) and we read it from the stream.
    vendor_session: str | None
    #: Keep stdin open after the prompt: the CLI talks back on it (Claude
    #: Code's control protocol — permission prompts answered from the chat).
    #: The pump closes stdin once the turn's ``result`` line arrived.
    keep_stdin: bool = False
    #: The control-protocol handshake, written before the prompt. Claude Code
    #: only asks about tool calls once a client has announced itself this way.
    control_init: str | None = None
    #: For a CLI whose stream never names its session: called once the turn
    #: is over with the working folder and the wall-clock start, and answers
    #: the id the CLI's own store gave the conversation (or None).
    discover: Callable[[Path, float], str | None] | None = None
    #: An Agent Client Protocol turn (Hermes, OpenClaw — ``runner_acp``): the
    #: pump hands every stdout object to it instead of a ``_SHAPES`` translator,
    #: and it writes its own requests on stdin.
    acp: Any | None = None
    #: Called once the process is gone (a runtime releasing its Gateway).
    after_turn: Callable[[], None] | None = None
    #: The local gateway knows failures that a runtime may render as prose.
    provider_failure: Future[str] | None = None
    #: Why a turn that ended without an answer failed, from the runtime's own
    #: log (``RuntimeLaunch.failure_probe``), given the turn's wall-clock start.
    failure_probe: Callable[[float], str] | None = None
    #: A process that is already running (an agent runtime's warm process,
    #: ``agent_runtimes.warm.Lease``): driven instead of spawning ``argv``.
    #: Its owner contains it, so the turn adds no process tree of its own.
    proc: Any | None = None


def _resolved_cwd(raw: Path | str | None) -> Path:
    """Absolute working folder for a CLI spawn.

    agy refuses a relative ``--add-dir`` (``path is not absolute``) and a
    society session used to store ``data\\society\\<id>\\workspace`` relative
    to the app cwd. Resolve here so every planner sees the same folder.
    """
    path = Path(raw or Path.home()).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    return path


#: society session id -> (digest of the memory refresh last sent, resumed turns since).
#: In-process only: a restart sends the refresh once more.
_REFRESH_SENT: dict[str, tuple[str, int]] = {}

#: A vendor may compact its own history; resend an unchanged refresh this often.
_REFRESH_EVERY: Final[int] = 20


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _with_identity(
    prompt: str,
    identity: dodaios_harness.Identity | None,
    resume: str | None,
    *,
    compact: bool = False,
) -> str:
    """The prompt with the identity in front of it — on a fresh conversation.

    A resumed conversation carries the identity from its first turn; repeating
    it every turn would grow the vendor's history for nothing. A society seat
    gets its memory refresh only when it changed (or every ``_REFRESH_EVERY``
    turns) and its live state lines on every turn. The blocks are fenced so the
    model can tell the head from the person's words.
    """
    if identity is None:
        return prompt
    society = identity.session_id.startswith("society:")
    if not resume:
        if society:
            refresh = dodaios_harness.society_memory_refresh(identity.text, compact=compact)
            _REFRESH_SENT[identity.session_id] = (_digest(refresh), 0)
        text = identity.compact if compact else identity.text
        return f"<jarvis_identity>\n{text}\n</jarvis_identity>\n\n{prompt}"
    if not society:
        return identity.catchup + prompt if identity.catchup else prompt
    refresh = dodaios_harness.society_memory_refresh(identity.text, compact=compact)
    digest = _digest(refresh)
    sent, turns = _REFRESH_SENT.get(identity.session_id, ("", 0))
    if sent == digest and turns + 1 < _REFRESH_EVERY:
        head, turns = "", turns + 1
    else:
        head, turns = refresh, 0
    _REFRESH_SENT[identity.session_id] = (digest, turns)
    state = dodaios_harness.society_turn_state(identity.text)
    if state:
        head += f"<jarvis_turn_context>\n{state}\n</jarvis_turn_context>\n\n"
    return head + prompt


#: The runners that are Claude Code under the hood, and so take its identity
#: file and its control protocol.
_CLAUDE_CODE_RUNNERS: Final[frozenset[str]] = frozenset({"claude-cli", "glm-cli"})


def _cli_tool_summary(name: str, args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    for key in (
        "command",
        "file_path",
        "filePath",
        "target_file",
        "path",
        "pattern",
        "query",
        "url",
        "description",
    ):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().splitlines()[0][:200]
    return ""


def run_tag(proc: Any) -> str:
    """A short tag of one CLI process, the same when the app reattaches to it.

    A hosted CLI keeps its host id across an app restart, a child process
    its pid; the replayed lines then rebuild the very ids the timeline holds.
    """
    ident = str(getattr(proc, "host_id", "") or getattr(proc, "pid", "") or "")
    if not ident:
        ident = uuid.uuid4().hex
    return hashlib.sha1(ident.encode("utf-8"), usedforsecurity=False).hexdigest()[:6]
