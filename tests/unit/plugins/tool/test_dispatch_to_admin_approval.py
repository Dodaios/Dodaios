"""dispatch_to_admin: only a person's approval of the call unlocks a destructive op.

Security audit 2026-11-09: a ``destructive_approved`` tool argument let the
model approve its own destructive admin operation.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from dodaios.admin.client import DestructiveRequiresApproval
from dodaios.admin.schema import DESTRUCTIVE_OPS, AdminResponse
from dodaios.core.protocols import ExecutionContext
from dodaios.plugins.tool.dispatch_to_admin import DispatchToAdminTool

_SCHEDULED_TASK = {
    "type": "add_scheduled_task", "task_name": "x", "schedule_xml": "<xml/>",
}


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def execute(self, op: Any, *, destructive_approved: bool = False) -> AdminResponse:
        self.calls.append(destructive_approved)
        if op.type in DESTRUCTIVE_OPS and not destructive_approved:
            raise DestructiveRequiresApproval(op)
        return AdminResponse(op_id=op.op_id, success=True)


def _ctx(approved_by: str | None) -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(), user_utterance="", config={}, memory_read=None,
        approved_by=approved_by,
    )


def test_the_schema_has_no_self_approval_argument() -> None:
    schema = DispatchToAdminTool.schema
    assert "destructive_approved" not in schema["properties"]
    assert schema["additionalProperties"] is False


def test_a_scheduled_task_is_destructive() -> None:
    assert "add_scheduled_task" in DESTRUCTIVE_OPS


@pytest.mark.parametrize(
    "approved_by", [None, "auto", "bypass", "whitelist", "chat-bypass", "scheduled-task:x"],
)
async def test_a_destructive_op_without_a_persons_approval_is_refused(approved_by) -> None:
    client = _FakeClient()
    tool = DispatchToAdminTool(client_factory=lambda: client)
    result = await tool.execute(
        {"op": _SCHEDULED_TASK, "destructive_approved": True}, _ctx(approved_by)
    )
    assert not result.success
    assert result.error == "destructive_requires_approval"
    assert client.calls == [False]


async def test_a_persons_approval_unlocks_the_destructive_op() -> None:
    client = _FakeClient()
    tool = DispatchToAdminTool(client_factory=lambda: client)
    result = await tool.execute({"op": _SCHEDULED_TASK}, _ctx("user"))
    assert result.success
    assert client.calls == [True]
