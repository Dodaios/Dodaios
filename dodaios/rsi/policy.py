"""A coding policy: how the app steers the coding runs of one cell.

A policy is small, declarative and content-addressed (its id is a hash of its
canonical JSON), so a run records exactly which one it ran under. Three parts:

* **H, hold:** whether the app holds a run of this cell until its output was
  checked. A run that holds is not over for the lead before its verdict, and a
  finding brings it a follow-up order. A run that does not hold is judged all
  the same (scan, evidence, verdict), but the lead's job ends with the turn
  and nothing is sent to the agent. The factory policy does not hold.

* **O, steering parameters** the app applies after a turn: how many follow-up
  orders a run may get (``p_max``, never above the code's own limit) and how
  long the checks are waited for (``evidence_wait_s``, never above it either).
  A policy can choose less, never more.
* **T, turn material:** ``domain_block``, at most 600 characters a run's first
  brief would carry. It is empty in every policy the app makes on its own;
  text changes wait for the person's approval (decision 5.4).

What is checked, the review's triggers and the audit rate are not part of a
policy: a policy that checked less would always look cheaper.

Policies live as self-changes (surface ``coding_policy``): one target per cell
for the active policy (``<cell>#active``) and one for a candidate on trial
(``<cell>#candidate``), each with versions, a diff and a byte-exact rollback in
Trust → Self-changes. The registry writes them through :class:`PolicyStore`.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "ACTIVE",
    "CANDIDATE",
    "DEFAULT",
    "MAX_BLOCK_CHARS",
    "Policy",
    "PolicyError",
    "PolicyStore",
    "store_for",
    "target_for",
]

MAX_BLOCK_CHARS: Final[int] = 600
ACTIVE: Final[str] = "active"
CANDIDATE: Final[str] = "candidate"
#: Words that make a domain block weaken the work instead of guiding it.
_WEAKENING = re.compile(
    r"\b(skip|disable|ignore|silence|suppress|delete|remove|loosen|xfail)\b[^.\n]{0,40}"
    r"\b(tests?|checks?|lint|types?|assertions?|warnings?|ci|hooks?)\b"
    r"|--no-verify|\bnoqa\b|type:\s*ignore|eslint-disable",
    re.IGNORECASE,
)


class PolicyError(ValueError):
    """A policy text that is not a valid policy."""


@dataclass(frozen=True, slots=True)
class Policy:
    """How the coding runs of one cell are steered."""

    #: Follow-up orders a run may get, at most ``driver.MAX_FOLLOW_UPS``.
    p_max: int = 2
    #: Seconds the checks of an output are waited for, at most ``driver.EVIDENCE_WAIT_S``.
    evidence_wait_s: int = 45 * 60
    #: Text a run's first brief carries; empty unless the person approved one.
    domain_block: str = ""
    #: The run is held until its output was checked, and a finding brings a
    #: follow-up order. ``False``: judged only, nothing is held or sent.
    hold: bool = False

    def __post_init__(self) -> None:
        from dodaios.orchestrator.verification import driver

        if not isinstance(self.hold, bool):
            raise PolicyError("hold must be true or false")
        if not 0 <= int(self.p_max) <= driver.MAX_FOLLOW_UPS:
            raise PolicyError(f"p_max must be 0 to {driver.MAX_FOLLOW_UPS}")
        if not 60 <= int(self.evidence_wait_s) <= driver.EVIDENCE_WAIT_S:
            raise PolicyError(f"evidence_wait_s must be 60 to {driver.EVIDENCE_WAIT_S}")
        if len(self.domain_block) > MAX_BLOCK_CHARS:
            raise PolicyError(f"the domain block is longer than {MAX_BLOCK_CHARS} characters")
        if _WEAKENING.search(self.domain_block):
            raise PolicyError("the domain block tells agents to weaken the checks")

    def to_text(self) -> str:
        """The canonical JSON the registry stores and the id is taken from.

        ``hold`` is written only when it is set, so a policy stored before the
        field existed keeps its text and its id.
        """
        data = asdict(self)
        if not self.hold:
            del data["hold"]
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    @property
    def id(self) -> str:
        return "pol_" + hashlib.sha256(self.to_text().encode()).hexdigest()[:12]

    @classmethod
    def from_text(cls, text: str | None) -> Policy:
        """The policy a stored text describes; the default for none."""
        if not text:
            return DEFAULT
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise PolicyError("the policy is not JSON") from exc
        if not isinstance(data, dict):
            raise PolicyError("the policy is not a JSON object")
        unknown = set(data) - {"p_max", "evidence_wait_s", "domain_block", "hold"}
        if unknown:
            raise PolicyError(f"unknown policy fields: {sorted(unknown)}")
        try:
            return cls(
                p_max=int(data.get("p_max", DEFAULT.p_max)),
                evidence_wait_s=int(data.get("evidence_wait_s", DEFAULT.evidence_wait_s)),
                domain_block=str(data.get("domain_block") or ""),
                # Absent in a policy stored before the field existed: it does not hold.
                hold=data.get("hold", False),
            )
        except (TypeError, ValueError) as exc:
            raise PolicyError(str(exc)) from exc


DEFAULT: Final[Policy] = Policy()


def target_for(cell: str, slot: str) -> str:
    """The self-change target of a cell's active policy or its candidate."""
    if slot not in (ACTIVE, CANDIDATE):
        raise ValueError(f"unknown policy slot: {slot!r}")
    return f"{cell}#{slot}"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    target      TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    updated_ms  INTEGER NOT NULL
);
"""


_stores: dict[str, PolicyStore] = {}
_stores_lock = threading.Lock()


def store_for(data_dir: Path | str) -> PolicyStore:
    """The one policy store of a data directory, shared by the registry and the binding."""
    path = str(Path(data_dir) / "rsi.db")
    with _stores_lock:
        found = _stores.get(path)
        if found is None:
            found = _stores[path] = PolicyStore(path)
        return found


class PolicyStore:
    """Where the registry writes policies; the self-change handler of ``coding_policy``."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        with self._lock:
            if self._path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --------------------------------------------------- the handler protocol

    def read(self, target: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT text FROM policies WHERE target = ?", (target,)
            ).fetchone()
        return str(row[0]) if row is not None else None

    def write(self, target: str, text: str | None) -> None:
        if text is not None:
            Policy.from_text(text)  # never stores what is not a policy
        with self._lock:
            if text is None:
                self._conn.execute("DELETE FROM policies WHERE target = ?", (target,))
            else:
                self._conn.execute(
                    "INSERT INTO policies (target, text, updated_ms) VALUES (?, ?, ?) "
                    "ON CONFLICT(target) DO UPDATE SET text = excluded.text, "
                    "updated_ms = excluded.updated_ms",
                    (target, text, int(time.time() * 1000)),
                )
            self._conn.commit()

    # ------------------------------------------------------------- reading

    def policy(self, cell: str, slot: str = ACTIVE) -> Policy | None:
        """The cell's policy in ``slot``; ``None`` when there is none (or it is unreadable)."""
        text = self.read(target_for(cell, slot))
        if text is None:
            return None
        try:
            return Policy.from_text(text)
        except PolicyError:  # a damaged entry binds nothing: the default applies
            return None

    def cells(self) -> dict[str, dict[str, Any]]:
        """Every cell with a stored policy: ``{cell: {slot: policy id}}``."""
        with self._lock:
            rows = self._conn.execute("SELECT target, text FROM policies").fetchall()
        out: dict[str, dict[str, Any]] = {}
        for target, text in rows:
            cell, _, slot = str(target).rpartition("#")
            try:
                out.setdefault(cell, {})[slot] = Policy.from_text(text).id
            except PolicyError:  # listed as what it is, so the report shows it
                out.setdefault(cell, {})[slot] = "(unreadable)"
        return out
