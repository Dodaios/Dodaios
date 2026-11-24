"""The supervisor: keeps exactly one server running, and starts it again after a crash.

Run as::

    python -m daemonkit.supervise --state-dir DIR --name NAME [options] -- <server argv>

It is what the operating system starts at login (see :mod:`daemonkit.service`),
or what a client spawns when no server is running (``Daemon.start``). It does
four things, and nothing that is specific to any one application:

1. **Standby.** While another process holds the server's instance lock, it
   waits. When that process ends, it starts its own server. So a supervisor
   started at login next to a server that is already running does no harm,
   and takes over when that server goes away.
2. **Restart.** A server that exits with an unexpected code is started again
   after a pause that doubles up to ``--max-backoff`` and resets once a run
   has lasted ``--stable-after`` seconds.
3. **Respect a clean end.** Exit code 0, or 78 (``EXIT_CONFIG``: the server
   cannot start until someone fixes its configuration), ends the supervisor.
   It then exits 0 itself, so the OS does not start it again in a loop; the
   server's code is in the log. Code 75 (``EXIT_ALREADY_RUNNING``: the
   application is already running) makes it pause like after a crash, then
   stand by.
4. **Stop on request.** ``Daemon.stop()`` drops a stop file. The supervisor
   then lets the server finish on its own for ``--stop-grace`` seconds,
   terminates it if it has not, and exits 0. SIGTERM/SIGINT do the same.

Output of the server and of the supervisor goes to ``--log`` (appended; the
file is rotated once it passes 5 MB).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from ._platform import NO_WINDOW
from .lock import is_locked
from .paths import DaemonPaths

log = logging.getLogger("daemonkit.supervise")

#: The server is fine but another instance owns the lock (sysexits EX_TEMPFAIL).
EXIT_ALREADY_RUNNING = 75
#: The server cannot run until its configuration is fixed (sysexits EX_CONFIG).
EXIT_CONFIG = 78

_LOG_ROTATE_BYTES = 5 * 1024 * 1024


@dataclass
class SupervisorPolicy:
    """When to restart, and how long to wait."""

    min_backoff: float = 1.0
    max_backoff: float = 60.0
    stable_after: float = 120.0
    stop_grace: float = 15.0
    standby_poll: float = 2.0
    poll: float = 0.5
    final_exit_codes: frozenset[int] = field(default_factory=lambda: frozenset({0, EXIT_CONFIG}))
    standby_exit_codes: frozenset[int] = field(
        default_factory=lambda: frozenset({EXIT_ALREADY_RUNNING})
    )


def write_stop_request(path: Path) -> None:
    """Ask the supervisor (if any) to stop its server and not start it again."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"requested_at": time.time(), "pid": os.getpid()}), "utf-8")


def read_stop_request(path: Path) -> float | None:
    """When a stop was requested, or ``None``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        # Unreadable or garbled, yet present: still a request to stop.
        return time.time()
    try:
        return float(data.get("requested_at"))
    except (AttributeError, TypeError, ValueError):
        return time.time()


def clear_stop_request(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.warning("daemonkit: stop request %s not removed: %s", path, exc)


class Supervisor:
    """Runs ``argv`` and keeps it running according to ``policy``."""

    def __init__(
        self,
        argv: Sequence[str],
        paths: DaemonPaths,
        *,
        policy: SupervisorPolicy | None = None,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        output: IO[bytes] | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not argv:
            raise ValueError("the supervisor needs a command to run")
        self.argv = list(argv)
        self.paths = paths
        self.policy = policy or SupervisorPolicy()
        self.cwd = cwd
        self.env = dict(env) if env is not None else None
        self.output = output
        self._popen = popen
        self._clock = clock
        self._wake = threading.Event()
        self._stop_signal = False
        self._started_wall = time.time()
        self.child: Any = None
        self.starts = 0

    # -- stop handling -------------------------------------------------------

    def request_stop(self) -> None:
        """Stop from inside this process (signal handlers, tests)."""
        self._stop_signal = True
        self._wake.set()

    def stop_requested(self) -> bool:
        if self._stop_signal:
            return True
        requested = read_stop_request(self.paths.stop)
        # A stop request older than this supervisor was meant for an earlier
        # run; it must not stop a fresh start at the next login.
        return requested is not None and requested >= self._started_wall - 1.0

    def _sleep(self, seconds: float) -> None:
        """Sleep that a stop request cuts short."""
        deadline = self._clock() + seconds
        while not self.stop_requested():
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            self._wake.wait(min(self.policy.poll, remaining))

    # -- main loop -----------------------------------------------------------

    def run(self) -> int:
        """Supervise until a final exit or a stop request. Returns the exit code."""
        stale = read_stop_request(self.paths.stop)
        if stale is not None and stale < self._started_wall - 1.0:
            clear_stop_request(self.paths.stop)
        backoff = self.policy.min_backoff
        try:
            while True:
                if not self._wait_for_free_slot():
                    return 0
                started = self._clock()
                code = self._run_child_once()
                if code is None or self.stop_requested():
                    return 0
                ran_for = self._clock() - started
                if code in self.policy.final_exit_codes:
                    log.info("daemonkit: server ended with code %s; not restarting", code)
                    return code
                if ran_for >= self.policy.stable_after:
                    backoff = self.policy.min_backoff
                if code in self.policy.standby_exit_codes:
                    # The server found its own application lock taken. That
                    # owner may not hold this lock, so standby alone would
                    # retry at once; the growing pause keeps it from looping.
                    log.info(
                        "daemonkit: another instance owns the application; retrying in %.1f s",
                        backoff,
                    )
                else:
                    log.warning(
                        "daemonkit: server exited with code %s after %.1f s; restarting in %.1f s",
                        code,
                        ran_for,
                        backoff,
                    )
                self._sleep(backoff)
                if self.stop_requested():
                    return 0
                backoff = min(backoff * 2, self.policy.max_backoff)
        finally:
            if self.stop_requested():
                clear_stop_request(self.paths.stop)

    def _wait_for_free_slot(self) -> bool:
        """Standby while another server holds the instance lock. False on stop."""
        announced = False
        while is_locked(self.paths.lock):
            if self.stop_requested():
                return False
            if not announced:
                log.info("daemonkit: a server is already running; standing by")
                announced = True
            self._sleep(self.policy.standby_poll)
        return not self.stop_requested()

    def _run_child_once(self) -> int | None:
        """Start the server and wait for it. ``None`` when it never started."""
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "cwd": self.cwd,
            "env": self.env,
        }
        if self.output is not None:
            kwargs["stdout"] = self.output
            kwargs["stderr"] = subprocess.STDOUT
        if sys.platform == "win32":
            kwargs["creationflags"] = NO_WINDOW
        try:
            self.child = self._popen(self.argv, **kwargs)
        except OSError as exc:
            log.error("daemonkit: could not start %s: %s", self.argv[0], exc)
            return 1
        self.starts += 1
        log.info("daemonkit: server started (pid %s)", self.child.pid)
        stop_seen_at: float | None = None
        terminated_at: float | None = None
        killed = False
        while True:
            code = self.child.poll()
            if code is not None:
                return int(code)
            if self.stop_requested():
                now = self._clock()
                if stop_seen_at is None:
                    stop_seen_at = now
                    log.info("daemonkit: stop requested; waiting for the server to end")
                # A stop file usually comes with the application's own stop
                # request in flight, so the server gets time to finish. A
                # signal to the supervisor reached only the supervisor: pass
                # it on at once.
                grace = 0.0 if self._stop_signal else self.policy.stop_grace
                if terminated_at is None and now - stop_seen_at >= grace:
                    log.info("daemonkit: terminating the server (pid %s)", self.child.pid)
                    self.child.terminate()
                    terminated_at = now
                elif terminated_at is not None and not killed and now - terminated_at >= 10.0:
                    log.warning("daemonkit: server ignored terminate; killing it")
                    self.child.kill()
                    killed = True
            self._wake.wait(self.policy.poll)


def _rotate(path: Path) -> None:
    try:
        if path.stat().st_size < _LOG_ROTATE_BYTES:
            return
    except FileNotFoundError:
        return
    try:
        os.replace(path, path.with_name(path.name + ".1"))
    except OSError as exc:
        print(f"daemonkit: log {path} not rotated: {exc}", file=sys.stderr)


def _parse_env(pairs: Sequence[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise SystemExit(f"--env expects KEY=VALUE, got {pair!r}")
        env[key] = value
    return env


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--" not in args:
        print("usage: python -m daemonkit.supervise [options] -- <server argv>", file=sys.stderr)
        return 2
    split = args.index("--")
    own, command = args[:split], args[split + 1 :]
    parser = argparse.ArgumentParser(prog="python -m daemonkit.supervise")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--log", default=None, help="append output here (default: <name>.log)")
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--min-backoff", type=float, default=1.0)
    parser.add_argument("--max-backoff", type=float, default=60.0)
    parser.add_argument("--stable-after", type=float, default=120.0)
    parser.add_argument("--stop-grace", type=float, default=15.0)
    opts = parser.parse_args(own)
    if not command:
        parser.error("no server command after --")
    paths = DaemonPaths(Path(opts.state_dir), opts.name)
    log_path = Path(opts.log) if opts.log else paths.log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate(log_path)
    with open(log_path, "ab", buffering=0) as output:
        stream = open(output.fileno(), "w", encoding="utf-8", buffering=1, closefd=False)  # noqa: SIM115
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        env = None
        extra = _parse_env(opts.env)
        if extra:
            env = {**os.environ, **extra}
        supervisor = Supervisor(
            command,
            paths,
            policy=SupervisorPolicy(
                min_backoff=opts.min_backoff,
                max_backoff=opts.max_backoff,
                stable_after=opts.stable_after,
                stop_grace=opts.stop_grace,
            ),
            cwd=opts.cwd,
            env=env,
            output=output,
        )
        _install_signal_handlers(supervisor)
        log.info("daemonkit: supervisor %s started for %s", os.getpid(), opts.name)
        code = supervisor.run()
        if code != 0:
            log.warning(
                "daemonkit: the server's last exit code was %s; it stays stopped until "
                "it is started again",
                code,
            )
        # The supervisor itself ended as intended. Exiting 0 keeps the OS
        # service manager (launchd's KeepAlive, systemd's Restart=on-failure)
        # from starting it again in a loop; those restart only a supervisor
        # that died.
        log.info("daemonkit: supervisor %s exits", os.getpid())
        return 0


def _install_signal_handlers(supervisor: Supervisor) -> None:
    def _handle(signum: int, _frame: object) -> None:
        log.info("daemonkit: signal %s received; stopping", signum)
        supervisor.request_stop()

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle)
        except (OSError, ValueError) as exc:
            log.debug("daemonkit: no handler for %s: %s", name, exc)
    # Closing the terminal that started us must not stop the server.
    hangup = getattr(signal, "SIGHUP", None)
    if hangup is not None:
        signal.signal(hangup, signal.SIG_IGN)


if __name__ == "__main__":
    raise SystemExit(main())
