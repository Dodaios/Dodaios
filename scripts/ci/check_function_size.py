"""Function-size ratchet: Python functions max 300 lines, cyclomatic complexity max 20.

Keys are ``path::qualname`` (complexity entries ``path::qualname#complexity``).
Complexity is 1 plus the branch points (if, for, while, except, boolean
operators, conditional expressions, comprehension clauses, match cases),
counted per function without its nested functions. Covered by
``tests/unit/ci/test_ratchet_gates.py``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet as r  # noqa: E402

MAX_LINES = 300
MAX_COMPLEXITY = 20
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def complexity(func: ast.AST) -> int:
    score = 1
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (*_FUNCS, ast.Lambda, ast.ClassDef)):
            continue
        branch = (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)
        if isinstance(node, branch):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            score += 1 + len(node.ifs)
        elif isinstance(node, ast.match_case):
            score += 1
        stack.extend(ast.iter_child_nodes(node))
    return score


def functions(tree: ast.AST, prefix: str = ""):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, _FUNCS):
            qual = prefix + node.name
            yield qual, node
            yield from functions(node, qual + ".<locals>.")
        elif isinstance(node, ast.ClassDef):
            yield from functions(node, prefix + node.name + ".")
        else:
            yield from functions(node, prefix)


def scan_file(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    rp = r.rel(path)
    for qual, node in functions(r.parse(path)):
        size = (node.end_lineno or node.lineno) - node.lineno + 1
        if size > MAX_LINES:
            key = f"{rp}::{qual}"
            out[key] = max(out.get(key, 0), size)
        cx = complexity(node)
        if cx > MAX_COMPLEXITY:
            key = f"{rp}::{qual}#complexity"
            out[key] = max(out.get(key, 0), cx)
    return out


def scan() -> dict[str, int]:
    out: dict[str, int] = {}
    for found in r.pmap(scan_file, list(r.python_files("dodaios"))):
        out.update(found)
    return out


def main(argv: list[str] | None = None) -> int:
    return r.run(
        "function-size",
        scan,
        "function-size-baseline.json",
        "lines/branches",
        f"Python functions stay under {MAX_LINES} lines and complexity {MAX_COMPLEXITY}.",
        "split the function into named steps (extract a helper per branch or phase); "
        "do not raise the baseline.",
        argv,
    )


if __name__ == "__main__":
    sys.exit(main())
