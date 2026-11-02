"""The on-demand Verse download, as the host and its routes see it (README Delivery).

The Unreal Verse is never part of the installer, a ``git clone`` or an app
update. When the host status is ``not_installed`` the launcher card offers
"Download the Verse"; Settings offers "Remove the Verse". The work itself
(manifest, resumable download, signature and hash check, unpack, uninstall)
belongs to WP22's package ``dodaios.verse_host.install``. This module is the
seam between the two:

* :class:`VerseInstaller` is the interface the package implements. Its
  module exposes ``get_installer(data_dir: Path) -> VerseInstaller``; the
  build it installs lands in ``<data_dir>/verse/build`` so
  :func:`dodaios.verse_host.probe.candidate_executables` finds it.
* :class:`InstallJob` runs one download at a time (single flight), keeps the
  progress the card polls, cancels on request and refreshes the host status
  when the install finishes or the Verse is removed.
* Until the package lands, :func:`load_installer` returns
  :class:`UnavailableInstaller` (the card says the download is not published
  yet). ``DODAIOS_VERSE_FAKE_INSTALL=1`` selects :class:`SimulatedInstaller`
  for UI checks: it walks through the progress states and installs nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from .env import getenv

log = logging.getLogger(__name__)

INSTALL_MODULE = "dodaios.verse_host.install"
FAKE_ENV = "DODAIOS_VERSE_FAKE_INSTALL"

Phase = Literal["downloading", "verifying", "installing"]
JobState = Literal[
    "idle",  # nothing running; see ``installed_version`` for what is on disk
    "downloading",
    "verifying",
    "installing",
    "installed",  # the last run finished
    "cancelled",
    "failed",
    "removing",
    "unavailable",  # no package published for this platform (or WP22 not landed)
]
ProgressFn = Callable[[Phase, int, int], None]


@dataclass(frozen=True)
class Manifest:
    """What the published Verse package for this platform is."""

    version: str
    download_bytes: int
    install_bytes: int


class InstallError(Exception):
    """The installer refused or failed; ``message`` is shown on the card."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@runtime_checkable
class VerseInstaller(Protocol):
    """Implemented by ``dodaios.verse_host.install`` (WP22.5)."""

    async def manifest(self) -> Manifest | None:
        """The package on offer, or ``None`` when none is published for this platform."""
        ...

    def installed_version(self) -> str | None:
        """The version on disk, or ``None`` when the Verse is not installed."""
        ...

    async def install(self, progress: ProgressFn) -> None:
        """Download (resuming a partial file), verify and unpack.

        Calls ``progress(phase, done_bytes, total_bytes)`` as it goes. A task
        cancel (``asyncio.CancelledError``) stops it and keeps the partial
        download for the next resume. Raises :class:`InstallError` when the
        package is rejected (signature, hash, disk space).
        """
        ...

    async def uninstall(self) -> None:
        """Delete the installed Verse folder; a no-op when nothing is installed."""
        ...


class UnavailableInstaller:
    """Stand-in until WP22's package lands: nothing to download, nothing installed."""

    async def manifest(self) -> Manifest | None:
        return None

    def installed_version(self) -> str | None:
        return None

    async def install(self, progress: ProgressFn) -> None:
        raise InstallError("The Verse download is not published yet.")

    async def uninstall(self) -> None:
        return None


class SimulatedInstaller:
    """UI check double (``DODAIOS_VERSE_FAKE_INSTALL=1``): progress only, no files."""

    def __init__(self, *, download_bytes: int = 7_400_000_000, seconds: float = 40.0) -> None:
        self.download_bytes = download_bytes
        self.seconds = seconds
        self.version: str | None = None
        self.done = 0

    async def manifest(self) -> Manifest | None:
        return Manifest("0.0.0-simulated", self.download_bytes, int(self.download_bytes * 1.4))

    def installed_version(self) -> str | None:
        return self.version

    async def install(self, progress: ProgressFn) -> None:
        steps = 200
        chunk = self.download_bytes // steps
        while self.done < self.download_bytes:
            await asyncio.sleep(self.seconds / steps)
            self.done = min(self.download_bytes, self.done + chunk)
            progress("downloading", self.done, self.download_bytes)
        progress("verifying", self.download_bytes, self.download_bytes)
        await asyncio.sleep(0.5)
        progress("installing", self.download_bytes, self.download_bytes)
        await asyncio.sleep(0.5)
        self.version = "0.0.0-simulated"

    async def uninstall(self) -> None:
        self.version = None
        self.done = 0


def load_installer(data_dir: Path) -> VerseInstaller:
    """WP22's installer when present, else the simulated or the unavailable one."""
    if getenv(FAKE_ENV).strip() == "1":
        return SimulatedInstaller()
    try:
        module = importlib.import_module(INSTALL_MODULE)
    except ImportError:
        return UnavailableInstaller()
    factory = getattr(module, "get_installer", None)
    if factory is None:
        log.warning("verse install: %s has no get_installer(); download disabled", INSTALL_MODULE)
        return UnavailableInstaller()
    installer = factory(Path(data_dir))
    if not isinstance(installer, VerseInstaller):
        log.warning("verse install: %s.get_installer() returned %r", INSTALL_MODULE, installer)
        return UnavailableInstaller()
    return installer


@dataclass
class Progress:
    state: JobState = "idle"
    done_bytes: int = 0
    total_bytes: int = 0
    version: str | None = None
    installed_version: str | None = None
    download_bytes: int | None = None
    install_bytes: int | None = None
    error: str | None = None
    started_at: float | None = None
    bytes_per_s: float | None = None

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out.pop("started_at")
        return out


class InstallBusy(Exception):
    """A remove was asked for while a download runs (cancel it first)."""


class InstallJob:
    """One download or removal at a time; the routes read :meth:`progress`."""

    def __init__(
        self,
        installer: VerseInstaller,
        *,
        on_change: Callable[[], Awaitable[None]] | None = None,
        before_remove: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.installer = installer
        self.on_change = on_change
        self.before_remove = before_remove
        self._progress = Progress()
        self._task: asyncio.Task[None] | None = None
        self._manifest: Manifest | None = None
        self._manifest_at = 0.0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _read_manifest(self, *, refresh: bool = False) -> Manifest | None:
        if refresh or self._manifest is None or time.monotonic() - self._manifest_at > 600:
            try:
                self._manifest = await self.installer.manifest()
            except Exception as exc:  # noqa: BLE001 - offline, server error: show and retry later
                log.info("verse install: manifest unavailable: %s", exc)
                self._manifest = None
            self._manifest_at = time.monotonic()
        return self._manifest

    async def progress(self, *, refresh: bool = False) -> dict[str, Any]:
        p = self._progress
        if not self.running:
            manifest = await self._read_manifest(refresh=refresh)
            p.installed_version = self.installer.installed_version()
            if manifest is None:
                p.download_bytes = p.install_bytes = p.version = None
                if p.state in ("idle", "unavailable"):
                    p.state = "unavailable"
            else:
                p.version = manifest.version
                p.download_bytes = manifest.download_bytes
                p.install_bytes = manifest.install_bytes
                if p.state == "unavailable":
                    p.state = "idle"
        return p.to_json()

    async def start(self) -> dict[str, Any]:
        """Start the download; a second call while one runs joins it."""
        if self.running:
            return self._progress.to_json()
        manifest = await self._read_manifest(refresh=True)
        if manifest is None:
            self._progress = Progress(
                state="unavailable",
                installed_version=self.installer.installed_version(),
                error="The Verse download is not published yet.",
            )
            return self._progress.to_json()
        self._progress = Progress(
            state="downloading",
            total_bytes=manifest.download_bytes,
            version=manifest.version,
            download_bytes=manifest.download_bytes,
            install_bytes=manifest.install_bytes,
            installed_version=self.installer.installed_version(),
            started_at=time.monotonic(),
        )
        self._task = asyncio.ensure_future(self._run())
        return self._progress.to_json()

    def _report(self, phase: Phase, done: int, total: int) -> None:
        p = self._progress
        p.state = phase
        p.done_bytes = max(0, int(done))
        p.total_bytes = max(p.done_bytes, int(total))
        if phase == "downloading" and p.started_at is not None:
            spent = time.monotonic() - p.started_at
            if spent > 0.5:
                p.bytes_per_s = p.done_bytes / spent

    async def _run(self) -> None:
        p = self._progress
        try:
            await self.installer.install(self._report)
        except asyncio.CancelledError:
            p.state = "cancelled"
            p.bytes_per_s = None
            raise
        except InstallError as exc:
            p.state, p.error = "failed", exc.message
        except Exception as exc:  # noqa: BLE001 - a network or disk error ends this run only
            log.warning("verse install failed: %s", exc)
            p.state, p.error = "failed", str(exc) or exc.__class__.__name__
        else:
            p.state = "installed"
            p.done_bytes = p.total_bytes
            p.installed_version = self.installer.installed_version()
        finally:
            p.bytes_per_s = None if p.state != "installed" else p.bytes_per_s
            await self._changed()

    async def cancel(self) -> bool:
        task = self._task
        if task is None or task.done():
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        return True

    async def remove(self) -> dict[str, Any]:
        """Stop the Verse and delete the installed build."""
        if self.running:
            raise InstallBusy("A download is running; cancel it first.")
        if self.before_remove is not None:
            await self.before_remove()
        self._progress.state = "removing"
        try:
            await self.installer.uninstall()
        except Exception as exc:  # noqa: BLE001 - files in use, permissions
            self._progress.state, self._progress.error = "failed", str(exc)
            raise InstallError(f"The Verse could not be removed: {exc}") from exc
        self._progress = Progress()
        await self._changed()
        return await self.progress()

    async def _changed(self) -> None:
        if self.on_change is None:
            return
        try:
            await self.on_change()
        except Exception:  # noqa: BLE001
            log.exception("verse install: status refresh failed")
