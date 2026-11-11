"""The watchdog supervisor: a scheduled, isolated control loop.

It runs in threads of its own and shares none of the lead's turn machinery: its
state is a SQLite file of its own, its checks read the stores through read-only
connections, and every step that has to touch the app's event loop (probing a job,
steering a turn, writing the notice) goes through one bounded hop. A hop that does
not answer in time is itself a finding ("the app stopped answering") and never
blocks the next heartbeat.

Two threads:

* the heartbeat thread rewrites ``watchdog_heartbeat.json`` every few seconds
  (time, boot id, what was in flight, whether the loop answered). The next boot
  reads the file: a heartbeat that stopped without a clean shutdown becomes one
  notice saying how long the app was down and what was in flight;
* the scan thread runs one scan per interval (5 minutes by default).

A scan is code first (``checks.run_checks``), then at most one reversible repair
per finding, then, for suspected stuck work only and only if the person turned it
on, the judge. Whatever is left becomes ONE written notice in the lead's
conversation, deduplicated by finding key. The watchdog never speaks.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, Protocol

from dodaios.orchestrator.watchdog import checks
from dodaios.orchestrator.watchdog.checks import Finding, Limits, Snapshot
from dodaios.orchestrator.watchdog.store import WatchdogStore, now_ms

log = logging.getLogger(__name__)

HEARTBEAT_FILE: Final[str] = "watchdog_heartbeat.json"
STORE_FILE: Final[str] = "watchdog.db"
HEARTBEAT_S: Final[float] = 15.0
#: A heartbeat older than this at the next boot, without a clean stop, is downtime.
DOWNTIME_MIN_S: Final[int] = 120
_INFLIGHT_MAX: Final[int] = 10
NUDGE_TEXT: Final[str] = (
    "Status check from the watchdog: this turn has been silent or is repeating the same "
    "step. In one or two sentences say what you are doing and what blocks you, then "
    "continue with a different approach or finish."
)


class Sources(Protocol):
    """Where a scan reads its evidence. ``LiveSources`` reads the running app."""

    def snapshot(self, store: WatchdogStore, now: int) -> Snapshot: ...

    def drain_log(self) -> list[str]: ...


class Actions(Protocol):
    """What a scan may do. Every method answers ``False``/``None`` instead of raising."""

    def can_repair(self, finding: Finding) -> bool: ...

    def repair(self, finding: Finding) -> str | None: ...

    def post_notice(self, payload: dict[str, Any]) -> bool: ...

    def quiet_hours(self) -> bool: ...

    def judge(self, goal: str, evidence: str) -> tuple[str, str] | None: ...


def build_notice(findings: list[dict[str, Any]], repairs: list[dict[str, Any]]) -> dict[str, Any]:
    """ONE written notice for every new finding: evidence first, then what can be done."""
    lines = ["Something needs a look. I did not change anything beyond what is listed."]
    for row in findings[:8]:
        ev = row.get("evidence") or {}
        facts = ", ".join(f"{k}: {v}" for k, v in list(ev.items())[:5])
        line = f"- {row['title']} ({facts})" if facts else f"- {row['title']}"
        if row.get("repair_result"):
            line += f". Tried once: {row['repair_result']}"
        if row.get("judge_note"):
            line += f". Check: {row['judge_note']}"
        lines.append(line)
    if len(findings) > 8:
        lines.append(f"- and {len(findings) - 8} more (ask for the watchdog status)")
    if repairs:
        lines.append("Repaired on its own: " + "; ".join(r["detail"] for r in repairs[:5]))
    return {
        "kind": "watchdog",
        "status": "done",
        "text": "\n".join(lines),
        "findings": [
            {"id": r["key"], "title": r["title"], "actions": r.get("actions", []),
             **({"open": r["open_ref"]} if r.get("open_ref") else {})}
            for r in findings[:8]
        ],
    }


class Watchdog:
    def __init__(
        self,
        data_dir: Path | str,
        sources: Sources,
        actions: Actions,
        *,
        store: WatchdogStore | None = None,
        limits: Limits | None = None,
        boot_id: str = "",
        clock: Callable[[], int] = now_ms,
    ) -> None:
        self._dir = Path(data_dir)
        self.store = store or WatchdogStore(self._dir / STORE_FILE)
        self.sources = sources
        self.actions = actions
        self.limits = limits or Limits()
        self.boot_id = boot_id or f"{os.getpid()}-{int(time.time())}"
        self._clock = clock
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._scan_lock = threading.Lock()
        self._inflight: list[str] = []
        self._loop_ok = True
        self.last_scan_ms = 0
        self.last_scan_findings = 0

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._threads:
            return
        self.check_previous_run()
        self._write_heartbeat(clean=False)
        for name, target in (("heartbeat", self._heartbeat_loop), ("scan", self._scan_loop)):
            thread = threading.Thread(target=target, name=f"dodaios-watchdog-{name}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """Clean shutdown: the next boot must not report downtime."""
        self._stop.set()
        self._write_heartbeat(clean=True)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_S):
            self._write_heartbeat(clean=False)

    def _scan_loop(self) -> None:
        # First scan a minute after start: the app is still booting its stores.
        wait = 60.0
        while not self._stop.wait(wait):
            try:
                self.scan()
            except Exception:  # noqa: BLE001 - a scan problem never ends the watchdog
                log.warning("watchdog: scan failed", exc_info=True)
            wait = self.store.settings()["interval_min"] * 60.0

    # ------------------------------------------------------------ heartbeat

    @property
    def heartbeat_path(self) -> Path:
        return self._dir / HEARTBEAT_FILE

    def _write_heartbeat(self, *, clean: bool) -> None:
        body = {
            "ts_ms": self._clock(),
            "boot_id": self.boot_id,
            "pid": os.getpid(),
            "clean": clean,
            "loop_ok": self._loop_ok,
            "last_scan_ms": self.last_scan_ms,
            "inflight": self._inflight[:_INFLIGHT_MAX],
        }
        try:
            tmp = self.heartbeat_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(body), encoding="utf-8")
            tmp.replace(self.heartbeat_path)
        except OSError:
            log.debug("watchdog: heartbeat not written", exc_info=True)

    def check_previous_run(self) -> Finding | None:
        """Report how long the app was down if the last run ended without a clean stop."""
        try:
            previous = json.loads(self.heartbeat_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # no readable heartbeat: a first run, nothing to report
            return None
        if not isinstance(previous, dict) or previous.get("boot_id") == self.boot_id:
            return None
        if previous.get("clean"):
            return None
        down_s = max(0, (self._clock() - int(previous.get("ts_ms") or 0)) // 1000)
        if down_s < DOWNTIME_MIN_S:
            return None
        inflight = [str(x) for x in (previous.get("inflight") or [])][:_INFLIGHT_MAX]
        minutes = max(1, round(down_s / 60))
        finding = Finding(
            key=f"{checks.KIND_DOWNTIME}:{previous.get('boot_id')}",
            kind=checks.KIND_DOWNTIME,
            title=f"The app was not running for about {minutes} minutes",
            evidence={"down_min": minutes, "in_flight": inflight or "nothing recorded"},
        )
        self.store.upsert(finding, now=self._clock())
        self.store.log("detected", key=finding.key, kind=finding.kind,
                       detail=f"down {minutes} min, in flight: {len(inflight)}", now=self._clock())
        return finding

    # ----------------------------------------------------------------- scan

    def scan(self) -> dict[str, Any]:
        """One pass. Returns a small report (also what the tests read)."""
        with self._scan_lock:
            return self._scan()

    def _scan(self) -> dict[str, Any]:
        report: dict[str, Any] = {"findings": 0, "repaired": [], "notified": 0, "judged": 0}
        settings = self.store.settings()
        now = self._clock()
        if not settings["checks"]:
            return report
        snap = self.sources.snapshot(self.store, now)
        self._loop_ok = snap.loop_ok
        self._inflight = [f"{t.surface}:{t.session_id}" for t in snap.turns][:5] + [
            j.title for j in snap.jobs if j.state in ("queued", "running")
        ][:5]
        for line in self.sources.drain_log():
            self.store.log("repaired", detail=line, now=now)
            report["repaired"].append(line)
        found = checks.run_checks(snap, self.limits)
        report["findings"] = len(found)
        for finding in found:
            if self.store.upsert(finding, now=now):
                self.store.log("detected", key=finding.key, kind=finding.kind,
                               detail=finding.title, now=now)
        # Downtime findings come from the previous run, not from this scan's evidence.
        keep = {f.key for f in found} | {
            r["key"]
            for r in self.store.open_findings(200)
            if r["kind"] == checks.KIND_DOWNTIME and not r["notified_ms"]
        }
        for key in self.store.resolve_missing(keep, now=now):
            self.store.log("resolved", key=key, detail="no longer detected", now=now)
        held = self._repair(found, report, now)
        if settings["judge"]:
            self._judge(found, report)
        self._notify(held, report, now)
        self.last_scan_ms = now
        self.last_scan_findings = len(found)
        return report

    def _repair(self, found: list[Finding], report: dict[str, Any], now: int) -> set[str]:
        """The one reversible repair per finding. Returns keys that wait a scan."""
        held: set[str] = set()
        for finding in found:
            if not finding.repair or not self.actions.can_repair(finding):
                continue
            row = self.store.get(finding.key)
            if row is None or row["state"] != "open" or not self.store.claim_repair(finding.key):
                continue
            result = self.actions.repair(finding)
            if result is None:
                self.store.set_repair_result(finding.key, "the repair did not apply")
                self.store.log("repair_failed", key=finding.key, kind=finding.kind, now=now)
                continue
            self.store.set_repair_result(finding.key, result)
            self.store.log("repaired", key=finding.key, kind=finding.kind, detail=result, now=now)
            report["repaired"].append(result)
            if finding.repair == checks.ACT_REQUEUE:
                self.store.dismiss(finding.key)  # handled: the work runs again
            else:
                held.add(finding.key)  # give the nudge a scan to work before saying anything
        return held

    def _judge(self, found: list[Finding], report: dict[str, Any]) -> None:
        for finding in found:
            if finding.judge is None:
                continue
            row = self.store.get(finding.key)
            if row is None or row["state"] != "open" or row["judged"]:
                continue
            verdict = self.actions.judge(*finding.judge)
            if verdict is None:
                self.store.set_judged(finding.key, "")
                self.store.log("judge_skipped", key=finding.key, kind=finding.kind,
                               detail="no subscription or local seat")
                continue
            report["judged"] += 1
            kind, reason = verdict
            self.store.set_judged(finding.key, reason)
            self.store.log("judged", key=finding.key, kind=finding.kind, detail=f"{kind}: {reason}")
            if kind == "progress":
                self.store.mark_quiet(finding.key, reason)

    def _notify(self, held: set[str], report: dict[str, Any], now: int) -> None:
        pending = [r for r in self.store.to_notify() if r["key"] not in held]
        if not pending or self.actions.quiet_hours():
            return
        repairs = [
            {"detail": r["detail"]}
            for r in self.store.events_since(now - 24 * 3600 * 1000, 20)
            if r["event"] == "repaired" and not r["key"]
        ]
        payload = build_notice(pending, repairs)
        if self.actions.post_notice(payload):
            self.store.mark_notified([r["key"] for r in pending], now=now)
            self.store.log("notified", detail=f"{len(pending)} finding(s)", now=now)
            report["notified"] = len(pending)
            self._report_urgent(pending)
        else:
            self.store.log("notice_deferred", detail="the conversation was not reachable", now=now)

    def _report_urgent(self, notified: list[dict[str, Any]]) -> None:
        """Hand each critical finding to the opt-in urgent caller, once, with its notice."""
        report = getattr(self.actions, "report_urgent", None)
        if report is None:
            return
        for row in notified:
            if checks.severity_of(str(row.get("kind") or "")) != "critical":
                continue
            try:
                report(row)
            except Exception:  # noqa: BLE001 - the call is an extra; the notice already stands
                log.info("watchdog: urgent report failed for %s", row.get("key"), exc_info=True)


# ------------------------------------------------------------ module handle

_current: Watchdog | None = None
_current_lock = threading.Lock()


def current() -> Watchdog | None:
    return _current


def set_current(watchdog: Watchdog | None) -> None:
    global _current
    with _current_lock:
        _current = watchdog


__all__ = [
    "DOWNTIME_MIN_S", "HEARTBEAT_FILE", "NUDGE_TEXT", "STORE_FILE", "Actions", "Sources",
    "Watchdog", "build_notice", "current", "set_current",
]
