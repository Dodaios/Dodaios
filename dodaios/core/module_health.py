"""Which optional modules failed to start or load, kept for the health reads.

A plugin that cannot be imported, a service that raises while it starts: the
app goes on without that one module. This registry is where each such boundary
writes down what happened, so the failure is not only a log line. It is read by
``GET /api/health`` (``degraded``: module names) and
``GET /api/diagnostics/modules`` (the reasons).

Dependency-free and thread-safe: any boundary may report from any thread, and
a report never raises.
"""

from __future__ import annotations

import threading
import time
from typing import Any

__all__ = ["clear", "degraded_names", "report_failure", "reset", "snapshot"]

_LOCK = threading.Lock()
_FAILED: dict[str, dict[str, Any]] = {}

#: A reason is a line for a person, not a traceback.
_REASON_CHARS = 300
#: Bound for a registry that outlives a misbehaving caller.
_MAX_MODULES = 200


def report_failure(module: str, error: BaseException | str) -> None:
    """Mark ``module`` unhealthy; the latest reason replaces an earlier one."""
    try:
        if isinstance(error, BaseException):
            reason = f"{type(error).__name__}: {error}"
        else:
            reason = str(error)
        entry = {"reason": " ".join(reason.split())[:_REASON_CHARS], "since": time.time()}
        with _LOCK:
            if module in _FAILED:
                entry["since"] = _FAILED[module]["since"]
            elif len(_FAILED) >= _MAX_MODULES:
                return
            _FAILED[module] = entry
    except Exception:  # noqa: BLE001 — broad-except: module boundary — module health must never raise
        return


def clear(module: str) -> None:
    """Mark ``module`` healthy again (a later start or load succeeded)."""
    with _LOCK:
        _FAILED.pop(module, None)


def snapshot() -> dict[str, dict[str, Any]]:
    """Every unhealthy module with its reason and the time it first failed."""
    with _LOCK:
        return {name: dict(entry) for name, entry in sorted(_FAILED.items())}


def degraded_names() -> list[str]:
    with _LOCK:
        return sorted(_FAILED)


def reset() -> None:
    """Forget everything; for tests."""
    with _LOCK:
        _FAILED.clear()
