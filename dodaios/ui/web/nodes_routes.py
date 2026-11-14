"""HTTP API of nodes (:mod:`dodaios.nodes`, ``docs/nodes.md``).

* ``GET    /api/nodes``                      the library: every card (``?scan=<n>``).
* ``GET    /api/nodes/types``                the node types and their spec guides.
* ``GET    /api/nodes/by-slug/{slug}``       the typed node behind a run, with its spec.
* ``GET    /api/nodes/{id}``                 one typed node, with its spec.
* ``POST   /api/nodes``                      a new node from its type's starter.
* ``PATCH  /api/nodes/{id}``                 rename.
* ``POST   /api/nodes/{id}/edit``            one value the person typed into the page.
* ``PUT    /api/nodes/{id}/spec``            the type editor's save: the whole spec, from a version.
* ``POST   /api/nodes/{id}/preview``         the page drawn from an unsaved spec.
* ``POST   /api/nodes/{id}/duplicate``       a second node with the same content.
* ``POST   /api/nodes/{id}/revert``          put the previous version back.
* ``POST   /api/nodes/{id}/upkeep/stop``     stop keeping it current; the content stays.
* ``POST   /api/nodes/{id}/upkeep/resume``   keep it current again.
* ``POST   /api/nodes/{id}/comments``        the reader's comments, worked in in the background.
* ``DELETE /api/nodes/{id}``                 remove the node, its page and its history.

A whiteboard is drawn in the app's embedded editor, so it has routes of its own:

* ``GET    /api/nodes/{id}/scene``           the board's scene and its version.
* ``PUT    /api/nodes/{id}/scene``           the editor's save, merged with the stored scene.
* ``POST   /api/nodes/{id}/files``           keep a picture (a data URL); answers its id.
* ``GET    /api/nodes/{id}/files/{fileId}``  a picture's bytes.
* ``POST   /api/nodes/{id}/whiteboard``      the ``whiteboard`` tool's actions, over HTTP.

The library is what the app's Nodes section shows: the typed nodes plus what
older runs left behind (:mod:`dodaios.nodes.library`). The routes that change
something only reach typed nodes; an adopted file is still deleted through
``/api/outputs``. A node's content is written by the assistant through the
``node`` tool, and by the person one value at a time in the stage's edit mode
(``/edit``, :mod:`dodaios.nodes.edit`): the library renames, copies, reverts and
removes. Nothing here calls a model; the comments route starts a background run
of the assistant (:mod:`dodaios.nodes.comments`) and returns at once.

A node's page runs in a sandbox with no network, so everything a person does
TO a node (stop its upkeep, rename it) is a control of the app and a route here.

The type editors (``frontend/src/components/nodes/editors``) save the whole
spec with the version they started from. When the node moved on meanwhile
(the assistant revised it) the save is refused with 409 and the node's
current ``version``, ``updated_at`` and ``spec``, so the editor can let the
person take that version or save over it; a spec the type's ``normalize``
refuses is a 422 with its sentence. The answer to a save carries the spec as
it was kept. ``/preview`` draws a spec without saving it and is served like
the node's page itself (scripts run, every way out shut), because the editor
frames it the same way.

The whiteboard routes read their bodies themselves, with a ceiling checked
while the body streams in: a scene may be megabytes (a hand-drawn stroke is
hundreds of points) and a picture five, and neither should be read whole
before it is refused. A saved scene is joined with what the assistant drew
meanwhile (:meth:`~dodaios.nodes.store.NodeStore.merge_save_scene`); when the
stored scene had something newer the answer carries the merged scene, and the
editor takes it. A picture is served with the type its bytes have, cached for
good (a file id never changes its picture) and under a policy that lets it
run nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from dodaios.nodes import comments, library, refresh
from dodaios.nodes.board import files as board_files
from dodaios.nodes.board.scene import MAX_SCENE_BYTES, live_elements, scene_bounds
from dodaios.nodes.edit import KINDS, apply_field
from dodaios.nodes.kinds import kind_of
from dodaios.nodes.model import Node
from dodaios.nodes.store import MAX_EVERY_MINUTES, MIN_EVERY_MINUTES, NodeStore, SpecConflict
from dodaios.nodes.types import MAX_SPEC_BYTES, MAX_TITLE_CHARS, NODE_TYPES, NodeError, node_type
from dodaios.ui.web import living_pages_routes
from dodaios.ui.web.artifact_view import ARTIFACT_PAGE_CSP

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

#: Body ceilings of the whiteboard routes: a scene with its JSON overhead, a
#: picture as base64 text, a list of actions (a Mermaid source, a diagram).
MAX_SCENE_BODY: Final[int] = MAX_SCENE_BYTES + 512 * 1024
MAX_FILE_BODY: Final[int] = board_files.MAX_DATA_URL_CHARS + 4 * 1024
MAX_ACTIONS_BODY: Final[int] = 2 * 1024 * 1024
MAX_ACTIONS: Final[int] = 500
#: Body ceiling of a spec save or preview. The spec bound counts characters;
#: in UTF-8 a character of a non-Latin script takes up to four bytes, and an
#: editor may send a few parts ``normalize`` then drops.
MAX_SPEC_BODY: Final[int] = 4 * MAX_SPEC_BYTES + 64 * 1024
#: A preview is served like the node's page (``/api/outputs/…/page``).
_PAGE_HEADERS: Final[dict[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": ARTIFACT_PAGE_CSP,
    "Cache-Control": "no-store",
}
#: A picture never changes under its id, and runs nothing.
_FILE_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "private, max-age=31536000, immutable",
    "Content-Security-Policy": "default-src 'none'",
    "X-Content-Type-Options": "nosniff",
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


class CommentBody(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    quote: str = Field(default="", max_length=240)
    where: str = Field(default="", max_length=300)


class CommentsBody(BaseModel):
    comments: list[CommentBody] = Field(min_length=1, max_length=comments.MAX_COMMENTS)


class SceneBody(BaseModel):
    scene: dict[str, Any]


class SpecBody(BaseModel):
    """The editor's whole spec, and the version it was edited from (null: any)."""

    spec: dict[str, Any]
    base_version: int | None = Field(default=None, ge=0)


class PreviewBody(BaseModel):
    spec: dict[str, Any]


class FileBody(BaseModel):
    data_url: str = Field(alias="dataURL", min_length=1)
    id: str | None = Field(default=None, max_length=100)

    model_config = {"populate_by_name": True}


class ActionsBody(BaseModel):
    actions: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_ACTIONS)


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


async def _read_json(request: Request, limit: int) -> Any:
    """The request's JSON body, refused with 413 as soon as it passes ``limit`` bytes."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(status_code=413, detail="The request body is too large.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="The request body is too large.")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks) or b"null")
    except ValueError:
        raise HTTPException(status_code=422, detail="The request body must be JSON.") from None


def _body(model: type[BaseModel], data: Any) -> Any:
    """``data`` read as ``model``; 422 with what is wrong."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'body'}: {error['msg']}"
            for error in exc.errors()[:5]
        )
        raise HTTPException(status_code=422, detail=problems) from None


async def _require_board(node_id: str) -> Node:
    """The whiteboard node ``node_id``: 404 for no node, 422 for another type."""
    node = await _require(node_id)
    if node.type != "whiteboard":
        raise HTTPException(
            status_code=422, detail=f"Node {node_id} is a {node.type} node, not a whiteboard."
        )
    return node


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
    return await _state_or_404(await asyncio.to_thread(get_store().by_slug, slug), with_spec=spec)


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


@router.put("/{node_id}/spec")
async def put_spec(node_id: str, request: Request) -> Any:
    """Save the type editor's spec, made from ``base_version``.

    Answers ``{version, updated_at, spec}`` with the spec as the type kept
    it. 409 ``{detail, version, updated_at, spec}`` when the node is no
    longer at ``base_version``; 422 with the type's sentence when the spec
    is refused (and for a whiteboard, which saves its scene).
    """
    await _require(node_id)
    body = _body(SpecBody, await _read_json(request, MAX_SPEC_BODY))
    try:
        node = await asyncio.to_thread(
            lambda: get_store().save_spec(node_id, body.spec, base_version=body.base_version)
        )
    except SpecConflict as exc:  # an answer, not a failure: the editor offers both versions
        current = exc.node
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "version": current.version,
                "updated_at": current.updated_at,
                "spec": current.spec,
            },
        )
    except NodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"version": node.version, "updated_at": node.updated_at, "spec": node.spec}


@router.post("/{node_id}/preview")
async def preview_spec(node_id: str, request: Request) -> HTMLResponse:
    """The node's page drawn from ``{spec}`` without saving it (422 when refused)."""
    await _require(node_id)
    body = _body(PreviewBody, await _read_json(request, MAX_SPEC_BODY))
    try:
        page = await asyncio.to_thread(get_store().preview, node_id, body.spec)
    except NodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return HTMLResponse(page, headers=dict(_PAGE_HEADERS))


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


@router.post("/{node_id}/comments", status_code=202)
async def send_node_comments(node_id: str, body: CommentsBody) -> dict[str, Any]:
    """Hand the reader's comments to the assistant as one background request.

    The run is quiet: the conversation shows nothing of it unless it fails or
    a comment could not be carried out. The page is drawn again when the
    assistant writes the revision.
    """
    await _require(node_id)
    batch = [comments.NodeComment(c.text, c.quote, c.where) for c in body.comments]
    try:
        task_id = await comments.send_comments(get_store(), node_id, batch)
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"task_id": task_id, "count": len(batch)}


@router.get("/{node_id}/scene")
async def get_scene(node_id: str) -> dict[str, Any]:
    """The whiteboard's scene, with the version it belongs to."""
    await _require_board(node_id)
    try:
        node, scene = await asyncio.to_thread(get_store().scene_of, node_id)
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"version": node.version, "updated_at": node.updated_at, "scene": scene}


@router.put("/{node_id}/scene")
async def put_scene(node_id: str, request: Request) -> dict[str, Any]:
    """Save the editor's scene, joined with what the assistant drew meanwhile.

    Answers ``{version, updated_at, merged}``; with ``merged: true`` also the
    ``scene`` as saved, which the editor has to take (the stored scene had a
    newer element, or one the editor did not have).
    """
    await _require_board(node_id)
    body = _body(SceneBody, await _read_json(request, MAX_SCENE_BODY))
    try:
        node, merged = await asyncio.to_thread(get_store().merge_save_scene, node_id, body.scene)
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    answer: dict[str, Any] = {
        "version": node.version,
        "updated_at": node.updated_at,
        "merged": merged,
    }
    if merged:
        answer["scene"] = node.spec
    return answer


@router.post("/{node_id}/files")
async def put_board_file(node_id: str, request: Request) -> dict[str, Any]:
    """Keep a picture for the board: ``{dataURL, id?}`` → ``{id, mimeType}``."""
    await _require_board(node_id)
    body = _body(FileBody, await _read_json(request, MAX_FILE_BODY))
    try:
        file_id, mime = await asyncio.to_thread(
            lambda: get_store().put_file(node_id, body.data_url, file_id=body.id)
        )
    except board_files.FileConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": file_id, "mimeType": mime}


@router.get("/{node_id}/files/{file_id}")
async def get_board_file(node_id: str, file_id: str) -> Response:
    """A picture of the board, with the type its bytes have."""
    await _require_board(node_id)
    try:
        found = await asyncio.to_thread(get_store().read_file, node_id, file_id)
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if found is None:
        raise HTTPException(status_code=404, detail="unknown file")
    data, mime = found
    return Response(content=data, media_type=mime, headers=dict(_FILE_HEADERS))


def _summary(scene: dict[str, Any]) -> dict[str, Any]:
    """How much is on the board now and where: ``{elements, bounds}``."""
    elements = live_elements(scene)
    return {
        "elements": len(elements),
        "bounds": [round(value) for value in scene_bounds(elements)],
    }


@router.post("/{node_id}/whiteboard")
async def run_board_actions(node_id: str, request: Request) -> dict[str, Any]:
    """Run the ``whiteboard`` tool's actions on the board, for scripts and other agents.

    Body ``{actions: [...]}`` (the tool's ``edit`` actions). All actions or
    none: an action that fails is a 400 naming it, and the board stays as it
    was. Saved as an ordinary revision (one history version). Answers
    ``{version, report, summary}``: one report line per action, and the
    board's element count and bounds.
    """
    await _require_board(node_id)
    body = _body(ActionsBody, await _read_json(request, MAX_ACTIONS_BODY))
    store = get_store()

    def run() -> tuple[Node, list[str]]:
        from dodaios.nodes.board.ops import apply_actions

        with store.locked(node_id):
            _, scene = store.scene_of(node_id)
            new_scene, report = apply_actions(scene, body.actions)
            return store.update(node_id, spec=new_scene), list(report)

    try:
        node, report = await asyncio.to_thread(run)
    except ImportError as exc:
        log.warning("whiteboard actions unavailable", exc_info=True)
        raise HTTPException(
            status_code=503, detail="The whiteboard actions are not available."
        ) from exc
    except NodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"version": node.version, "report": report, "summary": _summary(node.spec)}


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


__all__ = ["DEFAULT_TITLES", "MAX_SCENE_BODY", "MAX_SPEC_BODY", "get_store", "router", "set_store"]
