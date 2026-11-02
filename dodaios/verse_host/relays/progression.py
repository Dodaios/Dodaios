"""Progression relay (BW7, contract 9, 10 and 14): levels, awards, world actions.

``progression.snapshot`` on subscribe (with ``told_seq`` and the duel
totals), every ``ProgressionAwarded`` forwarded field for field as
``progression.awarded`` (an event: never dropped), ``progression.action``
onto the rulebook's world actions, ``progression.told`` stored, and
``duel.result`` handed to the duel service of WP21 (``unavailable`` until it
is installed).
"""

from __future__ import annotations

import logging
from typing import Any

from .. import protocol as P
from ..ports import UnknownWorldAction
from .base import RelayBase

log = logging.getLogger(__name__)

WORLD_ACTIONS = (
    "daily_visit",
    "deck_discovered",
    "inspection",
    "walk_together",
    "team_briefing",
    "simulator_round",
    "simulator_record",
)
EMPTY_DUEL_STATS: dict[str, Any] = {
    "matches": 0,
    "wins": 0,
    "losses": 0,
    "unfinished": 0,
    "kills": 0,
    "deaths": 0,
    "headshots": 0,
    "finishers": 0,
    "best_streak": 0,
    "by_tier": {},
}


def subject_row(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_id": str(s.get("subject_id")),
        "kind": str(s.get("kind") or "person"),
        "level": max(1, int(s.get("level") or 1)),
        "total_xp": max(0, int(s.get("total_xp", s.get("xp", 0)) or 0)),
        "into_level": max(0, int(s.get("into_level", s.get("xp_into_level", 0)) or 0)),
        "for_next": max(0, int(s.get("for_next", s.get("xp_for_next", 0)) or 0)),
        "title": str(s.get("title") or ""),
    }


def rulebook(prog: dict[str, Any]) -> dict[str, Any]:
    titles: dict[str, str] = {}
    raw_titles = prog.get("titles") or {}
    if isinstance(raw_titles, dict):
        for kind, bands in raw_titles.items():
            if isinstance(bands, list):
                for band in bands:
                    if isinstance(band, dict):
                        titles[f"{kind}.{band.get('level')}"] = str(band.get("title", ""))
            elif isinstance(bands, str):
                titles[str(kind)] = bands
    return {
        "ranks": [
            {"id": r["id"], "level": int(r["level"]), "tier": r["tier"]}
            for r in prog.get("ranks", [])
            if isinstance(r, dict)
        ],
        "rewards": [r for r in prog.get("rewards", []) if isinstance(r, dict)],
        "looks": [r for r in prog.get("looks", []) if isinstance(r, dict)],
        "titles": titles,
    }


def award_data(event: Any) -> dict[str, Any]:
    """``ProgressionAwarded`` as it is (contract 9), without the bus envelope fields."""
    return {
        "seq": int(event.seq),
        "subject_id": str(event.subject_id),
        "subject_kind": str(event.subject_kind),
        "xp_source": str(event.xp_source),
        "xp": int(event.xp),
        "total_xp": int(event.total_xp),
        "level": int(event.level),
        "previous_level": int(event.previous_level),
        "title": str(event.title),
        "unlocked": list(event.unlocked),
        "unlocked_looks": list(event.unlocked_looks),
    }


class ProgressionRelay(RelayBase):
    topics = ("progression", "duel_stats")

    def __init__(self, session: Any, backend: Any, store: Any) -> None:
        super().__init__(session, backend)
        self.store = store

    async def start(self) -> None:
        from dodaios.core import events as E

        hub = self.session.hub
        hub.command("progression.action", self._action)
        hub.command("progression.told", self._told)
        hub.command("duel.result", self._duel)
        self.listen([E.ProgressionAwarded], self._on_award)

    async def subscribe(self, topic: str) -> None:
        if topic == "progression":
            self.session.send("progression.snapshot", await self.snapshot(), topic="progression")

    async def duel_stats(self) -> dict[str, Any]:
        service = self.backend.duel_service()
        if service is None:
            return dict(EMPTY_DUEL_STATS)
        try:
            stats = service.duel_stats()
            if hasattr(stats, "__await__"):
                stats = await stats
            return dict(stats) if isinstance(stats, dict) else dict(EMPTY_DUEL_STATS)
        except Exception:  # noqa: BLE001
            log.warning("verse progression: duel stats read failed", exc_info=True)
            return dict(EMPTY_DUEL_STATS)

    async def snapshot(self) -> dict[str, Any]:
        prog = await self.backend.progression()
        subjects = [subject_row(s) for s in prog.get("subjects", []) if s.get("subject_id")]
        pet = prog.get("pet_id")
        return {
            "subjects": subjects,
            "pet_id": pet if isinstance(pet, str) and pet else None,
            "latest_seq": max(0, int(prog.get("latest_seq") or 0)),
            "told_seq": self.store.told_seq(),
            "rulebook": rulebook(prog),
            "duel_stats": prog.get("duel_stats") or await self.duel_stats(),
        }

    async def _on_award(self, event: Any) -> None:
        if "progression" in self.subscribed:
            self.session.send("progression.awarded", award_data(event), topic=None)

    # ------------------------------------------------------------------ commands
    async def _action(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        action, ref = msg.data.get("action"), msg.data.get("ref", "")
        if not isinstance(action, str) or not isinstance(ref, str) or len(ref) > 40:
            raise P.BridgeError("bad_request", "progression.action needs action and ref.")
        if action in ("duel_won", "duel_lost", "duel_finisher") or action not in WORLD_ACTIONS:
            raise P.BridgeError("bad_request", f"{action} is not a world action.")
        try:
            award = await self.backend.report_action(action, ref)
        except UnknownWorldAction as exc:
            raise P.BridgeError("bad_request", str(exc)) from exc
        return {"awarded": award}

    async def _told(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        seq = msg.data.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise P.BridgeError("bad_request", "seq must be a non-negative integer.")
        return {"told_seq": self.store.raise_told_seq(seq)}

    async def _duel(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        service = self.backend.duel_service()
        if service is None:
            raise P.BridgeError("unavailable", "Duel results are not recorded yet.")
        data = msg.data
        if not isinstance(data.get("match_id"), str) or data.get("outcome") not in (
            "won",
            "lost",
            "unfinished",
        ):
            raise P.BridgeError("bad_request", "duel.result needs match_id and outcome.")
        result = service.record_duel(data)
        if hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, dict):
            raise P.BridgeError("internal", "The duel service gave no answer.")
        return {
            "recorded": bool(result.get("recorded", True)),
            "awards": [
                {"xp_source": str(a.get("xp_source")), "xp": int(a.get("xp", 0))}
                for a in result.get("awards", [])
                if isinstance(a, dict)
            ],
            "duel_stats": result.get("duel_stats") or await self.duel_stats(),
        }
