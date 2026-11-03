"""Groups and meetings relay (BW6, contract 7).

``groups.snapshot`` on subscribe, ``groups.delta`` when a group changed (same
rules as the roster delta). ``meetings.update`` is pushed on every trigger
for a group with a running room, and once with ``running: false`` when it
settles. ``meeting.start`` / ``meeting.stop`` run the app's own meeting calls
after its confirmation path; a declined confirmation replies ``conflict``.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import protocol as P
from ..ports import NotFound
from .base import Coalescer, RelayBase, diff_rows

log = logging.getLogger(__name__)

MAX_MESSAGES = 8
TEXT_MAX = 200
SAFETY_S = 60.0


def _cut(text: Any, limit: int = TEXT_MAX) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def group_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    gid = raw.get("group_id") or raw.get("id")
    if not isinstance(gid, str) or not gid:
        return None
    members = []
    for m in raw.get("members") or []:
        mid = m.get("agent_id") if isinstance(m, dict) else m
        if isinstance(mid, str) and mid:
            members.append(mid)
    lead = raw.get("lead") or raw.get("lead_id")
    goal = raw.get("goal")
    goal_out = None
    if isinstance(goal, dict) and isinstance(goal.get("goal_id") or goal.get("id"), str):
        goal_out = {
            "goal_id": str(goal.get("goal_id") or goal.get("id")),
            "state": str(goal.get("state") or "running"),
        }
    return {
        "group_id": gid,
        "name": str(raw.get("name") or ""),
        "members": members,
        "lead": lead if isinstance(lead, str) and lead else None,
        "goal": goal_out,
    }


def meeting_update(group_id: str, snap: dict[str, Any]) -> dict[str, Any]:
    room = snap.get("room") if isinstance(snap.get("room"), dict) else None
    messages = [
        {
            "id": str(m.get("id")),
            "speaker": str(m.get("speaker") or "user"),
            "text": _cut(m.get("text")),
        }
        for m in (snap.get("messages") or [])
        if isinstance(m, dict) and m.get("id")
    ][-MAX_MESSAGES:]
    room_out = None
    if room is not None:
        phase = room.get("phase")
        room_out = {
            "room_id": str(room.get("room_id") or "room"),
            "phase": phase if phase in ("open", "settle") else "open",
            "topic": str(room.get("topic") or ""),
            "rounds": max(0, int(room.get("rounds") or 0)),
            "max_rounds": max(1, int(room.get("max_rounds") or 1)),
        }
    speakers = [m["speaker"] for m in messages if m["speaker"] != "user"]
    running = bool(snap.get("running"))
    return {
        "group_id": group_id,
        "running": running,
        "round": room_out["rounds"] if room_out else None,
        "speaker": speakers[-1] if speakers and running else None,
        "room": room_out,
        "messages": messages,
    }


class MeetingsRelay(RelayBase):
    topics = ("groups", "meetings")

    def __init__(self, session: Any, backend: Any) -> None:
        super().__init__(session, backend)
        self.groups: dict[str, dict[str, Any]] = {}
        self.sent_groups: dict[str, dict[str, Any]] | None = None
        self.running: set[str] = set()
        self._later = Coalescer(self, self._refresh, 0.5)

    async def start(self) -> None:
        from dodaios.core import events as E

        hub = self.session.hub
        hub.command("meeting.start", self._start)
        hub.command("meeting.stop", self._stop)
        self.listen([E.SocietyRoomChanged, E.SocietyMessageSent, E.SocietyTeamChanged], self._poke)
        self.every(SAFETY_S, self._refresh)

    async def subscribe(self, topic: str) -> None:
        await self._read_groups()
        if topic == "groups":
            self.sent_groups = None
            self._emit_groups()
        else:
            for gid in list(self.groups):
                await self._push_meeting(gid, initial=True)

    async def _read_groups(self) -> None:
        try:
            raw = await self.backend.chat_groups()
        except Exception:  # noqa: BLE001
            log.warning("verse meetings: group read failed", exc_info=True)
            return
        rows = {}
        for g in raw:
            row = group_row(g)
            if row is not None:
                rows[row["group_id"]] = row
        self.groups = rows

    def _snapshot(self) -> dict[str, Any]:
        self.sent_groups = {k: dict(v) for k, v in self.groups.items()}
        return {"groups": list(self.sent_groups.values())}

    def _emit_groups(self) -> None:
        if "groups" not in self.subscribed:
            return
        self.session.outbox.snapshot_of["groups"] = self._snapshot
        if self.sent_groups is None:
            self.session.send("groups.snapshot", self._snapshot, topic="groups", feed=True)
            return
        upserts, removed = diff_rows(self.sent_groups, self.groups, "group_id")
        if not upserts and not removed:
            return
        self.sent_groups = {k: dict(v) for k, v in self.groups.items()}
        data = {"upsert": {"groups": upserts}, "remove": {"groups": removed}}
        self.session.send("groups.delta", data, topic="groups", delta=True, feed=True)

    async def _push_meeting(self, group_id: str, initial: bool = False) -> None:
        if "meetings" not in self.subscribed:
            return
        try:
            snap = await self.backend.group_meeting(group_id)
        except Exception:  # noqa: BLE001
            log.debug("verse meetings: meeting read failed", exc_info=True)
            return
        if snap is None:
            return
        update = meeting_update(group_id, snap)
        was_running = group_id in self.running
        if update["running"]:
            self.running.add(group_id)
        else:
            self.running.discard(group_id)
        if update["running"] or was_running or (initial and update["room"] is not None):
            self.session.send("meetings.update", update, topic="meetings", feed=True)

    async def _refresh(self) -> None:
        await self._read_groups()
        self._emit_groups()
        for gid in list(self.groups):
            await self._push_meeting(gid)

    async def _poke(self, _event: Any) -> None:
        self._later.poke()

    # ------------------------------------------------------------------ commands
    async def _start(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        gid, text = msg.data.get("group_id"), msg.data.get("text")
        if not isinstance(gid, str) or not gid or not isinstance(text, str) or not text.strip():
            raise P.BridgeError("bad_request", "meeting.start needs group_id and text.")
        if not await self.backend.confirm_dangerous("meeting.start", gid):
            raise P.BridgeError("conflict", "The person declined.")
        await self._call(self.backend.meeting_start(gid, text))
        self._later.poke()
        return {}

    async def _stop(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        gid = msg.data.get("group_id")
        if not isinstance(gid, str) or not gid:
            raise P.BridgeError("bad_request", "meeting.stop needs group_id.")
        if not await self.backend.confirm_dangerous("meeting.stop", gid):
            raise P.BridgeError("conflict", "The person declined.")
        await self._call(self.backend.meeting_stop(gid))
        self._later.poke()
        return {}

    @staticmethod
    async def _call(coro: Any) -> Any:
        try:
            return await coro
        except NotFound as exc:
            raise P.BridgeError("not_found", "Group is gone.") from exc
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 404:
                raise P.BridgeError("not_found", "Group is gone.") from exc
            if status == 409:
                raise P.BridgeError("conflict", str(getattr(exc, "detail", exc))) from exc
            raise
