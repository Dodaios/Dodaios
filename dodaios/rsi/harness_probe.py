"""Which coding CLI, in which version, a turn is about to run on.

Coding CLIs update themselves, often daily, so "the version" is only true for
one binary on disk. The answer here is cached by that binary's fingerprint
(resolved path, modification time, size): an unchanged binary costs one
``stat``, a replaced one is read again. The version is taken from the cheapest
honest source: the resolved path when the installer names the folder after the
version, the package manifest beside a script, and only then one ``--version``
call.

Blocking (a ``stat``, at most one short process): call it off the event loop.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

log = logging.getLogger(__name__)

__all__ = ["Harness", "for_runner", "parse_version", "version_line", "version_of"]

_VERSION = re.compile(r"(?<![\w.])v?(\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?)(?![\w])")
_VERSION_TIMEOUT_S: Final[float] = 6.0

Fingerprint = tuple[str, int, int]

_cache: dict[Fingerprint, str] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class Harness:
    """The CLI behind a runner: its name, full version and version line."""

    name: str
    version: str
    line: str


def parse_version(text: str) -> str:
    """The first ``x.y`` or ``x.y.z`` in ``text``, or ``""``."""
    match = _VERSION.search(text or "")
    return match.group(1) if match else ""


def version_line(version: str) -> str:
    """``major.minor`` of a version: what stays the same across patch releases."""
    parts = re.split(r"[.\-+]", version or "")
    return ".".join(parts[:2]) if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]) else ""


def _fingerprint(binary: str) -> Fingerprint | None:
    try:
        resolved = Path(binary).resolve()
        stat = resolved.stat()
    except OSError:  # the binary is gone or unreadable: nothing to fingerprint
        return None
    return str(resolved), stat.st_mtime_ns, stat.st_size


def _from_path(resolved: Path) -> str:
    """A version the installer wrote into the path (``…/versions/2.1.330``)."""
    for part in (resolved.name, resolved.parent.name):
        if _VERSION.fullmatch(part):
            return parse_version(part)
    return ""


def _from_manifest(resolved: Path) -> str:
    """The version of the package a script belongs to (``package.json`` beside it)."""
    for folder in (resolved.parent, resolved.parent.parent, resolved.parent.parent.parent):
        manifest = folder / "package.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):  # an unreadable manifest names no version
            continue
        version = str(data.get("version") or "") if isinstance(data, dict) else ""
        if version:
            return parse_version(version)
    return ""


def _run_version(binary: str) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - the resolved CLI binary, a fixed flag
            [binary, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_VERSION_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.info("harness probe: %s --version did not answer (%s)", binary, exc)
        return ""
    return parse_version((done.stdout or "") + "\n" + (done.stderr or ""))


def version_of(binary: str, *, run: Callable[[str], str] = _run_version) -> str:
    """The version of the CLI at ``binary``; ``""`` when it cannot be read."""
    stamp = _fingerprint(binary)
    if stamp is None:
        return ""
    with _cache_lock:
        known = _cache.get(stamp)
    if known is not None:
        return known
    resolved = Path(stamp[0])
    version = _from_path(resolved) or _from_manifest(resolved) or run(binary)
    with _cache_lock:
        # An unreadable version is not cached: the next turn asks again.
        if version:
            _cache[stamp] = version
    return version


def _binary_for(runner: str) -> str:
    from dodaios.agent_chat import runner_cli

    try:
        return runner_cli._which(*runner_cli.CLI_BINARIES.get(runner, ())) or ""
    except Exception:  # noqa: BLE001 - an unresolvable CLI simply has no version
        log.debug("harness probe: %s did not resolve", runner, exc_info=True)
        return ""


def for_runner(runner: str, *, binary_of: Callable[[str], str] = _binary_for) -> Harness:
    """The harness a turn on ``runner`` starts now (name only when unresolved)."""
    binary = binary_of(runner) if runner else ""
    version = version_of(binary) if binary else ""
    return Harness(name=runner or "", version=version, line=version_line(version))
