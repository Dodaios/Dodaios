"""Compose the command-props lookdev contact sheets (outside Blender, Pillow).

    python art/verse/kit/props/command/compose_sheet.py

Reads the renders and ``pieces.json`` written by ``sheet.py`` and writes
``sheet_game.png`` (every piece at game density, true relative scale) and
``sheet_crop.png`` (the 3x crops, scaled to fit) next to them.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[3] / ".cache" / "lookdev" / "props-command"
BG = (12, 12, 13)
INK = (200, 202, 205)


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("consola.ttf", "DejaVuSansMono.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def compose(tag: str, max_tile: int | None, columns: int) -> Path | None:
    report = json.loads((OUT / "pieces.json").read_text(encoding="utf-8"))
    tiles = []
    for name, info in report.items():
        path = OUT / f"{name}_{tag}.png"
        if not path.exists():
            continue
        img = Image.open(path).convert("RGB")
        if max_tile and max(img.size) > max_tile:
            img.thumbnail((max_tile, max_tile))
        dims = info.get("dims_measured") or [0, 0, 0]
        label = f"{name[3:]}  {dims[0]:.2f}x{dims[1]:.2f}x{dims[2]:.2f} m"
        tiles.append((label, img))
    if not tiles:
        return None
    font = _font(13)
    pad, label_h = 10, 20
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def tile_w(tile) -> int:
        return max(tile[1].width, int(measure.textlength(tile[0], font=font)))

    rows = [tiles[i : i + columns] for i in range(0, len(tiles), columns)]
    width = max(sum(tile_w(t) + pad for t in row) for row in rows) + pad
    heights = [max(t[1].height for t in row) + label_h + pad for row in rows]
    sheet = Image.new("RGB", (width, sum(heights) + pad), BG)
    draw = ImageDraw.Draw(sheet)
    y = pad
    for row, h in zip(rows, heights, strict=True):
        x = pad
        for tile in row:
            label, img = tile
            sheet.paste(img, (x, y + label_h))
            draw.text((x, y + 2), label, fill=INK, font=font)
            x += tile_w(tile) + pad
        y += h
    target = OUT / f"sheet_{tag}.png"
    sheet.save(target)
    return target


def _socket_summary(names: list[str]) -> str:
    """'SOCKET_seat_<id>__01'... -> 'seat 01-12' (local ids; '' = the placement id)."""
    kinds: dict[str, list[str]] = {}
    for name in names:
        kind, _, rest = name[len("SOCKET_") :].partition("_<id>")
        kinds.setdefault(kind, []).append(rest[2:] if rest.startswith("__") else "''")
    parts = []
    for kind, ids in kinds.items():
        ids = sorted(set(ids))
        if len(ids) > 3 and all(i.isdigit() for i in ids):
            parts.append(f"{kind} {ids[0]}-{ids[-1]}")
        else:
            parts.append(f"{kind} {' '.join(ids)}")
    return "; ".join(parts)


def markdown_table() -> str:
    """Piece table (dims, anchor, sockets) for README.md, from pieces.json."""
    report = json.loads((OUT / "pieces.json").read_text(encoding="utf-8"))
    lines = ["| Piece | W x D x H (m) | Anchor | Sockets |", "|---|---|---|---|"]
    for name, info in report.items():
        d = info["dims_measured"]
        sockets = _socket_summary(info["sockets"]) or "-"
        dims = f"{d[0]:.2f} x {d[1]:.2f} x {d[2]:.2f}"
        lines.append(f"| `{name}` | {dims} | {info.get('anchor')} | {sockets} |")
    return "\n".join(lines)


def main() -> None:
    import sys

    if "--table" in sys.argv:
        print(markdown_table())
        return
    for tag, max_tile, columns in (("game", None, 8), ("crop", 520, 6)):
        path = compose(tag, max_tile, columns)
        if path:
            print(f"wrote {path}")


if __name__ == "__main__":
    main()
