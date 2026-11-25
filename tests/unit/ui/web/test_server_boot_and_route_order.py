"""Golden order of the web server: mounted routes and boot-service starts.

The server is assembled from several parts; moving code between them must not
change which route answers first or which boot service starts first. The route
list is recorded as it is mounted; the boot list is the ordered calls that
``start()`` makes to its init and schedule methods (recorded by fakes).
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.ui.web.server import WebServer

_BOOT_CALLS = (
    "prepare_app",
    "_init_mission_stack",
    "_init_screenshot_retention",
    "_init_flight_recorder",
    "_init_task_stack",
    "_init_session_stack",
    "_init_channel_stack",
    "_schedule_anyio_pool_warm",
    "_schedule_registry_bootstraps",
    "_schedule_marketplace_refresh_scheduler",
    "_start_local_models_health_monitor",
    "_start_main_follower",
    "_start_microphone_rescue",
    "_schedule_local_models_autostart",
    "_schedule_realtime_transport_warm",
    "_schedule_appshot_shortcut",
    "_schedule_credential_migration",
    "_schedule_distribution_check",
)

EXPECTED_BOOT_ORDER = [
    "prepare_app",
    "_schedule_anyio_pool_warm",
    "_init_mission_stack",
    "_init_screenshot_retention",
    "_init_flight_recorder",
    "_init_session_stack",
    "_init_task_stack",
    "_schedule_registry_bootstraps",
    "_schedule_marketplace_refresh_scheduler",
    "_start_local_models_health_monitor",
    "_start_main_follower",
    "_start_microphone_rescue",
    "_schedule_local_models_autostart",
    "_schedule_realtime_transport_warm",
    "_schedule_appshot_shortcut",
    "_schedule_credential_migration",
    "_schedule_distribution_check",
    "_init_channel_stack",
]

EXPECTED_ROUTE_COUNT = 131
EXPECTED_ROUTE_DIGEST = "e95fb951eda332eb997f0e351e8bdaecd055d08276dc95ffbb5b1599a97b098b"


def _mounted(server: WebServer) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for route in server.app.routes:
        if type(route).__name__ == "Mount":  # present only when a UI build exists
            continue
        methods = ",".join(sorted(getattr(route, "methods", None) or ())) or "-"
        out.append((methods, getattr(route, "path", getattr(route, "name", "?"))))
    return out


def test_routes_are_mounted_in_the_recorded_order() -> None:
    server = WebServer(JarvisConfig(), bus=EventBus())
    mounted = _mounted(server)
    digest = hashlib.sha256("\n".join(f"{m} {p}" for m, p in mounted).encode()).hexdigest()
    assert len(mounted) == EXPECTED_ROUTE_COUNT
    assert digest == EXPECTED_ROUTE_DIGEST
    # The SPA catch-all must stay behind every API route.
    assert mounted[-1][1].startswith("/{full_path")


@pytest.mark.asyncio
async def test_boot_services_start_in_the_recorded_order(monkeypatch, tmp_path) -> None:
    cfg = JarvisConfig()
    cfg.memory.data_dir = str(tmp_path)
    server = WebServer(cfg, bus=EventBus())
    calls: list[str] = []

    def recorder(name: str, *, is_async: bool):
        if is_async:

            async def arec(*_a, **_k):
                calls.append(name)

            return arec

        def rec(*_a, **_k):
            calls.append(name)

        return rec

    for name in _BOOT_CALLS:
        original = getattr(server, name)
        monkeypatch.setattr(
            server, name, recorder(name, is_async=asyncio.iscoroutinefunction(original))
        )
    for name in (
        "_skill_registry", "_doc_registry", "_cli_registry", "_plugin_registry",
        "_board_aggregator", "_board_evaluator", "_bio_scheduler",
    ):
        setattr(server, name, None)
    server._voice_ready = True
    server._pending_reloads.clear()

    await server.start(start_serving=False)
    await server._channel_stack_task
    await asyncio.sleep(0)

    assert calls == EXPECTED_BOOT_ORDER
