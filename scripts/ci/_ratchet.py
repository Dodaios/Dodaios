"""Shared core of the count ratchets (file size, function size, broad except, ...).

A ratchet gate scans the tree into ``{key: value}`` (a file, or ``path::name``,
mapped to a count or size). A committed baseline lists every CURRENT violation
with its current value. The gate fails when

* a key appears that the baseline does not list (a new violation),
* a value is higher than its baseline (an existing violation grew).

A stale baseline entry (the value shrank or the key is gone) is only a note and
exits 0: many pull requests delete code at once and must not fight over the
baseline files. ``ratchet-baselines.yml`` runs ``--update`` daily and opens one
pull request that tightens them.

``--update`` rewrites the baseline from the tree. It refuses to raise a value or
add a key unless ``--allow-increase`` is passed (say why in the commit message).
``--report`` prints the worst entries and exits 0.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CI_DIR = Path(__file__).resolve().parent


def read_text(path: Path) -> str:
    """Read source as text, tolerating a UTF-8 BOM (``ast.parse`` rejects U+FEFF)."""
    return path.read_text(encoding="utf-8-sig", errors="ignore")


def parse(path: Path) -> ast.AST:
    try:
        return ast.parse(read_text(path))
    except SyntaxError as exc:
        raise RuntimeError(f"{path.relative_to(REPO)} cannot be parsed ({exc}).") from exc


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def is_test_path(path: Path) -> bool:
    name = path.name
    return (
        "tests" in path.parts
        or "__tests__" in path.parts
        or name.startswith("test_")
        or name == "conftest.py"
        or ".test." in name
        or ".spec." in name
    )


_SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", ".venv"}


def walk_files(root: str, suffixes: tuple[str, ...]) -> Iterator[Path]:
    """Sorted files under ``root`` with a suffix, never descending into build/vendor dirs."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO / root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        found.extend(Path(dirpath, f) for f in filenames if f.endswith(suffixes))
    yield from sorted(found)


def python_files(root: str, include_tests: bool = False) -> Iterator[Path]:
    for path in walk_files(root, (".py",)):
        if include_tests or not is_test_path(path):
            yield path


def pmap(func: Callable, paths: list[Path]) -> list:
    """``func`` over ``paths`` on all cores (parsing the whole tree is CPU-bound)."""
    if len(paths) < 64:
        return [func(p) for p in paths]
    with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        return list(pool.map(func, paths, chunksize=32))


def load_baseline(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["files"]


def save_baseline(path: Path, current: dict[str, int], comment: str) -> None:
    payload = {
        "_comment": comment,
        "total": sum(current.values()),
        "files": dict(sorted(current.items())),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def compare(current: dict[str, int], baseline: dict[str, int]):
    """Return ``(new, grown, stale)``; each maps key to ``(was, now)``."""
    new, grown, stale = {}, {}, {}
    for key, now in sorted(current.items()):
        was = baseline.get(key)
        if was is None:
            new[key] = (0, now)
        elif now > was:
            grown[key] = (was, now)
        elif now < was:
            stale[key] = (was, now)
    for key, was in sorted(baseline.items()):
        if key not in current:
            stale[key] = (was, 0)
    return new, grown, stale


def _show(title: str, items: dict[str, tuple[int, int]], unit: str) -> None:
    print(f"{title} ({len(items)}):")
    for key, (was, now) in list(items.items())[:25]:
        print(f"  {key}: {was} -> {now} {unit}")
    if len(items) > 25:
        print(f"  ... and {len(items) - 25} more")
    print()


def run(
    name: str,
    scan: Callable[[], dict[str, int]],
    baseline_file: str,
    unit: str,
    rule: str,
    how_to_fix: str,
    argv: list[str] | None = None,
) -> int:
    """Gate entry point shared by every ratchet script."""
    parser = argparse.ArgumentParser(description=f"{name} ratchet. {rule}")
    parser.add_argument("--report", action="store_true", help="show the worst entries, exit 0")
    parser.add_argument("--update", action="store_true", help="rewrite the baseline")
    parser.add_argument(
        "--allow-increase", action="store_true", help="with --update: permit growth"
    )
    args = parser.parse_args(argv)

    script = f"check_{name.replace('-', '_')}.py"
    path = CI_DIR / baseline_file
    current = scan()
    total = sum(current.values())
    comment = (
        f"{rule} Generated by scripts/ci/{script} --update. "
        "Values may only go DOWN; a new entry or a higher value is a gate failure."
    )

    if args.report:
        print(f"{name}: {len(current)} entries, total {total} {unit}.\n")
        for key, value in sorted(current.items(), key=lambda kv: -kv[1])[:25]:
            print(f"  {value:6d}  {key}")
        return 0

    baseline = load_baseline(path)
    new, grown, stale = compare(current, baseline)

    if args.update:
        if baseline and (new or grown) and not args.allow_increase:
            _show("Refusing to raise the baseline", {**new, **grown}, unit)
            print("Fix the code, or pass --update --allow-increase and say why in the commit.")
            return 1
        save_baseline(path, current, comment)
        print(f"{name}: baseline written, {len(current)} entries, total {total} {unit}.")
        return 0

    if not baseline:
        print(f"{name}: no baseline yet. Run with --update to create one.")
        return 1

    def note_stale() -> None:
        if stale:
            _show("Improved: baseline entries can be tightened", stale, unit)
            print(
                "Nothing to do: ratchet-baselines.yml tightens them daily "
                f"(or run python scripts/ci/{script} --update).\n"
            )

    if not (new or grown):
        note_stale()
        print(f"OK: {name} ratchet holds ({len(current)} entries, total {total} {unit}).")
        return 0

    print(f"{name} ratchet failed. Rule: {rule}\n")
    if new:
        _show("New violations", new, unit)
    if grown:
        _show("Existing violations that grew", grown, unit)
    print(f"How to fix: {how_to_fix}\n")
    note_stale()
    return 1
