"""The lead's own inbox (AgentMail): mail that arrives at the address the owner gave it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import quote

from ..event import AGENT_SCOPE_PREFIX, TriggerEvent
from .base import Api, NotConnected, Poll, ProviderError, address_of

_BASE: Final[str] = "https://api.agentmail.to/v0"
_SEEN_REMEMBERED: Final[int] = 200


def _moment(raw: Any) -> float:
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp()


class AgentMailProducer:
    id = "agentmail"
    source = "mail"

    def __init__(self, api: Api, address: Callable[[], str]) -> None:
        self._api = api
        self._address = address

    async def connected(self) -> bool:
        return await self._api.connected()

    async def poll(self, cursor: dict[str, Any], now: float) -> Poll:
        address = self._address()
        if not address:
            raise NotConnected("no address set for the assistant")
        if cursor.get("address") != address or "since" not in cursor:
            return Poll([], {"address": address, "since": now, "seen": []})  # mark the present
        response = await self._api.get(
            f"{_BASE}/inboxes/{quote(address, safe='@')}/messages", {"limit": 50}
        )
        if response.status_code != 200:
            raise ProviderError(f"agentmail: messages HTTP {response.status_code}")
        since = float(cursor["since"])
        seen = [str(i) for i in cursor.get("seen") or []]
        newest, events = since, []
        for item in response.json().get("messages") or []:
            message_id = str(item.get("message_id") or item.get("id") or "")
            stamp = _moment(item.get("timestamp") or item.get("created_at"))
            labels = [str(x).lower() for x in item.get("labels") or []]
            if not message_id or message_id in seen or stamp <= since or "sent" in labels:
                continue
            seen.append(message_id)
            newest = max(newest, stamp)
            events.append(TriggerEvent(
                source="mail", scope=f"{AGENT_SCOPE_PREFIX}{address}",
                sender=address_of(str(item.get("from") or item.get("from_") or "")),
                thread_key=str(item.get("thread_id") or ""),
                summary=" ".join(
                    f"{item.get('subject') or ''}: {item.get('preview') or ''}".split()
                )[:300],
                ids=(message_id,), received_at=stamp,
                raw_ref=f"agentmail:{address}:{message_id}", labels=tuple(labels),
            ))
        return Poll(events, {"address": address, "since": newest, "seen": seen[-_SEEN_REMEMBERED:]})
