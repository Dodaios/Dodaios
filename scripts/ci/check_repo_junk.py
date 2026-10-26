#!/usr/bin/env python3
"""CI gate: keep the repo to the product, never films, renders or source art.

The repo was cut from 382 MB to 201 MB on 2026-10-19 (PR #754) because demo
films, screen recordings, Blender masters and render evidence kept landing in
it. Nothing stopped the next one: ``.gitignore`` only covered the repo root.
Every such file stays in the history forever, so every clone pays for it even
after it is deleted again.

This gate blocks the classes that never belong in the product:

* video and screen recordings (``.mp4``, ``.webm``, ``.mov``, ``.gif`` ...)
* raw audio, design and 3D masters (``.wav``, ``.blend``, ``.psd`` ...)
* archives (``.zip``, ``.7z`` ...)
* working folders: ``video/``, ``films/``, ``renders/``, ``evidence/`` ...
* any single file over the size cap, unless it is a known runtime asset

A path the product really needs goes into ``repo-junk-allowlist.txt`` (one glob
per line, with a comment saying why) in the same change.

Modes:
  (default)   check every tracked file; rc 1 on a violation (CI use)
  ``--staged`` check only files the staged change adds or modifies (hook use)
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).resolve().parent / "repo-junk-allowlist.txt"

MAX_BYTES = 5 * 1024 * 1024

BLOCKED_EXTENSIONS = {
    # Video and screen recordings.
    ".mp4": "video", ".m4v": "video", ".mov": "video", ".webm": "video",
    ".mkv": "video", ".avi": "video", ".wmv": "video", ".flv": "video",
    ".gif": "animated recording",
    # Raw audio masters.
    ".wav": "raw audio", ".flac": "raw audio", ".aiff": "raw audio", ".aif": "raw audio",
    # Design and 3D source files (exports such as .glb ship, masters do not).
    ".blend": "Blender master", ".blend1": "Blender backup", ".psd": "Photoshop master",
    ".kra": "Krita master", ".xcf": "GIMP master", ".aep": "After Effects project",
    ".prproj": "Premiere project", ".exr": "render output", ".fbx": "3D source",
    # Archives.
    ".zip": "archive", ".7z": "archive", ".rar": "archive", ".tar": "archive",
    ".tgz": "archive", ".gz": "archive",
    # Leftover copies.
    ".bak": "backup copy", ".backup": "backup copy", ".orig": "merge leftover",
}

# Folder names that only ever hold working material.
BLOCKED_DIRS = {
    "video": "film project", "videos": "film project", "film": "film project",
    "films": "film project", "renders": "render output", "evidence": "render evidence",
    "recordings": "screen recordings", "screenshots": "screenshots",
}

# Third-party trees keep their own layout; their folder names are not ours.
DIR_RULE_EXEMPT = ("dodaios/ui/web/dist/", "dodaios/ui/web/frontend/node_modules/")


def _git(*args: str) -> list[str]:
    out = subprocess.run(  # noqa: S603
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if out.returncode != 0:
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def _load_allowlist() -> list[str]:
    if not ALLOWLIST.is_file():
        return []
    patterns = []
    for raw in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            patterns.append(line)
    return patterns


def _allowed(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pat) for pat in patterns)


def _blob_size(path: str, staged: bool) -> int:
    spec = f":{path}" if staged else f"HEAD:{path}"
    sizes = _git("cat-file", "-s", spec)
    if sizes:
        return int(sizes[0])
    file = REPO_ROOT / path
    return file.stat().st_size if file.is_file() else 0


def _tracked_sizes() -> dict[str, int]:
    """Every tracked path with its size, read from the index in one call."""
    sizes: dict[str, int] = {}
    for line in _git("ls-files", "-s"):
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 2 or parts[0] == "160000":  # submodule
            continue
        sizes[path] = -1
    if not sizes:
        return sizes
    proc = subprocess.run(  # noqa: S603
        ["git", "cat-file", "--batch-check=%(objectsize)"], cwd=REPO_ROOT,
        input="\n".join(f":{p}" for p in sizes), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    for path, size in zip(sizes, proc.stdout.splitlines(), strict=False):
        sizes[path] = int(size) if size.isdigit() else 0
    return sizes


def problems(paths: dict[str, int], patterns: list[str]) -> list[str]:
    found = []
    for path, size in sorted(paths.items()):
        if _allowed(path, patterns):
            continue
        pure = PurePosixPath(path)
        kind = BLOCKED_EXTENSIONS.get(pure.suffix.lower())
        if kind:
            found.append(f"{path}: {kind} ({pure.suffix.lower()} files never belong in the repo)")
            continue
        if not path.startswith(DIR_RULE_EXEMPT):
            folder = next((p for p in pure.parts[:-1] if p.lower() in BLOCKED_DIRS), None)
            if folder:
                found.append(f"{path}: inside '{folder}/' ({BLOCKED_DIRS[folder.lower()]})")
                continue
        if size > MAX_BYTES:
            found.append(f"{path}: {size / 1048576:.1f} MB, over the {MAX_BYTES // 1048576} MB cap")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--staged", action="store_true", help="Check the staged change only.")
    args = parser.parse_args(argv)

    patterns = _load_allowlist()
    if args.staged:
        changed = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
        paths = {p: _blob_size(p, staged=True) for p in changed}
    else:
        paths = _tracked_sizes()

    found = problems(paths, patterns)
    if not found:
        print(f"repo-junk: OK ({len(paths)} files checked)")
        return 0
    print("repo-junk: files that are not part of the product:")
    for line in found:
        print(f"  {line}")
    print(
        "\nKeep films, recordings, renders and source art outside the repo"
        " (a local folder or a release asset). If the product truly needs one,"
        f" add its path to {ALLOWLIST.relative_to(REPO_ROOT).as_posix()} with a reason."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
