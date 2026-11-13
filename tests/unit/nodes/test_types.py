"""The node types, their names on the shelf, and what a person may call them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.nodes.types import DISPLAY_NAMES, NODE_TYPES, NodeError, node_type
from dodaios.plugins.tool.node import TYPE_LINES, NodeTool

_LOCALES = Path(__file__).resolve().parents[3] / "dodaios/ui/web/frontend/src/i18n/locales"


def test_every_type_has_a_name_on_the_shelf() -> None:
    assert tuple(DISPLAY_NAMES) == NODE_TYPES


@pytest.mark.parametrize("locale", sorted(path.name for path in _LOCALES.glob("*.json")))
def test_the_shelf_names_are_the_ones_the_app_shows(locale: str) -> None:
    # The type names stay as they are in every language, so the model hears
    # from the person the same word it was told.
    shown = json.loads((_LOCALES / locale).read_text(encoding="utf-8"))["nodes"]["type"]
    assert {name: shown[name] for name in NODE_TYPES} == DISPLAY_NAMES


@pytest.mark.parametrize(
    ("said", "meant"),
    [
        ("Analytics", "data"),
        ("analysis", "data"),
        ("dashboard", "data"),
        ("Visuals", "design"),
        ("visual", "design"),
        ("Clips", "motion"),
        ("clip", "motion"),
        ("  Sheets ", "sheets"),
        ("deck", "slides"),
    ],
)
def test_a_type_is_found_by_the_name_a_person_uses(said: str, meant: str) -> None:
    assert node_type(said) == meant


def test_an_unknown_name_lists_the_types() -> None:
    with pytest.raises(NodeError) as raised:
        node_type("spreadsheets galore")

    assert all(name in str(raised.value) for name in NODE_TYPES)


def test_the_tool_tells_the_model_the_three_names_that_differ() -> None:
    for name, shelf in DISPLAY_NAMES.items():
        if shelf.lower() == name:
            continue
        assert shelf in TYPE_LINES[name]
        assert shelf in NodeTool.description
