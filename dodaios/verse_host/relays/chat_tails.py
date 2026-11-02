"""Chat tails relay (BW5, contract 6): the last lines of watched agents' chats.

No agent-chat bus event exists, so the relay polls each watched agent every
2.5 s (plus jitter), at most 6 agents and 6 reads in flight, as the web
Verse does today. A ``chat_tails.update`` goes out only when ``version``
changes; an agent without a chat session yields one empty update.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from .. import protocol as P
from ..chat_lines import chat_lines, chat_version
from .base import RelayBase

log = logging.getLogger(__name__)

POLL_S = 2.5
JITTER_S = 1.2
TAIL_EVENTS = 60


class ChatTailsRelay(RelayBase):
    topics = ("chat_tails",)

    def __init__(self, session: Any, backend: Any) -> None:
        super().__init__(session, backend)
        self.watching: list[str] = []
        self.versions: dict[str, str] = {}
        self.sessions: dict[str, str | None] = {}
        self._wake = asyncio.Event()

    async def start(self) -> None:
        self.session.hub.command("chat_tails.watch", self._watch)
        self.spawn(self._loop())

    async def resync(self, topic: str, data: dict[str, Any]) -> None:
        self.versions.clear()
        self._wake.set()

    async def _watch(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        agents = msg.data.get("agents")
        if not isinstance(agents, list) or not all(isinstance(a, str) and a for a in agents):
            raise P.BridgeError("bad_request", "agents must be a list of agent ids.")
        unique = list(dict.fromkeys(agents))
        limit = P.LIMITS["chat_tails_max_agents"]
        self.watching, dropped = unique[:limit], unique[limit:]
        for gone in [a for a in self.versions if a not in self.watching]:
            self.versions.pop(gone, None)
        self._wake.set()
        return {"watching": list(self.watching), "dropped": dropped}

    async def _session_for(self, agent_id: str) -> str | None:
        if agent_id not in self.sessions:
            session_id = None
            try:
                for row in await self.backend.list_agents():
                    if row.get("agent_id") == agent_id:
                        session_id = row.get("session_id") or row.get("chat_session_id")
                        break
            except Exception:  # noqa: BLE001
                log.debug("verse chat tails: roster read failed", exc_info=True)
            self.sessions[agent_id] = session_id or f"society:{agent_id}"
        return self.sessions[agent_id]

    async def read_one(self, agent_id: str) -> None:
        session_id = await self._session_for(agent_id)
        events = None
        if session_id:
            try:
                events = await self.backend.chat_tail(session_id, TAIL_EVENTS)
            except Exception:  # noqa: BLE001 - the monitor keeps its last good frame
                log.debug("verse chat tails: read failed for %s", agent_id, exc_info=True)
                return
        if events is None:
            data = {"agent_id": agent_id, "lines": [], "version": ""}
        else:
            data = {
                "agent_id": agent_id,
                "version": chat_version(events),
                "lines": chat_lines(events, P.LIMITS["chat_tail_lines"]),
            }
        if agent_id not in self.watching:
            return
        if self.versions.get(agent_id) == data["version"]:
            return
        self.versions[agent_id] = data["version"]
        self.session.send("chat_tails.update", data, topic="chat_tails", feed=True)

    async def _loop(self) -> None:
        while not self.stopped:
            batch = list(self.watching)
            if batch:
                await asyncio.gather(*(self.read_one(a) for a in batch), return_exceptions=True)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), POLL_S + random.random() * JITTER_S)  # noqa: S311
            except TimeoutError:  # poll interval elapsed; next round
                pass
