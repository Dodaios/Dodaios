"""One failing module does not take the app down; it is named in the health reads.

Plugins (entry points) and optional boot services are exercised with a module
that is broken on purpose. Each test asserts the same three things: the rest of
the group or the boot sequence still works, a fallback is chosen where one
exists, and the failure shows in ``dodaios.core.module_health`` (the source of
``/api/health`` ``degraded`` and ``/api/diagnostics/modules``).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dodaios.core import module_health
from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig


class FakeEntryPoint:
    """The part of ``importlib.metadata.EntryPoint`` the loaders read."""

    def __init__(self, name: str, target: Any = None, *, import_error: Exception | None = None):
        self.name = name
        self.group = "dodaios.fake"
        self.value = f"fake.{name}:Plugin"
        self._target = target
        self._import_error = import_error

    def load(self) -> Any:
        if self._import_error is not None:
            raise self._import_error
        return self._target


class GoodPlugin:
    name = "good"

    def __init__(self, **_: Any) -> None:
        pass


class CtorRaises:
    def __init__(self, **_: Any) -> None:
        raise RuntimeError("constructor exploded")


@pytest.fixture(autouse=True)
def _fresh_health():
    module_health.reset()
    yield
    module_health.reset()


def _eps() -> list[FakeEntryPoint]:
    return [
        FakeEntryPoint("broken-import", import_error=RuntimeError("import exploded")),
        FakeEntryPoint("good", GoodPlugin),
        FakeEntryPoint("broken-syntax", import_error=SyntaxError("bad plugin source")),
    ]


# -- brain ------------------------------------------------------------------


def test_brain_plugin_with_failing_import_leaves_the_others(monkeypatch) -> None:
    from dodaios.brain import provider_registry

    monkeypatch.setattr(provider_registry, "entry_points", lambda group: _eps())
    reg = provider_registry.BrainProviderRegistry()
    monkeypatch.setattr("dodaios.brain.usage_meter.meter_brain", lambda brain, name: brain)

    assert reg.available() == ["good"]
    assert set(reg.failed()) == {"broken-import", "broken-syntax"}
    assert isinstance(reg.instantiate("good"), GoodPlugin)
    degraded = module_health.snapshot()
    assert "plugin:brain:broken-import" in degraded
    assert "import exploded" in degraded["plugin:brain:broken-import"]["reason"]


def test_brain_plugin_with_failing_constructor_raises_only_for_that_plugin(monkeypatch) -> None:
    from dodaios.brain import provider_registry

    monkeypatch.setattr(
        provider_registry,
        "entry_points",
        lambda group: [FakeEntryPoint("ctor", CtorRaises), FakeEntryPoint("good", GoodPlugin)],
    )
    monkeypatch.setattr("dodaios.brain.usage_meter.meter_brain", lambda brain, name: brain)
    reg = provider_registry.BrainProviderRegistry()

    with pytest.raises(RuntimeError, match="constructor exploded"):
        reg.instantiate("ctor")
    assert isinstance(reg.instantiate("good"), GoodPlugin)


# -- harness ----------------------------------------------------------------


class _Harness:
    async def health(self) -> bool:
        raise RuntimeError("runtime failure")


class _OkHarness:
    async def health(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_harness_plugin_failures_leave_the_other_harnesses(monkeypatch) -> None:
    from dodaios.harness import manager as harness_manager

    monkeypatch.setattr(
        harness_manager,
        "entry_points",
        lambda group: [
            FakeEntryPoint("broken-import", import_error=ImportError("no module named x")),
            FakeEntryPoint("raises-at-runtime", _Harness),
            FakeEntryPoint("ok", _OkHarness),
        ],
    )
    manager = harness_manager.HarnessManager(bus=EventBus())

    assert manager.available() == ["ok", "raises-at-runtime"]
    assert "broken-import" in manager.failed()
    assert "plugin:harness:broken-import" in module_health.snapshot()
    # A method raising at runtime reads as "not healthy", never as an exception.
    assert await manager.health("raises-at-runtime") is False
    assert await manager.health("ok") is True


# -- channel ----------------------------------------------------------------


def test_channel_plugin_with_failing_import_leaves_the_others(monkeypatch) -> None:
    from dodaios.channels import manager as channel_manager

    monkeypatch.setattr(channel_manager, "entry_points", lambda group: _eps())
    manager = channel_manager.ChannelManager(SimpleNamespace(bus=EventBus()))  # type: ignore[arg-type]

    assert manager.available() == ["good"]
    assert set(manager.failed()) == {"broken-import", "broken-syntax"}
    assert "plugin:channel:broken-import" in module_health.snapshot()


# -- stt --------------------------------------------------------------------


def test_stt_plugin_with_failing_import_falls_back_to_local(monkeypatch) -> None:
    from dodaios.core import entry_points as eps_module
    from dodaios.plugins import stt

    monkeypatch.setattr(eps_module, "entry_points_for", lambda group: _eps())
    sentinel = object()
    monkeypatch.setattr(stt, "_resolve_effective_stt", lambda name: ("broken-import", None))
    monkeypatch.setattr(stt, "_build_local_fallback", lambda cfg, language: sentinel)

    assert stt._load_provider_class("broken-import") is None
    assert stt._load_provider_class("broken-syntax") is None
    assert stt._load_provider_class("good") is GoodPlugin
    assert "plugin:stt:broken-import" in module_health.snapshot()
    cfg = SimpleNamespace(provider="broken-import", language="auto", bias_prompt="")
    assert stt.build_stt_from_config(cfg, dictionary_bias=False) is sentinel


def test_stt_plugin_with_failing_constructor_falls_back_to_local(monkeypatch) -> None:
    from dodaios.core import entry_points as eps_module
    from dodaios.plugins import stt

    monkeypatch.setattr(
        eps_module, "entry_points_for", lambda group: [FakeEntryPoint("ctor", CtorRaises)]
    )
    sentinel = object()
    monkeypatch.setattr(stt, "_resolve_effective_stt", lambda name: ("ctor", None))
    monkeypatch.setattr(stt, "_stt_has_credential", lambda name, kwargs: True)
    monkeypatch.setattr(stt, "_build_local_fallback", lambda cfg, language: sentinel)
    monkeypatch.setattr(stt, "provider_runs_on_device", lambda name: False)
    monkeypatch.setattr(stt, "resolve_stt_model", lambda cfg, name: "")

    cfg = SimpleNamespace(provider="ctor", language="auto", bias_prompt="")
    assert stt.build_stt_from_config(cfg, dictionary_bias=False) is sentinel


# -- realtime / registry.load -----------------------------------------------


def test_registry_load_reports_a_plugin_whose_import_raises(monkeypatch) -> None:
    from dodaios.core import registry

    monkeypatch.setattr(registry, "entry_points_for", lambda group: _eps())

    with pytest.raises(registry.PluginLoadError):
        registry.load("jarvis.realtime", "broken-import")
    with pytest.raises(registry.PluginLoadError):
        registry.load("jarvis.realtime", "broken-syntax")
    assert registry.load("jarvis.realtime", "good") is GoodPlugin
    assert registry.list_plugins("jarvis.realtime") == ["broken-import", "broken-syntax", "good"]
    assert "plugin:realtime:broken-import" in module_health.snapshot()


def test_realtime_candidates_skip_a_plugin_whose_constructor_raises(monkeypatch) -> None:
    from dodaios.realtime import factory

    class _Broken:
        supports_realtime = True
        credential_candidates = ("k",)

        def __init__(self, **_: Any) -> None:
            raise RuntimeError("realtime ctor exploded")

    monkeypatch.setattr(factory, "_configured_provider_ids", lambda cfg: ["bad", "none"])
    monkeypatch.setattr(factory, "_explicit_provider_ids", lambda cfg: [])
    monkeypatch.setattr(factory, "get_secret_any", lambda names: "key")
    monkeypatch.setattr(
        factory,
        "load",
        lambda group, name, protocol=None: _Broken if name == "bad" else None,
    )

    assert factory._identified_provider_candidates(JarvisConfig()) == []
    assert "plugin:realtime:bad" in module_health.snapshot()


# -- tool -------------------------------------------------------------------


def test_cli_tool_loader_skips_a_tool_whose_import_raises(monkeypatch) -> None:
    from dodaios.brain import launcher
    from dodaios.core import entry_points as eps_module

    class _Tool:
        name = "good-tool"

        def __init__(self) -> None:
            pass

    monkeypatch.setattr(
        eps_module,
        "entry_points",
        lambda group=None: [FakeEntryPoint("broken", import_error=RuntimeError("x")),
                            FakeEntryPoint("good-tool", _Tool)],
    )

    tools = launcher._load_tools()
    assert "good-tool" in tools and "broken" not in tools


# -- module health surface ---------------------------------------------------


def test_health_and_diagnostics_name_the_failed_modules() -> None:
    from dodaios.ui.web.server import WebServer

    cfg = JarvisConfig()
    cfg.ui.dev_mode = True
    server = WebServer(cfg, bus=EventBus())
    module_health.report_failure("plugin:brain:broken", RuntimeError("boom"))
    with TestClient(server.app) as client:
        health = client.get("/api/health").json()
        detail = client.get("/api/diagnostics/modules").json()

    assert health["ok"] is True
    assert health["degraded"] == ["plugin:brain:broken"]
    assert detail["degraded"]["plugin:brain:broken"]["reason"] == "RuntimeError: boom"


# -- boot services ----------------------------------------------------------


@pytest.mark.asyncio
async def test_failing_boot_services_leave_the_backend_serving(monkeypatch, tmp_path) -> None:
    """Representative optional services each raise while starting."""
    from dodaios.memory.learning import loop as learning
    from dodaios.society.browser import install
    from dodaios.ui.web.server import WebServer

    monkeypatch.setattr(install, "start_install", lambda *args: None)
    monkeypatch.setattr(mars_routes, "schedule_mars_resume", lambda *args: None, raising=False)

    def learning_raises(*_args: Any) -> None:
        raise RuntimeError("learning exploded")

    monkeypatch.setattr(learning, "start_learning", learning_raises)
    cfg = JarvisConfig()
    cfg.memory.data_dir = str(tmp_path)
    server = WebServer(cfg, bus=EventBus())

    async def noop_async() -> None:
        return None

    async def async_raises() -> None:
        raise RuntimeError("service exploded")

    def sync_raises() -> None:
        raise RuntimeError("service exploded")

    for name in ("_init_screenshot_retention", "_init_channel_stack"):
        monkeypatch.setattr(server, name, noop_async)
    for name in ("_init_mission_stack", "_init_flight_recorder", "_init_task_stack"):
        monkeypatch.setattr(server, name, async_raises)
    monkeypatch.setattr(server, "_init_session_stack", sync_raises)
    for name in (
        "_schedule_anyio_pool_warm", "_schedule_registry_bootstraps",
        "_schedule_marketplace_refresh_scheduler", "_start_local_models_health_monitor",
        "_schedule_local_models_autostart", "_schedule_realtime_transport_warm",
        "_schedule_appshot_shortcut", "_schedule_credential_migration",
        "_schedule_distribution_check",
    ):
        monkeypatch.setattr(server, name, lambda **kwargs: None)
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

    with TestClient(server.app) as client:
        assert client.get("/api/health").status_code == 200
        degraded = client.get("/api/diagnostics/modules").json()["degraded"]
    for module in ("missions", "flight-recorder", "tasks", "sessions", "learning-loop"):
        assert module in degraded, module
        assert "exploded" in degraded[module]["reason"]
