"""17.13 (on-demand download): the install routes and job against a fake installer.

The Verse is never part of the app install (README Delivery). With no Verse
on disk the host says ``not_installed``; ``POST /api/verse/install`` downloads
it through WP22's ``dodaios.verse_host.install`` (faked here),
``GET /api/verse/install/progress`` reports size and progress, ``DELETE``
cancels a running download or removes the installed Verse.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from dodaios.ui.web import verse_routes
from dodaios.verse_host import install_port
from dodaios.verse_host.install_port import (
    InstallBusy,
    InstallError,
    InstallJob,
    Manifest,
    SimulatedInstaller,
    UnavailableInstaller,
    VerseInstaller,
    load_installer,
)
from tests.unit.verse_host._support import make_host


class FakeInstaller:
    """Implements :class:`VerseInstaller` exactly; the test steps the download."""

    def __init__(self, build_dir: Path, *, size: int = 1000) -> None:
        self.build_dir = build_dir
        self.size = size
        self.published = True
        self.partial = 0
        self.gate = asyncio.Event()
        self.reject: str | None = None
        self.uninstalls = 0

    @property
    def exe(self) -> Path:
        return self.build_dir / "Verse.exe"

    async def manifest(self) -> Manifest | None:
        return Manifest("5.0.0", self.size, self.size * 2) if self.published else None

    def installed_version(self) -> str | None:
        return "5.0.0" if self.exe.is_file() else None

    async def install(self, progress) -> None:
        # Resume from the partial file of an earlier, cancelled run.
        while self.partial < self.size:
            progress("downloading", self.partial, self.size)
            await self.gate.wait()
            self.gate.clear()
            self.partial = min(self.size, self.partial + self.size // 4)
        progress("verifying", self.size, self.size)
        if self.reject:
            self.partial = 0
            raise InstallError(self.reject)
        progress("installing", self.size, self.size)
        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.exe.write_bytes(b"MZ")

    async def uninstall(self) -> None:
        self.uninstalls += 1
        if self.exe.is_file():
            self.exe.unlink()
        self.partial = 0


@pytest.fixture
def gpu_ok(monkeypatch):
    monkeypatch.setenv("DODAIOS_VERSE_PROBE", "pass")
    monkeypatch.delenv("DODAIOS_VERSE_FAKE_INSTALL", raising=False)


@pytest.fixture
def setup(tmp_path: Path, monkeypatch, gpu_ok):
    fake = FakeInstaller(tmp_path / "verse" / "build")
    from dodaios.verse_host import probe

    monkeypatch.setattr(probe, "candidate_executables", lambda: [fake.exe])
    host, backend = make_host(tmp_path, installer=fake)
    app = FastAPI()
    app.include_router(verse_routes.router)
    app.state.verse_host = host
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
    return host, backend, fake, client


async def _until(predicate, limit: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def test_fake_and_shipped_doubles_implement_the_interface(tmp_path: Path) -> None:
    for obj in (FakeInstaller(tmp_path), UnavailableInstaller(), SimulatedInstaller()):
        assert isinstance(obj, VerseInstaller)


def test_loader_falls_back_until_wp22_lands(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DODAIOS_VERSE_FAKE_INSTALL", raising=False)

    def missing(name: str):
        raise ImportError(name)

    monkeypatch.setattr(install_port.importlib, "import_module", missing)
    assert isinstance(load_installer(tmp_path), UnavailableInstaller)
    monkeypatch.setenv("DODAIOS_VERSE_FAKE_INSTALL", "1")
    assert isinstance(load_installer(tmp_path), SimulatedInstaller)


def test_loader_uses_the_install_package(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DODAIOS_VERSE_FAKE_INSTALL", raising=False)
    fake = FakeInstaller(tmp_path)
    seen: list[Path] = []

    class Module:
        @staticmethod
        def get_installer(data_dir: Path):
            seen.append(data_dir)
            return fake

    monkeypatch.setattr(install_port.importlib, "import_module", lambda name: Module)
    assert load_installer(tmp_path) is fake
    assert seen == [tmp_path]


async def test_fresh_install_is_not_installed_and_shows_the_size(setup) -> None:
    host, _, fake, client = setup
    async with client:
        status = (await client.get("/api/verse/status")).json()
        assert status["status"] == "not_installed"
        progress = (await client.get("/api/verse/install/progress")).json()
    assert progress["state"] == "idle"
    assert progress["download_bytes"] == fake.size
    assert progress["install_bytes"] == fake.size * 2
    assert progress["version"] == "5.0.0"
    assert progress["installed_version"] is None


async def test_download_installs_and_status_becomes_ready(setup) -> None:
    from dodaios.core.events import VerseStatusChanged

    host, backend, fake, client = setup
    async with client:
        started = (await client.post("/api/verse/install")).json()
        assert started["state"] == "downloading"
        # A second press joins the running download (single flight).
        again = (await client.post("/api/verse/install")).json()
        assert again["state"] == "downloading"
        for _ in range(4):
            fake.gate.set()
            await asyncio.sleep(0.02)
        await _until(lambda: not host.install.running)
        progress = (await client.get("/api/verse/install/progress")).json()
        status = (await client.get("/api/verse/status")).json()
    assert progress["state"] == "installed"
    assert progress["done_bytes"] == progress["total_bytes"] == fake.size
    assert progress["installed_version"] == "5.0.0"
    assert status["status"] == "stopped"
    changes = [e for e in backend.bus.published if isinstance(e, VerseStatusChanged)]
    assert changes and changes[-1].status == "stopped"


async def test_cancel_then_resume_keeps_the_partial_download(setup) -> None:
    host, _, fake, client = setup
    async with client:
        await client.post("/api/verse/install")
        fake.gate.set()
        await _until(lambda: fake.partial == fake.size // 4)
        await _until(lambda: host.install._progress.done_bytes == fake.size // 4)
        mid = (await client.get("/api/verse/install/progress")).json()
        assert mid["state"] == "downloading" and mid["done_bytes"] == fake.size // 4
        cancelled = (await client.delete("/api/verse/install")).json()
        assert cancelled["cancelled"] is True and cancelled["removed"] is False
        assert cancelled["state"] == "cancelled"
        assert fake.uninstalls == 0
        await client.post("/api/verse/install")
        await _until(lambda: host.install._progress.done_bytes == fake.size // 4)
        for _ in range(3):
            fake.gate.set()
            await asyncio.sleep(0.02)
        await _until(lambda: not host.install.running)
        status = (await client.get("/api/verse/status")).json()
    assert host.install._progress.state == "installed"
    assert status["status"] == "stopped"


async def test_tampered_package_is_rejected(setup) -> None:
    host, _, fake, client = setup
    fake.reject = "The Verse package failed its signature check."
    async with client:
        await client.post("/api/verse/install")
        for _ in range(4):
            fake.gate.set()
            await asyncio.sleep(0.02)
        await _until(lambda: not host.install.running)
        progress = (await client.get("/api/verse/install/progress")).json()
        status = (await client.get("/api/verse/status")).json()
    assert progress["state"] == "failed"
    assert progress["error"] == fake.reject
    assert status["status"] == "not_installed"


async def test_remove_stops_the_verse_and_returns_to_not_installed(setup) -> None:
    host, _, fake, client = setup
    fake.build_dir.mkdir(parents=True)
    fake.exe.write_bytes(b"MZ")
    host.capability = None
    stops: list[str] = []

    async def stop(reason: str = "app_quit") -> None:
        stops.append(reason)

    class Alive:
        def alive(self) -> bool:
            return not stops

    host.supervisor.stop = stop  # type: ignore[method-assign]
    host.supervisor.process = Alive()  # type: ignore[assignment]
    async with client:
        before = (await client.get("/api/verse/install/progress")).json()
        assert before["installed_version"] == "5.0.0"
        removed = (await client.delete("/api/verse/install")).json()
        status = (await client.get("/api/verse/status")).json()
    assert stops == ["update"]
    assert removed["removed"] is True and removed["installed_version"] is None
    assert fake.uninstalls == 1 and not fake.exe.exists()
    assert status["status"] == "not_installed"


async def test_unpublished_package_says_unavailable(setup) -> None:
    host, _, fake, client = setup
    fake.published = False
    async with client:
        progress = (await client.get("/api/verse/install/progress?refresh=true")).json()
        started = (await client.post("/api/verse/install")).json()
    assert progress["state"] == "unavailable" and progress["download_bytes"] is None
    assert started["state"] == "unavailable" and started["error"]
    assert not host.install.running


async def test_unsupported_gpu_cannot_download(setup, monkeypatch) -> None:
    host, _, _, client = setup
    monkeypatch.setenv("DODAIOS_VERSE_PROBE", "fail")
    host.check(refresh=True)
    async with client:
        res = await client.post("/api/verse/install")
    assert res.status_code == 409
    assert not host.install.running


async def test_job_without_host_reports_each_phase(tmp_path: Path) -> None:
    fake = FakeInstaller(tmp_path / "build", size=8)
    changed: list[str] = []

    async def on_change() -> None:
        changed.append(fake.installed_version() or "none")

    job = InstallJob(fake, on_change=on_change)
    phases: list[str] = []
    original = job._report

    def spy(phase, done, total):
        phases.append(phase)
        original(phase, done, total)

    job._report = spy  # type: ignore[method-assign]
    await job.start()
    while job.running:
        fake.gate.set()
        await asyncio.sleep(0.01)
    assert phases[0] == "downloading" and phases[-2:] == ["verifying", "installing"]
    assert changed == ["5.0.0"]
    fake.partial = 0
    await job.start()
    with pytest.raises(InstallBusy):
        await job.remove()
    assert await job.cancel() is True
    assert await job.cancel() is False
    assert (await job.remove())["installed_version"] is None
    assert changed[-1] == "none"


def test_switches_are_read_under_the_adopted_spelling(tmp_path: Path, monkeypatch) -> None:
    """Importing ``dodaios`` renames DODAIOS_* to JARVIS_*; the host must still see them."""
    from dodaios.verse_host.env import getenv
    from dodaios.verse_host.relays.commands import qa_enabled

    for name in ("DODAIOS_VERSE_FAKE_INSTALL", "DODAIOS_VERSE_QA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_VERSE_FAKE_INSTALL", "1")
    monkeypatch.setenv("JARVIS_VERSE_QA", "1")
    assert getenv("DODAIOS_VERSE_FAKE_INSTALL") == "1"
    assert isinstance(load_installer(tmp_path), SimulatedInstaller)
    assert qa_enabled()
    monkeypatch.setenv("DODAIOS_VERSE_QA", "0")
    assert not qa_enabled()
