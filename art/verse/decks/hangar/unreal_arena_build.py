"""Build the WP11 hangar arena outputs from `unreal_arena/layout.py`.

    python art/verse/decks/hangar/unreal_arena_build.py            # placements + flow report
    python art/verse/decks/hangar/unreal_arena_build.py --quick    # coarser flow sampling
    python art/verse/decks/hangar/unreal_arena_build.py --bot-log runs.jsonl

Writes, all under the ignored proof folder
`unreal/Verse/Saved/Harness/proof/WP11/` (work-packages.md 0.4):

* `placements/hangar/<zone>.placement.json`: the six WP11 zones in canonical
  `verse.placement/1` form. They move to `unreal/Verse/Art/Placements/hangar/`
  in the same PR that imports their graybox meshes, because the static gate
  refuses placements whose assets have no import record (art-pipeline 14).
* `flow.json`: the WP11.11 flow report (sightlines, spawn spacing, time to
  contact; `--bot-log` adds the harness bot runs).
* `plan_<level>.png`: top-down plan per level (needs matplotlib; skipped without).

Pure Python, no Blender and no Unreal, so it needs no machine lock.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "art" / "verse"))

from lib import placement as placement_lib  # noqa: E402
from unreal_arena import (  # noqa: E402
    flow,
    nav,
    placements,  # noqa: E402
)
from unreal_arena import layout as L  # noqa: E402

PROOF = REPO / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP11"


def write_placements(lay: L.Layout, out_dir: Path) -> list[Path]:
    written = []
    for zone, doc in placements.documents(lay).items():
        path = out_dir / "hangar" / f"{zone}.placement.json"
        placement_lib.write(path, doc)
        errors = placement_lib.validate_file(path)
        if errors:
            raise SystemExit(f"{path}: " + "; ".join(errors))
        written.append(path)
    return written


def plot_levels(lay: L.Layout, graph: nav.NavGraph, out_dir: Path) -> list[Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        return []
    colours = {
        "shell": "#5b5b5b",
        "arena_canyon": "#8a6a2f",
        "arena_shuttle": "#4f5a63",
        "arena_booth": "#6b4a3a",
        "arena_catwalks": "#7a7a50",
        "armoury": "#3d3d3d",
    }
    out = []
    for name, lo, hi in L.LEVEL_BANDS:
        fig, ax = plt.subplots(figsize=(10, 8.4), dpi=110)
        ax.set_facecolor("#141414")
        mask = [(lo <= h < hi) for h in graph.hs]
        xs = [x for x, m in zip(graph.xs, mask, strict=True) if m]
        zs = [z for z, m in zip(graph.zs, mask, strict=True) if m]
        ax.scatter(xs, zs, s=1.5, c="#c9a227", alpha=0.7, linewidths=0, zorder=3)
        for b in lay.boxes:
            if b.h1 <= lo or b.h0 >= hi + 2.0 or (b.walk and b.h1 <= lo + 1.5):
                continue
            if (
                b.x1 < L.ARENA[0] - 3
                or b.x0 > L.ARENA[1] + 3
                or b.z1 < L.ARENA[2] - 3
                or b.z0 > L.ARENA[3] + 3
            ):
                continue
            face = colours[b.zone] if b.sight else "none"
            edge = "#d0d0d0" if b.piece_class else "#9a9a9a"
            ax.add_patch(
                Rectangle(
                    (b.x0, b.z0),
                    b.x1 - b.x0,
                    b.z1 - b.z0,
                    facecolor=face,
                    edgecolor=edge,
                    linewidth=0.5,
                    alpha=0.85,
                )
            )
        for s in lay.spawns:
            if lo <= s.h < hi:
                ax.plot(s.x, s.z, marker="o", color="#b3261e", markersize=6)
                ax.annotate(
                    s.id,
                    (s.x, s.z),
                    color="#e0e0e0",
                    fontsize=6,
                    xytext=(3, 3),
                    textcoords="offset points",
                )
        ax.set_xlim(L.ARENA[0] - 2, L.ARENA[1] + 2)
        ax.set_ylim(L.ARENA[3] + 2, L.ARENA[2] - 2)  # plan z grows toward the near wall: down
        ax.set_aspect("equal")
        ax.set_title(
            f"Hangar arena graybox, level {name} (h {lo:g}..{hi:g} m): nav dots, boxes, spawns",
            color="#e0e0e0",
            fontsize=9,
        )
        ax.tick_params(colors="#9a9a9a", labelsize=7)
        fig.patch.set_facecolor("#0c0c0c")
        path = out_dir / f"plan_{name}.png"
        fig.savefig(path, facecolor=fig.get_facecolor())
        plt.close(fig)
        out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="coarser sampling for a fast check")
    ap.add_argument("--bot-log", type=Path, help="harness time-to-contact log (JSON lines)")
    ap.add_argument("--out", type=Path, default=PROOF)
    args = ap.parse_args(argv)

    lay = L.build()
    graph = nav.build(lay)
    args.out.mkdir(parents=True, exist_ok=True)
    files = write_placements(lay, args.out / "placements")
    report = flow.report(graph, lay, quick=args.quick, bot_log=args.bot_log)
    (args.out / "flow.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    plots = plot_levels(lay, graph, args.out)
    print(f"placements: {len(files)} zones -> {args.out / 'placements'}")
    print(
        f"flow: longest sightline {report['sightlines']['longest_m']} m, "
        f"spawn min path {report['spawns']['min_path_m']} m, "
        f"time to contact median {report['time_to_contact']['median_s']} s"
    )
    print(f"plans: {len(plots)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
