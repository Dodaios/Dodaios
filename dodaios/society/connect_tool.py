"""``society_request_connect``: an agent asks the person to connect a plugin or CLI.

The chat shows a small card with the service's logo and a Connect button
("Connect GitHub · Lets Ada read your issues"). The button runs the same
sign-in the Plugins and CLIs pages run; when it finishes, the card reports
back and this side checks that the connection really exists before the agent
hears "connected". Nothing secret passes through the card: the sign-in
happens with the provider, its token goes to the existing token store.

The card reuses the secure field plumbing (credential_requests.py) with the
kinds ``plugin`` and ``cli``: it stays open across turns and restarts, and
the agent checks it on a later turn with ``wait_for``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from dodaios.agent_chat.credential_requests import (
    CANCELLED,
    CLI,
    DECLINED,
    MAX_REQUESTS_PER_TURN,
    PLUGIN,
    SAVED,
    CredentialSpec,
    TooManyCredentialRequests,
)
from dodaios.core.protocols import ToolResult

from .credentials import CredentialError
from .routine_runner import is_routine_session

log = logging.getLogger(__name__)

__all__ = [
    "CONNECT_TOOL_NAME",
    "RequestConnectTool",
    "connect_save",
    "lead_connect_tools",
    "resolve_target",
]

CONNECT_TOOL_NAME: Final[str] = "society_request_connect"


@dataclass(frozen=True, slots=True)
class Target:
    kind: str
    id: str
    label: str
    connected: bool | None


def _plugin(raw: str) -> Target | None:
    from dodaios.marketplace.catalog_data import load_catalog

    catalog = load_catalog()
    for candidate in (raw, raw.replace("-", "_"), raw.replace("_", "-")):
        spec = catalog.by_id(candidate)
        if spec is not None:
            return Target(PLUGIN, spec.id, spec.display_name, _plugin_connected(spec.id))
    return None


def _plugin_connected(plugin_id: str) -> bool | None:
    from .runtime import current_runtime

    rt = current_runtime()
    state = getattr(rt, "_plugin_state", None) if rt is not None else None
    if not callable(state):
        return None
    try:
        _catalog_ids, usable = state()
    except Exception:  # noqa: BLE001 — unknown state is reported as unknown
        log.warning("society connect: plugin state unavailable", exc_info=True)
        return None
    return plugin_id in set(usable)


def _cli(raw: str) -> Target | None:
    from dodaios.clis.shared import get_active_registry

    registry = get_active_registry()
    if registry is None:
        return None
    spec = registry.catalog().get(raw)
    if spec is None:
        return None
    status = registry.status_of(spec.name)
    connected = None if status is None else bool(
        status.installed and status.auth_status == "connected"
    )
    return Target(CLI, spec.name, spec.display_name, connected)


def resolve_target(kind: str, raw: str) -> Target | None:
    """The plugin or CLI ``raw`` names, with its current connection state."""
    ident = str(raw or "").strip().lower()
    if not ident:
        return None
    if kind == PLUGIN:
        return _plugin(ident)
    if kind == CLI:
        return _cli(ident)
    return None


def connect_save(kind: str, target_id: str) -> Callable[[str], Awaitable[None]]:
    """The card's receipt: accepted only when the connection really exists now."""

    async def save(_value: str) -> None:
        if kind == CLI:
            from dodaios.clis.shared import get_active_registry

            registry = get_active_registry()
            if registry is not None:
                try:
                    await registry.refresh_status(target_id)
                except Exception:  # noqa: BLE001 — the cached status still decides
                    log.debug("society connect: CLI re-check failed", exc_info=True)
        target = await asyncio.to_thread(resolve_target, kind, target_id)
        if target is None or target.connected is False:
            raise CredentialError(
                "Not connected yet. Finish signing in, then press Connect again.",
                code="not_connected",
            )

    return save


class RequestConnectTool:
    """Ask the person to connect a plugin or CLI through a card in the chat."""

    name: str = CONNECT_TOOL_NAME
    risk_tier: str = "safe"
    is_action_tool: bool = False
    description: str = (
        "Ask the user to connect a Dodaios plugin (kind 'plugin', a marketplace id such as "
        "'github', 'notion', 'gmail') or a command-line tool (kind 'cli', a CLI name such as "
        "'gh', 'vercel'). It shows a small card with the service's logo and a Connect button "
        "in the user's chat; the button starts the normal sign-in. Use it when a task needs "
        "a service that is listed but not connected, instead of telling the user to go to "
        "the Plugins page. Give in reason what you will do with it, one sentence in the "
        "user's language. A connected service returns 'connected' at once. While the user "
        "has not finished, the call returns 'waiting' with a request_id; do not poll. The "
        "card stays open; on a later turn, wait_for checks it."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": [PLUGIN, CLI]},
            "id": {"type": "string", "description": "The plugin id or the CLI name."},
            "reason": {
                "type": "string",
                "description": "One sentence: what you will do once it is connected.",
            },
            "wait_for": {
                "type": "string",
                "description": "The request_id of an earlier 'waiting' result. Send it alone.",
            },
        },
    }

    def __init__(
        self,
        runtime: Any,
        agent_id: str,
        *,
        session_id: str,
        unconnected: Sequence[str] = (),
    ) -> None:
        self._runtime = runtime
        self._agent_id = agent_id
        self._session_id = session_id
        # A caller without a briefing (the lead's chat) learns from the tool
        # itself which plugins it can offer.
        offer = sorted({p for p in unconnected if p})
        if offer:
            self.description = (
                f"{type(self).description} Not connected right now: {', '.join(offer)}. "
                "When a task needs one of them, call this before anything else; do not "
                "send the user to the Plugins page and do not answer that you cannot do it."
            )

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        wait_for = str(args.get("wait_for") or "").strip()
        if wait_for:
            return await self._check_existing(wait_for)
        kind = str(args.get("kind") or "").strip().lower()
        if kind not in (PLUGIN, CLI):
            return _invalid("kind must be 'plugin' or 'cli'")
        raw = str(args.get("id") or "")
        try:
            target = await asyncio.to_thread(resolve_target, kind, raw)
        except Exception:  # noqa: BLE001 — a broken catalog is reported, not raised
            log.warning("society connect: catalog unavailable", exc_info=True)
            return _invalid("the catalog is not available right now")
        if target is None:
            return _invalid(
                f"no {kind} named {raw!r}. Use an id from your capability list or the "
                "Plugins / CLIs catalog."
            )
        if target.connected:
            return ToolResult(
                success=True,
                output={"status": "connected", "kind": kind, "id": target.id},
            )
        if is_routine_session(self._session_id):
            return ToolResult(
                success=False,
                output={"status": "unattended", "id": target.id},
                error=f"Routines cannot ask to connect {target.label}. Report it instead.",
            )
        reason = " ".join(str(args.get("reason") or "").split())
        if not reason:
            return _invalid("reason is required: say what you will do once it is connected")
        spec = CredentialSpec.build(target.id, target.label, reason, kind=kind)
        service = self._runtime.chat_service()
        if service is None or not callable(getattr(service, "open_credential_request", None)):
            return _nobody(target.label)
        try:
            request_id = await service.open_credential_request(
                self._session_id, spec, connect_save(kind, target.id), asker=self._asker()
            )
        except TooManyCredentialRequests as exc:  # The limit is the visible tool error.
            return ToolResult(
                success=False,
                output={"status": "limit", "id": target.id},
                error=f"Card limit reached: {exc}. At most {MAX_REQUESTS_PER_TURN} per turn.",
            )
        except RuntimeError as exc:  # No running turn: reported as unattended.
            log.info("society connect: %s cannot ask here (%s)", self._agent_id, exc)
            return _nobody(target.label)
        return await self._status(service, request_id, spec)

    async def _check_existing(self, request_id: str) -> ToolResult:
        service = self._runtime.chat_service()
        try:
            await service.restore_credential_requests(self._session_id)
            spec = service.credential_request_spec(self._session_id, request_id)
        except (AttributeError, KeyError):  # An unknown id is the visible tool error.
            return _invalid("no connect card with that id in this chat")
        return await self._status(service, request_id, spec)

    async def _status(self, service: Any, request_id: str, spec: CredentialSpec) -> ToolResult:
        status = await service.wait_credential_request(self._session_id, request_id, 0)
        if status is None:
            return ToolResult(
                success=True,
                output={
                    "status": "waiting",
                    "request_id": request_id,
                    "id": spec.env,
                    "note": (
                        f"The user has not connected {spec.label} yet. The card stays open. "
                        "Continue unrelated work or finish your reply now; do not poll. On a "
                        f'later turn, check it with {{"wait_for": "{request_id}"}}.'
                    ),
                },
            )
        if status == SAVED:
            return ToolResult(
                success=True,
                output={
                    "status": "connected",
                    "kind": spec.kind,
                    "id": spec.env,
                    "note": f"{spec.label} is connected; its tools reach you from the next turn.",
                },
            )
        if status == CANCELLED:
            return ToolResult(
                success=False,
                output={"status": CANCELLED, "id": spec.env},
                error="The user stopped this turn. Do not continue the task.",
            )
        reason = "The user declined." if status == DECLINED else "The card closed."
        return ToolResult(
            success=False,
            output={"status": status, "id": spec.env},
            error=(
                f"{reason} {spec.label} is not connected. Continue without it where you can. "
                "Do not ask again in this turn."
            ),
        )

    def _asker(self) -> str:
        cached = getattr(self._runtime, "cached_agent", None)
        agent = cached(self._agent_id) if callable(cached) else None
        return str(getattr(agent, "name", "") or "")


def lead_connect_tools(session: Any) -> dict[str, Any]:
    """The same Connect card for the lead's own chat (surface ``jarvis``)."""
    from .runtime import current_runtime

    rt = current_runtime()
    session_id = str(getattr(session, "session_id", "") or "")
    if rt is None or not session_id or is_routine_session(session_id):
        return {}
    try:
        unconnected = rt.unconnected_plugins()
    except Exception:  # noqa: BLE001 — the card works without the list
        log.warning("society connect: plugin state unavailable", exc_info=True)
        unconnected = []
    return {
        CONNECT_TOOL_NAME: RequestConnectTool(
            rt, rt.lead_id, session_id=session_id, unconnected=unconnected
        )
    }


def _invalid(detail: str) -> ToolResult:
    return ToolResult(success=False, output=None, error=f"invalid request: {detail}")


def _nobody(label: str) -> ToolResult:
    return ToolResult(
        success=False,
        output={"status": "unattended"},
        error=f"Nobody can connect {label} in this run. Report that the user has to do it.",
    )
