"""``living_page`` — a page the assistant keeps current, and its refresh.

The person asks "keep a page that tracks my parcels / job applications / this
stock list". The assistant reads the sources once, then calls this tool with
``create``: the page lands in the Artifacts section with the rows it found, and
a lead routine refreshes it on a schedule (:mod:`dodaios.artifacts.living_refresh`).
Every refresh run calls this tool again with ``update`` and the complete rows.
``stop`` ends the refresh; the page keeps its last rows.

Router-tier, risk ``monitor``: it writes one page in the run archive and adds
or removes one routine of the assistant's own. It never sends anything, never
spawns a worker, and the routine never bills an API key (routine runner).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult

log = logging.getLogger(__name__)

_OPERATIONS: Final[tuple[str, ...]] = ("create", "update", "stop", "resume", "list")


def session_of(ctx: Any) -> str:
    """The chat session that called, from the executor's approval reference."""
    config = getattr(ctx, "config", None)
    ref = str(config.get("approval_ref") or "") if isinstance(config, dict) else ""
    return ref.removeprefix("agent-chat:") if ref.startswith("agent-chat:") else ""


def _language(ctx: Any, args: dict[str, Any]) -> str:
    config = getattr(ctx, "config", None)
    stamped = str(config.get("output_language") or "") if isinstance(config, dict) else ""
    return (stamped or str(args.get("language") or "") or "en").strip().lower()[:8]


async def post_card(session_id: str, payload: dict[str, Any]) -> bool:
    """Post a result card into ``session_id``, or the lead conversation."""
    try:
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        svc = runtime.chat_service() if runtime is not None else None
        if svc is None:
            return False
        target = session_id
        if not target or svc.store.get_session(target) is None:
            from dodaios.agent_chat.lead import lead_session

            session = lead_session(svc, create=False)
            target = session.session_id if session is not None else ""
        if not target:
            return False
        await svc.post_notice(target, payload)
        return True
    except Exception:  # noqa: BLE001 — the card is a projection; the work itself is done
        log.warning("result card not posted", exc_info=True)
        return False


def page_item(page: Any, *, state: str = "created") -> dict[str, Any]:
    """One result-card row that opens a living page in the Artifacts section."""
    return {
        "kind": "page",
        "label": page.title,
        "state": state,
        "artifact": page.visual_id,
        "detail": f"every {page.every_minutes} min" if page.refreshing else "",
    }


class LivingPageTool:
    """Create, refresh, stop or list the pages the assistant keeps current."""

    name: str = "living_page"
    risk_tier: str = "monitor"
    description: str = (
        "Keep a LIVING PAGE: a page in the Artifacts section that you keep current "
        "on a schedule, for when the person asks you to keep, track or watch a list "
        "('keep a page that tracks my parcels', 'track my job applications', 'watch "
        "this stock list'). First read the current items from the person's apps or "
        "the screen, then call operation 'create' with a title, 'track' (what to keep "
        "current and where to read it, self-contained), the columns and the rows. A "
        "routine of yours then refreshes the page every 'every_minutes'. On a refresh "
        "run call 'update' with page_id and the COMPLETE current rows. 'stop' ends the "
        "refresh, 'resume' starts it again, 'list' shows the pages. Read only: a "
        "refresh never sends, books or deletes anything."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": list(_OPERATIONS)},
            "page_id": {"type": "string", "description": "For update, stop and resume."},
            "title": {"type": "string", "description": "create: a few words."},
            "track": {
                "type": "string",
                "description": (
                    "create: what the page keeps current and where to read it, "
                    "self-contained (the refresh run sees only this)."
                ),
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Column names, at most 8 (e.g. Item, Status, Expected).",
            },
            "rows": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "One object per item, keyed by column name; an optional 'link' "
                    "field holds the item's web address."
                ),
            },
            "every_minutes": {
                "type": "integer",
                "description": "create/resume: refresh interval, 15 to 10080 (default 180).",
            },
            "note": {
                "type": "string",
                "description": "update: one short line, e.g. why no source could be read.",
            },
            "language": {"type": "string", "description": "The person's language code."},
        },
        "required": ["operation"],
    }

    def __init__(self, store: Any | None = None) -> None:
        self._store = store

    def _pages(self) -> Any:
        if self._store is None:
            from dodaios.artifacts.living import LivingPageStore

            self._store = LivingPageStore()
        return self._store

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        from dodaios.artifacts import living_refresh
        from dodaios.artifacts.living import LivingPageError

        args = args or {}
        operation = str(args.get("operation") or "").strip().lower()
        if operation not in _OPERATIONS:
            return ToolResult(
                False, "", f"'operation' must be one of {', '.join(_OPERATIONS)}."
            )
        store = self._pages()
        page_id = str(args.get("page_id") or "").strip()
        try:
            if operation == "list":
                pages = await asyncio.to_thread(store.list_pages)
                return ToolResult(
                    True,
                    [
                        {
                            "page_id": p.id,
                            "title": p.title,
                            "rows": len(p.rows),
                            "refreshing": p.refreshing,
                            "every_minutes": p.every_minutes,
                        }
                        for p in pages
                    ],
                )
            if operation == "update":
                if not page_id:
                    return ToolResult(False, "", "'page_id' is required for update.")
                rows = args.get("rows")
                page = await asyncio.to_thread(
                    store.update_rows,
                    page_id,
                    rows=rows if rows else None,
                    columns=args.get("columns"),
                    note=str(args.get("note") or ""),
                )
                return ToolResult(
                    True, f"Living page '{page.title}' updated with {len(page.rows)} rows."
                )
            if operation == "stop":
                page = await living_refresh.stop_refresh(store, page_id)
                return ToolResult(
                    True, f"The page '{page.title}' no longer refreshes; it keeps its last rows."
                )
            if operation == "resume":
                if args.get("every_minutes") is not None:
                    await asyncio.to_thread(store.set_every, page_id, args["every_minutes"])
                page = await living_refresh.start_refresh(store, page_id)
                return ToolResult(
                    True, f"The page '{page.title}' refreshes every {page.every_minutes} minutes."
                )
            return await self._create(store, args, ctx)
        except LivingPageError as exc:  # the model's call to fix; the error says how
            return ToolResult(False, "", str(exc))
        except RuntimeError as exc:  # scheduler down: said to the model, not swallowed
            return ToolResult(False, "", f"The refresh routine is unavailable: {exc}")

    async def _create(self, store: Any, args: dict[str, Any], ctx: Any) -> ToolResult:
        from dodaios.artifacts import living_refresh

        page = await asyncio.to_thread(
            store.create,
            title=str(args.get("title") or ""),
            track=str(args.get("track") or ""),
            columns=args.get("columns"),
            rows=args.get("rows") or [],
            every_minutes=args.get("every_minutes", 180),
            language=_language(ctx, args),
        )
        refresh_error = ""
        try:
            page = await living_refresh.start_refresh(store, page.id)
        except RuntimeError as exc:
            # The page exists either way; the person hears that it will not refresh.
            refresh_error = str(exc)
            log.warning("living page %s: refresh not scheduled: %s", page.id, exc)
        await post_card(
            session_of(ctx),
            {"kind": "chain_result", "text": page.title, "items": [page_item(page)]},
        )
        if refresh_error:
            return ToolResult(
                True,
                f"Created the page '{page.title}' (page_id {page.id}) with {len(page.rows)} "
                f"rows, but it cannot refresh yet: {refresh_error}.",
            )
        return ToolResult(
            True,
            f"Created the living page '{page.title}' (page_id {page.id}) with "
            f"{len(page.rows)} rows. It refreshes every {page.every_minutes} minutes and is "
            "in the Artifacts section; the person can stop the refresh there.",
        )


__all__ = ["LivingPageTool", "page_item", "post_card", "session_of"]
