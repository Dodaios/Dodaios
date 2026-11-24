"""Source-text-test ratchet: tests that assert on product source TEXT, per file.

A test that reads ``dodaios/...`` source (``read_text``/``open``/``getsource``) and
greps it passes while the behaviour is broken and fails on a harmless rename.
Python: test functions that call ``read_text(``/``open(``/``getsource(`` in a
module that points at ``dodaios/`` (any ``getsource`` counts). Frontend tests:
lines with ``readFileSync`` or a ``?raw`` import. Covered by
``tests/unit/ci/test_ratchet_gates.py``.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet as r  # noqa: E402

FRONTEND = "dodaios/ui/web/frontend/src"
_READ = re.compile(r"\b(read_text|read_bytes|getsource|open)\(")
_POINTS_AT_PRODUCT = re.compile(r"""["']dodaios["']|dodaios[/\\]""")
_FRONT = re.compile(r"readFileSync|\?raw\b")


def count_python(path: Path) -> int:
    text = r.read_text(path)
    if not _READ.search(text):
        return 0
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return 0
    module_hit = bool(_POINTS_AT_PRODUCT.search(text))
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        seg = ast.get_source_segment(text, node) or ""
        if "getsource(" in seg:
            n += 1
        elif module_hit and _READ.search(seg) and "tmp_path" not in {a.arg for a in node.args.args}:
            n += 1
    return n


def count_frontend(path: Path) -> int:
    return sum(1 for ln in r.read_text(path).splitlines() if _FRONT.search(ln))


def scan() -> dict[str, int]:
    out: dict[str, int] = {}
    paths = list(r.python_files("tests", include_tests=True))
    for path, n in zip(paths, r.pmap(count_python, paths), strict=True):
        if n:
            out[r.rel(path)] = n
    for path in r.walk_files(FRONTEND, (".ts", ".tsx")):
        if not r.is_test_path(path):
            continue
        n = count_frontend(path)
        if n:
            out[r.rel(path)] = n
    return out


def main(argv: list[str] | None = None) -> int:
    return r.run(
        "source-text-tests",
        scan,
        "source-text-tests-baseline.json",
        "tests",
        "Tests do not read product source text to assert on it.",
        "test the behaviour instead: call the function, hit the route, render the component. "
        "Reading source passes while the feature is broken.",
        argv,
    )


if __name__ == "__main__":
    sys.exit(main())
