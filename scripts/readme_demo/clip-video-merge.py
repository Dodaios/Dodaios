#!/usr/bin/env python3
"""Merge a take of the README video with its pick-up into one take folder.

    python3 scripts/readme_demo/clip-video-merge.py TAKE PICKUP OUT

clip-video-take.cjs with DEMO_FROM=memory films the end again in the same
instance when a take stopped after the deletion. This links the frames of
both into OUT (no copies) and writes one take.json: the take's stretches up
to the pick-up, then the pick-up's, so clip-video-cut.cjs cuts both as one.
"""

import json
import os
import sys
from pathlib import Path

take, pickup, out = (Path(a).resolve() for a in sys.argv[1:4])
out.mkdir(parents=True, exist_ok=True)
a = json.loads((take / "take.json").read_text())
b = json.loads((pickup / "take.json").read_text())
frames = []
for src, data, prefix in ((take, a, "a"), (pickup, b, "b")):
    for f in data["frames"]:
        name = f"{prefix}{f['name']}"
        link = out / name
        if not link.exists():
            os.symlink(src / f["name"], link)
        frames.append({**f, "name": name})
merged = {
    **a,
    "stretches": a["stretches"] + b["stretches"],
    "marks": a["marks"] + b["marks"],
    "typed": {**a.get("typed", {}), **b.get("typed", {})},
    "notes": {**a.get("notes", {}), "pickup": b.get("notes", {})},
    "frames": sorted(frames, key=lambda f: f["ts"]),
}
(out / "take.json").write_text(json.dumps(merged))
print(f"{len(frames)} frames, {len(merged['stretches'])} stretches -> {out}")
