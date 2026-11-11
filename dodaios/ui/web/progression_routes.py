"""REST API of the Dodaios Verse level system (``dodaios/progression``).

- ``GET  /api/progression``          → every subject's level, the rulebook and recent awards
- ``GET  /api/progression/duels``    → duel totals and the most recent duel sets
- ``POST /api/progression/actions``  → report a world action from the Verse (metered server-side)

Duel XP is never a world action: ``duel_won``, ``duel_lost`` and
``duel_finisher`` are server rules that only a ``duel.result`` pays
(``ProgressionService.record_duel``), so ``/actions`` refuses them.

Live awards travel as ``ProgressionAwarded`` over the WebSocket; this API is
the first read and the catch-up after a reconnect.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from dodaios.progression.rules import (
    LOOK_UNLOCKS,
    MAX_LEVEL,
    RANKS,
    REWARDS,
    RULES,
    TITLES,
    VERSE_DECKS,
    total_xp_for_level,
)
from dodaios.progression.service import ProgressionService, UnknownAction

router = APIRouter(prefix="/api/progression", tags=["progression"])


def _service(request: Request) -> ProgressionService:
    service = getattr(request.app.state, "progression", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Level system not available")
    return service


def _rulebook() -> dict[str, Any]:
    return {
        "max_level": MAX_LEVEL,
        "level_xp": [total_xp_for_level(level) for level in range(1, MAX_LEVEL + 1)],
        "rules": [
            {
                "source": r.source,
                "kind": r.kind,
                "xp": r.xp,
                "trigger": r.trigger,
                "cooldown_s": r.cooldown_s,
                "daily_cap": r.daily_cap,
            }
            for r in RULES
        ],
        "rewards": [
            {
                "reward_id": r.reward_id,
                "slot": r.slot,
                "levels": {"person": r.person, "agent": r.agent, "pet": r.pet},
            }
            for r in REWARDS
        ],
        "ranks": [{"id": rank, "level": level, "tier": tier} for level, rank, tier in RANKS],
        "decks": list(VERSE_DECKS),
        "looks": [{"look_id": look, "agent": level} for look, level in LOOK_UNLOCKS.items()],
        "titles": {
            kind: [{"level": lvl, "title": t} for lvl, t in bands]
            for kind, bands in TITLES.items()
        },
    }


@router.get("", summary="Levels of the person, the pet and every agent")
async def get_progression(
    request: Request,
    after_seq: int = Query(0, ge=0, description="Only awards newer than this sequence number"),
) -> dict[str, Any]:
    service = _service(request)
    subjects, recent, latest, duel_stats = await asyncio.gather(
        asyncio.to_thread(service.snapshot),
        asyncio.to_thread(service.store.recent, after_seq=after_seq, limit=50),
        asyncio.to_thread(service.store.latest_seq),
        asyncio.to_thread(service.duel_stats),
    )
    return {
        "subjects": subjects,
        "pet_id": service.current_pet(),
        "recent": recent,
        "latest_seq": latest,
        "duel_stats": duel_stats,
        **_rulebook(),
    }


@router.get("/duels", summary="Duel totals and the most recent duel sets, newest first")
async def get_duels(
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="How many recent sets to list"),
) -> dict[str, Any]:
    service = _service(request)
    duels, duel_stats = await asyncio.gather(
        asyncio.to_thread(service.recent_duels, limit),
        asyncio.to_thread(service.duel_stats),
    )
    return {"duels": duels, "duel_stats": duel_stats}


class WorldAction(BaseModel):
    action: str = Field(..., max_length=40, description="A world-action source from the rulebook")
    ref: str = Field(
        "", max_length=40, description="The action's subject: a deck, a team or a game"
    )


@router.post("/actions", summary="Report a small action inside the Dodaios Verse")
async def post_action(body: WorldAction, request: Request) -> dict[str, Any]:
    service = _service(request)
    try:
        award = await service.report_action(body.action, ref=body.ref)
    except UnknownAction as exc:
        raise HTTPException(status_code=422, detail=f"unknown action: {exc}") from exc
    return {"awarded": award.to_dict() if award is not None else None}
