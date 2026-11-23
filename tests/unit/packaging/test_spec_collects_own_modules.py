"""The installer builds ship every module of the app, also those loaded by name (#1879).

Import analysis follows ``import`` statements only. The node kinds behind
whiteboards, documents, decks and sheets are loaded with
``importlib.import_module(f"dodaios.nodes.kinds.{name}")``, so the installer
builds shipped without them and every whiteboard or document a chat made
failed with "No module named 'dodaios.nodes.kinds.whiteboard'".
"""

from __future__ import annotations

import re
from pathlib import Path

from dodaios.nodes import kinds
from dodaios.nodes.types import NODE_TYPES

SPEC = Path(__file__).resolve().parents[3] / "dodaios.spec"


def test_the_spec_collects_the_whole_package() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert re.search(r'^hiddenimports \+= collect_submodules\("dodaios"\)$', text, re.MULTILINE)


def test_the_node_kinds_are_still_loaded_by_name() -> None:
    """Why the line above is needed: no static import names the kind modules."""
    source = Path(kinds.__file__).read_text(encoding="utf-8")
    assert 'importlib.import_module(f"{__name__}.{name}")' in source
    for type_name in NODE_TYPES:
        assert kinds.kind_of(type_name) is not None
