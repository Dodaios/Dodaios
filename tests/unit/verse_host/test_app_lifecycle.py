"""App start/stop of the verse host, the bridge port, and the probe off the event loop.

Contract 1 (Dev discovery: written at start with the flag on, deleted on
shutdown), contract 12 (``lifecycle.quit {reason: app_quit}`` on app quit).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import httpx
from fastapi import FastAPI

from dodaios.ui.web import verse_routes
from dodaios.verse_host import probe
from tests.unit.verse_host._support import close, connect, make_host
from tests.unit.verse_host.test_supervisor import Clock, _settle, _supervisor


def _app(host) -> FastAPI:
    app = FastAPI()
    app.include_router(verse_routes.router)
    app.state.verse_host = host
    return app


async def test_bridge_port_comes_from_the_bound_socket(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DODAIOS_VERSE_PROBE", "pass")
    host, _ = make_host(tmp_path)
    transport = httpx.ASGITransport(app=_app(host))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9123") as c:
        res = await c.get("/api/verse/status", headers={"Host": "evil.example:5555"})
    assert res.status_code == 200
    assert host.bridge_url() == "ws://127.0.0.1:9123/api/verse/bridge"


async def test_start_renews_dev_discovery_and_stop_removes_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DODAIOS_VERSE_DEV_BRIDGE", "1")
    host, _ = make_host(tmp_path)
    app = _app(host)
    await verse_routes.start_verse_host(app, 8811)
    path = tmp_path / "verse" / "bridge.json"
    assert path.is_file()
    assert '"url": "ws://127.0.0.1:8811/api/verse/bridge"' in path.read_text(encoding="utf-8")
    token = host.tokens._tokens["dev"]
    assert host.tokens.check(token)
    await verse_routes.stop_verse_host(app)
    assert not path.exists()
    assert not host.tokens.check(token)


async def test_start_without_the_flag_creates_no_host(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DODAIOS_VERSE_DEV_BRIDGE", "0")
    app = FastAPI()
    await verse_routes.start_verse_host(app, 8811)
    assert getattr(app.state, "verse_host", None) is None
    await verse_routes.stop_verse_host(app)  # nothing to stop


async def test_app_quit_asks_verse_to_quit(tmp_path: Path) -> None:
    clock, spawned = Clock(), []
    sup = _supervisor(tmp_path, clock, spawned)
    host, _ = make_host(tmp_path, supervisor=sup)
    sup._request_quit = host._request_quit
    await sup.ensure_running()
    t, task = await connect(host)
    await verse_routes.stop_verse_host(_app(host))
    await _settle()
    quits = t.of_type("lifecycle.quit")
    assert [q["data"]["reason"] for q in quits] == ["app_quit"]
    assert spawned[0].killed  # it did not exit before the deadline, so it was ended by PID
    assert sup.state.status == "stopped" and sup.state.crashes == []
    await close(t, task)


def test_a_failed_probe_is_retried_not_final(monkeypatch) -> None:
    monkeypatch.delenv("DODAIOS_VERSE_PROBE", raising=False)
    calls = {"n": 0}

    def timeout(*args, **kwargs):
        calls["n"] += 1
        raise subprocess.TimeoutExpired("probe", probe.PROBE_TIMEOUT_S)

    monkeypatch.setattr(probe, "_cache", None)
    monkeypatch.setattr(probe.subprocess, "run", timeout)
    first = probe.probe_gpu()
    assert not first.ok and first.failed
    assert probe.probe_gpu() is first and calls["n"] == 1  # cached briefly
    monkeypatch.setattr(probe, "_cache_at", time.monotonic() - probe.RETRY_FAILED_S - 1)
    probe.probe_gpu()
    assert calls["n"] == 2


async def test_install_is_allowed_while_the_probe_has_no_verdict(tmp_path: Path) -> None:
    host, _ = make_host(tmp_path)
    host.capability = probe.Capability(
        "unsupported", None, probe.GpuReport(False, reason="probe failed", failed=True), time.time()
    )
    transport = httpx.ASGITransport(app=_app(host))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
        res = await c.post("/api/verse/install")
    assert res.status_code != 409


async def test_async_paths_probe_in_a_thread(tmp_path: Path, monkeypatch) -> None:
    import threading

    host, _ = make_host(tmp_path)
    seen: list[bool] = []

    def check(*, refresh: bool = False) -> probe.Capability:
        seen.append(threading.current_thread() is threading.main_thread())
        return probe.Capability("not_installed", None, probe.GpuReport(True), time.time())

    monkeypatch.setattr(probe, "check", check)
    host.capability = None
    await host.acheck()
    assert seen == [False]
