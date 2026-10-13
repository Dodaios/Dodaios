"""The Agentic IDE's side chat: what the model is told.

The side panel's Chat tab is a plain conversation beside the terminals: the
user picks a model, types, reads the answer. It is not a coding agent. The
model has no tools on any seat (``SurfaceKit.plain_chat``), so everything it
knows about the project is in the system prompt written here: who it is, how
to answer, and a short description of the workspace folder.

The chat is also where prompts for the terminals get drafted: any answer can
be sent to a terminal with one click. So the one piece of prompt-writing
doctrine the composer has, goal and not implementation, is stated here too,
imported so the two cannot drift.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from .folders import ProjectProfile, probe_project
from .prompt_blueprint import GOAL_NOT_IMPLEMENTATION_RULE

#: Room for the file map in the workspace notes.
_MAP_CHARS = 2400

_INSTRUCTIONS = f"""\
You are {{name}}, the chat in the side panel of the person's coding workspace. \
This is a plain conversation: you have no tools here, so you cannot open \
files, run commands or look anything up. When an answer would need that, say \
so in a sentence and answer from what you know and from the workspace notes \
below.

Answer the way a good colleague would: directly, in the language the person \
writes in, and as short as the question allows. Put code in fenced blocks \
with a language tag.

Coding agents run in the terminals next to this chat, and the person can send \
any of your answers to one of them with a click. When they ask you to write or \
improve a prompt for an agent, answer with the prompt alone, ready to send. \
{GOAL_NOT_IMPLEMENTATION_RULE} Keep everything the person asked for and add no \
requirement, step list or success criterion they did not state."""


def workspace_notes(folder: str, text: str, profile: ProjectProfile | None = None) -> str:
    """What the model is told about the workspace folder. Blocking.

    The folder's profile (branch, stack, top-level folders, the skills and
    subagents the repo defines) plus a map of the folders that fit ``text``,
    taken from the workspace's file index when it is already built. Never
    waits for a directory walk; an empty ``folder`` has no notes.
    """
    if not folder:
        return ""
    from .file_index import cached_index, prime_index

    profile = profile or probe_project(folder)
    if not profile.exists:
        return ""
    lines = profile.summary_lines()
    index = cached_index(folder)
    if index is None:
        # Built in the background for the next message.
        prime_index(folder)
    tree = index.render_map(text, max_chars=_MAP_CHARS) if index is not None else ""
    if tree:
        lines += ["", "Files that fit the message:", tree]
    return "\n".join(lines)


async def system_prompt(session: Any, user_text: str, assistant_name: str) -> str:
    """The side chat's whole system prompt for one turn.

    Written per turn, so the notes follow the folder the session points at and
    the file map follows the message. Unreadable notes cost the notes, never
    the turn.
    """
    prompt = _INSTRUCTIONS.format(name=assistant_name or "the assistant")
    folder = str(getattr(session, "cwd", "") or "")
    try:
        notes = await asyncio.to_thread(workspace_notes, folder, user_text)
    except Exception as exc:  # noqa: BLE001 - the notes are a help, never a requirement
        logger.info("Side chat: no workspace notes ({})", type(exc).__name__)
        notes = ""
    return f"{prompt}\n\nWORKSPACE\n{notes}" if notes else prompt


def opening_message(system: str, user_text: str) -> str:
    """A conversation's first message on a seat that takes no system prompt.

    A coding CLI run tool-free keeps its own system prompt, so the side chat's
    instructions travel at the head of the first message instead. The CLI then
    resumes its own conversation, which still holds them.
    """
    return f"<side_chat_instructions>\n{system}\n</side_chat_instructions>\n\n{user_text}"


__all__ = ["opening_message", "system_prompt", "workspace_notes"]
