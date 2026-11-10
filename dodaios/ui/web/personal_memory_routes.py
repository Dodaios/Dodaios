"""HTTP API of the personal memory vault (ADR-0044, chunk 5).

* ``GET    /api/memory/vault``                 stats, kinds and the prompt block.
* ``GET    /api/memory/vault/items``           memories (``kind``, ``origin``, ``since``,
  ``until``, ``q``, ``history``, ``sort``, ``offset``/``limit`` paging, ``total``).
* ``POST   /api/memory/vault/forget``          forget a selection; answers an undo token.
* ``POST   /api/memory/vault/undo/{token}``    bring a just-forgotten selection back.
* ``POST   /api/memory/vault/items``           add one in the user's words.
* ``PUT    /api/memory/vault/items/{id}``      edit: a new version supersedes it.
* ``POST   /api/memory/vault/items/{id}/pin``  pin or unpin.
* ``POST   /api/memory/vault/items/{id}/end``  mark as no longer true.
* ``DELETE /api/memory/vault/items/{id}``      forget it and every version.
* ``GET    /api/memory/vault/items/{id}/history``
* ``GET    /api/memory/vault/activity``        recent changes.
* ``PUT    /api/memory/vault/items/{id}/scope`` mark it work, private or neither.
* ``GET    /api/memory/vault/export``          zip: ``format=all``, ``bundle`` or ``markdown``.
* ``POST   /api/memory/vault/import``          a bundle zip as the request body.
* ``POST   /api/memory/vault/import/read``     another assistant's export -> review list.
* ``POST   /api/memory/vault/import/save``     save the rows the person kept.

Handlers are plain ``def`` so FastAPI runs them off the event loop. Nothing
here calls a model.
"""

from __future__ import annotations

import io
import secrets
import threading
import time
import zipfile
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from dodaios.memory.vault.models import KINDS, ORIGINS, SCOPES, Memory

router = APIRouter(prefix="/api/memory/vault", tags=["memory"])

_MAX_IMPORT_BYTES = 100 * 1024 * 1024
#: Largest export of another assistant read in one upload (characters).
_MAX_FOREIGN_CHARS = 20 * 1024 * 1024


class NewMemory(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="", max_length=20)
    entities: list[str] = Field(default_factory=list, max_length=12)
    pinned: bool = False
    sensitive: bool = False


class EditMemory(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="", max_length=20)


class ForgetMany(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class PinBody(BaseModel):
    pinned: bool = True


class ScopeBody(BaseModel):
    scope: str = Field(max_length=20)


class ForeignUpload(BaseModel):
    #: The file name, only to tell JSON from text.
    name: str = Field(default="", max_length=300)
    #: The file's text, read in the browser.
    text: str = Field(min_length=1, max_length=_MAX_FOREIGN_CHARS)


class ForeignItem(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="", max_length=20)
    extracted: bool = False


class ForeignSave(BaseModel):
    name: str = Field(default="", max_length=300)
    items: list[ForeignItem] = Field(default_factory=list, max_length=500)
    scope: str = Field(default="global", max_length=20)


class PauseBody(BaseModel):
    #: Minutes to pause; None with ``forever`` false resumes learning.
    minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 365)
    forever: bool = False


#: How long a forgotten selection can be brought back (seconds).
UNDO_WINDOW_SECONDS = 60
_undo_lock = threading.Lock()
_undo: dict[str, tuple[float, list[Memory]]] = {}


def _stash_for_undo(memories: list[Memory]) -> str:
    """Hold the erased versions in this process only, for the undo window."""
    now = time.monotonic()
    token = secrets.token_urlsafe(12)
    with _undo_lock:
        for key in [k for k, (until, _) in _undo.items() if until <= now]:
            del _undo[key]
        _undo[token] = (now + UNDO_WINDOW_SECONDS, memories)
    return token


def _forget_chains(vault: Any, ids: list[str], reason: str) -> tuple[int, str | None]:
    """Forget each id with its versions. Returns (rows erased, undo token)."""
    seen: set[str] = set()
    saved: list[Memory] = []
    erased = 0
    for memory_id in ids:
        if memory_id in seen:
            continue
        chain = vault.history(memory_id)
        seen.update(m.id for m in chain)
        count = vault.forget(memory_id, reason=reason)
        if count:
            erased += count
            saved.extend(chain)
    return erased, (_stash_for_undo(saved) if saved else None)


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
    origin: str = Query(default=""),
    since: str = Query(default="", max_length=40),
    until: str = Query(default="", max_length=40),
    q: str = Query(default="", max_length=300),
    history: bool = Query(default=False),
    sort: str = Query(default="", pattern="^(|newest)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    if origin and origin not in ORIGINS:
        raise HTTPException(status_code=422, detail=f"unknown origin {origin!r}")
    vault = _vault()
    now = vault.now()
    if q.strip():
        hits = vault.search(q, limit=100, kinds=[kind] if kind else None, include_closed=history)
        found = [(h.memory, round(h.score, 3)) for h in hits]
    else:
        found = [(m, None) for m in vault.list(kind=kind or None, include_closed=history)]
    if origin:
        found = [(m, s) for m, s in found if m.origin == origin]
    if since:
        found = [(m, s) for m, s in found if m.recorded_at[: len(since)] >= since]
    if until:
        found = [(m, s) for m, s in found if m.recorded_at[: len(until)] <= until]
    if sort == "newest":
        found.sort(key=lambda pair: (pair[0].recorded_at, pair[0].id), reverse=True)
    total = len(found)
    page = found[offset : offset + limit]
    rows = [
        {**_row(m, now), **({"score": score} if score is not None else {})} for m, score in page
    ]
    return {
        "items": rows,
        "count": len(rows),
        "total": total,
        "has_more": offset + len(rows) < total,
    }


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
    count, token = _forget_chains(_vault(), [memory_id], "forgotten in the memory section")
    if not count:
        raise HTTPException(status_code=404, detail="no such memory")
    _changed()
    return {"forgotten": count, "undo_token": token, "undo_seconds": UNDO_WINDOW_SECONDS}


@router.post("/forget")
def forget_many(body: ForgetMany) -> dict[str, Any]:
    """Forget a selection (each with its versions); undoable for a short time."""
    count, token = _forget_chains(
        _vault(), body.ids, "forgotten in the memory section (selection)"
    )
    if not count:
        raise HTTPException(status_code=404, detail="no such memories")
    _changed()
    return {"forgotten": count, "undo_token": token, "undo_seconds": UNDO_WINDOW_SECONDS}


@router.post("/undo/{token}")
def undo_forget(token: str) -> dict[str, Any]:
    """Bring back what a forget just erased, while the undo window is open."""
    with _undo_lock:
        entry = _undo.pop(token, None)
    if entry is None or entry[0] <= time.monotonic():
        raise HTTPException(status_code=410, detail="the undo window has closed")
    restored = _vault().restore(entry[1])
    _changed()
    return {"restored": restored}


@router.get("/items/{memory_id}/history")
def history(memory_id: str) -> dict[str, Any]:
    vault = _vault()
    versions = vault.history(memory_id)
    if not versions:
        raise HTTPException(status_code=404, detail="no such memory")
    now = vault.now()
    return {"versions": [_row(m, now) for m in versions]}


@router.get("/upcoming")
def upcoming(days: int = Query(default=14, ge=1, le=365)) -> dict[str, Any]:
    """Memories that fall due soon: plans, deadlines, appointments (overdue first)."""
    vault = _vault()
    now = vault.now()
    return {"items": [_row(m, now) for m in vault.upcoming(days=days)]}


@router.get("/pause")
def pause_state() -> dict[str, Any]:
    until = _vault().learning_paused_until()
    return {"paused": until is not None, "until": until}


@router.put("/pause")
def pause(body: PauseBody) -> dict[str, Any]:
    """Pause background learning for a while, for good, or resume it."""
    from datetime import datetime, timedelta

    vault = _vault()
    if body.forever:
        vault.pause_learning("forever")
    elif body.minutes:
        end = datetime.fromisoformat(vault.now()) + timedelta(minutes=body.minutes)
        vault.pause_learning(end.isoformat(timespec="seconds"))
    else:
        vault.pause_learning(None)
    until = vault.learning_paused_until()
    return {"paused": until is not None, "until": until}


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


@router.put("/items/{memory_id}/scope")
def set_scope(memory_id: str, body: ScopeBody) -> dict[str, Any]:
    """Mark a memory work or private, or unmark it (``global``)."""
    if body.scope not in SCOPES:
        raise HTTPException(status_code=422, detail=f"unknown scope {body.scope!r}")
    if not _vault().set_scope(memory_id, body.scope):
        raise HTTPException(status_code=404, detail="no such memory")
    _changed()
    return {"ok": True, "scope": body.scope}


@router.post("/import/read")
async def import_read(body: ForeignUpload) -> dict[str, Any]:
    """Read another assistant's export into a review list; nothing is saved.

    A memory list is read without a model; the person's messages of a chat
    export go through one extraction call per chunk, on the assistant's seat.
    """
    import asyncio

    from dodaios.memory.vault import foreign_import

    vault = _vault()
    parsed = await asyncio.to_thread(foreign_import.parse_upload, body.name, body.text)
    facts: list[str] = list(parsed.facts)
    extracted: list[str] = []
    model_missing = False
    if parsed.said:
        ask = _extractor()
        if ask is None:
            model_missing = True
        else:
            rows, answered = await foreign_import.extract(parsed.said, ask)
            model_missing = not answered and bool(foreign_import.worth_reading(parsed.said))
            extracted = [r["text"] for r in rows]
    listed = await asyncio.to_thread(foreign_import.candidates, vault, facts)
    found = await asyncio.to_thread(foreign_import.candidates, vault, extracted, extracted=True)
    seen = {row["text"].casefold() for row in listed}
    rows = listed + [row for row in found if row["text"].casefold() not in seen]
    return {
        "candidates": rows[: foreign_import.MAX_CANDIDATES],
        "shape": parsed.shape,
        "messages": len(parsed.said),
        "model_missing": model_missing,
    }


@router.post("/import/save")
def import_save(body: ForeignSave) -> dict[str, Any]:
    """Save the rows the person kept, with origin ``imported``."""
    from dodaios.memory.vault import foreign_import

    vault = _vault()
    try:
        counts = foreign_import.save(
            vault,
            [item.model_dump() for item in body.items],
            file=body.name,
            scope=body.scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if counts["added"]:
        _changed()
    return counts


def _extractor() -> Any | None:
    """The model call that reads a chat export, on the assistant's own seat."""
    from dodaios.core.runtime_refs import get_brain_manager
    from dodaios.memory.learning.review import ModelReviewer
    from dodaios.memory.vault import foreign_import

    config = getattr(get_brain_manager(), "_config", None)
    if config is None:
        return None
    return ModelReviewer(
        config,
        system=foreign_import.extract_system_prompt,
        parser=foreign_import.parse_extracted,
        max_tokens=foreign_import.EXTRACT_MAX_TOKENS,
        caller="memory-import",
    )


@router.get("/export")
def export(
    kind: str = Query(default="bundle", alias="format", pattern="^(bundle|markdown|all)$"),
) -> Response:
    from dodaios.memory.vault.portable import (
        everything_zip_bytes,
        export_zip_bytes,
        markdown_files,
    )

    vault = _vault()
    stamp = vault.now()[:10]
    if kind == "all":
        data = everything_zip_bytes(vault)
        name = f"my-memory-{stamp}-all.zip"
    elif kind == "bundle":
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
