"""Always reachable: the agent server as an OS service, kept running by daemonkit.

The independent agent server (``--persistent-server``, docs/agent-server.md)
owns the chat channels, routines and agents. On its own it runs only once
something starts it: a desktop launch, the hand-off when the window closes, or
the login entry. Nothing starts it again after a crash, and nothing starts it
when the person never opens the app.

"Always reachable" closes that gap with :mod:`daemonkit`, the standalone
package at the repository root:

* :func:`install` registers daemonkit's supervisor with the operating system
  (systemd user unit, launchd agent, Windows logon task or ``Run`` key). The
  supervisor starts the agent server at login, and on Linux it can start at
  boot as well. It starts the server again after a crash, with a growing
  pause. An explicit stop (tray, ``POST /api/agent-server/stop``) ends the
  server with exit code 0, and the supervisor leaves it stopped.
* Every background or persistent server takes daemonkit's lock once it
  serves (:func:`claim_for_this_process`), so a supervisor stands by while
  another server runs and takes over when that one ends.
* A desktop client starts the server through the installed service
  (:func:`start_installed_service`), so the OS supervises it.

Only the default app instance installs a service; a dev instance stops with
its window, as everywhere else.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from daemonkit import Claim, Daemon
    from daemonkit.service import ServiceStatus

#: systemd unit ``dodaios-agent-server.service`` and the lock/record file names.
DAEMON_NAME = "dodaios-agent-server"
#: The launchd label of the agent (``~/Library/LaunchAgents/<label>.plist``).
MACOS_LABEL = "com.dodaios.agent-server"
#: The Windows Task Scheduler task.
WINDOWS_TASK = "Dodaios Agent Server"
#: A frozen build has no ``python -m``; ``dodaios/__main__.py`` routes this flag
#: to ``daemonkit.supervise.main``.
FROZEN_SUPERVISE_FLAG = "--daemonkit-supervise"
START_AT = ("login", "boot")
DEFAULT_PORT = 47821

_claim: Claim | None = None


def _state_dir() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "background"


def _port(cfg: Any | None) -> int:
    ui = getattr(cfg, "ui", None)
    try:
        return int(getattr(ui, "admin_api_port", DEFAULT_PORT) or DEFAULT_PORT)
    except (TypeError, ValueError):  # a malformed port falls back to the documented default
        return DEFAULT_PORT


def _label() -> str | None:
    if sys.platform == "darwin":
        return MACOS_LABEL
    if sys.platform == "win32":
        return WINDOWS_TASK
    return None


def agent_daemon(cfg: Any | None = None, *, port: int | None = None) -> Daemon:
    """The daemonkit view of this instance's agent server."""
    from daemonkit import Daemon
    from dodaios.core import background_service as bg
    from dodaios.core.branding import PRODUCT_NAME
    from dodaios.core.frozen import is_frozen
    from dodaios.core.instance import current_instance
    from dodaios.ui.relauncher import restart_workdir

    suffix = current_instance().state_file_suffix.replace(".", "-")
    frozen = is_frozen()
    return Daemon(
        DAEMON_NAME + suffix,
        bg.service_command(
            after_pid=None,
            persistent=True,
            port=port if port is not None else _port(cfg),
            frozen=frozen,
        ),
        state_dir=_state_dir(),
        cwd=restart_workdir(bg._source_root()),
        # Travels on the supervisor's command line: never a secret here.
        env={"PYTHONIOENCODING": "utf-8"},
        description=f"{PRODUCT_NAME} agent server (chat channels, routines, agents)",
        label=_label(),
        supervisor_command=[sys.executable, FROZEN_SUPERVISE_FLAG] if frozen else None,
    )


# ---------------------------------------------------------------------------
# Settings: install, remove, report
# ---------------------------------------------------------------------------


def supported() -> bool:
    from dodaios.core.instance import current_instance

    return current_instance().owns_ambient_duties


def describe(status: ServiceStatus) -> dict[str, Any]:
    """The service status as the settings page shows it."""
    return {
        "supported": bool(status.supported and supported()),
        "installed": bool(status.installed),
        "active": status.active,
        "mechanism": status.mechanism,
        "starts_at": status.starts_at,
        "detail": status.detail,
    }


def status(cfg: Any | None = None) -> dict[str, Any]:
    """Whether the agent server is registered with the OS. Never raises."""
    try:
        return describe(agent_daemon(cfg).service_status())
    except Exception as exc:  # noqa: BLE001 - the settings page must still load
        logger.opt(exception=exc).warning("always-on: service status unreadable")
        return {
            "supported": False,
            "installed": False,
            "active": None,
            "mechanism": "none",
            "starts_at": None,
            "detail": str(exc),
        }


def install(cfg: Any | None = None, *, start_at: str = "login") -> dict[str, Any]:
    """Register the supervised agent server with the OS and start it now.

    A server that already runs keeps running: the new supervisor stands by
    and takes over when it ends.
    """
    if start_at not in START_AT:
        raise ValueError(f"start_at must be one of {START_AT}")
    if not supported():
        raise ValueError("Only the default app can keep the agent server running.")
    daemon = agent_daemon(cfg)
    result = daemon.install_service(start_at=start_at, start_now=True)
    logger.info(
        "always-on: {} via {} (starts at {}){}",
        "installed" if result.installed else "NOT installed",
        result.mechanism,
        result.starts_at,
        f": {result.detail}" if result.detail else "",
    )
    return describe(result)


def uninstall(cfg: Any | None = None) -> dict[str, Any]:
    """Remove the OS registration. A running server keeps running until stopped."""
    daemon = agent_daemon(cfg)
    result = daemon.service_manager().uninstall(daemon.service_spec(), stop=False)
    logger.info("always-on: removed ({})", result.mechanism)
    return describe(result)


def start_installed_service(cfg: Any | None = None, *, port: int | None = None) -> bool:
    """Start the agent server through the OS service, if one is installed.

    False when none is installed or the OS refused; the caller then starts the
    server itself. Never raises.
    """
    try:
        daemon = agent_daemon(cfg, port=port)
        manager = daemon.service_manager()
        spec = daemon.service_spec()
        if not manager.status(spec).installed:
            return False
        from daemonkit.supervise import clear_stop_request

        clear_stop_request(daemon.paths.stop)
        started = manager.start(spec)
    except Exception as exc:  # noqa: BLE001 - starting it directly still works
        logger.opt(exception=exc).warning("always-on: starting through the OS service failed")
        return False
    if started:
        logger.info("always-on: agent server started through the OS service")
    return started


# ---------------------------------------------------------------------------
# The running server's side
# ---------------------------------------------------------------------------


def claim_for_this_process(port: int) -> None:
    """Take daemonkit's lock for this server and publish its port. Never raises.

    Called once the background or persistent server holds the app's own
    single-instance lock and serves on ``port``. Without the claim a
    supervisor would not see this server and would keep trying to start its
    own until this one ends.
    """
    global _claim
    if _claim is not None:
        return
    from daemonkit import AlreadyRunning
    from dodaios import __version__

    try:
        claim = agent_daemon().claim(wait=2.0)
        claim.ready(port=int(port), version=__version__)
    except AlreadyRunning as exc:
        logger.warning("always-on: {}; this server stays unsupervised", exc)
        return
    except OSError as exc:
        logger.warning("always-on: server lock not taken: {}", exc)
        return
    _claim = claim


def release() -> None:
    """Give daemonkit's lock back (before the app's own lock goes). Never raises."""
    global _claim
    claim, _claim = _claim, None
    if claim is None:
        return
    try:
        claim.release()
    except OSError as exc:
        logger.warning("always-on: server lock not released cleanly: {}", exc)
