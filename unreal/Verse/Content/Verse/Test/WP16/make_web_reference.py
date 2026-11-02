#!/usr/bin/env python3
"""Capture colour_reference.json for A16.3 from the IDE's own web painter.

The colour test screen (every 256-colour palette entry as foreground and as background,
bold 0-7, and RGB colours plain, inverse and dim) is written as escape sequences into a
real xterm buffer with the IDE's DARK_TERMINAL_THEME, read with snapshotXterm and painted
with paintTerminalTile (frontend components/society/verse/effects/terminalCanvas.ts), in
headless Chrome. The page reads every sample cell back from the canvas pixels: the block
cell, the core of an "M" glyph and the blank background cell. Verse.Visual.Screens.Colour
renders the same screen on a monitor render target on the GPU, samples it the same way
and reports the mean CIEDE2000 against these pixels.

    python unreal/Verse/Content/Verse/Test/WP16/make_web_reference.py \
        --node-modules <a checkout's dodaios/ui/web/frontend/node_modules>

It also saves the painted canvas as web_reference.png under
unreal/Verse/Saved/Harness/proof/WP16/16.2/ (proof only, never committed).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[3]  # unreal/Verse
REPO = PROJECT.parents[1]
FRONTEND = REPO / "dodaios" / "ui" / "web" / "frontend"

COLS = 64
ROWS = 30
PER_ROW = 20
GLYPHS = "\u2588M "
WIDTH = 1280
HEIGHT = 1500

CHROME_CANDIDATES = [
    Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    / "Google/Chrome/Application/chrome.exe",
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
]


def cells() -> list[dict]:
    out: list[dict] = []
    for i in range(256):
        out.append({"fg": {"i": i}, "bg": None, "attrs": []})
        out.append({"fg": None, "bg": {"i": i}, "attrs": []})
    for i in range(8):
        out.append({"fg": {"i": i}, "bg": None, "attrs": ["bold"]})
    for c in [
        "#000000",
        "#ffffff",
        "#e3242b",
        "#4fb86a",
        "#1f6feb",
        "#7f7f7f",
        "#ffb000",
        "#102030",
    ]:
        out.append({"fg": c, "bg": None, "attrs": []})
        out.append({"fg": None, "bg": c, "attrs": []})
        out.append({"fg": c, "bg": "#202020", "attrs": ["inverse"]})
        out.append({"fg": c, "bg": None, "attrs": ["dim"]})
    out.append({"fg": {"i": 2}, "bg": {"i": 236}, "attrs": ["dim", "inverse"]})
    out.append({"fg": None, "bg": None, "attrs": ["inverse"]})
    for k, c in enumerate(out):
        c["row"] = 1 + k // PER_ROW
        c["col"] = 2 + (k % PER_ROW) * len(GLYPHS)
    assert out[-1]["row"] < ROWS
    return out


def find_chrome() -> Path:
    for c in CHROME_CANDIDATES:
        if c.is_file():
            return c
    found = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    if not found:
        sys.exit("no Chrome found")
    return Path(found)


def chrome(exe: Path, page: Path, profile: Path, *extra: str) -> str:
    cmd = [
        str(exe),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--force-color-profile=srgb",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=15000",
        *extra,
        page.as_uri(),
    ]
    done = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
    )
    if done.returncode != 0:
        sys.exit(f"chrome failed ({done.returncode}): {done.stderr[-2000:]}")
    return done.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--node-modules", type=Path, default=FRONTEND / "node_modules")
    options = parser.parse_args()
    modules = options.node_modules.resolve()
    esbuild = modules / ".bin" / ("esbuild.cmd" if os.name == "nt" else "esbuild")
    if not esbuild.exists():
        sys.exit(f"esbuild not found under {modules}")
    screen = {
        "cols": COLS,
        "rows": ROWS,
        "width": WIDTH,
        "height": HEIGHT,
        "glyphs": GLYPHS,
        "samples": cells(),
    }

    with tempfile.TemporaryDirectory(prefix="wp16-web-") as tmp:
        work = Path(tmp)
        bundle = work / "bundle.js"
        env = {**os.environ, "NODE_PATH": str(modules)}
        subprocess.run(
            [
                str(esbuild),
                str(HERE / "web_reference.ts"),
                "--bundle",
                "--format=iife",
                "--log-level=warning",
                f"--tsconfig={FRONTEND / 'tsconfig.json'}",
                f"--outfile={bundle}",
            ],
            check=True,
            env=env,
            shell=os.name == "nt",
        )
        page = work / "page.html"
        page.write_text(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;background:#000}canvas{display:block}pre{display:none}</style></head><body>"
            f"<script>window.VERSE_SCREEN = {json.dumps(screen)};</script>"
            f"<script>{bundle.read_text(encoding='utf-8')}</script></body></html>",
            encoding="utf-8",
        )
        exe = find_chrome()
        dom = chrome(exe, page, work / "profile", "--dump-dom")
        match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
        if not match:
            sys.exit("the page wrote no samples:\n" + dom[-2000:])
        captured = json.loads(html.unescape(match.group(1)))
        proof = PROJECT / "Saved" / "Harness" / "proof" / "WP16" / "16.2"
        proof.mkdir(parents=True, exist_ok=True)
        chrome(
            exe,
            page,
            work / "profile",
            f"--screenshot={proof / 'web_reference.png'}",
            f"--window-size={WIDTH},{HEIGHT}",
        )

    doc = {
        "format": "wp16-web-colour-reference/1",
        "source": (
            "terminalCanvas.ts paintTerminalTile over snapshotXterm, DARK_TERMINAL_THEME,"
            " headless Chrome"
        ),
        "cols": COLS,
        "rows": ROWS,
        "glyphs": GLYPHS,
        **captured,
    }
    out = HERE / "colour_reference.json"
    out.write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"wrote {len(doc['samples'])} samples to {out.name};"
        f" canvas at {proof / 'web_reference.png'}"
    )


if __name__ == "__main__":
    main()
