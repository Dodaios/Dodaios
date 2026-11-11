"""Gmail: new inbox mail by history id (incremental, metadata only)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Final

from ..event import AGENT_SCOPE_PREFIX, TriggerEvent
from .base import Api, Poll, ProviderError, address_of

_BASE: Final[str] = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_PAGES: Final[int] = 10
MAX_FETCH: Final[int] = 40
MAX_BACKLOG: Final[int] = 500
_MACHINE_LABELS: Final[frozenset[str]] = frozenset(
    {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}
)
_NO_REPLY = re.compile(r"(^|[._-])(no-?reply|do-?not-?reply|mailer-daemon|notifications?)@")


class GmailProducer:
    id = "gmail"
    source = "mail"

    def __init__(self, api: Api, agent_address: Callable[[], str] = lambda: "") -> None:
        self._api = api
        self._agent_address = agent_address

    async def connected(self) -> bool:
        return await self._api.connected()

    async def _baseline(self) -> Poll:
        response = await self._api.get(f"{_BASE}/profile")
        if response.status_code != 200:
            raise ProviderError(f"gmail: profile HTTP {response.status_code}")
        return Poll([], {"history_id": str(response.json().get("historyId") or ""), "backlog": []})

    async def poll(self, cursor: dict[str, Any], now: float) -> Poll:
        history_id = str(cursor.get("history_id") or "")
        if not history_id:  # the first poll only marks the present: no flood of old mail
            return await self._baseline()
        queue = [str(i) for i in cursor.get("backlog") or []]
        newest, truncated_at, page = history_id, "", ""
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {
                "startHistoryId": history_id, "historyTypes": "messageAdded",
                "labelId": "INBOX", "maxResults": 100,
            }
            if page:
                params["pageToken"] = page
            response = await self._api.get(f"{_BASE}/history", params)
            if response.status_code == 404:  # the history id expired: start from now
                return await self._baseline()
            if response.status_code != 200:
                raise ProviderError(f"gmail: history HTTP {response.status_code}")
            data = response.json()
            newest = str(data.get("historyId") or newest)
            for record in data.get("history") or []:
                truncated_at = str(record.get("id") or truncated_at)
                for added in record.get("messagesAdded") or []:
                    message_id = str((added.get("message") or {}).get("id") or "")
                    if message_id and message_id not in queue:
                        queue.append(message_id)
            page = str(data.get("nextPageToken") or "")
            if not page:
                truncated_at = ""
                break
        events: list[TriggerEvent] = []
        for message_id in queue[:MAX_FETCH]:
            event = await self._event(message_id, now)
            if event is not None:
                events.append(event)
        rest = queue[MAX_FETCH:][:MAX_BACKLOG]
        return Poll(events, {"history_id": truncated_at or newest, "backlog": rest})

    async def _event(self, message_id: str, now: float) -> TriggerEvent | None:
        response = await self._api.get(
            f"{_BASE}/messages/{message_id}",
            {"format": "metadata",
             "metadataHeaders": ["From", "To", "Subject", "Auto-Submitted", "Precedence"]},
        )
        if response.status_code == 404:  # deleted since: nothing to report
            return None
        if response.status_code != 200:
            raise ProviderError(f"gmail: message HTTP {response.status_code}")
        raw = response.json()
        labels = [str(label) for label in raw.get("labelIds") or []]
        if "SENT" in labels or "DRAFT" in labels:
            return None
        headers = {
            str(h.get("name") or "").lower(): str(h.get("value") or "")
            for h in (raw.get("payload") or {}).get("headers") or []
        }
        sender = address_of(headers.get("from", ""))
        automated = (
            headers.get("auto-submitted", "no").lower() != "no"
            or headers.get("precedence", "").lower() in ("bulk", "list", "junk")
        )
        subject = headers.get("subject", "")
        snippet = str(raw.get("snippet") or "")
        agent = self._agent_address()
        to_agent = bool(agent) and agent in headers.get("to", "").lower()
        thread_id = str(raw.get("threadId") or "")
        return TriggerEvent(
            source="mail",
            scope=f"{AGENT_SCOPE_PREFIX}{agent}" if to_agent else "inbox",
            sender=sender,
            thread_key=thread_id,
            summary=" ".join(f"{subject}: {snippet}".split())[:300],
            ids=(message_id, thread_id) if thread_id else (message_id,),
            received_at=now,
            raw_ref=f"https://mail.google.com/mail/u/0/#inbox/{thread_id or message_id}",
            is_bot=automated
            or bool(_MACHINE_LABELS & set(labels))
            or bool(_NO_REPLY.search(sender)),
            labels=tuple(labels),
        )
