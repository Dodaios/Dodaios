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

import base64
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

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


# ------------------------------------------------------------------ pictures
#
# A plain chat hands an attached picture to the model it is talking to, not
# only a description of it. The description comes from a separate vision
# provider, and when that one has no quota left the picture would reach the
# chat as a filename. The chat's own model sees it instead: Claude Code as an
# image block in its stream-json message, Codex through ``--image``, an API
# seat as an image on the user message.

#: Pictures every one of those accepts inline. Anything else stays a file.
INLINE_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
#: More than this in one message is a folder, not a question about a picture.
MAX_IMAGES = 8
#: Per picture, under the smallest provider limit; larger ones are scaled down.
MAX_IMAGE_BYTES = 3_500_000

#: Told to the model when the pictures ride along, so a note saying a picture
#: "could not be described" does not read as "you cannot see it".
IMAGES_NOTE = (
    "The images among these attachments are also attached to this message "
    "itself; look at them directly."
)


def image_paths(cwd: str | Path, attachments: list[Any] | None) -> list[Path]:
    """The attached pictures as files inside ``cwd``, at most :data:`MAX_IMAGES`.

    The references are request data, so each one must resolve INSIDE the
    chat's folder and name a picture type; anything else is left out.
    """
    from dodaios.agentic_ide import drops

    if not cwd:
        return []
    out: list[Path] = []
    for item in attachments or []:
        if getattr(item, "kind", "") != "image":
            continue
        relative = drops.dereference(str(getattr(item, "reference", "") or ""))
        if not relative:
            continue
        inside = drops.within_workspace(str(Path(cwd) / relative), cwd)
        if inside is None:
            continue
        path = Path(cwd) / inside
        if path.suffix.lower() not in INLINE_TYPES or not path.is_file() or path in out:
            continue
        out.append(path)
        if len(out) >= MAX_IMAGES:
            break
    return out


def encoded(path: str | Path) -> tuple[str, str] | None:
    """``(mime, base64)`` of one picture, scaled under the budget; None if unreadable."""
    from dodaios.vision.image_budget import cap_image_b64

    source = Path(path)
    mime = INLINE_TYPES.get(source.suffix.lower())
    if mime is None:
        return None
    try:
        data = source.read_bytes()
    except OSError as exc:
        # The picture still goes as its description; only the inline copy is skipped.
        log.info("plain chat: %s not attached inline (%s)", source.name, exc)
        return None
    return cap_image_b64(mime, base64.b64encode(data).decode("ascii"), MAX_IMAGE_BYTES)


def claude_message_with_images(stdin_text: str, images: list[tuple[str, str]]) -> str:
    """Claude Code's stream-json user message with the pictures in front of the text."""
    if not images:
        return stdin_text
    message = json.loads(stdin_text)
    content = message["message"]["content"]
    blocks: list[dict[str, Any]] = [
        {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
        for mime, data in images
    ]
    if isinstance(content, list):
        blocks += content
    else:
        blocks.append({"type": "text", "text": str(content)})
    message["message"]["content"] = blocks
    return json.dumps(message, ensure_ascii=False) + "\n"


def attach_images(plan: Any, runner: str, paths: list[Path]) -> bool:
    """Hand ``paths`` to a planned CLI turn natively. False when the runner cannot take them."""
    if not paths:
        return False
    if runner == "claude-cli" and plan.shape == "claude" and plan.stdin_text:
        images = [pair for pair in (encoded(path) for path in paths) if pair is not None]
        if not images:
            return False
        plan.stdin_text = claude_message_with_images(plan.stdin_text, images)
        return True
    if runner == "codex-cli" and "-" in plan.argv:
        # In front of the stdin prompt marker; flags added after planning (the
        # tool switches) may follow it. ``--image=`` takes exactly one value,
        # where ``--image <FILE>...`` would swallow the ``-`` as a picture.
        at = len(plan.argv) - 1 - plan.argv[::-1].index("-")
        plan.argv[at:at] = [f"--image={path}" for path in paths]
        return True
    return False


__all__ = [
    "IMAGES_NOTE",
    "attach_images",
    "claude_message_with_images",
    "cli_prompt",
    "encoded",
    "image_paths",
    "opening",
    "permission_mode",
    "transcript",
]
