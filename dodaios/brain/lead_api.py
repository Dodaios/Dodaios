"""One in-process call into the app's own REST surface, for the lead's thin tools.

The lead's ``team_thread``, ``costs_summary`` and ``artifacts`` tools wrap routes
the UI already uses, so they can never drift from what the matching section
shows. The call runs in-process through the same transport ``run-app-action``
uses (with the same control key, timezone and chat headers); it adds no
execution logic of its own.
"""

from __future__ import annotations

import json
from typing import Any

from dodaios.core.bounded_json import bound_json
from dodaios.core.protocols import ToolResult

#: Character budget of one tool answer. A provider/receiver limit, not a cost lever:
#: bigger answers come back structurally trimmed with a hint to ask for a slice.
ANSWER_CHARS = 24_000


async def call_app_api(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: Any = None,
) -> tuple[int | None, Any]:
    """``(status, data)`` of one request to the running app; status ``None`` when it is down."""
    from dodaios.plugins.tool.app_action import RunAppActionTool

    return await RunAppActionTool()._request(method, path, query or {}, body)  # noqa: SLF001


def failure(what: str, status: int | None, data: Any) -> ToolResult:
    """A refusal or an outage as an honest tool error (never an empty success)."""
    if status is None:
        return ToolResult(success=False, output=None, error=f"{what}: {data}")
    detail = data.get("detail", data) if isinstance(data, dict) else data
    return ToolResult(
        success=False, output={"status": status}, error=f"{what} failed: HTTP {status}: {detail}"
    )


def bounded(value: Any, *, hint: str, max_chars: int = ANSWER_CHARS) -> Any:
    """``value`` as plain data within the answer budget (structurally trimmed, still valid)."""
    return json.loads(bound_json(value, max_chars, hint=hint))
