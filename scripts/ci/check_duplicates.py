"""Duplicate-code ratchet: copy-pasted blocks of at least 12 identical normalized lines.

Scans ``dodaios/**/*.py`` and the frontend ``src/**/*.{ts,tsx}`` (tests excluded).
Lines are normalized (whitespace collapsed; comments, imports and punctuation-only
lines dropped), then a 12-line window slides over each file and is hashed. A window
that occurs at another place (another file, or the same file 12+ lines away) marks its
lines as duplicated. The baseline holds the duplicated line count per file and may only
shrink. ``--clusters`` prints the biggest duplicated file pairs as cleanup leads.
Covered by ``tests/unit/ci/test_frontend_gates.py``.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet as r  # noqa: E402

WINDOW = 12
FRONTEND = "dodaios/ui/web/frontend/src"
_SKIP_PREFIX = ("#", "//", "/*", "*", "import ", "from ", "@", '"""', "'''")
_PUNCT = re.compile(r"^[\W_]*$")


def normalize(source: str) -> list[tuple[int, str]]:
    """Return ``(line number, normalized text)`` for the lines that carry meaning."""
    out: list[tuple[int, str]] = []
    for no, raw in enumerate(source.splitlines(), 1):
        line = " ".join(raw.split())
        if not line or line.startswith(_SKIP_PREFIX) or _PUNCT.match(line):
            continue
        if line.startswith("export ") and " from " in line:
            continue
        out.append((no, line))
    return out


def find_duplicates(files: dict[str, str]) -> dict[tuple[str, str], list[tuple[int, int]]]:
    """Map ``(file_a, file_b)`` to merged duplicated line ranges ``(start, end)`` in ``file_a``."""
    seqs = {name: normalize(text) for name, text in files.items()}
    index: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for name, seq in seqs.items():
        texts = [t for _, t in seq]
        for i in range(len(texts) - WINDOW + 1):
            index[hash(tuple(texts[i : i + WINDOW]))].append((name, i))
    hits: dict[tuple[str, str], set[int]] = defaultdict(set)
    for places in index.values():
        if len(places) < 2:
            continue
        for name, i in places:
            for other, j in places:
                if (name, i) != (other, j) and (name != other or abs(i - j) >= WINDOW):
                    hits[(name, other)].add(i)
    out: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for pair, starts in hits.items():
        seq = seqs[pair[0]]
        runs: list[tuple[int, int]] = []  # normalized-line indices, inclusive
        for i in sorted(starts):
            if runs and i <= runs[-1][1] + 1:
                runs[-1] = (runs[-1][0], max(runs[-1][1], i + WINDOW - 1))
            else:
                runs.append((i, i + WINDOW - 1))
        out[pair] = [(seq[a][0], seq[b][0]) for a, b in runs]
    return out


def _lines_of(runs: list[tuple[int, int]]) -> int:
    return sum(b - a + 1 for a, b in runs)


def _collect() -> dict[str, str]:
    files: dict[str, str] = {}
    for path in r.python_files("dodaios"):
        files[r.rel(path)] = r.read_text(path)
    for path in r.walk_files(FRONTEND, (".ts", ".tsx")):
        if r.is_test_path(path) or path.name.endswith(".d.ts"):
            continue
        files[r.rel(path)] = r.read_text(path)
    return files


def scan() -> dict[str, int]:
    per_file: dict[str, set[int]] = defaultdict(set)
    for (name, _other), runs in find_duplicates(_collect()).items():
        for a, b in runs:
            per_file[name].update(range(a, b + 1))
    return {name: len(lines) for name, lines in per_file.items()}


def clusters(top: int = 10) -> int:
    pairs = find_duplicates(_collect())
    seen: set[frozenset[str]] = set()
    rows = []
    for (a, b), runs in sorted(pairs.items(), key=lambda kv: -_lines_of(kv[1])):
        key = frozenset((a, b))
        if key in seen:
            continue
        seen.add(key)
        rows.append((_lines_of(runs), a, b, runs))
    for n, a, b, runs in rows[:top]:
        spans = ", ".join(f"{s}-{e}" for s, e in runs[:4])
        print(f"{n:5d} lines  {a}  <->  {b}  (lines {spans})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--clusters" in args:
        return clusters()
    return r.run(
        "duplicates",
        scan,
        "duplicates-baseline.json",
        "duplicated lines",
        f"No new copy-pasted block of {WINDOW}+ identical lines in dodaios/ (Python, TS/TSX).",
        "move the shared block into one function or module and call it from both places; "
        "check `python scripts/ci/check_duplicates.py --clusters` for the biggest pairs.",
        argv,
    )


if __name__ == "__main__":
    sys.exit(main())
