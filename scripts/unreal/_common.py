"""Shared paths, limits and helpers of the Unreal wrapper scripts.

Every build, test, capture and cook of the Unreal Verse goes through
``scripts/unreal/*.py`` (docs/verse/unreal/orchestration.md 0.5 and 3.3).
This module holds what they share: where the engine, the project and the
toolchain pins are, the machine limits of orchestration.md section 4, and a
small ``run`` helper the tests replace.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNREAL_ROOT = REPO_ROOT / "unreal"
PROJECT_DIR = UNREAL_ROOT / "Verse"
PROJECT_FILE = PROJECT_DIR / "Verse.uproject"
TOOLCHAINS_FILE = UNREAL_ROOT / "Toolchain" / "toolchains.json"

#: Machine limits, orchestration.md section 4 (start values until step 0.8).
LOCK_HOLDERS = 1
MAX_PARALLEL_ACTIONS = 10
MAX_HEADLESS_JOBS = 4
MAX_RENDERED_JOBS = 1
MIN_FREE_GB = 40
MAX_HOLD_MINUTES = 90
QUEUE_DEPTH_WARN = 8

#: Build output folders of one worktree; the shared DDC is never among them.
BUILD_OUTPUT_DIRS = ("Binaries", "Intermediate", "Saved")

ENGINE_ENV = "DODAIOS_UE_ROOT"
DEFAULT_ENGINE_ROOT = Path("C:/Program Files/Epic Games/UE_5.7")


class UnrealScriptError(RuntimeError):
    """A wrapper script cannot do what it was asked; the message says why."""


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def log(message: str) -> None:
    print(f"[unreal] {message}", flush=True)


def load_toolchains(path: Path = TOOLCHAINS_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def engine_root(env: Mapping[str, str] | None = None) -> Path:
    """The Unreal install: ``DODAIOS_UE_ROOT`` when set, else the pinned default."""
    env = os.environ if env is None else env
    override = env.get(ENGINE_ENV, "").strip()
    if override:
        return Path(override)
    try:
        pinned = load_toolchains()["engine"]["windows_root"]
    except (OSError, KeyError, ValueError):
        return DEFAULT_ENGINE_ROOT
    return Path(pinned)


def build_bat(root: Path) -> Path:
    return root / "Engine" / "Build" / "BatchFiles" / "Build.bat"


def run_uat_bat(root: Path) -> Path:
    return root / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"


def editor_cmd(root: Path) -> Path:
    return root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"


def project_file(worktree: Path = REPO_ROOT) -> Path:
    return worktree / "unreal" / "Verse" / "Verse.uproject"


def current_branch(worktree: Path = REPO_ROOT) -> str:
    result = run(["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    name = result.stdout.strip() if result.returncode == 0 else ""
    return name or "detached"


def safe_name(text: str) -> str:
    """A string usable as one folder name (branch slashes become dashes)."""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in text)
    return cleaned.strip("-.") or "run"


def run_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def free_gb(path: Path) -> float:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free / 1e9


def require_free_disk(path: Path, minimum: float = MIN_FREE_GB) -> None:
    free = free_gb(path)
    if free < minimum:
        raise UnrealScriptError(
            f"only {free:.1f} GB free on the drive of {path}; builds need {minimum} GB. "
            "Ask the orchestrator to clean merged worktrees (worktree.py remove)."
        )


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    capture: bool = False,
    timeout: float | None = None,
) -> Completed:
    """Run one command; the tests replace this function."""
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env is not None else None,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return Completed(127, "", str(exc))
    except subprocess.TimeoutExpired:
        return Completed(124, "", f"timed out after {timeout} s")
    return Completed(result.returncode, result.stdout or "", result.stderr or "")


def exit_with(error: Exception) -> int:
    print(f"[unreal] error: {error}", file=sys.stderr, flush=True)
    return 2
