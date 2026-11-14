"""``look``: which slides one look shows, and how its pictures are laid out."""

from __future__ import annotations

import base64
import io

from PIL import Image

from dodaios.nodes import look
from dodaios.nodes.model import Node


def _png(color: tuple[int, int, int], size: tuple[int, int] = (1280, 720)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _image(data: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data)))


def test_a_look_shows_the_wanted_slides_that_exist_else_the_first_ones() -> None:
    assert look.slide_numbers(0, None) == ()
    assert look.slide_numbers(3, None) == (1, 2, 3)
    assert look.slide_numbers(40, None) == tuple(range(1, look.MAX_SLIDES + 1))
    assert look.slide_numbers(11, [9, 2, 9, 30, 0, True]) == (9, 2)
    assert look.slide_numbers(11, [30]) == tuple(range(1, 12))


def test_slides_go_four_to_a_sheet_and_the_pictures_stay_within_budget() -> None:
    shots = [_png((10 * i, 40, 90)) for i in range(11)]
    sheets = look.contact_sheets(shots, list(range(1, 12)))
    assert len(sheets) == 3
    first, last = _image(sheets[0]), _image(sheets[2])
    assert first.format == "JPEG" and first.width <= 1600 and first.height < first.width
    # The last sheet holds three slides: still two columns, two rows.
    assert last.size == first.size
    # Under the MCP bridge's 500 kB per picture, so nothing is squeezed again.
    assert all(len(s) * 3 // 4 < 500_000 for s in sheets)


def test_a_long_page_is_cut_into_at_most_four_pieces() -> None:
    pieces = look.page_pieces(_png((250, 250, 250), size=(2560, 20000)))
    assert len(pieces) == look.MAX_PICTURES
    assert _image(pieces[0]).width == 1568


def test_a_deck_with_its_own_theme_is_drawn_in_it() -> None:
    def deck(theme: str) -> Node:
        return Node(
            id="abc", type="slides", title="T", spec={"theme": theme, "slides": []},
            slug="s", page_path="p.html", created_at=0.0, updated_at=0.0,
        )

    assert look.deck_theme(deck("dark"), "light") == "dark"
    assert look.deck_theme(deck("auto"), "dark") == "dark"
    assert look.deck_theme(deck("auto"), "") == "light"
