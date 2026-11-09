"""dispatch_to_admin tool — brain calls admin ops via a UAC-elevated helper.

Risk tier = ``ask``, and a person approves every call: the tool is on the
``requires_human_approval`` list, so neither a ``[safety.whitelist]`` entry
nor the global ``approval_mode = "bypass"`` can answer for it.

Destructive ops (DESTRUCTIVE_OPS) run only when that approval came from a
person answering THIS call (``ctx.approved_by == "user"``: the chat card, the
mission card, or the spoken "yes"). The model has no say in it — an earlier
``destructive_approved`` argument let the model approve itself and was
removed (security audit 2026-11-09).

Call flow:

1. Brain calls ``{"op": {...AdminOperation JSON...}}``.
2. ToolExecutor obtains the person's approval for the call.
3. Tool validates the JSON against the Pydantic schema.
4. ``AdminClient.execute(op, destructive_approved=<a person approved>)``.
5. On ``DestructiveRequiresApproval`` (no person approved this call):
   → ``ToolResult(success=False, error="destructive_requires_approval")``.
6. On success/failure: the ``AdminResponse`` model is packed into
   ``ToolResult.output`` as a dict.
"""
from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from dodaios.admin.client import AdminClient, DestructiveRequiresApproval
from dodaios.admin.schema import DESTRUCTIVE_OPS, AdminOperation
from dodaios.core.bus import EventBus
from dodaios.core.protocols import ExecutionContext, ToolResult

_ADMIN_OP_ADAPTER: TypeAdapter[AdminOperation] = TypeAdapter(AdminOperation)

#: ``ExecutionContext.approved_by`` when a person approved the call itself.
HUMAN_APPROVAL = "user"


class DispatchToAdminTool:
    """Protocol-compatible tool. Called by the brain via a tool call."""

    name: str = "dispatch_to_admin"
    risk_tier: str = "ask"
    description: str = (
        "Sends an admin operation (winget install, service start/stop, "
        "firewall, registry write, scheduled task, write_protected_path) "
        "to the UAC-elevated admin helper. Destructive ops "
        "(uninstall, remove, write_registry_hklm, write_protected_path) "
        "need the user's approval of this exact call."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "op": {
                "type": "object",
                "description": (
                    "AdminOperation JSON. Must have a 'type' key "
                    "(e.g. 'install_winget') and the fields required for "
                    "that op type. See dodaios.admin.schema."
                ),
            },
        },
        "required": ["op"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        bus: EventBus | None = None,
        client_factory: Any = None,
    ) -> None:
        self._bus = bus
        # Optional injection for tests — otherwise lazily built in execute.
        self._client_factory = client_factory

    async def execute(
        self, args: dict[str, Any], ctx: ExecutionContext
    ) -> ToolResult:
        op_payload = args.get("op")
        # Only a person answering this very call unlocks a destructive op —
        # never a tool argument, a whitelist, a standing grant or bypass.
        destructive_approved = getattr(ctx, "approved_by", None) == HUMAN_APPROVAL

        if not isinstance(op_payload, dict):
            return ToolResult(
                success=False, output=None,
                error="'op' must be a JSON object.",
            )

        try:
            op = _ADMIN_OP_ADAPTER.validate_python(op_payload)
        except ValidationError as exc:
            return ToolResult(
                success=False, output=None,
                error=f"AdminOperation invalid: {exc.error_count()} error(s)",
            )

        client = self._build_client()
        try:
            resp = await client.execute(
                op, destructive_approved=destructive_approved
            )
        except DestructiveRequiresApproval as dra:
            return ToolResult(
                success=False,
                output={
                    "op_id": dra.op_id,
                    "op_type": dra.op_type,
                    "destructive": True,
                },
                error="destructive_requires_approval",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False, output=None,
                error=f"{type(exc).__name__}: {exc}",
            )

        return ToolResult(
            success=resp.success,
            output={
                "op_id": str(resp.op_id),
                "op_type": op.type,
                "success": resp.success,
                "duration_ms": resp.duration_ms,
                "result": resp.result,
                "destructive": op.type in DESTRUCTIVE_OPS,
            },
            error=resp.error_message if not resp.success else None,
        )

    def _build_client(self) -> AdminClient:
        if self._client_factory is not None:
            return self._client_factory()
        return AdminClient(bus=self._bus)


__all__ = ["DispatchToAdminTool"]
