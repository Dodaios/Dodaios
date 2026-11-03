"""HTTP API of the personal memory vault (ADR-0044, chunk 5).

* ``GET    /api/memory/vault``                 stats, kinds and the prompt block.
* ``GET    /api/memory/vault/items``           memories (``kind``, ``q``, ``history``).
* ``POST   /api/memory/vault/items``           add one in the user's words.
* ``PUT    /api/memory/vault/items/{id}``      edit: a new version supersedes it.
* ``POST   /api/memory/vault/items/{id}/pin``  pin or unpin.
* ``POST   /api/memory/vault/items/{id}/end``  mark as no longer true.
* ``DELETE /api/memory/vault/items/{id}``      forget it and every version.
* ``GET    /api/memory/vault/items/{id}/history``
* ``GET    /api/memory/vault/activity``        recent changes.
* ``GET    /api/memory/vault/export``          zip: ``format=bundle`` or ``markdown``.
* ``POST   /api/memory/vault/import``          a bundle zip as the request body.

Handlers are plain ``def`` so FastAPI runs them off the event loop. Nothing
here calls a model.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from dodaios.memory.vault.models import KINDS, Memory

router = APIRouter(prefix="/api/memory/vault", tags=["memory"])

_MAX_IMPORT_BYTES = 100 * 1024 * 1024


class NewMemory(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="", max_length=20)
    entities: list[str] = Field(default_factory=list, max_length=12)
    pinned: bool = False
    sensitive: bool = False


class EditMemory(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="", max_length=20)


class PinBody(BaseModel):
    pinned: bool = True


def _vault() -> Any:
    from dodaios.memory.vault.runtime import active

    vault = active()
    if vault is None:
        raise HTTPException(status_code=503, detail="memory vault is not running")
    return vault


def _changed() -> None:
    from dodaios.memory.vault.runtime import changed

    changed()


def _row(memory: Memory, now: str) -> dict[str, Any]:
    data = memory.to_dict()
    data["current"] = memory.is_current(now)
    data.pop("content_hash", None)
    return data


def _kind(kind: str, text: str) -> str:
    from dodaios.memory.vault.runtime import guess_kind

    kind = kind.strip().lower()
    if not kind:
        return guess_kind(text)
    if kind not in KINDS:
        raise HTTPException(status_code=422, detail=f"unknown kind {kind!r}")
    return kind


@router.get("")
def overview() -> dict[str, Any]:
    from dodaios.memory.vault.runtime import budget_chars, prompt_block

    vault = _vault()
    budget = budget_chars()
    block = prompt_block()
    selection = vault.profile_selection(max_chars=budget)
    return {
        "path": str(vault.path),
        "stats": vault.stats(),
        "kinds": list(KINDS),
        "prompt_block": block,
        "in_mind_ids": [m.id for _, memories in selection for m in memories],
        "budget_chars": budget,
        "used_chars": len(vault.profile_block(max_chars=budget)),
        "imported": vault.get_meta("legacy_import") is not None,
    }


@router.get("/files")
def files() -> dict[str, Any]:
    """The memory as readable Markdown files, exactly as the export writes them."""
    from dodaios.memory.vault.portable import markdown_files

    vault = _vault()
    rendered = markdown_files(vault)
    order = ["MEMORY.md", *(f"{k}.md" for k in KINDS)]
    return {
        "files": [
            {
                "name": name,
                "kind": name[:-3] if name != "MEMORY.md" else "index",
                "bytes": len(rendered[name].encode()),
                "lines": rendered[name].count("\n"),
                "content": rendered[name],
            }
            for name in order
            if name in rendered
        ]
    }


@router.get("/items")
def items(
    kind: str = Query(default=""),
    q: str = Query(default="", max_length=300),
    history: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    vault = _vault()
    now = vault.now()
    if q.strip():
        hits = vault.search(
            q, limit=min(limit, 100), kinds=[kind] if kind else None, include_closed=history
        )
        rows = [{**_row(h.memory, now), "score": round(h.score, 3)} for h in hits]
    else:
        rows = [
            _row(m, now) for m in vault.list(kind=kind or None, include_closed=history, limit=limit)
        ]
    return {"items": rows, "count": len(rows)}


@router.post("/items")
def add(body: NewMemory) -> dict[str, Any]:
    vault = _vault()
    try:
        result = vault.remember(
            body.text,
            _kind(body.kind, body.text),
            entities=body.entities,
            origin="user",
            source={"via": "memory section"},
            pinned=body.pinned,
            sensitivity="sensitive" if body.sensitive else "normal",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result.action == "refused":
        raise HTTPException(status_code=422, detail="that looks like a secret; not saved")
    _changed()
    memory = result.memory
    return {"action": result.action, "item": _row(memory, vault.now()) if memory else None}


@router.put("/items/{memory_id}")
def edit(memory_id: str, body: EditMemory) -> dict[str, Any]:
    vault = _vault()
    try:
        result = vault.supersede(
            memory_id,
            body.text,
            kind=_kind(body.kind, body.text) if body.kind else None,
            origin="user",
            source={"via": "memory section"},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such memory") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.action == "refused":
        raise HTTPException(status_code=422, detail="that looks like a secret; not saved")
    _changed()
    memory = result.memory
    return {"action": result.action, "item": _row(memory, vault.now()) if memory else None}


@router.post("/items/{memory_id}/pin")
def pin(memory_id: str, body: PinBody) -> dict[str, Any]:
    if not _vault().pin(memory_id, body.pinned):
        raise HTTPException(status_code=404, detail="no such memory")
    _changed()
    return {"ok": True}


@router.post("/items/{memory_id}/end")
def end(memory_id: str) -> dict[str, Any]:
    if not _vault().invalidate(memory_id, reason="ended in the memory section"):
        raise HTTPException(status_code=404, detail="no current memory with that id")
    _changed()
    return {"ok": True}


@router.delete("/items/{memory_id}")
def forget(memory_id: str) -> dict[str, Any]:
    count = _vault().forget(memory_id, reason="forgotten in the memory section")
    if not count:
        raise HTTPException(status_code=404, detail="no such memory")
    _changed()
    return {"forgotten": count}


@router.get("/items/{memory_id}/history")
def history(memory_id: str) -> dict[str, Any]:
    vault = _vault()
    versions = vault.history(memory_id)
    if not versions:
        raise HTTPException(status_code=404, detail="no such memory")
    now = vault.now()
    return {"versions": [_row(m, now) for m in versions]}


@router.get("/activity")
def activity(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    vault = _vault()
    entries = vault.audit_log(limit=limit)
    texts = {}
    for entry in entries:
        mid = entry.get("memory_id")
        if mid and mid not in texts:
            memory = vault.get(mid)
            texts[mid] = memory.text if memory else ""
    return {"entries": [{**e, "text": texts.get(e.get("memory_id") or "", "")} for e in entries]}


@router.get("/export")
def export(
    kind: str = Query(default="bundle", alias="format", pattern="^(bundle|markdown)$"),
) -> Response:
    from dodaios.memory.vault.portable import export_zip_bytes, markdown_files

    vault = _vault()
    stamp = vault.now()[:10]
    if kind == "bundle":
        data = export_zip_bytes(vault)
        name = f"my-memory-{stamp}.zip"
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, text in markdown_files(vault).items():
                zf.writestr(f"my-memory/{path}", text)
        data = buffer.getvalue()
        name = f"my-memory-{stamp}-markdown.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/import")
async def import_bundle(request: Request) -> dict[str, Any]:
    import asyncio

    from dodaios.memory.vault.portable import BundleError
    from dodaios.memory.vault.portable import import_bundle as run_import

    data = await request.body()
    if not data:
        raise HTTPException(status_code=422, detail="send the bundle zip as the request body")
    if len(data) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="bundle too large")
    vault = _vault()
    try:
        report = await asyncio.to_thread(run_import, vault, data)
    except BundleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _changed()
    return report.to_dict()
