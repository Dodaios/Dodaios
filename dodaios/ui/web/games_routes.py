"""REST API for Game settings — per-game profiles and the sensitivity converter.

Endpoints (mounted by the WebServer in ``_build_app()``):

    GET    /api/games                  → every game in the catalog (summary),
                                         which ones have a saved profile, and
                                         the default mouse DPI.
    GET    /api/games/{id}             → one game's full definition + profile.
    PUT    /api/games/{id}/profile     → merge values / keybinds / dpi / notes.
    DELETE /api/games/{id}/profile     → forget the profile (back to defaults).
    PUT    /api/games/dpi              → the default mouse DPI.
    POST   /api/games/convert          → a hip-fire sensitivity in every other
                                         game with the same cm/360.

No brain, no config file: the profiles live in ``<DATA_DIR>/games`` (see
``dodaios.games.store``), so this works headless too.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dodaios.games import sensitivity
from dodaios.games.catalog import get_game, list_games
from dodaios.games.store import GameProfileStore, UnknownGameError

router = APIRouter(prefix="/api/games", tags=["games"])


def _store() -> GameProfileStore:
    # Built per request so DATA_DIR is read at call time (tests patch it).
    return GameProfileStore()


def _summary(game: dict[str, Any], profiles: dict[str, Any]) -> dict[str, Any]:
    profile = profiles.get(game["id"])
    return {
        "id": game["id"],
        "name": game["name"],
        "publisher": game["publisher"],
        "convertible": bool(game.get("yaw") and game.get("sens_key")),
        "has_profile": profile is not None,
        "updated_at": profile.get("updated_at") if profile else None,
    }


@router.get("")
def games_index() -> dict[str, Any]:
    data = _store().snapshot()
    return {
        "dpi": data["dpi"],
        "games": [_summary(g, data["games"]) for g in list_games()],
    }


class DpiBody(BaseModel):
    dpi: int


@router.put("/dpi")
def set_dpi(body: DpiBody) -> dict[str, Any]:
    try:
        return {"dpi": _store().set_default_dpi(body.dpi)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ConvertBody(BaseModel):
    game_id: str
    sens: float
    dpi: int | None = None
    to_dpi: int | None = None


@router.post("/convert")
def convert(body: ConvertBody) -> dict[str, Any]:
    source = get_game(body.game_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown game")
    if not source.get("yaw"):
        raise HTTPException(
            status_code=400,
            detail=f"{source['name']} has no linear sensitivity, so it cannot be converted.",
        )
    default_dpi = _store().snapshot()["dpi"]
    dpi = body.dpi or default_dpi
    to_dpi = body.to_dpi or dpi
    try:
        cm = sensitivity.cm_per_360(source["yaw"], body.sens, dpi)
        results = []
        for game in list_games():
            if game["id"] == source["id"] or not game.get("yaw") or not game.get("sens_key"):
                continue
            value = sensitivity.convert(body.sens, source["yaw"], game["yaw"], dpi, to_dpi)
            results.append(
                {
                    "id": game["id"],
                    "name": game["name"],
                    "sens_key": game["sens_key"],
                    "sens": round(value, 4),
                    "edpi": round(value * to_dpi, 1),
                }
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "game_id": source["id"],
        "sens": body.sens,
        "dpi": dpi,
        "to_dpi": to_dpi,
        "cm_per_360": round(cm, 2),
        "edpi": round(body.sens * dpi, 1),
        "results": results,
    }


@router.get("/{game_id}")
def game_detail(game_id: str) -> dict[str, Any]:
    game = get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Unknown game")
    store = _store()
    return {"game": game, "profile": store.profile(game_id), "default_dpi": store.snapshot()["dpi"]}


class ProfileBody(BaseModel):
    values: dict[str, Any] | None = None
    keybinds: dict[str, str | None] | None = None
    dpi: int | None = None
    # Distinguishes "dpi": null (follow the default) from leaving dpi out.
    reset_dpi: bool = False
    notes: str | None = None


@router.put("/{game_id}/profile")
def save_profile(game_id: str, body: ProfileBody) -> dict[str, Any]:
    dpi: Any = ...
    if body.reset_dpi:
        dpi = None
    elif body.dpi is not None:
        dpi = body.dpi
    try:
        profile = _store().update(
            game_id, values=body.values, keybinds=body.keybinds, dpi=dpi, notes=body.notes
        )
    except UnknownGameError as exc:
        raise HTTPException(status_code=404, detail="Unknown game") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"profile": profile}


@router.delete("/{game_id}/profile")
def reset_profile(game_id: str) -> dict[str, Any]:
    try:
        return {"removed": _store().reset(game_id)}
    except UnknownGameError as exc:
        raise HTTPException(status_code=404, detail="Unknown game") from exc
