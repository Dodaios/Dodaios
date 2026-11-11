"""The self-change registry: one versioned record for every change the agent makes to itself.

Flow of a proposal (``propose``)::

    record exact before/after + diff
      -> gate (offline regression for the surface)
           fail         -> blocked, never applied, one written notice
           core surface -> proposed, waits for the owner (never applied by the agent)
           unavailable  -> proposed, waits for the owner
           pass         -> applied, state ``trial``
    trial -> live   (``promote``, the owner keeps it)
    any applied state -> reverted (``rollback``: the exact previous text comes back)

Only the owner's routes call ``approve``, ``reject``, ``promote`` and ``rollback``.
The agent's tools get ``propose`` through the surfaces that already exist (skill
authoring, self-build); none of them can approve, grade, or touch the audit.
Every step also lands in the owner's audit log.
"""

from __future__ import annotations

import contextlib
import difflib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from .gate import FAIL, UNAVAILABLE, Draft, Gate, GateReport
from .store import DB_NAME, Change, ChangeStore
from .surfaces import ACTIVE_STATES, State, Surface, core_reasons

log = logging.getLogger(__name__)

OWNER: Final = "owner"
#: ``ref`` prefix of changes mirrored from the self-build ledger.
MIRROR_PREFIX: Final = "build:"

Notify = Callable[[dict[str, Any]], None]
ExternalReverter = Callable[[Change], None]


class SelfChangeError(RuntimeError):
    """A request the registry refuses (wrong state, unknown change, no handler)."""


class Handler(Protocol):
    """Reads and writes the live text of one surface. ``None`` means "does not exist"."""

    def read(self, target: str) -> str | None: ...

    def write(self, target: str, text: str | None) -> None: ...


@dataclass(slots=True)
class FileHandler:
    """A handler for surfaces that are one file each. ``resolve`` maps a target to its path."""

    resolve: Callable[[str], Path]

    def read(self, target: str) -> str | None:
        path = self.resolve(target)
        try:
            return path.read_bytes().decode("utf-8")
        except FileNotFoundError:  # a missing file is the "does not exist yet" state
            return None

    def write(self, target: str, text: str | None) -> None:
        path = self.resolve(target)
        if text is None:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.self_change.tmp")
        tmp.write_bytes(text.encode("utf-8"))  # byte-exact: a rollback restores the same bytes
        tmp.replace(path)


def make_diff(target: str, before: str | None, after: str | None) -> str:
    lines = difflib.unified_diff(
        (before or "").splitlines(keepends=True),
        (after or "").splitlines(keepends=True),
        fromfile=f"{target} (before)" if before is not None else "/dev/null",
        tofile=f"{target} (after)" if after is not None else "/dev/null",
    )
    text = "".join(lines)
    return text[:40_000]


def _origin(author: str) -> str:
    return "owner" if author == OWNER else "agent"


class SelfChangeRegistry:
    def __init__(
        self,
        data_dir: Path | str,
        *,
        gate: Gate | None = None,
        notify: Notify | None = None,
        audit: Callable[[], Any] | None = None,
    ) -> None:
        self.store = ChangeStore(Path(data_dir) / DB_NAME)
        self.gate = gate or Gate(self.store)
        self._handlers: dict[Surface, Handler] = {}
        #: A handler a proposal brought for one target; later approve/rollback reuse it.
        self._overrides: dict[tuple[Surface, str], Handler] = {}
        self._external: ExternalReverter | None = None
        self._notify = notify
        self._audit = audit
        self._lock = threading.RLock()

    # ------------------------------------------------------------ wiring

    def register_handler(self, surface: Surface, handler: Handler) -> None:
        self._handlers[surface] = handler

    def register_external_reverter(self, reverter: ExternalReverter) -> None:
        """Reverts changes another ledger owns (self-build artefacts), by their ``ref``."""
        self._external = reverter

    def set_notifier(self, notify: Notify | None) -> None:
        self._notify = notify

    def close(self) -> None:
        self.store.close()

    # ----------------------------------------------------------- helpers

    def _say(self, change: Change, text: str) -> None:
        payload = {
            "kind": "self_change",
            "status": "done",
            "text": text,
            "change_id": change.id,
            "surface": change.surface.value,
            "state": change.state.value,
        }
        if self._notify is None:
            return
        try:
            self._notify(payload)
        except Exception:  # noqa: BLE001 — a notice must never undo a recorded decision
            log.info("self_change: notice not posted", exc_info=True)

    def _log(self, change: Change, action: str, outcome: str, actor: str, note: str = "") -> None:
        try:
            audit = self._audit() if self._audit else None
            if audit is None:
                from dodaios.trust.audit import audit_log

                audit = audit_log()
            audit.record(
                {
                    "tool": "self_change",
                    "action": action,
                    "origin": _origin(change.author if action == "propose" else actor),
                    "origin_detail": (change.author if action == "propose" else actor)[:200],
                    "approval": "owner_click" if actor == OWNER else "none",
                    "approval_by": actor if actor == OWNER else "",
                    "outcome": outcome,
                    "error": note if outcome in ("failed", "blocked") else "",
                    "args_preview": f"{change.surface.value}:{change.target} v{change.version} "
                    f"({change.id}) {note}"[:500],
                }
            )
        except Exception:  # noqa: BLE001 — the audit never costs the action
            log.info("self_change: audit not written", exc_info=True)

    def _handler(self, surface: Surface, target: str = "") -> Handler:
        handler = self._overrides.get((surface, target)) or self._handlers.get(surface)
        if handler is None:
            raise SelfChangeError(f"nothing can apply or restore a {surface.value} change here")
        return handler

    @staticmethod
    def _label(change: Change) -> str:
        return f"{change.surface.value} {change.target!r}"

    # ----------------------------------------------------------- propose

    def propose(self, draft: Draft, *, handler: Handler | None = None) -> Change:
        """Record, gate and (when it may be) apply one change. Never raises on a refusal.

        ``handler`` replaces the surface's registered handler for this one write (a skill
        folder that is not the default one).
        """
        with self._lock:
            handler = handler or self._handlers.get(draft.surface)
            if handler is not None:
                self._overrides[(draft.surface, draft.target)] = handler
            before = draft.before
            if before is None and handler is not None:
                before = handler.read(draft.target)
            if before == draft.after:
                raise SelfChangeError("the change does not change anything")
            reasons = core_reasons(draft.surface, draft.target, draft.after, draft.paths)
            report = self.gate.run(draft)
            core = bool(reasons)
            if report.status == FAIL:
                state, note = State.BLOCKED, report.summary()
            elif core or report.status == UNAVAILABLE or handler is None:
                state = State.PROPOSED
                note = "; ".join(reasons) or report.summary() or "no handler can apply it here"
            else:
                state, note = State.TRIAL, "passed the gate; on trial"
            change = self.store.add(
                surface=draft.surface,
                target=draft.target,
                before=before,
                after=draft.after,
                diff=make_diff(draft.target, before, draft.after),
                author=draft.author,
                turn=draft.turn,
                reason=draft.reason,
                state=State.PROPOSED if state is State.TRIAL else state,
                core=core,
                core_reasons=reasons,
                gate=report.public(),
                ref=draft.ref,
            )
            self.gate.record(change.id, report)
            if state is State.TRIAL:
                change = self._apply(
                    change, actor=draft.author, to=State.TRIAL, note=note, handler=handler
                )
            elif state is State.BLOCKED:
                change = self.store.move(change.id, State.BLOCKED, actor="gate", note=note)
            self._announce_proposal(change, report, note)
            return change

    def _announce_proposal(self, change: Change, report: GateReport, note: str) -> None:
        label = self._label(change)
        if change.state is State.BLOCKED:
            self._say(
                change,
                f"I did not change my {label}: it failed the regression check ({note}). "
                "Nothing is different.",
            )
            self._log(change, "propose", "blocked", change.author, note)
        elif change.state is State.PROPOSED:
            self._say(
                change,
                f"I would like to change my {label}, but that needs your approval ({note}). "
                "Nothing is different until you approve it in Trust.",
            )
            self._log(change, "propose", "awaiting_confirmation", change.author, note)
        else:
            self._log(change, "propose", "executed", change.author, note)

    def _apply(
        self,
        change: Change,
        *,
        actor: str,
        to: State,
        note: str,
        handler: Handler | None = None,
    ) -> Change:
        handler = handler or self._handler(change.surface, change.target)
        try:
            handler.write(change.target, change.after)
        except Exception as exc:  # noqa: BLE001 — a failed write leaves the old version in place
            log.warning("self_change: apply failed for %s", change.id, exc_info=True)
            with contextlib.suppress(Exception):
                handler.write(change.target, change.before)
            moved = self.store.move(
                change.id, State.BLOCKED, actor="registry", note=f"apply failed: {exc}"
            )
            self._say(moved, f"I did not change my {self._label(moved)}: it could not be written.")
            return moved
        return self.store.move(change.id, to, actor=actor, note=note)

    # --------------------------------------------------- owner decisions

    def _get(self, change_id: str) -> Change:
        change = self.store.get(change_id)
        if change is None:
            raise SelfChangeError(f"unknown change {change_id}")
        return change

    def approve(self, change_id: str) -> Change:
        """The owner lets a waiting change go live. The only way a core change is applied."""
        with self._lock:
            change = self._get(change_id)
            if change.state is not State.PROPOSED:
                raise SelfChangeError(f"a {change.state.value} change cannot be approved")
            handler = self._handler(change.surface, change.target)
            if handler.read(change.target) != change.before:
                note = "the target changed since the proposal"
                moved = self.store.move(change.id, State.BLOCKED, actor=OWNER, note=note)
                self._log(moved, "approve", "blocked", OWNER, moved.note)
                raise SelfChangeError("the target changed since the proposal; propose it again")
            applied = self._apply(change, actor=OWNER, to=State.LIVE, note="approved by the owner")
            outcome = "executed" if applied.state is State.LIVE else "failed"
            self._log(applied, "approve", outcome, OWNER)
            return applied

    def reject(self, change_id: str) -> Change:
        with self._lock:
            change = self._get(change_id)
            if change.state is not State.PROPOSED:
                raise SelfChangeError(f"a {change.state.value} change cannot be refused")
            note = "refused by the owner"
            moved = self.store.move(change.id, State.BLOCKED, actor=OWNER, note=note)
            self._log(moved, "reject", "denied", OWNER)
            return moved

    def promote(self, change_id: str) -> Change:
        """Keep a change that is on trial."""
        with self._lock:
            change = self._get(change_id)
            if change.state is not State.TRIAL:
                raise SelfChangeError(f"a {change.state.value} change is not on trial")
            moved = self.store.move(change.id, State.LIVE, actor=OWNER, note="kept by the owner")
            self._log(moved, "promote", "executed", OWNER)
            return moved

    # ---------------------------------------------------------- rollback

    def _newer_active(self, change: Change) -> list[Change]:
        return [
            c
            for c in self.store.list(states=tuple(ACTIVE_STATES), limit=500)
            if c.surface is change.surface and c.target == change.target and c.seq > change.seq
        ]

    def _revert_one(self, change: Change, actor: str) -> Change:
        if change.ref.startswith(MIRROR_PREFIX):
            if self._external is None:
                raise SelfChangeError("nothing can revert this self-built change here")
            self._external(change)
        else:
            handler = self._handler(change.surface, change.target)
            handler.write(change.target, change.before)
        moved = self.store.move(change.id, State.REVERTED, actor=actor, note="rolled back")
        self._log(moved, "rollback", "executed", actor)
        return moved

    def rollback(self, change_id: str, actor: str = OWNER) -> list[Change]:
        """Restore the exact text from before this change (newer changes on the target go first)."""
        with self._lock:
            change = self._get(change_id)
            if change.state not in ACTIVE_STATES:
                raise SelfChangeError(f"a {change.state.value} change is not in effect")
            newer = sorted(self._newer_active(change), key=lambda c: -c.seq)
            done = [self._revert_one(c, actor) for c in newer]
            done.append(self._revert_one(change, actor))
            self._say(done[-1], f"I put my {self._label(change)} back to how it was before.")
            return done

    def rollback_since(self, since_ms: int, actor: str = OWNER) -> list[Change]:
        """Revert every change still in effect that was recorded at or after ``since_ms``."""
        with self._lock:
            active = [
                c
                for c in self.store.list(since_ms=since_ms, states=tuple(ACTIVE_STATES), limit=1000)
            ]
            done: list[Change] = []
            for change in sorted(active, key=lambda c: -c.seq):
                if self.store.get(change.id).state in ACTIVE_STATES:  # type: ignore[union-attr]
                    done.append(self._revert_one(change, actor))
            if done:
                self._say(done[0], f"I reverted {len(done)} of my own changes since you asked.")
            return done

    # ---------------------------------------------- self-build mirror

    def note_external(
        self,
        *,
        surface: Surface,
        ref: str,
        title: str,
        state: State,
        author: str,
        gate: dict[str, Any] | None = None,
        core: bool = False,
    ) -> Change:
        """Mirror a change another ledger applied and checked itself (a self-built artefact).

        The registry never applies these; it records them with their proof, keeps the state
        in step and reverts them through the owner of the artefact.
        """
        with self._lock:
            existing = self.store.by_ref(ref)
            if existing is None:
                return self.store.add(
                    surface=surface,
                    target=ref,
                    before=None,
                    after=None,
                    diff="",
                    author=author,
                    turn="",
                    reason=title,
                    state=state,
                    core=core,
                    core_reasons=[],
                    gate=gate or {},
                    ref=ref,
                )
            if existing.state is not state:
                if gate:
                    self.store.set_gate(existing.id, gate)
                return self.store.move(existing.id, state, actor=author, note=title[:200])
            return existing

    # ------------------------------------------------------------- reads

    def list(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return [c.public() for c in self.store.list(limit=limit)]

    def detail(self, change_id: str) -> dict[str, Any]:
        change = self._get(change_id)
        out = change.public(with_text=True)
        out["history"] = self.store.history(change_id)
        out["evaluations"] = self.store.evaluations(change_id=change_id)
        return out

    def summary(self) -> dict[str, Any]:
        """The numbers theory criterion 14 asks for."""
        rows = self.store.list(limit=5000)
        count = lambda *states: sum(1 for r in rows if r.state in states)  # noqa: E731
        return {
            "total": len(rows),
            "waiting": count(State.PROPOSED),
            "on_trial": count(State.TRIAL),
            "live": count(State.LIVE),
            "reverted": count(State.REVERTED),
            "blocked": count(State.BLOCKED),
            "now_ms": int(time.time() * 1000),
        }
