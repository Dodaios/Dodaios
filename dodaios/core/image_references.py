"""Scoped, short-lived image capabilities for an explicitly selected work order.

Pixels remain in RAM until an authorized handoff copies the selected images.
There is deliberately no latest-image lookup and no arbitrary path/URL loader.

A picture uploaded into the Dodaios chat is the exception to "short-lived":
the person often shows a screenshot, talks it through, and only a message
later says "yes, send an agent". Its file already lies in the chat's own
folder, so its reference (:meth:`ImageReferences.add_file`) keeps a stable ID
for :data:`CHAT_TTL_SECONDS`, holds the bytes in RAM only for the first
:data:`TTL_SECONDS`, and afterwards reads the file again, checked against the
SHA-256 it had when it was attached.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

MAX_IMAGES = 20
MAX_BYTES = 25 * 1024 * 1024
TTL_SECONDS = 120.0
#: A picture handed to a live call stays in that call's model context until the
#: call ends, so its reference must live as long or the model sees an image it
#: cannot forward. The call's close clears the scope; this bound only expires a
#: scope whose call never closed cleanly.
LIVE_CALL_TTL_SECONDS = 3600.0
#: A picture uploaded into the Dodaios chat stays addressable this long after
#: the last message of its conversation re-registered it, so a work order the
#: person confirms later in the same conversation can still carry it.
CHAT_TTL_SECONDS = 24 * 3600.0
active_scope: ContextVar[str] = ContextVar("visual_reference_scope", default="")
_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class ImageReferenceError(ValueError):
    """Nothing may be sent when a selected image is unavailable."""


@dataclass(frozen=True, slots=True)
class ReferencedImage:
    id: str
    data: bytes
    mime: str
    source: str
    sha256: str

    @property
    def name(self) -> str:
        return self.id + _EXTENSIONS[self.mime]


def scope_for(config: dict | None = None, trace_id: object = "") -> str:
    """Trusted conversation identity, never a model-supplied argument."""
    from dodaios.core.protocols import current_chat_turn

    turn = current_chat_turn.get()
    if turn is not None:
        return "chat:" + turn.session_id
    config = config or {}
    if config.get("live_session_id"):
        return "live:" + str(config["live_session_id"])
    if config.get("approval_ref", "").startswith("agent-chat:"):
        return "chat:" + config["approval_ref"].removeprefix("agent-chat:")
    return str(
        config.get("image_reference_scope") or active_scope.get() or ("turn:" + str(trace_id))
    )


def ttl_for(scope: str, config: object = None) -> float:
    """Reference lifetime: the capture budget, or the whole call for a live scope."""
    ttl = float(getattr(getattr(config, "screen_context", None), "ttl_s", TTL_SECONDS))
    return max(ttl, LIVE_CALL_TTL_SECONDS) if scope.startswith("live:") else ttl


def appshot_context(session_id: str, image: bytes, mime: str, config: object) -> str:
    scope = "live:" + session_id
    ref = get_store().add(scope, image, mime, source="appshot", ttl_s=ttl_for(scope, config))
    return instruction([ref])


def instruction(refs: list[str], *, lasting: bool = False) -> str:
    """The note beside the pixels that tells the model how to forward them.

    ``lasting`` is for chat uploads (:meth:`ImageReferences.add_file`): their
    IDs stay valid for later messages of the same conversation.
    """
    if not refs:
        return ""
    ending = (
        "These IDs stay valid in this conversation for 24 hours, so a work order the user "
        "asks for or confirms in a later message carries them too. If one is refused as "
        "expired or missing, say so and ask for the picture again."
        if lasting
        else "References expire; report unavailability honestly."
    )
    return (
        "Visual reference IDs (same order as the attached images): " + ", ".join(refs) + ". "
        "When handing a task based on these images to workspace-orchestrate create, "
        "open_workspace or send, include the relevant IDs in image_refs. Select only "
        "images used by that specific task; never substitute a description or unrelated "
        "older screenshots. " + ending
    )


@dataclass(slots=True)
class _Entry:
    scope: str
    until: float
    image: ReferencedImage
    #: Until when the image counts as attached to the current message: a work
    #: order without ``image_refs`` is asked for a selection only meanwhile.
    fresh_until: float
    #: A chat upload's file; its bytes are dropped from RAM after the fresh
    #: window and read again (and checked against ``image.sha256``) on resolve.
    path: Path | None = None

    def holds_bytes_past_fresh(self) -> bool:
        return self.path is not None and bool(self.image.data)


class ImageReferences:
    def __init__(self, *, clock=time.monotonic, schedule_expiry: bool = True) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._schedule_expiry = schedule_expiry
        self._timer: threading.Timer | None = None
        self._expiry_at = 0.0

    def _expire(self) -> None:
        now = self._clock()
        for key in [k for k, entry in self._entries.items() if entry.until <= now]:
            del self._entries[key]
        for entry in self._entries.values():
            if entry.holds_bytes_past_fresh() and entry.fresh_until <= now:
                entry.image = replace(entry.image, data=b"")

    def _deadline(self) -> float:
        return min(
            min(entry.until, entry.fresh_until) if entry.holds_bytes_past_fresh() else entry.until
            for entry in self._entries.values()
        )

    def _arm_expiry(self) -> None:
        """One daemon timer per store, so idle conversations do not retain pixels."""
        if not self._schedule_expiry or not self._entries:
            return
        deadline = self._deadline()
        if self._timer is not None and self._expiry_at <= deadline:
            return
        if self._timer is not None:
            self._timer.cancel()
        self._expiry_at = deadline
        self._timer = threading.Timer(max(0.001, deadline - self._clock()), self._on_expiry)
        self._timer.daemon = True
        self._timer.start()

    def _on_expiry(self) -> None:
        with self._lock:
            if self._timer is not threading.current_thread():
                return  # A replacement or clear cancelled this timer while it waited.
            self._timer = None
            self._expire()
            self._arm_expiry()

    def _insert(self, key: str, entry: _Entry) -> None:
        """Store ``entry``; the caller holds the lock and has expired old rows."""
        size = len(entry.image.data)
        # A bounded RAM cache. Evicted IDs fail closed, never refer to another image.
        while self._entries and (
            len(self._entries) >= 100
            or sum(len(row.image.data) for row in self._entries.values()) + size
            > 100 * 1024 * 1024
        ):
            del self._entries[next(iter(self._entries))]
        self._entries[key] = entry
        self._arm_expiry()

    def add(
        self, scope: str, data: bytes, mime: str, *, source: str, ttl_s: float = TTL_SECONDS
    ) -> str:
        if not scope or mime not in _EXTENSIONS or not data or len(data) > MAX_BYTES:
            raise ImageReferenceError(
                "The image cannot be handed off (unsupported or empty image)."
            )
        with self._lock:
            self._expire()
            key = "img_" + uuid4().hex
            image = ReferencedImage(key, data, mime, source, hashlib.sha256(data).hexdigest())
            until = self._clock() + max(0, ttl_s)
            self._insert(key, _Entry(scope, until, image, fresh_until=until))
            return key

    def add_file(
        self,
        scope: str,
        path: Path,
        *,
        source: str,
        fresh: bool = True,
        ttl_s: float = CHAT_TTL_SECONDS,
    ) -> str:
        """Reference a chat upload by its file, under an ID that stays the same.

        The ID depends only on ``scope`` and ``path``, so the ID a message once
        carried is valid again when a later message re-registers the same file
        (also after an app restart emptied this store). ``fresh`` marks a
        picture attached to the message being answered right now; a picture of
        an earlier message is registered with ``fresh=False`` and makes no work
        order ask for a picture selection. The caller vouches that ``path`` is
        inside the conversation's own folder.
        """
        key = "img_" + hashlib.sha256(f"{scope}\0{path}".encode()).hexdigest()[:32]
        with self._lock:
            self._expire()
            now = self._clock()
            entry = self._entries.get(key)
            if entry is not None and entry.scope == scope:
                entry.until = max(entry.until, now + max(0, ttl_s))
                if fresh:
                    entry.fresh_until = max(entry.fresh_until, now + TTL_SECONDS)
                self._arm_expiry()
                return key
        mime = mimetypes.guess_type(path.name)[0] or ""
        if not scope or mime not in _EXTENSIONS:
            raise ImageReferenceError("The image cannot be handed off (unsupported image).")
        if path.stat().st_size > MAX_BYTES:
            raise ImageReferenceError("Image is too large for a handoff.")
        data = path.read_bytes()
        if not data:
            raise ImageReferenceError("The image cannot be handed off (empty image).")
        image = ReferencedImage(key, data, mime, source, hashlib.sha256(data).hexdigest())
        with self._lock:
            self._expire()
            now = self._clock()
            if not fresh:
                image = replace(image, data=b"")  # An earlier picture is read when it is sent.
            self._insert(key, _Entry(
                scope, now + max(0, ttl_s), image,
                fresh_until=now + TTL_SECONDS if fresh else now, path=path,
            ))
            return key

    def add_blocks(self, scope: str, images: tuple, *, source: str) -> list[str]:
        refs = []
        for image in images:
            try:
                data = base64.b64decode(image.data_b64, validate=True)
            except ValueError as exc:
                raise ImageReferenceError("The attached image could not be decoded.") from exc
            refs.append(self.add(scope, data, image.mime, source=source))
        return refs

    def resolve(self, scope: str, refs: object) -> tuple[ReferencedImage, ...]:
        if (
            not isinstance(refs, list)
            or len(refs) > MAX_IMAGES
            or any(not isinstance(r, str) for r in refs)
        ):
            raise ImageReferenceError("image_refs must be a list of at most 20 image IDs.")
        with self._lock:
            self._expire()
            images = []
            for key in dict.fromkeys(refs):
                entry = self._entries.get(key)
                if entry is None or entry.scope != scope:
                    raise ImageReferenceError(
                        "A selected image is expired, missing or belongs to another conversation. "
                        "Nothing was sent. Ask for the image again "
                        "or take a new authorized appshot."
                    )
                images.append(entry)
        return tuple(_loaded(entry) for entry in images)

    def clear_scope(self, scope: str) -> None:
        with self._lock:
            for key in [k for k, row in self._entries.items() if row.scope == scope]:
                del self._entries[key]
            if not self._entries and self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def available(self, scope: str, *, fresh_only: bool = False) -> list[dict[str, str]]:
        """The images ``scope`` may hand off; ``fresh_only`` keeps the current message's."""
        with self._lock:
            self._expire()
            now = self._clock()
            return [
                {"id": entry.image.id, "source": entry.image.source}
                for entry in self._entries.values()
                if entry.scope == scope and (not fresh_only or entry.fresh_until > now)
            ]


def _loaded(entry: _Entry) -> ReferencedImage:
    """The entry's image with its bytes, read again from a chat upload's file if needed."""
    image = entry.image
    if image.data or entry.path is None:
        return image
    try:
        data = entry.path.read_bytes()
    except OSError as exc:
        raise ImageReferenceError(
            "A selected picture was deleted from the chat folder. Nothing was sent. "
            "Ask for the image again."
        ) from exc
    if hashlib.sha256(data).hexdigest() != image.sha256:
        raise ImageReferenceError(
            "A selected picture changed after it was attached. Nothing was sent. "
            "Ask for the image again."
        )
    return replace(image, data=data)


_STORE = ImageReferences()


def get_store() -> ImageReferences:
    return _STORE
