"""Typing-only view of the host class for the mixins in this package.

The mixins read attributes the host `__init__` sets and call methods their
sibling mixins define. This class declares them so the type checker sees them.
It is imported under `TYPE_CHECKING` only; at run time the mixins derive from
`object` and nothing here exists.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.applications import FastAPI
from starlette.websockets import WebSocket

from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.missions.tool_approvals import MissionToolApprovalCoordinator
from dodaios.terminal.pty_manager import PtyManager
from dodaios.ui.deferred_setup import DeferredSetup


class WebServerHostState:
    """Attributes and cross-mixin methods of the host, typed for checking only."""

    _bio_scheduler: Any | None
    _board_aggregator: Any | None
    _board_evaluator: Any | None
    _client_send_locks: dict[str, asyncio.Lock]
    _clients: dict[str, WebSocket]
    _doc_registry: Any | None
    _feature_setup: DeferredSetup
    _mic_level_revision: int
    _mic_level_sessions: set[str]
    _mission_tool_approvals: MissionToolApprovalCoordinator
    _pending_reloads: list[tuple[str, Any]]
    _plugin_registry: Any | None
    _pty: PtyManager
    _pty_input_buffers: dict[str, str]
    _pty_shell_ids: dict[str, str]
    _refresh_registry_tasks: set[asyncio.Task[Any]]
    _skill_registry: Any | None
    _voice_ready: bool
    app: FastAPI
    bus: EventBus
    cfg: JarvisConfig

    def _build_agent_chat_service(self) -> Any:
        raise NotImplementedError

    def _build_society_runtime(self) -> Any:
        raise NotImplementedError

    async def _forward_delegation_to_chat(self, event: Any) -> None:
        raise NotImplementedError

    async def _init_channel_stack(self) -> None:
        raise NotImplementedError

    async def _init_flight_recorder(self) -> None:
        raise NotImplementedError

    async def _init_mission_stack(self) -> None:
        raise NotImplementedError

    async def _init_screenshot_retention(self) -> None:
        raise NotImplementedError

    def _init_session_stack(self) -> None:
        raise NotImplementedError

    async def _init_task_stack(self) -> None:
        raise NotImplementedError

    def _register_static_or_spa(self, app: FastAPI) -> None:
        raise NotImplementedError

    def _resolve_sessions_db_path(self) -> Path:
        raise NotImplementedError

    def _schedule_anyio_pool_warm(self) -> None:
        raise NotImplementedError

    def _schedule_appshot_shortcut(self) -> None:
        raise NotImplementedError

    def _schedule_credential_migration(self) -> None:
        raise NotImplementedError

    def _schedule_distribution_check(self) -> None:
        raise NotImplementedError

    def _schedule_local_models_autostart(self) -> None:
        raise NotImplementedError

    def _schedule_marketplace_refresh_scheduler(self) -> None:
        raise NotImplementedError

    def _schedule_realtime_transport_warm(self) -> None:
        raise NotImplementedError

    def _schedule_registry_bootstraps(self) -> None:
        raise NotImplementedError

    def _start_local_models_health_monitor(self) -> None:
        raise NotImplementedError

    def _start_main_follower(self) -> None:
        raise NotImplementedError

    def _start_microphone_rescue(self) -> None:
        raise NotImplementedError

    async def _stop_local_models_autostart(self) -> None:
        raise NotImplementedError

    async def _stop_local_models_health_monitor(self) -> None:
        raise NotImplementedError

    async def _stop_marketplace_refresh_scheduler(self) -> None:
        raise NotImplementedError

    def _stop_mic_level_bridge(self) -> None:
        raise NotImplementedError

    async def _stop_microphone_rescue(self) -> None:
        raise NotImplementedError

    async def _stop_registry_bootstraps(self) -> bool:
        raise NotImplementedError

    async def _voice_ready_watchdog(self, deadline_s: float=...) -> None:
        raise NotImplementedError

    async def prepare_app(self) -> None:
        raise NotImplementedError
