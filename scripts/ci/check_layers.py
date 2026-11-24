"""Layer gate: lower layers must not import higher ones.

Layers (``scripts/ci/layers.json``), lowest first::

    foundation = platform, i18n, assets
    core
    middle     = every other ``dodaios`` package or module
    ui

Rules, all static (``ast``; the app is never imported):

* A -- a module in a lower layer must not import a higher layer at MODULE
  level (top level, class bodies, ``try``/``if`` blocks; ``if TYPE_CHECKING``
  is skipped, it never runs). Imports inside functions are counted separately
  as a softer baseline (``function_level``): they do not run at import time,
  but they still tie the layers together.
* B -- ``dodaios/plugins/`` may import only core, platform, i18n and itself
  (the plugin API is ``dodaios.core.protocols`` plus the entry-point loader
  ``dodaios.core.entry_points``), and ``dodaios.core`` must not import a
  specific plugin.
* C -- the size of the largest import cycle between top-level ``dodaios``
  packages (module-level imports only) may not grow.

Existing violations live in ``scripts/ci/layers-baseline.json``; the lists
may only shrink (``--update`` re-baselines downwards, never upwards).

How to fix a violation: move the shared name (constant, dataclass, enum) DOWN
into the lower layer and let the higher module import it from there; or invert
the dependency -- the lower layer publishes an event or calls a registered
callback (``dodaios/core/events.py``) and the higher layer subscribes.

Usage::

    python scripts/ci/check_layers.py            # gate
    python scripts/ci/check_layers.py --report   # list every violation
    python scripts/ci/check_layers.py --update   # re-baseline (lower only)
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent
_CONFIG = _HERE / "layers.json"
_BASELINE = _HERE / "layers-baseline.json"
_ROOT = "dodaios"


def load_config(path: Path = _CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def layer_of(pkg: str, cfg: dict) -> int:
    """Rank of a top-level package/module name (0 = lowest)."""
    for rank, names in enumerate(cfg["layers"]):
        if pkg in names:
            return rank
    return cfg["default_layer"]


def _module_name(path: Path, root: Path) -> tuple[str, bool]:
    parts = list(path.relative_to(root).with_suffix("").parts)
    is_pkg = parts[-1] == "__init__"
    if is_pkg:
        parts.pop()
    return ".".join(parts), is_pkg


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _targets(node: ast.stmt, module: str, is_pkg: bool) -> list[str]:
    """Dotted names of the ``dodaios`` modules an import statement reaches."""
    out: list[str] = []
    if isinstance(node, ast.Import):
        out = [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom):
        if node.level:
            base = module.split(".")
            if not is_pkg:
                base = base[:-1]
            if node.level > 1:
                base = base[: len(base) - (node.level - 1)]
            mod = ".".join(base + ([node.module] if node.module else []))
        else:
            mod = node.module or ""
        if mod:
            out = [mod] + [f"{mod}.{a.name}" for a in node.names if a.name != "*"]
    return [t for t in out if t == _ROOT or t.startswith(_ROOT + ".")]


def _walk(body: list[ast.stmt], in_func: bool):
    """Yield ``(import_node, in_func)`` for every import under *body*."""
    for node in body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            yield node, in_func
        elif isinstance(node, ast.If) and _is_type_checking(node.test):
            yield from _walk(node.orelse, in_func)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _walk(node.body, True)
        else:
            for field in ("body", "orelse", "finalbody"):
                sub = getattr(node, field, None)
                if isinstance(sub, list):
                    yield from _walk(sub, in_func)
            for handler in getattr(node, "handlers", None) or []:
                yield from _walk(handler.body, in_func)
            for case in getattr(node, "cases", None) or []:
                yield from _walk(case.body, in_func)


def collect_edges(root: Path = _REPO) -> list[dict]:
    """Every import edge: ``{src, dst, line, func}`` (dotted module names)."""
    edges: list[dict] = []
    for path in sorted((root / _ROOT).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module, is_pkg = _module_name(path, root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="ignore"))
        except SyntaxError:
            continue
        for node, in_func in _walk(tree.body, False):
            for dst in _targets(node, module, is_pkg):
                edges.append({"src": module, "dst": dst, "line": node.lineno, "func": in_func})
    return edges


def _top(name: str) -> str:
    parts = name.split(".")
    return parts[1] if len(parts) > 1 else ""


def _is_plugin(name: str) -> bool:
    return name.startswith("dodaios.plugins.")


def violations(edges: list[dict], cfg: dict) -> dict[str, list[str]]:
    """Rule A/B violations, keyed ``module_level`` / ``function_level``."""
    out: dict[str, set[str]] = {"module_level": set(), "function_level": set()}
    allowed = set(cfg["plugin_allowed"])
    for e in edges:
        src_top, dst_top = _top(e["src"]), _top(e["dst"])
        if not src_top or not dst_top:
            continue
        # Report the destination as a package (or a plugin), not a symbol.
        short = ".".join(e["dst"].split(".")[: 3 if _is_plugin(e["dst"]) else 2])
        e = {**e, "dst": short}
        entry = None
        if _is_plugin(e["src"]):
            if dst_top not in allowed:
                entry = f"{e['src']} -> {e['dst']} [B: a plugin may import only core/platform/i18n]"
        elif src_top == "core" and _is_plugin(e["dst"]):
            entry = f"{e['src']} -> {e['dst']} [B: core must not import a specific plugin]"
        if entry is None and layer_of(src_top, cfg) < layer_of(dst_top, cfg):
            entry = f"{e['src']} -> {e['dst']} [A: {src_top} is a lower layer than {dst_top}]"
        if entry:
            out["function_level" if e["func"] else "module_level"].add(entry)
    return {k: sorted(v) for k, v in out.items()}


def largest_cycle(edges: list[dict]) -> tuple[int, list[str]]:
    """Size and members of the largest cycle (SCC) of the package graph."""
    graph: dict[str, set[str]] = {}
    for e in edges:
        if e["func"]:
            continue
        a, b = _top(e["src"]), _top(e["dst"])
        if a and b:
            graph.setdefault(a, set())
            graph.setdefault(b, set())
            if a != b:
                graph[a].add(b)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    best: list[str] = []
    counter = 0
    for start in sorted(graph):
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on.add(start)
        work = [(start, iter(sorted(graph[start])))]
        while work:
            node, it = work[-1]
            pushed = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(graph[w]))))
                    pushed = True
                    break
                if w in on:
                    low[node] = min(low[node], index[w])
            if pushed:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > len(best):
                    best = comp
    return (len(best) if len(best) > 1 else 0), sorted(best)


def scan(root: Path = _REPO, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    edges = collect_edges(root)
    found = violations(edges, cfg)
    size, members = largest_cycle(edges)
    return {
        "largest_cycle_size": size,
        "module_level": found["module_level"],
        "function_level": found["function_level"],
        "_cycle_members": members,
    }


_HOWTO = (
    "Fix: move the shared name (constant, dataclass, enum) DOWN into the lower layer and "
    "import it from there in the higher module, or invert the dependency (the lower layer "
    "emits an event / calls a registered callback, see dodaios/core/events.py). "
    "Layers are defined in scripts/ci/layers.json."
)


def compare(current: dict, baseline: dict) -> list[str]:
    """Human-readable failures; empty when nothing got worse."""
    errors: list[str] = []
    for key, label in (("module_level", "module-level"), ("function_level", "function-level")):
        new = sorted(set(current[key]) - set(baseline.get(key, [])))
        if new:
            errors.append(f"{len(new)} new {label} layer violation(s):")
            errors.extend(f"  {line}" for line in new)
    old_cycle = baseline.get("largest_cycle_size", 0)
    if current["largest_cycle_size"] > old_cycle:
        errors.append(
            f"largest import cycle between packages grew to {current['largest_cycle_size']} "
            f"(baseline {old_cycle}): {', '.join(current['_cycle_members'])}"
        )
    if errors:
        errors.append(_HOWTO)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Layer gate for dodaios imports")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args(argv)
    current = scan()
    baseline = json.loads(_BASELINE.read_text(encoding="utf-8")) if _BASELINE.exists() else None
    if args.report:
        for key in ("module_level", "function_level"):
            print(f"== {key} ({len(current[key])})")
            print("\n".join(current[key]))
        print(f"largest cycle: {current['largest_cycle_size']} {current['_cycle_members']}")
        return 0
    if args.update:
        errors = compare(current, baseline) if baseline is not None else []
        if errors:
            print("\n".join(errors), file=sys.stderr)
            print("refusing to raise the baseline", file=sys.stderr)
            return 1
        public = {k: v for k, v in current.items() if not k.startswith("_")}
        _BASELINE.write_text(json.dumps(public, indent=1) + "\n", encoding="utf-8")
        print("baseline updated")
        return 0
    errors = compare(current, baseline or {})
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(
        f"layers: ok ({len(current['module_level'])} module-level, "
        f"{len(current['function_level'])} function-level, cycle {current['largest_cycle_size']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
