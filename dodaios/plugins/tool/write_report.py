"""``write_report`` — put a long answer on a page and keep the chat short.

When the full answer to a request is a document (the important mails of the
week, a comparison, a research summary, a plan, more than a handful of items),
the assistant writes it here as Markdown. The tool lays it out as a page in
the Artifacts section (:mod:`dodaios.artifacts.report`) and posts a report
card into the conversation that called it. The reply in the chat is then two
or three sentences: the gist, and what needs the person.

Router-tier, risk ``monitor``: it writes one page in the run archive and posts
one card. It never sends anything, never spawns a worker and never calls a
model, so it costs nothing and returns at once.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.orchestrator import jobs
from dodaios.plugins.tool.living_page import post_card, session_of

log = logging.getLogger(__name__)


def _language(ctx: Any, args: dict[str, Any]) -> str:
    config = getattr(ctx, "config", None)
    stamped = str(config.get("output_language") or "") if isinstance(config, dict) else ""
    return (stamped or str(args.get("language") or "") or "en").strip().lower()[:8]


def report_card(report: Any) -> dict[str, Any]:
    """The conversation notice that shows a report and opens it."""
    return {
        "kind": "report",
        "text": report.title,
        "summary": report.summary,
        "artifact": report.visual_id,
        "sections": report.sections,
    }


class WriteReportTool:
    """Write a long answer as a report page and show its card in the chat."""

    name: str = "write_report"
    risk_tier: str = "monitor"
    description: str = (
        "Put a long answer on a REPORT page instead of into the chat. Use it when the "
        "full answer is a document: more than about six items, several sections, a "
        "comparison or table, a research summary, a plan, a digest of mails or news. "
        "Write the complete report in Markdown (## sections, short bullets, tables "
        "where they help; no title line, the page shows the title). The page opens "
        "in the Artifacts section and a report card appears in the chat. Then reply "
        "in two or three short sentences: the gist and what needs the person; do not "
        "repeat the report in the chat."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A few words, e.g. 'Mails, 6-11 Nov'."},
            "summary": {
                "type": "string",
                "description": "One or two sentences shown under the title: the gist.",
            },
            "markdown": {"type": "string", "description": "The full report in Markdown."},
            "language": {"type": "string", "description": "The person's language code."},
        },
        "required": ["title", "markdown"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        from dodaios.artifacts.report import ReportError, write_report

        args = args or {}
        try:
            report = await asyncio.to_thread(
                write_report,
                title=str(args.get("title") or ""),
                summary=str(args.get("summary") or ""),
                markdown=str(args.get("markdown") or ""),
                language=_language(ctx, args),
            )
        except ReportError as exc:  # the model's call to fix; the error says how
            return ToolResult(False, "", str(exc))
        except OSError as exc:
            log.warning("write_report: archive not writable", exc_info=True)
            return ToolResult(False, "", f"The report could not be saved: {exc}")
        # Written synchronously, so the job is already done; the ledger lists the page.
        job_id = jobs.start(
            "artifact", ctx=ctx, title=report.title, target=f"report:{report.id}",
            meta={"report_id": report.id},
        )
        jobs.finish(
            job_id, "done", summary="Report page.", result_ref=f"artifact:{report.visual_id}"
        )
        shown = await post_card(session_of(ctx), report_card(report))
        where = (
            "Its card is in the chat"
            if shown
            else "It is in the Artifacts section (no card could be posted)"
        )
        return ToolResult(
            True,
            jobs.with_job_id(
                f"Report '{report.title}' saved. {where}. Now reply in two or three "
                "short sentences: the gist and what needs the person. Do not repeat "
                "the report.",
                job_id, ctx,
            ),
        )


__all__ = ["WriteReportTool", "report_card"]
