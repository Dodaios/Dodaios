"""Stop everything, and resume it: the owner's one reliable off-switch.

Any channel the owner speaks on (the desk, a Telegram, Discord or WhatsApp
message that says "stop") ends here. One call:

1. writes the ``everything`` stop hold first, so nothing that races the stop
   can start again (the tool executor, the scheduler and the repair paths all
   read it);
2. cancels every running turn and parks queued messages,
3. pauses every routine (running ones are interrupted and parked as paused,
   resumable, not ended as cancelled),
4. closes every open job in the jobs ledger as cancelled,
5. fires the app's emergency stop so tokens held by missions and computer-use
   loops fire too;
6. returns one report whose :meth:`StopReport.message` is the single written
   confirmation the owner receives.

The steps run concurrently under one deadline, so the time from the stop to
all work halted is bounded by ``deadline_s`` and not by the slowest turn.

The owner's own messages keep working while the hold is in force (a hold stops
what runs without the owner). Work comes back only through
:func:`resume_everything`, which the owner triggers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Final

from .stop_hold import StopHolds, stop_holds

log = logging.getLogger(__name__)

#: Longest the whole stop may take before it reports what it reached.
DEADLINE_S: Final[float] = 10.0

_LINES: Final[dict[str, dict[str, str]]] = {
    "en": {
        "stopped": (
            "Stopped. {turns} running turns, {routines} routines and {jobs} jobs are halted. "
            "Nothing starts again until you say resume."
        ),
        "already": "Everything is already stopped. Say resume when you want work to continue.",
        "resumed": "Resumed. {routines} routines are back on. Stopped jobs stay stopped.",
        "not_stopped": "Nothing was stopped, so there is nothing to resume.",
    },
    "de": {  # i18n-allow: localized phone lines
        "stopped": (
            "Gestoppt. {turns} laufende Antworten, {routines} Routinen und {jobs} Aufträge "  # i18n-allow  # noqa: E501
            "sind angehalten. Nichts startet wieder, bis du \"weiter\" sagst."  # i18n-allow
        ),
        "already": "Alles ist schon gestoppt. Sag \"weiter\", wenn die Arbeit weitergehen soll.",  # i18n-allow  # noqa: E501
        "resumed": "Weiter geht es: {routines} Routinen laufen wieder. Gestoppte Aufträge bleiben so.",  # i18n-allow  # noqa: E501
        "not_stopped": "Es war nichts gestoppt, also gibt es nichts fortzusetzen.",  # i18n-allow
    },
    "es": {  # i18n-allow: localized phone lines
        "stopped": (
            "Detenido. {turns} turnos en curso, {routines} rutinas y {jobs} trabajos "
            "están parados. Nada vuelve a empezar hasta que digas reanudar."
        ),
        "already": "Todo ya está detenido. Di reanudar cuando quieras que siga el trabajo.",
        "resumed": "Reanudado. {routines} rutinas vuelven a estar activas. Los trabajos detenidos siguen detenidos.",  # noqa: E501
        "not_stopped": "No había nada detenido, así que no hay nada que reanudar.",
    },
    "pt": {  # i18n-allow: localized phone lines
        "stopped": (
            "Parado. {turns} respostas em curso, {routines} rotinas e {jobs} trabalhos "
            "estão parados. Nada recomeça até dizeres retomar."
        ),
        "already": "Tudo já está parado. Diz retomar quando quiseres que o trabalho continue.",
        "resumed": "Retomado. {routines} rotinas voltaram a estar ativas. Os trabalhos parados continuam parados.",  # noqa: E501
        "not_stopped": "Não havia nada parado, por isso não há nada a retomar.",
    },
}


def _line(key: str, language: str, **values: int) -> str:
    table = _LINES.get((language or "en").lower()[:2]) or _LINES["en"]
    return table.get(key, _LINES["en"][key]).format(**values)


@dataclass(slots=True)
class StopReport:
    already_held: bool = False
    turns: int = 0
    routines: int = 0
    jobs: int = 0
    elapsed_ms: int = 0
    reason: str = ""
    source: str = ""
    errors: list[str] = field(default_factory=list)

    def message(self, language: str = "en") -> str:
        """The one written confirmation: what was halted and how it comes back."""
        if self.already_held and not (self.turns or self.routines or self.jobs):
            return _line("already", language)
        return _line(
            "stopped", language, turns=self.turns, routines=self.routines, jobs=self.jobs
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "already_held": self.already_held,
            "turns": self.turns,
            "routines": self.routines,
            "jobs": self.jobs,
            "elapsed_ms": self.elapsed_ms,
            "reason": self.reason,
            "source": self.source,
            "errors": list(self.errors),
        }


@dataclass(slots=True)
class ResumeReport:
    was_held: bool = False
    routines: int = 0
    errors: list[str] = field(default_factory=list)

    def message(self, language: str = "en") -> str:
        if not self.was_held:
            return _line("not_stopped", language)
        return _line("resumed", language, routines=self.routines)


async def _stop_turns(svc: Any, reason: str) -> int:
    """Cancel every running turn and keep waiting messages parked."""
    if svc is None:
        return 0
    sids = list(dict.fromkeys(svc.running_session_ids()))
    if not sids:
        return 0
    from dodaios.agent_chat import send_queue

    controls = getattr(svc, "_controls", None)

    async def one(sid: str) -> None:
        try:
            send_queue.pause(svc, sid)
        except Exception:  # noqa: BLE001 — parking a queue never blocks the stop
            log.debug("stop everything: could not park the queue of %s", sid, exc_info=True)
        # A goal loop must not start the next turn: pause it, which cancels too.
        if controls is not None and sid in getattr(controls, "jobs", {}):
            await controls.pause(sid, reason or "Stopped by the owner")
        else:
            await svc.cancel(sid)

    results = await asyncio.gather(*(one(s) for s in sids), return_exceptions=True)
    for sid, result in zip(sids, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("stop everything: turn %s did not stop cleanly: %s", sid, result)
    return len(sids)


async def _stop_routines(scheduler: Any, reason: str) -> tuple[int, list[str]]:
    if scheduler is None:
        return 0, []
    outcome = await scheduler.hold_all(reason)
    ids = [*outcome.get("paused", []), *outcome.get("interrupted", [])]
    return len(ids), ids


def _stop_jobs(ledger: Any, reason: str) -> int:
    if ledger is None:
        return 0
    count = 0
    for job in ledger.recent(open_only=True, limit=1000):
        ledger.update(
            job.id,
            state="cancelled",
            detail="Stopped by you",
            error=(reason or "stopped by the owner")[:200],
        )
        count += 1
    return count


async def stop_everything(
    *,
    chat_service: Any = None,
    scheduler: Any = None,
    ledger: Any = None,
    bus: Any = None,
    reason: str = "",
    source: str = "desk",
    holds: StopHolds | None = None,
    deadline_s: float = DEADLINE_S,
) -> StopReport:
    """Halt all work and keep it halted. Never raises; says what it reached."""
    started = time.monotonic()
    store = holds or stop_holds()
    report = StopReport(reason=reason, source=source)
    report.already_held = store.get("everything") is not None
    # The hold goes first: from here on nothing that runs without the owner
    # can start, so the steps below only have to end what is already running.
    store.hold("everything", reason=reason or "Stopped by the owner", source=source)

    async def kill() -> None:
        if bus is None:
            return
        from dodaios.core.events import KillRequested

        await bus.publish(KillRequested(source=source, reason="owner_stop"))

    async def run_turns() -> None:
        report.turns = await _stop_turns(chat_service, reason)

    routine_ids: list[str] = []

    async def run_routines() -> None:
        report.routines, ids = await _stop_routines(scheduler, reason)
        routine_ids.extend(ids)

    async def run_jobs() -> None:
        report.jobs = await asyncio.to_thread(_stop_jobs, ledger, reason)

    steps = {"kill": kill, "turns": run_turns, "routines": run_routines, "jobs": run_jobs}
    tasks = {name: asyncio.ensure_future(fn()) for name, fn in steps.items()}
    done, pending = await asyncio.wait(tasks.values(), timeout=deadline_s)
    for task in pending:
        task.cancel()
    for name, task in tasks.items():
        if task in pending:
            report.errors.append(f"{name}: not finished within {deadline_s:.0f}s")
        elif task.exception() is not None:
            report.errors.append(f"{name}: {task.exception()}")
            log.warning("stop everything: %s failed: %s", name, task.exception())
    if routine_ids:
        store.hold("everything", meta={"routines": routine_ids})
    report.elapsed_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "stop everything (%s): %d turns, %d routines, %d jobs in %d ms",
        source, report.turns, report.routines, report.jobs, report.elapsed_ms,
    )
    return report


async def resume_everything(
    *,
    scheduler: Any = None,
    source: str = "desk",
    holds: StopHolds | None = None,
) -> ResumeReport:
    """The owner lifts the stop: routines paused by it come back on.

    Jobs that were stopped stay stopped (their evidence is final), and routines
    the owner had paused one by one stay paused: only what the stop itself
    paused returns.
    """
    store = holds or stop_holds()
    lifted = store.release("everything")
    report = ResumeReport(was_held=lifted is not None)
    if lifted is None:
        return report
    for task_id in lifted.meta.get("routines", []) if scheduler is not None else []:
        if store.get("routine", str(task_id)) is not None:
            continue  # the owner paused this one on its own: it stays paused
        try:
            await scheduler.resume(str(task_id), owner=True)
            report.routines += 1
        except Exception as exc:  # noqa: BLE001 — one routine that cannot resume does not block the rest
            report.errors.append(f"{task_id}: {exc}")
            log.info("resume everything: routine %s not resumed: %s", task_id, exc)
    return report


# ------------------------------------------------------------ the words

#: A message that is only one of these stops everything (closed lists, like the
#: card-answer words in the channel bridge).
_STOP_WORDS: Final[frozenset[str]] = frozenset(
    {
        "stop", "stop everything", "stop all", "stop it all", "emergency stop",
        "stopp", "stopp alles", "alles stoppen", "alles stopp", "alles anhalten",  # i18n-allow
        "para", "para tudo", "detener todo", "detén todo", "alto", "parar tudo",  # i18n-allow
    }
)  # fmt: skip
_RESUME_WORDS: Final[frozenset[str]] = frozenset(
    {
        "resume", "resume everything", "resume all", "continue everything",
        "weiter", "alles fortsetzen", "alles weiter", "weitermachen",  # i18n-allow
        "reanudar", "reanudar todo", "retomar", "retomar tudo",  # i18n-allow
    }
)  # fmt: skip


def _normal(text: str) -> str:
    cleaned = "".join(ch for ch in (text or "").lower() if ch.isalnum() or ch.isspace())
    return " ".join(cleaned.split())


def is_stop_everything(text: str) -> bool:
    """True when the whole message is a stop word (never a sentence containing one)."""
    return _normal(text) in {_normal(w) for w in _STOP_WORDS}


def is_resume_everything(text: str) -> bool:
    return _normal(text) in {_normal(w) for w in _RESUME_WORDS}


__all__ = [
    "DEADLINE_S",
    "ResumeReport",
    "StopReport",
    "is_resume_everything",
    "is_stop_everything",
    "resume_everything",
    "stop_everything",
]
