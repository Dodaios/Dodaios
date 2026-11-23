#!/usr/bin/env python3
"""Print (markdown) and optionally write (JSON) a handful of repo health numbers.

Only files tracked by git are looked at (``git ls-files``).  Run it from
anywhere inside the repository::

    python scripts/health_report.py
    python scripts/health_report.py --json scripts/ci/health-baseline.json

The numbers are meant to be compared over time, not to gate anything.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

CODE_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go", ".sh", ".ps1",
    ".css", ".html", ".swift", ".kt", ".java", ".c", ".cc", ".cpp", ".h",
}  # fmt: skip
BIG_FILE_LINES = 3000
BIG_FUNC_LINES = 200
BIG_BLOB_BYTES = 1024 * 1024
UPPER_LAYERS = ("ui", "speech", "brain", "live", "harness")
ENV_RE = re.compile(r"\b(JARVIS|DODAIOS)_[A-Z0-9_]+\b")
TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore")
SOURCE_READ_RE = re.compile(r"read_text\(|getsource\(")
FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True
    ).stdout.decode("utf-8", "replace")
    return [p for p in out.split("\0") if p]


def read_text(path: Path) -> str | None:
    """Return the file text without a UTF-8 BOM, or None if unreadable."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    text = data.decode("utf-8", "replace")
    return text[1:] if text.startswith("﻿") else text


def parse(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None


def count_lines(text: str) -> int:
    return len(text.splitlines())


def top(items: list[tuple[str, int]], n: int = 10) -> list[dict]:
    ranked = sorted(items, key=lambda t: (-t[1], t[0]))[:n]
    return [{"name": k, "lines": v} for k, v in ranked]


def long_functions(trees: dict[str, ast.AST], limit: int = BIG_FUNC_LINES) -> list[tuple[str, int]]:
    found = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, FUNC_NODES):
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                if length > limit:
                    found.append((f"{path}:{node.lineno} {node.name}", length))
    return found


def _package_of(module: str, packages: set[str]) -> str | None:
    parts = module.split(".")
    if parts[0] != "dodaios" or len(parts) < 2:
        return None
    return parts[1] if parts[1] in packages else None


def _module_parts(path: str) -> list[str]:
    parts = path[:-3].split("/")
    return parts[:-1] if parts[-1] == "__init__" else parts


def _visit_imports(node, module_level, src, base, packages, all_edges, top_edges) -> None:
    for child in ast.iter_child_nodes(node):
        targets: list[str] = []
        if isinstance(child, ast.Import):
            targets = [a.name for a in child.names]
        elif isinstance(child, ast.ImportFrom):
            if child.level:
                up = base[: len(base) - (child.level - 1)]
                name = ".".join(up + ([child.module] if child.module else []))
            else:
                name = child.module or ""
            targets = [name]
            if name == "dodaios":
                targets = [f"dodaios.{a.name}" for a in child.names]
        for target in targets:
            dst = _package_of(target, packages)
            if dst and dst != src:
                all_edges.add((src, dst))
                if module_level:
                    top_edges.add((src, dst))
        deferred = isinstance(child, (*FUNC_NODES, ast.ClassDef, ast.Lambda))
        _visit_imports(
            child, module_level and not deferred, src, base, packages, all_edges, top_edges
        )


def package_edges(trees: dict[str, ast.AST], packages: set[str]) -> tuple[set, set]:
    """Return (all_edges, module_level_edges) between dodaios subpackages."""
    all_edges: set[tuple[str, str]] = set()
    top_edges: set[tuple[str, str]] = set()
    for path, tree in trees.items():
        mod = _module_parts(path)
        if len(mod) < 2 or mod[1] not in packages:
            continue
        base = mod if path.endswith("/__init__.py") else mod[:-1]
        _visit_imports(tree, True, mod[1], base, packages, all_edges, top_edges)
    return all_edges, top_edges


def largest_scc(nodes: set[str], edges: set[tuple[str, str]]) -> list[str]:
    """Tarjan's algorithm (iterative); returns the largest component, sorted."""
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, [])
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    best: list[str] = []
    counter = 0
    for start in sorted(adj):
        if start in index:
            continue
        work = [(start, iter(sorted(adj[start])))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on.add(start)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(sorted(adj[nxt]))))
                    advanced = True
                    break
                if nxt in on:
                    low[node] = min(low[node], index[nxt])
            if advanced:
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
    return sorted(best)


def pattern_counts(texts: dict[str, str], trees: dict[str, ast.AST]) -> dict[str, int]:
    counts = {"except_exception": 0, "bare_except": 0, "type_ignore": 0, "global_statements": 0}
    for path, text in texts.items():
        counts["type_ignore"] += len(TYPE_IGNORE_RE.findall(text))
        tree = trees.get(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    counts["bare_except"] += 1
                elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    counts["except_exception"] += 1
            elif isinstance(node, ast.Global):
                counts["global_statements"] += 1
    return counts


def comment_share(texts: dict[str, str], trees: dict[str, ast.AST]) -> dict:
    total = comment = doc = 0
    for path, text in texts.items():
        lines = text.splitlines()
        total += len(lines)
        comment += sum(1 for ln in lines if ln.lstrip().startswith("#"))
        tree = trees.get(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, *FUNC_NODES)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    doc += (body[0].end_lineno or body[0].lineno) - body[0].lineno + 1
    return {"lines": total, "comment_lines": comment, "docstring_lines": doc}


def share_percent(cs: dict) -> float:
    if not cs["lines"]:
        return 0.0
    return round(100.0 * (cs["comment_lines"] + cs["docstring_lines"]) / cs["lines"], 2)


def env_names(texts: dict[str, str]) -> dict[str, list[str]]:
    names: dict[str, set[str]] = {"JARVIS": set(), "DODAIOS": set()}
    for text in texts.values():
        for m in ENV_RE.finditer(text):
            names[m.group(1)].add(m.group(0))
    return {k: sorted(v) for k, v in names.items()}


def tests_reading_source(texts: dict[str, str], trees: dict[str, ast.AST]) -> dict[str, int]:
    """Count test functions that read dodaios source text (read_text / getsource)."""
    files = funcs = 0
    for path, text in texts.items():
        tree = trees.get(path)
        if tree is None or not (SOURCE_READ_RE.search(text) and "dodaios" in text):
            continue
        lines = text.splitlines()
        hit_file = False
        for node in ast.walk(tree):
            if isinstance(node, FUNC_NODES) and node.name.startswith("test"):
                seg = "\n".join(lines[node.lineno - 1 : node.end_lineno])
                if SOURCE_READ_RE.search(seg) and "dodaios" in seg:
                    funcs += 1
                    hit_file = True
        files += hit_file
    return {"files": files, "test_functions": funcs}


def analyze_file(args: tuple[str, str, frozenset[str]]) -> dict:
    """Read and analyse one tracked file; runs in a worker process."""
    root, rel, packages = args
    text = read_text(Path(root) / rel)
    if text is None:
        return {"path": rel, "missing": True}
    res: dict = {"path": rel, "missing": False, "lines": count_lines(text)}
    if not rel.endswith(".py"):
        return res
    tree = parse(text)
    trees = {rel: tree} if tree is not None else {}
    texts = {rel: text}
    res["jarvis"] = len(re.findall("jarvis", text, re.IGNORECASE))
    res["env"] = env_names(texts)
    res["long_funcs"] = long_functions(trees)
    if rel.startswith("dodaios/"):
        res["patterns"] = pattern_counts(texts, trees)
        res["comments"] = comment_share(texts, trees)
        res["edges"] = [sorted(e) for e in package_edges(trees, set(packages))]
    if rel.startswith("tests/"):
        res["tests_src"] = tests_reading_source(texts, trees)
    return res


def collect(root: Path, workers: int = 0) -> dict:
    tracked = tracked_files(root)
    packages = frozenset(
        p.split("/")[1]
        for p in tracked
        if p.startswith("dodaios/") and p.count("/") >= 2 and p.endswith("/__init__.py")
    )
    wanted = [p for p in tracked if Path(p).suffix in CODE_EXTS]
    jobs = [(str(root), p, packages) for p in wanted]
    if workers == 1:
        results = [analyze_file(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers or None) as pool:
            results = list(pool.map(analyze_file, jobs, chunksize=32))
    results = [r for r in results if not r["missing"]]

    big_files = [(r["path"], r["lines"]) for r in results if r["lines"] > BIG_FILE_LINES]
    big_funcs = [f for r in results for f in r.get("long_funcs", [])]
    dod = [r for r in results if r["path"].startswith("dodaios/") and r["path"].endswith(".py")]

    all_edges: set[tuple[str, str]] = set()
    top_edges: set[tuple[str, str]] = set()
    patterns = {"except_exception": 0, "bare_except": 0, "type_ignore": 0, "global_statements": 0}
    cs = {"lines": 0, "comment_lines": 0, "docstring_lines": 0}
    for r in dod:
        all_part, top_part = r["edges"]
        all_edges.update(map(tuple, all_part))
        top_edges.update(map(tuple, top_part))
        for k in patterns:
            patterns[k] += r["patterns"][k]
        for k in cs:
            cs[k] += r["comments"][k]
    cs["share_percent"] = share_percent(cs)

    env: dict[str, set[str]] = {"JARVIS": set(), "DODAIOS": set()}
    for r in results:
        for k, v in r.get("env", {}).items():
            env[k].update(v)

    blobs = []
    for p in tracked:
        try:
            size = (root / p).stat().st_size
        except OSError:
            continue
        if size > BIG_BLOB_BYTES:
            blobs.append((p, size))
    blobs.sort(key=lambda t: -t[1])

    core_bad = sorted({b for a, b in top_edges if a == "core" and b in UPPER_LAYERS})
    scc_all = largest_scc(set(packages), all_edges)
    scc_top = largest_scc(set(packages), top_edges)
    tests_src = [r["tests_src"] for r in results if "tests_src" in r]

    return {
        "dodaios_python": {
            "lines": sum(r["lines"] for r in dod),
            "modules": len(dod),
            "packages": len(packages),
        },
        "code_files_over_3000_lines": {"count": len(big_files), "top10": top(big_files)},
        "functions_over_200_lines": {"count": len(big_funcs), "top10": top(big_funcs)},
        "import_graph": {
            "packages": len(packages),
            "edges_all": len(all_edges),
            "edges_module_level": len(top_edges),
            "largest_scc_all_imports": len(scc_all),
            "largest_scc_all_imports_members": scc_all,
            "largest_scc_module_level": len(scc_top),
            "largest_scc_module_level_members": scc_top,
            "core_imports_upper_layers_at_module_level": bool(core_bad),
            "core_upper_layers_imported": core_bad,
        },
        "patterns_in_dodaios": patterns,
        "comment_share_dodaios": cs,
        "jarvis_name": {
            "occurrences_in_py": sum(r.get("jarvis", 0) for r in results),
            "distinct_JARVIS_env_vars": len(env["JARVIS"]),
            "distinct_DODAIOS_env_vars": len(env["DODAIOS"]),
        },
        "tracked_files_over_1mb": {
            "count": len(blobs),
            "top10": [{"name": k, "bytes": v} for k, v in blobs[:10]],
        },
        "scripts_files": sum(1 for p in tracked if p.startswith("scripts/")),
        "workflow_files": sum(1 for p in tracked if p.startswith(".github/workflows/")),
        "tests_reading_dodaios_source": {
            "files": sum(t["files"] for t in tests_src),
            "test_functions": sum(t["test_functions"] for t in tests_src),
        },
    }


def to_markdown(r: dict) -> str:
    d, g, p = r["dodaios_python"], r["import_graph"], r["patterns_in_dodaios"]
    c, j, t = r["comment_share_dodaios"], r["jarvis_name"], r["tests_reading_dodaios_source"]
    out = ["# Repo health", ""]
    out.append(
        f"- Python in dodaios/: {d['lines']} lines, {d['modules']} modules, "
        f"{d['packages']} subpackages"
    )
    for key, title in (
        ("code_files_over_3000_lines", "Code files over 3000 lines"),
        ("functions_over_200_lines", "Functions over 200 lines"),
    ):
        out.append(f"- {title}: {r[key]['count']}")
        for row in r[key]["top10"]:
            out.append(f"  - {row['lines']}  {row['name']}")
    out.append(
        f"- Import graph ({g['packages']} subpackages): largest strongly connected component "
        f"{g['largest_scc_all_imports']} (all imports), "
        f"{g['largest_scc_module_level']} (module level)"
    )
    if g["core_imports_upper_layers_at_module_level"]:
        core = "YES: " + ", ".join(g["core_upper_layers_imported"])
    else:
        core = "no"
    out.append(f"- dodaios.core imports ui/speech/brain/live/harness at module level: {core}")
    out.append(
        f"- `except Exception`: {p['except_exception']}, bare `except:`: {p['bare_except']}, "
        f"`type: ignore`: {p['type_ignore']}, `global` statements: {p['global_statements']}"
    )
    out.append(f"- Comment + docstring share of lines: {c['share_percent']}%")
    out.append(
        f'- "jarvis" in .py files: {j["occurrences_in_py"]}; distinct env vars '
        f"JARVIS_*: {j['distinct_JARVIS_env_vars']}, DODAIOS_*: {j['distinct_DODAIOS_env_vars']}"
    )
    out.append(f"- Tracked files over 1 MB: {r['tracked_files_over_1mb']['count']}")
    out.append(f"- scripts/ files: {r['scripts_files']}, workflow files: {r['workflow_files']}")
    out.append(
        f"- Tests reading dodaios source text: {t['test_functions']} test functions "
        f"in {t['files']} files"
    )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--json", metavar="PATH", help="also write the numbers as JSON")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    report = collect(root)
    sys.stdout.reconfigure(encoding="utf-8")
    print(to_markdown(report))
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
