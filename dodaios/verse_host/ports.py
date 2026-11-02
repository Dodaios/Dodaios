"""What the verse host needs from the rest of the backend, as one port.

The relays never speak HTTP: every command is "executed by the relay
in-process" (architecture 5.2). :class:`AppBackend` calls the same route
functions the web UI reaches over REST, with a synthetic request bound to
the running app, so both callers share one code path. Tests use a fake port.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

log = logging.getLogger(__name__)


class UnknownWorldAction(ValueError):
    """``progression.action`` named an action the rulebook does not list."""


class NotFound(LookupError):
    """The pane, agent, group or session a command names is gone."""


OutputHandler = Callable[[str], Awaitable[None]]
ExitHandler = Callable[[int], Awaitable[None]]


class BackendPort(Protocol):
    """Reads and actions of the backend the relays use."""

    @property
    def bus(self) -> Any: ...

    async def list_agents(self) -> list[dict[str, Any]]: ...
    async def list_panes(self) -> list[dict[str, Any]]: ...
    async def progression(self) -> dict[str, Any]: ...
    async def report_action(self, action: str, ref: str) -> dict[str, Any] | None: ...
    def duel_service(self) -> Any | None: ...
    async def chat_tail(self, session_id: str, tail: int) -> list[dict[str, Any]] | None: ...
    async def chat_groups(self) -> list[dict[str, Any]]: ...
    async def group_meeting(self, group_id: str) -> dict[str, Any] | None: ...
    async def meeting_start(self, group_id: str, text: str) -> dict[str, Any]: ...
    async def meeting_stop(self, group_id: str) -> dict[str, Any]: ...
    async def confirm_dangerous(self, action: str, detail: str) -> bool: ...
    async def create_agent(self, fields: dict[str, Any]) -> str: ...
    async def ide_state(self) -> dict[str, Any]: ...
    async def ide_agents(self) -> list[dict[str, Any]]: ...
    async def open_terminal(self, workspace_id: str | None, agent: str) -> tuple[str, str]: ...
    async def start_terminal(self, name: str, workspace_id: str) -> None: ...
    async def prompt_terminal(self, name: str, text: str, workspace_id: str) -> bool | None: ...
    async def active_pet(self) -> dict[str, Any]: ...
    async def attach_screen(
        self, pane_id: str, on_output: OutputHandler, on_exit: ExitHandler
    ) -> tuple[int, int] | None: ...
    def detach_screen(self, pane_id: str, on_output: OutputHandler) -> None: ...
    def plain_screen(self, pane_id: str) -> dict[str, Any] | None: ...


def split_pane_id(pane_id: str) -> tuple[str, str]:
    """``<workspace_id>:<key>`` -> ``(workspace_id, key)``; NotFound when malformed."""
    workspace_id, sep, key = pane_id.partition(":")
    if not sep or not workspace_id or not key:
        raise NotFound(f"bad pane id {pane_id!r}")
    return workspace_id, key


def _status(exc: BaseException) -> int | None:
    return getattr(exc, "status_code", None)


class AppBackend:
    """The live backend: route functions called in-process against ``app``."""

    def __init__(self, app: Any) -> None:
        self.app = app

    @property
    def bus(self) -> Any:
        return getattr(self.app.state, "bus", None)

    def _request(self, method: str = "GET") -> Any:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "app": self.app,
            "method": method,
            "path": "/api/verse/bridge",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 0),
        }
        return Request(scope)

    # ------------------------------------------------------------------ reads
    async def list_agents(self) -> list[dict[str, Any]]:
        from dodaios.ui.web import society_routes

        body = await society_routes.list_agents(self._request(), include_archived=False)
        return list(body.get("agents", []))

    async def list_panes(self) -> list[dict[str, Any]]:
        from dodaios.ui.web import agentic_ide_routes

        body = await asyncio.to_thread(agentic_ide_routes.get_panes)
        return list(body.get("panes", []))

    async def progression(self) -> dict[str, Any]:
        from dodaios.ui.web import progression_routes

        return await progression_routes.get_progression(self._request(), after_seq=0)

    async def report_action(self, action: str, ref: str) -> dict[str, Any] | None:
        from dodaios.progression.service import UnknownAction

        service = getattr(self.app.state, "progression", None)
        if service is None:
            raise RuntimeError("progression service is not running")
        try:
            award = await service.report_action(action, ref=ref)
        except UnknownAction as exc:
            raise UnknownWorldAction(str(exc)) from exc
        return award.to_dict() if award is not None else None

    def duel_service(self) -> Any | None:
        """The progression service when it records duels (WP21), else ``None``."""
        service = getattr(self.app.state, "progression", None)
        return service if callable(getattr(service, "record_duel", None)) else None

    async def chat_tail(self, session_id: str, tail: int) -> list[dict[str, Any]] | None:
        from dodaios.ui.web import agent_chat_routes

        try:
            body = await agent_chat_routes.get_session(session_id, self._request(), tail=tail)
        except Exception as exc:  # noqa: BLE001 - a 404 means "no chat yet"
            if _status(exc) == 404:
                return None
            raise
        return list(body.get("events", []))

    async def chat_groups(self) -> list[dict[str, Any]]:
        from dodaios.ui.web import society_routes

        body = await society_routes.list_chat_groups(self._request())
        return list(body.get("groups", body.get("chat_groups", [])))

    async def group_meeting(self, group_id: str) -> dict[str, Any] | None:
        from dodaios.ui.web import society_routes

        try:
            return await society_routes.get_group_meeting(group_id, self._request())
        except Exception as exc:  # noqa: BLE001
            if _status(exc) == 404:
                return None
            raise

    async def meeting_start(self, group_id: str, text: str) -> dict[str, Any]:
        from dodaios.ui.web import society_routes

        body = society_routes.MeetingMessageBody(text=text)
        try:
            return await society_routes.send_group_meeting(group_id, body, self._request("POST"))
        except Exception as exc:  # noqa: BLE001
            if _status(exc) == 404:
                raise NotFound(group_id) from exc
            raise

    async def meeting_stop(self, group_id: str) -> dict[str, Any]:
        from dodaios.ui.web import society_routes

        try:
            return await society_routes.stop_group_meeting(group_id, self._request("POST"))
        except Exception as exc:  # noqa: BLE001
            if _status(exc) == 404:
                raise NotFound(group_id) from exc
            raise

    async def confirm_dangerous(self, action: str, detail: str) -> bool:
        """The app's confirmation path for a dangerous station command.

        A host that installs ``app.state.verse_confirm`` (an async
        ``(action, detail) -> bool``) decides. Without one, the person's own
        press at the Verse station (which asks before it sends) confirms.
        """
        confirm = getattr(self.app.state, "verse_confirm", None)
        if confirm is None:
            return True
        return bool(await confirm(action, detail))

    async def create_agent(self, fields: dict[str, Any]) -> str:
        from dodaios.ui.web import society_routes

        body = society_routes.CreateAgentBody(**fields)
        result = await society_routes.create_agent(body, self._request("POST"))
        agent = result.get("agent", result)
        return str(agent.get("agent_id", ""))

    async def ide_state(self) -> dict[str, Any]:
        from dodaios.ui.web import agentic_ide_routes

        return await asyncio.to_thread(agentic_ide_routes.get_state)

    async def ide_agents(self) -> list[dict[str, Any]]:
        from dodaios.ui.web import agentic_ide_routes

        body = await agentic_ide_routes.get_agents(quick=True)
        data = body.model_dump() if hasattr(body, "model_dump") else dict(body)
        return list(data.get("agents", []))

    # ------------------------------------------------------------------ launcher
    async def open_terminal(self, workspace_id: str | None, agent: str) -> tuple[str, str]:
        from dodaios.ui.web import agentic_ide_routes

        req = agentic_ide_routes.AddTerminalRequest(workspace_id=workspace_id, agent=agent)
        body = await agentic_ide_routes.add_terminal(req)
        term = body.get("terminal", {})
        state = body.get("state", {}) or {}
        ws = str(term.get("workspace_id") or workspace_id or state.get("active_id") or "")
        return ws, str(term.get("name") or term.get("key") or "")

    async def start_terminal(self, name: str, workspace_id: str) -> None:
        from dodaios.ui.web import agentic_ide_routes

        await agentic_ide_routes.terminal_start(name, workspace_id)

    async def prompt_terminal(self, name: str, text: str, workspace_id: str) -> bool | None:
        from dodaios.ui.web import agentic_ide_routes

        req = agentic_ide_routes.PromptRequest(prompt=text)
        body = await agentic_ide_routes.terminal_prompt(
            self._request("POST"), name, req, workspace_id
        )
        submitted = body.get("submitted") if isinstance(body, dict) else None
        return submitted if isinstance(submitted, bool) else None

    # ------------------------------------------------------------------ companion
    async def active_pet(self) -> dict[str, Any]:
        cfg = getattr(self.app.state, "config", None)
        pet = getattr(cfg, "pet", None)
        ui = getattr(cfg, "ui", None)
        pet_id = str(
            getattr(ui, "pet_id", "") or getattr(pet, "pet_id", "") or getattr(pet, "id", "") or ""
        )
        service = getattr(self.app.state, "progression", None)
        if not pet_id and service is not None:
            try:
                pet_id = str(service.current_pet() or "")
            except Exception:  # noqa: BLE001
                pet_id = ""
        style = str(getattr(ui, "overlay_style", "") or "default")
        look = str(getattr(pet, "look", "") or pet_id or "")
        return {"pet_id": pet_id or "drone", "look": look or "drone", "style": style}

    # ------------------------------------------------------------------ screens
    def _registry(self) -> Any:
        from dodaios.agentic_ide.session import get_registry

        return get_registry()

    async def attach_screen(
        self, pane_id: str, on_output: OutputHandler, on_exit: ExitHandler
    ) -> tuple[int, int] | None:
        """Attach as a non-claiming viewer; the replay seeds the mirror. Returns the PTY size."""
        workspace_id, key = split_pane_id(pane_id)
        registry = self._registry()

        async def on_replay(text: str, repaint: bool = False) -> None:
            await on_output(text)

        try:
            await registry.attach(
                key,
                80,
                24,
                on_output,
                on_exit,
                workspace_id=workspace_id,
                on_replay=on_replay,
                claim_owner=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise NotFound(pane_id) from exc
        geometry = registry.pty_geometry(key, workspace_id)
        return (int(geometry[0]), int(geometry[1])) if geometry else None

    def detach_screen(self, pane_id: str, on_output: OutputHandler) -> None:
        try:
            workspace_id, key = split_pane_id(pane_id)
            self._registry().detach(key, workspace_id, viewer=on_output)
        except Exception:  # noqa: BLE001 - detaching a gone pane is a no-op
            log.debug("verse: detach of %s failed", pane_id, exc_info=True)

    def plain_screen(self, pane_id: str) -> dict[str, Any] | None:
        """The plain ``ScreenBuffer`` rows of one pane (the fallback of 5.1)."""
        from dodaios.agentic_ide import screen_feed

        try:
            refs = screen_feed.parse_pane_refs([pane_id])
            shots = screen_feed.collect_screens(self._registry(), refs)
        except Exception:  # noqa: BLE001
            return None
        return shots[0] if shots else None
