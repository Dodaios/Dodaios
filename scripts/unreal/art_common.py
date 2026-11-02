"""Shared paths, records and the machine-wide lock of the art pipeline entries.

Used by `scripts/verse/export_unreal.py`, `scripts/unreal/import_art.py` and
`scripts/unreal/check_art_text.py` (docs/verse/unreal/contracts/art-pipeline.md
sections 2 and 10). Pure Python; no Blender, no Unreal.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ART_ROOT = REPO_ROOT / "art" / "verse"
CACHE_ROOT = ART_ROOT / ".cache" / "unreal"
PROJECT_DIR = REPO_ROOT / "unreal" / "Verse"
UPROJECT = PROJECT_DIR / "Verse.uproject"
ART_TEXT = PROJECT_DIR / "Art"
PLACEMENTS = ART_TEXT / "Placements"
IMPORT_RECORDS = ART_TEXT / "Import"
MI_RECIPES = ART_TEXT / "Materials"
SPACE_VECTORS = ART_TEXT / "space_vectors.json"
CONTENT_VERSE = PROJECT_DIR / "Content" / "Verse"
SCHEMA_DIR = ART_ROOT / "schema"

LOCK_DIR_ENV = "DODAIOS_LOCK_DIR"
HELD_ENV = "DODAIOS_GPU_LOCK_HELD"
DEFAULT_LOCK_DIR = Path("C:/demo/.locks")


def lock_path() -> Path:
    """The machine-wide `gpu-heavy.lock` (orchestration.md 4, architecture 8.2)."""
    override = os.environ.get(LOCK_DIR_ENV, "").strip()
    if override:
        return Path(override) / "gpu-heavy.lock"
    if os.name == "nt":
        return DEFAULT_LOCK_DIR / "gpu-heavy.lock"
    return Path.home() / ".cache" / "dodaios" / "locks" / "gpu-heavy.lock"


@contextmanager
def heavy_lock(label: str) -> Iterator[None]:
    """Hold the machine-wide lock; waiters queue, never fail.

    Uses `scripts/unreal/with_lock.py` (FIFO queue, holder file, 90 minute
    hold limit) when it is present, else the same OS file lock directly. A job
    started under the lock (`DODAIOS_GPU_LOCK_HELD`) does not queue again.
    """
    if os.environ.get(HELD_ENV):
        yield
        return
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from scripts.unreal import with_lock
    except ImportError:
        with_lock = None
    if with_lock is not None and hasattr(with_lock, "held"):
        with with_lock.held(label, sys.argv):
            yield
        return
    from filelock import FileLock, Timeout

    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path))
    started = time.monotonic()
    announced = False
    while True:
        try:
            lock.acquire(timeout=10)
            break
        except Timeout:
            if not announced:
                print(f"[verse] {label}: waiting for {path}", flush=True)
                announced = True
    if announced:
        print(f"[verse] {label}: lock acquired after {time.monotonic() - started:.0f} s")
    os.environ[HELD_ENV] = label
    try:
        yield
    finally:
        os.environ.pop(HELD_ENV, None)
        lock.release()


def load_lib(name: str):
    """Import a pure module of `art/verse/lib` (e.g. `placement`, `ue_space`)."""
    art = str(ART_ROOT)
    if art not in sys.path:
        sys.path.insert(0, art)
    module = __import__(f"lib.{name}", fromlist=[name])
    return module


def dump_json(path: Path, payload: dict) -> bool:
    """Write sorted, 2-space, LF JSON; return True when the file changed."""
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return True


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)
