"""Warn once when one environment holds the app under both distribution names.

The Python distribution was renamed (``dodaios.core.branding``:
``LEGACY_DISTRIBUTION_NAMES`` -> ``DISTRIBUTION_NAME``). For a transition the
same code is published under both names, so both own the same package files.
With both installed the app runs fine, but uninstalling either one later
deletes files the other still needs. ``install/installer.py`` never creates
that state (it uninstalls the earlier name first); a manual ``pip install``
can, and this check names the fix.

Off the boot path (AP-26): :func:`schedule_duplicate_distribution_check`
starts one daemon thread a while after the server is up, once per process,
and only outside a frozen build, whose bundle carries one record by
construction. The check reads package metadata and logs one line at most.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from importlib import metadata

from dodaios.core.branding import DISTRIBUTION_NAME, DISTRIBUTION_NAMES

log = logging.getLogger(__name__)

# The boot is long over by then: the check competes with nothing in use.
DEFAULT_DELAY_S = 30.0
PRIMARY_INSTANCE_ENV_VAR = "JARVIS_PRIMARY_INSTANCE"

_SCHEDULE_LOCK = threading.Lock()
_scheduled = False


def _is_installed(name: str) -> bool:
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        # Not installed under this name: that is the answer, not a failure.
        return False
    return True


def installed_distribution_names(
    names: Sequence[str] = DISTRIBUTION_NAMES,
    *,
    is_installed: Callable[[str], bool] = _is_installed,
) -> tuple[str, ...]:
    """Which of the distribution's names this environment has installed."""
    return tuple(name for name in names if is_installed(name))


def duplicate_distribution_message(installed: Sequence[str]) -> str | None:
    """The warning for ``installed``, or ``None`` when it holds at most one name."""
    if len(installed) < 2:
        return None
    others = [name for name in installed if name != DISTRIBUTION_NAME]
    return (
        f"The Python packages {' and '.join(installed)} are both installed in {sys.prefix}. "
        "They contain the same files, so uninstalling one later deletes files the "
        f"other needs. Run: pip uninstall -y {' '.join(others)} && "
        f"pip install --force-reinstall --no-deps {DISTRIBUTION_NAME} "
        "(an install from the one-line installer: run the installer again)."
    )


def check_duplicate_distributions(
    *, is_installed: Callable[[str], bool] = _is_installed
) -> str | None:
    """Log the warning when it applies; return it for callers and tests."""
    message = duplicate_distribution_message(
        installed_distribution_names(is_installed=is_installed)
    )
    if message:
        log.warning(message)
    return message


def _run(delay_s: float) -> None:
    if delay_s > 0:
        time.sleep(delay_s)
    try:
        check_duplicate_distributions()
    except Exception:  # noqa: BLE001 - a diagnostic must never take the app down
        log.debug("Duplicate distribution check failed.", exc_info=True)


def schedule_duplicate_distribution_check(
    *,
    delay_s: float = DEFAULT_DELAY_S,
    environ: Mapping[str, str] | None = None,
) -> threading.Thread | None:
    """Start the check in a daemon thread, once per process; ``None`` when skipped.

    Main instance only (``JARVIS_PRIMARY_INSTANCE=1``, set by the launcher that
    holds the single-instance lock), like the other one-time background jobs.
    """
    global _scheduled
    env = os.environ if environ is None else environ
    if getattr(sys, "frozen", False) or env.get(PRIMARY_INSTANCE_ENV_VAR) != "1":
        return None
    with _SCHEDULE_LOCK:
        if _scheduled:
            return None
        _scheduled = True
    thread = threading.Thread(
        target=_run, args=(delay_s,), name="distribution-check", daemon=True
    )
    thread.start()
    return thread


__all__ = [
    "DEFAULT_DELAY_S",
    "check_duplicate_distributions",
    "duplicate_distribution_message",
    "installed_distribution_names",
    "schedule_duplicate_distribution_check",
]
