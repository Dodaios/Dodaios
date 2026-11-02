"""One-time import of the old memory stores into the vault (ADR-0044, chunk 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.memory.vault.legacy_import import clean, import_legacy, import_once
from dodaios.memory.vault.store import MemoryVault

USER_PAGE = """---
type: entity
entity_kind: person
slug: ruben
aliases: [Ruben]
---

# Ruben

## Summary
Ruben is the primary user.

## Facts
- Proficient in English.
- Based in Germany.
- Owner of [[projects/math-exam-prep|Math Exam Prep]] *(inferred)*
- Experienced a heartbreak on 2026-06-28.

## Relationships
- Owner of [[projects/x|X]]
"""

TOOL_PAGE = """---
type: entity
entity_kind: tool
slug: bridgemind
---

# BridgeMind

## Facts
- It is a desktop application.
- BridgeMind has a Discord server.
"""

PROJECT_ACTIVE = """---
type: project
slug: taiwan-travel
status: active
last_activity: 2099-01-01
---

## Goal
Plan a trip to Taiwan in spring.
"""

PROJECT_DONE = PROJECT_ACTIVE.replace("active", "done").replace("Taiwan", "Peru")

PROFILE = """---
identity:
  name: Ruben
  preferred_address: Ruben
  primary_language: de
  timezone: Europe/Berlin
---

# About the user
"""


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path]:
    wiki = tmp_path / "wiki"
    (wiki / "entities").mkdir(parents=True)
    (wiki / "projects").mkdir()
    (wiki / "entities" / "ruben.md").write_text(USER_PAGE, encoding="utf-8")
    (wiki / "entities" / "bridgemind.md").write_text(TOOL_PAGE, encoding="utf-8")
    (wiki / "projects" / "taiwan-travel.md").write_text(PROJECT_ACTIVE, encoding="utf-8")
    (wiki / "projects" / "peru.md").write_text(PROJECT_DONE, encoding="utf-8")
    data = tmp_path / "data"
    (data / "workspace").mkdir(parents=True)
    (data / "workspace" / "USER.md").write_text(PROFILE, encoding="utf-8")
    (data / "core_memory.json").write_text(
        json.dumps(
            {
                "user_facts": {"general": ["Drinks coffee black."]},
                "preferences": {"voice": "Algieba"},
                "current_projects": {},
            }
        ),
        encoding="utf-8",
    )
    return wiki, data


def test_clean_strips_wiki_markup():
    assert clean("Owner of [[projects/a-b|A B]] *(inferred)*") == "Owner of A B"
    assert clean("Uses [[entities/obs-studio]].") == "Uses obs studio."


def test_imports_every_source_with_kinds_and_provenance(tmp_path, sources):
    wiki, data = sources
    with MemoryVault(tmp_path / "vault.db") as vault:
        report = import_legacy(vault, wiki_root=wiki, data_dir=data)
        texts = {m.text: m for m in vault.list()}

    assert "Proficient in English." in texts
    assert texts["Proficient in English."].kind == "profile"
    assert texts["Owner of Math Exam Prep"].kind == "profile"
    assert texts["BridgeMind: It is a desktop application."].entities == ("BridgeMind",)
    assert "BridgeMind has a Discord server." in texts
    assert texts["Taiwan Travel: Plan a trip to Taiwan in spring."].kind == "project"
    assert not any("Peru" in t for t in texts)
    assert texts["The user's name is Ruben."].kind == "profile"
    assert texts["Drinks coffee black."].origin == "imported"
    assert texts["Experienced a heartbreak on 2026-06-28."].sensitivity == "sensitive"
    assert not any("Algieba" in t for t in texts)
    assert texts["Proficient in English."].source["file"] == "entities/ruben.md"
    assert report.by_source["wiki"] >= 5


def test_dormant_projects_arrive_closed(tmp_path, sources):
    wiki, data = sources
    old = PROJECT_ACTIVE.replace("2099-01-01", "2020-05-01").replace("Taiwan", "Japan")
    (wiki / "projects" / "japan.md").write_text(old, encoding="utf-8")
    with MemoryVault(tmp_path / "vault.db") as vault:
        import_legacy(vault, wiki_root=wiki, data_dir=data)
        assert not any("Japan" in m.text for m in vault.list())
        closed = [m for m in vault.list(include_closed=True) if "Japan" in m.text]
        assert closed[0].valid_to == "2020-05-01T00:00:00+00:00"


def test_import_runs_once_and_never_duplicates(tmp_path, sources):
    wiki, data = sources
    with MemoryVault(tmp_path / "vault.db") as vault:
        assert import_once(vault, wiki_root=wiki, data_dir=data)
        count = vault.stats()["current"]
        assert not import_once(vault, wiki_root=wiki, data_dir=data)
        again = import_legacy(vault, wiki_root=wiki, data_dir=data)
        assert again.added == 0 and again.existing == count
        assert vault.stats()["current"] == count


def test_missing_sources_are_fine(tmp_path):
    with MemoryVault(tmp_path / "vault.db") as vault:
        report = import_legacy(vault, wiki_root=tmp_path / "nope", data_dir=tmp_path / "none")
        assert report.added == 0
        assert vault.get_meta("legacy_import") is not None
