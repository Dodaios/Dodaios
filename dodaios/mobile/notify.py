"""Push to the paired phone: needs-you notices, approvals waiting, reminders.

Two sources, one sender:

* :class:`AgentAttentionChanged` on the app bus (``transition == "needs_input"``):
  an agent waits on the person — an approval card, a question, a credential,
  a proposal. The attention module already decided the change is worth
  telling (never for unattended work, never while the person looks at that
  agent, throttled); this only carries it to the phone.
* ``notice`` events in the lead conversation whose kind is a reminder or a
  result the person asked for (a routine's report, the morning brief, a due
  memory), or that carry ``push: true`` explicitly.

Every push is a short, encrypted JSON note the phone's service worker shows;
the data stays on this machine until the phone opens the conversation. A
subscription the push service reports gone is dropped from the device record.
Nothing here speaks, and nothing here runs a model.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from .devices import MobileDevices, get_devices
from .webpush import WebPushSender

log = logging.getLogger(__name__)

#: Lead notices worth a push without being asked.
REMINDER_NOTICE_KINDS = frozenset(
    {
        "reminder",
        "memory_due",
        "due",
        "morning_brief",
        "brief",
        "routine_result",
        "society_result",
        "coding_result",
        "delegation_report",
        "team_report",
    }
)
#: The same card or notice is pushed at most once per this window.
DEDUPE_S = 90.0
_BODY_CHARS = 180


def _line(value: Any, limit: int = _BODY_CHARS) -> str:
    return " ".join(str(value or "").split())[:limit]


class MobilePushNotifier:
    """Fans one note out to every paired phone with a push subscription."""

    def __init__(
        self,
        *,
        devices: MobileDevices | None = None,
        sender: WebPushSender | None = None,
        lead_session_id: Callable[[], str | None] | None = None,
        assistant_name: Callable[[], str] | None = None,
    ) -> None:
        self._devices = devices
        self._sender = sender
        self._lead_session_id = lead_session_id or (lambda: None)
        self._assistant_name = assistant_name or (lambda: "Assistant")
        self._recent: dict[str, float] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._attached: set[int] = set()

    @property
    def devices(self) -> MobileDevices:
        if self._devices is None:
            self._devices = get_devices()
        return self._devices

    @property
    def sender(self) -> WebPushSender:
        if self._sender is None:
            self._sender = WebPushSender()
        return self._sender

    # ------------------------------------------------------------ sources

    async def on_attention(self, event: Any) -> None:
        """Bus handler for :class:`AgentAttentionChanged`."""
        if str(getattr(event, "transition", "") or "") != "needs_input":
            return
        ref = str(getattr(event, "ref_id", "") or "")
        kind = str(getattr(event, "kind", "") or "")
        who = str(getattr(event, "agent_name", "") or "") or self._assistant_name()
        summary = _line(getattr(event, "summary", ""))
        body = summary or {
            "approval": "An action waits for your approval.",
            "question": "A question waits for your answer.",
            "credential": "A login is needed to continue.",
            "proposal": "A proposal waits for your decision.",
        }.get(kind, "Something waits for you.")
        await self.push(
            tag=f"needs-{ref or int(time.time())}",
            title=f"{who} needs you",
            body=body,
            kind=kind or "needs_input",
            url="/m/",
            urgency="high",
        )

    def attach_service(self, service: Any) -> None:
        """Watch the lead conversation's notices through the chat service (once)."""
        add = getattr(service, "add_event_listener", None)
        if not callable(add) or id(service) in self._attached:
            return
        add(self.listener)
        self._attached.add(id(service))

    def listener(self, session_id: str, event: dict[str, Any]) -> None:
        """Chat-service event listener: records, then schedules the push."""
        if event.get("kind") != "notice":
            return
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return
        notice_kind = str(payload.get("kind") or "")
        if payload.get("push") is not True and notice_kind not in REMINDER_NOTICE_KINDS:
            return
        if session_id != (self._lead_session_id() or session_id):
            return
        text = _line(payload.get("text") or payload.get("report") or payload.get("summary"))
        if not text:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # emitted off the loop: no push for this one
            return
        title = _line(payload.get("title"), 60) or self._assistant_name()
        task = loop.create_task(
            self.push(
                tag=f"notice-{event.get('seq') or int(time.time())}",
                title=title,
                body=text,
                kind=notice_kind or "notice",
                url="/m/",
            ),
            name="mobile-push-notice",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------- sending

    def _fresh(self, tag: str) -> bool:
        now = time.monotonic()
        for key, when in list(self._recent.items()):
            if now - when > DEDUPE_S:
                self._recent.pop(key, None)
        if tag in self._recent:
            return False
        self._recent[tag] = now
        return True

    async def push(
        self,
        *,
        tag: str,
        title: str,
        body: str,
        kind: str = "",
        url: str = "/m/",
        urgency: str = "normal",
    ) -> int:
        """Send one note to every subscribed phone; returns how many were sent."""
        if not self._fresh(tag):
            return 0
        try:
            targets = await asyncio.to_thread(self.devices.push_targets)
        except Exception:  # noqa: BLE001 — an unreadable device file means no phones
            log.warning("mobile push: could not read the paired phones", exc_info=True)
            return 0
        if not targets:
            return 0
        payload = {
            "title": title[:80],
            "body": body[:_BODY_CHARS],
            "tag": tag,
            "kind": kind,
            "url": url,
        }
        sent = 0
        for device in targets:
            assert device.push is not None
            result = await self.sender.send(device.push, payload, urgency=urgency)
            if result == "sent":
                sent += 1
            elif result == "gone":
                try:
                    await asyncio.to_thread(self.devices.set_push, device.id, None)
                except Exception:  # noqa: BLE001 — the next push retries the same cleanup
                    log.debug("mobile push: could not drop a dead subscription", exc_info=True)
        return sent


_NOTIFIER: MobilePushNotifier | None = None


def notifier() -> MobilePushNotifier:
    """The process-wide notifier (built on first use)."""
    global _NOTIFIER
    if _NOTIFIER is None:
        _NOTIFIER = MobilePushNotifier(lead_session_id=_lead_id, assistant_name=_assistant_name)
    return _NOTIFIER


def set_notifier(value: MobilePushNotifier | None) -> None:
    """Test hook."""
    global _NOTIFIER
    _NOTIFIER = value


_CONFIG: Any = None


def install(bus: Any, *, config: Any = None) -> MobilePushNotifier:
    """Subscribe the notifier to the app bus; ``config`` names the assistant in titles."""
    global _CONFIG
    if config is not None:
        _CONFIG = config
    current = notifier()
    try:
        from dodaios.agent_chat.attention import AgentAttentionChanged

        bus.subscribe(AgentAttentionChanged, current.on_attention)
    except Exception:  # noqa: BLE001 — without the attention module there is nothing to carry
        log.debug("mobile push: attention events unavailable", exc_info=True)
    return current


def _lead_id() -> str | None:
    try:
        from dodaios.agent_chat.lead import lead_session_id
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        svc = runtime.chat_service() if runtime is not None else None
        return lead_session_id(svc) if svc is not None else None
    except Exception:  # noqa: BLE001 — no society runtime: every session counts
        return None


def _assistant_name() -> str:
    """What the person calls the assistant (from the wake phrase), or a neutral word."""
    try:
        from dodaios.brain.assistant_name import DEFAULT_ASSISTANT_NAME, resolve_assistant_name

        return resolve_assistant_name(_CONFIG) if _CONFIG is not None else DEFAULT_ASSISTANT_NAME
    except Exception:  # noqa: BLE001 — the neutral word is a fine title
        return "Assistant"


__all__ = [
    "DEDUPE_S",
    "REMINDER_NOTICE_KINDS",
    "MobilePushNotifier",
    "install",
    "notifier",
    "set_notifier",
]
