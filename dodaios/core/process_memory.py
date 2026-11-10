"""What the app's processes hold in memory, as numbers a person can compare.

The desktop app is a tree of processes: the backend, the window's WebView
processes, the dictation engine workers, the screenshot helpers, MCP servers.
"The app uses a lot of memory" could not be answered from inside until now;
the only tool was Task Manager, which shows the tree as unrelated rows.

Two numbers per process, because they answer different questions:

* ``private_mb`` is what the process has committed. Windows charges it against
  the page file whether or not a page was ever touched, so this is the number
  that runs a machine out of memory.
* ``rss_mb`` is what sits in physical memory right now. Under memory pressure
  Windows trims it, so a small value can mean "idle", not "small".

Read-only and stdlib plus psutil. Nothing here runs unless it is called.
"""

from __future__ import annotations

import gc
import os
import sys
from collections import Counter
from typing import Any

_MB = 1024 * 1024


def _role(name: str, cmdline: list[str]) -> str:
    """A short label for a process, without paths or arguments that name files."""
    for index, part in enumerate(cmdline[:-1]):
        if part == "-m":
            return cmdline[index + 1]
    for part in cmdline:
        if part.startswith("--type="):
            return f"webview {part[len('--type=') :]}"
    if "webview" in name.lower():
        return "webview host"
    return name


def tree_memory(pid: int | None = None) -> dict[str, Any]:
    """Memory of ``pid`` (this process by default) and every process below it."""
    import psutil

    try:
        root = psutil.Process(pid or os.getpid())
        members = [root, *root.children(recursive=True)]
    except psutil.Error:  # the process is gone: an empty report says exactly that
        return {"total": {"processes": 0, "private_mb": 0.0, "rss_mb": 0.0}, "processes": []}
    rows: list[dict[str, Any]] = []
    for process in members:
        try:
            with process.oneshot():
                info = process.memory_info()
                name = process.name()
                try:
                    cmdline = process.cmdline()
                except psutil.Error:  # a protected process: its name still labels it
                    cmdline = []
                # Only Windows reports (and charges) a private commit; elsewhere
                # the resident size is the honest stand-in.
                private = getattr(info, "private", None) or info.rss
                rows.append(
                    {
                        "pid": process.pid,
                        "name": name,
                        "role": _role(name, cmdline),
                        "private_mb": round(private / _MB, 1),
                        "rss_mb": round(info.rss / _MB, 1),
                        "threads": process.num_threads(),
                    }
                )
        except psutil.Error:
            continue  # ended while we looked
    rows.sort(key=lambda row: row["private_mb"], reverse=True)
    return {
        "total": {
            "processes": len(rows),
            "private_mb": round(sum(row["private_mb"] for row in rows), 1),
            "rss_mb": round(sum(row["rss_mb"] for row in rows), 1),
        },
        "processes": rows,
    }


def _owner(obj: Any) -> str:
    """Who holds ``obj``, as type names only. Never values: they may be private."""
    names: list[str] = []
    for referrer in gc.get_referrers(obj)[:8]:
        if isinstance(referrer, dict):
            holders = [
                holder
                for holder in gc.get_referrers(referrer)[:8]
                if getattr(holder, "__dict__", None) is referrer
            ]
            if holders:
                holder = holders[0]
                label = getattr(holder, "__name__", None) or type(holder).__qualname__
                names.append(f"{type(holder).__module__}.{label}")
                continue
        kind = type(referrer)
        if kind.__name__ not in ("frame", "list_iterator"):
            names.append(f"{kind.__module__}.{kind.__qualname__}")
    return ", ".join(dict.fromkeys(names))[:200]


def python_objects(*, top: int = 30, largest: int = 20) -> dict[str, Any]:
    """The Python heap by type, and the largest single objects with their owners.

    Walks every tracked object: it holds the interpreter for a moment (a
    second or so on a busy backend). A diagnostics call, never product code.
    Sizes are shallow (``sys.getsizeof``); contents are never returned.
    """
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    big: list[tuple[int, Any]] = []
    floor = 0
    for obj in gc.get_objects():
        try:
            size = sys.getsizeof(obj)
        except Exception:  # noqa: BLE001, S112 - a proxy that refuses is skipped, not fatal
            continue
        kind = type(obj)
        key = f"{kind.__module__}.{kind.__qualname__}"
        counts[key] += 1
        sizes[key] += size
        if size > floor and size >= 256 * 1024:
            big.append((size, obj))
            if len(big) > largest * 4:
                big.sort(key=lambda item: item[0], reverse=True)
                del big[largest:]
                floor = big[-1][0]
    big.sort(key=lambda item: item[0], reverse=True)
    del big[largest:]
    report = {
        "tracked_objects": sum(counts.values()),
        "tracked_mb": round(sum(sizes.values()) / _MB, 1),
        "by_type": [
            {"type": key, "count": counts[key], "mb": round(size / _MB, 2)}
            for key, size in sizes.most_common(top)
        ],
        "largest": [
            {
                "type": f"{type(obj).__module__}.{type(obj).__qualname__}",
                "mb": round(size / _MB, 2),
                "len": len(obj) if hasattr(obj, "__len__") else None,
                "held_by": _owner(obj),
            }
            for size, obj in big
        ],
    }
    del big
    return report


def loaded_packages(*, top: int = 40) -> list[dict[str, Any]]:
    """Top-level packages by number of loaded modules: what the process imported."""
    packages: Counter[str] = Counter(name.partition(".")[0] for name in list(sys.modules))
    return [{"package": name, "modules": count} for name, count in packages.most_common(top)]


__all__ = ["loaded_packages", "python_objects", "tree_memory"]
