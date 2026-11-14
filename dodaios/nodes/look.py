"""See a node the way the person sees it: pictures of its rendered page.

The assistant writes a node's content blind: the type's renderer lays it out,
and without a look the assistant never learns that a title wraps into three
lines, a slide is half empty or a chart squeezes its labels. ``look`` draws
the node's page in a headless browser (:mod:`dodaios.ui.web.artifact_share`)
and hands the pictures back to the model, so it can judge the result and
revise it before the person opens it.

A deck comes back as contact sheets: four slides per picture, two by two,
each slide numbered as in the player. Any other type comes back as its page,
cut into a few screen-high pieces. At most ``MAX_PICTURES`` pictures go back
per call (the MCP bridge passes no more); a longer deck is looked at in parts
with ``slides``.
"""

from __future__ import annotations

import base64
import io
import logging
from collections.abc import Sequence
from typing import Any, Final

from dodaios.nodes.model import Node

log = logging.getLogger(__name__)

#: Pictures per call; the MCP bridge forwards at most four to the model.
MAX_PICTURES: Final[int] = 4
#: Slides on one contact sheet, two by two.
SLIDES_PER_SHEET: Final[int] = 4
#: Slides one call can show.
MAX_SLIDES: Final[int] = MAX_PICTURES * SLIDES_PER_SHEET
#: One slide on a sheet, in pixels: two with their gaps make a 1600 px wide sheet.
_CELL_W: Final[int] = 776
_CELL_H: Final[int] = 436
_GAP: Final[int] = 16
_LABEL_H: Final[int] = 28
#: A page piece: the page's width (1280 CSS px at double density) by this height.
_PIECE_HEIGHT_CSS: Final[int] = 1100
_JPEG_QUALITY: Final[int] = 82


class LookError(RuntimeError):
    """The node could not be drawn (no browser, no page, a timeout)."""


def slide_numbers(count: int, wanted: Sequence[int] | None) -> tuple[int, ...]:
    """The slides (from 1) one look shows: the wanted ones that exist, else the first ones."""
    if count <= 0:
        return ()
    if wanted:
        picked: list[int] = []
        for value in wanted:
            if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= count:
                if value not in picked:
                    picked.append(value)
        if picked:
            return tuple(picked[:MAX_SLIDES])
    return tuple(range(1, min(count, MAX_SLIDES) + 1))


def _jpeg(image: Any) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def contact_sheets(shots: Sequence[bytes], numbers: Sequence[int]) -> list[str]:
    """Slide pictures laid out four to a sheet, each with its number; base64 JPEGs."""
    from PIL import Image, ImageDraw  # noqa: PLC0415 — only a look needs it

    sheets: list[str] = []
    pairs = list(zip(numbers, shots, strict=False))
    for start in range(0, len(pairs), SLIDES_PER_SHEET):
        group = pairs[start : start + SLIDES_PER_SHEET]
        columns = 2 if len(group) > 1 else 1
        rows = (len(group) + 1) // 2
        width = columns * _CELL_W + (columns + 1) * _GAP
        height = rows * (_CELL_H + _LABEL_H) + (rows + 1) * _GAP
        sheet = Image.new("RGB", (width, height), (128, 128, 128))
        pen = ImageDraw.Draw(sheet)
        for index, (number, data) in enumerate(group):
            column, row = index % 2, index // 2
            left = _GAP + column * (_CELL_W + _GAP)
            top = _GAP + row * (_CELL_H + _LABEL_H + _GAP)
            pen.text((left, top + 6), f"Slide {number}", fill=(255, 255, 255))
            with Image.open(io.BytesIO(data)) as shot:
                cell = shot.convert("RGB").resize((_CELL_W, _CELL_H), Image.Resampling.LANCZOS)
            sheet.paste(cell, (left, top + _LABEL_H))
        sheets.append(_jpeg(sheet))
    return sheets


def page_pieces(png: bytes) -> list[str]:
    """A whole-page picture cut into at most ``MAX_PICTURES`` screen-high pieces."""
    from PIL import Image  # noqa: PLC0415 — only a look needs it

    with Image.open(io.BytesIO(png)) as page:
        page.load()
        width, height = page.size
        # The page was drawn 1280 CSS px wide; keep the pieces in proportion.
        piece = max(1, int(_PIECE_HEIGHT_CSS * width / 1280))
        out: list[str] = []
        for top in range(0, height, piece):
            if len(out) >= MAX_PICTURES:
                break
            part = page.crop((0, top, width, min(height, top + piece)))
            if width > 1568:
                ratio = 1568 / width
                part = part.resize((1568, max(1, int(part.height * ratio))))
            out.append(_jpeg(part))
        return out


def deck_theme(node: Node, theme: str) -> str:
    """The theme a deck is drawn in: its own fixed one, else the one asked for."""
    own = str((node.spec or {}).get("theme") or "").lower() if isinstance(node.spec, dict) else ""
    if own in ("dark", "light"):
        return own
    return "dark" if theme == "dark" else "light"


def look(
    node: Node, html: bytes, *, slides: Sequence[int] | None = None, theme: str = ""
) -> tuple[list[str], str]:
    """Pictures (base64 JPEGs) of ``node``'s page and a line saying what they show.

    Blocking (starts a browser): call it in a worker thread.
    """
    from dodaios.ui.web import artifact_share  # noqa: PLC0415 — a browser, on demand

    try:
        if node.type == "slides":
            raw = (node.spec or {}).get("slides") if isinstance(node.spec, dict) else None
            count = len(raw) if isinstance(raw, list) else 0
            numbers = slide_numbers(count, slides)
            if not numbers:
                raise LookError("the deck has no slides")
            shots = artifact_share.draw_slides(html, deck_theme(node, theme), numbers)
            if not shots:
                raise LookError("the deck page drew no slide")
            shown = numbers[: len(shots)]
            pictures = contact_sheets(shots, shown)
            rest = count - len(shown)
            line = f"Slides {', '.join(str(n) for n in shown)} of {count}, four to a picture." + (
                f" {rest} more: look again with 'slides' to see them." if rest > 0 else ""
            )
            return pictures, line
        png = artifact_share.draw_page(html, "dark" if theme == "dark" else "light")
        pictures = page_pieces(png)
        return pictures, f"The page from the top, in {len(pictures)} piece(s)."
    except artifact_share.ShareExportError as exc:
        raise LookError(str(exc)) from exc


__all__ = [
    "MAX_PICTURES",
    "MAX_SLIDES",
    "LookError",
    "contact_sheets",
    "deck_theme",
    "look",
    "page_pieces",
    "slide_numbers",
]
