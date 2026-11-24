"""The brief domain: does a brief point at where the work turned out to be.

A task is a request the person made and the change that was merged for it
(``check["files"]``: path -> lines changed). A brief for that request is
scored on the files it names:

* **found**: the share of the change, in lines, that lies in files the brief
  names;
* **astray**: of the paths the brief names, the share the change did not
  touch.

The score is the balance of the two (the harmonic mean of ``found`` and
``1 - astray``). A brief that names the one file most of the work was in
scores well, a brief that lists every file in sight does not, and a brief that
names no file scores 0: it left the agent to find the place by itself.

A file is named by its path, by its file name where that name tells files
apart (``__init__.py`` does not), or, for Python, by its dotted module.

Not scored yet: whether the brief already said what the person had to add
afterwards (``check["told_later"]``). That needs a judge.

The cost of a brief is its length in tokens (characters / 4), which the gate
holds against a gain. Writing the brief is not part of this module:
:func:`score` takes the text.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Final

from .model import Task
from .recall import Scored

__all__ = ["score"]

_CHARS_PER_TOKEN: Final = 4
#: File names many folders have: naming one says nothing without its folder.
_SHARED_NAMES: Final = frozenset(
    {
        "__init__.py",
        "__main__.py",
        "conftest.py",
        "index.js",
        "index.ts",
        "index.tsx",
        "main.py",
        "mod.rs",
        "readme.md",
        "types.ts",
        "utils.py",
    }
)
#: A path in running text: at least one folder, then a file name with an extension.
_PATH: Final = re.compile(r"(?<![\w./-])((?:[\w.@-]+/)+[\w.@-]+\.[a-z0-9]{1,5})(?![\w/-])")
_MISSED_SHOWN: Final = 3


def _flat(text: str) -> str:
    return text.replace("\\", "/").lower()


def _names(flat: str, path: str) -> bool:
    """Whether the brief (lower case, forward slashes) names the file at ``path``."""
    posix = PurePosixPath(path.lower())
    if str(posix) in flat:
        return True
    name = posix.name
    if name in _SHARED_NAMES:
        return f"{posix.parent.name}/{name}" in flat
    if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-])", flat):
        return True
    return posix.suffix == ".py" and ".".join(posix.with_suffix("").parts) in flat


def _same_file(named: str, changed: str) -> bool:
    """A brief may write a path from a folder further down (``bench/model.py``), or from
    further up: the clone's own folder in front (``personal jarvis/dodaios/x.py``)."""
    return named == changed or changed.endswith("/" + named) or named.endswith("/" + changed)


def score(task: Task, brief: str) -> Scored:
    """Score the text of one brief against the change that was merged for its request."""
    tokens = round(len(brief) / _CHARS_PER_TOKEN)
    files = task.check.get("files")
    weights: dict[str, int] = (
        {str(path).replace("\\", "/"): max(1, int(lines)) for path, lines in files.items()}
        if isinstance(files, Mapping)
        else {}
    )
    if not weights:
        raise LookupError(f"{task.id} names no changed file to score a brief against")
    flat = _flat(brief)
    hit = {path for path in weights if _names(flat, path)}
    total = sum(weights.values())
    found = sum(weights[path] for path in hit) / total
    changed = [path.lower() for path in weights]
    pointed = set(_PATH.findall(flat))
    astray = [named for named in pointed if not any(_same_file(named, c) for c in changed)]
    on_target = 1.0 - (len(astray) / len(pointed) if pointed else 0.0)
    balance = 2 * found * on_target / (found + on_target) if found and on_target else 0.0
    missed = sorted((path for path in weights if path not in hit), key=lambda p: -weights[p])
    notes = [f"found {found:.2f} of the change"]
    if astray:
        notes.append(f"{len(astray)} of {len(pointed)} named paths not touched")
    if missed:
        notes.append("not named: " + ", ".join(missed[:_MISSED_SHOWN]))
    return Scored(round(balance, 4), tokens, "; ".join(notes))
