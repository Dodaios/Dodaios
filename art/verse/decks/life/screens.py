"""Read-outs for the deck screens (WP12, decks look pass).

Own work, drawn with Pillow: seven sci-fi console layouts on the charcoal
ground of the brand, amber as the working colour, ivory for the accents, red
for the rare warning. No cyan, blue or violet: the never-colours of
art-pipeline 8.3 hold for emissive textures too. Each image feeds one `M_Verse_Screen` instance
(`MI_Deck_Screen_<Layout>`, `kit/mi_recipes.py`), which the deck look puts on
every `M_Screen` slot of a deck (`VerseDeckLife.cpp`) until WP16's live
monitors bind their own render targets.

Writes `art/verse/.cache/unreal/textures/decklife/T_Deck_Screen_<Layout>_E.png`
and one `verse.import/1` texture record per layout.

    python art/verse/decks/life/screens.py
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path

VERSE = Path(__file__).resolve().parents[2]
REPO = VERSE.parents[1]
OUT = VERSE / ".cache" / "unreal" / "textures" / "decklife"
RECORDS = REPO / "unreal" / "Verse" / "Art" / "Import" / "Textures" / "DeckLife"
#: Final size (16:10, the crew-pit screens are 1.5:1, the wall screens wider) and the
#: supersampling factor the shapes are drawn at.
WIDTH, HEIGHT = 1024, 640
SUPER = 2

GROUND = (7, 10, 14)
PANEL = (13, 19, 25)
AMBER = (240, 150, 50)  # the working colour (cyan is banned, art-pipeline 8.3)
AMBER_DIM = (78, 54, 26)
IVORY = (228, 222, 206)
IVORY_DIM = (96, 92, 84)
RED = (232, 72, 58)
WHITE = (214, 228, 234)

LAYOUTS = ("Tactical", "Systems", "Nav", "Comms", "Crew", "Reactor", "Map")


def _font(size: int):
    from PIL import ImageFont

    return ImageFont.load_default(size=size * SUPER)


def _s(*values: float) -> tuple[int, ...]:
    return tuple(int(v * SUPER) for v in values)


def _frame(draw, title: str, rng: random.Random) -> None:
    """Header bar, title, clock blocks and the thin panel border every layout shares."""
    draw.rectangle(_s(0, 0, WIDTH, HEIGHT), fill=GROUND)
    draw.rectangle(_s(12, 12, WIDTH - 12, HEIGHT - 12), outline=AMBER_DIM, width=SUPER)
    draw.rectangle(_s(12, 12, WIDTH - 12, 52), fill=PANEL)
    draw.rectangle(_s(12, 12, 20, 52), fill=IVORY)
    draw.text(_s(32, 20), title.upper(), fill=WHITE, font=_font(22))
    draw.text(
        _s(WIDTH - 230, 22),
        f"T+{rng.randint(10, 99):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}",
        fill=AMBER,
        font=_font(18),
    )
    for i in range(4):
        colour = IVORY if i == 0 else AMBER_DIM
        draw.rectangle(_s(WIDTH - 90 + i * 18, 26, WIDTH - 78 + i * 18, 38), fill=colour)


def _text_rows(
    draw, x: float, y: float, w: float, rows: int, rng: random.Random, gap: float = 22
) -> None:
    for r in range(rows):
        length = w * rng.uniform(0.35, 1.0)
        colour = IVORY if rng.random() < 0.12 else (RED if rng.random() < 0.04 else AMBER)
        draw.rectangle(_s(x, y + r * gap, x + 8, y + r * gap + 8), fill=colour)
        draw.rectangle(
            _s(x + 16, y + r * gap + 2, x + 16 + length, y + r * gap + 6), fill=AMBER_DIM
        )


def _tactical(draw, rng: random.Random) -> None:
    cx, cy, r = 360, 350, 250
    for k in range(1, 5):
        draw.ellipse(
            _s(cx - r * k / 4, cy - r * k / 4, cx + r * k / 4, cy + r * k / 4),
            outline=AMBER_DIM,
            width=SUPER * 2,
        )
    draw.line(_s(cx - r, cy, cx + r, cy), fill=AMBER_DIM, width=SUPER)
    draw.line(_s(cx, cy - r, cx, cy + r), fill=AMBER_DIM, width=SUPER)
    for a in range(0, 60, 2):
        shade = tuple(int(c * (1 - a / 60) * 0.7) for c in AMBER)
        ang = math.radians(-40 - a)
        draw.line(
            _s(cx, cy, cx + r * math.cos(ang), cy + r * math.sin(ang)), fill=shade, width=SUPER * 3
        )
    for _ in range(9):
        ang, dist = rng.uniform(0, math.tau), rng.uniform(0.2, 0.95) * r
        x, y = cx + dist * math.cos(ang), cy + dist * math.sin(ang)
        colour = RED if rng.random() < 0.25 else IVORY
        draw.ellipse(_s(x - 7, y - 7, x + 7, y + 7), fill=colour)
        draw.line(_s(x + 9, y - 9, x + 30, y - 24), fill=colour, width=SUPER)
    draw.rectangle(_s(660, 80, 990, 600), fill=PANEL)
    draw.text(_s(676, 92), "CONTACTS", fill=IVORY, font=_font(18))
    _text_rows(draw, 676, 130, 280, 20, rng)


def _systems(draw, rng: random.Random) -> None:
    for i in range(8):
        x = 60 + i * 64
        value = rng.uniform(0.25, 0.95)
        draw.rectangle(_s(x, 120, x + 36, 400), fill=PANEL)
        colour = RED if value > 0.9 else (IVORY if value > 0.75 else AMBER)
        draw.rectangle(_s(x, 400 - 280 * value, x + 36, 400), fill=colour)
        draw.text(_s(x, 412), f"S{i + 1}", fill=WHITE, font=_font(16))
    pts = []
    level = 0.5
    for i in range(60):
        level = min(0.95, max(0.05, level + rng.uniform(-0.12, 0.12)))
        pts.append((600 + i * 6.4, 400 - 260 * level))
    draw.rectangle(_s(590, 120, 990, 410), fill=PANEL)
    for k in range(1, 5):
        draw.line(_s(590, 120 + k * 58, 990, 120 + k * 58), fill=AMBER_DIM, width=SUPER)
    draw.line([_s(*p) for p in pts], fill=AMBER, width=SUPER * 3)
    for i in range(3):
        cx, cy = 140 + i * 300, 530
        draw.arc(_s(cx - 60, cy - 60, cx + 60, cy + 60), 135, 405, fill=AMBER_DIM, width=SUPER * 8)
        end = 135 + 270 * rng.uniform(0.3, 0.95)
        draw.arc(
            _s(cx - 60, cy - 60, cx + 60, cy + 60),
            135,
            end,
            fill=IVORY if i == 1 else AMBER,
            width=SUPER * 8,
        )
        draw.text(_s(cx - 24, cy - 10), f"{int((end - 135) / 2.7)}%", fill=WHITE, font=_font(20))


def _nav(draw, rng: random.Random) -> None:
    cx, cy = 420, 350
    draw.ellipse(
        _s(cx - 70, cy - 70, cx + 70, cy + 70), fill=(40, 32, 22), outline=AMBER, width=SUPER * 2
    )
    for k, (a, b) in enumerate(((180, 120), (270, 170), (360, 230))):
        draw.ellipse(
            _s(cx - a, cy - b, cx + a, cy + b),
            outline=AMBER_DIM if k != 1 else AMBER,
            width=SUPER * 2,
        )
    ang = rng.uniform(0, math.tau)
    sx, sy = cx + 270 * math.cos(ang), cy + 170 * math.sin(ang)
    draw.polygon([_s(sx, sy - 12), _s(sx + 10, sy + 8), _s(sx - 10, sy + 8)], fill=IVORY)
    for i in range(30):
        t = ang + 0.08 * i
        if i % 2 == 0:
            draw.line(
                _s(
                    cx + 270 * math.cos(t),
                    cy + 170 * math.sin(t),
                    cx + 270 * math.cos(t + 0.06),
                    cy + 170 * math.sin(t + 0.06),
                ),
                fill=IVORY,
                width=SUPER * 2,
            )
    draw.rectangle(_s(800, 80, 990, 600), fill=PANEL)
    for i, label in enumerate(("ALT", "VEL", "INC", "ECC", "PER", "APO")):
        draw.text(_s(812, 96 + i * 82), label, fill=IVORY_DIM if i % 2 else IVORY, font=_font(16))
        draw.text(_s(812, 118 + i * 82), f"{rng.uniform(0, 999):07.2f}", fill=AMBER, font=_font(24))


def _comms(draw, rng: random.Random) -> None:
    draw.rectangle(_s(40, 80, 600, 600), fill=PANEL)
    _text_rows(draw, 56, 100, 500, 22, rng)
    draw.rectangle(_s(630, 80, 990, 330), fill=PANEL)
    for i in range(90):
        h = abs(math.sin(i * 0.31) * rng.uniform(0.2, 1.0)) * 100
        draw.line(_s(640 + i * 3.8, 205 - h, 640 + i * 3.8, 205 + h), fill=AMBER, width=SUPER * 2)
    draw.rectangle(_s(630, 350, 990, 600), fill=PANEL)
    draw.text(_s(646, 362), "CHANNELS", fill=IVORY, font=_font(18))
    for i in range(6):
        y = 400 + i * 32
        draw.rectangle(_s(646, y, 970, y + 22), outline=AMBER_DIM, width=SUPER)
        draw.rectangle(_s(646, y, 646 + 324 * rng.uniform(0.2, 1.0), y + 22), fill=AMBER_DIM)
        draw.ellipse(_s(950, y + 5, 962, y + 17), fill=IVORY if i == 2 else AMBER)


def _crew(draw, rng: random.Random) -> None:
    for i in range(12):
        col, row = i % 4, i // 4
        x, y = 40 + col * 240, 90 + row * 175
        draw.rectangle(_s(x, y, x + 220, y + 155), fill=PANEL, outline=AMBER_DIM, width=SUPER)
        draw.ellipse(
            _s(x + 14, y + 14, x + 74, y + 74), fill=AMBER_DIM, outline=AMBER, width=SUPER * 2
        )
        draw.rectangle(_s(x + 88, y + 22, x + 88 + rng.uniform(60, 120), y + 32), fill=WHITE)
        draw.rectangle(_s(x + 88, y + 44, x + 88 + rng.uniform(40, 100), y + 52), fill=AMBER_DIM)
        status = RED if rng.random() < 0.1 else (IVORY if rng.random() < 0.3 else AMBER)
        draw.ellipse(_s(x + 190, y + 18, x + 206, y + 34), fill=status)
        draw.rectangle(_s(x + 14, y + 100, x + 206, y + 112), fill=GROUND)
        draw.rectangle(
            _s(x + 14, y + 100, x + 14 + 192 * rng.uniform(0.3, 1.0), y + 112), fill=status
        )


def _reactor(draw, rng: random.Random) -> None:
    cx, cy, r = 330, 380, 230
    draw.arc(_s(cx - r, cy - r, cx + r, cy + r), 150, 390, fill=AMBER_DIM, width=SUPER * 22)
    level = rng.uniform(0.55, 0.85)
    draw.arc(
        _s(cx - r, cy - r, cx + r, cy + r), 150, 150 + 240 * level, fill=IVORY, width=SUPER * 22
    )
    draw.arc(
        _s(cx - r + 40, cy - r + 40, cx + r - 40, cy + r - 40),
        150,
        390,
        fill=AMBER,
        width=SUPER * 3,
    )
    draw.text(_s(cx - 70, cy - 30), f"{level * 100:.1f}%", fill=WHITE, font=_font(44))
    draw.text(_s(cx - 60, cy + 30), "CORE OUTPUT", fill=AMBER, font=_font(16))
    draw.rectangle(_s(620, 80, 990, 600), fill=PANEL)
    for k in range(3):
        base = 170 + k * 150
        pts = [
            (632 + i * 3.4, base + 40 * math.sin(i * (0.12 + k * 0.05) + rng.uniform(0, 0.3)))
            for i in range(104)
        ]
        draw.line([_s(*p) for p in pts], fill=(AMBER, IVORY, AMBER)[k], width=SUPER * 2)
        draw.line(_s(632, base + 60, 980, base + 60), fill=AMBER_DIM, width=SUPER)


def _map(draw, rng: random.Random) -> None:
    size = 36
    for row in range(-1, 20):
        for col in range(-1, 18):
            x = 60 + col * size * 1.5
            y = 70 + row * size * 0.866 * 2 + (size * 0.866 if col % 2 else 0)
            pts = [
                _s(
                    x + size * math.cos(math.radians(60 * k)),
                    y + size * math.sin(math.radians(60 * k)),
                )
                for k in range(6)
            ]
            roll = rng.random()
            fill = (44, 32, 18) if roll < 0.25 else (GROUND if roll < 0.9 else IVORY_DIM)
            draw.polygon(pts, fill=fill, outline=AMBER_DIM)
    for _ in range(5):
        x, y = rng.uniform(150, 900), rng.uniform(150, 560)
        draw.ellipse(_s(x - 14, y - 14, x + 14, y + 14), outline=IVORY, width=SUPER * 3)
        draw.line(_s(x - 24, y, x + 24, y), fill=IVORY, width=SUPER)
        draw.line(_s(x, y - 24, x, y + 24), fill=IVORY, width=SUPER)
    draw.rectangle(_s(12, 12, WIDTH - 12, 52), fill=PANEL)


DRAW = {
    "Tactical": _tactical,
    "Systems": _systems,
    "Nav": _nav,
    "Comms": _comms,
    "Crew": _crew,
    "Reactor": _reactor,
    "Map": _map,
}


def render(layout: str):
    """One layout as an RGB image at the final size."""
    from PIL import Image, ImageDraw, ImageFilter

    rng = random.Random(f"verse-deck-screen-{layout}")  # noqa: S311 - seeded art, not crypto
    image = Image.new("RGB", (WIDTH * SUPER, HEIGHT * SUPER), GROUND)
    draw = ImageDraw.Draw(image)
    _frame(draw, layout, rng)
    DRAW[layout](draw, rng)
    if layout == "Map":
        draw.text(_s(32, 20), "SECTOR MAP", fill=WHITE, font=_font(22))
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    # Scanlines and a soft bloom of the bright strokes: a lit panel, not a flat print.
    glow = image.filter(ImageFilter.GaussianBlur(6))
    image = Image.blend(image, glow, 0.25)
    lines = Image.new("L", (WIDTH, HEIGHT), 255)
    ldraw = ImageDraw.Draw(lines)
    for y in range(0, HEIGHT, 3):
        ldraw.line((0, y, WIDTH, y), fill=215)
    return Image.composite(image, Image.new("RGB", image.size, (0, 0, 0)), lines)


def record(name: str, layout: str, png: Path) -> dict:
    return {
        "asset_path": f"/Game/Verse/Textures/DeckLife/{name}.{name}",
        "export": {
            "blender": "0.0.0",
            "file": png.relative_to(REPO).as_posix(),
            "format": "png",
            "settings_id": "png-ue/1",
            "sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
        },
        "kind": "texture",
        "license": {"kind": "own"},
        "lightmap": "none",
        "name": name,
        "owner": "WP12",
        "schema": "verse.import/1",
        "source": {
            "args": {"layout": layout},
            "builder": "art/verse/decks/life/screens.py",
            "function": "main",
        },
        "texture": {
            "compression": "Default",
            "flip_green": False,
            "group": "World",
            "max_size": WIDTH,
            "srgb": True,
        },
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    RECORDS.mkdir(parents=True, exist_ok=True)
    for layout in LAYOUTS:
        name = f"T_Deck_Screen_{layout}_E"
        png = OUT / f"{name}.png"
        render(layout).save(png, optimize=True)
        text = json.dumps(record(name, layout, png), indent=2, sort_keys=True) + "\n"
        (RECORDS / f"{name}.import.json").write_bytes(text.encode("utf-8"))
        print(f"[verse] {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
