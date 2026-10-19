"""Corrections the user gives a mission while it is running.

A mission's worker is a one-shot process: once started it cannot be told
anything. What the user says meanwhile ("make it dark mode instead", "leave
the tests alone") is kept here, next to the mission's other files, and the
orchestrator hands every correction to the next attempt of every step. A
correction that arrives while an attempt runs makes the mission take one more
attempt instead of finishing on a result the user already changed.

The inbox is an append-only file so a correction survives a restart exactly
like the mission's reflections do.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)
# Steps of one mission run side by side and may note late corrections at once.
_unapplied_lock = threading.Lock()

__all__ = [
    "CORRECTIONS_FILENAME",
    "Correction",
    "CorrectionInbox",
    "render",
    "with_corrections",
]

CORRECTIONS_FILENAME = "corrections.jsonl"
#: One correction is an instruction, not a document.
MAX_CORRECTION_CHARS = 4000


@dataclass(frozen=True, slots=True)
class Correction:
    number: int
    text: str
    ts_ms: int

    def to_dict(self) -> dict:
        return asdict(self)


class CorrectionInbox:
    """The corrections of one mission, oldest first."""

    def __init__(self, mission_dir: Path) -> None:
        self._path = mission_dir / CORRECTIONS_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> list[Correction]:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:  # no correction was given to this mission yet
            return []
        found: list[Correction] = []
        for line in lines:
            try:
                row = json.loads(line)
                text = str(row["text"]).strip()
            except (ValueError, KeyError, TypeError):  # a line torn by a crash: no correction
                continue
            if text:
                found.append(Correction(len(found) + 1, text, int(row.get("ts_ms") or 0)))
        return found

    def add(self, text: str) -> Correction:
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            raise ValueError("A correction needs text.")
        if len(cleaned) > MAX_CORRECTION_CHARS:
            raise ValueError(f"A correction is at most {MAX_CORRECTION_CHARS} characters.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"text": cleaned, "ts_ms": int(time.time() * 1000)}
        # A crash can leave a last line without its line end; start a new line
        # then, or this correction would be glued onto the torn one and lost.
        torn = False
        try:
            with self._path.open("rb") as existing:
                existing.seek(0, os.SEEK_END)
                if existing.tell():
                    existing.seek(-1, os.SEEK_END)
                    torn = existing.read(1) != b"\n"
        except FileNotFoundError:  # the first correction of this mission
            torn = False
        with self._path.open("a", encoding="utf-8") as handle:
            if torn:
                handle.write("\n")
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return self.read()[-1]

    def note_unapplied(self, task_id: str, corrections: list[Correction]) -> None:
        """Record that a step ended before these corrections could reach an attempt."""
        if not corrections:
            return
        with _unapplied_lock:
            late = self._late()
            late.setdefault(task_id, [])
            late[task_id] = sorted({*late[task_id], *(item.number for item in corrections)})
            # Written whole and swapped in, so a reader never sees half a file.
            scratch = self._unapplied_path.with_suffix(".json.tmp")
            scratch.write_text(json.dumps(late), encoding="utf-8")
            os.replace(scratch, self._unapplied_path)

    def unapplied(self) -> list[Correction]:
        """Corrections at least one step finished without, oldest first."""
        numbers = {number for group in self._late().values() for number in group}
        return [item for item in self.read() if item.number in numbers]

    @property
    def _unapplied_path(self) -> Path:
        return self._path.with_name("corrections-unapplied.json")

    def _late(self) -> dict[str, list[int]]:
        try:
            data = json.loads(self._unapplied_path.read_text(encoding="utf-8"))
        except FileNotFoundError:  # nothing came too late so far
            return {}
        except ValueError:
            log.warning("Unreadable record of late corrections: %s", self._unapplied_path)
            return {}
        return data if isinstance(data, dict) else {}


def render(corrections: list[Correction]) -> str:
    """The block a worker and its reviewer read; empty without corrections."""
    if not corrections:
        return ""
    lines = [
        "USER CORRECTIONS - the user changed this task after it was started. Follow "
        "them; where they differ from the task below, the corrections win, and a "
        "later correction wins over an earlier one. Keep everything else of the "
        "task and of the work already done.",
    ]
    lines.extend(f"{item.number}. {item.text}" for item in corrections)
    return "\n".join(lines)


def with_corrections(prompt: str, corrections: list[Correction]) -> str:
    """``prompt`` as its reviewer should judge it once corrections exist."""
    block = render(corrections)
    return f"{prompt}\n\n{block}" if block else prompt
