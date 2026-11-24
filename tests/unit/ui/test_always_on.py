"""Always reachable: the agent server registered with the OS through daemonkit.

The OS side is daemonkit's (tests/unit/daemonkit). These tests pin what
Dodaios decides: which command the service runs, who holds the lock, how a
desktop starts the server, and what the settings route does.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from daemonkit import Daemon, is_locked, read_record
from daemonkit.service import ServiceSpec, ServiceStatus
from dodaios.ui import always_on


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("JARVIS_INSTANCE", raising=False)
    monkeypatch.setattr(always_on, "_state_dir", lambda: tmp_path / "background")
    monkeypatch.setattr(always_on, "_claim", None)


class FakeManager:
    mechanism = "fake"

    def __init__(self, *, installed: bool = False, starts: bool = True, accepts: bool = True):
        self.installed = installed
        self.starts = starts
        self.accepts = accepts
        self.calls: list[str] = []
        self.specs: list[ServiceSpec] = []

    def available(self) -> tuple[bool, str]:
        return True, ""

    def install(self, spec: ServiceSpec, *, start_at: str = "login", start_now: bool = True):  # type: ignore[no-untyped-def]
        self.calls.append(f"install:{start_at}:{start_now}")
        self.specs.append(spec)
        self.installed = self.accepts
        return ServiceStatus(
            self.mechanism,
            supported=True,
            installed=self.accepts,
            starts_at=start_at if self.accepts else None,
            detail="" if self.accepts else "refused by the OS",
        )

    def uninstall(self, spec: ServiceSpec, *, stop: bool = True) -> ServiceStatus:
        self.calls.append(f"uninstall:{stop}")
        self.installed = False
        return ServiceStatus(self.mechanism, supported=True, installed=False)

    def status(self, spec: ServiceSpec) -> ServiceStatus:
        return ServiceStatus(self.mechanism, supported=True, installed=self.installed)

    def start(self, spec: ServiceSpec) -> bool:
        self.calls.append("start")
        return self.starts

    def stop(self, spec: ServiceSpec) -> bool:
        return True


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> FakeManager:
    fake = FakeManager()
    monkeypatch.setattr(Daemon, "service_manager", lambda self: fake)
    return fake


def _cfg(port: int = 51234, server_url: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        ui=SimpleNamespace(admin_api_port=port),
        background=SimpleNamespace(
            keep_agents_running=True, persistent_server=False, server_url=server_url
        ),
        autostart=SimpleNamespace(enabled=False, background_only=False),
    )


def test_the_service_runs_the_persistent_server_under_the_supervisor() -> None:
    daemon = always_on.agent_daemon(_cfg())
    argv = daemon.supervisor_argv(windowless=False)
    assert daemon.name == "dodaios-agent-server"
    assert argv[1:3] == ["-m", "daemonkit.supervise"]
    server = argv[argv.index("--") + 1 :]
    assert server[1:3] == ["-m", "dodaios.ui.web.launcher"]
    assert "--persistent-server" in server
    assert server[server.index("--port") + 1] == "51234"
    assert "--after-pid" not in server
    assert "PYTHONIOENCODING=utf-8" in argv


def test_a_frozen_build_reenters_its_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.core import frozen

    monkeypatch.setattr(frozen, "is_frozen", lambda: True)
    argv = always_on.agent_daemon(_cfg()).supervisor_argv()
    assert argv[:2] == [sys.executable, always_on.FROZEN_SUPERVISE_FLAG]
    server = argv[argv.index("--") + 1 :]
    assert server[1] == "--background-service" and "--persistent-server" in server


def test_a_dev_instance_gets_its_own_name_and_cannot_install(
    monkeypatch: pytest.MonkeyPatch, manager: FakeManager
) -> None:
    monkeypatch.setenv("JARVIS_INSTANCE", "dev")
    assert always_on.agent_daemon().name == "dodaios-agent-server-dev"
    with pytest.raises(ValueError, match="default app"):
        always_on.install(_cfg())
    assert manager.calls == []


def test_install_registers_and_reports(manager: FakeManager) -> None:
    result = always_on.install(_cfg(), start_at="boot")
    assert manager.calls == ["install:boot:True"]
    assert result["installed"] is True and result["starts_at"] == "boot"
    assert always_on.status(_cfg())["installed"] is True
    with pytest.raises(ValueError):
        always_on.install(_cfg(), start_at="sometimes")


def test_uninstall_leaves_a_running_server_alone(manager: FakeManager) -> None:
    always_on.install(_cfg())
    result = always_on.uninstall(_cfg())
    assert manager.calls[-1] == "uninstall:False"
    assert result["installed"] is False


def test_start_installed_service_only_when_installed(manager: FakeManager) -> None:
    assert always_on.start_installed_service() is False
    assert manager.calls == []
    manager.installed = True
    assert always_on.start_installed_service(port=1) is True
    assert manager.calls == ["start"]
    manager.starts = False
    assert always_on.start_installed_service() is False


def test_status_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Daemon) -> Any:
        raise RuntimeError("no service manager")

    monkeypatch.setattr(Daemon, "service_manager", boom)
    result = always_on.status()
    assert result["installed"] is False and "no service manager" in result["detail"]


def test_the_running_server_holds_the_lock_and_publishes_its_port(tmp_path: Path) -> None:
    always_on.claim_for_this_process(47999)
    daemon = always_on.agent_daemon()
    assert is_locked(daemon.paths.lock)
    record = read_record(daemon.paths.record)
    assert record is not None and record.ready and record.port == 47999
    always_on.claim_for_this_process(1)  # a second call keeps the first claim
    assert read_record(daemon.paths.record).port == 47999  # type: ignore[union-attr]
    always_on.release()
    assert not is_locked(daemon.paths.lock)
    assert not daemon.paths.record.exists()
    always_on.release()  # twice is fine


def test_a_second_server_stays_unsupervised_instead_of_failing() -> None:
    daemon = always_on.agent_daemon()
    with daemon.claim():
        always_on.claim_for_this_process(1)
        assert always_on._claim is None


def test_a_refused_persistent_boot_asks_the_supervisor_to_wait() -> None:
    from daemonkit import EXIT_ALREADY_RUNNING
    from dodaios.core import background_service as bg
    from dodaios.ui.web import launcher

    persistent = launcher._parse_args(["--persistent-server"])
    handoff = launcher._parse_args([bg.SERVICE_FLAG])
    assert launcher._service_refused_exit_code(persistent) == EXIT_ALREADY_RUNNING
    assert launcher._service_refused_exit_code(handoff) == 0


def test_the_frozen_entry_routes_the_supervisor_flag() -> None:
    main = Path(always_on.__file__).resolve().parents[1] / "__main__.py"
    text = main.read_text(encoding="utf-8")
    assert f'sys.argv[1] == "{always_on.FROZEN_SUPERVISE_FLAG}"' in text
    assert "from daemonkit.supervise import main" in text


# ---------------------------------------------------------------------------
# Settings route
# ---------------------------------------------------------------------------


def _client(cfg: SimpleNamespace):  # type: ignore[no-untyped-def]
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.ui.web import settings_routes

    app = FastAPI()
    app.include_router(settings_routes.router)
    app.state.config = cfg
    return TestClient(app)


def test_route_turns_it_on_and_makes_this_computer_the_server(
    monkeypatch: pytest.MonkeyPatch, manager: FakeManager
) -> None:
    from dodaios.core import config_writer

    writes: list[tuple[bool, str]] = []
    monkeypatch.setattr(
        config_writer,
        "set_agent_server",
        lambda *, persistent, server_url="": writes.append((persistent, server_url)),
    )
    cfg = _cfg()
    client = _client(cfg)
    assert client.get("/api/settings/background").json()["always_on"]["installed"] is False

    body = client.put("/api/settings/background", json={"always_on": True}).json()
    assert manager.calls == ["install:login:True"]
    assert writes == [(True, "")]
    assert cfg.background.persistent_server is True
    assert body["always_on"]["installed"] is True
    assert body["persistent_server"] is True

    body = client.put("/api/settings/background", json={"always_on": False}).json()
    assert manager.calls[-1] == "uninstall:False"
    assert body["always_on"]["installed"] is False
    assert writes == [(True, "")]  # client mode stays as it is


def test_route_refuses_while_a_remote_server_is_configured(manager: FakeManager) -> None:
    client = _client(_cfg(server_url="https://agents.example.com"))
    response = client.put("/api/settings/background", json={"always_on": True})
    assert response.status_code == 409
    assert manager.calls == []


def test_route_reports_an_os_refusal(
    monkeypatch: pytest.MonkeyPatch, manager: FakeManager
) -> None:
    from dodaios.core import config_writer

    monkeypatch.setattr(config_writer, "set_agent_server", lambda **_kw: None)
    manager.accepts = False
    response = _client(_cfg()).put("/api/settings/background", json={"always_on": True})
    assert response.status_code == 409
    assert "refused by the OS" in response.json()["detail"]


def test_an_integrated_window_holds_the_lock_so_a_supervisor_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dodaios.ui.web import launcher

    ports: list[int] = []
    monkeypatch.setattr(always_on, "claim_for_this_process", ports.append)
    launcher._claim_for_always_on(_cfg(port=47555))
    import threading

    for thread in threading.enumerate():
        if thread.name == "always-on-claim":
            thread.join(5)
    assert ports == [47555]
