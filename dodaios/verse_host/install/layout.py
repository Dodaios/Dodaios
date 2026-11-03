"""Where an installed Verse lives and which version runs (WP22.5).

The Verse is an optional download (docs/verse/unreal/README.md, Delivery):
the installer, a plain ``git clone`` and app updates never carry it. Once the
user asks for it, it lives in the per-user data folder, outside the app:

    <root>/current.json                   which version runs, and the one before
    <root>/versions/<version>/            one complete, verified payload each
    <root>/versions/<v>/verse-tree.json   size + SHA-256 of every file of it
    <root>/downloads/                     resumable ``.part`` downloads

``<root>`` is ``DODAIOS_VERSE_ROOT`` when set, else ``<user data>/verse``
(``%LOCALAPPDATA%\\Dodaios\\verse`` on Windows). No ``current.json`` means
the Verse is not installed.
"""

from __future__ import annotations

import json
import os
import platform as platform_module
import re
import sys
from pathlib import Path
from typing import Any

__all__ = [
    "VERSE_CURRENT_FILE",
    "VERSE_CURRENT_SCHEMA",
    "VERSE_PLATFORMS",
    "VERSE_ROOT_ENV",
    "VerseInstallError",
    "check_version",
    "default_root",
    "read_current",
    "verse_platform",
    "version_dir",
    "version_key",
    "write_current",
]

VERSE_CURRENT_SCHEMA = "verse.current/1"
VERSE_CURRENT_FILE = "current.json"
VERSE_ROOT_ENV = "DODAIOS_VERSE_ROOT"

#: ``(os, cpu)`` -> the Unreal platform name of the package.
VERSE_PLATFORMS: dict[tuple[str, str], str] = {
    ("windows", "x64"): "Win64",
    ("linux", "x64"): "Linux",
}
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class VerseInstallError(RuntimeError):
    """A Verse download, install, delta, rollback or removal failed.

    The message is user-facing: the launcher card shows it.
    """


def check_version(value: Any) -> str:
    """``MAJOR.MINOR.PATCH`` (a leading ``v`` is dropped), else :class:`VerseInstallError`."""
    version = str(value or "").strip().removeprefix("v")
    if not _VERSION.match(version):
        raise VerseInstallError(f"{value!r} is not a Verse version (want MAJOR.MINOR.PATCH)")
    return version


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in check_version(version).split("."))


def verse_platform(platform_name: str | None = None, machine: str | None = None) -> str | None:
    """``Win64`` / ``Linux`` for this machine, ``None`` where no Verse ships (macOS, ARM)."""
    active = (sys.platform if platform_name is None else platform_name).lower()
    cpu = (platform_module.machine() if machine is None else machine).strip().lower()
    if active.startswith("win"):
        os_name = "windows"
    elif active.startswith("linux"):
        os_name = "linux"
    else:
        os_name = ""
    arch = "x64" if cpu in {"amd64", "x86_64", "x64"} else ""
    return VERSE_PLATFORMS.get((os_name, arch))


def default_root(env: dict[str, str] | None = None) -> Path:
    """``DODAIOS_VERSE_ROOT``, else ``<user data folder>/verse``."""
    environ = os.environ if env is None else env
    override = environ.get(VERSE_ROOT_ENV, "").strip()
    if override:
        return Path(override)
    # Imported late: the app's path rules read the environment once per process.
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "verse"


def version_dir(root: Path, version: str) -> Path:
    return root / "versions" / check_version(version)


def read_current(root: Path) -> dict[str, Any] | None:
    """``current.json`` of ``root``: the running version and the previous one."""
    try:
        data = json.loads((root / VERSE_CURRENT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # no or unreadable pointer means nothing installed
        return None
    if not isinstance(data, dict) or data.get("schema") != VERSE_CURRENT_SCHEMA:
        return None
    try:
        check_version(data.get("version"))
    except VerseInstallError:  # a pointer naming no version means nothing installed
        return None
    return data


def write_current(
    root: Path, version: str, previous: str | None, platform: str, *, entry: str | None
) -> None:
    """Move ``current.json`` atomically (write a sibling, then replace)."""
    data = {
        "schema": VERSE_CURRENT_SCHEMA,
        "version": version,
        "previous": previous,
        "platform": platform,
        "entry": entry,
    }
    tmp = root / f".{VERSE_CURRENT_FILE}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, root / VERSE_CURRENT_FILE)
