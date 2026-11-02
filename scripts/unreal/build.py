#!/usr/bin/env python3
"""Build the Unreal Verse under the machine lock, or clean a worktree's output.

The only build entry for agents (docs/verse/unreal/orchestration.md 3.3 and
5.1); nobody calls UBT directly.

    python scripts/unreal/build.py editor        # VerseEditor Win64 Development
    python scripts/unreal/build.py game          # Verse Win64 Development
    python scripts/unreal/build.py linux         # Verse Linux Development (cross)
    python scripts/unreal/build.py editor game   # several, one lock hold each
    python scripts/unreal/build.py clean         # delete Binaries/, Intermediate/, Saved/

A build refuses to start with less than 40 GB free (orchestration.md 4) and
the Linux build refuses to start without ``LINUX_MULTIARCH_ROOT``
(``doctor.py`` says how to fix both).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common
from scripts.unreal import with_lock

#: target name -> (UBT target, platform, configuration)
TARGETS: dict[str, tuple[str, str, str]] = {
    "editor": ("VerseEditor", "Win64", "Development"),
    "game": ("Verse", "Win64", "Development"),
    "linux": ("Verse", "Linux", "Development"),
}
LINUX_ENV = "LINUX_MULTIARCH_ROOT"


def command_for(target: str, engine: Path, project: Path) -> list[str]:
    name, platform, configuration = TARGETS[target]
    return [
        str(common.build_bat(engine)),
        name,
        platform,
        configuration,
        f"-Project={project}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
        f"-MaxParallelActions={common.MAX_PARALLEL_ACTIONS}",
    ]


def check_prerequisites(target: str, engine: Path, worktree: Path, env: Mapping[str, str]) -> None:
    if not common.build_bat(engine).is_file():
        raise common.UnrealScriptError(
            f"no Unreal install at {engine} (set {common.ENGINE_ENV}; run doctor.py)"
        )
    if not common.project_file(worktree).is_file():
        raise common.UnrealScriptError(f"no project at {common.project_file(worktree)}")
    if target == "linux" and not env.get(LINUX_ENV, "").strip():
        raise common.UnrealScriptError(
            f"{LINUX_ENV} is not set: the Linux cross toolchain is missing (run doctor.py)"
        )
    common.require_free_disk(worktree)


def build(
    targets: Sequence[str],
    *,
    worktree: Path = common.REPO_ROOT,
    env: Mapping[str, str] | None = None,
    runner: Callable[..., int] = with_lock.run_locked,
) -> int:
    env = os.environ if env is None else env
    engine = common.engine_root(env)
    project = common.project_file(worktree)
    for target in targets:
        check_prerequisites(target, engine, worktree, env)
    for target in targets:
        command = command_for(target, engine, project)
        common.log(f"build {target}: {' '.join(command)}")
        started = time.monotonic()
        code = runner(command, label=f"build {target} ({worktree.name})", cwd=worktree)
        minutes = (time.monotonic() - started) / 60
        verdict = "OK" if code == 0 else f"FAILED (exit {code})"
        common.log(f"build {target}: {verdict} in {minutes:.1f} min")
        if code != 0:
            return code
    return 0


def clean(
    worktree: Path = common.REPO_ROOT,
    *,
    remove: Callable[[Path], None] = shutil.rmtree,
) -> list[Path]:
    """Delete this worktree's build output; never the shared DDC."""
    project_dir = worktree / "unreal" / "Verse"
    roots = [project_dir]
    plugins = project_dir / "Plugins"
    if plugins.is_dir():
        roots += [p for p in plugins.iterdir() if p.is_dir()]
    removed: list[Path] = []
    for root in roots:
        for name in common.BUILD_OUTPUT_DIRS:
            target = root / name
            if target.is_dir() and not target.is_symlink():
                remove(target)
                removed.append(target)
    for path in removed:
        common.log(f"clean: removed {path}")
    if not removed:
        common.log("clean: nothing to remove")
    return removed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="+", choices=[*TARGETS, "clean"])
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    options = parser.parse_args(argv)
    worktree = options.worktree.resolve()
    if "clean" in options.targets:
        if len(options.targets) > 1:
            parser.error("clean runs on its own")
        clean(worktree)
        return 0
    try:
        return build(options.targets, worktree=worktree)
    except common.UnrealScriptError as error:
        return common.exit_with(error)


if __name__ == "__main__":
    sys.exit(main())
