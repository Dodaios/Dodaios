"""Augment the process PATH with well-known CLI install locations.

GUI-launched processes do not inherit the user's shell PATH: on macOS an app
started from Finder/Dock/launchd gets the minimal ``/usr/bin:/bin:/usr/sbin:
/sbin`` (no Homebrew, no npm-global, no ``~/.local/bin``), and on Windows a
fresh installer can update only the registry PATH or place a binary in an app-
specific user directory. Already-running processes see neither change. Every
``shutil.which``-based CLI probe (claude / codex / agy / gemini / node / npm,
the CLI-tools catalog prober, worker spawns) then reports a perfectly-installed
binary as "not installed" — the 2026-07-18 Mac-test-machine symptom: Claude
Code installed via the shell, the desktop app insisting it is missing.

``ensure_cli_paths()`` appends the well-known, actually-existing install dirs
to ``os.environ["PATH"]``. Existing entries keep priority — only *missing*
dirs are appended, so a user-managed PATH always wins and the call is
idempotent. Pure ``stat()`` probes, no subprocess: boot-budget-safe (AP-26).

The PATH it writes stays inside what the platform can spawn with: see
``_WINDOWS_PATH_BUDGET``. A PATH that arrives too long is shortened the same
way, so an app started from such an environment can still launch programs.

Cross-platform per CLOUD.md Rule #1: the candidate list covers macOS
(Intel + Apple Silicon Homebrew), Linux (incl. headless), and Windows; a dir
that does not exist on this host is simply skipped.
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

# Windows builds one search path per ``CreateProcess`` from the application
# directory, the system directories and the CALLER's ``PATH``, in a string that
# holds 32,767 characters. Past that EVERY spawn of the process fails with
# ``WinError 8`` ("not enough memory resources"), whatever is being started and
# whatever environment the child is given; a child handed such a PATH dies
# during its own start-up instead. The budget leaves room for a long
# application directory and for the folder a caller adds to one child's PATH.
# (BUG-233)
_WINDOWS_PATH_BUDGET = 31_000

# The last over-budget request that changed nothing. Callers ask on every
# status probe, and re-probing several hundred folders each time to reach the
# same answer would cost more than the lookup it serves.
_settled_overflow: tuple[str, tuple[str, ...]] | None = None


def _posix_candidates() -> list[str]:
    home = Path.home()
    dirs: list[str] = [
        # Homebrew (Intel Macs + Linuxbrew default) and the npm default prefix.
        "/usr/local/bin",
        # Homebrew on Apple Silicon.
        "/opt/homebrew/bin",
        # MacPorts.
        "/opt/local/bin",
        # Native installers (Claude Code, pipx, uv) and the XDG user bin dir.
        str(home / ".local" / "bin"),
        # Official Grok Build installer (install.sh) may drop ``grok`` here.
        str(home / ".grok" / "bin"),
        # Claude Code's npm-local migration target (`claude install`).
        str(home / ".claude" / "local"),
        # A user-configured npm prefix (`npm config set prefix ~/.npm-global`).
        str(home / ".npm-global" / "bin"),
        # Volta pins a single stable shim dir.
        str(home / ".volta" / "bin"),
        # OpenClaw's user-space installer (install-cli.sh) and its default prefix.
        str(home / ".openclaw" / "bin"),
    ]
    if sys.platform.startswith("linux"):
        dirs.append("/snap/bin")
    # nvm/fnm keep per-node-version bin dirs; a GUI process sees none of them
    # because the shims live in shell init files. Newest-first is best-effort
    # (lexicographic, same trade-off as jarvis.google_cli.resolver) — for a
    # global CLI install ANY hit beats "not installed".
    for pattern in (
        str(home / ".nvm" / "versions" / "node" / "*" / "bin"),
        str(
            home / ".local" / "share" / "fnm" / "node-versions" / "*"
            / "installation" / "bin"
        ),
    ):
        dirs.extend(sorted(glob.glob(pattern), reverse=True))
    return dirs


def _windows_candidates() -> list[str]:
    home = Path.home()
    dirs: list[str] = []
    node_dirs: set[str] = set()
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        program_files = os.environ.get(var)
        if not program_files:
            continue
        # The official Node.js Windows installer writes this directory to the
        # machine PATH. A running desktop process keeps its old PATH, though,
        # so a freshly installed npm Codex shim is found while its `node.exe`
        # runtime is not. ProgramW6432 keeps the 64-bit install visible even
        # when Jarvis itself runs as a 32-bit process.
        candidate = os.path.join(program_files, "nodejs")
        key = os.path.normcase(os.path.normpath(candidate))
        if key not in node_dirs:
            node_dirs.add(key)
            dirs.append(candidate)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        # User-scoped Node installers commonly use this UAC-free location.
        dirs.append(os.path.join(local, "Programs", "nodejs"))
        # The official Hermes Agent installer (install.ps1) stages its
        # launchers here and registers the folder on the registry PATH only.
        dirs.append(os.path.join(local, "hermes", "bin"))
        # The official Antigravity PowerShell/CMD installer uses this directory.
        dirs.append(os.path.join(local, "agy", "bin"))
        # winget's shim dir lands on the *registry* PATH only — a running
        # process (and every subprocess it spawns) misses fresh installs.
        dirs.append(os.path.join(local, "Microsoft", "WinGet", "Links"))
        # Ollama's per-user installer (OllamaSetup.exe / winget) writes here
        # and appends it to the registry PATH only — a Jarvis that just
        # installed Ollama would otherwise not find the binary it installed.
        dirs.append(os.path.join(local, "Programs", "Ollama"))
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(os.path.join(appdata, "npm"))
    # Claude Code's NATIVE installer (install.ps1) drops the binary into
    # %USERPROFILE%\.local\bin, and `claude install` migrates npm setups to
    # %USERPROFILE%\.claude\local — neither is on a default Windows PATH, so
    # the desktop app reported a working terminal `claude` as "not installed"
    # (Windows test-machine report 2026-07-18; same class as the Mac case in
    # the module docstring).
    dirs.append(str(home / ".local" / "bin"))
    dirs.append(str(home / ".claude" / "local"))
    # Official Grok Build installer (install.ps1) drops ``grok`` next to
    # other native CLIs; some builds also use a dedicated bin under GROK_HOME.
    dirs.append(str(home / ".grok" / "bin"))
    if local:
        dirs.append(os.path.join(local, "grok", "bin"))
    return dirs


def _registered_agent_dirs() -> list[str]:
    """Install dirs contributed by registered coding-CLI entries.

    A CLI whose own installer drops the binary somewhere the platform lists are
    not going to guess (``~/.local/bin`` on a GUI-launched macOS process, for
    one) says so on its registry entry rather than earning a line in the
    platform tables here — which would put product knowledge in a module that
    has no business holding any.

    Failures are swallowed: PATH augmentation is best-effort by contract, and a
    registry that cannot be imported must not take the whole lookup with it.
    """
    try:
        from jarvis.workspace import agents as workspace_agents

        return [
            os.path.expanduser(d)
            for agent in workspace_agents.coding_agents()
            for d in agent.extra_path_dirs
        ]
    except Exception:  # noqa: BLE001 - see docstring
        return []


def candidate_dirs() -> list[str]:
    """The platform's well-known CLI install dirs (existing or not)."""
    base = _windows_candidates() if sys.platform == "win32" else _posix_candidates()
    return [*base, *_registered_agent_dirs()]


def _path_budget() -> int | None:
    """The longest ``PATH`` this platform can spawn with; ``None`` if unbounded."""
    return _WINDOWS_PATH_BUDGET if sys.platform == "win32" else None


def _entry_key(entry: str) -> str:
    return os.path.normcase(os.path.normpath(entry))


def _joined_length(entries: list[str]) -> int:
    return sum(len(entry) for entry in entries) + max(len(entries) - 1, 0)


def fit_path_entries(entries: list[str], budget: int) -> list[str]:
    """Shorten ``entries`` until their joined ``PATH`` fits ``budget``.

    Gives up the cheapest thing first: empty and repeated entries, then folders
    that do not exist, and only then real folders from the end, where the
    lowest-priority ones sit. A list that already fits comes back unchanged, so
    a healthy PATH is never rewritten.
    """
    if _joined_length(entries) <= budget:
        return entries
    seen: set[str] = set()
    unique: list[str] = []
    for entry in entries:
        key = _entry_key(entry) if entry else ""
        if not entry or key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    if _joined_length(unique) <= budget:
        return unique
    existing: list[str] = []
    for entry in unique:
        try:
            if os.path.isdir(entry):
                existing.append(entry)
        except OSError:  # an unreadable entry cannot be searched either
            continue
    while existing and _joined_length(existing) > budget:
        existing.pop()
    return existing


def _store_path(current: str, added: list[str]) -> list[str]:
    """Write ``current`` plus ``added`` to ``PATH``; return what of ``added`` got in.

    Inside the platform's budget this is a plain append. Past it the PATH is
    shortened with :func:`fit_path_entries` first, which is also how a PATH
    that was already too long when the app started gets repaired.
    """
    global _settled_overflow

    entries = current.split(os.pathsep) if current else []
    budget = _path_budget()
    if budget is None or _joined_length(entries + added) <= budget:
        if added:
            os.environ["PATH"] = os.pathsep.join([current, *added] if current else added)
        return added
    request = (current, tuple(added))
    if request == _settled_overflow:
        return []
    fitted = fit_path_entries(entries + added, budget)
    kept_keys = {_entry_key(entry) for entry in fitted}
    kept = [entry for entry in added if _entry_key(entry) in kept_keys]
    value = os.pathsep.join(fitted)
    if value == current:
        _settled_overflow = request
    else:
        os.environ["PATH"] = value
    log.warning(
        "PATH is %d characters long, over the %d-character budget that keeps "
        "Windows able to start programs: kept %d of %d entries (repeated and "
        "missing folders go first), %d of %d CLI install dir(s) added",
        len(current),
        budget,
        len(fitted),
        len(entries) + len(added),
        len(kept),
        len(added),
    )
    return kept


def ensure_cli_paths() -> list[str]:
    """Append missing well-known CLI dirs to ``PATH``; return what was added.

    Idempotent: dirs already on PATH (case-normalized) are never re-added, so
    repeated calls — and a PATH the user already curated — are both safe.
    """
    current = os.environ.get("PATH", "")
    seen = {
        os.path.normcase(os.path.normpath(p))
        for p in current.split(os.pathsep)
        if p
    }
    added: list[str] = []
    for cand in candidate_dirs():
        try:
            if not os.path.isdir(cand):
                continue
        except OSError:
            continue
        key = os.path.normcase(os.path.normpath(cand))
        if key in seen:
            continue
        seen.add(key)
        added.append(cand)
    added = _store_path(current, added)
    if added:
        log.info("PATH augmented with %d CLI install dir(s): %s", len(added), added)
    return added


def _registry_paths() -> list[str]:
    """The user's and the machine's persistent PATH (Windows registry)."""
    import winreg

    values: list[str] = []
    for hive, key_path in (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    ):
        try:
            with winreg.OpenKey(hive, key_path, 0, winreg.KEY_QUERY_VALUE) as key:
                value, _kind = winreg.QueryValueEx(key, "Path")
        except OSError:  # no such value or no access: that hive adds nothing
            continue
        values.append(str(value))
    return values


def refresh_from_persistent_path(
    read: Callable[[], list[str]] | None = None,
    *,
    skip: Callable[[str], bool] | None = None,
) -> list[str]:
    """Append entries an installer just added to the persistent PATH.

    An installer run by the app (Hermes, OpenClaw, Node.js) registers its
    folder in the user's or the machine's PATH, which a running process never
    sees. Windows only (POSIX installers edit shell profiles, which
    ``ensure_cli_paths`` covers with the folders they use); ``read`` is
    injectable for tests. Existing entries keep priority; ``skip`` drops
    entries that must never be used. Returns the appended folders.
    """
    if read is None:
        if sys.platform != "win32":
            return []
        read = _registry_paths
    current = os.environ.get("PATH", "")
    seen = {os.path.normcase(os.path.normpath(p)) for p in current.split(os.pathsep) if p}
    added: list[str] = []
    for value in read():
        for raw in value.split(";"):
            entry = os.path.expandvars(raw.strip().strip('"'))
            if not entry or (skip is not None and skip(entry)):
                continue
            key = os.path.normcase(os.path.normpath(entry))
            if key in seen or not os.path.isdir(entry):
                continue
            seen.add(key)
            added.append(entry)
    added = _store_path(current, added)
    if added:
        log.info("PATH refreshed with %d folder(s) from the persistent PATH", len(added))
    return added


def resolve_node_executable() -> str | None:
    """Return an absolute Node.js executable, including stale-GUI-PATH hosts."""
    ensure_cli_paths()
    found = shutil.which("node") or shutil.which("node.exe")
    if found:
        return found
    if sys.platform == "win32":
        for directory in _windows_candidates():
            candidate = Path(directory) / "node.exe"
            try:
                if candidate.is_file():
                    return str(candidate)
            except OSError:
                continue
    return None


__all__ = [
    "candidate_dirs",
    "ensure_cli_paths",
    "fit_path_entries",
    "refresh_from_persistent_path",
    "resolve_node_executable",
]
