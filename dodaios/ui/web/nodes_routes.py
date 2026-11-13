"""HTTP API of nodes (:mod:`dodaios.nodes`, ``docs/nodes.md``).

* ``GET    /api/nodes``                      the library: every card (``?scan=<n>``).
* ``GET    /api/nodes/types``                the node types and their spec guides.
* ``GET    /api/nodes/by-slug/{slug}``       the typed node behind a run, with its spec.
* ``GET    /api/nodes/{id}``                 one typed node, with its spec.
* ``POST   /api/nodes``                      a new node from its type's starter.
* ``PATCH  /api/nodes/{id}``                 rename.
* ``POST   /api/nodes/{id}/edit``            one value the person typed into the page.
* ``POST   /api/nodes/{id}/duplicate``       a second node with the same content.
* ``POST   /api/nodes/{id}/revert``          put the previous version back.
* ``POST   /api/nodes/{id}/upkeep/stop``     stop keeping it current; the content stays.
* ``POST   /api/nodes/{id}/upkeep/resume``   keep it current again.
* ``DELETE /api/nodes/{id}``                 remove the node, its page and its history.

The library is what the app's Nodes section shows: the typed nodes plus what
older runs left behind (:mod:`dodaios.nodes.library`). The routes that change
something only reach typed nodes; an adopted file is still deleted through
``/api/outputs``. A node's content is written by the assistant through the
``node`` tool, and by the person one value at a time in the stage's edit mode
(``/edit``, :mod:`dodaios.nodes.edit`). Nothing here calls a model.

A node's page runs in a sandbox with no network, so everything a person does
TO a node (stop its upkeep, rename it) is a control of the app and a route here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from dodaios.nodes import library, refresh
from dodaios.nodes.edit import KINDS, apply_field
from dodaios.nodes.kinds import kind_of
from dodaios.nodes.model import Node
from dodaios.nodes.store import MAX_EVERY_MINUTES, MIN_EVERY_MINUTES, NodeStore
from dodaios.nodes.types import MAX_TITLE_CHARS, NODE_TYPES, NodeError, node_type
from dodaios.ui.web import living_pages_routes

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

#: What a node made from the library's "new" row is called until it is renamed.
DEFAULT_TITLES: Final[dict[str, str]] = {
    "docs": "Untitled document",
    "slides": "Untitled deck",
    "sheets": "Untitled sheet",
    "design": "Untitled design",
    "data": "Untitled dashboard",
    "whiteboard": "Untitled whiteboard",
    "motion": "Untitled animation",
}

_store: NodeStore | None = None


def get_store() -> NodeStore:
    global _store
    if _store is None:
        _store = NodeStore()
    return _store


def set_store(store: NodeStore | None) -> None:
    """Swap the store (tests)."""
    global _store
    _store = store


class CreateBody(BaseModel):
    type: str
    title: str | None = Field(default=None, max_length=400)
    language: str | None = Field(default=None, max_length=16)


class RenameBody(BaseModel):
    title: str = Field(max_length=400)


class EditBody(BaseModel):
    """One value typed into the page: where it goes and what it is."""

    path: str = Field(min_length=1, max_length=400)
    value: Any = None
    kind: str = Field(default="text", alias="as")

    model_config = {"populate_by_name": True}


class DuplicateBody(BaseModel):
    title: str | None = Field(default=None, max_length=400)


class ResumeBody(BaseModel):
    every_minutes: int | None = Field(default=None, ge=MIN_EVERY_MINUTES, le=MAX_EVERY_MINUTES)


async def _checked(node: Node) -> Node:
    """The node with ``refreshing`` as the scheduler sees it right now."""
    return replace(node, refreshing=await refresh.refresh_live(node))


async def _card(node: Node) -> dict[str, Any]:
    """One node's library card."""
    return await asyncio.to_thread(library.node_card, await _checked(node), get_store())


async def _require(node_id: str) -> Node:
    node = await asyncio.to_thread(get_store().get, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="unknown node")
    return node


async def _state_or_404(node: Node | None, *, with_spec: bool = True) -> dict[str, Any]:
    if node is None:
        raise HTTPException(status_code=404, detail="unknown node")
    return await refresh.node_state(node, with_spec=with_spec)


def _known_types() -> list[dict[str, str]]:
    types: list[dict[str, str]] = []
    for name in NODE_TYPES:
        try:
            types.append({"type": name, "guide": kind_of(name).guide})
        except Exception:  # noqa: BLE001 - one broken renderer must not hide the other types
            log.warning("node type %s is not available", name, exc_info=True)
    return types


@router.get("")
async def list_nodes(request: Request, scan: int = library.DEFAULT_SCAN_LIMIT) -> dict[str, Any]:
    """The library: typed nodes and everything adopted from older runs."""
    store = get_store()
    runs = await library.list_runs(request)
    nodes = [await _checked(node) for node in await asyncio.to_thread(store.list_nodes)]
    return await asyncio.to_thread(
        library.build_library,
        request,
        runs=runs,
        nodes=nodes,
        store=store,
        living_store=living_pages_routes.get_store(),
        scan_limit=max(1, min(library.MAX_SCAN_LIMIT, scan)),
    )


@router.get("/types")
async def list_node_types() -> dict[str, Any]:
    """Every node type that can be made here, with the grammar of its spec."""
    return {"types": await asyncio.to_thread(_known_types)}


@router.get("/by-slug/{slug}")
async def node_by_slug(slug: str, spec: bool = True) -> dict[str, Any]:
    # ``?spec=0``: the stage asks every few seconds whether the open node
    # changed, and has no use for its content.
    return await _state_or_404(
        await asyncio.to_thread(get_store().by_slug, slug), with_spec=spec
    )


@router.get("/{node_id}")
async def get_node(node_id: str, spec: bool = True) -> dict[str, Any]:
    return await _state_or_404(await asyncio.to_thread(get_store().get, node_id), with_spec=spec)


@router.post("")
async def create_node(body: CreateBody) -> dict[str, Any]:
    """A new node of ``type``, filled with the type's starter content."""
    try:
        name = node_type(body.type)
        node = await asyncio.to_thread(
            lambda: get_store().create(
                type=name,
                title=(body.title or "").strip() or DEFAULT_TITLES[name],
                spec=None,
                language=(body.language or "").strip() or "en",
            )
        )
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _card(node)


@router.patch("/{node_id}")
async def rename_node(node_id: str, body: RenameBody) -> dict[str, Any]:
    node = await _require(node_id)
    # The store refuses a revision that changes nothing; a rename to the name
    # the node already has is simply done.
    if " ".join(body.title.split())[:MAX_TITLE_CHARS] != node.title:
        try:
            node = await asyncio.to_thread(lambda: get_store().update(node_id, title=body.title))
        except NodeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _card(node)


@router.post("/{node_id}/duplicate")
async def duplicate_node(node_id: str, body: DuplicateBody | None = None) -> dict[str, Any]:
    await _require(node_id)
    title = (body.title if body is not None else None) or ""
    try:
        copy = await asyncio.to_thread(lambda: get_store().duplicate(node_id, title=title))
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _card(copy)


@router.post("/{node_id}/edit")
async def edit_node(node_id: str, body: EditBody) -> dict[str, Any]:
    """Save one value the person typed into the node's page.

    Answers with the node's state (without its spec): its new ``version`` and
    ``updated_at`` tell the stage which revision the page now shows. A value
    the type does not accept is a 400 with the reason, and the node stays as
    it was.
    """
    node = await _require(node_id)
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"'as' must be one of: {', '.join(KINDS)}.")
    try:
        saved = await asyncio.to_thread(
            apply_field, get_store(), node, body.path, body.value, body.kind
        )
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await refresh.node_state(saved, with_spec=False)


@router.post("/{node_id}/revert")
async def revert_node(node_id: str) -> dict[str, Any]:
    await _require(node_id)
    try:
        node = await asyncio.to_thread(get_store().revert, node_id)
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _card(node)


@router.post("/{node_id}/upkeep/stop")
async def stop_node_upkeep(node_id: str) -> dict[str, Any]:
    await _require(node_id)
    try:
        node = await refresh.stop_refresh(get_store(), node_id)
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return await refresh.node_state(node)


@router.post("/{node_id}/upkeep/resume")
async def resume_node_upkeep(node_id: str, body: ResumeBody | None = None) -> dict[str, Any]:
    await _require(node_id)
    every_minutes = body.every_minutes if body is not None else None
    try:
        node = await refresh.start_refresh(get_store(), node_id, every_minutes=every_minutes)
    except NodeError as exc:
        # The node never said what it tracks: there is nothing to resume.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return await refresh.node_state(node)


@router.delete("/{node_id}")
async def delete_node(node_id: str) -> dict[str, Any]:
    """Remove the node for good: its page, its history and its refresh routine."""
    await _require(node_id)
    try:
        await refresh.stop_refresh(get_store(), node_id)
    except Exception:  # noqa: BLE001 - best effort: the person asked for the node to go
        # A routine that could not be removed stays in Automations, where the
        # person can delete it; the log names the node it belonged to.
        log.warning("node %s: refresh routine not removed before delete", node_id, exc_info=True)
    try:
        deleted = await asyncio.to_thread(get_store().delete, node_id)
    except OSError as exc:
        log.warning("node %s: delete failed", node_id, exc_info=True)
        raise HTTPException(status_code=500, detail=f"delete failed: {exc}") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="unknown node")
    return {"deleted": True}


__all__ = ["DEFAULT_TITLES", "get_store", "router", "set_store"]
