"""Designs: the person's own colours and animated background (docs/designs.md).

    GET    /api/designs              -> every design, the active id, what a design may set
    POST   /api/designs              -> make a design, or change one of the person's own
    PUT    /api/designs/active       -> switch to a design ("standard" = the app's own look)
    POST   /api/designs/reset        -> back to the standard look
    DELETE /api/designs/{design_id}  -> delete one of the person's own designs

Every change is announced as ``UiDesignChanged`` so every open window repaints
at once, whether the settings page or Dodaios made it. Designs live in each
instance's own data directory, so the Dev app never changes the person's app.
The design store is imported inside the handlers: nothing here loads on the
boot path.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/designs", tags=["designs"])


class SaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None,
        max_length=64,
        description="Change this design of yours; leave out to make a new one.",
    )
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=600)
    dark: dict[str, str] | None = None
    light: dict[str, str] | None = None
    background: dict[str, Any] | None = None
    apply: bool = Field(default=True, description="Switch to the design right away.")


class ActiveBody(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)


def _schema() -> dict[str, Any]:
    from dodaios.ui.designs import store

    return {
        "color_keys": list(store.COLOR_KEYS),
        "required_keys": list(store.REQUIRED_KEYS),
        "background_styles": list(store.BACKGROUND_STYLES),
        "speeds": list(store.SPEEDS),
    }


async def _announce(request: Request, active: str) -> None:
    bus = getattr(request.app.state, "bus", None)
    if bus is None:
        return
    try:
        from dodaios.core.events import UiDesignChanged

        await bus.publish(UiDesignChanged(active=active))
    except Exception as exc:  # noqa: BLE001 - a bus hiccup must not fail the write
        log.warning("UiDesignChanged publish failed: %s", exc)


def _bad(exc: Exception) -> HTTPException:
    from dodaios.ui.designs.store import DesignNotFound

    return HTTPException(
        status_code=404 if isinstance(exc, DesignNotFound) else 400, detail=str(exc)
    )


@router.get("")
async def list_designs() -> dict[str, Any]:
    """Every design (built-in first), the active one, and what a design may set."""
    from dodaios.ui.designs import store

    state = await asyncio.to_thread(store.load_state)
    return {**state, "schema": _schema()}


@router.post("")
async def save_design(body: SaveBody, request: Request) -> dict[str, Any]:
    """Make a design, or change one of the person's own; switches to it unless ``apply`` is off."""
    from dodaios.ui.designs import store

    payload = body.model_dump(exclude={"apply"}, exclude_unset=True)
    try:
        design, state = await asyncio.to_thread(store.save_design, payload, apply=body.apply)
    except (store.DesignError, store.DesignNotFound) as exc:
        raise _bad(exc) from exc
    await _announce(request, state["active"])
    return {
        "ok": True,
        "active": state["active"],
        "applied": state["active"] == design["id"],
        "design": design,
        "state": state,
    }


@router.put("/active")
async def put_active(body: ActiveBody, request: Request) -> dict[str, Any]:
    """Switch to a design; ``"standard"`` goes back to the app's own look."""
    from dodaios.ui.designs import store

    try:
        state = await asyncio.to_thread(store.set_active, body.id)
    except store.DesignNotFound as exc:
        raise _bad(exc) from exc
    await _announce(request, state["active"])
    return {"ok": True, "active": state["active"], "state": state}


@router.post("/reset")
async def reset_design(request: Request) -> dict[str, Any]:
    """Back to the standard look. The person's designs stay in the list."""
    from dodaios.ui.designs import store

    state = await asyncio.to_thread(store.set_active, store.STANDARD_ID)
    await _announce(request, state["active"])
    return {"ok": True, "active": state["active"], "state": state}


@router.delete("/{design_id}")
async def delete_design(design_id: str, request: Request) -> dict[str, Any]:
    """Delete one of the person's own designs; built-in ones stay."""
    from dodaios.ui.designs import store

    try:
        state = await asyncio.to_thread(store.delete_design, design_id)
    except (store.DesignError, store.DesignNotFound) as exc:
        raise _bad(exc) from exc
    await _announce(request, state["active"])
    return {"ok": True, "active": state["active"], "deleted": design_id, "state": state}
