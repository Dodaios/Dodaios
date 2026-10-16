"""Lifecycle supervisor for the local ChatGPT web bridge behind ``chatgpt-web``.

The bridge is a separate local process (``chatgpt-web-provider serve``) that
drives the user's own ChatGPT web session in a dedicated browser profile and
exposes an OpenAI-Responses-shaped API on loopback. This module owns exactly
that one process: it reports a typed status, starts it lazily (never on the
boot critical path, AP-26), bounds restarts, keeps a PID/lock file so two
callers never spawn twice, and stops it on request.

Configuration lives on ``[brain.providers."chatgpt-web"]``:

* ``base_url`` — the bridge root, loopback only (default ``http://127.0.0.1:17852``)
* ``home``     — the bridge home (its ``config.json`` holds the bearer token;
  the browser session stays inside it and never leaves it)
* ``cli``      — path to the built ``provider-cli.mjs``
* ``runtime``  — the JavaScript runtime that runs it (default ``bun``)
* ``log_dir``  — where the size-capped bridge log goes (default ``<home>/logs``)

The token is read from the secret store first (``chatgpt_web_token``) and
otherwise from the bridge's own ``config.json``; it is never logged.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from jarvis.core import config as cfg
from jarvis.core.http_pool import SyncHttpClientPool
from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS, resolve_executable

log = logging.getLogger(__name__)

PROVIDER_ID = "chatgpt-web"
DEFAULT_BASE_URL = "http://127.0.0.1:17852"

BridgeStatus = Literal[
    "not_installed",
    "not_configured",
    "login_required",
    "starting",
    "ready",
    "offline",
    "session_invalid",
    "failed",
]

# Bounded restarts: a bridge that keeps dying must surface as ``failed``
# instead of being respawned in a loop.
MAX_STARTS = 3
START_WINDOW_S = 600.0
STARTUP_GRACE_S = 45.0
LOG_CAP_BYTES = 5 * 1024 * 1024

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_probe_pool = SyncHttpClientPool(timeout_s=3.0)


class ChatGPTWebError(RuntimeError):
    """A typed bridge failure. ``code`` is one of the status/turn codes below.

    ``login_required`` · ``offline`` · ``session_invalid`` ·
    ``bridge_unavailable`` · ``submission_ambiguous`` · ``failed``
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BridgeSettings:
    base_url: str
    home: Path | None
    cli: Path | None
    runtime: str
    log_dir: Path | None


@dataclass(frozen=True)
class BridgeState:
    status: BridgeStatus
    detail: str


def _provider_extra(name: str) -> str:
    try:
        provider = cfg.load_config().brain.providers.get(PROVIDER_ID)
    except Exception as exc:  # noqa: BLE001 — an unreadable config reads as "not configured"
        log.warning("chatgpt-web: config unreadable: %s", exc)
        return ""
    if provider is None:
        return ""
    if name == "base_url":
        return (provider.base_url or "").strip()
    return str((provider.model_extra or {}).get(name) or "").strip()


def settings() -> BridgeSettings:
    home = _provider_extra("home")
    cli = _provider_extra("cli")
    log_dir = _provider_extra("log_dir")
    home_path = Path(home) if home else None
    return BridgeSettings(
        base_url=(_provider_extra("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        home=home_path,
        cli=Path(cli) if cli else None,
        runtime=_provider_extra("runtime") or "bun",
        log_dir=Path(log_dir) if log_dir else (home_path / "logs" if home_path else None),
    )


def is_loopback(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "") in _LOOPBACK_HOSTS


def bridge_token(s: BridgeSettings | None = None) -> str | None:
    """The bridge bearer token. Never log the return value."""
    token = cfg.get_secret("chatgpt_web_token", "CHATGPT_WEB_PROVIDER_TOKEN")
    if token:
        return token
    s = s or settings()
    if s.home is None:
        return None
    try:
        data = json.loads((s.home / "config.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:  # an unconfigured bridge has no token yet
        return None
    except (OSError, ValueError) as exc:
        log.warning("chatgpt-web: bridge config.json unreadable: %s", type(exc).__name__)
        return None
    token = str(data.get("apiToken") or "").strip()
    return token or None


class BridgeSupervisor:
    """One process, one lock, bounded restarts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._starts: deque[float] = deque()
        self._started_at: float | None = None
        self._session_invalid = False

    # ---- paths -------------------------------------------------------------

    @staticmethod
    def _run_dir(s: BridgeSettings) -> Path | None:
        return s.home / "run" if s.home else None

    def _pid_file(self, s: BridgeSettings) -> Path | None:
        run = self._run_dir(s)
        return run / "bridge.pid" if run else None

    def _read_pid(self, s: BridgeSettings) -> int | None:
        pid_file = self._pid_file(s)
        if pid_file is None:
            return None
        try:
            return int(pid_file.read_text(encoding="utf-8").strip())
        except FileNotFoundError:  # no PID file means nothing was started
            return None
        except (OSError, ValueError) as exc:
            log.warning("chatgpt-web: stale pid file ignored: %s", exc)
            return None

    @staticmethod
    def _pid_alive(pid: int | None) -> bool:
        if not pid:
            return False
        import psutil  # noqa: PLC0415 — lazy (AP-26)

        try:
            proc = psutil.Process(pid)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except psutil.Error:  # a vanished or foreign PID is not our bridge
            return False

    # ---- status ------------------------------------------------------------

    @staticmethod
    def login_saved(s: BridgeSettings) -> bool:
        """The bridge's own verified-login marker; ``serve`` exits without it."""
        if s.home is None:
            return False
        marker = s.home / "browser" / "storage-state.json.verified.json"
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except FileNotFoundError:  # never signed in
            return False
        except (OSError, ValueError) as exc:
            log.warning("chatgpt-web: login marker unreadable: %s", type(exc).__name__)
            return False
        return isinstance(data, dict) and data.get("authenticated") is True

    def mark_session_invalid(self) -> None:
        self._session_invalid = True

    def status(self) -> BridgeState:
        s = settings()
        if not is_loopback(s.base_url):
            return BridgeState("failed", "The bridge URL must be a loopback address.")
        if s.cli is None or not s.cli.is_file():
            return BridgeState("not_installed", "The ChatGPT bridge is not installed.")
        if s.home is None or not (s.home / "config.json").is_file():
            return BridgeState("not_configured", "The ChatGPT bridge has no home configured.")
        token = bridge_token(s)
        if not token:
            return BridgeState("not_configured", "The ChatGPT bridge has no access token.")
        client = _probe_pool.client()
        try:
            client.get(f"{s.base_url}/healthz").raise_for_status()
        except Exception as exc:  # noqa: BLE001 — any probe failure is "not up"
            log.debug("chatgpt-web: healthz failed: %s", type(exc).__name__)
            if self._pid_alive(self._read_pid(s)) and self._within_grace():
                return BridgeState("starting", "The ChatGPT bridge is starting.")
            if not self.login_saved(s):
                return BridgeState("login_required", "Sign in to ChatGPT in the bridge browser.")
            if self._exhausted():
                return BridgeState("failed", "The ChatGPT bridge keeps stopping; restarts paused.")
            return BridgeState("offline", "The ChatGPT bridge is not running.")
        try:
            ready = client.get(
                f"{s.base_url}/readyz", headers={"Authorization": f"Bearer {token}"}
            )
        except Exception as exc:  # noqa: BLE001 — up a moment ago, gone now
            log.debug("chatgpt-web: readyz failed: %s", type(exc).__name__)
            return BridgeState("offline", "The ChatGPT bridge is not responding.")
        if ready.status_code == 401:
            return BridgeState("failed", "The bridge rejected the Dodaios access token.")
        if ready.status_code == 503:
            return BridgeState("login_required", "Sign in to ChatGPT in the bridge browser.")
        if ready.status_code != 200:
            return BridgeState("failed", f"The bridge answered HTTP {ready.status_code}.")
        if self._session_invalid:
            return BridgeState("session_invalid", "The ChatGPT session expired; sign in again.")
        return BridgeState("ready", "ChatGPT is ready.")

    def _within_grace(self) -> bool:
        started = self._started_at
        return started is not None and time.monotonic() - started < STARTUP_GRACE_S

    def _exhausted(self) -> bool:
        now = time.monotonic()
        while self._starts and now - self._starts[0] > START_WINDOW_S:
            self._starts.popleft()
        return len(self._starts) >= MAX_STARTS

    # ---- lifecycle ---------------------------------------------------------

    def _env(self, s: BridgeSettings) -> dict[str, str]:
        env = dict(os.environ)
        env["CHATGPT_WEB_PROVIDER_HOME"] = str(s.home)
        # The bridge must never see a paid key it could fall back to.
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            env.pop(name, None)
        return env

    def _open_log(self, s: BridgeSettings, name: str) -> Any:
        assert s.log_dir is not None
        s.log_dir.mkdir(parents=True, exist_ok=True)
        path = s.log_dir / name
        if path.exists() and path.stat().st_size > LOG_CAP_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
        return path.open("ab")

    def start(self) -> BridgeState:
        """Start the bridge unless it already runs. Idempotent, bounded."""
        with self._lock:
            state = self.status()
            if state.status in ("ready", "login_required", "starting", "session_invalid"):
                return state
            if state.status in ("not_installed", "not_configured"):
                return state
            s = settings()
            if self._pid_alive(self._read_pid(s)):
                # Our process lives but does not answer: replace it once.
                self._kill(s)
            if self._exhausted():
                return BridgeState("failed", "The ChatGPT bridge keeps stopping; restarts paused.")
            runtime = resolve_executable(s.runtime) or s.runtime
            log_file = self._open_log(s, "bridge.log")
            try:
                proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
                    [runtime, str(s.cli), "serve"],
                    cwd=str(s.home),
                    env=self._env(s),
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=NO_WINDOW_CREATIONFLAGS,
                )
            except OSError as exc:
                log.error("chatgpt-web: bridge failed to start: %s", exc)
                return BridgeState("failed", "The ChatGPT bridge could not be started.")
            finally:
                log_file.close()
            self._starts.append(time.monotonic())
            self._started_at = time.monotonic()
            self._session_invalid = False
            pid_file = self._pid_file(s)
            assert pid_file is not None
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(proc.pid), encoding="utf-8")
            log.info("chatgpt-web: bridge started (pid %d)", proc.pid)
            return BridgeState("starting", "The ChatGPT bridge is starting.")

    def wait_until_up(self, timeout_s: float = STARTUP_GRACE_S) -> BridgeState:
        deadline = time.monotonic() + timeout_s
        state = self.status()
        while state.status == "starting" and time.monotonic() < deadline:
            time.sleep(0.5)
            state = self.status()
        return state

    def ensure_running(self) -> BridgeState:
        state = self.status()
        if state.status in ("offline", "failed"):
            self.start()
            state = self.wait_until_up()
        elif state.status == "starting":
            state = self.wait_until_up()
        return state

    def _kill(self, s: BridgeSettings) -> None:
        pid = self._read_pid(s)
        if self._pid_alive(pid):
            import psutil  # noqa: PLC0415 — lazy (AP-26)

            try:
                proc = psutil.Process(pid)
                for child in proc.children(recursive=True):
                    child.kill()
                proc.kill()
                proc.wait(timeout=10)
            except psutil.Error as exc:
                log.warning("chatgpt-web: could not stop bridge pid %s: %s", pid, exc)
        pid_file = self._pid_file(s)
        if pid_file is not None:
            pid_file.unlink(missing_ok=True)

    def stop(self) -> BridgeState:
        with self._lock:
            self._kill(settings())
            self._started_at = None
        return BridgeState("offline", "The ChatGPT bridge is stopped.")

    def restart(self) -> BridgeState:
        self.stop()
        self.start()
        return self.wait_until_up()

    def login(self) -> BridgeState:
        """Open the bridge's own headed browser profile for a one-time sign-in."""
        s = settings()
        if s.cli is None or s.home is None:
            return self.status()
        runtime = resolve_executable(s.runtime) or s.runtime
        log_file = self._open_log(s, "login.log")
        try:
            subprocess.Popen(  # noqa: S603 — fixed argv, no shell
                [runtime, str(s.cli), "login"],
                cwd=str(s.home),
                env=self._env(s),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=NO_WINDOW_CREATIONFLAGS,
            )
        finally:
            log_file.close()
        self._session_invalid = False
        return BridgeState("login_required", "Finish the ChatGPT sign-in in the opened browser.")


supervisor = BridgeSupervisor()
