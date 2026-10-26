"""The picture behind the tiled section layout.

By default it is the user's own desktop wallpaper, read from the operating
system on every request (so a changed wallpaper shows up without a restart).
A custom picture uploaded in the app replaces it until it is removed.

Nothing here raises: an OS that will not say where its wallpaper is simply
yields ``None``, and the page paints its plain fallback ground instead.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

#: Extension -> media type of every picture this module will hand out.
IMAGE_MEDIA: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

#: Pillow format name -> extension the uploaded custom picture is stored under.
UPLOAD_FORMAT_EXT: dict[str, str] = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "WEBP": ".webp",
    "GIF": ".gif",
    "BMP": ".bmp",
}

CUSTOM_STEM = "workspace_wallpaper"
MAX_UPLOAD_BYTES = 40 * 1024 * 1024


def custom_dir() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "data"


def find_custom() -> Path | None:
    """The uploaded custom wallpaper, or None."""
    folder = custom_dir()
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob(f"{CUSTOM_STEM}.*")):
        if path.is_file() and path.suffix.lower() in IMAGE_MEDIA:
            return path
    return None


def media_type(path: Path) -> str:
    """Media type for ``path``; Windows' extension-less cache file is a JPEG."""
    return IMAGE_MEDIA.get(path.suffix.lower(), "image/jpeg")


def _usable(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        return path if path.is_file() and path.stat().st_size > 0 else None
    except OSError:  # unreadable file = no wallpaper; the page paints its fallback
        return None


def _windows_wallpaper() -> Path | None:
    try:
        import ctypes

        spi_getdeskwallpaper = 0x0073
        buffer = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
            spi_getdeskwallpaper, len(buffer), buffer, 0
        ):
            found = _usable(Path(buffer.value)) if buffer.value else None
            if found is not None and found.suffix.lower() in IMAGE_MEDIA:
                return found
    except Exception as exc:  # noqa: BLE001 - no wallpaper is a normal answer
        from loguru import logger

        logger.debug("Desktop wallpaper lookup failed: {}", exc)
    # Slideshows and Spotlight leave only the cached copy Windows paints from.
    appdata = os.environ.get("APPDATA")
    if appdata:
        return _usable(Path(appdata) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper")
    return None


def _run(argv: list[str]) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, text=True, timeout=3, check=False
        )
    except (OSError, subprocess.SubprocessError):  # tool missing = no answer, not an error
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _from_uri(value: str) -> Path | None:
    value = value.strip().strip("'\"")
    if not value:
        return None
    if value.startswith("file://"):
        value = url2pathname(urlparse(value).path)
    return _usable(Path(value))


def _macos_wallpaper() -> Path | None:
    out = _run([
        "osascript", "-e",
        'tell application "System Events" to get picture of current desktop',
    ])
    return _usable(Path(out)) if out else None


def _linux_wallpaper() -> Path | None:
    for key in ("picture-uri-dark", "picture-uri"):
        found = _from_uri(_run(["gsettings", "get", "org.gnome.desktop.background", key]))
        if found is not None:
            return found
    return None


def desktop_wallpaper() -> Path | None:
    """Path of the operating system's current desktop wallpaper, or None."""
    if sys.platform == "win32":
        return _windows_wallpaper()
    if sys.platform == "darwin":
        return _macos_wallpaper()
    return _linux_wallpaper()


def current() -> tuple[str, Path | None]:
    """``(source, path)``: the custom picture first, then the desktop one."""
    custom = find_custom()
    if custom is not None:
        return "custom", custom
    found = desktop_wallpaper()
    return ("desktop", found) if found is not None else ("none", None)
