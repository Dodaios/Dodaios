"""File-size ratchet: Python files in dodaios/ max 2000 lines, TS/TSX max 1000.

Tests are excluded. The baseline lists every file already over its limit with
its current line count; it may only shrink. Covered by
``tests/unit/ci/test_ratchet_gates.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet as r  # noqa: E402

PY_LIMIT = 2000
TS_LIMIT = 1000
FRONTEND = "dodaios/ui/web/frontend/src"


def _lines(path: Path) -> int:
    return len(r.read_text(path).splitlines())


def scan() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in r.python_files("dodaios"):
        n = _lines(path)
        if n > PY_LIMIT:
            out[r.rel(path)] = n
    for path in r.walk_files(FRONTEND, (".ts", ".tsx")):
        if r.is_test_path(path) or path.name.endswith(".d.ts"):
            continue
        n = _lines(path)
        if n > TS_LIMIT:
            out[r.rel(path)] = n
    return out


def main(argv: list[str] | None = None) -> int:
    return r.run(
        "file-size",
        scan,
        "file-size-baseline.json",
        "lines",
        f"Python files in dodaios/ stay under {PY_LIMIT} lines, TS/TSX under {TS_LIMIT}.",
        "split the file along a seam (one responsibility per module) and move the code out; "
        "do not raise the baseline.",
        argv,
    )


if __name__ == "__main__":
    sys.exit(main())
