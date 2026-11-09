#!/usr/bin/env python3
"""Run the hangar duel (endless 1v1 deathmatch) under the machine lock.

The integration's end-to-end check of the playable loop (orchestration.md 2.2):
the Verse boots into the hangar, ``-VerseDuel`` starts the duel against the
bot, and the run ends after ``--seconds`` of match time with a stats JSON
(kills, deaths, shots, hits, fps, error lines).

    python scripts/unreal/duel.py --tier hard --seconds 120 --autoplay
    python scripts/unreal/duel.py --tier elite --bots --seconds 120
    python scripts/unreal/duel.py --tier normal --render --autoplay --seconds 60
    python scripts/unreal/duel.py --print-play-command

Headless runs use ``-nullrhi`` at a fixed 60 Hz step; ``--render`` opens the
game off the person's monitors (fps measured on the GPU). ``--print-play-command``
prints the command a person starts to play (no lock, nothing runs).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common  # noqa: E402
from scripts.unreal import with_lock  # noqa: E402

HANGAR_MAP = "/Game/Verse/Decks/Hangar/LV_Hangar"
TIERS = ("normal", "hard", "elite", "adaptive")
#: Far outside any monitor layout, so a rendered run never covers the person's work.
OFFSCREEN = ("-WinX=-32000", "-WinY=-32000")


def out_dir(worktree: Path) -> Path:
    branch = common.safe_name(common.current_branch(worktree))
    return worktree / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / branch / "duel"


def command_for(
    engine: Path,
    project: Path,
    *,
    tier: str,
    seconds: float,
    bots: bool,
    autoplay: bool,
    render: bool,
    stats: Path,
    log_path: Path,
) -> list[str]:
    command = [str(common.editor_cmd(engine)), str(project), HANGAR_MAP, "-game"]
    if render:
        command += ["-d3d12", "-windowed", "-ResX=1920", "-ResY=1080", *OFFSCREEN]
    else:
        command += ["-nullrhi", "-benchmark", "-fps=60"]
    command += [
        "-nosound",
        "-unattended",
        "-NoP4",
        "-nosplash",
        f"-VerseDuel={tier}",
        f"-VerseDuelSeconds={seconds:g}",
        f"-VerseDuelStats={stats}",
        f"-abslog={log_path}",
    ]
    if bots:
        command.append("-VerseDuelBots")
    if autoplay:
        command.append("-VerseDuelAutoplay")
    return command


def play_command(engine: Path, project: Path) -> list[str]:
    """What a person runs to play: the editor build as the game, in a window, sound on."""
    editor = str(common.editor_cmd(engine)).replace("-Cmd.exe", ".exe")
    return [editor, str(project), HANGAR_MAP, "-game", "-windowed", "-ResX=1920", "-ResY=1080"]


def summarize(stats: dict) -> str:
    players = ", ".join(
        f"{p.get('name') or p['id']}: {p['kills']}K/{p['deaths']}D {p['hits']}/{p['shots']} hits"
        for p in stats.get("players", [])
    )
    return (
        f"tier {stats.get('tier')} bots={stats.get('botVsBot')} "
        f"{stats.get('matchSeconds', 0):.0f} s, fps avg {stats.get('fpsAverage', 0):.1f} "
        f"(1% low {stats.get('fpsOnePercentLow', 0):.1f}), errors {stats.get('errors')}; {players}"
    )


def verdict(stats: dict) -> list[str]:
    """Problems that make a run not clean: no shots, no kills, error lines."""
    problems = []
    players = stats.get("players", [])
    if sum(p.get("shots", 0) for p in players) == 0:
        problems.append("nobody fired")
    if sum(p.get("kills", 0) for p in players) == 0:
        problems.append("no kill")
    if stats.get("errors", 0):
        problems.append(f"{stats['errors']} error log lines")
    return problems


def run(
    args: argparse.Namespace,
    *,
    worktree: Path = common.REPO_ROOT,
    runner: Callable[..., int] = with_lock.run_locked,
) -> int:
    engine = common.engine_root()
    project = common.project_file(worktree)
    if args.print_play_command:
        parts = play_command(engine, project)
        print(" ".join(f'"{part}"' if " " in part else part for part in parts))
        return 0
    folder = out_dir(worktree) / common.run_stamp()
    folder.mkdir(parents=True, exist_ok=True)
    tag = f"{'botvbot' if args.bots else 'player'}_{args.tier}_{'gpu' if args.render else 'null'}"
    stats_path = folder / f"{tag}.json"
    log_path = folder / f"{tag}.log"
    command = command_for(
        engine,
        project,
        tier=args.tier,
        seconds=args.seconds,
        bots=args.bots,
        autoplay=args.autoplay,
        render=args.render,
        stats=stats_path,
        log_path=log_path,
    )
    common.log(f"duel {tag}: {' '.join(command)}")
    code = runner(command, label=f"duel {tag} ({worktree.name})", cwd=worktree)
    if not stats_path.is_file():
        common.log(f"duel {tag}: no stats written (exit {code}); log {log_path}")
        return code or 1
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    common.log(f"duel {tag}: {summarize(stats)}")
    problems = verdict(stats)
    if problems:
        common.log(f"duel {tag}: NOT CLEAN: {', '.join(problems)}; log {log_path}")
        return 1
    common.log(f"duel {tag}: clean; stats {stats_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tier", choices=TIERS, default="hard")
    parser.add_argument("--seconds", type=float, default=120.0, help="Match time to run.")
    parser.add_argument("--bots", action="store_true", help="Bot vs bot; the person spectates.")
    parser.add_argument(
        "--autoplay", action="store_true", help="The scripted player drives the person."
    )
    parser.add_argument("--render", action="store_true", help="Rendered (GPU) instead of -nullrhi.")
    parser.add_argument("--print-play-command", action="store_true")
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    args = parser.parse_args(argv)
    try:
        return run(args, worktree=args.worktree.resolve())
    except common.UnrealScriptError as error:
        return common.exit_with(error)


if __name__ == "__main__":
    sys.exit(main())
