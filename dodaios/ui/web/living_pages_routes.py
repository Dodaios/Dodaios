"""HTTP API of living pages (:mod:`dodaios.artifacts.living`).

* ``GET  /api/living-pages``                 every living page, newest first.
* ``GET  /api/living-pages/by-slug/{slug}``  the page behind an Artifacts run.
* ``GET  /api/living-pages/{id}``            one page.
* ``POST /api/living-pages/{id}/stop``       stop the refresh; the rows stay.
* ``POST /api/living-pages/{id}/resume``     start the refresh again.

The Artifacts stage reads the page's state from here to show "updated 10
minutes ago" and the stop control above the page: the page itself runs in a
sandbox with no network, so the control lives in the app. Nothing here calls
a model.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dodaios.artifacts import living_refresh
from dodaios.artifacts.living import (
    MAX_EVERY_MINUTES,
    MIN_EVERY_MINUTES,
    LivingPage,
    LivingPageError,
    LivingPageStore,
)

router = APIRouter(prefix="/api/living-pages", tags=["living-pages"])

_store: LivingPageStore | None = None


def get_store() -> LivingPageStore:
    global _store
    if _store is None:
        _store = LivingPageStore()
    return _store


def set_store(store: LivingPageStore | None) -> None:
    """Swap the store (tests)."""
    global _store
    _store = store


class ResumeBody(BaseModel):
    every_minutes: int | None = Field(default=None, ge=MIN_EVERY_MINUTES, le=MAX_EVERY_MINUTES)


async def _page_or_404(page: LivingPage | None) -> dict[str, Any]:
    if page is None:
        raise HTTPException(status_code=404, detail="unknown living page")
    return await living_refresh.page_state(get_store(), page)


@router.get("")
async def list_living_pages() -> dict[str, Any]:
    pages = await asyncio.to_thread(get_store().list_pages)
    return {"pages": [await living_refresh.page_state(get_store(), p) for p in pages]}


@router.get("/by-slug/{slug}")
async def living_page_by_slug(slug: str) -> dict[str, Any]:
    return await _page_or_404(await asyncio.to_thread(get_store().by_slug, slug))


@router.get("/{page_id}")
async def living_page(page_id: str) -> dict[str, Any]:
    return await _page_or_404(await asyncio.to_thread(get_store().get, page_id))


@router.post("/{page_id}/stop")
async def stop_living_page(page_id: str) -> dict[str, Any]:
    try:
        page = await living_refresh.stop_refresh(get_store(), page_id)
    except LivingPageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await living_refresh.page_state(get_store(), page)


@router.post("/{page_id}/resume")
async def resume_living_page(page_id: str, body: ResumeBody | None = None) -> dict[str, Any]:
    store = get_store()
    try:
        if body is not None and body.every_minutes is not None:
            await asyncio.to_thread(store.set_every, page_id, body.every_minutes)
        page = await living_refresh.start_refresh(store, page_id)
    except LivingPageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return await living_refresh.page_state(store, page)


__all__ = ["get_store", "router", "set_store"]
