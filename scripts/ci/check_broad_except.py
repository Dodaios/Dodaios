"""Broad-except ratchet: per-file count of ``except Exception``/``BaseException``/bare ``except:``.

A handler whose ``except`` line carries ``# broad-except: <reason>`` is a
decision somebody wrote down and does not count. Covered by
``tests/unit/ci/test_ratchet_gates.py``.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet as r  # noqa: E402

_BROAD = {"Exception", "BaseException"}
_MARK = re.compile(r"#\s*broad-except:\s*\S")


def _is_broad(node: ast.expr | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in _BROAD
    if isinstance(node, ast.Attribute):
        return node.attr in _BROAD
    if isinstance(node, ast.Tuple):
        return any(_is_broad(e) for e in node.elts)
    return False


def count_file(path: Path) -> int:
    lines = r.read_text(path).splitlines()
    n = 0
    for node in ast.walk(r.parse(path)):
        if isinstance(node, ast.ExceptHandler) and _is_broad(node.type):
            line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            if not _MARK.search(line):
                n += 1
    return n


def scan() -> dict[str, int]:
    out: dict[str, int] = {}
    paths = list(r.python_files("dodaios"))
    for path, n in zip(paths, r.pmap(count_file, paths), strict=True):
        if n:
            out[r.rel(path)] = n
    return out


def main(argv: list[str] | None = None) -> int:
    return r.run(
        "broad-except",
        scan,
        "broad-except-baseline.json",
        "handlers",
        "No new `except Exception` / `except BaseException` / bare `except:` in dodaios/.",
        "catch the specific exception types the call can raise; if a broad catch is truly "
        "right (a plugin boundary, a top-level loop), add `# broad-except: <reason>` on the "
        "except line.",
        argv,
    )


if __name__ == "__main__":
    sys.exit(main())
