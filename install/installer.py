"""Dodaios Stage-2 installer.

The Stage-1 shell bootstraps a venv (an up-to-date pip and ``packaging``) and
then ``exec``s this script with the venv's Python. From here we own the full
install lifecycle in Python, where it is portable and testable. It needs
nothing beyond the standard library and this checkout until phase 4 has run;
the terminal presentation lives in ``dodaios/setup/install_ui.py``.

The installer is fully NON-INTERACTIVE: it downloads and prepares everything,
explains each step in one line, and launches the app as its LAST action. All
setup questions (language, wake word, API keys, Terms) live in the app's
one-time first-launch onboarding — never in this terminal.

The user-visible journey is ONE six-phase sequence spanning both stages: the
Stage-1 shell prints phases 1-3 (prerequisites, fetch, venv), this script
continues with 4-6. Keep the numbering in sync with install.sh / install.ps1.

Phases owned here:
    4/6 Dependencies — editable install + runtime deps via pip. Desktop hosts
        (Windows/macOS/Linux, or ``--with-desktop``) get the ``[full]`` extras;
        headless keeps the torch-free base floor.
    5/6 Voice models — prefetch everything the config needs (``python -m
        jarvis --prefetch``) + verify what actually landed on disk.
    6/6 Finish & launch — best-effort worker CLI (npm) + native desktop-shell
        registration + UI-bundle integrity check, then the flat summary, then
        launch the Desktop App / headless server as the LAST action unless
        ``--no-launch``.

Environment variables (any can be set before re-invoking the installer):
    JARVIS_INSTALL_DIR      override install location
    JARVIS_INSTALL_NO_PIP   skip the pip install steps

Exit codes:
    0  success
    1  pre-flight failure (Python version, missing files)
    2  pip install failure
    4  desktop registration or launch failure
    5  shipped UI bundle missing or incomplete
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import sysconfig
import time
from collections.abc import Sequence
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parent.parent
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from dodaios.core.branding import (  # noqa: E402 - bootstrap source path above
    CLI_COMMAND_NAME,
    LAUNCHER_ENTRY_NAME,
    LEGACY_DISTRIBUTION_NAMES,
    LINUX_APP_NAME,
    MACOS_APP_NAME,
    MANAGED_INSTALL_MARKERS,
    OFFICIAL_REPO_SLUG,
    PRODUCT_NAME,
)
from dodaios.setup.install_ui import (  # noqa: E402 - bootstrap source path above
    InstallUI,
    format_duration,
)

# AGENTS.md: new CLI modules must use UTF-8 stdout or stick to ASCII. Without
# this, the glyphs break on a cp1252 pipe.
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

#: When this install began. The shell stage hands over its own start so the
#: finale counts the whole run; run on its own, this script starts the clock.
_STARTED_AT = time.time()


# ---------------------------------------------------------------- discovery
def installer_dir() -> Path:
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    return installer_dir().parent


def venv_python() -> Path:
    """Return the Python executable inside the venv."""
    if sys.platform == "win32":
        return repo_root() / ".venv" / "Scripts" / "python.exe"
    return repo_root() / ".venv" / "bin" / "python"


# ---------------------------------------------------------------- presentation
# One look across both stages (dodaios/setup/install_ui.py): gold phase pills,
# a check per finished step with its time on the right, a red rail under a
# failure, a framed card at the end. The Stage-1 twins are the helpers of the
# same names in install.sh and install.ps1; keep the three in visual lockstep.
_UI: InstallUI | None = None


def ui() -> InstallUI:
    """The terminal presentation, decided on first use (after the env is final)."""
    global _UI
    if _UI is None:
        _UI = InstallUI()
    return _UI


def phase(num: str, title: str) -> None:
    """A numbered phase pill (``4/6``), continuing the Stage-1 journey.

    One six-phase journey spans BOTH installer stages: the Stage-1 shell owns
    phases 1-3 (prerequisites, download, Python environment), this script owns
    4-6 — keep the numbering in sync with install.sh / install.ps1.
    """
    step, _, total = num.partition("/")
    ui().phase(int(step), title, int(total or 6))


def ok(text: str, seconds: float | None = None, detail: str = "") -> None:
    ui().ok(text, seconds, detail)


def note(text: str) -> None:
    ui().note(text)


def skip(text: str) -> None:
    ui().skip(text)


def warn(text: str) -> None:
    ui().warn(text)


def fail(
    title: str,
    lines: Sequence[str] = (),
    hints: Sequence[str] = (),
    help_url: str = "",
) -> None:
    ui().fail(title, lines, hints, help_url)


#: The captured tail of the last command ``run_quiet`` saw fail, for the
#: failure block its caller prints once retries are spent.
_LAST_FAILURE_TAIL: list[str] = []


def run_quiet(cmd: list[str], *, label: str, cwd: Path | None = None) -> int:
    """Run a noisy, non-interactive command (pip) behind a clean spinner.

    On a real terminal the raw output is hidden behind a gold spinner with the
    elapsed time, so the transcript stays calm. On a headless/piped run (no
    TTY — a VPS, CI) the output streams through so operators keep a readable
    log. A failure keeps the captured tail for the caller's failure block, so
    the error is never swallowed.
    """
    _LAST_FAILURE_TAIL.clear()
    if ui().caps.motion:
        with ui().spinner(label):
            result = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
        if result.returncode != 0:
            tail = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
            _LAST_FAILURE_TAIL.extend(tail[-20:])
        return result.returncode
    # Non-interactive: stream for the log.
    with ui().spinner(label):
        return subprocess.run(cmd, cwd=cwd).returncode


def run_captured(
    cmd: list[str],
    *,
    label: str,
    cwd: Path | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a captured command behind the standard spinner.

    Like ``run_quiet``, but for callers that PARSE the captured stdout (probe
    verdicts, JSON reports): output stays captured on every host and the full
    ``CompletedProcess`` is returned. The spinner renders only on a real
    terminal so a long step never looks hung; a non-tty run still prints one
    honest "label…" line so logs show what the wait was. Raises ``OSError`` /
    ``TimeoutExpired`` exactly like ``subprocess.run`` — callers keep their
    own handling.
    """
    with ui().spinner(label):
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, env=env,
        )


def run_noted(cmd: list[str], *, label: str, cwd: Path | None = None) -> int:
    """Stream a milestone-printing command as quiet notes above a live spinner.

    For subprocesses whose output is a short series of human-readable
    milestone lines (the voice-model prefetch): each line renders as a note
    the moment it appears, so a multi-minute download shows real, honest
    progress instead of a frozen label or raw column-0 spam (Intel-Mac field
    report 2026-07-16). stderr joins stdout so stray library noise can never
    break the layout. Non-tty hosts get the same lines without the spinner.
    """
    proc = subprocess.Popen(  # noqa: S603 — fixed argv built by the caller, no shell
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    with ui().spinner(label):
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if line:
                note(line)
        return proc.wait()


def is_headless_linux() -> bool:
    """Best-effort: True on a Linux VPS without a display server."""
    return sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )


# ---------------------------------------------------------------- steps
def handed_over_from_shell() -> bool:
    """True when the Stage-1 shell started this run (it hands over its start time)."""
    return bool(os.environ.get("JARVIS_INSTALL_STARTED_AT", "").strip())


def install_started_at() -> float:
    """When this install began: the shell stage's start, else this script's."""
    try:
        started = float(os.environ.get("JARVIS_INSTALL_STARTED_AT", "").strip())
    except ValueError:
        return _STARTED_AT
    return started if 0 < started <= time.time() else _STARTED_AT


def step_preflight() -> None:
    """Sanity re-assert (Stage 1 already gate-keeps) + a quiet environment line."""
    if not handed_over_from_shell():
        # Run on its own (CI, a developer, the in-app updater): the shell's
        # context line never printed, so say where this runs.
        ui().context(
            f"{platform.system()} {platform.release()} ({platform.machine()})"
            f" · Python {sys.version.split()[0]} · {repo_root()}"
        )
    if is_headless_linux():
        skip("Headless Linux detected — installing the server profile")

    if sys.version_info < (3, 11):  # noqa: UP036 - Stage 2 rechecks Stage 1
        fail("Python 3.11+ is required.", [f"This is Python {sys.version.split()[0]}."])
        sys.exit(1)

    if not (repo_root() / "pyproject.toml").exists():
        fail(
            "pyproject.toml not found — installer.py was started outside the checkout.",
            hints=["Run the install command again instead of this file on its own."],
        )
        sys.exit(1)


def write_managed_marker(*, with_desktop: bool) -> bool:
    """Mark this checkout as an installer-managed copy; True once a marker is on disk.

    The in-app "Update Now" button (dodaios/ui/web/update_routes.py) only appears,
    and only ever runs ``git reset --hard``, when this marker is present AND the
    checkout's ``origin`` is the official public repo. A maintainer's dev tree or
    a manual clone never gets this marker, so neither can be self-reset — this is
    the load-bearing safety guard for the whole updater. Best-effort: a marker
    failure must never fail the install (it only disables in-app updates).

    The marker is written under its current name and under every earlier one,
    so an updater from before the rename (a running app that has not restarted
    yet, or a downgrade) still recognises the checkout.
    """
    payload = {
        "managed": True,
        "install_path": str(repo_root()),
        "created_by": "install/installer.py",
        "profile": "full" if with_desktop else "headless",
        "desktop": with_desktop,
    }
    text = json.dumps(payload, indent=2) + "\n"
    written = 0
    for name in MANAGED_INSTALL_MARKERS:
        try:
            (repo_root() / name).write_text(text, encoding="utf-8")
            written += 1
        except OSError as exc:
            warn(f"Could not write the update marker {name} ({exc})")
    if not written:
        note("In-app updates stay off for this install.")
    return bool(written)


def _make_tree_owner_writable(root: Path) -> None:
    """Make a metadata tree removable without following directory symlinks."""

    def _make_writable(path: Path, *, directory: bool) -> None:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            return
        required = stat.S_IRUSR | stat.S_IWUSR
        if directory:
            required |= stat.S_IXUSR
        path.chmod(stat.S_IMODE(mode) | required)

    # A read-only root cannot be traversed reliably on POSIX. In top-down
    # order, each child directory is then made searchable before os.walk
    # descends into it. Adding S_IWUSR also clears the Windows read-only flag.
    _make_writable(root, directory=True)
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        _make_writable(current_path, directory=True)
        for name in directories:
            _make_writable(current_path / name, directory=True)
        for name in files:
            _make_writable(current_path / name, directory=False)


def repair_distribution_metadata(
    *, site_packages: Path | None = None, dry_run: bool = False
) -> bool:
    """Remove torn ``dist-info`` records left by an interrupted old update.

    The legacy updater could run while Python still had the environment open.
    On Windows that sometimes left empty or RECORD-only metadata directories;
    pip then treated the environment as corrupt and could not prove that the
    next update was complete. Removing only invalid metadata is safe: the
    normal install plan immediately restores every distribution still required
    by the selected profile, while obsolete packages remain unregistered.
    """
    if dry_run:
        note("(dry-run) repair interrupted package metadata")
        return True

    root = site_packages or Path(sysconfig.get_path("purelib"))
    try:
        candidates = sorted(root.glob("*.dist-info"))
    except OSError as exc:
        warn(f"Could not inspect the package metadata ({exc})")
        return False

    broken: list[Path] = []
    for candidate in candidates:
        metadata = candidate / "METADATA"
        try:
            content = metadata.read_text(encoding="utf-8", errors="replace")
        except OSError:
            broken.append(candidate)
            continue
        if "Metadata-Version:" not in content or "\nName:" not in f"\n{content}":
            broken.append(candidate)

    for candidate in broken:
        try:
            if candidate.is_symlink():
                candidate.unlink()
            else:
                _make_tree_owner_writable(candidate)
                shutil.rmtree(candidate)
        except OSError as exc:
            warn(f"Could not repair the package metadata at {candidate.name} ({exc})")
            return False

    if broken:
        ok(f"Repaired {len(broken)} interrupted package metadata record(s)")
    return True


def _venv_site_packages() -> list[Path]:
    venv = repo_root() / ".venv"
    if sys.platform == "win32":
        return [venv / "Lib" / "site-packages"]
    return sorted((venv / "lib").glob("python*/site-packages"))


def installed_legacy_distributions() -> tuple[str, ...]:
    """Earlier distribution names this checkout's environment still has installed.

    Read from the metadata on disk, without starting pip: an install made
    before the rename registered the checkout as ``personal-jarvis``.
    """
    found: list[str] = []
    for name in LEGACY_DISTRIBUTION_NAMES:
        stem = name.replace("-", "_")
        patterns = (f"{stem}-*.dist-info", f"{stem}.egg-link", f"{name}.egg-link")
        for site in _venv_site_packages():
            try:
                hit = any(any(site.glob(pattern)) for pattern in patterns)
            except OSError:
                hit = False
            if hit:
                found.append(name)
                break
    return tuple(found)


_PIP_CHECK_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*) \S+ "
    r"(?:has requirement |requires |is not supported on this platform)"
)

# Runs inside the venv's interpreter. For each distribution ``pip check``
# named, it answers whether that distribution is HOST-ONLY: installed outside
# the venv's own site-packages and not part of Dodaios' dependency closure
# (every extra counted, so the closure errs on the large side).
_HOST_ONLY_PROBE = r'''
import json, re, sys
from importlib import metadata
from pathlib import Path
from packaging.requirements import Requirement

def canon(name):
    return re.sub(r"[-_.]+", "-", name).lower()

venv = Path(sys.prefix).resolve()
needed = set()
queue = [("dodaios", None)]
while queue:
    name, extras = queue.pop()
    key = canon(name)
    if key in needed:
        continue
    needed.add(key)
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        continue
    if extras is None:
        extras = set(dist.metadata.get_all("Provides-Extra") or [])
    for raw in dist.requires or []:
        req = Requirement(raw)
        if req.marker is not None and not any(
            req.marker.evaluate({"extra": extra}) for extra in ("", *extras)
        ):
            continue
        queue.append((req.name, set(req.extras)))

verdict = {}
for name in json.loads(sys.argv[1]):
    try:
        where = Path(metadata.distribution(name).locate_file("")).resolve()
    except metadata.PackageNotFoundError:
        verdict[canon(name)] = False
        continue
    inside = where == venv or venv in where.parents
    verdict[canon(name)] = not inside and canon(name) not in needed
print(json.dumps(verdict))
'''


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pip_check_subjects(output: str) -> list[str] | None:
    """The distributions whose requirements ``pip check`` reported as broken.

    ``None`` when a line is not in a known form: an unknown report is never
    waved through.
    """
    subjects: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("WARNING:", "DEPRECATION:")):
            continue
        match = _PIP_CHECK_LINE.match(line)
        if match is None:
            return None
        subjects.append(match.group("name"))
    return subjects


def _host_only_distributions(names: list[str]) -> dict[str, bool] | None:
    """Ask the venv's interpreter which of ``names`` are host-only (see the probe)."""
    try:
        result = subprocess.run(
            [str(venv_python()), "-c", _HOST_ONLY_PROBE, json.dumps(names)],
            cwd=repo_root(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        verdict = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return verdict if isinstance(verdict, dict) else None


def dependency_check_passes(cmd: list[str], *, label: str) -> bool:
    """Run ``pip check``; tolerate conflicts that live only in host packages.

    A Linux desktop venv links the host's site-packages (install.sh, H-01), so
    ``pip check`` also judges packages the host installed for other tools. A
    broken requirement of such a package cannot affect Dodaios as long as the
    package lives outside the venv and Dodaios does not depend on it, yet it
    stopped whole updates (#1018). Those conflicts become a warning. Anything
    else, or a report this cannot read, stops the install as before.
    """
    started = time.monotonic()
    try:
        result = run_captured(cmd, label=_sentence(label), cwd=repo_root(), timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"{_sentence(label)} could not run", [str(exc)])
        return False
    if result.returncode == 0:
        ok(_sentence(label), time.monotonic() - started)
        return True
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    subjects = _pip_check_subjects(output)
    verdict = _host_only_distributions(subjects) if subjects else None
    blocking = (
        None if verdict is None or subjects is None
        else [name for name in subjects if not verdict.get(_canonical_name(name))]
    )
    lines = output.splitlines()[-40:]
    if blocking is None or blocking:
        fail(f"{_sentence(label)} found broken requirements", lines)
        return False
    warn("A warning only: packages installed outside Dodaios' environment have broken")
    note("requirements. Dodaios does not use them, so the install goes on:")
    for line in lines:
        note(f"  {line}")
    return True


#: Pause before the one automatic retry of a failed ``pip install``. A dropped
#: connection or a wheel an antivirus scanner still holds open (a Windows
#: "Access is denied" / "used by another process" on a fresh file) usually
#: clears within seconds; a real failure fails the same way twice.
PIP_RETRY_PAUSE_S = 4.0

#: Where the install troubleshooting lives (public docs).
INSTALL_HELP_URL = (
    "https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/"
    "install-dodaios.md#troubleshooting"
)


def _sentence(text: str) -> str:
    """``text`` as it starts a line on screen: with a capital letter."""
    return text[:1].upper() + text[1:]


def _retry_pip_install(cmd: list[str], *, label: str) -> int:
    """Run a failed ``pip install`` once more. ``pip install`` is idempotent."""
    note(
        "A dropped connection or a file briefly locked by antivirus often "
        "clears up, so: retrying once."
    )
    time.sleep(PIP_RETRY_PAUSE_S)
    return run_quiet(cmd, label=f"{label} (retry)", cwd=repo_root())


def pip_failure_hints() -> list[str]:
    """What usually stops a dependency step, as steps to try."""
    hints = ["Check your connection and free disk space, then run the installer again."]
    if sys.platform == "win32":
        hints.append(
            "If your antivirus quarantined or blocked a file, restore it and allow "
            "the Dodaios folder, then run the installer again."
        )
    return hints


def print_pip_failure_help() -> None:
    """Say what usually stops this step and where the fixes are written down."""
    ui().hints(pip_failure_hints(), INSTALL_HELP_URL)


def step_pip_install(*, with_desktop: bool, with_voice_local: bool, dry_run: bool) -> None:
    from scripts.native_crypto_index import pip_options

    phase("4/6", "Dependencies")
    pip = [str(venv_python()), "-m", "pip"]

    # ``requirements.txt`` is the Wave 6 hash-pinned, PLATFORM-UNIVERSAL lockfile
    # generated from ``pyproject.toml [project].dependencies`` (mirrored by
    # ``requirements.in``) using ``uv pip compile --universal --generate-hashes``
    # and the scoped native-crypto config. Per-OS markers let ONE lockfile
    # installs on Windows/macOS/Linux (each OS pulls only its wheels). Every
    # package-pinning line carries ``--hash=sha256:...`` so an attacker who compromises a PyPI
    # mirror cannot swap out a transitive dependency without invalidating
    # the lockfile signature published in the GitHub Release. Both profiles
    # install it with ``--require-hashes`` so unhashed/mismatched entries
    # fail-closed. The lockfile holds only the base dependencies, so the
    # headless profile stays on the torch-free base floor. Headless used to
    # resolve ``pip install -e .`` from the open ``pyproject.toml`` ranges
    # instead, and on a Linux venv that links the host's site-packages pip then
    # took any host copy as "already satisfied", so the server ran on host
    # versions (#456). Exact pins install venv-local copies unless the host has
    # the very same version. See ``docs/supply-chain/threat-model.md`` §11.
    lockfile = pip + ["install", "--require-hashes", "-r", "requirements.txt"]
    if with_desktop:
        runtime_step = ("runtime dependencies (hash-pinned lockfile)", lockfile)
    else:
        runtime_step = ("runtime dependencies (cloud-first base, hash-pinned)", lockfile)

    plans: list[tuple[str, list[str]]] = []
    # The checkout used to be installed under the distribution's earlier name.
    # Both names own the same files, and uninstalling the earlier one AFTER the
    # current one is installed would delete files the current one needs, so it
    # goes first. Only the environment's record of it goes: the checkout stays.
    legacy = installed_legacy_distributions()
    if legacy:
        plans.append((
            f"retire the earlier package name ({', '.join(legacy)})",
            pip + ["uninstall", "-y", *legacy],
        ))
    plans += [
        ("editable install (entry points)", pip + ["install", "-e", ".", "--no-deps"]),
        runtime_step,
    ]
    if with_desktop:
        # One official install profile (design 2026-07-07): desktop + telephony
        # + channels + local voice in one shot. Platform markers skip whatever
        # this OS cannot use. --headless keeps the torch-free base floor.
        # ``with_voice_local`` is a deprecated no-op: [full] already carries it.
        plans.append(("full profile (desktop, telephony, channels, local voice)",
                      pip + ["install", *pip_options(), "-e", ".[full]"]))
    plans.append(("dependency consistency check", pip + ["check"]))

    if not repair_distribution_metadata(dry_run=dry_run):
        fail(
            "Package metadata repair failed",
            hints=["Close Dodaios and anything using its folder, then run the installer again."],
            help_url=INSTALL_HELP_URL,
        )
        ui().stopped("The install stopped here. Nothing was launched.")
        sys.exit(2)

    if dry_run:
        for label, cmd in plans:
            note(f"(dry-run) {label}: {' '.join(cmd)}")
        return

    for label, cmd in plans:
        if cmd[len(pip):] == ["check"]:
            rc = 0 if dependency_check_passes(cmd, label=label) else 1
            if rc == 0:
                continue
        else:
            started = time.monotonic()
            rc = run_quiet(cmd, label=_sentence(label), cwd=repo_root())
            if rc != 0 and cmd[len(pip)] == "install":
                rc = _retry_pip_install(cmd, label=_sentence(label))
            if rc == 0:
                ok(_sentence(label), time.monotonic() - started)
                continue
            fail(_sentence(label), list(_LAST_FAILURE_TAIL))
        # The advertised desktop install is the [full] profile. Continuing
        # after that profile fails would advertise a ready app without the
        # microphone, macOS bridge, or local-voice dependencies it needs.
        print_pip_failure_help()
        ui().stopped(f"{_sentence(label)} failed, so the install stopped here.")
        sys.exit(2)


def is_update_run() -> bool:
    """True when this checkout was already installer-managed (re-run = update).

    A marker under any of its names counts: an install made before the rename
    carries only the earlier one.
    """
    return any((repo_root() / name).exists() for name in MANAGED_INSTALL_MARKERS)


def step_models(*, full_profile: bool, dry_run: bool) -> None:
    phase("5/6", "Voice models")
    note("Everything the voice pipeline needs is fetched now, so the first launch")
    note("is ready at once and nothing downloads at startup.")
    cmd = [str(venv_python()), "-m", "dodaios", "--prefetch"]
    if full_profile:
        # Onboarding has not selected a language yet. Cache every supported
        # wake language so English, German, and Spanish are all ready on the
        # first launch; the internal headless/base path stays intentionally small.
        cmd.append("--prefetch-all-wake-languages")
    if dry_run:
        note(f"(dry-run) {' '.join(cmd)}")
        return
    # The download step's exit code alone is not proof: a skipped or cache-served
    # model can still leave "done" looking complete. So don't stop at rc — VERIFY
    # what actually landed on disk and print a per-model truth. Read-only +
    # best-effort: this never bricks the install.
    # run_noted, not run_quiet: with the HF progress bars silenced inside the
    # prefetch itself, its output is a handful of milestone lines ("downloading
    # wake model … ~40 MB", "speech model 'base': ready") — streaming them as
    # notes above the spinner is the honest progress indicator a multi-minute
    # download needs; a static label just reads as a hang.
    started = time.monotonic()
    run_noted(
        cmd,
        label="Downloading voice models (the long step, a few hundred MB)",
        cwd=repo_root(),
    )
    verify_models(full_profile=full_profile, started=started)


def verify_models(*, full_profile: bool = False, started: float | None = None) -> None:
    """Print a per-model truth: what is on disk, what is pending, what is missing.

    Runs the read-only report inside the venv's Python — the interpreter that
    will actually run Dodaios — so it sees the real installed packages and model
    caches. Exit 0 = every REQUIRED model present; non-zero = a required model is
    missing. A probe failure degrades to an honest note, never a failed install.
    """
    # One JSON object per model, so each one draws as its own step line with
    # its explanation in a quiet second line.
    probe = (
        "import dataclasses, json\n"
        "from dodaios.setup.model_report import voice_model_report, report_complete\n"
        f"items = voice_model_report(full_profile={full_profile!r})\n"
        "for item in items: print(json.dumps(dataclasses.asdict(item)))\n"
        "import sys; sys.exit(0 if report_complete(items) else 3)\n"
    )
    unverified = "Could not verify the voice models; they are checked again on first launch."
    try:
        result = run_captured(
            [str(venv_python()), "-c", probe], cwd=repo_root(),
            label="Checking the voice models", timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        warn(unverified)
        return
    produced = False
    for raw in (result.stdout or "").splitlines():
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        produced = True
        label, detail = str(item.get("label", "")), str(item.get("detail", ""))
        if item.get("present"):
            ok(label, detail=detail)
            continue
        if item.get("required"):
            fail(label)
        else:
            skip(label)
        if detail:
            note(detail)
    if not produced:
        warn(unverified)
        for tail in (result.stderr or "").strip().splitlines()[-5:]:
            note(tail)
        return
    took = time.monotonic() - started if started is not None else None
    if result.returncode == 0:
        profile = "full voice profile" if full_profile else "default voice path"
        ok(f"Everything the {profile} needs is present", took)
    else:
        warn("Some required voice models are missing: run the installer again or")
        note("check your connection. The app also fetches them on first use.")


def step_worker_cli(*, dry_run: bool) -> None:
    """Finish & launch sub-step: the coding-agent worker CLI (needs Node.js)."""
    if dry_run:
        note("(dry-run) npm i -g @anthropic-ai/claude-code")
        return
    probe = (
        "from dodaios.setup.dependencies import check_claude_cli, check_npm, install_claude_cli\n"
        "import sys\n"
        "if check_claude_cli().present:\n"
        "    print('present'); sys.exit(0)\n"
        "if not check_npm().present:\n"
        "    print('no-npm'); sys.exit(0)\n"
        "installed, _status = install_claude_cli()\n"
        "print('installed' if installed else 'failed')\n"
    )
    try:
        result = run_captured(
            [str(venv_python()), "-c", probe], cwd=repo_root(),
            label="Setting up the Dodaios-Agent worker CLI (npm download)", timeout=600,
        )
        stdout = (result.stdout or "").strip()
        verdict = stdout.splitlines()[-1] if stdout else "failed"
    except (OSError, subprocess.TimeoutExpired):
        verdict = "failed"
    if verdict == "present":
        ok("Dodaios-Agent worker CLI already installed")
    elif verdict == "installed":
        ok("Dodaios-Agent worker CLI installed (npm)")
    elif verdict == "no-npm":
        skip("Node.js/npm not found — the Dodaios-Agent worker CLI can be added in the app")
    else:
        skip("Dodaios-Agent worker CLI did not install — it can be added in the app")


def _write_desktop_integration_log(result: object) -> Path | None:
    """Persist the registration subprocess output; return the path or None."""
    log_path = repo_root() / "data" / "logs" / "install-desktop-integration.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "--- stdout ---\n"
            + (getattr(result, "stdout", "") or "")
            + "\n--- stderr ---\n"
            + (getattr(result, "stderr", "") or "")
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        return None
    return log_path


_SPOTLIGHT_PROBE = (
    "from dodaios.setup.macos_app_bundle import macos_app_bundle_path\n"
    "from dodaios.setup.macos_search_index import wait_until_indexed\n"
    "print(wait_until_indexed(macos_app_bundle_path()))\n"
)


def _note_stalled_spotlight() -> None:
    """Say so when this Mac's Spotlight will not find the app just installed.

    Spotlight answers from an index macOS owns. When that index has stalled —
    it accepts the import and never lists the app — the app is in Finder and
    Launchpad but typing its name finds nothing, which reads as a failed
    install. Only an administrator can rebuild the index, so the installer
    names the one command instead of leaving the user to guess.
    """
    try:
        result = subprocess.run(
            [str(venv_python()), "-c", _SPOTLIGHT_PROBE],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # The probe is a courtesy; an install never fails over it.
        return
    if (result.stdout or "").strip().splitlines()[-1:] != ["False"]:
        return
    warn("Spotlight on this Mac is not indexing new apps, so search will not find")
    note(f"{MACOS_APP_NAME} yet (Finder › Applications, Launchpad and the Dock do).")
    note("To repair the macOS search index, run:  sudo mdutil -E /")


def step_macos_bundle_name(*, dry_run: bool) -> None:
    """Give the macOS app bundle its current name, before anything looks for it.

    The updater of the release before this one starts the app again from the
    bundle name ``install/update-contract.json`` states, so the bundle must
    carry that name once this installer is done, with or without the desktop
    profile. One rename in place, only for this install's own bundle; the
    privacy grants stay with it (``rename_legacy_macos_app_bundles``).
    """
    if sys.platform != "darwin":
        return
    if dry_run:
        note("(dry-run) rename the macOS app to its current name")
        return
    try:
        from dodaios.setup.macos_app_bundle import rename_legacy_macos_app_bundles

        renamed = rename_legacy_macos_app_bundles()
    except Exception as exc:  # noqa: BLE001 - the desktop step repairs it again
        warn(f"Could not rename the macOS app: {exc}")
        return
    for bundle in renamed:
        ok(f"macOS app renamed to {bundle.name} (its permissions stay)")


def step_desktop_integration(*, enabled: bool, dry_run: bool) -> bool:
    """Register the managed install with the current desktop shell."""
    if not enabled:
        return True
    if dry_run:
        note("(dry-run) repair desktop-shell registration")
        return True
    result = None
    report: dict[str, object] = {}
    argv = [
        str(venv_python()),
        "-m",
        "dodaios.setup.desktop_integration",
        "--install-dir",
        str(repo_root()),
        "--json",
    ]
    if sys.platform == "darwin":
        # The per-user signing certificate keeps the app's macOS permissions
        # across every future update. Trusting it is the one step macOS
        # guards with a password dialog — say so before it appears.
        argv.append("--create-signing-identity")
        # Once per install; a user who removes the tile keeps it removed.
        argv.append("--pin-to-dock")
        note("macOS may ask for your login password once: it trusts the local signing")
        note(f"certificate that keeps {PRODUCT_NAME}'s permissions across updates.")
    started = time.monotonic()
    try:
        result = run_captured(
            argv,
            cwd=repo_root(),
            label="Registering the desktop app (a first run on macOS can take minutes)",
            # py2app build + icon conversion + signing + LaunchServices import
            # probe can legitimately exceed two minutes on Intel macOS.
            timeout=600,
        )
        output = (result.stdout or "").strip().splitlines()
        report = json.loads(output[-1]) if output else {}
    except (OSError, subprocess.TimeoutExpired):
        report = {}
    except (json.JSONDecodeError, TypeError, ValueError):
        report = {}
    log_path = _write_desktop_integration_log(result)
    if (
        result is not None
        and result.returncode == 0
        and report.get("ok")
        and report.get("attempted")
    ):
        ok("Desktop app registered with the operating system", time.monotonic() - started)
        if sys.platform == "darwin":
            _note_stalled_spotlight()
        return True
    evidence: list[str] = []
    warnings = report.get("warnings") if isinstance(report, dict) else None
    if isinstance(warnings, list):
        evidence.extend(f"warning: {warning}" for warning in warnings)
    evidence.extend((getattr(result, "stderr", "") or "").strip().splitlines()[-15:])
    if log_path is not None:
        evidence.append(f"full log: {log_path}")
    fail(
        "Desktop app registration failed (the app needs a stable launcher identity)",
        evidence,
        hints=[
            "Run the installer again; it repairs the registration.",
            "To install without a desktop app, run it with '--headless'.",
        ],
    )
    return False


# The UI build (tsc + vite) outgrows V8's default heap on a small machine: the
# macOS installer smoke runner (7 GB) aborted in vite with "Abort trap: 6"
# (#1033). A user's own NODE_OPTIONS always wins.
UI_BUILD_NODE_OPTIONS = "--max-old-space-size=4096"
# Lines worth keeping from a long build log even when they are not in its tail:
# a V8 OOM prints its "FATAL ERROR ... heap out of memory" header first and
# then a 50-frame native stack that pushes it out of any short tail.
_UI_BUILD_KEY_LINE = r"fatal|error|heap|out of memory|abort|killed|signal"


def _ui_build_env() -> dict[str, str]:
    env = dict(os.environ)
    if not env.get("NODE_OPTIONS", "").strip():
        env["NODE_OPTIONS"] = UI_BUILD_NODE_OPTIONS
    return env


def _ui_build_diagnostics(output: str, *, tail: int = 15, key_lines: int = 10) -> list[str]:
    """The tail of a failed build's output, preceded by its key lines from before it."""
    import re

    lines = [line for line in output.splitlines() if line.strip()]
    head, last = lines[:-tail], lines[-tail:]
    pattern = re.compile(_UI_BUILD_KEY_LINE, re.IGNORECASE)
    keys = [line for line in head if pattern.search(line)][:key_lines]
    if keys:
        return [*keys, "...", *last]
    return last


def _build_ui_bundle(index: Path) -> bool:
    """Build the UI for a checkout that has none (main tracks no bundle).

    Release tags carry a built bundle, so this only runs for an install of a
    branch. It needs npm; without it the caller says so and stops.
    """
    npm = shutil.which("npm")
    if npm is None:
        fail(
            "No prebuilt UI found, and Node.js/npm is not installed to build one",
            ["Release installs always ship the UI; a checkout of main needs",
             "`npm run build` in dodaios/ui/web/frontend."],
        )
        return False
    frontend = index.parent.parent / "frontend"
    if not (frontend / "package-lock.json").is_file():
        fail("No prebuilt UI found, and dodaios/ui/web/frontend/package-lock.json is missing")
        return False
    env = _ui_build_env()
    for args, label in (
        (["ci"], "Installing the UI build tools (npm ci)"),
        (["run", "build"], "Building the UI (npm run build)"),
    ):
        cmd_name = f"npm {' '.join(args)}"
        started = time.monotonic()
        try:
            result = run_captured(
                [npm, *args], cwd=frontend, label=label, timeout=1800, env=env
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            fail(f"UI build command '{cmd_name}' failed", [str(exc)])
            return False
        if result.returncode != 0:
            combined = "\n".join(
                part.strip()
                for part in (
                    getattr(result, "stdout", "") or "",
                    getattr(result, "stderr", "") or "",
                )
                if part and part.strip()
            )
            output_tail = _ui_build_diagnostics(combined)
            fail(
                f"UI build command '{cmd_name}' failed with exit code {result.returncode}",
                ["npm output (key lines, then the tail):", *output_tail] if output_tail else [],
            )
            return False
        ok(label, time.monotonic() - started)
    if not index.is_file():
        fail(
            "The UI build finished (npm run build exited 0) but its output is incomplete",
            ["build output is incomplete: dodaios/ui/web/dist/index.html was not produced"],
        )
        return False
    return True


def step_ui_bundle_check() -> bool:
    """Honest packaging check: the shipped UI build must be present + intact.

    The public snapshot ships a prebuilt ``dodaios/ui/web/dist``; a dev clone
    may not have one. Missing or torn builds are the 'old/broken app' symptom,
    so say it out loud instead of letting the first launch look broken.
    """
    dist = repo_root() / "dodaios" / "ui" / "web" / "dist"
    index = dist / "index.html"
    if not index.is_file() and not _build_ui_bundle(index):
        return False
    try:
        html = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        fail("The UI build's index is unreadable", [str(index)])
        return False
    refs = [
        ref.split("?", 1)[0]
        for ref in re.findall(r'(?:src|href)="/?(assets/[^"]+)"', html)
    ]
    if not any(ref.endswith(".js") for ref in refs):
        fail("The UI build has no JavaScript entry bundle", [str(index)])
        return False
    missing = [
        ref for ref in refs
        if not (dist / ref.replace("/", os.sep)).is_file()
    ]
    if missing:
        fail(
            f"The UI build is incomplete ({missing[0]} missing)",
            hints=["Please report this: the app may look broken until it is fixed."],
            help_url=f"https://github.com/{OFFICIAL_REPO_SLUG}/issues",
        )
        return False
    ok("UI build present and intact")
    return True


def _resolved_admin_port() -> int:
    """The port the headless launcher will ACTUALLY bind — a jarvis.toml
    ``[ui].admin_api_port`` override if present, else the packaged default.

    Reads it from the launcher itself so the "your server is here" hint can never
    drift from the port the process opens. A hard-coded hint (the old
    ``localhost:8765``) sent every headless/VPS downloader to a dead port while
    the server was serving elsewhere. Falls back to the packaged default if the
    import is somehow unavailable, so this never breaks the launch step."""
    try:
        from dodaios.ui.web.launcher import _DEFAULT_ADMIN_PORT, _fast_admin_port

        return _fast_admin_port()
    except Exception:  # noqa: BLE001 — a hint must never block the launch
        try:
            from dodaios.ui.web.launcher import _DEFAULT_ADMIN_PORT

            return _DEFAULT_ADMIN_PORT
        except Exception:  # noqa: BLE001
            return 47821


def _rescan_venv_site_packages() -> None:
    """Make packages installed by THIS run importable in THIS process.

    The installer process starts before phase 4 runs ``pip install -e .``, and
    editable installs work through a ``.pth`` finder hook that the interpreter
    only processes at startup — so a fresh install could never ``import
    jarvis`` in-process (update runs could, the hook already existed at
    startup, which is why only fresh installs crashed at launch).
    ``site.addsitedir`` re-processes the venv's ``.pth`` files now.
    """
    import importlib
    import site
    import sysconfig

    site.addsitedir(sysconfig.get_paths()["purelib"])
    importlib.invalidate_caches()


def _relaunch_command(*, headless: bool) -> str:
    """The exact command a user can type to (re-)open the app by hand.

    A detached ``Popen`` — and macOS LaunchServices ``open`` — reports success
    the instant the child is spawned, even when no window ever surfaces (a
    first-launch Gatekeeper/permission prompt stealing focus, the bundle
    launching into the background, a display-less session). So the launch outro
    must never *claim* it opened; it always leaves this fallback behind, one
    honest line per OS. Mirrors the "Start again" rows in step_summary.
    """
    if headless or is_headless_linux():
        return f'{venv_python()} -m dodaios.ui.web.launcher --headless'
    if sys.platform == "win32":
        return str(repo_root() / "run.bat")
    if sys.platform == "darwin":
        return f'open -a "{MACOS_APP_NAME}"'
    return f"{venv_python()} -m dodaios.ui.web.launcher"


def step_launch(*, headless: bool, dry_run: bool) -> None:
    if headless or is_headless_linux():
        cmd = [str(venv_python()), "-m", "dodaios.ui.web.launcher", "--headless"]
        msg = f"the headless server on http://localhost:{_resolved_admin_port()}"
    elif sys.platform == "win32":
        cmd = [str(repo_root() / "run.bat")]
        msg = "the desktop app"
    elif sys.platform == "darwin":
        try:
            _rescan_venv_site_packages()
            from dodaios.setup.macos_app_bundle import (
                macos_app_bundle_is_launchable,
                macos_app_bundle_path,
                macos_launch_services_command,
            )
        except Exception:  # noqa: BLE001 — a hint-import must never fail the install
            # The install itself is complete; launch through LaunchServices
            # by app name instead of failing the whole run. Ported from the Mac
            # line (BUG-066 there; the local register merged it as BUG-078).
            cmd = ["/usr/bin/open", "-a", MACOS_APP_NAME]
            msg = "the desktop app"
        else:
            bundle = macos_app_bundle_path()
            if not macos_app_bundle_is_launchable(bundle):
                fail("Could not launch: the installed macOS app bundle is missing or invalid",
                     hints=["Run the installer again; it rebuilds the app bundle."])
                sys.exit(4)
            cmd = macos_launch_services_command(bundle)
            msg = "the desktop app"
    else:
        cmd = [str(venv_python()), "-m", "dodaios.ui.web.launcher"]
        msg = "the desktop app"

    hint = _relaunch_command(headless=headless)
    if dry_run:
        note(f"(dry-run) {' '.join(cmd)}")
        ui().launch(msg, hint)
        return

    # We deliberately do not wait for the App — the installer returns control
    # to the user's shell as soon as the App is spawned.
    try:
        subprocess.Popen(cmd, cwd=repo_root(), close_fds=True, env=app_launch_env())
    except OSError as exc:
        fail(f"Could not launch {msg}", [str(exc)], hints=[f"Open it by hand: {hint}"])
        sys.exit(4)

    # A spawned Popen (and LaunchServices) reports success even when nothing ever
    # surfaces on screen. Never claim it opened without leaving the manual
    # command behind — this is the line the user needs when the window never
    # appears (macOS first-launch permission prompt, background launch, …).
    ui().launch(msg, hint)


def app_launch_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the launched app: the installer's own, minus its git-only knobs.

    The shell stage sets ``GIT_LFS_SKIP_SMUDGE`` for its clone so an install
    never pulls Git LFS binaries. The app (coding-agent panes, git in
    the user's own repos) must not inherit it, or LFS files there would come
    out as pointer files.
    """
    env = dict(os.environ if base is None else base)
    env.pop("GIT_LFS_SKIP_SMUDGE", None)
    # The shell stage's start time is for this installer's finale only.
    env.pop("JARVIS_INSTALL_STARTED_AT", None)
    return env


def step_cli_links(*, dry_run: bool) -> None:
    """Make `dodaios` and its earlier names plain terminal commands on every OS.

    The venv's console scripts are linked (macOS/Linux, ``~/.local/bin``) or
    copied (Windows, ``<install>\\bin``) onto the user's PATH — see
    ``dodaios/setup/cli_path.py``. Never fatal: the app itself works without
    the terminal commands, so a failure here is reported and the install goes on.
    """
    from dodaios.setup.cli_path import install_commands, retired_install_roots

    try:
        # An install moved from its earlier folder name takes that folder's
        # commands off the Windows Path and puts its own on; elsewhere the
        # links are pointed at the new folder.
        report = install_commands(
            repo_root(), dry_run=dry_run, retired_roots=retired_install_roots(repo_root())
        )
    except Exception as exc:  # noqa: BLE001 - terminal commands are optional
        warn(f"Could not set up the terminal commands: {exc}")
        return
    target = str(report.bin_dir)
    if dry_run:
        note(f"(dry-run) terminal commands {', '.join(report.linked)} -> {target}")
        return
    if report.linked:
        ok(f"Terminal commands ready: {', '.join(report.linked)}")
    for command in report.missing:
        warn(f"CLI entry point missing: {command}")
    for command in report.kept:
        note(
            f"Keeping existing {report.bin_dir / command}; "
            f"use {repo_root() / '.venv' / 'bin' / command}"
        )
    for error in report.errors:
        warn(f"Could not create CLI link: {error}")
    for command, other in report.shadowed_by.items():
        note(f"Another {command} comes first on your PATH: {other}")
    for retired in report.path_retired:
        note(f"Took the earlier folder {retired} off your PATH.")
    if report.path_updated:
        note(f"Added {target} to your PATH ({report.path_updated}).")
    if report.needs_new_terminal:
        note("Open a new terminal window to use them.")


def summary_rows(*, update: bool, headless: bool) -> list[tuple[str, str]]:
    """What the finale card says: how to open, update and find the install."""
    gold = (255, 214, 10)
    command = ui().paint(CLI_COMMAND_NAME, gold)
    arrow = "→"
    server = headless or is_headless_linux()
    rows: list[tuple[str, str]] = []
    if server:
        rows.append(("Open", f"http://localhost:{_resolved_admin_port()} in your browser"))
        rows.append(("Start", ".venv/bin/python -m dodaios.ui.web.launcher --headless"))
        rows.append(("", "(in the install folder)"))
    elif sys.platform == "win32":
        # The entry the OS lists, not the display name: this is what a search finds.
        rows.append(("Open", f'Windows search {arrow} "{LAUNCHER_ENTRY_NAME}"'))
    elif sys.platform == "darwin":
        rows.append(("Open", f'Launchpad or Spotlight {arrow} "{MACOS_APP_NAME}"'))
    else:
        rows.append(("Open", f'App menu {arrow} "{LINUX_APP_NAME}"'))
    if not server:
        rows.append(("", f"or type {command} in a new terminal"))
    update_command = ui().paint(f"{CLI_COMMAND_NAME} update", gold)
    rows.append(("Update", f"{update_command}, or run the install command again"))
    rows.append(("Folder", str(repo_root())))
    if sys.platform == "darwin" and not server:
        rows.append(("Permissions", "macOS asks on first use; approve each prompt"))
    if update:
        rows.append(("Next", "Your setup and settings are kept: no re-onboarding."))
    elif server:
        rows.append(("Next", "The one-time setup guide (language, wake word,"))
        rows.append(("", "API keys) runs in the browser, once."))
    else:
        rows.append(("Next", "The app opens with a one-time setup guide"))
        rows.append(("", "(language, wake word, API keys). It never shows again."))
    # Most installs never find their way back to the repo page; one quiet line
    # in the finale is the only place a new user learns how to support it.
    rows.append(("", ""))
    rows.append(("Like it?", "A GitHub star helps others find it:"))
    rows.append(("", ui().paint(f"github.com/{OFFICIAL_REPO_SLUG}", gold)))
    return rows


def step_summary(*, no_launch: bool, update: bool, headless: bool) -> None:
    """The finale: a framed card with the result, the total time and what's next.

    Printed before the launch, so when the app window appears the terminal
    story is already told.
    """
    took = format_duration(time.time() - install_started_at())
    verb = "updated" if update else "installed"
    ui().card(
        f"{PRODUCT_NAME} is {'updated' if update else 'ready'}",
        summary_rows(update=update, headless=headless),
        f"{verb} in {took}" if took else "",
    )


# ---------------------------------------------------------------- entry
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="installer.py",
        description=f"{PRODUCT_NAME} Stage-2 installer",
    )
    parser.add_argument("--no-wizard", action="store_true",
                        help="deprecated no-op: the installer never runs the terminal "
                             "wizard anymore (setup happens in the app)")
    parser.add_argument("--no-launch", action="store_true",
                        help="don't launch the Desktop App at the end")
    parser.add_argument("--headless", action="store_true",
                        help="install headless (no GUI extras, no App launch)")
    parser.add_argument("--with-desktop", action="store_true",
                        help="install [desktop] extras (default: auto-detect by platform)")
    parser.add_argument("--with-voice-local", action="store_true",
                        help="deprecated no-op: the full profile already includes "
                             "the local voice extras")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be done; don't run pip/wizard/launch")
    args = parser.parse_args(argv)

    if args.with_voice_local:
        note("--with-voice-local is deprecated: the full profile already "
             "includes local voice.")

    # Auto-pick desktop extras unless the user said --headless or we're on a
    # headless Linux VPS. (--with-desktop forces it on either way.)
    if not args.with_desktop:
        if args.headless or is_headless_linux():
            with_desktop = False
        else:
            with_desktop = sys.platform in {"win32", "darwin"} or sys.platform.startswith(
                "linux"
            )
    else:
        with_desktop = True

    # Detect BEFORE write_managed_marker stamps the tree: a pre-existing
    # marker means this run is an update of a managed install.
    update = is_update_run()

    step_preflight()
    managed = False
    if not args.dry_run:
        managed = bool(write_managed_marker(with_desktop=with_desktop))
    if not os.environ.get("JARVIS_INSTALL_NO_PIP"):
        step_pip_install(
            with_desktop=with_desktop,
            with_voice_local=args.with_voice_local,
            dry_run=args.dry_run,
        )

    step_models(full_profile=with_desktop, dry_run=args.dry_run)

    phase("6/6", "Finish & launch")
    if managed:
        ok("Managed install: in-app updates enabled")
    browser_cmd = [str(venv_python()), "-m", "dodaios.society.browser.install"]
    if sys.platform.startswith("linux"):
        browser_cmd.append("--system-deps")
    if not with_desktop or args.headless:
        skip("Agent browser skipped (headless profile); the core install is unaffected.")
        note("Optional browser setup (system libraries may require administrator access):")
        note(shlex.join(browser_cmd))
    elif args.dry_run:
        note("(dry-run) managed browser: install and verify on first full installation")
    else:
        started = time.monotonic()
        rc = run_noted(browser_cmd, label="Preparing the agent browser", cwd=repo_root())
        if rc == 0:
            ok("Agent browser ready", time.monotonic() - started)
        else:
            warn(f"The agent browser setup did not finish (exit code {rc}).")
            note("The core install is unaffected; the browser can be set up again later.")
    step_cli_links(dry_run=args.dry_run)
    step_worker_cli(dry_run=args.dry_run)
    step_macos_bundle_name(dry_run=args.dry_run)
    if not step_desktop_integration(enabled=with_desktop, dry_run=args.dry_run):
        ui().stopped("The install stopped before launch. Run the same command again.")
        sys.exit(4)
    # --dry-run must not compile. step_ui_bundle_check builds a missing bundle
    # with npm, and main does not track dist. On the macOS suite that compile
    # ran inside a dry-run test until the file budget killed it.
    if args.dry_run:
        note("(dry-run) check the UI build, and create it with npm when the checkout has none")
    elif not step_ui_bundle_check():
        ui().stopped("The install stopped before launch: the app's UI is not ready.")
        sys.exit(5)

    # Summary FIRST, launch LAST: when the app window appears, the terminal
    # story is already told — and everything the first launch needs is on disk.
    step_summary(no_launch=args.no_launch, update=update, headless=args.headless)
    if not args.no_launch:
        step_launch(headless=args.headless, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
