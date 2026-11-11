"""``artifacts``: list and read what the agents made, for every lead seat.

The Artifacts wall and the Outputs list hold the deliverables of missions (files
the workers wrote) and the living pages the lead keeps current. The lead used to
see them only by clicking. This is a read-only wrapper over the routes those
views use, summary-first: ``list`` shows the newest outputs (page with
``offset``), ``files`` lists one output's deliverables, ``read`` returns one text
file (bounded, with a flag when it was cut) and ``living`` lists the living pages
or reads one (``slug``). To create or refresh a page use ``living_page`` or
``create_artifact``.
"""

from __future__ import annotations

from typing import Any, Final
from urllib.parse import quote

from dodaios.brain.lead_api import bounded, call_app_api, failure
from dodaios.core.protocols import ExecutionContext, ToolResult

_DEFAULT_LIMIT = 15
_MAX_LIMIT = 100
_READ_CHARS = 16_000
_CELL = 160
_HINT = "Ask for a slice: a smaller limit, offset to page, or read one file at a time."
_ACTIONS: Final[tuple[str, ...]] = ("list", "files", "read", "living")


def _clip(text: Any, limit: int) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + "…"


class ArtifactsTool:
    name = "artifacts"
    risk_tier = "safe"
    is_action_tool = False
    description = (
        "What the agents made: mission outputs and living pages. actions: list (the newest "
        "outputs: slug, request, status, summary, how many deliverables; limit/offset), files "
        "(slug: the deliverable files of one output with title and size), read (slug + path "
        "from files: the text of one file, bounded), living (the living pages the lead keeps "
        "current: title, what it tracks, cadence, state; with slug it reads one page with its "
        "rows). Use it for 'what did the agent produce', 'show me the last report', 'what is "
        "on my dashboard page'. Read-only; use living_page or create_artifact to make or "
        "refresh one."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "slug": {
                "type": "string",
                "description": "files/read: the output slug; living: a page slug.",
            },
            "path": {
                "type": "string",
                "description": "read: the file path exactly as files lists it.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_LIMIT,
                "description": f"list/files/living: rows to return (default {_DEFAULT_LIMIT}).",
            },
            "offset": {"type": "integer", "minimum": 0, "description": "list: rows to skip."},
        },
        "required": ["action"],
    }

    def read_only_for_args(self, args: dict[str, Any]) -> bool:
        return True

    def describe_args(self, args: dict[str, Any]) -> dict[str, str]:
        return {"level": "read", "task": str(args.get("slug") or "")}

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        action = str(args.get("action") or "")
        limit = min(max(int(args.get("limit") or _DEFAULT_LIMIT), 1), _MAX_LIMIT)
        offset = max(int(args.get("offset") or 0), 0)
        slug = str(args.get("slug") or "").strip()
        if action == "list":
            return await self._list(limit, offset)
        if action == "living":
            return await self._living(slug, limit)
        if action not in ("files", "read"):
            return ToolResult(success=False, output=None, error=f"Unknown action {action!r}.")
        if not slug:
            return ToolResult(success=False, output=None, error=f"{action} needs slug.")
        if action == "files":
            return await self._files(slug, limit)
        path = str(args.get("path") or "").strip()
        if not path:
            return ToolResult(success=False, output=None, error="read needs path (see files).")
        return await self._read(slug, path)

    async def _list(self, limit: int, offset: int) -> ToolResult:
        status, data = await call_app_api("GET", "/api/outputs")
        if status is None or status >= 400:
            return failure("The outputs list", status, data)
        rows = [r for r in (data or {}).get("sessions") or [] if isinstance(r, dict)]
        page = rows[offset : offset + limit]
        out: dict[str, Any] = {
            "outputs": [
                {
                    "slug": r.get("slug"),
                    "request": _clip(r.get("utterance"), _CELL),
                    "status": r.get("status"),
                    "summary": _clip(r.get("summary"), 300),
                    "deliverables": r.get("artifact_count"),
                    "started_at": r.get("started_at"),
                    "mission_id": r.get("mission_id"),
                    "needs_review": r.get("needs_review") or None,
                }
                for r in page
            ],
            "total": len(rows),
        }
        if offset + limit < len(rows):
            out["next_offset"] = offset + limit
        return ToolResult(success=True, output=bounded(out, hint=_HINT))

    async def _files(self, slug: str, limit: int) -> ToolResult:
        status, data = await call_app_api("GET", f"/api/outputs/{quote(slug, safe='')}/artifacts")
        if status is None or status >= 400:
            return failure("The deliverables", status, data)
        files = [f for f in (data or {}).get("files") or [] if isinstance(f, dict)]
        out: dict[str, Any] = {
            "slug": slug,
            "files": [
                {
                    "path": f.get("path"),
                    "title": f.get("title"),
                    "size": f.get("size"),
                    "text": f.get("is_text"),
                    "mtime": f.get("mtime"),
                }
                for f in files[:limit]
            ],
            "total": len(files),
        }
        return ToolResult(success=True, output=bounded(out, hint=_HINT))

    async def _read(self, slug: str, path: str) -> ToolResult:
        status, data = await call_app_api(
            "GET", f"/api/outputs/{quote(slug, safe='')}/files/{quote(path, safe='/')}/raw"
        )
        if status is None or status >= 400:
            return failure("Reading the file", status, data)
        data = data if isinstance(data, dict) else {}
        text = str(data.get("text") or "")
        cut = len(text) > _READ_CHARS
        out = {
            "slug": slug,
            "path": data.get("path") or path,
            "size": data.get("size"),
            "text": text[:_READ_CHARS],
            "truncated": cut or bool(data.get("truncated")),
        }
        if out["truncated"]:
            out["note"] = f"Showing the first {_READ_CHARS} characters of {data.get('size')} bytes."
        return ToolResult(success=True, output=bounded(out, hint=_HINT))

    async def _living(self, slug: str, limit: int) -> ToolResult:
        if slug:
            status, data = await call_app_api(
                "GET", f"/api/living-pages/by-slug/{quote(slug, safe='')}"
            )
            if status is None or status >= 400:
                return failure("The living page", status, data)
            page = data if isinstance(data, dict) else {}
            keys = (
                "id",
                "title",
                "track",
                "columns",
                "rows",
                "every_minutes",
                "refreshing",
                "note",
                "updated_at",
                "slug",
                "page_url",
            )
            shaped = {k: page.get(k) for k in keys if k in page}
            return ToolResult(success=True, output=bounded(shaped, hint=_HINT))
        status, data = await call_app_api("GET", "/api/living-pages")
        if status is None or status >= 400:
            return failure("The living pages", status, data)
        pages = [p for p in (data or {}).get("pages") or [] if isinstance(p, dict)]
        out = {
            "pages": [
                {
                    "slug": p.get("slug"),
                    "title": p.get("title"),
                    "track": _clip(p.get("track"), _CELL),
                    "every_minutes": p.get("every_minutes"),
                    "refreshing": p.get("refreshing"),
                    "rows": len(p.get("rows") or []),
                    "updated_at": p.get("updated_at"),
                    "note": _clip(p.get("note"), _CELL),
                }
                for p in pages[:limit]
            ],
            "total": len(pages),
        }
        return ToolResult(success=True, output=bounded(out, hint=_HINT))
