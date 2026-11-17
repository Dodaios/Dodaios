"""The person's standing wishes for how Dodaios briefs its agents.

Dodaios writes the brief every coding agent works from. Without a wish the
brief lets the agent finish the job (``agent_brief.SHIP_DEFAULT``). A person
who wants it otherwise says so in the chat ("I want to approve every PR
myself", "write the prompts in English", "always with tests") or writes it in
Settings. The lead saves the list with the ``agent-briefs-set`` command
(``PUT /api/settings/agent-briefs``), and every brief after that follows it:
the line beside each lead message (``dodaios_harness.brief_line``), the lead's
system prompt (``BrainManager``), the voice composer and the live voice
backends all read the file fresh, so a change applies to the next brief
without a restart.

The wishes are the person's own words, one per line, in their language. They
win over the default; they do not lift ``agent_brief.REAL_LIMITS``.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Final

log = logging.getLogger(__name__)

WISHES_FILENAME: Final[str] = "agent_brief_wishes.md"

#: The wishes ride beside every lead message, so they stay a short list.
MAX_WISHES_CHARS: Final[int] = 2_000


def wishes_path() -> Path:
    """Where the wishes live: under ``DATA_DIR``, resolved at call time (tests redirect it)."""
    from dodaios.core import config as core_config

    return core_config.DATA_DIR / WISHES_FILENAME


def normalize(text: str) -> str:
    """The stored form: one wish per line, trimmed, without blank lines."""
    lines = (line.strip() for line in (text or "").replace("\r\n", "\n").split("\n"))
    return "\n".join(line for line in lines if line)


def read_wishes() -> str:
    """The stored wishes, ``""`` when there are none or the file cannot be read."""
    try:
        return normalize(wishes_path().read_text(encoding="utf-8"))
    except FileNotFoundError:  # no file means no wishes: the default applies
        return ""
    except (OSError, UnicodeDecodeError):
        log.warning("agent brief wishes: file not readable, briefs use the default", exc_info=True)
        return ""


def save_wishes(text: str) -> str:
    """Store ``text`` as the whole list (empty clears it) and return what is stored.

    Raises ``ValueError`` when the list is longer than ``MAX_WISHES_CHARS``.
    Written atomically, UTF-8 without a BOM.
    """
    body = normalize(text)
    if len(body) > MAX_WISHES_CHARS:
        raise ValueError(
            f"The wishes are {len(body)} characters long; keep them under {MAX_WISHES_CHARS}."
        )
    if not body:
        reset_wishes()
        return ""
    path = wishes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".brief_wishes.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:  # cleanup only; the original error is re-raised below
            pass
        raise
    return body


def reset_wishes() -> bool:
    """Remove the wishes; ``True`` when there were some."""
    try:
        wishes_path().unlink()
        return True
    except FileNotFoundError:  # already the default: nothing to remove
        return False


def _as_list(wishes: str) -> str:
    """The wishes as a list the model reads as separate items."""
    return "\n".join(
        line if line.startswith(("-", "*")) else f"- {line}" for line in wishes.split("\n")
    )


def wishes_line(wishes: str | None = None) -> str:
    """The wishes for a brief writer, ``""`` without any (read fresh when not given)."""
    text = read_wishes() if wishes is None else normalize(wishes)
    if not text:
        return ""
    return (
        "\nThe person's standing wishes for every brief, in their words; they win over the "
        "default rules for briefs and over anything older you remember about briefs:\n"
        + _as_list(text)
    )


def wishes_rule() -> str:
    """``wishes_line()`` for an instruction built once per session; never raises."""
    try:
        return wishes_line()
    except Exception:  # noqa: BLE001 - wishes never break an instruction build
        log.warning("agent brief wishes: unavailable, briefs use the default", exc_info=True)
        return ""


def prompt_block(wishes: str | None = None) -> str:
    """The system-prompt block for the lead, ``""`` without wishes."""
    text = read_wishes() if wishes is None else normalize(wishes)
    if not text:
        return ""
    return (
        "AGENT BRIEF WISHES\n"
        "How the person wants every brief you hand an agent, in their words. Follow them "
        "over the default in the hand-off tools' brief rule and over anything older you "
        "remember about briefs; they never lift the real limits named there. When the person "
        "changes them, save the whole new list with agent-briefs-set.\n" + _as_list(text)
    )


__all__ = [
    "MAX_WISHES_CHARS",
    "WISHES_FILENAME",
    "normalize",
    "prompt_block",
    "read_wishes",
    "reset_wishes",
    "save_wishes",
    "wishes_line",
    "wishes_path",
    "wishes_rule",
]
