"""Resumable, verified download of one Verse package (WP22.5).

A package streams into ``<downloads>/<name>.part``. After a dropped
connection, an app restart or a cancel, the next attempt asks for
``Range: bytes=<size of .part>-`` and appends; a server that ignores ranges
(``200``) starts the file over. The file is renamed to its final name only
after its size and SHA-256 match the signed manifest, so nothing unverified
is ever unpacked. A cancelled download keeps its ``.part`` so it resumes.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from dodaios.verse_host.install.layout import VerseInstallError
from dodaios.verse_host.install.manifest import PackageRef
from dodaios.verse_host.install.payload import sha256_file

log = logging.getLogger(__name__)

__all__ = [
    "MAX_TEXT_BYTES",
    "HttpFetcher",
    "Progress",
    "RangeFetcher",
    "download_package",
]

#: ``(bytes on disk, total bytes)`` as a download advances.
Progress = Callable[[int, int], None]
#: Transport failures one download survives by resuming where it stopped.
RESUME_ATTEMPTS = 8
RESUME_BACKOFF_S = 3.0
#: Release listings and manifests; anything larger is not what was published.
MAX_TEXT_BYTES = 4_000_000
CONNECT_TIMEOUT_S = 15.0
READ_TIMEOUT_S = 120.0
USER_AGENT = "Dodaios-Verse-Installer"


class RangeFetcher(Protocol):
    """The only network the Verse installer performs. Faked in tests."""

    async def get_text(self, url: str, *, max_bytes: int) -> str: ...

    async def download_range(
        self,
        url: str,
        dest: Path,
        *,
        offset: int,
        max_bytes: int,
        on_chunk: Callable[[int], None] | None = None,
    ) -> int:
        """Append ``url`` from byte ``offset`` to ``dest`` (or rewrite it); return its size."""
        ...


class HttpFetcher:
    """:class:`RangeFetcher` on httpx. Every hop, redirects included, must be ``https``.

    ``allow_loopback_http`` exists for tests against a local server only.
    """

    def __init__(self, *, transport: Any | None = None, allow_loopback_http: bool = False) -> None:
        self._transport = transport
        self._allow_loopback_http = allow_loopback_http

    async def _check_hop(self, request: Any) -> None:
        if request.url.scheme == "https":
            return
        if self._allow_loopback_http and request.url.host in {"127.0.0.1", "localhost"}:
            return
        raise VerseInstallError(
            f"refusing a non-https download hop to {request.url.host or 'an unknown host'}"
        )

    def _client(self) -> Any:
        import httpx  # lazy: the app boots without ever loading it here

        return httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
            follow_redirects=True,
            transport=self._transport,
            event_hooks={"request": [self._check_hop]},
            headers={"User-Agent": USER_AGENT},
        )

    async def get_text(self, url: str, *, max_bytes: int) -> str:
        body = bytearray()
        async with self._client() as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise VerseInstallError(f"{url} is larger than {max_bytes} bytes")
        return body.decode("utf-8")

    async def download_range(
        self,
        url: str,
        dest: Path,
        *,
        offset: int,
        max_bytes: int,
        on_chunk: Callable[[int], None] | None = None,
    ) -> int:
        headers = {"Accept": "application/octet-stream"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        async with self._client() as client:
            async with client.stream("GET", url, headers=headers) as response:
                if offset and response.status_code == 416:
                    return offset  # already complete; the hash check decides
                response.raise_for_status()
                resumed = bool(offset) and response.status_code == 206
                written = offset if resumed else 0
                with dest.open("ab" if resumed else "wb") as handle:
                    async for chunk in response.aiter_bytes():
                        written += len(chunk)
                        if written > max_bytes:
                            raise VerseInstallError(
                                f"the download exceeded {max_bytes} bytes — refusing it"
                            )
                        handle.write(chunk)
                        if on_chunk is not None:
                            on_chunk(written)
        return written


def _report(on_progress: Progress | None, done: int, total: int) -> None:
    if on_progress is None:
        return
    try:
        on_progress(done, total)
    except Exception:  # noqa: BLE001 - a progress consumer never breaks a download
        log.debug("[verse] progress callback failed", exc_info=True)


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning("[verse] could not remove %s", path)


async def download_package(
    ref: PackageRef,
    url: str,
    *,
    dest_dir: Path,
    fetcher: RangeFetcher,
    on_progress: Progress | None = None,
    timeout_s: float = 6 * 3600.0,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> Path:
    """Download ``ref`` from ``url`` into ``dest_dir``, resuming after drops. Fail closed."""
    _make_dir(dest_dir)
    final = dest_dir / ref.name
    part = dest_dir / f"{ref.name}.part"
    if final.is_file():
        if final.stat().st_size == ref.size and await asyncio.to_thread(sha256_file, final) == (
            ref.sha256
        ):
            _report(on_progress, ref.size, ref.size)
            return final
        _discard(final)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    attempt = 0
    while True:
        offset = part.stat().st_size if part.is_file() else 0
        if offset > ref.size:
            _discard(part)
            offset = 0
        _report(on_progress, offset, ref.size)
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise VerseInstallError(
                f"{ref.name} did not finish in time; the next attempt resumes where it stopped"
            )
        try:
            await asyncio.wait_for(
                fetcher.download_range(
                    url,
                    part,
                    offset=offset,
                    max_bytes=ref.size,
                    on_chunk=lambda done: _report(on_progress, done, ref.size),
                ),
                timeout=remaining,
            )
            break
        except VerseInstallError:
            _discard(part)
            raise
        except TimeoutError as exc:
            raise VerseInstallError(
                f"{ref.name} did not finish in time; the next attempt resumes where it stopped"
            ) from exc
        except asyncio.CancelledError:
            log.info("[verse] %s paused at %d bytes", ref.name, _size(part))
            raise
        except Exception as exc:  # noqa: BLE001 - every transport error resumes
            attempt += 1
            if attempt >= RESUME_ATTEMPTS:
                raise VerseInstallError(
                    f"{ref.name}: {attempt} attempts failed ({exc}); "
                    "the next attempt resumes where this one stopped"
                ) from exc
            log.info("[verse] %s dropped at %d bytes (%s); resuming", ref.name, _size(part), exc)
            await sleep(RESUME_BACKOFF_S)
    size = _size(part)
    actual = await asyncio.to_thread(sha256_file, part) if size == ref.size else None
    if actual != ref.sha256:
        _discard(part)
        raise VerseInstallError(
            f"{ref.name} failed its check (size {size} of {ref.size}, sha256 {actual}) — "
            "the download was NOT installed"
        )
    os.replace(part, final)
    log.info("[verse] verified %s (sha256 %s)", ref.name, actual)
    return final


def _make_dir(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:  # no partial file yet: the download starts at byte 0
        return 0
