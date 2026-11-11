"""``recall``: read one object of the lead's world by its id.

Cards in the conversation (reports, event notices, the catch-up block, search
hits, job rows) carry ids such as ``ev:41``, ``job_ab12...``, ``trg:mail:9``,
``thread:...``, ``artifact:...`` and ``agent:...``. ``recall(id)`` answers with
a summary first, the key fields, the ids of the closest related objects and, for
a long body, a ``more`` cursor. Follow those ids to hop from a message to the
work it started and on to its result. Read-only and instant.
"""

from __future__ import annotations

import logging
from typing import Any

from dodaios.agent_chat import recall as recall_core
from dodaios.core.bounded_json import bound_json
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.orchestrator import jobs

log = logging.getLogger(__name__)


class RecallTool:
    name: str = "recall"
    risk_tier: str = "safe"
    is_action_tool: bool = False
    description: str = (
        "Read one thing by its id: a message or report in this conversation (ev:<n>), a "
        "turn (turn:<id>), a thread (thread:<id>), a job (job_<id>), a trigger event "
        "(trg:<id>), an artifact (artifact:<id>) or a team agent (agent:<id>). Returns a "
        "summary, the key fields, the ids of closely related objects under 'related' "
        "(follow them to go from a message to its thread, its job and the job's result) "
        "and, when the body is long, a 'more' offset to pass back as 'more' for the next "
        "page. Use it when a card or report in your context says it has more, or when "
        "the person refers to something from earlier. Read-only."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "An id from a card, a result or an earlier recall.",
            },
            "more": {
                "type": "integer",
                "minimum": 0,
                "description": "The 'more' offset a previous recall returned (next page).",
            },
        },
        "required": ["id"],
    }

    def __init__(self, sources: recall_core.Sources | None = None) -> None:
        self._sources = sources

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        raw = str((args or {}).get("id") or "").strip()
        if not raw:
            return ToolResult(False, "", "'id' is missing. Pass an id such as ev:41 or job_ab12.")
        try:
            more = max(0, int((args or {}).get("more") or 0))
        except (TypeError, ValueError):
            more = 0
        sources = self._sources
        if sources is None:
            try:
                sources = recall_core.live_sources()
            except Exception:  # noqa: BLE001 - the app may not be fully up
                log.warning("recall: sources unavailable", exc_info=True)
                sources = None
        if sources is None:
            return ToolResult(
                False, "", "Nothing can be recalled right now: the chat is not running."
            )
        session, _turn = jobs.owner_of(ctx)
        card = await recall_core.Recall(sources, session=session or sources.lead_session).recall(
            raw, more=more
        )
        found = card.get("found", True) is not False
        return ToolResult(
            found, bound_json(card, recall_core.MAX_ANSWER_CHARS), None if found else card["note"]
        )
