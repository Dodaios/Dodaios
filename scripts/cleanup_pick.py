#!/usr/bin/env python3
"""Pick ONE small, safe cleanup target and write a brief for a coding agent.

    python scripts/cleanup_pick.py                 # markdown brief on stdout
    python scripts/cleanup_pick.py --json          # the same pick as JSON
    python scripts/cleanup_pick.py --category long_function

It reads the ratchet baselines in ``scripts/ci`` and scans tracked Python for
the next target.  Categories rotate by day: a duplicate cluster in one file,
a function just over the size limit, silent exception handlers in one small
file, dead code that vulture reports at 80 % confidence or more.  A file is
skipped when an open pull request touches it or when main changed it in the
last 24 hours.  When nothing is found the exit code is 3 and nothing is
printed to stdout (a nightly routine treats that as "skip tonight").
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("duplicate_cluster", "long_function", "silent_handlers", "dead_code")
FUNC_LIMIT = 200  # same limit scripts/health_report.py counts
FUNC_WINDOW = 60  # "just over": at most this many lines above the limit
DUP_MIN_LINES = 6
SMALL_FILE_LINES = 400
MAX_HANDLERS = 6
SCAN_DIRS = ("dodaios/", "scripts/")
FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _run(args: list[str], cwd: Path) -> str | None:
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def tracked_python(root: Path) -> list[str]:
    out = _run(["git", "ls-files", "-z", "--", "*.py"], root) or ""
    return [p for p in out.split("\0") if p.startswith(SCAN_DIRS)]


def files_in_open_prs(root: Path) -> set[str]:
    """Files any open pull request changes; empty when gh is not usable."""
    if not shutil.which("gh"):
        return set()
    out = _run(["gh", "pr", "list", "--state", "open", "--limit", "200", "--json", "files"], root)
    if not out:
        return set()
    try:
        prs = json.loads(out)
    except ValueError:
        return set()
    return {f.get("path", "") for pr in prs for f in pr.get("files", [])}


def files_changed_recently(root: Path, hours: int = 24) -> set[str]:
    for ref in ("origin/main", "main", "HEAD"):
        out = _run(
            ["git", "log", ref, f"--since={hours} hours ago", "--name-only", "--format="], root
        )
        if out is not None:
            return {line.strip() for line in out.splitlines() if line.strip()}
    return set()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, SyntaxError, ValueError, RecursionError):
        return None


def _span(node: ast.AST) -> int:
    return (getattr(node, "end_lineno", None) or node.lineno) - node.lineno + 1


def _body_fingerprint(node: ast.AST) -> str:
    """Hash of a function body (names kept), so only true copies match."""
    dumped = "|".join(ast.dump(stmt, annotate_fields=False) for stmt in node.body)
    return hashlib.sha256(dumped.encode()).hexdigest()


def scan_functions(root: Path, files: list[str], skip: set[str], limit: int = FUNC_LIMIT):
    """Return (long_function candidates, duplicate_cluster candidates)."""
    longs: list[dict] = []
    dupes: list[dict] = []
    for rel in files:
        if rel in skip or rel.startswith("tests/"):
            continue
        tree = _parse(root / rel)
        if tree is None:
            continue
        groups: dict[str, list] = defaultdict(list)
        for node in ast.walk(tree):
            if not isinstance(node, FUNC_NODES):
                continue
            length = _span(node)
            if limit < length <= limit + FUNC_WINDOW:
                longs.append(
                    {
                        "file": rel,
                        "symbol": node.name,
                        "line": node.lineno,
                        "size": length,
                        "score": length - limit,
                    }
                )
            if length >= DUP_MIN_LINES:
                groups[_body_fingerprint(node)].append(node)
        for nodes in groups.values():
            if len(nodes) >= 2:
                size = _span(nodes[0])
                dupes.append(
                    {
                        "file": rel,
                        "symbol": ", ".join(n.name for n in nodes),
                        "line": min(n.lineno for n in nodes),
                        "size": size,
                        "copies": len(nodes),
                        "score": -size * (len(nodes) - 1),
                    }
                )
    return longs, dupes


def silent_handler_candidates(root: Path, baseline: dict, skip: set[str]) -> list[dict]:
    found = []
    for rel, count in (baseline.get("files") or {}).items():
        if rel in skip or not 1 <= count <= MAX_HANDLERS:
            continue
        path = root / rel
        if not path.is_file():
            continue
        lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        if lines <= SMALL_FILE_LINES:
            found.append(
                {
                    "file": rel,
                    "symbol": f"{count} silent handler(s)",
                    "line": 1,
                    "size": lines,
                    "score": lines,
                }
            )
    return found


def dead_code_candidates(root: Path, files: set[str], skip: set[str]) -> list[dict]:
    """vulture findings at >= 80 % confidence; empty when vulture is missing."""
    out = _run([sys.executable, "-m", "vulture", "dodaios", "--min-confidence", "80"], root)
    if not out:
        return []
    per_file: dict[str, list[str]] = defaultdict(list)
    for line in out.splitlines():
        head, _, rest = line.partition(": ")
        rel = head.rsplit(":", 1)[0].replace("\\", "/")
        if rel in files and rel not in skip:
            per_file[rel].append(rest)
    return [
        {"file": rel, "symbol": "; ".join(items[:5]), "line": 1, "size": len(items),
         "score": len(items)}
        for rel, items in per_file.items()
    ]


def guard_commands(file: str) -> list[str]:
    cmds = [f"python -m pytest tests -q -k {Path(file).stem} -x"]
    if (ROOT / "scripts" / "perf_guard.py").is_file():
        cmds.append("python scripts/perf_guard.py --fast")
    cmds.append("python scripts/ci/run_gates.py")
    return cmds


GOALS = {
    "duplicate_cluster": "Merge the identical copies into one helper and call it from each place.",
    "long_function": "Split the function into smaller named functions so it falls under the "
    f"{FUNC_LIMIT}-line limit. Move code, do not rewrite it.",
    "silent_handlers": "Make each silent exception handler log (with the repo's logger) or "
    "re-raise, or narrow it to the exception that can really happen.",
    "dead_code": "Delete the unused names listed. Check each with grep first, including "
    "string lookups and tests; keep any that is reached by name at runtime.",
}
BASELINE_NOTE = {
    "silent_handlers": "python scripts/ci/check_silent_exception_handlers.py --update",
}


def pick(root: Path, category: str | None, day: dt.date, skip: set[str]) -> dict | None:
    files = tracked_python(root)
    base = load_json(root / "scripts" / "ci" / "silent-handlers-baseline.json")
    longs, dupes = scan_functions(root, files, skip)
    pools = {
        "duplicate_cluster": dupes,
        "long_function": longs,
        "silent_handlers": silent_handler_candidates(root, base, skip),
    }
    order = list(CATEGORIES)
    start = day.toordinal() % len(order)
    order = order[start:] + order[:start]
    if category:
        order = [category]
    for cat in order:
        pool = pools[cat] if cat in pools else dead_code_candidates(root, set(files), skip)
        if pool:
            best = min(pool, key=lambda c: (c["score"], c["file"], c["line"]))
            return {"category": cat, **best}
    return None


def brief(p: dict) -> str:
    update = BASELINE_NOTE.get(
        p["category"],
        "the gate that fails prints its own `--update` command; run exactly that",
    )
    guards = "\n".join(f"- `{c}`" for c in guard_commands(p["file"]))
    title = p["category"].replace("_", " ")
    return f"""# Nightly cleanup: {title} in `{p['file']}`

## Goal
{GOALS[p['category']]}

Target: `{p['file']}` (line {p['line']}), `{p['symbol']}`, size {p['size']}.
Touch this one file and its tests only. Nothing else.

## Rules
- Work in your own git worktree; never edit the shared checkout.
- No behaviour change. Same inputs give the same outputs, same logs, same API.
- English only in code, comments and the commit message.
- One pull request. Land it with `python scripts/agent_land.py` (auto-merge is set).
- Lower the ratchet baseline for this file: {update}
- If the change is not clearly safe in under an hour, stop and open no PR.

## Guard commands (all must pass before landing)
{guards}
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--json", action="store_true", help="print the pick as JSON")
    ap.add_argument("--category", choices=CATEGORIES, help="force one category")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--day", help="YYYY-MM-DD, decides the rotation (default today)")
    ap.add_argument("--no-gh", action="store_true", help="do not ask GitHub for open PR files")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.day) if args.day else dt.date.today()
    skip = files_changed_recently(args.root)
    if not args.no_gh:
        skip |= files_in_open_prs(args.root)
    result = pick(args.root, args.category, day, skip)
    if result is None:
        print("cleanup_pick: no safe target tonight", file=sys.stderr)
        return 3
    print(json.dumps(result, indent=2) if args.json else brief(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
