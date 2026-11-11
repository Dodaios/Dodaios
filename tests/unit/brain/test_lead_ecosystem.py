"""The ecosystem map: generated from code, byte-stable, and every section has a lead read path."""

from __future__ import annotations

import pytest

from dodaios.brain.lead_ecosystem import (
    AREAS,
    SECTION_READS,
    render_ecosystem_map,
    section_read_paths,
)
from dodaios.plugins.tool.navigate import KNOWN


@pytest.fixture(scope="module")
def lead_tool_names() -> frozenset[str]:
    from tests.eval.lead_routing import build_lead_catalog

    return frozenset(build_lead_catalog().names) | _declared_tool_names()


def _declared_tool_names() -> frozenset[str]:
    """Tool names declared in pyproject's ``jarvis.tool`` entry points.

    The hermetic catalog loads tools from the installed package metadata, which a
    long-lived checkout may not have refreshed yet; pyproject is the source of truth.
    """
    import importlib
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    names: set[str] = set()
    for target in declared["project"]["entry-points"]["jarvis.tool"].values():
        module, _, attr = target.partition(":")
        name = getattr(getattr(importlib.import_module(module), attr, None), "name", None)
        if isinstance(name, str):
            names.add(name)
    return frozenset(names)


@pytest.fixture(scope="module")
def get_paths() -> frozenset[str]:
    from dodaios.core.bus import EventBus
    from dodaios.core.config import JarvisConfig
    from dodaios.ui.web.server import WebServer

    cfg = JarvisConfig()
    cfg.ui.dev_mode = True
    paths = WebServer(cfg, bus=EventBus()).app.openapi()["paths"]
    return frozenset(path for path, ops in paths.items() if "get" in ops)


def test_every_sidebar_section_is_in_the_map_exactly_once() -> None:
    placed = [section for area in AREAS for section in area.sections]
    assert sorted(placed) == sorted(set(placed)), "a section sits in two areas"
    assert set(placed) == set(KNOWN), (
        f"missing from the map: {sorted(set(KNOWN) - set(placed))}; "
        f"not a sidebar section: {sorted(set(placed) - set(KNOWN))}"
    )
    text = render_ecosystem_map()
    for section in KNOWN:
        assert section in text, section


def test_every_sidebar_section_has_a_lead_read_path() -> None:
    reads = section_read_paths()
    assert set(reads) == set(KNOWN), "SECTION_READS must name every sidebar section"
    for section, paths in reads.items():
        assert paths, f"{section} has no lead read path"


def test_every_read_path_is_a_real_lead_tool_or_a_mounted_get_route(
    lead_tool_names: frozenset[str], get_paths: frozenset[str]
) -> None:
    named = {path for paths in SECTION_READS.values() for path in paths}
    named |= {path for area in AREAS for path in (*area.reads, *area.acts)}
    for path in sorted(named):
        if path.startswith("GET "):
            assert path.removeprefix("GET ") in get_paths, f"{path} is not a mounted GET route"
        else:
            assert path in lead_tool_names, f"{path} is not a lead tool"


def test_the_new_lead_tools_are_in_the_map(lead_tool_names: frozenset[str]) -> None:
    text = render_ecosystem_map()
    for tool in ("team_thread", "costs_summary", "artifacts"):
        assert tool in lead_tool_names
        assert tool in text


def test_the_map_is_generated_stable_and_bounded() -> None:
    first = render_ecosystem_map()
    render_ecosystem_map.cache_clear()
    assert render_ecosystem_map() == first, "the map must be byte-stable"
    assert first.startswith("ECOSYSTEM MAP")
    # Generated parts, not hand-typed copies: registry sections and the coding agents.
    from dodaios.commands.registry import get_registry

    for section in {command.ui_section for command in get_registry()}:
        assert f"{section} " in first.split("commands per section:")[1]
    assert "Claude Code" in first and "Codex" in first
    assert len(first) < 6_000, "the map rides in every lead turn"
