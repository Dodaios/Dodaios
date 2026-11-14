"""``run_shell`` in the lead's own chat: the owner's secrets set, never shown.

A secret the owner pasted into the lead's secure field
(``society_request_credential``) lives in the owner's vault, the lead's
(``credentials.py``). The lead uses it by name: every command its chat runs
through ``run_shell`` gets the stored values as environment variables, and the
command's output is masked before the model reads it. A command that would read
the secret store itself is refused (``credential_broker/vault_guard.py``).

Voice turns, workers and coding threads keep the plain ``run_shell``: only the
lead's chat is wrapped (``BrainSupervisorToolGateway.lead_session_tools``).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Final

from dodaios.core.protocols import ToolResult
from dodaios.credential_broker.vault_guard import refusal

log = logging.getLogger(__name__)

__all__ = ["SHELL_NAME", "VaultShellTool", "with_vault_shell"]

SHELL_NAME: Final[str] = "run_shell"


class VaultShellTool:
    """Wraps ``run_shell``: same name, schema and risk hooks, plus the vault."""

    def __init__(self, inner: Any, agent_id: str) -> None:
        self._inner = inner
        self._agent_id = agent_id
        self.name = getattr(inner, "name", SHELL_NAME)
        try:
            params = inspect.signature(inner.execute).parameters
        except (TypeError, ValueError):  # not introspectable: run it as it is
            params = {}
        self._takes_env = "extra_env" in params

    def __getattr__(self, item: str) -> Any:
        # Description, schema, risk tier and the per-call risk hooks stay the
        # inner tool's, so the safety layer judges the call exactly as before.
        return getattr(self._inner, item)

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        reason = refusal(str(args.get("command") or ""))
        if reason:
            return ToolResult(success=False, output=None, error=reason)
        from .credentials import current_vault

        vault = current_vault()
        secrets: dict[str, str] = {}
        if vault is not None:
            try:
                secrets = await asyncio.to_thread(vault.shell_env, self._agent_id)
            except Exception:  # noqa: BLE001 - an unreadable store runs the command without it
                log.warning("lead shell: the vault could not be read", exc_info=True)
        if vault is None or not secrets or not self._takes_env:
            return await self._inner.execute(args, ctx)
        result = await self._inner.execute(args, ctx, extra_env=secrets)
        return ToolResult(
            success=result.success,
            output=vault.redact_payload(self._agent_id, result.output),
            error=vault.redact(self._agent_id, result.error) if result.error else result.error,
            artifacts=result.artifacts,
        )


def with_vault_shell(tools: dict[str, Any]) -> dict[str, Any]:
    """``tools`` with its ``run_shell`` wrapped for the lead's chat (unchanged without one)."""
    inner = tools.get(SHELL_NAME)
    if inner is None or isinstance(inner, VaultShellTool):
        return tools
    from .roster import LEAD_AGENT_ID

    return {**tools, SHELL_NAME: VaultShellTool(inner, LEAD_AGENT_ID)}
