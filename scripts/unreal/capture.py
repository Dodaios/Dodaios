#!/usr/bin/env python3
"""Scripted-camera screenshots, palette share measurement and the evidence folder layout.

``shots`` renders the reference views of ``unreal/Verse/Harness/capture/cameras.json``
(or another ``verse.capture/1`` file): one rendered game process per map, under
the machine lock, window off the person's monitors, UI hidden. ``VerseHarness``
places the camera at each view, waits for shader compiles and streaming, then
writes ``<view>.png``. Every shot is measured against the Military-Industrial Noir
palette (``contracts/art-pipeline.md`` 8.1 caps, 8.3 rendered-pixel ban), and a
``manifest.json`` lands beside the images in the evidence folder
``unreal/Verse/Saved/Harness/proof/WP<nn>/<sub-task>/`` (work-packages.md 0.4).

    python scripts/unreal/capture.py shots --wp WP12 --subtask 12.3 [--view hangar_floor]
    python scripts/unreal/capture.py palette shot.png [more.png ...]
    python scripts/unreal/capture.py proof-dir --wp WP10 --subtask 10.8
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common

CAMERAS_FILE = common.PROJECT_DIR / "Harness" / "capture" / "cameras.json"
RUN_TIMEOUT_S = 20 * 60

#: art-pipeline.md 8.1: role -> (sRGB hexes, min share, max share). None = no bound.
PALETTE: dict[str, tuple[tuple[str, ...], float | None, float | None]] = {
    "void_black": (("#0B0C0E",), 0.25, 0.45),
    "blackened_steel": (("#16171A",), 0.15, 0.30),
    "graphite": (("#2A2D31",), 0.10, 0.25),
    "gunmetal": (("#3B3F47",), 0.05, 0.15),
    "concrete": (("#5E6368", "#6A6C6B"), 0.05, 0.20),
    "oil_grime": (("#121212",), None, None),
    "worn_steel": (("#A9ADB2",), None, 0.03),
    "work_light": (("#F2F4F5", "#D9DDE0"), 0.03, 0.08),
    "signal_red": (("#E3242B",), None, 0.015),
    "amber": (("#F2A33A",), None, 0.008),
    "hazard_yellow": (("#D9B23A",), None, 0.01),
    "brand_gold": (("#C8A24A",), None, 0.005),
}
#: A pixel belongs to its nearest role when within this CIE76 distance, else "other".
MATCH_DELTA_E = 12.0
#: art-pipeline.md 8.3 rendered-pixel rule.
BANNED_HUE = (160.0, 330.0)
BANNED_SAT = 0.25
BANNED_VALUE = 0.08
MAX_SAMPLE_PIXELS = 1_000_000


def _hex_rgb(text: str) -> tuple[int, int, int]:
    text = text.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def srgb_to_lab(rgb):  # numpy array (..., 3) of 0-255 -> CIELAB (D65)
    import numpy as np

    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack(
        [116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1
    )


def banned_mask(rgb):
    """Pixels the rendered-pixel rule bans: hue 160-330 deg, saturation > 0.25, value > 0.08."""
    import numpy as np

    c = np.asarray(rgb, dtype=np.float64) / 255.0
    mx, mn = c.max(-1), c.min(-1)
    delta = mx - mn
    sat = np.where(mx > 0, delta / np.where(mx > 0, mx, 1), 0)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    safe = np.where(delta > 0, delta, 1)
    hue = np.where(
        mx == r, ((g - b) / safe) % 6, np.where(mx == g, (b - r) / safe + 2, (r - g) / safe + 4)
    )
    hue = np.where(delta > 0, hue * 60.0, 0.0)
    return (
        (hue >= BANNED_HUE[0]) & (hue <= BANNED_HUE[1]) & (sat > BANNED_SAT) & (mx > BANNED_VALUE)
    )


def measure(pixels) -> dict:
    """Palette shares, cap verdicts and banned-pixel count of an (H, W, 3) uint8 array."""
    import numpy as np

    flat = np.asarray(pixels)[..., :3].reshape(-1, 3)
    if len(flat) > MAX_SAMPLE_PIXELS:
        step = int(np.ceil(len(flat) / MAX_SAMPLE_PIXELS))
        flat = flat[::step]
    roles, refs = [], []
    for role, (hexes, _lo, _hi) in PALETTE.items():
        for h in hexes:
            roles.append(role)
            refs.append(_hex_rgb(h))
    lab = srgb_to_lab(flat)
    ref_lab = srgb_to_lab(np.array(refs))
    dist = np.linalg.norm(lab[:, None, :] - ref_lab[None, :, :], axis=-1)
    nearest = dist.argmin(1)
    matched = dist[np.arange(len(flat)), nearest] <= MATCH_DELTA_E
    total = len(flat)
    shares = {role: 0.0 for role in PALETTE}
    for idx, role in enumerate(roles):
        shares[role] += float(((nearest == idx) & matched).sum()) / total
    shares["other"] = float((~matched).sum()) / total
    caps = []
    for role, (_hexes, lo, hi) in PALETTE.items():
        share = shares[role]
        status = "fail" if hi is not None and share > hi else "pass"
        caps.append(
            {
                "role": role,
                "share": round(share, 5),
                "min": lo,
                "max": hi,
                "status": status,
                "belowRange": lo is not None and share < lo,
            }
        )
    banned = int(banned_mask(flat).sum())
    return {
        "pixels": total,
        "shares": {k: round(v, 5) for k, v in shares.items()},
        "caps": caps,
        "bannedPixels": banned,
        "pass": banned == 0 and all(c["status"] == "pass" for c in caps),
    }


def measure_file(path: Path) -> dict:
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        pixels = np.asarray(image.convert("RGB"))
    result = measure(pixels)
    result["file"] = str(path)
    return result


def proof_dir(worktree: Path, wp: str, subtask: str) -> Path:
    """``unreal/Verse/Saved/Harness/proof/WP<nn>/<sub-task>/`` (work-packages.md 0.4)."""
    if not re.fullmatch(r"WP\d{2}", wp):
        raise common.UnrealScriptError(f"package id must look like WP07, got {wp!r}")
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}[a-z]?", subtask):
        raise common.UnrealScriptError(f"sub-task must look like 7.3 or 7.3a, got {subtask!r}")
    return worktree / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / wp / subtask


def views_by_map(doc: Mapping, only: Sequence[str] | None = None) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for view in doc["views"]:
        if only and view["id"] not in only:
            continue
        groups.setdefault(view["map"], []).append(view)
    return groups


def command_for(
    engine: Path,
    project: Path,
    map_path: str,
    capture_file: Path,
    out_dir: Path,
    log: Path,
    width: int = 1920,
    height: int = 1080,
) -> list[str]:
    return [
        str(common.editor_cmd(engine)),
        str(project),
        map_path,
        "-game",
        "-d3d12",
        "-windowed",
        f"-ResX={width}",
        f"-ResY={height}",
        "-WinX=-20000",
        "-WinY=-20000",
        "-unattended",
        "-nosound",
        "-NoP4",
        f"-VerseCapture={capture_file}",
        f"-VerseCaptureOut={out_dir}",
        f"-abslog={log}",
    ]


def shots(doc: Mapping, out_dir: Path, worktree: Path, only: Sequence[str] | None = None) -> dict:
    from scripts.unreal import with_lock

    engine, project = common.engine_root(), common.project_file(worktree)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    for k, (map_path, views) in enumerate(views_by_map(doc, only).items()):
        capture_file = out_dir / f"capture{k}.json"
        part = {
            "schema": "verse.capture/1",
            "id": f"{doc['id']}.{k}",
            "map": map_path,
            "views": views,
            "settleFrames": doc.get("settleFrames", 30),
        }
        capture_file.write_text(json.dumps(part, indent=2), encoding="utf-8")
        log = out_dir / f"capture{k}.log"
        command = command_for(engine, project, map_path, capture_file, out_dir, log)
        with with_lock.MachineLock("capture", " ".join(command[:3])):
            try:
                code = subprocess.run(
                    command,
                    timeout=RUN_TIMEOUT_S,
                    check=False,  # noqa: S603
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
            except subprocess.TimeoutExpired:
                code = 124
        runs.append({"map": map_path, "returncode": code, "log": str(log)})
    images = []
    for view in [v for vs in views_by_map(doc, only).values() for v in vs]:
        png = out_dir / f"{view['id']}.png"
        entry = {
            "view": view["id"],
            "deck": view.get("deck"),
            "file": str(png),
            "exists": png.exists(),
        }
        if png.exists():
            entry["palette"] = measure_file(png)
        images.append(entry)
    manifest = {
        "schema": "verse.proof/1",
        "branch": common.current_branch(worktree),
        "created": common.run_stamp(),
        "runs": runs,
        "images": images,
        "pass": all(r["returncode"] == 0 for r in runs) and all(i["exists"] for i in images),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    shots_p = sub.add_parser("shots")
    shots_p.add_argument("--views", type=Path, default=CAMERAS_FILE)
    shots_p.add_argument("--view", action="append", help="Only these view ids (repeatable).")
    shots_p.add_argument("--wp", default="WP10")
    shots_p.add_argument("--subtask", default="10.8")
    shots_p.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    pal_p = sub.add_parser("palette")
    pal_p.add_argument("images", type=Path, nargs="+")
    dir_p = sub.add_parser("proof-dir")
    dir_p.add_argument("--wp", required=True)
    dir_p.add_argument("--subtask", required=True)
    dir_p.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "proof-dir":
            path = proof_dir(args.worktree.resolve(), args.wp, args.subtask)
            path.mkdir(parents=True, exist_ok=True)
            print(path)
            return 0
        if args.cmd == "palette":
            results = [measure_file(p) for p in args.images]
            print(json.dumps(results, indent=2))
            return 0 if all(r["pass"] for r in results) else 1
        out = proof_dir(args.worktree.resolve(), args.wp, args.subtask)
        manifest = shots(
            json.loads(args.views.read_text(encoding="utf-8")),
            out,
            args.worktree.resolve(),
            args.view,
        )
    except common.UnrealScriptError as error:
        return common.exit_with(error)
    for image in manifest["images"]:
        verdict = image.get("palette", {})
        print(
            f"{image['view']}: {'ok' if image['exists'] else 'MISSING'} "
            f"banned={verdict.get('bannedPixels', 'n/a')} palette={verdict.get('pass', 'n/a')}"
        )
    print(f"capture: {'OK' if manifest['pass'] else 'FAIL'} ({out / 'manifest.json'})")
    return 0 if manifest["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
