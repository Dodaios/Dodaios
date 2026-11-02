"""Roster relay (BW3, contract 4): officers, technicians, ranks and duty status.

Snapshot on subscribe; agents re-read on any society trigger (coalesced to at
most 2 Hz); panes patched in place from ``AgenticIdePaneActivity`` and re-read
on ``TerminalsAdded/Closed/WorkspaceChanged``; ranks re-joined on
``ProgressionAwarded``; a safety re-read every 30 s. A delta goes out only
when a field Verse sees changed.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import protocol as P
from ..duty import (
    PANE_ACTIVITIES,
    PANE_STATUSES,
    RUN_STATES,
    duty_of,
    or_fallback,
    pane_duty,
)
from .base import Coalescer, RelayBase, diff_rows

log = logging.getLogger(__name__)

SAFETY_REREAD_S = 30.0
AGENT_REREAD_S = 0.5


def rank_of(level: int) -> str:
    from dodaios.progression.rules import rank_for

    return rank_for(max(1, int(level)))[1]


def _str(v: Any, default: str = "") -> str:
    return v if isinstance(v, str) else default


def agent_row(
    row: dict[str, Any],
    *,
    levels: dict[str, int],
    errors: set[str],
    overrides: dict[str, str],
    panes_by_agent: dict[str, str],
    teams: dict[str, list[str]],
) -> dict[str, Any]:
    """One society roster row as contract 4.2 sends it (and nothing else)."""
    agent_id = _str(row.get("agent_id"))
    state = _str(row.get("state"), "active")
    lifecycle = "paused" if state == "paused" else "active"
    run_state = or_fallback(row.get("run_state"), RUN_STATES, "idle")
    reason = row.get("waiting_reason")
    duty = duty_of(run_state, lifecycle, asking=reason is not None, error=agent_id in errors)
    duty = overrides.get(agent_id, duty)
    level = levels.get(f"agent:{agent_id}", 1)
    avatar_raw = row.get("avatar")
    avatar = avatar_raw if isinstance(avatar_raw, dict) else {}
    look = (
        _str(row.get("look"))
        or _str(avatar.get("look"))
        or (avatar_raw if isinstance(avatar_raw, str) else "")
    )
    figure = row.get("figure") if isinstance(row.get("figure"), dict) else avatar
    return {
        "agent_id": agent_id,
        "name": _str(row.get("name")),
        "title": _str(row.get("title")),
        "tier": _str(row.get("tier"), "specialist"),
        "lifecycle": lifecycle,
        "run_state": run_state,
        "waiting_reason": reason if isinstance(reason, str) else None,
        "duty": duty,
        "level": level,
        "rank": rank_of(level),
        "look": look,
        "figure": {
            "archetype": _str(figure.get("archetype"), "crew"),
            "palette": _str(figure.get("palette"), "graphite"),
        },
        "team_ids": sorted(teams.get(agent_id, [])),
        "pane": panes_by_agent.get(agent_id),
    }


def pane_row(row: dict[str, Any], active_id: str | None = None) -> dict[str, Any] | None:
    """One ``WorkspacePaneRow`` as contract 4.2 sends it, or None when it has no id."""
    workspace_id = _str(row.get("workspace_id"))
    key = _str(row.get("key")) or _str(row.get("name"))
    if not workspace_id or not key or ":" in workspace_id or ":" in key:
        return None
    since = row.get("activity_since")
    pane = {
        "pane_id": f"{workspace_id}:{key}",
        "workspace_id": workspace_id,
        "key": key,
        "history_id": row.get("history_id") if isinstance(row.get("history_id"), str) else None,
        "name": _str(row.get("name"), key),
        "display_name": _str(row.get("display_name")) or _str(row.get("agent")),
        "agent": _str(row.get("agent")),
        "title": _str(row.get("title")),
        "status": or_fallback(row.get("status"), PANE_STATUSES, "pending"),
        "activity": or_fallback(row.get("activity"), PANE_ACTIVITIES, "unknown"),
        "activity_since": float(since) if isinstance(since, int | float) and since else None,
        "worked": bool(row.get("worked")),
        "duty": "idle",
        "workspace_active": bool(
            row.get("workspace_active", active_id is not None and workspace_id == active_id)
        ),
        "cols": max(1, int(row.get("cols") or 80)),
        "rows": max(1, int(row.get("rows") or 24)),
    }
    pane["duty"] = pane_duty(pane)
    return pane


class RosterRelay(RelayBase):
    topics = ("roster", "panes")

    def __init__(self, session: Any, backend: Any) -> None:
        super().__init__(session, backend)
        self.agents_raw: list[dict[str, Any]] = []
        self.panes: dict[str, dict[str, Any]] = {}
        self.levels: dict[str, int] = {}
        self.titles: dict[str, str] = {}
        self.errors: set[str] = set()
        self.overrides: dict[str, str] = {}
        self.teams: dict[str, list[str]] = {}
        self.sent_agents: dict[str, dict[str, Any]] | None = None
        self.sent_panes: dict[str, dict[str, Any]] = {}
        self.sent_commander: dict[str, Any] | None = None
        self.uniform = "standard"
        self._agents_later = Coalescer(self, self._reread_agents, AGENT_REREAD_S)

    # ------------------------------------------------------------------ wiring
    async def start(self) -> None:
        from dodaios.core import events as E

        society = [
            E.SocietyRoomChanged,
            E.SocietyMessageSent,
            E.SocietyTeamChanged,
            E.SocietyCheckpointChanged,
        ]
        self.listen(society, self._on_society)
        self.listen([E.SocietyResultPosted], self._on_result)
        self.listen([E.AgenticIdePaneActivity], self._on_pane_activity)
        self.listen(
            [E.AgenticIdeTerminalsAdded, E.AgenticIdeTerminalsClosed, E.AgenticIdeWorkspaceChanged],
            self._on_panes_changed,
        )
        self.listen([E.ProgressionAwarded], self._on_award)
        self.every(SAFETY_REREAD_S, self._safety)

    async def subscribe(self, topic: str) -> None:
        if topic == "roster":
            await self._read_all()
            self.sent_agents = None
            self._emit(snapshot=True)

    async def unsubscribe(self, topic: str) -> None:
        if topic == "roster":
            self.sent_agents = None

    # ------------------------------------------------------------------ reads
    async def _read_agents(self) -> None:
        try:
            self.agents_raw = await self.backend.list_agents()
        except Exception:  # noqa: BLE001
            log.warning("verse roster: agent read failed", exc_info=True)

    async def _read_panes(self) -> None:
        try:
            rows = await self.backend.list_panes()
        except Exception:  # noqa: BLE001
            log.warning("verse roster: pane read failed", exc_info=True)
            return
        panes = {}
        for raw in rows:
            if raw.get("archived"):
                continue
            pane = pane_row(raw)
            if pane is not None:
                panes[pane["pane_id"]] = pane
        self.panes = panes

    async def _read_levels(self) -> None:
        try:
            prog = await self.backend.progression()
        except Exception:  # noqa: BLE001
            log.warning("verse roster: progression read failed", exc_info=True)
            return
        levels, titles = {}, {}
        for s in prog.get("subjects", []):
            sid = s.get("subject_id")
            if isinstance(sid, str):
                levels[sid] = int(s.get("level") or 1)
                titles[sid] = _str(s.get("title"))
        self.levels, self.titles = levels, titles

    async def _read_teams(self) -> None:
        try:
            groups = await self.backend.chat_groups()
        except Exception:  # noqa: BLE001
            return
        teams: dict[str, list[str]] = {}
        for g in groups:
            gid = g.get("group_id") or g.get("id")
            for member in g.get("members") or g.get("member_ids") or []:
                mid = member.get("agent_id") if isinstance(member, dict) else member
                if isinstance(mid, str) and isinstance(gid, str):
                    teams.setdefault(mid, []).append(gid)
        self.teams = teams

    async def _read_all(self) -> None:
        await self._read_agents()
        await self._read_panes()
        await self._read_levels()
        await self._read_teams()

    # ------------------------------------------------------------------ view
    def commander(self) -> dict[str, Any]:
        level = self.levels.get("person", 1)
        return {
            "subject_id": "person",
            "level": level,
            "rank": rank_of(level),
            "title": self.titles.get("person", ""),
            "uniform": self.uniform,
        }

    def view_agents(self) -> dict[str, dict[str, Any]]:
        panes_by_agent: dict[str, str] = {}
        out: dict[str, dict[str, Any]] = {}
        for raw in self.agents_raw:
            if str(raw.get("state", "active")) == "archived":
                continue
            row = agent_row(
                raw,
                levels=self.levels,
                errors=self.errors,
                overrides=self.overrides,
                panes_by_agent=panes_by_agent,
                teams=self.teams,
            )
            if row["agent_id"]:
                out[row["agent_id"]] = row
        return out

    def snapshot(self) -> dict[str, Any]:
        agents = self.view_agents()
        self.sent_agents = agents
        self.sent_panes = {k: dict(v) for k, v in self.panes.items()}
        self.sent_commander = self.commander()
        return {
            "commander": self.sent_commander,
            "agents": list(agents.values()),
            "panes": list(self.sent_panes.values()),
        }

    def _emit(self, snapshot: bool = False) -> None:
        if "roster" not in self.subscribed:
            return
        self.session.outbox.snapshot_of["roster"] = self.snapshot
        if snapshot or self.sent_agents is None:
            self.session.send("roster.snapshot", self.snapshot, topic="roster", feed=True)
            return
        agents = self.view_agents()
        up_a, rm_a = diff_rows(self.sent_agents, agents, "agent_id")
        up_p, rm_p = diff_rows(self.sent_panes, self.panes, "pane_id")
        commander = self.commander()
        cmd_changed = commander != self.sent_commander
        if not (up_a or rm_a or up_p or rm_p or cmd_changed):
            return
        self.sent_agents = agents
        self.sent_panes = {k: dict(v) for k, v in self.panes.items()}
        self.sent_commander = commander
        data = {
            "upsert": {"agents": up_a, "panes": up_p},
            "remove": {"agents": rm_a, "panes": rm_p},
            "commander": commander if cmd_changed else None,
        }
        self.session.send("roster.delta", data, topic="roster", delta=True, feed=True)

    # ------------------------------------------------------------------ triggers
    async def _reread_agents(self) -> None:
        await self._read_agents()
        await self._read_teams()
        self._emit()

    async def _on_society(self, _event: Any) -> None:
        self._agents_later.poke()

    async def _on_result(self, event: Any) -> None:
        agent_id = getattr(event, "agent_id", "")
        if getattr(event, "status", "") == "blocked":
            self.errors.add(agent_id)
        else:
            self.errors.discard(agent_id)
        self._agents_later.poke()

    async def _on_pane_activity(self, event: Any) -> None:
        pane_id = f"{getattr(event, 'session_id', '')}:{getattr(event, 'key', '')}"
        pane = self.panes.get(pane_id)
        if pane is None:
            await self._read_panes()
        else:
            pane["status"] = or_fallback(
                getattr(event, "status", ""), PANE_STATUSES, pane["status"]
            )
            pane["activity"] = or_fallback(
                getattr(event, "activity", ""), PANE_ACTIVITIES, "unknown"
            )
            since = getattr(event, "activity_since", 0.0)
            pane["activity_since"] = float(since) if since else None
            pane["worked"] = bool(getattr(event, "worked", pane["worked"]))
            pane["duty"] = pane_duty(pane)
        self._emit()

    async def _on_panes_changed(self, _event: Any) -> None:
        await self._read_panes()
        self._emit()

    async def _on_award(self, _event: Any) -> None:
        await self._read_levels()
        self._emit()

    async def _safety(self) -> None:
        if "roster" not in self.subscribed:
            return
        await self._read_all()
        self._emit()

    # ------------------------------------------------------------------ QA
    async def qa_set_duty(self, agent_id: str, duty: str) -> dict[str, Any]:
        if duty not in P.DUTY_STATUSES:
            raise P.BridgeError("bad_request", f"Unknown duty {duty!r}.")
        self.overrides[agent_id] = duty
        self._emit()
        return {"agent_id": agent_id, "duty": duty}
