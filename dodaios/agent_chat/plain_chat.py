"""A plain chat on a coding CLI: how the conversation is opened.

A plain surface (``SurfaceKit.plain_chat``) has no tools on any seat. An API
seat takes the surface's system prompt as its system prompt. A coding CLI run
tool-free keeps its own, so the surface's instructions travel at the head of
the first message it is sent, and the CLI's own session carries them from
there.

"First message" means every time the CLI starts a conversation, not only the
chat's first turn: a session it can no longer resume (a folder that moved, a
pruned session, a seat that changed) starts fresh, and the fresh one gets the
instructions again together with what was said so far. Without that a chat
would lose its framing for good the first time a resume failed.
"""

from __future__ import annotations

from typing import Any

#: Room for what was said before, newest kept. A fresh CLI conversation needs
#: the thread of the chat, not every word of it.
TRANSCRIPT_CHARS = 8000

#: Where a tool-free CLI could still write, its sandbox is read-only as well.
#: Claude Code with no tools has no such path; Codex keeps its patch tool.
READ_ONLY_MODE: dict[str, str] = {"codex-cli": "read-only"}


def transcript(history: list[dict[str, Any]], *, max_chars: int = TRANSCRIPT_CHARS) -> str:
    """The chat so far as plain lines, bounded from the newest message back."""
    lines: list[str] = []
    for event in history:
        text = str((event.get("payload") or {}).get("text") or "").strip()
        if not text:
            continue
        if event.get("kind") == "user_message":
            lines.append(f"User: {text}")
        elif event.get("kind") == "assistant_text":
            lines.append(f"Assistant: {text}")
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        if kept and used + len(line) > max_chars:
            break
        kept.append(line[-max_chars:])
        used += len(line)
    return "\n\n".join(reversed(kept))


def opening(system: str, history: list[dict[str, Any]], user_text: str) -> str:
    """The message that starts a CLI conversation for a plain chat."""
    parts = [f"<chat_instructions>\n{system}\n</chat_instructions>"]
    earlier = transcript(history)
    if earlier:
        parts.append(f"<earlier_conversation>\n{earlier}\n</earlier_conversation>")
    parts.append(user_text)
    return "\n\n".join(parts)


def cli_prompt(handle: Any, user_text: str, resume: str | None) -> str:
    """What a CLI is sent for this turn: the opening when it starts fresh."""
    system = str(getattr(handle, "plain_system", "") or "")
    if not system or resume:
        return user_text
    return opening(system, list(getattr(handle, "history", None) or []), user_text)


def permission_mode(handle: Any, runner: str, mode: str) -> str:
    """The permission mode a plain chat's CLI turn is planned with."""
    if not getattr(handle, "plain_system", ""):
        return mode
    return READ_ONLY_MODE.get(runner, mode)


__all__ = ["cli_prompt", "opening", "permission_mode", "transcript"]
