"""The brand-logo gate fails on unsourced, recoloured or public-copy marks."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import check_brand_logos as gate

_ICON = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M0 0h24v24H0z"/></svg>'
)
_HEADER = "| id | Source | Legal basis |\n| --- | --- | --- |\n"


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A miniature frontend: one ledgered folder and a public/ folder."""
    assets = tmp_path / "frontend" / "src" / "assets" / "agents"
    public = tmp_path / "frontend" / "public"
    assets.mkdir(parents=True)
    public.mkdir(parents=True)
    monkeypatch.setattr(gate, "_ROOT", tmp_path)
    monkeypatch.setattr(gate, "_FOLDERS", (assets,))
    monkeypatch.setattr(gate, "_PUBLIC", public)
    monkeypatch.setattr(
        gate, "_RETIRED_PUBLIC", (public / "provider-logos", public / "agent-logos")
    )
    return tmp_path


def _assets(tree: Path) -> Path:
    return tree / "frontend" / "src" / "assets" / "agents"


def test_a_ledgered_unmodified_mark_passes(tree: Path) -> None:
    (_assets(tree) / "kimi.svg").write_text(_ICON, encoding="utf-8")
    (_assets(tree) / "LOGOS.md").write_text(
        _HEADER + "| kimi | simple-icons `kimi.svg` | CC0-1.0 |\n", encoding="utf-8"
    )
    assert gate.main() == 0


def test_a_mark_without_a_row_fails(tree: Path) -> None:
    (_assets(tree) / "kimi.svg").write_text(_ICON, encoding="utf-8")
    assert gate.main() == 1


def test_a_row_that_records_a_redrawn_mark_fails(tree: Path) -> None:
    (_assets(tree) / "cursor.svg").write_text(_ICON, encoding="utf-8")
    (_assets(tree) / "LOGOS.md").write_text(
        _HEADER + "| cursor | Redrawn from the app icon | vendor |\n", encoding="utf-8"
    )
    assert gate.main() == 1


def test_a_mark_painted_in_the_app_ink_fails(tree: Path) -> None:
    (_assets(tree) / "grok.svg").write_text(
        _ICON.replace("<path ", '<path fill="#F4F4F5" '), encoding="utf-8"
    )
    (_assets(tree) / "LOGOS.md").write_text(
        _HEADER + "| grok | lobe-icons `grok.svg` | MIT |\n", encoding="utf-8"
    )
    assert gate.main() == 1


def test_a_retired_public_logo_folder_fails(tree: Path) -> None:
    retired = tree / "frontend" / "public" / "provider-logos"
    retired.mkdir()
    (retired / "claude.svg").write_text(_ICON, encoding="utf-8")
    assert gate.main() == 1


def test_a_public_logo_needs_a_row_but_first_party_files_do_not(tree: Path) -> None:
    public = tree / "frontend" / "public"
    (public / "dodaios.ico").write_bytes(b"\x00\x00\x01\x00")
    plugin_assets = public / "plugin-assets"
    plugin_assets.mkdir()
    (plugin_assets / "slack-logo.svg").write_text(_ICON, encoding="utf-8")
    assert gate.main() == 1

    (plugin_assets / "LOGOS.md").write_text(
        "| Asset | Source |\n| --- | --- |\n| `slack-logo.svg` | gilbarbara/logos |\n",
        encoding="utf-8",
    )
    assert gate.main() == 0


def test_the_repository_is_clean() -> None:
    assert gate.main() == 0
