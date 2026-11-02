"""The on-demand Verse installer the launcher card drives (WP22.5, WP22.6, A22.7).

The installer and app updates never carry the Verse. The first time someone
opens it, the card (WP17.13) shows the size from :meth:`VerseInstaller.offer`
and a "Download the Verse" button that calls :meth:`VerseInstaller.start_install`;
``GET /api/verse/install/progress`` reads :meth:`VerseInstaller.progress`,
``DELETE /api/verse/install`` cancels a running download (it resumes on the
next start) or, when none runs, :meth:`VerseInstaller.uninstall` removes the
Verse again. Only an installed Verse is offered updates
(:meth:`VerseInstaller.update`, a delta when one fits).

:meth:`VerseInstaller.install_state` answers ``unsupported`` (no package for
this OS, or the capability probe says no GPU: nothing is ever downloaded),
``not_installed``, ``installing``, ``installed`` or ``broken``. WP17's
``GET /api/verse/status`` reports ``installed`` as ``stopped`` / ``running``.

Where packages come from: the newest published release of the official repo,
no newer than the running app, that carries a signed
``verse-<Platform>-manifest.json`` (:mod:`.manifest`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dodaios.verse_host.install import payload
from dodaios.verse_host.install.download import (
    MAX_TEXT_BYTES,
    HttpFetcher,
    RangeFetcher,
    download_package,
)
from dodaios.verse_host.install.layout import (
    VerseInstallError,
    check_version,
    default_root,
    read_current,
    verse_platform,
    version_key,
)
from dodaios.verse_host.install.manifest import (
    PackageRef,
    ReleaseManifest,
    manifest_asset_name,
    signature_asset_name,
    verify_release_manifest,
)

log = logging.getLogger(__name__)

__all__ = ["InstallProgress", "VerseInstaller", "VerseRelease", "find_release", "releases_url"]

#: Releases looked at, newest first; a Verse ships with most releases, not all.
RELEASE_LOOKBACK = 30
#: Free space kept beyond the download and the unpacked folder.
DISK_MARGIN_BYTES = 1_000_000_000
_MAX_SIGNATURE_BYTES = 1_000
#: "Not given": the app's own version / this machine's platform.
_UNSET: Any = object()


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)


def releases_url(slug: str | None = None) -> str:
    if slug is None:
        from dodaios.core.branding import OFFICIAL_REPO_SLUG

        slug = OFFICIAL_REPO_SLUG
    return f"https://api.github.com/repos/{slug}/releases?per_page={RELEASE_LOOKBACK}"


def _app_version() -> str | None:
    try:
        from dodaios import __version__

        return check_version(__version__)
    except (ImportError, VerseInstallError):  # a dev build: no ceiling on the Verse version
        return None


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class VerseRelease:
    """A verified manifest and where its packages download from."""

    manifest: ReleaseManifest
    urls: dict[str, str]

    def url(self, ref: PackageRef) -> str:
        try:
            return self.urls[ref.name]
        except KeyError as exc:
            raise VerseInstallError(f"the release does not carry {ref.name}") from exc


def _asset_urls(release: dict[str, Any]) -> dict[str, tuple[str, int | None]]:
    urls: dict[str, tuple[str, int | None]] = {}
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name, url = asset.get("name"), asset.get("browser_download_url")
        if isinstance(name, str) and isinstance(url, str):
            size = asset.get("size")
            urls[name] = (url, size if isinstance(size, int) else None)
    return urls


async def find_release(
    fetcher: RangeFetcher,
    *,
    platform: str,
    listing_url: str,
    app_version: str | None,
    public_keys: Sequence[str] | None = None,
) -> VerseRelease:
    """The newest release, not newer than the app, with a verified Verse for ``platform``."""
    try:
        listed = json.loads(await fetcher.get_text(listing_url, max_bytes=MAX_TEXT_BYTES))
    except VerseInstallError:
        raise
    except Exception as exc:  # noqa: BLE001 - every network failure reads the same
        raise VerseInstallError(f"the release list could not be read ({exc})") from exc
    if not isinstance(listed, list):
        raise VerseInstallError("the release list is not a list")
    ceiling = version_key(app_version) if app_version else None
    for release in listed:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or "")
        try:
            key = version_key(tag)
        except VerseInstallError:  # not a release tag (a draft name): never a Verse source
            continue
        if ceiling is not None and key > ceiling:
            continue  # a Verse newer than the app may speak a newer bridge protocol
        assets = _asset_urls(release)
        manifest_asset = assets.get(manifest_asset_name(platform))
        signature_asset = assets.get(signature_asset_name(platform))
        if manifest_asset is None or signature_asset is None:
            continue
        try:
            text = await fetcher.get_text(manifest_asset[0], max_bytes=MAX_TEXT_BYTES)
            signature = await fetcher.get_text(signature_asset[0], max_bytes=_MAX_SIGNATURE_BYTES)
        except VerseInstallError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VerseInstallError(
                f"the Verse manifest of {tag} could not be read ({exc})"
            ) from exc
        manifest = verify_release_manifest(
            text.encode("utf-8"), signature, platform=platform, tag=tag, public_keys=public_keys
        )
        urls: dict[str, str] = {}
        for ref in (manifest.full, *manifest.deltas):
            found = assets.get(ref.name)
            if found is None:
                continue
            if found[1] is not None and found[1] != ref.size:
                raise VerseInstallError(
                    f"{ref.name} on {tag} is {found[1]} bytes, the signed manifest says {ref.size}"
                )
            urls[ref.name] = found[0]
        if manifest.full.name not in urls:
            continue
        return VerseRelease(manifest=manifest, urls=urls)
    raise VerseInstallError(f"no published release carries the Verse for {platform} yet")


@dataclass
class InstallProgress:
    phase: str = "idle"  # idle|checking|downloading|installing|done|failed|cancelled
    version: str | None = None
    kind: str | None = None  # full|delta
    done_bytes: int = 0
    total_bytes: int = 0
    error: str | None = None
    started_at: float | None = None
    history: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        percent = round(100.0 * self.done_bytes / self.total_bytes, 1) if self.total_bytes else None
        return {
            "phase": self.phase,
            "version": self.version,
            "kind": self.kind,
            "done_bytes": self.done_bytes,
            "total_bytes": self.total_bytes,
            "percent": percent,
            "error": self.error,
        }


class VerseInstaller:
    """Download, install, update and remove the Verse for one user data folder."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        fetcher: RangeFetcher | None = None,
        listing_url: str | None = None,
        app_version: str | None | object = _UNSET,
        gpu_supported: Callable[[], bool] | bool = True,
        platform: str | None | object = _UNSET,
        public_keys: Sequence[str] | None = None,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ) -> None:
        self.root = default_root() if root is None else root
        self._fetcher: RangeFetcher = HttpFetcher() if fetcher is None else fetcher
        self._listing_url = listing_url or releases_url()
        self._app_version: str | None = (
            _app_version() if app_version is _UNSET else _optional_str(app_version)
        )
        self._gpu_supported = gpu_supported
        self.platform: str | None = (
            verse_platform() if platform is _UNSET else _optional_str(platform)
        )
        self._public_keys = public_keys
        self._disk_usage = disk_usage
        self._progress = InstallProgress()
        self._task: asyncio.Task[dict[str, Any]] | None = None

    # ------------------------------------------------------------ status
    def supported(self) -> bool:
        if self.platform is None:
            return False
        probe = self._gpu_supported
        try:
            return bool(probe() if callable(probe) else probe)
        except Exception:  # noqa: BLE001 - a failing probe means "cannot run it"
            log.warning("[verse] the capability probe failed", exc_info=True)
            return False

    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def install_state(self) -> dict[str, Any]:
        """``unsupported`` / ``not_installed`` / ``installing`` / ``installed`` / ``broken``."""
        current = read_current(self.root)
        base: dict[str, Any] = {"version": current["version"] if current else None}
        if self.busy():
            return {"status": "installing", **base, "progress": self.progress()}
        if not self.supported():
            return {"status": "unsupported", **base}
        if current is None:
            return {"status": "not_installed", "version": None}
        health = payload.ensure_healthy(self.root)
        if health["status"] == "broken":
            return {"status": "broken", **base, "problems": health.get("problems", [])}
        entry = payload.entry_path(self.root)
        return {
            "status": "installed",
            "version": health.get("version", base["version"]),
            "entry": str(entry) if entry else None,
            "install_bytes": payload.folder_bytes(self.root / "versions"),
        }

    def launch_command(self) -> list[str]:
        """The command WP17's supervisor starts; raises when nothing is installed."""
        entry = payload.entry_path(self.root)
        if entry is None or not entry.is_file():
            raise VerseInstallError("the Verse is not installed")
        return [str(entry)]

    def progress(self) -> dict[str, Any]:
        return self._progress.as_dict()

    # ------------------------------------------------------------- offer
    async def release(self) -> VerseRelease:
        if not self.supported() or self.platform is None:
            raise VerseInstallError("this machine cannot run the Verse")
        return await find_release(
            self._fetcher,
            platform=self.platform,
            listing_url=self._listing_url,
            app_version=self._app_version,
            public_keys=self._public_keys,
        )

    async def offer(self) -> dict[str, Any]:
        """What the card shows before the download: version and sizes."""
        manifest = (await self.release()).manifest
        return {
            "version": manifest.version,
            "download_bytes": manifest.full.size,
            "install_bytes": manifest.install_bytes,
        }

    # ----------------------------------------------------------- install
    def start_install(self) -> dict[str, Any]:
        """Start (or join) the download in the background; returns the progress."""
        if not self.busy():
            self._task = asyncio.get_running_loop().create_task(self._run(self.install))
        return self.progress()

    def start_update(self) -> dict[str, Any]:
        if not self.busy():
            self._task = asyncio.get_running_loop().create_task(self._run(self.update))
        return self.progress()

    async def wait(self) -> dict[str, Any] | None:
        task = self._task
        if task is None:
            return None
        try:
            return await task
        except (asyncio.CancelledError, VerseInstallError):  # the reason is in progress()
            return None

    def cancel(self) -> dict[str, Any]:
        """Stop a running download; its ``.part`` stays, so the next start resumes.

        Only the download can be stopped. Once the verified package is being
        unpacked (phase ``installing``) the worker thread cannot be interrupted
        safely, so the cancel is refused and the install finishes.
        """
        if self.busy() and self._task is not None:
            if self._progress.phase == "installing":
                log.info("[verse] cancel refused: the verified package is being unpacked")
            else:
                self._task.cancel()
        return self.progress()

    async def _run(self, job: Callable[[], Any]) -> dict[str, Any]:
        self._progress = InstallProgress(phase="checking", started_at=time.time())
        try:
            result: dict[str, Any] = await job()
        except asyncio.CancelledError:
            self._progress.phase = "cancelled"
            raise
        except VerseInstallError as exc:
            self._progress.phase = "failed"
            self._progress.error = str(exc)
            raise
        except Exception as exc:  # noqa: BLE001 - reported on the card, never swallowed
            log.exception("[verse] install failed")
            self._progress.phase = "failed"
            self._progress.error = f"the Verse install failed: {exc}"
            raise VerseInstallError(self._progress.error) from exc
        self._progress.phase = "done"
        return result

    def _on_bytes(self, done: int, total: int) -> None:
        self._progress.phase = "downloading"
        self._progress.done_bytes = done
        self._progress.total_bytes = total

    def _prune_downloads(self, ref: PackageRef) -> None:
        """Drop packages and ``.part`` files of every other (superseded) release."""
        downloads = self.root / "downloads"
        if not downloads.is_dir():
            return
        keep = {ref.name, f"{ref.name}.part"}
        for entry in downloads.iterdir():
            if entry.name in keep or not entry.is_file():
                continue
            try:
                entry.unlink()
                log.info("[verse] removed stale download %s", entry.name)
            except OSError:
                log.warning("[verse] could not remove stale download %s", entry)

    def _check_disk(self, ref: PackageRef, install_bytes: int) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._prune_downloads(ref)
        part = self.root / "downloads" / f"{ref.name}.part"
        have = part.stat().st_size if part.is_file() else 0
        need = (ref.size - have) + install_bytes + DISK_MARGIN_BYTES
        free = int(self._disk_usage(self.root).free)
        if free < need:
            raise VerseInstallError(
                f"the Verse needs {need / 1e9:.1f} GB free in {self.root}, "
                f"only {free / 1e9:.1f} GB are free"
            )

    async def _fetch(self, release: VerseRelease, ref: PackageRef, kind: str) -> Path:
        self._progress.kind = kind
        self._progress.version = release.manifest.version
        self._progress.total_bytes = ref.size
        await asyncio.to_thread(self._check_disk, ref, release.manifest.install_bytes)
        return await download_package(
            ref,
            release.url(ref),
            dest_dir=self.root / "downloads",
            fetcher=self._fetcher,
            on_progress=self._on_bytes,
        )

    async def _apply(
        self, step: Callable[..., dict[str, Any]], path: Path, manifest: ReleaseManifest
    ) -> dict[str, Any]:
        """Run an unpack step in a worker thread and always wait for that thread.

        Cancelling the awaiting task does not stop a thread, so the task keeps
        waiting until the worker returns: ``busy()`` stays True, uninstall and a
        second install stay refused, and the package is removed only after the
        worker has closed it. A cancel that arrived meanwhile is re-raised then.
        """
        self._progress.phase = "installing"
        worker = asyncio.ensure_future(
            asyncio.to_thread(step, self.root, path, expected=manifest.expected())
        )
        cancelled = False
        try:
            while True:
                try:
                    result = await asyncio.shield(worker)
                    break
                except asyncio.CancelledError:
                    if worker.done():
                        raise
                    cancelled = True
                    log.info("[verse] unpack still running; waiting for it before stopping")
        finally:
            if worker.done():
                _remove(path)
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def install(self) -> dict[str, Any]:
        """Download the full package, verify it, unpack it into the user data folder."""
        release = await self.release()
        manifest = release.manifest
        path = await self._fetch(release, manifest.full, "full")
        result = await self._apply(payload.install_full, path, manifest)
        return {"status": "installed", **result}

    async def update(self) -> dict[str, Any]:
        """Bring an installed Verse to the newest release; a delta when one fits.

        A damaged install rolls back first; one with nothing healthy left gets
        the full package again. A delta that fails leaves the running version
        in place and falls back to the full package.
        """
        health = await asyncio.to_thread(payload.ensure_healthy, self.root)
        if health["status"] == "not_installed":
            raise VerseInstallError("the Verse is not installed; only an installed Verse updates")
        broken = health["status"] == "broken"
        current = read_current(self.root)
        installed = current["version"] if current else None
        release = await self.release()
        manifest = release.manifest
        if not broken and installed and version_key(installed) >= version_key(manifest.version):
            return {"status": "current", "version": installed}
        delta = None if broken else manifest.delta_from(installed)
        if delta is not None and delta.name in release.urls:
            base = payload.read_package_tree(payload.version_dir(self.root, str(installed)))
            if payload.tree_digest(base) == delta.from_tree_sha256:
                try:
                    path = await self._fetch(release, delta, "delta")
                    result = await self._apply(payload.apply_delta, path, manifest)
                    return {"status": "updated", **result}
                except VerseInstallError as exc:
                    log.warning("[verse] delta update failed (%s); using the full package", exc)
        path = await self._fetch(release, manifest.full, "full")
        result = await self._apply(payload.install_full, path, manifest)
        return {"status": "repaired" if broken else "updated", **result}

    # ---------------------------------------------------------- uninstall
    def uninstall(self) -> dict[str, Any]:
        """Remove the Verse; refused while a download or install runs."""
        if self.busy():
            raise VerseInstallError("a Verse download is running; cancel it first")
        result = payload.uninstall(self.root)
        self._progress = InstallProgress()
        return result
