"""Switching the wiki's semantic search on and off, and saying how far it is.

Semantic search is opt-in. Switching it on is one click in the app and then
three steps the user only watches: fetch the model once, load it, encode the
vault. Each step can fail on its own (no network, a full disk, a platform
without an inference runtime), and each failure has to stay retryable, so the
work runs on a daemon thread and reports through a small state the UI polls,
the same way the local speech engines install.

The switch itself is ``[wiki_context] semantic_search``. It records what the
user asked for; :func:`status` reports what is actually true on this machine.
After a restart :func:`resume` picks the work up again from wherever it
stopped, including a download the previous run did not finish.

Every start and every stop raises a generation number. A worker carries the
number it was started with and checks it at each step, so switching the search
off ends a download or an encoding run within one chunk or one page, and a
worker that was overtaken never publishes a state or leaves a model loaded.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from dodaios.memory.wiki import semantic_model, semantic_search

log = logging.getLogger(__name__)

SetupState = Literal["off", "downloading", "indexing", "ready", "error"]


class _Cancelled(Exception):
    """Raised inside a worker whose run was switched off or replaced."""


@dataclass
class _Run:
    """Progress of the one setup run, guarded by ``lock``."""

    state: SetupState = "off"
    message: str = ""
    progress: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None
    generation: int = 0
    #: The generation ``thread`` was started for. It differs from
    #: ``generation`` once a stop overtook that thread.
    thread_generation: int = -1


_run = _Run()


def enabled_in(config: Any) -> bool:
    """True when the user switched semantic search on."""
    return bool(getattr(getattr(config, "wiki_context", None), "semantic_search", False))


def status(config: Any) -> dict[str, Any]:
    """What the switch shows: the wish, the facts, and the step in progress.

    ``enabled`` with state ``off`` is the short moment between the app coming
    up and :func:`resume` running; every lasting condition has its own state.
    """
    data_dir = _data_dir(config)
    active = semantic_search.get_active()
    pages, passages = active.counts() if active is not None else (0, 0)
    with _run.lock:
        state, message, progress = _run.state, _run.message, _run.progress
    if not enabled_in(config):
        state, message, progress = "off", "", None
    return {
        "enabled": enabled_in(config),
        "available": semantic_model.runtime_available(),
        "state": state,
        "message": message,
        "progress": progress,
        "model_present": semantic_model.model_present(data_dir),
        "download_bytes": semantic_model.DOWNLOAD_BYTES,
        "pages": pages,
        "passages": passages,
    }


def start(config: Any) -> bool:
    """Begin (or join) the setup run. Returns False when it cannot run here.

    Idempotent: a call while a current run is in flight changes nothing, and a
    call when everything is already in place only brings the index up to date.
    A run that a stop has overtaken is not joined: a new one is started and
    waits for the old one to wind down first, so two runs never write the same
    file.
    """
    if not semantic_model.runtime_available():
        return _refuse(
            "Semantic search needs a component that is not available for "
            "this system. The word search keeps working as before."
        )
    if not getattr(getattr(config, "wiki_integration", None), "enabled", True):
        return _refuse("The wiki is switched off, so there is nothing to search.")
    vault_root = _vault_root(config)
    if vault_root is None:
        return _refuse("No wiki folder is set up yet, so there is nothing to search.")
    data_dir = _data_dir(config)
    with _run.lock:
        alive = _run.thread is not None and _run.thread.is_alive()
        if alive and _run.thread_generation == _run.generation:
            return True
        previous = _run.thread if alive else None
        _run.generation += 1
        _run.thread_generation = _run.generation
        _run.state = "indexing" if semantic_model.model_present(data_dir) else "downloading"
        _run.message = ""
        _run.progress = 0.0
        _run.thread = threading.Thread(
            target=_work,
            args=(_run.generation, previous, vault_root, data_dir),
            name="wiki-semantic-setup",
            daemon=True,
        )
        _run.thread.start()
    return True


def resume(config: Any) -> None:
    """Pick semantic search up at start when the user had it switched on."""
    if enabled_in(config):
        start(config)


def stop() -> None:
    """Switch semantic search off and free the model's memory. Never waits.

    A download or an encoding run in flight ends at its next chunk or page.
    The downloaded model and the stored vectors stay on disk, so switching it
    on again costs seconds, not a second download.
    """
    with _run.lock:
        _run.generation += 1
        _run.state = "off"
        _run.message = ""
        _run.progress = None
    semantic_search.deactivate()


def _refuse(message: str) -> bool:
    with _run.lock:
        _run.generation += 1
        _run.state = "error"
        _run.message = message
        _run.progress = None
    semantic_search.deactivate()
    return False


def _work(
    generation: int,
    previous: threading.Thread | None,
    vault_root: Path,
    data_dir: str | Path | None,
) -> None:
    """Download, load, encode; then publish a terminal state. Never raises."""
    if previous is not None:
        previous.join()

    def note(done: int, total: int) -> None:
        with _run.lock:
            if _run.generation != generation:
                raise _Cancelled
            _run.progress = min(done / total, 1.0) if total > 0 else None

    search: semantic_search.SemanticVaultSearch | None = None
    try:
        if not semantic_model.model_present(data_dir):
            semantic_model.download_model(data_dir, progress=note)
        if not _publish(generation, "indexing", progress=0.0):
            return
        search = semantic_search.activate(vault_root, data_dir=data_dir)
        result = search.sync(progress=note)
        if result.failed and not result.encoded and search.counts()[1] == 0:
            raise RuntimeError(f"none of the {result.failed} wiki pages could be read")
    except _Cancelled:  # switched off or replaced on purpose: there is nothing to report
        _retire(search)
        return
    except Exception as exc:  # noqa: BLE001 - surfaced as a retryable state, not a crash
        log.warning("Semantic wiki search setup failed: %s", exc, exc_info=True)
        # A search that could not be set up must not stay half alive, with the
        # watcher still feeding it pages while the switch says it failed.
        _retire(search)
        _publish(generation, "error", message=_explain(exc))
        return
    if not _publish(generation, "ready", progress=1.0):
        _retire(search)
        return
    log.info(
        "Semantic wiki search ready: %d page(s), %d newly encoded, %d removed, %d failed",
        result.pages,
        result.encoded,
        result.removed,
        result.failed,
    )


def _retire(search: semantic_search.SemanticVaultSearch | None) -> None:
    """Take this run's instance down, unless a newer run already replaced it."""
    if search is not None and semantic_search.get_active() is search:
        semantic_search.deactivate()


def _publish(
    generation: int,
    state: SetupState,
    *,
    message: str = "",
    progress: float | None = None,
) -> bool:
    """Record a step of run *generation*; False when it was overtaken."""
    with _run.lock:
        if _run.generation != generation:
            return False
        _run.state = state
        _run.message = message
        _run.progress = progress
        return True


def _explain(exc: Exception) -> str:
    """One English sentence a person can act on.

    A fixed sentence per kind of failure, never the exception's own text: the
    state is served over the API, and an exception can carry local paths. The
    full error is in the log, written by the caller.
    """
    try:
        import httpx

        if isinstance(exc, httpx.HTTPStatusError):
            return (
                "The search model could not be downloaded: the server refused "
                "the request. Switch it on again later."
            )
        if isinstance(exc, httpx.TransportError):
            return (
                "The search model could not be downloaded. Check the internet "
                "connection and switch it on again."
            )
    except ImportError:
        log.debug("httpx is unavailable; reporting a general setup error")
    if isinstance(exc, OSError):
        return (
            "The search model could not be stored on this disk. Check the free "
            "space and switch it on again."
        )
    return "Semantic search could not be set up. The log has the details."


def _data_dir(config: Any) -> str | None:
    return getattr(getattr(config, "memory", None), "data_dir", None)


def _vault_root(config: Any) -> Path | None:
    from dodaios.memory.wiki.vault_root import resolve_vault_root

    raw = getattr(getattr(config, "wiki_integration", None), "vault_root", None)
    try:
        root = resolve_vault_root(raw).path
    except Exception as exc:  # noqa: BLE001 - an unusable setting is "no vault"
        log.debug("Semantic wiki search: vault root could not be resolved: %s", exc)
        return None
    return root if root.is_dir() else None


__all__ = ["enabled_in", "resume", "start", "status", "stop"]
