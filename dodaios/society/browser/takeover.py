"""Human takeover of the agent's browser: state, hand-back note and request.

The owner can watch the agent's browser live and take over (CAPTCHA, single
sign-on, a second factor, a tricky form), then hand back. The pause itself and
the forwarding of clicks and keys already live in ``live.py`` /
``live_runner.py`` (the agent gate stops the task between steps, input goes to
the page). This module adds what a hand-over needs around it:

* ``TakeoverState`` records one takeover: where the page was, how much the
  owner did, and an open request from the agent. It counts inputs and never
  keeps their content: a typed password, a pasted code or a clicked secret
  link is not stored, logged or shown to the model.
* ``handback_note`` is the short sentence the agent gets back: the page the
  owner left it on (host and path only, no query string or fragment, which can
  carry tokens) and whether anything was typed, never what.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import uuid4

log = logging.getLogger(__name__)

__all__ = [
    "INPUT_OPS",
    "TYPING_OPS",
    "TakeoverState",
    "handback_note",
    "safe_url",
]

#: Control operations that act on the page for the owner (counted, never stored).
INPUT_OPS: Final[frozenset[str]] = frozenset(
    {"click", "scroll", "text", "key", "navigate", "back", "forward", "reload", "tab", "dialog"}
)
#: Of those, the ones that can carry something the owner typed.
TYPING_OPS: Final[frozenset[str]] = frozenset({"text", "key"})
#: The longest reason an agent can attach to a request.
MAX_REASON: Final[int] = 300


def safe_url(url: str) -> str:
    """``scheme://host/path`` of ``url``: no credentials, query string or fragment."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:  # an unparsable address carries nothing worth naming: empty is the answer
        return ""
    if not parts.hostname or parts.scheme not in {"http", "https"}:
        return ""
    return f"{parts.scheme}://{parts.hostname}{parts.path}"[:300]


@dataclass
class TakeoverState:
    """One browser session's takeover bookkeeping (lives on its ``LiveSession``)."""

    request: dict[str, Any] | None = None
    active: bool = False
    start_url: str = ""
    actions: int = 0
    typed: int = 0
    last_note: dict[str, Any] | None = None
    _waiters: list[asyncio.Future] = field(default_factory=list)

    def request_takeover(self, reason: str) -> tuple[dict[str, Any], bool]:
        """Open a request, or return the one that is already open: ``(request, is_new)``."""
        if self.request is not None:
            return self.request, False
        self.request = {"id": uuid4().hex[:12], "reason": " ".join(reason.split())[:MAX_REASON]}
        self.last_note = None
        return self.request, True

    def begin(self, url: str) -> None:
        self.active = True
        self.start_url = safe_url(url)
        self.actions = 0
        self.typed = 0

    def record(self, op: str) -> None:
        """Count one owner input. The operation's arguments are never passed in."""
        if not self.active or op not in INPUT_OPS:
            return
        self.actions += 1
        if op in TYPING_OPS:
            self.typed += 1

    def end(self, url: str) -> dict[str, Any]:
        """Close the takeover and return the hand-back note; wakes the agent's wait."""
        note = handback_note(self.start_url, safe_url(url), self.actions, self.typed)
        note["request_id"] = (self.request or {}).get("id", "")
        self.active = False
        self.request = None
        self.last_note = note
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(note)
        self._waiters.clear()
        return note

    async def wait_handback(
        self,
        timeout: float,  # noqa: ASYNC109 — caller-chosen wait
        request_id: str = "",
    ) -> dict[str, Any] | None:
        """Wait until the owner hands back; ``None`` when ``timeout`` runs out.

        A hand-back of ``request_id`` that landed between two waits is returned
        at once, so a slice boundary can never lose it.
        """
        if request_id and self.last_note and self.last_note.get("request_id") == request_id:
            return self.last_note
        waiter: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            return await asyncio.wait_for(asyncio.shield(waiter), timeout)
        except TimeoutError:  # no hand-back in time is the documented None
            return None
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)


def handback_note(url_before: str, url_after: str, actions: int, typed: int) -> dict[str, Any]:
    """What the agent learns when the owner hands the browser back."""
    changed = bool(url_after) and url_after != url_before
    if actions == 0:
        text = "The owner looked at the browser and handed it back without doing anything."
    else:
        text = f"The owner worked in the browser ({actions} inputs) and handed it back."
        if typed:
            text += " Some of it was typed; what was typed is not recorded and not shown to you."
    if url_after:
        text += f" The page is now {url_after}" + (" (it changed)." if changed else ".")
    return {
        "text": text,
        "url": url_after,
        "url_changed": changed,
        "inputs": actions,
        "typed": bool(typed),
    }
