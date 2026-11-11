"""The owner's stop, kept: a pause that holds until the owner lifts it.

A stop or pause the owner gives (on one job, one routine, one trigger policy,
one agent, or on everything at once) is written down here with its scope, its
reason and where it came from. Everything that could start the work again
checks this record first: the tool executor for unattended calls, the task
scheduler before it runs or resumes a routine, and the repair paths (the
watchdog, a boot sweep, a re-queue) before they put a job back. Because the
record is a file, it holds across follow-up messages from other sources, new
sessions and restarts. Automatic feedback never lifts it: only :meth:`release`
does, and only the owner's own actions call that.

Scopes (``kind``):

``everything``  the whole lead: every unattended call and every routine.
``job``         one row of the jobs ledger.
``routine``     one scheduled task.
``trigger``     one event trigger policy.
``agent``       one agent's assignments and routines.
``session``     one conversation's unattended work.

The owner's own messages are never blocked by a hold: a hold stops what runs
without the owner, not the owner.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

KINDS: Final[tuple[str, ...]] = (
    "everything",
    "job",
    "routine",
    "trigger",
    "agent",
    "session",
)
_SEP: Final[str] = ":"


@dataclass(frozen=True, slots=True)
class StopHold:
    kind: str
    ref: str
    reason: str
    source: str
    created_ms: int
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return _key(self.kind, self.ref)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "reason": self.reason,
            "source": self.source,
            "created_ms": self.created_ms,
            "meta": dict(self.meta),
        }


def _key(kind: str, ref: str) -> str:
    return kind if kind == "everything" else f"{kind}{_SEP}{ref}"


def _clean(kind: str, ref: str) -> tuple[str, str]:
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"unknown stop scope: {kind!r}")
    ref = str(ref or "").strip()
    if kind != "everything" and not ref:
        raise ValueError(f"a {kind} stop needs a reference")
    return kind, ("" if kind == "everything" else ref)


class StopHolds:
    """Persistent set of stop holds. Cheap to ask: one stat call per check."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._holds: dict[str, StopHold] = {}
        self._mtime_ns: int = -1

    # ------------------------------------------------------------ storage

    def _stamp(self) -> int:
        try:
            return self._path.stat().st_mtime_ns
        except OSError as exc:
            log.debug("stop holds: no record at %s: %s", self._path, exc)
            return -1

    def _refresh(self) -> None:
        """Re-read the file when another process (or a restart) changed it."""
        stamp = self._stamp()
        if stamp == self._mtime_ns:
            return
        if stamp < 0:
            self._mtime_ns = stamp
            self._holds = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # An unreadable record must not silently lift a stop: keep what
            # this process already knew.
            log.warning("stop holds: could not read %s: %s", self._path, exc)
            return
        self._mtime_ns = stamp
        items = raw.get("holds") if isinstance(raw, dict) else None
        loaded: dict[str, StopHold] = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                kind, ref = _clean(item.get("kind", ""), item.get("ref", ""))
            except ValueError as exc:
                log.warning("stop holds: skipped a malformed entry in %s: %s", self._path, exc)
                continue
            meta = item.get("meta")
            hold = StopHold(
                kind=kind,
                ref=ref,
                reason=str(item.get("reason") or ""),
                source=str(item.get("source") or ""),
                created_ms=int(item.get("created_ms") or 0),
                meta=dict(meta) if isinstance(meta, dict) else {},
            )
            loaded[hold.key] = hold
        self._holds = loaded

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"holds": [h.to_dict() for h in self._holds.values()]},
                ensure_ascii=False,
                indent=1,
            )
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self._path)
            self._mtime_ns = self._stamp()
        except OSError as exc:
            log.warning("stop holds: could not write %s: %s", self._path, exc)

    # ---------------------------------------------------------------- API

    def hold(
        self,
        kind: str,
        ref: str = "",
        *,
        reason: str = "",
        source: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> StopHold:
        """Put a hold in place (or refresh the one already there)."""
        kind, ref = _clean(kind, ref)
        with self._lock:
            self._refresh()
            previous = self._holds.get(_key(kind, ref))
            merged: dict[str, Any] = dict(previous.meta) if previous else {}
            merged.update(meta or {})
            hold = StopHold(
                kind=kind,
                ref=ref,
                reason=(reason or (previous.reason if previous else "")).strip()[:300],
                source=(source or (previous.source if previous else "") or "owner")[:40],
                created_ms=previous.created_ms if previous else int(time.time() * 1000),
                meta=merged,
            )
            self._holds[hold.key] = hold
            self._save()
            return hold

    def release(self, kind: str, ref: str = "") -> StopHold | None:
        """Lift one hold; returns what was lifted, or ``None``."""
        kind, ref = _clean(kind, ref)
        with self._lock:
            self._refresh()
            lifted = self._holds.pop(_key(kind, ref), None)
            if lifted is not None:
                self._save()
            return lifted

    def get(self, kind: str, ref: str = "") -> StopHold | None:
        kind, ref = _clean(kind, ref)
        with self._lock:
            self._refresh()
            return self._holds.get(_key(kind, ref))

    def items(self) -> list[StopHold]:
        with self._lock:
            self._refresh()
            return sorted(self._holds.values(), key=lambda h: h.created_ms)

    def blocking(
        self,
        *,
        job: str = "",
        routine: str = "",
        trigger: str = "",
        agent: str = "",
        session: str = "",
    ) -> StopHold | None:
        """The hold that stops work with these references, or ``None``.

        ``everything`` answers first, then the specific scopes in the order
        given. Empty references are skipped.
        """
        with self._lock:
            self._refresh()
            if not self._holds:
                return None
            found = self._holds.get("everything")
            if found is not None:
                return found
            for kind, ref in (
                ("job", job),
                ("routine", routine),
                ("trigger", trigger),
                ("agent", agent),
                ("session", session),
            ):
                if ref and (hold := self._holds.get(_key(kind, str(ref)))) is not None:
                    return hold
            return None


_DEFAULT: list[StopHolds] = []
_DEFAULT_LOCK = threading.Lock()


def stop_holds() -> StopHolds:
    """The process-wide store under the data dir (built on first use)."""
    with _DEFAULT_LOCK:
        if not _DEFAULT:
            from dodaios.core.config import DATA_DIR

            _DEFAULT.append(StopHolds(Path(DATA_DIR) / "safety" / "stop_holds.json"))
        return _DEFAULT[0]


def set_stop_holds(store: StopHolds | None) -> None:
    """Swap the process-wide store (tests, a custom data dir)."""
    with _DEFAULT_LOCK:
        _DEFAULT.clear()
        if store is not None:
            _DEFAULT.append(store)


def refs_from_context(context: dict[str, Any] | None) -> dict[str, str]:
    """The hold references a calling layer stamped on its tool context.

    Declared in code by the layer that starts the work (``task_id`` for a
    routine run, ``trigger_id``, ``agent_id``, ``job_id``, ``session_id``),
    never read from a tool argument.
    """
    ctx = context or {}
    out: dict[str, str] = {}
    for param, key in (
        ("job", "job_id"),
        ("routine", "task_id"),
        ("trigger", "trigger_id"),
        ("agent", "agent_id"),
        ("session", "session_id"),
    ):
        value = str(ctx.get(key) or "").strip()
        if value:
            out[param] = value
    return out


def blocking_for_job(job: Any) -> StopHold | None:
    """The hold that forbids repairing or re-queuing this jobs-ledger row.

    A repair path (the watchdog, a boot sweep) calls this before it touches a
    job and leaves the job alone when it returns a hold.
    """
    try:
        return stop_holds().blocking(
            job=str(getattr(job, "id", "") or ""),
            session=str(getattr(job, "owner_session", "") or ""),
            agent=str(getattr(job, "target", "") or ""),
        )
    except Exception:  # noqa: BLE001 — a record that cannot be read never decides a repair
        log.warning("stop holds: could not check a job", exc_info=True)
        return None


__all__ = [
    "KINDS",
    "StopHold",
    "StopHolds",
    "blocking_for_job",
    "refs_from_context",
    "set_stop_holds",
    "stop_holds",
]
