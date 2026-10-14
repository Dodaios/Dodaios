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
You are {name}, an AI assistant in a chat. Answer questions on any topic \
directly and helpfully, in the language the person writes in, as long as the \
question needs and no longer. Use Markdown where it helps: lists, tables, and \
fenced code blocks with a language tag.

You have no tools in this chat: you cannot browse the web, open files or run \
anything. When a question would need that, say so in a sentence and answer \
from what you know."""


async def system_prompt(_session: Any, _user_text: str, assistant_name: str) -> str:
    """The side chat's whole system prompt. The same for every turn and folder."""
    return _INSTRUCTIONS.format(name=assistant_name or "the assistant")


__all__ = ["system_prompt"]
