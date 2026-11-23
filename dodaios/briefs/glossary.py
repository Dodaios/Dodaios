"""The person's own words for the parts of a project, remembered per project.

A person does not call things what the code calls them, least of all when they
dictate: "the side bar", "the wake thing", a product name the recogniser
mishears the same way every time. The first time such a word is resolved, the
writer of the brief had to work it out from the screen, the conversation or
the code. This store keeps that answer, so the next brief starts from it: each
entry says what was said and what it stands for in this project (a component,
a file, a feature by its name in the code).

One small JSON file per project in the app's data directory. The project is
the repository (``dodaios.rsi.repo_identity``), so a worktree and the main
checkout share one glossary; the file is named by a hash of that id, never by
the id or a folder. Entries are data the person and their assistant wrote,
and they are shown to a brief writer as data.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "MAX_ENTRIES",
    "MAX_SAID_WORDS",
    "is_term",
    "Entry",
    "all_projects",
    "entries",
    "forget",
    "forget_in_project",
    "learn",
    "lookup",
    "project_of",
    "store_path",
]

log = logging.getLogger(__name__)

_DIRNAME: Final[str] = "brief_glossary"
MAX_ENTRIES: Final[int] = 200
_MAX_SAID: Final[int] = 80
#: A glossary entry is one of the person's words or a short name for a thing.
#: Real use (2026-11-23) showed writers storing whole sentences and rules
#: ("the agent should ask you first" -> "agents cannot ask live, write the
#: answer into the brief"); such an entry is matched into later kits and
#: carries a decision, possibly a wrong one, into every next brief.
MAX_SAID_WORDS: Final[int] = 4
_MAX_MEANS: Final[int] = 240
#: A said word shorter than this is matched exactly only: short words collide.
_FUZZY_MIN_CHARS: Final[int] = 6
_FUZZY_CUTOFF: Final[float] = 0.84
_LOCK = threading.Lock()
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Entry:
    """What the person says, and what it stands for in this project."""

    said: str
    means: str
    hits: int = 0
    updated: float = 0.0

    def as_dict(self) -> dict[str, str]:
        return {"said": self.said, "means": self.means}


def _clean(text: str, limit: int) -> str:
    return " ".join(_CONTROL.sub(" ", str(text or "")).split())[:limit].strip()


def project_of(folder: str | Path) -> str:
    """The project a folder belongs to: its repository, else the folder itself."""
    try:
        from dodaios.rsi.repo_identity import repo_id

        return repo_id(folder)
    except Exception:  # noqa: BLE001 - without git facts the folder itself is the project
        return "path:" + str(Path(folder).expanduser())


def _store_dir() -> Path:
    from dodaios.core import config as core_config

    return core_config.DATA_DIR / _DIRNAME


def _path_for(project: str) -> Path:
    # Named by a hash: a project id is an address or a path, never a file name.
    return _store_dir() / (hashlib.sha256(project.encode("utf-8")).hexdigest()[:24] + ".json")


def store_path(folder: str | Path) -> Path:
    """Where the glossary of the project in ``folder`` lives (data dir read at call time)."""
    return _path_for(project_of(folder))


def _load(path: Path) -> list[Entry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:  # no file yet: the project has no glossary
        return []
    except (OSError, ValueError):
        log.warning("brief glossary: %s is not readable, treated as empty", path.name)
        return []
    rows = raw.get("entries") if isinstance(raw, dict) else None
    found: list[Entry] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        said = _clean(row.get("said", ""), _MAX_SAID)
        means = _clean(row.get("means", ""), _MAX_MEANS)
        if said and means:
            try:
                hits, updated = int(row.get("hits") or 0), float(row.get("updated") or 0.0)
            except (TypeError, ValueError):  # a damaged counter restarts at zero
                hits, updated = 0, 0.0
            found.append(Entry(said=said, means=means, hits=hits, updated=updated))
    return found


def _save(path: Path, rows: list[Entry], project: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not project:
        try:
            project = str(json.loads(path.read_text(encoding="utf-8")).get("project") or "")
        except (OSError, ValueError, AttributeError):  # a new or damaged file has no name yet
            project = ""
    body = json.dumps(
        {"project": project, "entries": [
            {"said": e.said, "means": e.means, "hits": e.hits, "updated": e.updated}
            for e in rows
        ]},
        ensure_ascii=False, indent=1,
    )
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".glossary.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:  # cleanup only; the original error is re-raised below
            pass
        raise


def entries(folder: str | Path) -> list[Entry]:
    """Every entry of the project's glossary, most used first."""
    with _LOCK:
        rows = _load(store_path(folder))
    return sorted(rows, key=lambda e: (-e.hits, e.said.lower()))


def learn(folder: str | Path, said: str, means: str) -> Entry | None:
    """Remember that ``said`` stands for ``means``; a known word gets the new meaning.

    Returns the stored entry, or ``None`` when either part is empty. The list
    is capped: the entry used least and longest ago goes first.
    """
    said, means = _clean(said, _MAX_SAID), _clean(means, _MAX_MEANS)
    if not said or not means or said.lower() == means.lower():
        return None
    if not is_term(said):
        log.info("brief glossary: %r is no word or short name and is not remembered", said[:60])
        return None
    path = store_path(folder)
    with _LOCK:
        rows = _load(path)
        kept = [e for e in rows if e.said.lower() != said.lower()]
        old = next((e for e in rows if e.said.lower() == said.lower()), None)
        entry = Entry(said=said, means=means, hits=old.hits if old else 0, updated=time.time())
        kept.append(entry)
        if len(kept) > MAX_ENTRIES:
            kept.sort(key=lambda e: (e.hits, e.updated))
            kept = kept[len(kept) - MAX_ENTRIES:]
        _save(path, kept, project_of(folder))
    return entry


def is_term(said: str) -> bool:
    """Whether ``said`` is a word or a short name, which is all an entry may be."""
    return 0 < len((said or "").split()) <= MAX_SAID_WORDS


def forget(folder: str | Path, said: str) -> bool:
    """Drop the entry for ``said``; ``True`` when there was one."""
    wanted = _clean(said, _MAX_SAID).lower()
    path = store_path(folder)
    with _LOCK:
        rows = _load(path)
        kept = [e for e in rows if e.said.lower() != wanted]
        if len(kept) == len(rows):
            return False
        _save(path, kept)
    return True


def _spoken(text: str) -> tuple[str, list[str]]:
    lowered = " ".join(_WORD.findall((text or "").lower()))
    return lowered, lowered.split()


def _occurs(said: str, sentence: str, words: list[str]) -> bool:
    wanted, parts = _spoken(said)
    if not wanted:
        return False
    if f" {wanted} " in f" {sentence} ":
        return True
    if len(wanted) < _FUZZY_MIN_CHARS:
        return False
    # A dictated word arrives misheard: compare against every run of as many
    # words as the entry has.
    size = len(parts)
    for start in range(max(0, len(words) - size + 1)):
        window = " ".join(words[start:start + size])
        if difflib.SequenceMatcher(None, wanted, window).ratio() >= _FUZZY_CUTOFF:
            return True
    return False


def lookup(folder: str | Path, words: str, *, count: bool = True) -> list[Entry]:
    """The entries whose word occurs in ``words``, also when it was misheard.

    ``count`` raises each found entry's use counter, which decides what stays
    when the list is full.
    """
    sentence, tokens = _spoken(words)
    if not sentence:
        return []
    path = store_path(folder)
    with _LOCK:
        rows = _load(path)
        # An entry stored before the limit and longer than it is left out.
        found = [e for e in rows if is_term(e.said) and _occurs(e.said, sentence, tokens)]
        if found and count:
            names = {e.said.lower() for e in found}
            bumped = [
                Entry(e.said, e.means, e.hits + 1, e.updated) if e.said.lower() in names else e
                for e in rows
            ]
            try:
                _save(path, bumped)
            except OSError:
                log.warning("brief glossary: use counters not saved", exc_info=True)
    return found


def all_projects() -> list[dict[str, Any]]:
    """Every project's glossary, for the person to look at: project and entries."""
    found: list[dict[str, Any]] = []
    try:
        files = sorted(_store_dir().glob("*.json"))
    except OSError:  # no store yet: nothing was learned
        return found
    for path in files:
        with _LOCK:
            rows = _load(path)
            try:
                project = str(json.loads(path.read_text(encoding="utf-8")).get("project") or "")
            except (OSError, ValueError, AttributeError):  # unnamed: shown without a project
                project = ""
        if rows:
            found.append({
                "project": project,
                "entries": [
                    e.as_dict() | {"hits": e.hits}
                    for e in sorted(rows, key=lambda e: (-e.hits, e.said.lower()))
                ],
            })
    return found


def forget_in_project(project: str, said: str) -> bool:
    """Drop ``said`` from the glossary of ``project``; ``True`` when it was there."""
    wanted = _clean(said, _MAX_SAID).lower()
    path = _path_for(str(project or ""))
    with _LOCK:
        rows = _load(path)
        kept = [e for e in rows if e.said.lower() != wanted]
        if len(kept) == len(rows):
            return False
        _save(path, kept)
    return True
