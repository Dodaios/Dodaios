"""Files dropped, pasted or picked into a chat composer.

The typed chats — the front page and the Agentic IDE's chat mode — take a
sentence and nothing else. Someone with a screenshot of a broken layout has to
describe it in words, which is the one thing a screenshot exists to avoid. The
IDE's TERMINAL panes have taken dropped files since 2026-08 (``drops`` +
``drop_analysis``); the chats were never wired to any of it, so a drop landed
on a bare ``<textarea>`` and the browser navigated away to the file.

This module is that wiring, and it is deliberately thin: everything hard was
already solved one layer down and is reused rather than rewritten.

* :mod:`dodaios.agentic_ide.drops` writes the bytes into the chat's own working
  directory (``.jarvis/drops``, self-ignoring) and hands back a reference the
  agent can open.
* :mod:`dodaios.agentic_ide.drop_analysis` has a vision-capable model describe
  an image and extracts a document's text.
* :func:`dodaios.agentic_ide.prompt_blueprint.attachment_block` lays the result
  out for whatever answers the turn.

Why the description travels with the message rather than the file alone: a
chat can be answered by a coding CLI, by a provider's own API loop, or by
Jarvis' brain, and several of those cannot open an image at all. Sending only
a path means the person drops a picture, types "what is wrong here", and the
model receives a filename and a pronoun. The description is what makes the
gesture work on every seat instead of the maintainer's.

Import-light on purpose (AP-26): the heavy halves are imported inside the
functions, so a boot that never sees an attachment pays nothing for this.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dodaios.agentic_ide.drops import DropSource

log = logging.getLogger(__name__)

__all__ = [
    "AttachmentError",
    "compose",
    "ingest",
    "to_analysis",
]

class AttachmentError(RuntimeError):
    """The attach carried nothing usable, or the copies could not be written."""


#: How far back a Dodaios chat's earlier pictures stay forwardable.
_EARLIER_PICTURES_MS = 24 * 3600 * 1000
#: At most this many earlier pictures are re-registered per message.
_EARLIER_PICTURES_MAX = 20
#: How many of a conversation's newest events are searched for earlier pictures.
EARLIER_PICTURES_EVENTS = 400


def _upload_path(root: Path, reference: str) -> Path:
    """The file a chat attachment reference names, refused unless inside ``root``."""
    from dodaios.agentic_ide.drops import dereference
    from dodaios.core.image_references import ImageReferenceError

    raw = dereference(reference)
    path = (root / raw).resolve()
    if not raw or not path.is_relative_to(root) or not path.is_file():
        raise ImageReferenceError("Image is outside the chat folder or missing.")
    return path


def handoff_context(cwd: str, attachments: list[Any], *, session_id: str) -> str:
    """Register only the images selected on THIS message, inside its own folder.

    Client-provided paths are untrusted. No URL fetching, parent traversal or
    symlink escape may turn an attachment into access to another private file.
    The IDs stay valid for later messages of the conversation
    (:func:`refresh_handoffs`), so "yes, send an agent" a message after the
    screenshot still hands the screenshot over.
    """
    from dodaios.core.image_references import get_store, instruction

    refs = []
    missing = []
    root = Path(cwd).expanduser().resolve()
    for index, item in enumerate(attachments, 1):
        if item.kind != "image":
            continue
        try:
            refs.append(get_store().add_file(
                "chat:" + session_id, _upload_path(root, item.reference),
                source=f"upload #{index}",
            ))
        except (OSError, ValueError):
            # No raw client paths in logs or error text; the ordinal identifies the chip.
            missing.append(str(index))
    note = instruction(refs, lasting=True)
    if missing:
        note += (
            "\nVisual handoff unavailable for attachment(s) " + ", ".join(missing)
            + ". Do not send a task requiring those images or claim they were attached; "
            "ask the user to attach them again."
        )
    return note


def handoff_references(attachments: list[Any]) -> list[str]:
    """What a ``user_message`` keeps so :func:`refresh_handoffs` finds its pictures again."""
    return [str(item.reference) for item in attachments if item.kind == "image"]


def refresh_handoffs(
    cwd: str, events: list[dict[str, Any]], *, session_id: str, now_ms: int | None = None
) -> list[str]:
    """Register the pictures of this conversation's earlier messages again.

    Their IDs are the ones those messages carried (``add_file`` derives them
    from the file), so a picture shown a few messages ago, or before an app
    restart emptied the reference store, can still go with a work order. Only
    pictures of the last 24 hours, at most the newest
    :data:`_EARLIER_PICTURES_MAX`, and only files still inside the chat folder
    under the same checks as a new upload. Returns the registered IDs.
    """
    import time

    from dodaios.core.image_references import get_store

    root = Path(cwd).expanduser().resolve()
    since = (now_ms if now_ms is not None else int(time.time() * 1000)) - _EARLIER_PICTURES_MS
    references: list[str] = []
    for event in reversed(events):
        if event.get("kind") != "user_message" or int(event.get("ts_ms") or 0) < since:
            continue
        listed = (event.get("payload") or {}).get("visual_references")
        for reference in reversed(listed if isinstance(listed, list) else []):
            if isinstance(reference, str) and reference not in references:
                references.append(reference)
        if len(references) >= _EARLIER_PICTURES_MAX:
            break
    refs = []
    for reference in references[:_EARLIER_PICTURES_MAX]:
        try:
            refs.append(get_store().add_file(
                "chat:" + session_id, _upload_path(root, reference),
                source="upload, earlier message", fresh=False,
            ))
        except (OSError, ValueError):  # deleted or moved since: that picture is just not offered
            continue
    return refs


async def ingest(
    cwd: str | Path,
    *,
    paths: list[str] | None = None,
    uploads: Sequence[tuple[str, DropSource]] | None = None,
    provider: str = "",
    always_copy: bool = False,
    describe_images: bool = True,
) -> list[Any]:
    """Store what was dropped in ``cwd`` and read what is in it.

    ``paths`` are real locations the browser managed to hand over (an Explorer
    or Finder drag usually carries them, and inside the desktop shell the host
    resolves them for every drop). ``uploads`` are ``(name, bytes)`` for
    everything with no path at all — a pasted screenshot, an image dragged off
    a web page. An upload may also be an open binary file (the web server's
    spooled copy), so a large one streams to disk instead of into memory.

    A path already inside ``cwd`` is referenced where it lies; anything else is
    copied in, because an agent's reach outside its working directory is
    neither guaranteed nor silent.

    Returns ``drop_analysis.DropAnalysis`` entries — one per file, in the order
    they arrived. Raises :class:`AttachmentError` when nothing usable was
    carried; an analysis that fails costs the description and nothing else, so
    the file still travels.
    """
    from dodaios.agentic_ide import drops

    folder = Path(cwd).expanduser()  # noqa: ASYNC240 — string work; the stat below is threaded
    if not await asyncio.to_thread(folder.is_dir):
        raise AttachmentError(f"Not a folder: {folder}")

    references: list[str] = []
    # (name, bytes, reference) for everything attached — the reference travels
    # with the bytes so a description can never drift onto another file.
    readable: list[tuple[str, bytes, str]] = []
    to_copy: list[tuple[str, DropSource]] = []

    for raw in paths or []:
        candidate = (raw or "").strip()
        if not candidate:
            continue
        inside = drops.within_workspace(candidate, folder)
        if inside is not None and not always_copy:
            reference = drops.reference(inside, agent=provider)
            references.append(reference)
            try:
                body = await asyncio.to_thread(drops.read_for_analysis, folder / inside)
            except OSError as exc:
                # The reference still ships; the file simply goes undescribed.
                log.info("chat attach: %r not readable for analysis (%s)", inside, exc)
            else:
                if body is not None:
                    readable.append((Path(inside).name, body, reference))
            continue
        # expanduser() is string work; the stat itself goes to a worker thread
        # (a dropped file may live on a slow network share). The copy streams
        # from the path, so a large recording is never held in memory.
        resolved = Path(candidate).expanduser()  # noqa: ASYNC240
        if not await asyncio.to_thread(resolved.is_file):
            log.info("chat attach: unreadable dropped path %r", candidate)
            continue
        to_copy.append((resolved.name, resolved))

    for name, source in uploads or []:
        to_copy.append((name or "file", source))

    # ``store`` skips empty entries silently, so they are dropped HERE instead —
    # that keeps ``stored[i]`` paired with ``to_copy[i]`` positionally.
    sizes = await asyncio.to_thread(lambda: [drops.size_of(src) for _n, src in to_copy])
    to_copy = [pair for pair, size in zip(to_copy, sizes, strict=True) if size != 0]

    if to_copy:
        try:
            stored = await asyncio.to_thread(drops.store, folder, to_copy)
        except drops.DropError as exc:
            raise AttachmentError(str(exc)) from exc
        for item, (_original, source) in zip(stored, to_copy, strict=True):
            reference = drops.reference(item.relative_path, agent=provider)
            references.append(reference)
            # A file too large to analyse still ships; it goes undescribed.
            body = await asyncio.to_thread(drops.read_for_analysis, source)
            if body is not None:
                readable.append((item.name, body, reference))

    if not references:
        raise AttachmentError("That attachment carried nothing this chat could use.")

    if describe_images:
        return await _analyze(readable)
    return await _analyze(readable, describe_images=False)


async def _analyze(
    readable: list[tuple[str, bytes, str]], *, describe_images: bool = True
) -> list[Any]:
    """Describe images and extract documents. Never raises — this is a bonus.

    The files are already stored and referenced by the time this runs, so a
    provider outage here must cost the description and nothing more.
    """
    import mimetypes

    from dodaios.agentic_ide import drop_analysis
    from dodaios.brain.drop_context import DroppedItem

    if not readable:
        return []
    items = [
        (
            DroppedItem(
                name=name,
                mime=mimetypes.guess_type(name)[0] or "application/octet-stream",
                data=data,
            ),
            reference,
        )
        for name, data, reference in readable
    ]
    try:
        if describe_images:
            return await drop_analysis.analyze(items)
        return await drop_analysis.analyze(items, describe_images=False)
    except Exception as exc:  # noqa: BLE001 — the attach itself already succeeded
        log.info("chat attach: analysis failed (%s)", exc)
        return []


def to_analysis(raw: list[dict[str, Any]] | None) -> list[Any]:
    """Rebuild the analyses a composer hands back on the wire.

    The client holds what :func:`ingest` returned while the person finishes
    typing, then posts it with the message. It is request data, so nothing here
    may assume a shape: a malformed entry becomes an empty-detail attachment
    rather than a 500 on a message somebody is waiting to send.
    """
    from dodaios.agentic_ide import drop_analysis

    out: list[Any] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        item = drop_analysis.DropAnalysis.from_dict(entry)
        if item.name:
            out.append(item)
    return out


def compose(text: str, attachments: list[Any] | None) -> str:
    """The message as the turn will actually receive it.

    The person's sentence first, then what was attached — the sentence is the
    task, the files are context for it, and a model reads the instruction
    better when it is not buried under a page of extracted PDF.

    Returns ``text`` unchanged when nothing is attached, so an ordinary message
    is never reshaped by a feature it did not use.
    """
    from dodaios.agentic_ide.prompt_blueprint import attachment_block

    said = (text or "").strip()
    block = attachment_block(list(attachments or []))
    if not block:
        return said
    lead = (
        "Files the user attached to this message are below. Their contents are "
        "given in full because the file itself may not be openable from here — "
        "read them as part of the message."
    )
    return "\n\n".join(part for part in (said, lead, block) if part)
