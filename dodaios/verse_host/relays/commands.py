"""Station commands (BW9, BW12; contract 11 and 14).

Open commands publish ``VerseOpenRequested`` (the web UI opens the view) and
``ShowWindowRequested`` (the desktop process raises the app window).
``agent.create`` runs the same code as ``POST /api/society/agents``.
``launcher.*`` share :mod:`dodaios.agentic_ide.launch_sequence` with the web
launcher (single flight, ``busy``, ``launcher.cancel``). ``qa.exec`` answers
``unavailable`` unless the backend runs with ``DODAIOS_VERSE_QA=1``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from dodaios.agentic_ide.launch_sequence import LaunchBusy, LaunchSequence

from .. import protocol as P
from ..env import getenv
from ..ports import NotFound, split_pane_id
from .base import RelayBase

log = logging.getLogger(__name__)

QaHandler = Callable[[list[str]], Awaitable[Any]]


def qa_enabled() -> bool:
    return getenv("DODAIOS_VERSE_QA").strip() == "1"


class CommandsRelay(RelayBase):
    topics = ()

    def __init__(
        self,
        session: Any,
        backend: Any,
        *,
        launcher: LaunchSequence,
        qa: dict[str, QaHandler],
        on_open: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(session, backend)
        self.launcher = launcher
        self.qa = qa
        self.on_open = on_open

    async def start(self) -> None:
        hub = self.session.hub
        for name, handler in (
            ("pane.open", self._pane_open),
            ("ide.focus_terminal", self._focus_terminal),
            ("agent.open", self._agent_open),
            ("agents.open_list", self._agents_list),
            ("group.open", self._group_open),
            ("simulator.open", self._simulator_open),
            ("ide.open", self._ide_open),
            ("agent.create", self._agent_create),
            ("launcher.options", self._launcher_options),
            ("launcher.start", self._launcher_start),
            ("launcher.cancel", self._launcher_cancel),
            ("qa.exec", self._qa_exec),
        ):
            hub.command(name, handler)

    # ------------------------------------------------------------------ open
    async def _publish_open(self, **fields: Any) -> None:
        from dodaios.core.events import ShowWindowRequested, VerseOpenRequested

        bus = self.backend.bus
        if bus is None:
            raise P.BridgeError("unavailable", "The app is not listening.")
        await bus.publish(VerseOpenRequested(source_layer="verse_host", **fields))
        await bus.publish(ShowWindowRequested(source_layer="verse_host", source="verse"))
        if self.on_open is not None:
            await self.on_open()

    async def _known_pane(self, pane_id: Any) -> tuple[str, str]:
        if not isinstance(pane_id, str):
            raise P.BridgeError("bad_request", "pane_id is required.")
        try:
            workspace_id, key = split_pane_id(pane_id)
        except NotFound as exc:
            raise P.BridgeError("bad_request", "pane_id is <workspace_id>:<key>.") from exc
        for row in await self.backend.list_panes():
            if row.get("workspace_id") == workspace_id and key in (row.get("key"), row.get("name")):
                return workspace_id, str(row.get("name") or key)
        raise P.BridgeError("not_found", "Pane is gone.")

    async def _pane_open(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        opened = msg.data.get("open")
        if opened not in (None, "changes"):
            raise P.BridgeError("bad_request", "open must be changes.")
        ws, name = await self._known_pane(msg.data.get("pane_id"))
        await self._publish_open(target="pane", workspace_id=ws, name=name, open=opened or "")
        return {}

    async def _focus_terminal(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        ws, name = await self._known_pane(msg.data.get("pane_id"))
        await self._publish_open(target="pane", workspace_id=ws, name=name, focus=True)
        return {}

    async def _agent_open(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        agent_id = msg.data.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise P.BridgeError("bad_request", "agent_id is required.")
        if not any(a.get("agent_id") == agent_id for a in await self.backend.list_agents()):
            raise P.BridgeError("not_found", "Agent is gone.")
        await self._publish_open(target="agent", agent_id=agent_id)
        return {}

    async def _agents_list(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        await self._publish_open(target="agents")
        return {}

    async def _group_open(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        group_id = msg.data.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            raise P.BridgeError("bad_request", "group_id is required.")
        groups = await self.backend.chat_groups()
        if not any((g.get("group_id") or g.get("id")) == group_id for g in groups):
            raise P.BridgeError("not_found", "Group is gone.")
        await self._publish_open(target="group", group_id=group_id)
        return {}

    async def _simulator_open(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        programme = msg.data.get("programme")
        if not isinstance(programme, str) or not programme:
            raise P.BridgeError("bad_request", "programme is required.")
        await self._publish_open(target="simulator", programme=programme)
        return {}

    async def _ide_open(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        await self._publish_open(target="ide")
        return {}

    # ------------------------------------------------------------------ create
    async def _agent_create(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        name, title = msg.data.get("name"), msg.data.get("title")
        if name is not None:
            if not isinstance(name, str) or not 1 <= len(name) <= 40:
                raise P.BridgeError("bad_request", "name must be 1 to 40 characters.")
            fields["name"] = name
        if title is not None:
            if not isinstance(title, str) or len(title) > 120:
                raise P.BridgeError("bad_request", "title must be a short string.")
            fields["title"] = title
        try:
            agent_id = await self.backend.create_agent(fields)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in (409, 422):
                raise P.BridgeError("conflict", str(getattr(exc, "detail", exc))) from exc
            if status == 503:
                raise P.BridgeError("unavailable", str(getattr(exc, "detail", exc))) from exc
            raise
        if not agent_id:
            raise P.BridgeError("internal", "The agent was not created.")
        return {"agent_id": agent_id}

    # ------------------------------------------------------------------ launcher
    async def _launcher_options(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        state = await self.backend.ide_state()
        active = state.get("active_id")
        workspaces = []
        for w in state.get("workspaces", []):
            wid = w.get("id") or w.get("workspace_id")
            if isinstance(wid, str) and wid:
                workspaces.append(
                    {
                        "workspace_id": wid,
                        "name": str(w.get("name") or w.get("folder") or wid),
                        "active": wid == active,
                    }
                )
        agents = []
        for a in await self.backend.ide_agents():
            name = a.get("name")
            if not isinstance(name, str) or not name or (a.get("kind") or "cli") == "shell":
                continue
            agents.append(
                {
                    "agent": name,
                    "display_name": str(a.get("display_name") or a.get("label") or name),
                    "available": bool(a.get("installed", True)),
                }
            )
        return {"workspaces": workspaces, "agents": agents}

    async def _launcher_start(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        data = msg.data
        workspace_id = data.get("workspace_id")
        agents = data.get("agents")
        brief = data.get("brief", "")
        if workspace_id is not None and (not isinstance(workspace_id, str) or not workspace_id):
            raise P.BridgeError("bad_request", "workspace_id must be a non-empty string.")
        if not isinstance(brief, str) or not isinstance(agents, list) or not agents:
            raise P.BridgeError("bad_request", "launcher.start needs agents and brief.")
        plan: list[tuple[str, int]] = []
        for item in agents:
            agent = item.get("agent") if isinstance(item, dict) else None
            count = item.get("count") if isinstance(item, dict) else None
            if not isinstance(agent, str) or not agent:
                raise P.BridgeError("bad_request", "every entry needs an agent.")
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
                raise P.BridgeError("bad_request", "count must be 1 to 8.")
            plan.append((agent, count))
        if self.launcher.busy:
            raise P.BridgeError("busy", "A launch batch is already running.")
        try:
            panes = await self.launcher.run(workspace_id, plan, brief)
        except LaunchBusy as exc:
            raise P.BridgeError("busy", str(exc)) from exc
        return {"panes": [{"pane_id": p.pane_id, "submitted": p.submitted} for p in panes]}

    async def _launcher_cancel(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        return {"stopped": self.launcher.cancel()}

    # ------------------------------------------------------------------ QA
    async def _qa_exec(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        if not qa_enabled():
            raise P.BridgeError("unavailable", "QA commands need DODAIOS_VERSE_QA=1.")
        command, args = msg.data.get("command"), msg.data.get("args", [])
        if not isinstance(command, str) or not command.startswith("Verse.QA."):
            raise P.BridgeError("bad_request", "command must be a Verse.QA.* command.")
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise P.BridgeError("bad_request", "args must be strings.")
        handler = self.qa.get(command)
        if handler is None:
            raise P.BridgeError("not_found", f"No backend QA command {command}.")
        return {"result": await handler(args)}
