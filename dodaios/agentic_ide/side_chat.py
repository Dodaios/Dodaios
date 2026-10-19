"""The Agentic IDE's side chat: what the model is told.

The side panel's Chat tab is a plain AI chat: the person picks a model, asks
anything, reads the answer. It is not a coding agent and knows nothing about
the workspace beside it. The model has no tools on any seat
(``SurfaceKit.plain_chat``), and this short system prompt is all it is given:
who it is and how to answer.
"""

from __future__ import annotations

from typing import Any

_INSTRUCTIONS = """\
You are {name}, an AI assistant in a chat. Reply in the person's language; \
Markdown is rendered. You have no tools in this chat: no web, no files, no \
code execution."""


async def system_prompt(_session: Any, _user_text: str, assistant_name: str) -> str:
    """The side chat's whole system prompt. The same for every turn and folder."""
    return _INSTRUCTIONS.format(name=assistant_name or "the assistant")


__all__ = ["system_prompt"]
