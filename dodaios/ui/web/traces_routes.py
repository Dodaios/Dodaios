"""Read-only routes over the causal trace tree.

    GET /api/traces?session=<id>&limit=50   Trace roots a chat session started, newest first
    GET /api/traces/{root}                  The tree under one root, bounded

``{root}`` may be any node id (a turn id, an assignment event id, a job id): it
is resolved to its root first. Loopback-only, like the other read models.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from dodaios.orchestrator import traces

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("")
async def list_traces(
    session: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=traces.MAX_ROOTS)] = 50,
) -> dict[str, object]:
    if not session.strip():
        raise HTTPException(status_code=400, detail="session is required")
    roots = await asyncio.to_thread(traces.list_roots, session.strip(), limit=limit)
    return {"session": session.strip(), "roots": roots}


@router.get("/{root}")
async def get_trace(root: str) -> dict[str, object]:
    resolved = await asyncio.to_thread(traces.resolve_root, root)
    tree = await asyncio.to_thread(traces.build_tree, resolved) if resolved else None
    if tree is None:
        raise HTTPException(status_code=404, detail="unknown trace")
    return {"root": resolved, "tree": traces.public(tree)}
