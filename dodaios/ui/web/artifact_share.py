"""Prepare an artifact for sharing: a named copy, a PDF or a picture of a page.

The Artifacts stage's "Share" button hands a FILE to the operating system's
share sheet (macOS: ``NSSharingServicePicker``, see ``dodaios/ui/native_share.py``)
or, in a plain browser, downloads it. Nothing here uploads anything: sharing
is always the person's own act in the sheet (AirDrop, Mail, Messages, …), so
no artifact ever becomes reachable by anyone without that explicit step.

What is shared is a STAGED copy in a private temp folder, never the run's own
file: the recipient gets the artifact under its title (``Umsatz-Dashboard.pdf``
instead of ``index.html``), and the share sheet cannot reach any other file
of the person's — the native bridge accepts only paths inside
:func:`share_folder`.

A page (one self-contained HTML file) can also go out as a PDF or a PNG. Both
are drawn by a headless Chrome over the DevTools protocol. The page is not
fetched from the app's server: Chrome is pointed at an address that does not
exist (``https://artifact.invalid/``) and every request is intercepted — the
page itself is answered from the file with the same locked-down policy the
in-app frame uses (:data:`ARTIFACT_PAGE_CSP`), every other request fails. So a
page that tries to load anything from the network gets nothing, exactly as on
the stage.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final, Literal, TypeVar

from dodaios.ui.web.artifact_view import ARTIFACT_PAGE_CSP

log = logging.getLogger(__name__)

ShareFormat = Literal["file", "pdf", "png"]

#: Staged copies older than this are removed when the next one is staged; the
#: share sheet has long copied what it needed by then.
STAGE_MAX_AGE_S: Final = 24 * 3600

#: The address the headless browser loads; ``.invalid`` never resolves, and
#: every request to it is answered from the artifact file itself.
_PAGE_ORIGIN: Final = "https://artifact.invalid"
_PAGE_URL: Final = f"{_PAGE_ORIGIN}/page.html"

#: Width the page is laid out at for a picture, in CSS pixels.
_PICTURE_WIDTH: Final = 1280
#: A picture taller than this is cut (CSS pixels) — a sane cap for a chat.
_PICTURE_MAX_HEIGHT: Final = 16000
#: Time the page's own scripts get to draw after load (charts, counters).
_SETTLE_S: Final = 0.8
#: A slide of a deck page, in CSS pixels (``dodaios.nodes.kinds.slides``).
SLIDE_WIDTH: Final = 1280
SLIDE_HEIGHT: Final = 720
#: Time a deck gets after load before a slide is captured (fonts, charts).
_SLIDE_SETTLE_S: Final = 0.35

_T = TypeVar("_T")

#: Upper bound for one export, Chrome start included.
_EXPORT_TIMEOUT_S: Final = 45.0

_TOKEN_RE: Final = re.compile(r"^[0-9a-f]{16,64}$")
_UNSAFE_NAME_CHARS: Final = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')

_MAC_BROWSERS: Final = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)


class ShareExportError(RuntimeError):
    """A PDF or picture could not be drawn (no browser, a crash, a timeout)."""


def share_folder() -> Path:
    """Where staged copies live (not created here): private per user.

    The desktop window's native share bridge computes the same path and
    shares nothing outside it.
    """
    base = Path(tempfile.gettempdir())
    if os.name == "nt":
        return base / "dodaios-share"
    return base / f"dodaios-share-{os.getuid()}"


def safe_filename(title: str, fallback: str) -> str:
    """A title as a file name every OS and every share target accepts."""
    name = _UNSAFE_NAME_CHARS.sub(" ", title or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = _UNSAFE_NAME_CHARS.sub(" ", fallback).strip(" .") or "artifact"
    return name[:120].rstrip(" .")


def _prune(folder: Path, now: float) -> None:
    try:
        entries = list(folder.iterdir())
    except OSError:  # nothing staged yet, or the folder vanished meanwhile
        return
    for entry in entries:
        try:
            if now - entry.stat().st_mtime > STAGE_MAX_AGE_S:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError as exc:
            log.debug("artifact_share: could not prune %s: %s", entry, exc)


def new_stage_dir() -> tuple[str, Path]:
    """A fresh private folder for one share, after clearing out old ones."""
    folder = share_folder()
    folder.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(folder, 0o700)
    _prune(folder, time.time())
    token = secrets.token_hex(16)
    stage = folder / token
    stage.mkdir(mode=0o700)
    return token, stage


def staged_file(token: str, name: str) -> Path | None:
    """The staged file a download link names, or None for anything else."""
    if not _TOKEN_RE.match(token) or name != Path(name).name or name in ("", ".", ".."):
        return None
    folder = share_folder().resolve()
    target = (folder / token / name).resolve()
    if target.parent.parent != folder or not target.is_file():
        return None
    return target


def stage_copy(source: Path, title: str) -> tuple[str, Path]:
    """Copy ``source`` into a new stage folder under the artifact's title."""
    token, stage = new_stage_dir()
    name = safe_filename(title, source.stem) + source.suffix.lower()
    target = stage / name
    shutil.copyfile(source, target)
    return token, target


# --- PDF and picture of a page ------------------------------------------------


def find_export_browser() -> str | None:
    """A Chromium-family browser able to draw a page headless, or None."""
    try:
        from dodaios.society.browser.session import system_chrome  # noqa: PLC0415 — heavy package

        found = system_chrome()
    except Exception as exc:  # noqa: BLE001 — the browser package is optional here
        log.debug("artifact_share: system_chrome unavailable: %s", exc)
        found = None
    if found:
        return found
    if sys.platform == "darwin":
        for candidate in _MAC_BROWSERS:
            if Path(candidate).is_file():
                return candidate
    for name in ("msedge", "microsoft-edge", "brave-browser"):
        located = shutil.which(name)
        if located:
            return located
    return None


class _Cdp:
    """The few DevTools calls an export needs, over one page socket."""

    def __init__(self, socket: Any) -> None:
        self._socket = socket
        self._next = 0
        self._waiting: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: dict[str, list[asyncio.Future[dict[str, Any]]]] = {}
        self.on_paused: Any = None

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next += 1
        ident = self._next
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._waiting[ident] = future
        await self._socket.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        return await future

    def next_event(self, method: str) -> asyncio.Future[dict[str, Any]]:
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._events.setdefault(method, []).append(future)
        return future

    async def pump(self) -> None:
        async for raw in self._socket:
            message = json.loads(raw)
            ident = message.get("id")
            if ident is not None:
                future = self._waiting.pop(int(ident), None)
                if future is not None and not future.done():
                    if "error" in message:
                        future.set_exception(ShareExportError(str(message["error"])))
                    else:
                        future.set_result(message.get("result") or {})
                continue
            method = message.get("method", "")
            params = message.get("params") or {}
            if method == "Fetch.requestPaused" and self.on_paused is not None:
                asyncio.ensure_future(self.on_paused(params))
            for future in self._events.pop(method, []):
                if not future.done():
                    future.set_result(params)


def _devtools_port(profile: Path, deadline: float) -> int:
    marker = profile / "DevToolsActivePort"
    while time.monotonic() < deadline:
        try:
            first = marker.read_text(encoding="utf-8").splitlines()[0]
            return int(first)
        except (OSError, ValueError, IndexError):  # not written yet: the browser is starting
            time.sleep(0.05)
    raise ShareExportError("the browser did not open its DevTools port")


def _page_socket_url(port: int, deadline: float) -> str:
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as reply:  # noqa: S310 — loopback DevTools
                targets = json.loads(reply.read().decode("utf-8"))
            for target in targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return str(target["webSocketDebuggerUrl"])
        except (OSError, ValueError):  # the DevTools endpoint answers a moment after the marker
            pass
        time.sleep(0.05)
    raise ShareExportError("the browser opened no page")


def _serve_page(cdp: _Cdp, html: bytes) -> None:
    """Answer the page address from ``html`` and fail every other request."""

    async def answer(params: dict[str, Any]) -> None:
        request_id = params.get("requestId")
        url = str((params.get("request") or {}).get("url", ""))
        try:
            if url.split("?", 1)[0] == _PAGE_URL:
                await cdp.call(
                    "Fetch.fulfillRequest",
                    {
                        "requestId": request_id,
                        "responseCode": 200,
                        "responseHeaders": [
                            {"name": "Content-Type", "value": "text/html; charset=utf-8"},
                            {"name": "Content-Security-Policy", "value": ARTIFACT_PAGE_CSP},
                        ],
                        "body": base64.b64encode(html).decode("ascii"),
                    },
                )
            else:
                await cdp.call(
                    "Fetch.failRequest",
                    {"requestId": request_id, "errorReason": "BlockedByClient"},
                )
        except ShareExportError as exc:  # the page went away mid-request
            log.debug("artifact_share: could not answer %s: %s", url, exc)

    cdp.on_paused = answer


async def _with_page(socket_url: str, html: bytes, draw: Callable[[_Cdp], Awaitable[_T]]) -> _T:
    """Connect to the browser, serve ``html`` and run ``draw`` on the page."""
    import websockets  # noqa: PLC0415 — only an export needs it

    async with websockets.connect(socket_url, max_size=None) as socket:
        cdp = _Cdp(socket)
        pump = asyncio.ensure_future(cdp.pump())
        _serve_page(cdp, html)
        try:
            await cdp.call("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})
            await cdp.call("Page.enable")
            return await draw(cdp)
        finally:
            pump.cancel()
            try:
                await pump
            except asyncio.CancelledError:  # the reader was cancelled just above
                pass
            except Exception as exc:  # noqa: BLE001 — the socket closing under the reader
                log.debug("artifact_share: DevTools reader ended: %s", exc)


async def _draw(socket_url: str, html: bytes, fmt: Literal["pdf", "png"], theme: str) -> bytes:
    async def draw(cdp: _Cdp) -> bytes:
        if fmt == "png":
            await cdp.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": _PICTURE_WIDTH, "height": 900, "deviceScaleFactor": 2, "mobile": False},
            )
        loaded = cdp.next_event("Page.loadEventFired")
        await cdp.call("Page.navigate", {"url": f"{_PAGE_URL}?theme={theme}"})
        await loaded
        await asyncio.sleep(_SETTLE_S)
        if fmt == "pdf":
            result = await cdp.call(
                "Page.printToPDF",
                {
                    "printBackground": True,
                    "preferCSSPageSize": True,
                    "displayHeaderFooter": False,
                    "marginTop": 0.4,
                    "marginBottom": 0.4,
                    "marginLeft": 0.4,
                    "marginRight": 0.4,
                },
            )
        else:
            metrics = await cdp.call("Page.getLayoutMetrics")
            size = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
            height = int(min(max(float(size.get("height", 900)), 400), _PICTURE_MAX_HEIGHT))
            # A very long page at double density would be a huge file.
            scale = 2 if height <= 6000 else 1
            await cdp.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": _PICTURE_WIDTH,
                    "height": height,
                    "deviceScaleFactor": scale,
                    "mobile": False,
                },
            )
            await asyncio.sleep(0.2)
            result = await cdp.call(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
            )
        return base64.b64decode(result.get("data", ""))

    return await _with_page(socket_url, html, draw)


async def _draw_slides(
    socket_url: str, html: bytes, theme: str, numbers: tuple[int, ...]
) -> list[bytes]:
    """One 1280 x 720 PNG per slide of a deck page, for the slide ``numbers`` (from 1).

    The deck opens on the slide its address names (``#3``); a new query per
    slide makes each a real load, so no slide transition is caught midway.
    The picture is the slide's own frame, as the person sees it in the
    player (theme included), scaled to the slide's design size.
    """

    async def draw(cdp: _Cdp) -> list[bytes]:
        await cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False},
        )
        shots: list[bytes] = []
        for number in numbers:
            loaded = cdp.next_event("Page.loadEventFired")
            url = f"{_PAGE_URL}?theme={theme}&slide={number}#{number}"
            await cdp.call("Page.navigate", {"url": url})
            await loaded
            await asyncio.sleep(_SLIDE_SETTLE_S)
            box = await cdp.call(
                "Runtime.evaluate",
                {
                    "expression": (
                        "(function(){var f=document.querySelector("
                        "'.dk-cell.is-current .dk-frame');if(!f)return null;"
                        "var r=f.getBoundingClientRect();"
                        "return [r.left,r.top,r.width,r.height];})()"
                    ),
                    "returnByValue": True,
                },
            )
            frame = (box.get("result") or {}).get("value")
            if not isinstance(frame, list) or len(frame) != 4 or not frame[2]:
                break
            x, y, width, height = (float(v) for v in frame)
            result = await cdp.call(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "fromSurface": True,
                    "clip": {
                        "x": x,
                        "y": y,
                        "width": width,
                        "height": height,
                        "scale": SLIDE_WIDTH / width,
                    },
                },
            )
            shots.append(base64.b64decode(result.get("data", "")))
        return shots

    return await _with_page(socket_url, html, draw)


def _in_browser(browser: str, draw: Callable[[str], Awaitable[_T]]) -> _T:
    """Start a throwaway headless browser, run ``draw`` on its page, stop the browser."""
    profile = Path(tempfile.mkdtemp(prefix="dodaios-share-browser-"))
    deadline = time.monotonic() + _EXPORT_TIMEOUT_S
    process = subprocess.Popen(  # noqa: S603 — a resolved browser executable, fixed flags
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--mute-audio",
            "--hide-scrollbars",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        port = _devtools_port(profile, deadline)
        socket_url = _page_socket_url(port, deadline)
        remaining = max(1.0, deadline - time.monotonic())
        return asyncio.run(asyncio.wait_for(draw(socket_url), remaining))
    except TimeoutError as exc:
        raise ShareExportError("the page took too long to draw") from exc
    except OSError as exc:
        raise ShareExportError(f"the browser connection failed: {exc}") from exc
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # a browser that ignores terminate is killed
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)


def _run_browser_export(browser: str, html: bytes, fmt: Literal["pdf", "png"], theme: str) -> bytes:
    """Start a throwaway headless browser, draw the page, stop the browser."""
    return _in_browser(browser, lambda socket_url: _draw(socket_url, html, fmt, theme))


def draw_slides(html: bytes, theme: str, numbers: tuple[int, ...]) -> list[bytes]:
    """Pictures of the given slides (numbered from 1) of a deck page, 1280 x 720 PNGs.

    Blocking (starts a browser): call it in a worker thread.
    """
    browser = find_export_browser()
    if browser is None:
        raise ShareExportError("no Chromium-family browser is installed")
    theme = "dark" if theme == "dark" else "light"
    return _in_browser(browser, lambda socket_url: _draw_slides(socket_url, html, theme, numbers))


def draw_page(html: bytes, theme: str) -> bytes:
    """A picture of a whole page (1280 wide) as PNG. Blocking: call it in a worker thread."""
    browser = find_export_browser()
    if browser is None:
        raise ShareExportError("no Chromium-family browser is installed")
    return _run_browser_export(browser, html, "png", "dark" if theme == "dark" else "light")


def export_page(
    source: Path, title: str, fmt: Literal["pdf", "png"], theme: str
) -> tuple[str, Path]:
    """Draw an HTML page as a PDF or PNG into a new stage folder.

    Blocking (starts a browser): call it in a worker thread.
    """
    browser = find_export_browser()
    if browser is None:
        raise ShareExportError("no Chromium-family browser is installed")
    html = source.read_bytes()
    data = _run_browser_export(browser, html, fmt, "dark" if theme == "dark" else "light")
    if not data:
        raise ShareExportError("the browser returned an empty file")
    token, stage = new_stage_dir()
    target = stage / f"{safe_filename(title, source.stem)}.{fmt}"
    target.write_bytes(data)
    return token, target
