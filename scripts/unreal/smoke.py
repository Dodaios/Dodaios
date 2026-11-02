#!/usr/bin/env python3
"""Package the Verse and smoke-test the packaged build under the machine lock.

The packaged-build smoke test of docs/verse/unreal/orchestration.md 5.6.

    python scripts/unreal/smoke.py                 # package, then run with the GPU
    python scripts/unreal/smoke.py --nullrhi       # same run without rendering
    python scripts/unreal/smoke.py --skip-package  # reuse Saved/Smoke

Steps, all inside one lock hold:

1. ``RunUAT BuildCookRun`` for Win64 Development into
   ``unreal/Verse/Saved/Smoke`` (``--skip-package`` reuses it).
2. ``scripts/unreal/fake_bridge.py --token <random>`` (G0.11) serves
   ``verse.bridge/1`` with synthetic data.
3. ``Saved/Smoke/Windows/Verse.exe -VerseSmoke=<stages>`` with
   ``DODAIOS_VERSE_TOKEN`` set, its window off the person's monitors.

Pass: package exit code 0; the game exits 0 within the time limit; its log
has a ``VerseSmoke: stage <name> OK`` line for every requested stage and no
fatal error, ensure or crash.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common
from scripts.unreal import test as automation
from scripts.unreal import with_lock

DEFAULT_STAGES = ("boot", "hangar", "arena30s")
TOKEN_ENV = "DODAIOS_VERSE_TOKEN"  # noqa: S105 - the variable name, not a secret
GAME_TIMEOUT_S = 10 * 60
FAKE_BRIDGE = common.REPO_ROOT / "scripts" / "unreal" / "fake_bridge.py"


def archive_dir(worktree: Path) -> Path:
    return worktree / "unreal" / "Verse" / "Saved" / "Smoke"


def package_command(engine: Path, project: Path, archive: Path) -> list[str]:
    return [
        str(common.run_uat_bat(engine)),
        "BuildCookRun",
        f"-project={project}",
        "-platform=Win64",
        "-clientconfig=Development",
        "-build",
        "-cook",
        "-stage",
        "-pak",
        "-iostore",
        "-archive",
        f"-archivedirectory={archive}",
        "-unattended",
        "-utf8output",
        "-nocompileeditor",
    ]


def game_command(exe: Path, stages: Sequence[str], log_path: Path, nullrhi: bool) -> list[str]:
    command = [
        str(exe),
        "-windowed",
        "-ResX=1280",
        "-ResY=720",
        "-WinX=-32000",
        "-WinY=-32000",
        f"-VerseSmoke={','.join(stages)}",
        "-log",
        f"-abslog={log_path}",
        "-unattended",
    ]
    if nullrhi:
        command.append("-nullrhi")
    return command


def missing_stages(log_path: Path, stages: Sequence[str]) -> list[str]:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return list(stages)
    return [s for s in stages if not re.search(rf"VerseSmoke: stage {re.escape(s)} OK", text)]


def smoke(
    *,
    worktree: Path = common.REPO_ROOT,
    stages: Sequence[str] = DEFAULT_STAGES,
    nullrhi: bool = False,
    skip_package: bool = False,
    runner: Callable[..., common.Completed] = common.run,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    lock_factory: Callable[..., with_lock.MachineLock] = with_lock.MachineLock,
    fake_bridge: Path = FAKE_BRIDGE,
) -> list[str]:
    """Run the smoke test; return the problems found (empty means pass)."""
    engine = common.engine_root()
    project = common.project_file(worktree)
    archive = archive_dir(worktree)
    exe = archive / "Windows" / "Verse.exe"
    if not fake_bridge.is_file():
        raise common.UnrealScriptError(
            f"{fake_bridge} is missing; the fake bridge lands with G0.11"
        )
    if not skip_package:
        common.require_free_disk(worktree)
    token = secrets.token_hex(16)
    log_path = archive / f"smoke-{common.run_stamp()}.log"
    problems: list[str] = []
    with lock_factory(f"smoke ({worktree.name})", "smoke.py"):
        if not skip_package:
            command = package_command(engine, project, archive)
            common.log(f"package: {' '.join(command)}")
            packaged = runner(command, cwd=worktree)
            if packaged.returncode != 0:
                return [f"BuildCookRun exited with {packaged.returncode}"]
        if not exe.is_file():
            return [f"no packaged game at {exe}"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        bridge = popen([sys.executable, str(fake_bridge), "--token", token], cwd=str(worktree))
        try:
            env = dict(os.environ, **{TOKEN_ENV: token})
            command = game_command(exe, stages, log_path, nullrhi)
            common.log(f"run: {' '.join(command)}")
            game = runner(command, cwd=archive, env=env, timeout=GAME_TIMEOUT_S)
        finally:
            bridge.terminate()
            try:
                bridge.wait(timeout=10)
            except subprocess.TimeoutExpired:
                bridge.kill()
    if game.returncode != 0:
        problems.append(f"Verse.exe exited with {game.returncode}")
    problems += [f"stage {s} not reported OK" for s in missing_stages(log_path, stages)]
    problems += [f"log: {line}" for line in automation.scan_log(log_path)]
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--nullrhi", action="store_true", help="run the game without rendering")
    parser.add_argument("--skip-package", action="store_true", help="reuse Saved/Smoke")
    parser.add_argument("--stages", default=",".join(DEFAULT_STAGES))
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    options = parser.parse_args(argv)
    stages = [s.strip() for s in options.stages.split(",") if s.strip()]
    try:
        problems = smoke(worktree=options.worktree.resolve(), stages=stages,
                         nullrhi=options.nullrhi, skip_package=options.skip_package)
    except common.UnrealScriptError as error:
        return common.exit_with(error)
    for problem in problems:
        common.log(f"PROBLEM {problem}")
    common.log("PASS" if not problems else "FAIL")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
