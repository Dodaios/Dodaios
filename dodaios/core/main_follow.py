"""Keep a desktop app that runs from a git checkout on the newest ``main``.

Work lands on ``main`` through pull requests merged on GitHub; the desktop app
runs the code in the checkout it was started from. Without a nudge that
checkout stays on whatever commit it had, so merged work only shows once
somebody pulls, rebuilds the frontend and restarts. :class:`MainFollower` is
that nudge, for a person who opted in (``[agentic_ide] follow_main``):

* Every minute or so it fetches ``origin/main``. When the checkout is on
  ``main`` and ``origin`` is ahead, it fast-forwards. Never a merge, rebase,
  reset or stash: a checkout with local commits, or with a local edit the
  incoming commits would overwrite, is left alone and the reason reported.
* The built frontend bundle (``dodaios/ui/web/dist``) is this follower's to
  rebuild, so local copies of it never block the fast-forward.
* A change under the frontend source rebuilds the bundle; open windows reload
  themselves once the new bundle is on disk (``lib/bundleWatch.ts``).
* A change to the Python code needs a restart. It happens when nothing would be
  lost: no mission running, no live voice call, no speech session. Coding agent
  panes live in their own terminal host and survive it. Until then the status
  says a restart is pending.

Only the instance that owns the ambient duties follows, and only a checkout
whose top level is the folder this package was imported from: a linked
worktree, a dev instance or an installed copy never pulls.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

#: Seconds between two looks at ``origin/main``.
INTERVAL_S = 60.0
#: The first look waits this long, so it never competes with the app's boot.
FIRST_DELAY_S = 45.0
_GIT_TIMEOUT_S = 120.0
_BUILD_TIMEOUT_S = 20 * 60.0
_INSTALL_TIMEOUT_S = 15 * 60.0

#: The package folder this module lives in, as git names it ("jarvis" or a later name).
PACKAGE = Path(__file__).resolve().parents[1].name
DIST = f"{PACKAGE}/ui/web/dist"
FRONTEND = f"{PACKAGE}/ui/web/frontend"
#: Python outside these folders is never loaded by the running app.
_NOT_APP_CODE = ("tests/", "scripts/", "docs/", "tools/")
_NPM_INPUTS = {f"{FRONTEND}/package.json", f"{FRONTEND}/package-lock.json"}
_PIP_INPUTS = {"pyproject.toml", "requirements.txt"}
#: A git lock this old belongs to no running command: one that was killed left it.
STALE_LOCK_S = 10 * 60.0


@dataclass(slots=True)
class FollowStatus:
    enabled: bool = False
    #: The checkout can follow (a git checkout on ``main`` with an ``origin``).
    eligible: bool = False
    #: Why it does not follow, or what blocked the last update, in one sentence.
    reason: str = ""
    head: str = ""
    remote: str = ""
    last_check: float = 0.0
    last_update: float = 0.0
    #: The subject of the newest commit the last update brought in.
    last_subject: str = ""
    #: Updating, building or installing right now.
    busy: str = ""
    restart_pending: bool = False
    #: Local edits that stop the fast-forward.
    blocked_by: list[str] = field(default_factory=list)
    #: When a git lock that blocks the update was last written (epoch s); 0 = none.
    lock_since: float = 0.0
    #: That lock is older than :data:`STALE_LOCK_S`: offered for removal.
    lock_stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run(
    args: list[str], cwd: Path, *, timeout: float = _GIT_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=env,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )


def _git(
    args: list[str], root: Path, *, timeout: float = _GIT_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-c", "core.quotePath=false", *args], root, timeout=timeout)


def _last_line(result: subprocess.CompletedProcess[str]) -> str:
    lines = [
        line.strip() for line in (result.stderr or result.stdout or "").splitlines() if line.strip()
    ]
    return lines[-1] if lines else f"exit code {result.returncode}"


def _overwritten(result: subprocess.CompletedProcess[str]) -> list[str]:
    """The files git names when local edits would be overwritten by a merge."""
    files: list[str] = []
    collecting = False
    for line in (result.stderr or "").splitlines():
        if "would be overwritten" in line or "untracked working tree files" in line:
            collecting = True
            continue
        if collecting:
            if line.startswith(("\t", "    ")) and line.strip():
                files.append(line.strip())
            elif line.strip():
                collecting = False
    return files


def package_root() -> Path:
    """The folder the running ``jarvis`` package was imported from (its parent)."""
    return Path(__file__).resolve().parents[2]


class MainFollower:
    """Fetch, fast-forward, rebuild and restart, one round per :meth:`tick`."""

    def __init__(
        self,
        root: Path,
        *,
        enabled: Callable[[], bool],
        idle: Callable[[], bool],
        restart: Callable[[], bool],
        npm: str | None = None,
        python: str | None = None,
    ) -> None:
        self.root = root
        self._enabled = enabled
        self._idle = idle
        self._restart = restart
        self._npm = npm
        self._python = python or sys.executable
        self.status = FollowStatus()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._logged_reason = ""

    # ------------------------------------------------------------ lifecycle

    def start(self, *, first_delay: float = FIRST_DELAY_S, interval: float = INTERVAL_S) -> None:
        if self._thread is not None:
            return

        def loop() -> None:
            if self._stop.wait(first_delay):
                return
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:  # noqa: BLE001 -- a failed round must not end the follower
                    logger.opt(exception=exc).warning("Follow main: a round failed.")
                    self.status.busy = ""
                    self.status.reason = str(exc)
                self._wake.wait(interval)
                self._wake.clear()

        self._thread = threading.Thread(target=loop, name="jarvis-follow-main", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def poke(self) -> None:
        """Look again now instead of at the next interval."""
        self._wake.set()

    # ------------------------------------------------------------ one round

    def _note(self, reason: str) -> None:
        self.status.reason = reason
        if reason and reason != self._logged_reason:
            logger.info("Follow main: {}", reason)
        self._logged_reason = reason

    def _eligible(self) -> bool:
        top = _git(["rev-parse", "--show-toplevel"], self.root)
        if top.returncode != 0:
            self._note("This app does not run from a git checkout.")
            return False
        if Path(top.stdout.strip()).resolve() != self.root.resolve():
            self._note("This app runs from a folder inside another checkout.")
            return False
        branch = _git(["symbolic-ref", "--quiet", "--short", "HEAD"], self.root).stdout.strip()
        if branch != "main":
            self._note(f"The checkout is on {branch or 'a detached commit'}, not main.")
            return False
        if _git(["remote", "get-url", "origin"], self.root).returncode != 0:
            self._note("The checkout has no origin remote.")
            return False
        return True

    def tick(self) -> FollowStatus:
        """One round: maybe restart, fetch, fast-forward, rebuild. Returns the status."""
        with self._lock:
            status = self.status
            status.enabled = bool(self._enabled())
            if not status.enabled:
                status.eligible = False
                self._note("")
                return status
            status.eligible = self._eligible()
            if not status.eligible:
                return status
            if status.restart_pending and self._idle():
                self._try_restart()
                return status
            status.last_check = time.time()
            fetched = _git(["fetch", "--quiet", "origin", "main"], self.root)
            if fetched.returncode != 0:
                self._note(f"Fetching main failed: {_last_line(fetched)}")
                return status
            status.head = _git(["rev-parse", "HEAD"], self.root).stdout.strip()
            status.remote = _git(["rev-parse", "origin/main"], self.root).stdout.strip()
            if not status.head or status.head == status.remote:
                status.blocked_by = []
                self._note("")
                return status
            if (
                _git(["merge-base", "--is-ancestor", "HEAD", "origin/main"], self.root).returncode
                != 0
            ):
                self._note("Local main has commits that origin/main does not; it is left as it is.")
                return status
            self._update(status)
            if status.restart_pending and self._idle():
                self._try_restart()
            return status

    def _index_lock(self) -> Path | None:
        git_dir = _git(["rev-parse", "--absolute-git-dir"], self.root).stdout.strip()
        return Path(git_dir) / "index.lock" if git_dir else None

    def _locked(self, status: FollowStatus) -> bool:
        """Is the checkout's index locked? Says so, with its age, instead of failing later."""
        lock = self._index_lock()
        if lock is None or not lock.exists():
            status.lock_since = 0.0
            status.lock_stale = False
            return False
        try:
            since = lock.stat().st_mtime
        except OSError:  # removed between the check and the read: not locked any more
            return False
        status.lock_since = since
        status.lock_stale = time.time() - since > STALE_LOCK_S
        self._note(
            "A git lock left by a stopped command blocks the update (.git/index.lock)."
            if status.lock_stale
            else "Another git command is working in this checkout; the update waits."
        )
        return True

    def clear_stale_lock(self) -> bool:
        """Remove the checkout's index lock, only while it is older than :data:`STALE_LOCK_S`.

        Called from the person's own click; a lock any younger may belong to a
        command still running and is never touched.
        """
        with self._lock:
            lock = self._index_lock()
            if lock is None or not lock.exists():
                self.status.lock_since = 0.0
                self.status.lock_stale = False
                return True
            if time.time() - lock.stat().st_mtime <= STALE_LOCK_S:
                return False
            lock.unlink()
            logger.info("Follow main: removed the stale git lock at the person's request.")
            self.status.lock_since = 0.0
            self.status.lock_stale = False
            self._note("")
        self.poke()
        return True

    def _update(self, status: FollowStatus) -> None:
        if self._locked(status):
            return
        listed = _git(["diff", "--name-only", "HEAD", "origin/main"], self.root)
        changed = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        status.busy = "update"
        try:
            if any(path.startswith(f"{DIST}/") for path in changed):
                # The bundle is rebuilt below; a local copy of it must not block the update.
                _git(["checkout", "--", DIST], self.root)
                _git(["clean", "-fdq", "--", DIST], self.root)
            merged = _git(["merge", "--ff-only", "--quiet", "origin/main"], self.root)
            if merged.returncode != 0:
                status.blocked_by = _overwritten(merged)
                shown = ", ".join(status.blocked_by[:5]) or _last_line(merged)
                self._note(f"Local changes block the update: {shown}")
                return
            status.blocked_by = []
            status.last_update = time.time()
            status.last_subject = _git(["log", "-1", "--format=%s"], self.root).stdout.strip()
            status.head = _git(["rev-parse", "HEAD"], self.root).stdout.strip()
            logger.info("Follow main: updated to {} ({})", status.head[:10], status.last_subject)
            frontend = any(path.startswith((f"{FRONTEND}/", f"{DIST}/")) for path in changed)
            backend = any(
                (path.endswith(".py") and not path.startswith(_NOT_APP_CODE)) or path in _PIP_INPUTS
                for path in changed
            )
            if any(path in _PIP_INPUTS for path in changed) and not self._install_python():
                return
            if frontend and not self._build(
                npm_install=any(path in _NPM_INPUTS for path in changed)
            ):
                return
            if backend:
                status.restart_pending = True
            self._note("")
        finally:
            status.busy = ""

    def _build(self, *, npm_install: bool) -> bool:
        npm = self._npm or shutil.which("npm")
        if not npm:
            self._note("npm is not installed, so the frontend could not be rebuilt.")
            return False
        folder = self.root / FRONTEND
        if npm_install or not (folder / "node_modules").is_dir():
            self.status.busy = "install"
            installed = _run(
                [npm, "ci", "--no-audit", "--no-fund"], folder, timeout=_INSTALL_TIMEOUT_S
            )
            if installed.returncode != 0:
                self._note(f"Installing the frontend packages failed: {_last_line(installed)}")
                return False
        self.status.busy = "build"
        built = _run([npm, "run", "build"], folder, timeout=_BUILD_TIMEOUT_S)
        if built.returncode != 0:
            self._note(f"Building the frontend failed: {_last_line(built)}")
            return False
        return True

    def _install_python(self) -> bool:
        self.status.busy = "install"
        installed = _run(
            [self._python, "-m", "pip", "install", "--quiet", "-r", "requirements.txt"],
            self.root,
            timeout=_INSTALL_TIMEOUT_S,
        )
        if installed.returncode != 0:
            self._note(f"Installing the Python packages failed: {_last_line(installed)}")
            return False
        return True

    def _try_restart(self) -> None:
        if self._restart():
            logger.info("Follow main: restarting to load the new code.")
            self.status.restart_pending = False
        else:
            self._note("The new code needs a restart, and this app cannot restart itself.")


# ------------------------------------------------------------------ the app's one follower

_follower: MainFollower | None = None


def get_follower() -> MainFollower | None:
    return _follower


def start_follower(
    *, enabled: Callable[[], bool], idle: Callable[[], bool], restart: Callable[[], bool]
) -> MainFollower | None:
    """Start the app's follower once; only the instance that owns the ambient duties follows."""
    global _follower
    if _follower is not None:
        return _follower
    from dodaios.core.instance import current_instance

    if not current_instance().owns_ambient_duties:
        return None
    _follower = MainFollower(package_root(), enabled=enabled, idle=idle, restart=restart)
    _follower.start()
    return _follower
