"""Reading what a person typed into a number field."""

from __future__ import annotations

import pytest

from dodaios.nodes.edit import read_number
from dodaios.nodes.types import NodeError


@pytest.mark.parametrize(
    ("typed", "meant"),
    [
        ("40,62", 40.62),
        ("40.62", 40.62),
        ("1.234,5", 1234.5),
        ("1,234.5", 1234.5),
        ("1.200", 1200),
        ("1,200", 1200),
        ("1.200.000", 1200000),
        ("0,500", 0.5),
        ("1 200", 1200),
        ("1 200,50", 1200.5),
        ("-3,5", -3.5),
        ("+7", 7),
        ("12 €", 12),
        ("€ 12,90", 12.9),
        ("19 %", 19),
        ("1'000", 1000),
        ("  ", None),
        ("", None),
    ],
)
def test_a_number_is_read_the_way_people_write_it(typed: str, meant: float | None) -> None:
    assert read_number(typed) == meant


@pytest.mark.parametrize("typed", ["twelve", "1.2.3,4,5", "1,2,3.4.5", "--3", "12a", "1.234,5,6"])
def test_what_is_not_a_number_is_refused(typed: str) -> None:
    with pytest.raises(NodeError, match="is not a number"):
        read_number(typed)
