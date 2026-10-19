"""show_on_screen tool: put exact content in front of the user during a call.

A voice says a takeaway well and a table badly. This tool shows Markdown (a
table, a code block, a diff, a list of links) in the conversation the user is
looking at, so the spoken answer can stay one sentence. Inside a live call the
content also becomes part of that call's record, so it is still there when the
conversation is opened again later.

Risk tier: safe - it only displays what the model was about to say anyway.
"""

from __future__ import annotations

from typing import Any

from dodaios.core.events import VoiceContentShown
from dodaios.core.protocols import ExecutionContext, ToolResult

#: A screenful or two; longer material belongs in a file or an artifact.
MAX_MARKDOWN_CHARS = 20_000
_MAX_TITLE_CHARS = 120


def _app_bus() -> Any | None:
    from dodaios.core.runtime_refs import get_brain_manager, get_web_app

    bus = getattr(getattr(get_web_app(), "state", None), "bus", None)
    if bus is not None:
        return bus
    return getattr(get_brain_manager(), "_bus", None)


class ShowOnScreenTool:
    name: str = "show_on_screen"
    risk_tier: str = "safe"
    description: str = (
        "Show exact content on the user's screen instead of reading it out: a table, a "
        "code block, a diff, a list of links or steps, as Markdown. Use it whenever the "
        "answer has more structure than a sentence carries, then say only the takeaway "
        "and that the details are on screen. Never use it for the spoken answer itself "
        "or for something the user did not ask to see."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "markdown": {
                "type": "string",
                "description": "The content, as GitHub-flavoured Markdown.",
            },
            "title": {
                "type": "string",
                "description": "A short heading for it, in the user's language.",
            },
        },
        "required": ["markdown"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        markdown = str(args.get("markdown") or "").strip()
        if not markdown:
            return ToolResult(success=False, output=None, error="markdown is missing")
        if len(markdown) > MAX_MARKDOWN_CHARS:
            return ToolResult(
                success=False,
                output=None,
                error=(
                    f"Too long to show ({len(markdown)} characters, at most "
                    f"{MAX_MARKDOWN_CHARS}). Shorten it or write it to a file."
                ),
            )
        title = " ".join(str(args.get("title") or "").split())[:_MAX_TITLE_CHARS]
        session_id = str((getattr(ctx, "config", None) or {}).get("live_session_id") or "")
        if session_id:
            from dodaios.live.runtime import show_content

            if await show_content(session_id, title=title, markdown=markdown):
                return ToolResult(success=True, output={"shown": True, "kept_in_call": True})
        # No live call owns this turn: show it, without a call record to keep it in.
        bus = _app_bus()
        if bus is None:
            return ToolResult(
                success=False, output=None, error="No screen is connected to show this on."
            )
        await bus.publish(
            VoiceContentShown(
                trace_id=ctx.trace_id, source_layer="brain.tool.show_on_screen",
                session_id="", title=title, markdown=markdown,
            )
        )
        return ToolResult(success=True, output={"shown": True, "kept_in_call": False})
