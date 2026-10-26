"""One agent's learning review queue: what it proposed or wrote that waits for the person.

The queue is a read model over rows that already exist, so it needs no table,
enum or event kind of its own:

* ``proposal:<approval id>`` — a pending configuration proposal (rule, skill,
  routine, approval rule, focus, team, identity). Approve and reject go through
  :func:`dodaios.society.proposals.resolve`, the same path the chat card uses.
* ``share:<approval id>`` — a note the agent asked to promote to shared
  knowledge. Approve promotes it; reject keeps it private.
* ``memory:<knowledge id>`` — an entry the agent wrote into its own notebook
  (``MEMORY.md`` / ``USER.md``) that nobody has looked at yet. Approve keeps it;
  reject removes the entry from the notebook.

Only recent memory writes are listed (``MEMORY_WINDOW_MS``) and the list is
bounded, so years of old bookkeeping rows never turn into a wall of chores. The
person's own writes never need review and are skipped. Nothing here calls a
model, so deciding an item never bills a key.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from .events import now_ms
from .memory import MEMORY_SHARE_CAPABILITY, MemoryRefused
from .proposals import kind_of

log = logging.getLogger(__name__)

__all__ = ["MEMORY_WINDOW_MS", "ReviewRefused", "decide", "queue"]

#: Memory writes older than this are history, not a review chore.
MEMORY_WINDOW_MS: Final[int] = 14 * 24 * 3600 * 1000
#: Most items one queue lists; the total is reported separately.
MAX_ITEMS: Final[int] = 40
_MAX_PREVIEW: Final[int] = 24
_MAX_LINE: Final[int] = 240
_BOOKS: Final[tuple[str, ...]] = ("MEMORY.md", "USER.md")


class ReviewRefused(ValueError):
    """An item that is unknown, not this agent's, or already decided."""


def _clip(text: Any) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= _MAX_LINE else line[: _MAX_LINE - 1] + "…"


def _lines(prefix: str, values: list[Any]) -> list[str]:
    return [f"{prefix} {_clip(v)}" for v in values if str(v or "").strip()]


def _proposal_preview(kind: str, payload: dict[str, Any], agent: Any) -> list[str]:
    """A diff-style preview: ``+`` added, ``-`` removed, two spaces unchanged."""
    if kind == "rule":
        operation = str(payload.get("operation") or "add")
        out = _lines("-", [payload.get("old_text")]) if operation != "add" else []
        return out + (_lines("+", [payload.get("text")]) if operation != "remove" else [])
    if kind == "focus":
        new = [str(x) for x in payload.get("focus") or []]
        old = [str(x) for x in getattr(agent, "focus", []) or []]
        out = [f"- {cap}" for cap in old if cap not in new]
        out += [f"+ {cap}" if cap not in old else f"  {cap}" for cap in new]
        return out
    if kind == "approval_rule":
        return _lines("+ ask first:", list(payload.get("require_approval") or [])) + _lines(
            "+ always allow:", list(payload.get("always_allow") or [])
        )
    if kind == "identity":
        out: list[str] = []
        for key in ("name", "title", "description"):
            new_value = payload.get(key)
            if not new_value:
                continue
            old_value = getattr(agent, key, "")
            if old_value and old_value != new_value:
                out.append(f"- {key}: {_clip(old_value)}")
            out.append(f"+ {key}: {_clip(new_value)}")
        return out
    if kind == "skill":
        return (
            _lines("+", [payload.get("name")])
            + _lines(" ", [payload.get("goal")])
            + _lines("  ·", list(payload.get("steps") or []))
        )
    if kind == "routine":
        operation = str(payload.get("operation") or "create")
        if operation in {"pause", "resume", "cancel", "delete"}:
            return [f"  {operation} {payload.get('task_id', '')}"]
        schedule = payload.get("schedule") or {}
        return _lines("+", [payload.get("title")]) + _lines(
            " ", [f"{schedule.get('kind', 'every')}: {payload.get('prompt', '')}"]
        )
    return _lines("+", list(payload.get("names") or []))


def _book_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name if name in _BOOKS else ""


async def queue(rt: Any, agent: Any) -> dict[str, Any]:
    """Every review item of ``agent``, newest first, plus per-kind totals."""
    await rt.approvals.expire_due()
    items: list[dict[str, Any]] = []
    pending = [a for a in await rt.approvals.pending() if a.agent_id == agent.agent_id]
    for approval in pending:
        proposal_kind = kind_of(approval.capability)
        if proposal_kind is not None:
            payload = approval.action.get("payload") or {}
            items.append(
                {
                    "id": f"proposal:{approval.id}",
                    "kind": "proposal",
                    "proposal_kind": proposal_kind,
                    "summary": approval.summary,
                    "reason": _clip(approval.action.get("reason")),
                    "preview": _proposal_preview(proposal_kind, payload, agent)[:_MAX_PREVIEW],
                    "created_ms": approval.created_ms,
                }
            )
        elif approval.capability == MEMORY_SHARE_CAPABILITY:
            items.append(
                {
                    "id": f"share:{approval.id}",
                    "kind": "memory_share",
                    "proposal_kind": "",
                    "summary": approval.summary,
                    "reason": "",
                    "preview": _lines("+", [approval.action.get("title")]),
                    "path": str(approval.action.get("path") or ""),
                    "created_ms": approval.created_ms,
                }
            )
    since = now_ms() - MEMORY_WINDOW_MS
    rows = await rt.store.list_knowledge_rows(
        agent_id=agent.agent_id, reviewed=False, limit=MAX_ITEMS * 4
    )
    memory = [
        r
        for r in rows
        if int(r.get("created_ms") or 0) >= since
        and str(r.get("origin") or "") != "user"
        and _book_of(str(r.get("wiki_path") or ""))
        and str(r.get("summary") or "").strip()
    ]
    for row in memory:
        items.append(
            {
                "id": f"memory:{int(row['id'])}",
                "kind": "memory",
                "proposal_kind": "",
                "summary": _clip(row.get("summary")),
                "reason": "",
                "preview": _lines("+", [row.get("summary")]),
                "path": str(row.get("wiki_path") or ""),
                "book": _book_of(str(row.get("wiki_path") or "")),
                "origin": str(row.get("origin") or ""),
                "created_ms": int(row.get("created_ms") or 0),
            }
        )
    items.sort(key=lambda item: int(item.get("created_ms") or 0), reverse=True)
    counts = {
        "proposal": sum(1 for i in items if i["kind"] == "proposal"),
        "memory_share": sum(1 for i in items if i["kind"] == "memory_share"),
        "memory": sum(1 for i in items if i["kind"] == "memory"),
    }
    return {"items": items[:MAX_ITEMS], "total": len(items), "counts": counts}


async def _pending_approval(rt: Any, agent: Any, approval_id: str) -> Any:
    item = await rt.approvals.get(approval_id)
    if item is None or item.agent_id != agent.agent_id:
        raise KeyError(approval_id)
    if str(item.state) not in ("pending", "blocked"):
        raise ReviewRefused("already decided")
    return item


async def decide(
    rt: Any,
    agent: Any,
    item_id: str,
    *,
    approve: bool,
    task_store: Any = None,
    scheduler: Any = None,
) -> dict[str, Any]:
    """Approve or reject one item of the queue; returns ``{"id", "outcome", ...}``.

    Raises ``KeyError`` for an unknown item and :class:`ReviewRefused` for one
    that cannot be decided (already decided, wrong kind).
    """
    kind, _, ref = item_id.partition(":")
    if not ref:
        raise KeyError(item_id)
    if kind == "proposal":
        from . import proposals

        await _pending_approval(rt, agent, ref)
        try:
            result = await proposals.resolve(
                rt, ref, approve=approve, task_store=task_store, scheduler=scheduler
            )
        except ValueError as exc:
            raise ReviewRefused(str(exc)) from exc
        outcome = "rejected" if not approve else ("applied" if result.get("applied") else "failed")
        return {"id": item_id, "outcome": outcome, "detail": str(result.get("detail") or "")}
    if kind == "share":
        current = await _pending_approval(rt, agent, ref)
        if current.capability != MEMORY_SHARE_CAPABILITY:
            raise ReviewRefused("not a knowledge share")
        knowledge_id = int(current.action.get("knowledge_id") or 0)
        await rt.approvals.resolve(ref, approve=approve, note="agent pane")
        try:
            if approve:
                path = await rt.memory.promote(knowledge_id)
                return {"id": item_id, "outcome": "applied", "detail": path}
            if knowledge_id:
                await rt.memory.dismiss(knowledge_id)
        except MemoryRefused as exc:
            log.info("society review: share %s not applied: %s", item_id, exc)
            return {"id": item_id, "outcome": "failed", "detail": str(exc)}
        return {"id": item_id, "outcome": "rejected", "detail": ""}
    if kind == "memory":
        try:
            knowledge_id = int(ref)
        except ValueError as exc:
            raise KeyError(item_id) from exc
        rows = await rt.store.list_knowledge_rows(agent_id=agent.agent_id, limit=100_000)
        row = next((r for r in rows if int(r["id"]) == knowledge_id), None)
        if row is None:
            raise KeyError(item_id)
        if row.get("reviewed"):
            raise ReviewRefused("already decided")
        detail = ""
        outcome = "applied" if approve else "rejected"
        if not approve:
            # The staged summary is the entry's text (clipped at 280 characters):
            # remove the entry that carries it. An entry since rewritten by the
            # agent is no longer this text, and stays.
            target = _book_of(str(row.get("wiki_path") or "")).removesuffix(".md").lower()
            try:
                await rt.memory.remember_receipt(
                    agent,
                    "",
                    target=target or None,
                    origin="user",
                    operation="remove",
                    old_text=str(row.get("summary") or ""),
                )
            except (MemoryRefused, ValueError, KeyError) as exc:
                log.info("society review: %s not removed: %s", item_id, exc)
                outcome, detail = "not_found", str(exc)
        await rt.store.mark_knowledge_reviewed(knowledge_id)
        return {"id": item_id, "outcome": outcome, "detail": detail}
    raise KeyError(item_id)
