"""``show_result_card`` — one compact card listing what a multi-step request made.

A request that chains apps ("turn this mail into a calendar event and a task,
and draft the reply") ends with several things in several places. The reply
says it in words; this card shows it as a list the person can click: each
created thing with a link, each draft marked as a draft, and each outgoing
part that still waits for the person's go marked as waiting.

It only posts a card into the conversation that called it (the lead's one
conversation when the caller is unknown). Nothing is created, sent or
changed by the tool itself — risk ``safe``.
"""

from __future__ import annotations

from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.plugins.tool.living_page import post_card, session_of

#: What a row can be; the card picks its icon from this.
KINDS: Final[tuple[str, ...]] = (
    "event",
    "task",
    "draft",
    "message",
    "page",
    "note",
    "file",
    "contact",
    "other",
)
#: ``created`` exists now; ``draft`` exists unsent; ``waiting`` needs the
#: person's go before it leaves (an outgoing part not yet sent).
STATES: Final[tuple[str, ...]] = ("created", "updated", "draft", "waiting", "failed")
MAX_ITEMS: Final[int] = 12


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value if value is not None else "").split())[:limit]


def normalize_items(raw: Any) -> list[dict[str, str]]:
    """The card's rows, reduced to known fields; links only over http(s)."""
    items: list[dict[str, str]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        label = _clean(entry.get("label") or entry.get("title"), 160)
        if not label:
            continue
        kind = _clean(entry.get("kind"), 20).lower()
        state = _clean(entry.get("state") or entry.get("status"), 20).lower()
        item = {
            "kind": kind if kind in KINDS else "other",
            "label": label,
            "state": state if state in STATES else "created",
        }
        detail = _clean(entry.get("detail"), 200)
        if detail:
            item["detail"] = detail
        url = _clean(entry.get("url"), 2000)
        if url.startswith(("https://", "http://")):
            item["url"] = url
        artifact = _clean(entry.get("artifact"), 400)
        if "::" in artifact:
            item["artifact"] = artifact
        items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    return items


class ResultCardTool:
    """Show the person one card listing what a chained request created."""

    name: str = "show_result_card"
    risk_tier: str = "safe"
    description: str = (
        "Show ONE compact card in the conversation that lists what a multi-step "
        "request across apps produced, with links: calendar events, tasks, drafts, "
        "pages, notes. Call it once, at the end of such a request, after the work is "
        "done. Mark a draft as state 'draft' and an outgoing part that still needs the "
        "person's go as 'waiting'. Use the web link each app returned as 'url'. Do not "
        "call it for a single action or an ordinary answer."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A few words, e.g. the mail's subject."},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "label": {"type": "string"},
                        "state": {"type": "string", "enum": list(STATES)},
                        "url": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "required": ["kind", "label"],
                },
            },
        },
        "required": ["items"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        args = args or {}
        items = normalize_items(args.get("items"))
        if not items:
            return ToolResult(False, "", "'items' must list at least one thing with a label.")
        payload = {
            "kind": "chain_result",
            "text": _clean(args.get("title"), 120),
            "items": items,
        }
        if not await post_card(session_of(ctx), payload):
            return ToolResult(False, "", "The conversation is not available for a card.")
        waiting = sum(1 for item in items if item["state"] == "waiting")
        tail = f" {waiting} part(s) wait for the person's go." if waiting else ""
        return ToolResult(True, f"Card shown with {len(items)} item(s).{tail}")


__all__ = ["KINDS", "STATES", "ResultCardTool", "normalize_items"]
