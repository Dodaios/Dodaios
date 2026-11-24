"""``Daemon``: the one object a server and its clients share.

A server process calls :meth:`Daemon.claim` and, once it listens,
:meth:`Claim.ready`. Every client calls :meth:`Daemon.ensure_running` and gets
the server's :class:`~daemonkit.record.ServerRecord` back, starting the server
first when none runs. Neither side needs to know how the other was started.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

from ._platform import default_state_dir, windowless_python
from .lock import InstanceLock, is_locked
from .paths import DaemonPaths, check_name
from .process import pid_alive, spawn_detached, terminate
from .record import (
    READY,
    STARTING,
    STOPPING,
    ServerRecord,
    read_record,
    remove_record,
    write_record,
)
from .supervise import clear_stop_request, read_stop_request, write_stop_request

if TYPE_CHECKING:
    from .service import ServiceManager, ServiceSpec, ServiceStatus

log = logging.getLogger(__name__)

#: ``python -m <this>`` runs the supervisor, whatever package daemonkit was copied into.
SUPERVISE_MODULE = __name__.rpartition(".")[0] + ".supervise"


class AlreadyRunning(RuntimeError):
    """Another process is this daemon's server."""

    def __init__(self, name: str, record: ServerRecord | None) -> None:
        pid = record.pid if record else "unknown"
        super().__init__(f"{name} is already running (pid {pid})")
        self.record = record


class StartTimeout(RuntimeError):
    """The server did not become ready in time."""


@dataclass(frozen=True)
class DaemonStatus:
    """A snapshot for a status line or a settings page."""

    running: bool
    ready: bool
    record: ServerRecord | None
    stop_requested: bool


class Claim:
    """A server's hold on its name. Returned by :meth:`Daemon.claim`.

    Use it as a context manager, or call :meth:`release` yourself. Releasing
    removes the record first and gives up the lock last, so a client never
    finds a record without a live server behind it.
    """

    def __init__(self, daemon: Daemon, lock: InstanceLock, record: ServerRecord) -> None:
        self._daemon = daemon
        self._lock = lock
        self._record = record

    @property
    def record(self) -> ServerRecord:
        return self._record

    def ready(
        self,
        *,
        port: int | None = None,
        url: str | None = None,
        token: str | None = None,
        version: str | None = None,
        **info: Any,
    ) -> ServerRecord:
        """Tell clients where the server is. Call once it accepts connections."""
        self._record = ServerRecord(
            pid=self._record.pid,
            state=READY,
            port=port,
            url=url,
            token=token,
            version=version,
            started_at=self._record.started_at,
            info=dict(info),
        )
        write_record(self._daemon.paths.record, self._record)
        return self._record

    def stopping(self) -> None:
        """Tell clients the server is shutting down (they should not attach now)."""
        self._record = ServerRecord(**{**self._record.to_json(), "state": STOPPING})
        write_record(self._daemon.paths.record, self._record)

    def stop_requested(self) -> bool:
        """Whether :meth:`Daemon.stop` asked this server to end."""
        requested = read_stop_request(self._daemon.paths.stop)
        return requested is not None and requested >= self._record.started_at - 1.0

    def release(self) -> None:
        if not self._lock.held:
            return
        remove_record(self._daemon.paths.record, pid=self._record.pid)
        self._lock.release()

    def __enter__(self) -> Claim:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class Daemon:
    """A named, per-user, always-on server process.

    ``argv`` is how to start the server. The server process itself must call
    :meth:`claim` (and :meth:`Claim.ready`) with a ``Daemon`` of the same name
    and state directory.

    ``env`` is added to the server's environment. It travels on the
    supervisor's command line, so it must never hold a secret.
    """

    def __init__(
        self,
        name: str,
        argv: Sequence[str],
        *,
        state_dir: Path | str | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        description: str = "",
        label: str | None = None,
        python: str | None = None,
        supervisor_command: Sequence[str] | None = None,
        service: ServiceManager | None = None,
    ) -> None:
        self.name = check_name(name)
        self.argv = list(argv)
        self.paths = DaemonPaths(
            Path(state_dir) if state_dir is not None else default_state_dir(name), name
        )
        self.cwd = str(cwd) if cwd is not None else None
        self.env = dict(env or {})
        self.description = description or f"{name} (always-on server)"
        self.label = label
        self._python = python
        self._supervisor_command = list(supervisor_command) if supervisor_command else None
        self._service = service

    # -- server side ---------------------------------------------------------

    def claim(self, *, wait: float = 2.0) -> Claim:
        """Become this daemon's server, or raise :class:`AlreadyRunning`.

        ``wait`` covers a client probing the lock at the same instant; it is
        not meant to wait out a running server.
        """
        lock = InstanceLock(self.paths.lock)
        if not lock.acquire_within(wait):
            raise AlreadyRunning(self.name, read_record(self.paths.record))
        record = ServerRecord(pid=os.getpid(), state=STARTING, started_at=time.time())
        try:
            write_record(self.paths.record, record)
        except OSError:
            lock.release()
            raise
        return Claim(self, lock, record)

    # -- client side ---------------------------------------------------------

    def find(self) -> ServerRecord | None:
        """The running server's record (in any state), or ``None``."""
        record = read_record(self.paths.record)
        if not is_locked(self.paths.lock):
            if record is not None:
                # Left behind by a server that died. Only that record goes: a
                # server that started a moment ago has written its own pid.
                remove_record(self.paths.record, pid=record.pid)
            return None
        if record is None or not pid_alive(record.pid):
            return None
        return record

    def is_running(self) -> bool:
        return is_locked(self.paths.lock)

    def status(self) -> DaemonStatus:
        record = self.find()
        running = self.is_running()
        return DaemonStatus(
            running=running,
            ready=bool(running and record is not None and record.ready),
            record=record,
            stop_requested=read_stop_request(self.paths.stop) is not None,
        )

    def start(self) -> int:
        """Start the supervisor (which starts the server) detached. Returns its pid.

        Prefer :meth:`ensure_running`, which does not start a second one.
        """
        clear_stop_request(self.paths.stop)
        argv = self.supervisor_argv()
        log.info("daemonkit: starting %s", self.name)
        return spawn_detached(argv, cwd=self.cwd)

    def ensure_running(
        self,
        *,
        timeout: float = 60.0,
        ready: Callable[[ServerRecord], bool] | None = None,
        start: Callable[[], object] | None = None,
    ) -> ServerRecord:
        """Return the ready server's record, starting the server when none runs.

        ``ready`` is an optional extra check (an HTTP health request, say)
        that must pass before the record is returned. ``start`` replaces the
        default way of starting: the OS service when one is installed,
        otherwise :meth:`start`. Concurrent callers start one server between
        them.
        """
        deadline = time.monotonic() + timeout
        launch = InstanceLock(self.paths.launch_lock)
        if not launch.acquire_within(timeout):
            raise StartTimeout(f"{self.name}: another client is still starting the server")
        try:
            if not self.is_running():
                (start or self._default_start)()
            return self.wait_ready(max(0.0, deadline - time.monotonic()), ready=ready)
        finally:
            launch.release()

    def wait_ready(
        self,
        timeout: float,
        *,
        ready: Callable[[ServerRecord], bool] | None = None,
    ) -> ServerRecord:
        """Wait until the server is ready (and ``ready`` passes)."""
        deadline = time.monotonic() + timeout
        pause = 0.05
        while True:
            record = self.find()
            if record is not None and record.ready:
                try:
                    if ready is None or ready(record):
                        return record
                except Exception as exc:  # noqa: BLE001 - a failing probe means "not yet"
                    log.debug("daemonkit: readiness probe failed: %s", exc)
            if time.monotonic() >= deadline:
                raise StartTimeout(
                    f"{self.name} did not become ready in {timeout:.0f} s; see {self.paths.log}"
                )
            time.sleep(pause)
            pause = min(pause * 2, 0.5)

    def stop(
        self,
        *,
        timeout: float = 30.0,
        graceful: Callable[[ServerRecord], object] | None = None,
    ) -> bool:
        """Stop the server and keep its supervisor from starting it again.

        ``graceful`` is the application's own stop request (an HTTP call, a
        message on its socket); without one, or when it does not work within
        ``timeout``, the server is terminated. True once no server runs.
        The service stays installed: the next login starts it again.
        """
        write_stop_request(self.paths.stop)
        record = self.find()
        if record is None:
            return not self.is_running()
        if graceful is not None:
            try:
                graceful(record)
            except Exception as exc:  # noqa: BLE001 - fall back to terminating it
                log.warning("daemonkit: graceful stop of %s failed: %s", self.name, exc)
        deadline = time.monotonic() + max(0.0, timeout - 5.0)
        while self.is_running() and time.monotonic() < deadline:
            time.sleep(0.2)
        if self.is_running():
            terminate(record.pid, grace=5.0)
        end = time.monotonic() + 5.0
        while self.is_running() and time.monotonic() < end:
            time.sleep(0.1)
        return not self.is_running()

    # -- command lines -------------------------------------------------------

    def supervisor_argv(self, *, windowless: bool = True) -> list[str]:
        """The command that runs this daemon's supervisor around its server."""
        if self._supervisor_command is not None:
            prefix = list(self._supervisor_command)
        else:
            python = self._python or sys.executable
            if windowless:
                python = windowless_python(python)
            prefix = [python, "-m", SUPERVISE_MODULE]
        argv = [*prefix, "--state-dir", str(self.paths.state_dir), "--name", self.name]
        if self.cwd:
            argv += ["--cwd", self.cwd]
        for key, value in sorted(self.env.items()):
            argv += ["--env", f"{key}={value}"]
        return [*argv, "--", *self.argv]

    # -- operating-system service --------------------------------------------

    def service_manager(self) -> ServiceManager:
        """The OS service manager this daemon registers with."""
        if self._service is None:
            from .service import service_manager

            self._service = service_manager()
        return self._service

    def service_spec(self) -> ServiceSpec:
        from .service import ServiceSpec

        return ServiceSpec(
            name=self.name,
            argv=tuple(self.supervisor_argv()),
            description=self.description,
            working_dir=self.cwd,
            log_path=str(self.paths.log),
            label=self.label,
        )

    def install_service(
        self,
        *,
        start_at: str = "login",
        start_now: bool = True,
        manager: ServiceManager | None = None,
    ) -> ServiceStatus:
        """Register the supervisor with the OS so it starts at login (or boot).

        The OS then also restarts the supervisor if it ever dies. A server
        that is already running keeps running; the new supervisor waits and
        takes over when it ends.
        """
        return (manager or self.service_manager()).install(
            self.service_spec(), start_at=start_at, start_now=start_now
        )

    def uninstall_service(
        self, *, stop: bool = True, manager: ServiceManager | None = None
    ) -> ServiceStatus:
        """Remove the OS registration (systemd and launchd also stop it unless ``stop=False``)."""
        return (manager or self.service_manager()).uninstall(self.service_spec(), stop=stop)

    def service_status(self, *, manager: ServiceManager | None = None) -> ServiceStatus:
        return (manager or self.service_manager()).status(self.service_spec())

    def _default_start(self) -> None:
        """Start through the OS service when installed, so the OS supervises it."""
        clear_stop_request(self.paths.stop)
        try:
            manager = self.service_manager()
            spec = self.service_spec()
            if manager.status(spec).installed and manager.start(spec):
                return
        except Exception as exc:  # noqa: BLE001 - starting directly still works
            log.warning("daemonkit: OS service start failed, starting directly: %s", exc)
        self.start()
