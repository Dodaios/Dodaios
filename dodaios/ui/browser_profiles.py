"""The user's installed Chromium browsers and their profiles, for the IDE browser panel.

The Agentic IDE's browser panel shows a real window of the user's own browser,
signed in with their own profile (see ``dodaios.ui.browser_embed``). This module
holds the parts that need no window system: where the browsers live, which
profiles they have, how the new window is recognised, and how a panel's page
rectangle becomes window pixels. Everything here is pure or reads files only,
so it is tested on every platform.

Profiles come from the browser's own ``Local State`` file, the same list the
browser's profile picker shows. Nothing is copied, decrypted or changed: the
window that opens is the browser itself, so cookies and sign-ins stay where they
are.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)

__all__ = [
    "BROWSERS",
    "DEFAULT_START_URL",
    "BrowserProfile",
    "BrowserSpec",
    "browser_by_id",
    "find_browser_exe",
    "handoff_url",
    "installed_browsers",
    "is_profile_dir",
    "is_token",
    "new_token",
    "panel_to_client_rect",
    "read_profiles",
    "real_local_app_data",
    "safe_start_url",
]

#: Where a fresh panel window goes when no address was given.
DEFAULT_START_URL = "https://www.google.com/"


@dataclass(frozen=True)
class BrowserSpec:
    """One Chromium browser: where its exe and its profiles live on Windows."""

    id: str
    label: str
    #: Paths below Program Files, Program Files (x86) or %LOCALAPPDATA%.
    exe_relpaths: tuple[str, ...]
    #: The ``User Data`` folder below %LOCALAPPDATA%.
    user_data_rel: str

    @property
    def image_name(self) -> str:
        """The exe file name, as the process of a browser window reports it."""
        return Path(self.exe_relpaths[0].replace("\\", "/")).name.lower()


#: Chrome first: it is what most people mean by "my browser". Edge and Brave are
#: the same engine, so the same window handling works for them.
BROWSERS: tuple[BrowserSpec, ...] = (
    BrowserSpec(
        "chrome", "Google Chrome",
        (r"Google\Chrome\Application\chrome.exe",), r"Google\Chrome\User Data",
    ),
    BrowserSpec(
        "edge", "Microsoft Edge",
        (r"Microsoft\Edge\Application\msedge.exe",), r"Microsoft\Edge\User Data",
    ),
    BrowserSpec(
        "brave", "Brave",
        (r"BraveSoftware\Brave-Browser\Application\brave.exe",),
        r"BraveSoftware\Brave-Browser\User Data",
    ),
)


def browser_by_id(browser_id: str | None) -> BrowserSpec | None:
    """The spec for ``browser_id``, or None for an unknown id."""
    return next((spec for spec in BROWSERS if spec.id == browser_id), None)


@dataclass(frozen=True)
class BrowserProfile:
    """One profile as the browser's own profile picker lists it."""

    directory: str
    name: str
    #: The signed-in account, empty for a profile without sign-in.
    email: str

    def as_dict(self) -> dict[str, str]:
        return {"directory": self.directory, "name": self.name, "email": self.email}


def _install_roots(env: Mapping[str, str]) -> list[Path]:
    local = env.get("LOCALAPPDATA") if env is not os.environ else (
        real_local_app_data() or env.get("LOCALAPPDATA")
    )
    roots = [
        env.get("PROGRAMFILES") or r"C:\Program Files",
        env.get("PROGRAMFILES(X86)") or r"C:\Program Files (x86)",
        local or "",
    ]
    return [Path(root) for root in roots if root]


def find_browser_exe(spec: BrowserSpec, env: Mapping[str, str] | None = None) -> Path | None:
    """The installed exe of ``spec``, or None when it is not installed."""
    env = os.environ if env is None else env
    for root in _install_roots(env):
        for relpath in spec.exe_relpaths:
            candidate = root / relpath
            if candidate.is_file():
                return candidate
    return None


def real_local_app_data() -> str | None:
    """The real per-user Local AppData folder from the shell, or None off Windows.

    Asked from the shell rather than read from %LOCALAPPDATA%, which a launcher
    or an isolated test instance may point elsewhere: the browser's profiles
    are always in the user's real folder.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes  # noqa: PLC0415
        import uuid  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        folder = uuid.UUID("{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}")  # FOLDERID_LocalAppData
        guid = (ctypes.c_byte * 16).from_buffer_copy(folder.bytes_le)
        path = wintypes.LPWSTR()
        shell32 = ctypes.WinDLL("shell32")
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path)) != 0:
            return None
        try:
            return path.value
        finally:
            ctypes.WinDLL("ole32").CoTaskMemFree(path)
    except (OSError, AttributeError, ValueError):  # no shell folder API: callers use %LOCALAPPDATA%
        return None


def user_data_dir(spec: BrowserSpec, env: Mapping[str, str] | None = None) -> Path | None:
    """The browser's ``User Data`` folder, or None when Local AppData is unknown.

    With an explicit ``env`` (tests) only that mapping is used.
    """
    if env is not None:
        local = env.get("LOCALAPPDATA")
    else:
        local = real_local_app_data() or os.environ.get("LOCALAPPDATA")
    return Path(local) / spec.user_data_rel if local else None


def read_profiles(user_data: Path | None) -> tuple[list[BrowserProfile], str | None]:
    """The profiles in ``user_data`` and the one used last.

    Reads ``Local State``, the file behind the browser's own profile picker.
    Profiles keep the picker's order. A missing or unreadable file gives no
    profiles, so a browser that was never started simply offers its default
    profile. Never raises.
    """
    if user_data is None:
        return [], None
    try:
        state = json.loads((user_data / "Local State").read_text(encoding="utf-8"))
    except FileNotFoundError:  # a browser that never ran has no profile list yet
        return [], None
    except (OSError, ValueError) as exc:
        logger.warning("Could not read the browser profile list: %s", type(exc).__name__)
        return [], None
    section = state.get("profile") if isinstance(state, dict) else None
    if not isinstance(section, dict):
        return [], None
    cache = section.get("info_cache")
    if not isinstance(cache, dict):
        return [], None
    profiles: dict[str, BrowserProfile] = {}
    for directory, info in cache.items():
        if not isinstance(directory, str) or not isinstance(info, dict):
            continue
        if info.get("is_omitted_from_profile_list") or info.get("is_ephemeral"):
            continue
        name = str(info.get("name") or info.get("gaia_name") or directory)
        email = str(info.get("user_name") or "")
        profiles[directory] = BrowserProfile(directory, name, email)
    order = section.get("profiles_order")
    ordered: list[BrowserProfile] = []
    if isinstance(order, list):
        ordered = [profiles.pop(d) for d in order if isinstance(d, str) and d in profiles]
    ordered.extend(sorted(profiles.values(), key=lambda p: p.name.lower()))
    last_used = section.get("last_used")
    if not isinstance(last_used, str) or last_used not in {p.directory for p in ordered}:
        last_used = ordered[0].directory if ordered else None
    return ordered, last_used


def installed_browsers(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Every installed browser of :data:`BROWSERS` with its profiles, for the panel's picker."""
    found: list[dict[str, Any]] = []
    for spec in BROWSERS:
        if find_browser_exe(spec, env) is None:
            continue
        profiles, last_used = read_profiles(user_data_dir(spec, env))
        if not profiles:
            # A browser that never ran still has its default profile.
            profiles, last_used = [BrowserProfile("Default", spec.label, "")], "Default"
        found.append({
            "id": spec.id,
            "label": spec.label,
            "profiles": [profile.as_dict() for profile in profiles],
            "last_used": last_used,
        })
    return found


_PROFILE_DIR = re.compile(r"^[A-Za-z0-9 _.-]{1,64}$")


def is_profile_dir(value: str) -> bool:
    """Whether ``value`` can be a profile folder name (no paths, no switches)."""
    return (
        bool(_PROFILE_DIR.fullmatch(value))
        and not value.startswith(("-", ".", " "))
        and not value.endswith((".", " "))
    )


def safe_start_url(url: str | None) -> str:
    """``url`` when it is a plain http(s) address, otherwise the default start page.

    Only web addresses are passed on: a ``file:``, ``javascript:`` or browser
    internal page cannot be opened this way and is not tried.
    """
    if not url:
        return DEFAULT_START_URL
    parsed = urlparse(url.strip())
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url.strip()
    return DEFAULT_START_URL


_TOKEN = re.compile(r"^[a-z0-9]{12,40}$")


def new_token() -> str:
    """A fresh marker that names exactly one new browser window."""
    import secrets  # noqa: PLC0415

    return "dodaios" + secrets.token_hex(8)


def is_token(value: str) -> bool:
    return bool(_TOKEN.match(value))


def handoff_url(token: str, target: str) -> str:
    """The address the new window opens first: a blank page titled ``token``.

    The window title carries the page title, so the token identifies the window
    the app asked for even when the browser opens other windows at the same
    time (a cold start restoring the last session). A ``data:`` page needs no
    server: the browser never has to reach the app. It forwards to ``target``
    after a moment, which is enough for the app to find and take the window;
    ``location.replace`` keeps the blank page out of the back history.
    """
    if not is_token(token):
        raise ValueError("invalid window token")
    # JSON keeps the address a string literal; escaping "<" keeps it inside the script.
    target_js = json.dumps(safe_start_url(target)).replace("<", "\\u003c")
    html = (
        f"<!doctype html><title>{token}</title>"
        "<body style='margin:0;background:#1f1f1f'></body>"
        f"<script>setTimeout(function(){{location.replace({target_js})}},900)</script>"
    )
    return "data:text/html;charset=utf-8," + quote(html, safe="")


def panel_to_client_rect(
    rect: Mapping[str, float],
    device_pixel_ratio: float,
    origin: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Turn a page rectangle (CSS pixels) into ``(x, y, width, height)`` window pixels.

    ``rect`` is the panel's ``getBoundingClientRect()``; ``device_pixel_ratio``
    is the page's ``devicePixelRatio``, which already holds both the monitor
    scale and the app's own zoom. ``origin`` is where the page's top-left corner
    sits in the host window's client area. Edges are rounded separately, so two
    panels that touch in CSS still touch in pixels. Never negative in size.
    """
    ratio = device_pixel_ratio if device_pixel_ratio > 0 else 1.0
    x = float(rect.get("x", 0.0))
    y = float(rect.get("y", 0.0))
    width = max(0.0, float(rect.get("width", 0.0)))
    height = max(0.0, float(rect.get("height", 0.0)))
    left = round(x * ratio) + origin[0]
    top = round(y * ratio) + origin[1]
    right = round((x + width) * ratio) + origin[0]
    bottom = round((y + height) * ratio) + origin[1]
    return left, top, max(0, right - left), max(0, bottom - top)
