"""Background tasks of one live call: actions that outlive the turn that started them.

A spoken order ("brief the agent in terminal two") can take longer than the
user's attention. When the user moves on to the next order, the running action
is handed over to this board instead of holding the conversation: its function
call is answered at once with a pending receipt, the action keeps running, and
its real receipt is reported back at the next pause together with the request
it answers. Several such tasks run side by side.

The board is plain bookkeeping for one call. It never executes, authorizes or
retries anything; ``LiveTools`` owns execution and the session owns delivery.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["BackgroundTask", "TaskBoard", "report_prompt"]

#: Finished tasks kept for ``task_status`` and follow-up questions.
_FINISHED_KEPT = 24
_SUMMARY_CHARS = 240
_REQUEST_CHARS = 600

RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
#: The action stopped at its approval question; the user's yes is still owed.
NEEDS_APPROVAL = "needs_approval"
#: How much of a result ``task_status`` shows; the report carries the whole.
_RESULT_CHARS = 2000


@dataclass(slots=True, eq=False)
class BackgroundTask:
    """One action that left its turn and finishes on its own."""

    task_id: str
    tool: str
    arguments: dict
    #: What the action does, from the tool's own description of its arguments.
    summary: str
    #: The user's words for the order, so the report can name what it answers.
    request_text: str
    revision: int
    #: The connection generation the action started on.
    epoch: int
    work: asyncio.Future
    cancel_token: Any = None
    #: A late screenshot or lookup only answers the request it was made for;
    #: an action's outcome is owed whatever the user said in between.
    obsolete_on_new_request: bool = False
    status: str = RUNNING
    result: dict | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float = 0.0
    #: How often the call was handed this task's report without voicing it.
    report_attempts: int = 0

    @property
    def running(self) -> bool:
        return self.status == RUNNING

    def describe(self) -> dict[str, Any]:
        """The model-facing state of this task. No arguments: they may be large."""
        now = self.finished_at or time.monotonic()
        row: dict[str, Any] = {
            "task_id": self.task_id,
            "tool": self.tool,
            "doing": self.summary,
            "requested": self.request_text,
            "status": self.status,
            "seconds": round(max(0.0, now - self.started_at)),
        }
        if self.result is not None:
            row["result"] = _preview(self.result)
        return row


def _preview(result: dict) -> dict:
    """A result for a status listing: no pictures, and no page-long output."""
    shown = {key: value for key, value in result.items() if key != "artifacts"}
    output = shown.get("output")
    if isinstance(output, dict) and "_image" in output:
        shown["output"] = {key: value for key, value in output.items() if key != "_image"}
    text = json.dumps(shown, ensure_ascii=False, default=str)
    if len(text) <= _RESULT_CHARS:
        return shown
    return {
        "success": bool(result.get("success")),
        "excerpt": text[:_RESULT_CHARS] + " …",
        "note": "Shortened; the task's report carries the full result.",
    }


class TaskBoard:
    """The background tasks of one live call, newest last."""

    def __init__(self) -> None:
        self._tasks: list[BackgroundTask] = []
        self._count = 0

    def __len__(self) -> int:
        return len(self._tasks)

    def add(
        self,
        *,
        tool: str,
        arguments: dict,
        summary: str,
        request_text: str,
        revision: int,
        epoch: int,
        work: asyncio.Future,
        cancel_token: Any = None,
        obsolete_on_new_request: bool = False,
    ) -> BackgroundTask:
        self._count += 1
        task = BackgroundTask(
            task_id=f"task-{self._count}",
            tool=tool,
            arguments=dict(arguments),
            summary=" ".join(str(summary or tool).split())[:_SUMMARY_CHARS],
            request_text=" ".join(str(request_text or "").split())[-_REQUEST_CHARS:],
            revision=revision,
            epoch=epoch,
            work=work,
            cancel_token=cancel_token,
            obsolete_on_new_request=obsolete_on_new_request,
        )
        self._tasks.append(task)
        finished = [item for item in self._tasks if not item.running]
        for old in finished[: max(0, len(finished) - _FINISHED_KEPT)]:
            self._tasks.remove(old)
        return task

    def get(self, task_id: str) -> BackgroundTask | None:
        wanted = str(task_id or "").strip().casefold()
        return next((task for task in self._tasks if task.task_id == wanted), None)

    def running(self) -> list[BackgroundTask]:
        return [task for task in self._tasks if task.running]

    def snapshot(self) -> list[dict[str, Any]]:
        return [task.describe() for task in self._tasks]

    def settle(self, task: BackgroundTask, work: asyncio.Future) -> None:
        """Record how the action ended. A cancel already recorded stands."""
        task.finished_at = time.monotonic()
        if task.status == CANCELLED or work.cancelled():
            task.status = CANCELLED
            return
        if work.exception() is not None:
            task.status = FAILED
            task.result = {
                "success": False,
                "error": "The action failed; inspect its state before retrying.",
            }
            return
        result = work.result()
        task.result = result if isinstance(result, dict) else {"output": result}
        if task.result.get("confirmation_required"):
            task.status = NEEDS_APPROVAL
        else:
            task.status = DONE if task.result.get("success") else FAILED

    def cancel(self, task: BackgroundTask) -> bool:
        """Stop one running task. Its effect may already have happened."""
        if not task.running:
            return False
        task.status = CANCELLED
        task.finished_at = time.monotonic()
        task.work.cancel()
        return True

    def cancel_all(self) -> list[BackgroundTask]:
        return [task for task in self.running() if self.cancel(task)]


def report_prompt(task: BackgroundTask, result: dict | None, *, language: str) -> str:
    """The prompt that hands a live model this task's receipt (images removed)."""
    from jarvis.realtime.report_prompt import task_report_prompt

    return task_report_prompt(
        task_id=task.task_id,
        tool=task.tool,
        request=task.request_text,
        doing=task.summary,
        status=task.status,
        receipt=json.dumps(
            task.result if result is None else result, ensure_ascii=False, default=str
        ),
        language=language,
    )
