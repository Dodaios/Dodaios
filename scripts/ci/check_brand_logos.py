#!/usr/bin/env python3
"""Gate every third-party brand mark the frontend ships.

Failure modes this catches, all of which shipped at least once:

1. **An unsafe SVG.** An SVG is executable content: it can carry a script, an
   event handler, or a reference that phones a third party on render. These
   files come from outside the project, so they are checked rather than
   trusted.
2. **A licence gap.** A mark in a folder with no row in its ``LOGOS.md`` is an
   asset whose provenance nobody can reconstruct later.
3. **A wordmark in a square tile.** A horizontal logotype squeezed into 40 px
   is unreadable. Vendors publish both; the icon variant is the one that
   belongs here.
4. **A modified mark.** Brand guidelines (and nominative use) require a logo
   exactly as the vendor provides it. A ledger row that records a redrawn,
   traced or recoloured file fails, and so does an SVG carrying the app's own
   ink colour (``#F4F4F5``) - the fingerprint of the old recoloured copies.
   Single-colour marks are drawn as a mask over neutral text ink instead.
5. **An unsourced public copy.** ``public/`` is served verbatim, outside the
   ledgered ``src/assets`` folders. A logo file there needs its own ``LOGOS.md``
   row next to it; the retired ``public/provider-logos`` and
   ``public/agent-logos`` folders must stay gone (import the ledgered file from
   ``src/assets`` instead).

Run standalone or from the pre-push hook. Exit 0 = clean, 1 = findings.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND = _ROOT / "dodaios" / "ui" / "web" / "frontend"
_FRONTEND_ASSETS = _FRONTEND / "src" / "assets"
_PUBLIC = _FRONTEND / "public"
# One rulebook for every third-party mark folder. Each keeps its own LOGOS.md
# ledger next to the files it records.
_FOLDERS = (
    _FRONTEND_ASSETS / "brands",
    _FRONTEND_ASSETS / "providers",
    _FRONTEND_ASSETS / "clis",
    _FRONTEND_ASSETS / "tool-brands",
    _FRONTEND_ASSETS / "editors",
    _FRONTEND_ASSETS / "agents",
)
# Folders that held unsourced, recoloured duplicates. They must not come back.
_RETIRED_PUBLIC = (_PUBLIC / "provider-logos", _PUBLIC / "agent-logos")
# First-party files in public/ (the app's own mark and icons) need no ledger.
_FIRST_PARTY_PREFIX = "dodaios"

# Generous: a real icon is square, but a few legitimate marks are slightly
# rectangular. Anything past this is a logotype.
_MIN_ASPECT, _MAX_ASPECT = 0.65, 1.45  # Figma's icon is a 2:3 stack
_MAX_BYTES = 60_000

_ACTIVE = re.compile(r"<\s*(script|foreignObject|iframe|animate|set)\b", re.I)
_EVENT_ATTR = re.compile(r"\son[a-z]+\s*=", re.I)
_EXTERNAL = re.compile(r"(href|xlink:href|src)\s*=\s*[\"']\s*(https?:|//)", re.I)
_RASTER = re.compile(r"<\s*image\b", re.I)
_VIEWBOX = re.compile(r'viewBox\s*=\s*["\']([\d.eE+\-\s]+)["\']', re.I)
# The app's dark-theme ink. Vendor files never use it; every recoloured copy did.
_APP_INK = re.compile(r"#f4f4f5\b", re.I)
# A ledger row that admits the file is not the vendor's own drawing.
_MODIFIED = re.compile(
    r"\b(re-?drawn|redraw\w*|re-?colou?r\w*|vectori[sz]\w*|traced|hand-?drawn|tint\w*)\b",
    re.I,
)
_LOGO_SUFFIXES = {".svg", ".png", ".ico", ".webp", ".jpg", ".jpeg"}


def _aspect(svg: str) -> float | None:
    match = _VIEWBOX.search(svg)
    if not match:
        return None
    try:
        parts = [float(value) for value in match.group(1).split()]
    except ValueError:
        return None
    if len(parts) != 4 or parts[3] == 0:
        return None
    return parts[2] / parts[3]


def _ledger_row(ledger: str, path: Path) -> str | None:
    """The table row that records ``path``: ``| id |`` or ``| `file.ext` |``."""
    keys = (f"| {path.stem} |", f"| `{path.name}` |")
    for line in ledger.splitlines():
        if line.lstrip().startswith("|") and any(key in line for key in keys):
            return line
    return None


def _check_ledger(ledger: str, path: Path, problems: list[str]) -> None:
    where = path.relative_to(_ROOT).as_posix()
    row = _ledger_row(ledger, path)
    if row is None:
        problems.append(
            f"{where}: no row in LOGOS.md - every bundled mark needs its "
            "source and legal basis recorded"
        )
    elif _MODIFIED.search(row):
        problems.append(
            f"{where}: its LOGOS.md row records a redrawn or recoloured mark - "
            "ship the vendor's file unmodified, or a neutral icon instead"
        )


def _check_svg(path: Path, problems: list[str], *, require_icon_shape: bool) -> None:
    svg = path.read_text(encoding="utf-8", errors="replace")
    where = path.relative_to(_ROOT).as_posix()

    if _ACTIVE.search(svg):
        problems.append(f"{where}: contains active content (script/animation/embed)")
    if _EVENT_ATTR.search(svg):
        problems.append(f"{where}: carries an inline event handler")
    if _EXTERNAL.search(svg):
        problems.append(f"{where}: references a third-party URL at render time")
    if _RASTER.search(svg):
        problems.append(f"{where}: embeds a raster image (use vector paths)")
    if _APP_INK.search(svg):
        problems.append(
            f"{where}: painted in the app's ink #F4F4F5, i.e. recoloured - ship the "
            "vendor's file and draw a single-colour mark as a mask instead"
        )
    if len(svg.encode("utf-8")) > _MAX_BYTES:
        problems.append(f"{where}: {len(svg)} bytes exceeds the {_MAX_BYTES} limit")

    if not require_icon_shape:
        return
    ratio = _aspect(svg)
    if ratio is None:
        problems.append(f"{where}: no usable viewBox, so it cannot be laid out")
    elif not (_MIN_ASPECT <= ratio <= _MAX_ASPECT):
        problems.append(
            f"{where}: aspect {ratio:.2f} is a wordmark, not an icon - "
            "use the vendor's icon variant"
        )


def _read_ledger(folder: Path) -> str:
    ledger_path = folder / "LOGOS.md"
    return ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""


def _check_folder(folder: Path, problems: list[str]) -> int:
    """Append findings for one folder; return how many marks it holds."""
    ledger = _read_ledger(folder)
    marks = sorted(folder.glob("*.svg"))
    for path in marks:
        _check_svg(path, problems, require_icon_shape=True)
        _check_ledger(ledger, path, problems)
    # A raster mark is allowed only as a standalone file (a vendor that ships
    # no vector icon), and it still needs its row.
    rasters = sorted(folder.glob("*.png"))
    for path in rasters:
        _check_ledger(ledger, path, problems)
    return len(marks) + len(rasters)


def _check_public(problems: list[str]) -> int:
    """Every logo-shaped file under public/ is first-party or ledgered."""
    for retired in _RETIRED_PUBLIC:
        if retired.exists() and any(p.is_file() for p in retired.rglob("*")):
            where = retired.relative_to(_ROOT).as_posix()
            problems.append(
                f"{where}/: unledgered public logo copies are retired - import the "
                "ledgered file from src/assets instead"
            )
    if not _PUBLIC.is_dir():
        return 0
    count = 0
    for path in sorted(_PUBLIC.rglob("*")):
        if not path.is_file() or path.name.lower().startswith(_FIRST_PARTY_PREFIX):
            continue
        suffix = path.suffix.lower()
        logo_like = suffix in {".svg", ".ico"} or (
            suffix in _LOGO_SUFFIXES and "logo" in path.name.lower()
        )
        if not logo_like:
            continue
        count += 1
        if suffix == ".svg":
            _check_svg(path, problems, require_icon_shape=False)
        _check_ledger(_read_ledger(path.parent), path, problems)
    return count


def main() -> int:
    problems: list[str] = []
    count = 0
    checked = 0
    for folder in _FOLDERS:
        if not folder.is_dir():
            continue
        checked += 1
        count += _check_folder(folder, problems)
    count += _check_public(problems)
    if checked == 0:
        print("check_brand_logos: no brand folders - nothing to check.")
        return 0

    if problems:
        print("BRAND-LOGO GATE FAILED\n")
        for problem in problems:
            print(f"  [x] {problem}")
        print(f"\n{len(problems)} finding(s). See the LOGOS.md next to the files for the rules.")
        return 1

    print(f"check_brand_logos: OK - {count} bundled marks, all safe and recorded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
