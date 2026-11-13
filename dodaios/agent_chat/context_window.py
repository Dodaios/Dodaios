"""How full a coding thread's context window is, and what fills it.

Three sources, cheapest first:

* **Live** — every Claude Code message reports its usage. The tokens the model
  read for the newest message of the main agent (fresh input, cache reads,
  cache writes) plus what it wrote are the conversation as the next message
  will see it. ``runner_cli`` sends that number with each ``usage_delta`` and
  stores it once per turn as a ``context_usage`` event, with the window size
  the turn's ``result`` line names (``modelUsage[model].contextWindow``).
* **Record** — a thread that ran before this existed, or whose last turn was
  cut off, still has the CLI's own session file; its last main-chain
  ``assistant`` row carries the same usage (:func:`read_recorded`).
* **Breakdown** — Claude Code's local ``/context`` command splits the window
  into system prompt, tools, skills, memory files, messages, free space and
  the auto-compact buffer. It runs headless against a FORK of the session
  that is never written (``--fork-session --no-session-persistence``): no
  model call, no change to the thread (:func:`probe_breakdown`).

Only Claude Code is read here; other CLIs publish no window size, and an
empty spot is more honest than a guessed number.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

#: The usage fields that are the context the model read for one message.
_INPUT_KEYS: Final[tuple[str, ...]] = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

#: Window sizes the CLI reported, by model id (``modelUsage[m].contextWindow``).
#: Learned from every turn's ``result``; a breakdown probe teaches it too.
_WINDOWS: dict[str, int] = {}

#: How far back from the end of a session file the record reader looks.
_TAIL_BYTES: Final = 2 * 1024 * 1024
#: The ``/context`` probe gives up after this long.
PROBE_TIMEOUT_S: Final = 45.0
#: A breakdown stays good while the session file is unchanged, at most this long.
_PROBE_CACHE_S: Final = 300.0


def tokens_in_context(usage: dict[str, Any]) -> int:
    """The conversation as the model saw it for one message, plus its answer."""
    total = 0
    for key in (*_INPUT_KEYS, "output_tokens"):
        value = usage.get(key)
        if isinstance(value, int | float) and value > 0:
            total += int(value)
    return total


def learn_window(model: str, window: int) -> None:
    if model and window > 0:
        _WINDOWS[model] = int(window)


def known_window(model: str) -> int | None:
    return _WINDOWS.get(model) if model else None


def window_from_result(model_usage: Any, model: str) -> tuple[str, int | None]:
    """The main model's window from a ``result`` line's ``modelUsage``.

    ``modelUsage`` lists every model the turn used — the main one and any
    helper (a sub-agent's, a summary's). The main agent's is the one its own
    messages named; with no name, a single entry is taken as it.
    """
    if not isinstance(model_usage, dict) or not model_usage:
        return model, None
    entry = model_usage.get(model) if model else None
    if entry is None and len(model_usage) == 1:
        model, entry = next(iter(model_usage.items()))
    if not isinstance(entry, dict):
        return model, None
    window = entry.get("contextWindow")
    if isinstance(window, int | float) and window > 0:
        learn_window(str(model), int(window))
        return str(model), int(window)
    return model, None


def reading(used: int, model: str, window: int | None = None) -> dict[str, Any]:
    """The payload the chat's context ring reads."""
    return {"used": int(used), "window": window or known_window(model), "model": model}


# ----------------------------------------------------------- session files


def _claude_homes(account_id: str) -> list[tuple[Path, str | None]]:
    """Every Claude config dir a thread's conversation may live in, with its seat.

    The thread's own seat first, then every other seat (a turn may have moved
    on to the next subscription), then the CLI's plain default.
    """
    homes: list[tuple[Path, str | None]] = []
    try:
        from dodaios import agent_accounts

        accounts = agent_accounts.list_accounts("claude")
        own = [a for a in accounts if a.id == account_id]
        for account in (*own, *[a for a in accounts if a.id != account_id]):
            homes.append((Path(account.config_dir), account.id))
    except Exception as exc:  # noqa: BLE001 - seats are optional, the default dir is not
        log.debug("Claude seats unavailable (%s)", type(exc).__name__)
    default = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    if all(home != default for home, _ in homes):
        homes.append((default, None))
    return homes


def find_session_file(vendor_session: str, account_id: str = "") -> tuple[Path, str | None] | None:
    """The CLI's record of ``vendor_session`` and the seat it lives under."""
    if not vendor_session or "/" in vendor_session or "\\" in vendor_session:
        return None
    for home, account in _claude_homes(account_id):
        projects = home / "projects"
        if not projects.is_dir():
            continue
        found = next(projects.glob(f"*/{vendor_session}.jsonl"), None)
        if found is not None:
            return found, account
    return None


def _tail_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _TAIL_BYTES))
            data = handle.read()
    except OSError:  # unreadable record: read as empty
        return []
    rows: list[dict[str, Any]] = []
    for line in data.splitlines()[1 if len(data) >= _TAIL_BYTES else 0 :]:
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):  # a half-written last line: skipped
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def read_recorded(path: Path) -> dict[str, Any] | None:
    """The last main-agent message's context, from the CLI's session file.

    A compaction after that message makes the number stale (the next message
    starts from the summary), so a ``compact_boundary`` newer than every
    message answers nothing rather than a full ring that is no longer true.
    """
    for row in reversed(_tail_rows(path)):
        if row.get("type") == "system" and row.get("subtype") == "compact_boundary":
            return None
        if row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        model = str(message.get("model") or "")
        usage = message.get("usage")
        if model.startswith("<") or not isinstance(usage, dict):
            continue  # "<synthetic>": the CLI's own notice, no model call
        used = tokens_in_context(usage)
        if used > 0:
            return reading(used, model)
    return None


# ------------------------------------------------------- the /context probe

_SIZE = re.compile(r"^\s*([\d.,]+)\s*([km]?)\s*$", re.IGNORECASE)
_TOTAL = re.compile(r"\*\*Tokens:\*\*\s*([\d.,]+\s*[km]?)\s*/\s*([\d.,]+\s*[km]?)", re.IGNORECASE)
_MODEL = re.compile(r"\*\*Model:\*\*\s*([^\s*]+)")


def parse_size(text: str) -> int | None:
    """``"14.9k"`` -> 14900, ``"1m"`` -> 1000000, ``"10"`` -> 10."""
    match = _SIZE.match(text.replace("~", ""))
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:  # a cell that is no number: the row is skipped
        return None
    unit = match.group(2).lower()
    return int(round(value * (1000 if unit == "k" else 1_000_000 if unit == "m" else 1)))


#: ``/context``'s category names -> the keys the chat translates.
_CATEGORIES: Final[dict[str, str]] = {
    "system prompt": "system_prompt",
    "system tools": "system_tools",
    "system tools (deferred)": "deferred_tools",
    "mcp tools": "mcp_tools",
    "mcp tools (deferred)": "deferred_mcp_tools",
    "custom agents": "agents",
    "memory files": "memory",
    "skills": "skills",
    "messages": "messages",
    "free space": "free",
    "autocompact buffer": "autocompact",
}


@dataclass(slots=True)
class Breakdown:
    model: str = ""
    used: int | None = None
    window: int | None = None
    categories: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "used": self.used,
            "window": self.window,
            "categories": self.categories,
        }


def parse_breakdown(markdown: str) -> Breakdown | None:
    """Read ``/context``'s report: its totals and the category table.

    Only the first table (the categories) is read; the per-skill, per-tool and
    per-file tables after it are detail the ring does not show.
    """
    out = Breakdown()
    if match := _MODEL.search(markdown):
        out.model = match.group(1)
    if match := _TOTAL.search(markdown):
        out.used, out.window = parse_size(match.group(1)), parse_size(match.group(2))
    in_table = False
    for line in markdown.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|"):
            if in_table:
                break
            continue
        if len(cells) < 2 or cells[0].lower() == "category" or set(cells[0]) <= {"-", ":"}:
            in_table = in_table or cells[0].lower() == "category"
            continue
        if not in_table:
            continue
        tokens = parse_size(cells[1])
        if tokens is None:
            continue
        label = cells[0]
        out.categories.append(
            {"key": _CATEGORIES.get(label.lower(), "other"), "label": label, "tokens": tokens}
        )
    if not out.categories and out.used is None:
        return None
    if out.model and out.window:
        learn_window(out.model, out.window)
    return out


_probe_cache: dict[str, tuple[float, float, Breakdown]] = {}


def _probe_env(account: str | None) -> dict[str, str]:
    if account:
        try:
            from dodaios import agent_accounts

            return agent_accounts.spawn_env("claude", account)
        except Exception as exc:  # noqa: BLE001 - fall back to the plain login
            log.debug("Claude seat env unavailable (%s)", type(exc).__name__)
    return dict(os.environ)


async def probe_breakdown(
    *, vendor_session: str, cwd: str, model: str = "", account_id: str = ""
) -> Breakdown | None:
    """Ask Claude Code itself what fills the thread's window (``/context``).

    Runs on a fork the CLI never saves: the thread's record stays byte for
    byte the same, and no model is called. The answer is kept while the
    session file is unchanged, so hovering the ring twice runs it once.
    """
    from dodaios.agent_chat.runner_cli import CliUnavailable, claude_argv_prefix
    from dodaios.agent_chat.thread_sessions import split_fork

    resume_id, fork_source = split_fork(vendor_session)
    sid = fork_source or resume_id
    if not sid:
        return None
    found = await asyncio.to_thread(find_session_file, sid, account_id)
    folder = Path(cwd).expanduser() if cwd else None
    if found is None or folder is None or not folder.is_dir():
        return None
    path, account = found
    try:
        mtime = path.stat().st_mtime
    except OSError:  # the record vanished meanwhile: nothing to report
        return None
    cached = _probe_cache.get(sid)
    if cached and cached[0] == mtime and time.monotonic() - cached[1] < _PROBE_CACHE_S:
        return cached[2]
    try:
        argv = claude_argv_prefix()
    except CliUnavailable:  # no Claude Code here: the ring keeps its plain numbers
        return None
    argv += [
        "--print",
        "/context",
        "--output-format",
        "json",
        "--resume",
        sid,
        "--fork-session",
        "--no-session-persistence",
    ]
    if model:
        argv += ["--model", model]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(folder),
            env=_probe_env(account),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        log.info("context probe could not start (%s)", type(exc).__name__)
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        log.info("context probe timed out after %.0f s", PROBE_TIMEOUT_S)
        return None
    try:
        payload = json.loads(stdout.decode("utf-8", "replace"))
    except ValueError:  # an older CLI that prints no JSON: no breakdown
        return None
    if not isinstance(payload, dict) or payload.get("is_error"):
        return None
    breakdown = parse_breakdown(str(payload.get("result") or ""))
    if breakdown is not None:
        _probe_cache[sid] = (mtime, time.monotonic(), breakdown)
    return breakdown
