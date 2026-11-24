"""Product mandates the owner set once, kept as checks so no agent needs to be told.

Each test names the rule and says how to comply. Pure file reads: fast, no app.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dodaios.nodes import types as node_types

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "dodaios" / "ui" / "web" / "frontend" / "src"
_LOCALES = sorted((_SRC / "i18n" / "locales").glob("**/*.json"))


def _frontend_sources() -> list[Path]:
    return [p for p in _SRC.rglob("*") if p.suffix in {".ts", ".tsx"}]


def test_no_done_undo_toast_after_assistant_actions() -> None:
    """RULE (PR #1831): the app never pops up "Done: ... / Undo" after an assistant action.

    The undo ledger and its backend route may stay; the front end must not offer
    them as a toast. To comply: delete the toast code or i18n strings you added
    and show the result in the chat instead.
    """
    offenders = [
        str(p.relative_to(_REPO))
        for p in _frontend_sources()
        if re.search(r"offerUndo|undoToast|runUndo|/api/trust/undo", p.read_text("utf-8", "replace"))
    ]
    offenders += [str(p.relative_to(_REPO)) for p in _SRC.rglob("undoToast*")]
    offenders += [
        str(p.relative_to(_REPO))
        for p in _LOCALES
        if "Done: {what}" in p.read_text("utf-8", "replace")
    ]
    assert not offenders, (
        "Undo toasts were removed on purpose (owner mandate, PR #1831). "
        f"Remove them from: {offenders}"
    )


def test_visuals_node_type_stays_removed() -> None:
    """RULE (PR #1809): the node types are docs, slides, sheets, data, whiteboard, motion.

    To comply: do not add a `visuals` node type; pictures and pages shelve under Docs.
    """
    names = set(node_types.NODE_TYPES) | set(node_types.DISPLAY_NAMES)
    names |= set(getattr(node_types, "_ALIASES", {}).values())
    assert "visuals" not in names, "The Visuals node type was removed by design (PR #1809); never re-add it."
    kinds = _REPO / "dodaios" / "nodes" / "kinds"
    assert not any("visuals" in p.name.lower() for p in kinds.glob("*")), (
        "dodaios/nodes/kinds must not hold a visuals kind (PR #1809)."
    )


def _strings(node: object):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


@pytest.mark.parametrize("locale", _LOCALES, ids=lambda p: p.name)
def test_no_user_visible_old_product_name_in_locales(locale: Path) -> None:
    """RULE: the product is named Dodaios; "Jarvis" never shows in a user-visible string.

    To comply: write the product name as "Dodaios" (or the `{name}` placeholder
    for the assistant's own name). Keys may keep old spellings; values may not.
    """
    data = json.loads(locale.read_text("utf-8"))
    hits = [s[:80] for s in _strings(data) if re.search(r"jarvis", s, re.IGNORECASE)]
    assert not hits, f"{locale.name} shows the old name to users: {hits[:5]}"


def test_boot_splash_and_page_title_never_say_jarvis() -> None:
    """RULE: the boot splash and the page title never show "Jarvis" (trademark risk).

    Element ids, CSS selectors and storage keys may keep the old spelling; text a
    person can see may not.
    """
    splash = (_SRC / "components" / "BootSplash.tsx").read_text("utf-8")
    splash = splash.replace("jarvis-boot-splash", "")
    assert "jarvis" not in splash.lower(), "BootSplash.tsx shows the old product name; use Dodaios or no name."

    html = (_SRC.parent / "index.html").read_text("utf-8")
    html = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S | re.I)
    visible = re.findall(r">([^<]+)<", html)
    assert not [t for t in visible if "jarvis" in t.lower()], (
        "index.html shows the old product name (title or splash text); use Dodaios or no name."
    )
