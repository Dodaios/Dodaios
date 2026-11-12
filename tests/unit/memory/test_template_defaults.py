"""A profile states only what the person said, never the maintainer's own values.

The first USER.md template gave everybody ``primary_language: de`` and
``timezone: Europe/Berlin``. A new profile leaves both empty, and an older one
loses them unless the person touched the field or something of their own
supports the value.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dodaios.memory import template_defaults
from dodaios.memory.frontmatter import parse_frontmatter
from dodaios.memory.template_defaults import assumed_fields, clear_assumed
from dodaios.memory.templates import render_user_md
from dodaios.memory.user_profile import UserProfile
from dodaios.memory.vault.legacy_import import import_legacy, retire_template_defaults
from dodaios.memory.vault.store import MemoryVault
from dodaios.memory.workspace import USER_MD, Workspace

REPO = Path(__file__).resolve().parents[3]

#: The template as it shipped until November 2026, comments included.
OLD_TEMPLATE = render_user_md().replace(
    "primary_language: null", "primary_language: de", 1
).replace("timezone: null", "timezone: Europe/Berlin", 1)

ZONE_SENTENCE = "The user's time zone is Europe/Berlin."
LANGUAGE_SENTENCE = "The user's main language: de."


@pytest.fixture
def elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """A computer whose clock does not keep Berlin time."""
    monkeypatch.setattr(template_defaults, "computer_follows", lambda _zone: False)


@pytest.fixture
def in_berlin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(template_defaults, "computer_follows", lambda _zone: True)


def _identity(path: Path) -> dict:
    meta, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    return meta["identity"]


def _with_observation(text: str, line: str) -> str:
    marker = "<!-- curator:observations:start -->"
    assert marker in text
    return text.replace(marker, f"{marker}\n{line}", 1)


def test_old_template_fixture_really_carries_the_old_values() -> None:
    identity = parse_frontmatter(OLD_TEMPLATE)[0]["identity"]
    assert identity["primary_language"] == "de"
    assert identity["timezone"] == "Europe/Berlin"


def test_a_new_profile_assumes_no_language_and_no_time_zone(tmp_path: Path) -> None:
    ws = Workspace.ensure(tmp_path / "ws")
    identity = _identity(ws.user_path)
    assert identity["primary_language"] is None
    assert identity["timezone"] is None

    block = UserProfile.load(ws.user_path).render_for_prompt()
    assert "Timezone" not in block
    assert "Berlin" not in block


def test_the_prompt_names_the_first_language_when_no_main_one_is_set(tmp_path: Path) -> None:
    ws = Workspace.ensure(tmp_path / "ws")
    profile = UserProfile.load(ws.user_path)
    profile.append_list("identity", "languages", "pt")
    assert "(Primary: pt)" in profile.render_for_prompt()


def test_an_older_profile_loses_both_values_on_a_computer_elsewhere(
    tmp_path: Path, elsewhere: None
) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / USER_MD).write_text(OLD_TEMPLATE, encoding="utf-8")

    Workspace.ensure(root)

    identity = _identity(root / USER_MD)
    assert identity["primary_language"] is None
    assert identity["timezone"] is None
    # Only the two lines changed: every comment and every other line is intact.
    before, after = OLD_TEMPLATE.splitlines(), (root / USER_MD).read_text("utf-8").splitlines()
    changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
    assert [re.split(r":\s*", b.strip())[0] for _a, b in changed] == [
        "primary_language",
        "timezone",
    ]


def test_berlin_stays_where_the_computer_keeps_berlin_time(tmp_path: Path, in_berlin: None) -> None:
    path = tmp_path / USER_MD
    path.write_text(OLD_TEMPLATE, encoding="utf-8")
    assert clear_assumed(path) == ("primary_language",)
    assert _identity(path)["timezone"] == "Europe/Berlin"


def test_nothing_is_taken_when_the_computer_cannot_tell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(template_defaults, "computer_follows", lambda _zone: None)
    meta, body = parse_frontmatter(OLD_TEMPLATE)
    assert "timezone" not in assumed_fields(meta, body)


def test_german_stays_when_the_person_listed_it(tmp_path: Path, elsewhere: None) -> None:
    path = tmp_path / USER_MD
    path.write_text(OLD_TEMPLATE.replace("languages: []", "languages: [de, en]", 1), "utf-8")
    assert clear_assumed(path) == ("timezone",)
    assert _identity(path)["primary_language"] == "de"


def test_a_field_the_person_touched_is_theirs(tmp_path: Path, elsewhere: None) -> None:
    text = _with_observation(
        OLD_TEMPLATE, '- [2026-08-29] identity.timezone: Europe/Berlin — "I am in Berlin"'
    )
    text = _with_observation(
        text, '- [2026-08-30] identity.primary_language: de — "manual edit via profile UI"'
    )
    path = tmp_path / USER_MD
    path.write_text(text, encoding="utf-8")
    assert clear_assumed(path) == ()
    assert path.read_text(encoding="utf-8") == text


def test_other_values_are_never_touched(tmp_path: Path, elsewhere: None) -> None:
    text = OLD_TEMPLATE.replace("primary_language: de", "primary_language: en", 1).replace(
        "timezone: Europe/Berlin", "timezone: America/New_York", 1
    )
    path = tmp_path / USER_MD
    path.write_text(text, encoding="utf-8")
    assert clear_assumed(path) == ()
    assert path.read_text(encoding="utf-8") == text


def test_a_profile_the_app_saved_before_is_repaired_too(tmp_path: Path, elsewhere: None) -> None:
    """``UserProfile.save`` rewrites the YAML without the template's comments."""
    path = tmp_path / USER_MD
    path.write_text(OLD_TEMPLATE, encoding="utf-8")
    profile = UserProfile.load(path)
    profile.set("identity", "name", "Mara")
    profile.save()

    assert set(clear_assumed(path)) == {"primary_language", "timezone"}
    identity = _identity(path)
    assert identity["name"] == "Mara"
    assert identity["timezone"] is None and identity["primary_language"] is None
    assert clear_assumed(path) == ()  # a second run finds nothing


def test_computer_follows_reads_this_computers_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()
    assert template_defaults.computer_follows("Not/AZone") is None
    # No computer keeps both of these: they are never the same offset.
    assert not (
        template_defaults.computer_follows("Pacific/Kiritimati")
        and template_defaults.computer_follows("Pacific/Niue")
    )


# -- memory vault -------------------------------------------------------


def _data_dir(tmp_path: Path, profile: str) -> Path:
    data = tmp_path / "data"
    (data / "workspace").mkdir(parents=True)
    (data / "workspace" / USER_MD).write_text(profile, encoding="utf-8")
    return data


def test_the_import_leaves_assumed_values_out(tmp_path: Path, elsewhere: None) -> None:
    data = _data_dir(tmp_path, OLD_TEMPLATE.replace("name: null", "name: Mara", 1))
    with MemoryVault(tmp_path / "vault.db") as vault:
        import_legacy(vault, wiki_root=None, data_dir=data)
        texts = {m.text for m in vault.list()}
    assert "The user's name is Mara." in texts
    assert ZONE_SENTENCE not in texts
    assert LANGUAGE_SENTENCE not in texts


def _vault_with_old_import(vault: MemoryVault) -> None:
    for text in (ZONE_SENTENCE, LANGUAGE_SENTENCE, "The user's name is Mara."):
        vault.remember(
            text,
            "profile",
            origin="imported",
            source={"via": "legacy-import", "from": "user-profile", "file": "workspace/USER.md"},
        )


def test_an_older_vault_closes_what_the_template_said(tmp_path: Path, elsewhere: None) -> None:
    data = _data_dir(tmp_path, OLD_TEMPLATE)
    with MemoryVault(tmp_path / "vault.db") as vault:
        _vault_with_old_import(vault)
        assert retire_template_defaults(vault, data_dir=data) == 2
        assert {m.text for m in vault.list()} == {"The user's name is Mara."}
        # Once per vault: a value the person states later is not closed again.
        vault.remember(ZONE_SENTENCE, "profile", origin="inferred")
        assert retire_template_defaults(vault, data_dir=data) == 0
        assert ZONE_SENTENCE in {m.text for m in vault.list()}
        assert json.loads(vault.get_meta("template_defaults_retired"))["closed"] == 2


def test_an_older_vault_keeps_what_is_the_persons_own(tmp_path: Path, in_berlin: None) -> None:
    profile = OLD_TEMPLATE.replace("languages: []", "languages: [de]", 1)
    data = _data_dir(tmp_path, profile)
    with MemoryVault(tmp_path / "vault.db") as vault:
        _vault_with_old_import(vault)
        assert retire_template_defaults(vault, data_dir=data) == 0
        assert {ZONE_SENTENCE, LANGUAGE_SENTENCE} <= {m.text for m in vault.list()}


def test_only_the_imported_sentences_are_closed(tmp_path: Path, elsewhere: None) -> None:
    data = _data_dir(tmp_path, OLD_TEMPLATE)
    with MemoryVault(tmp_path / "vault.db") as vault:
        vault.remember(ZONE_SENTENCE, "profile", origin="user")
        assert retire_template_defaults(vault, data_dir=data) == 0
        assert ZONE_SENTENCE in {m.text for m in vault.list()}


# -- spoken lines -------------------------------------------------------


def test_no_spoken_line_addresses_the_maintainer() -> None:
    """Lines the app says on its own must fit whoever installed it."""
    for path in sorted((REPO / "dodaios" / "i18n" / "locales").glob("*.json")):
        assert "Ruben" not in path.read_text(encoding="utf-8"), path.name

    from dodaios.speech.pipeline import _smalltalk_fallback_for_non_substantive

    for prompt, lang in (("wie geht es dir", "de"), ("how are you", "en")):
        answer = _smalltalk_fallback_for_non_substantive(prompt, lang)
        assert answer and "Ruben" not in answer
