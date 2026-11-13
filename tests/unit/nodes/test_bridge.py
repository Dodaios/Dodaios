"""The comment bridge: both sides use the same message names."""

from __future__ import annotations

import re
from pathlib import Path

from dodaios.nodes import bridge

_APP_SIDE = (
    Path(__file__).resolve().parents[3]
    / "dodaios/ui/web/frontend/src/components/nodes/nodeBridge.ts"
)


def _app_constant(name: str) -> str:
    found = re.search(rf'export const {name} = "([^"]+)";', _APP_SIDE.read_text(encoding="utf-8"))
    assert found, name
    return found.group(1)


def test_the_app_and_the_page_use_the_same_message_names() -> None:
    assert _app_constant("NODE_READY_MESSAGE") == bridge.READY_MESSAGE
    assert _app_constant("NODE_MODE_MESSAGE") == bridge.MODE_MESSAGE
    assert _app_constant("NODE_COMMENT_MESSAGE") == bridge.COMMENT_MESSAGE
    assert _app_constant("NODE_COMMENT_STATE_MESSAGE") == bridge.COMMENT_STATE_MESSAGE
    assert _app_constant("NODE_COMMENT_REMOVE_MESSAGE") == bridge.COMMENT_REMOVE_MESSAGE


def test_the_page_script_speaks_those_names() -> None:
    for name in (
        bridge.READY_MESSAGE,
        bridge.MODE_MESSAGE,
        bridge.COMMENT_MESSAGE,
        bridge.COMMENT_STATE_MESSAGE,
        bridge.COMMENT_REMOVE_MESSAGE,
    ):
        assert f'"{name}"' in bridge.BRIDGE_JS


def test_both_sides_bound_a_comment_alike() -> None:
    app = _APP_SIDE.read_text(encoding="utf-8")
    assert f"const MAX_COMMENT_CHARS = {bridge.MAX_COMMENT_CHARS};" in app
    assert f"const MAX_QUOTE_CHARS = {bridge.MAX_QUOTE_CHARS};" in app
    assert f"const MAX_WHERE_CHARS = {bridge.MAX_WHERE_CHARS};" in app
    assert f"slice(0,{bridge.MAX_COMMENT_CHARS})" in bridge.BRIDGE_JS
