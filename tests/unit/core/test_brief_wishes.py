"""The person's standing wishes for agent briefs reach every brief writer.

Maintainer, 2026-11-17: Dodaios kept writing git brakes into its agent briefs
("do not merge", "needs-human label", "own worktree"). The default is now the
finished job, and a person who wants it otherwise says so in the chat; the
wishes are stored once (``dodaios.core.brief_wishes``) and read fresh by the
lead's message line, its system prompt, the voice composer and the live voice
backends.
"""

from __future__ import annotations

import pytest

import dodaios.core.config as core_config
from dodaios.agent_chat import dodaios_harness
from dodaios.core import brief_wishes
from dodaios.core.agent_brief import AGENT_BRIEF_RULE, REAL_LIMITS, SHIP_DEFAULT

#: Wishes as a German-speaking person types them (the person's own words).
APPROVE = "Ich will jeden PR selbst freigeben"  # i18n-allow: user input sample
TESTS = "Immer mit Tests"  # i18n-allow: user input sample


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(core_config, "DATA_DIR", tmp_path)
    return tmp_path


def test_without_wishes_nothing_is_stored_or_added() -> None:
    assert brief_wishes.read_wishes() == ""
    assert brief_wishes.wishes_line() == ""
    assert brief_wishes.prompt_block() == ""
    assert dodaios_harness.brief_line() == dodaios_harness.BRIEF_LINE


def test_saved_wishes_are_one_per_line_and_read_back(tmp_path) -> None:
    stored = brief_wishes.save_wishes(f"  {APPROVE} \r\n\r\n- {TESTS}\n")
    assert stored == f"{APPROVE}\n- {TESTS}"
    assert brief_wishes.read_wishes() == stored
    raw = (tmp_path / brief_wishes.WISHES_FILENAME).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "no BOM"


def test_an_empty_list_goes_back_to_the_default(tmp_path) -> None:
    brief_wishes.save_wishes("Write the prompts in English")
    assert brief_wishes.save_wishes("   \n ") == ""
    assert not (tmp_path / brief_wishes.WISHES_FILENAME).exists()
    assert brief_wishes.reset_wishes() is False


def test_a_list_past_the_limit_is_refused_and_the_old_one_kept() -> None:
    brief_wishes.save_wishes("Always with tests")
    with pytest.raises(ValueError, match="characters"):
        brief_wishes.save_wishes("x" * (brief_wishes.MAX_WISHES_CHARS + 1))
    assert brief_wishes.read_wishes() == "Always with tests"


def test_the_lead_message_line_carries_the_wishes_after_the_default() -> None:
    brief_wishes.save_wishes(f"{APPROVE}\n{TESTS}")
    line = dodaios_harness.brief_line()
    assert line.startswith(dodaios_harness.BRIEF_LINE)
    tail = line[len(dodaios_harness.BRIEF_LINE) :]
    assert "they win over the default rules" in tail
    assert f"- {APPROVE}\n- {TESTS}" in tail


def test_the_system_prompt_block_names_the_wishes_and_keeps_the_real_limits() -> None:
    brief_wishes.save_wishes("Write the prompts in English")
    block = brief_wishes.prompt_block()
    assert block.startswith("AGENT BRIEF WISHES")
    assert "- Write the prompts in English" in block
    assert "never lift the real limits" in block
    assert "agent-briefs-set" in block


def test_an_unreadable_file_falls_back_to_the_default(tmp_path) -> None:
    (tmp_path / brief_wishes.WISHES_FILENAME).write_bytes(b"\xff\xfe\x00broken")
    assert brief_wishes.read_wishes() == ""
    assert dodaios_harness.brief_line() == dodaios_harness.BRIEF_LINE


def test_the_default_lets_the_agent_ship_and_adds_no_git_brakes() -> None:
    for text in (SHIP_DEFAULT, dodaios_harness.BRIEF_LINE):
        low = text.lower()
        assert "pushes and merges" in low
        assert "ci green" in low
        assert "no git limits" in low or "write no git limits" in low
    assert SHIP_DEFAULT in AGENT_BRIEF_RULE
    assert "agent-briefs-set" in dodaios_harness.BRIEF_LINE


def test_the_real_limits_stay_on_every_brief_surface() -> None:
    for text in (REAL_LIMITS, dodaios_harness.BRIEF_LINE):
        low = text.lower()
        assert "in their name" in low
        assert "no payments" in low
        assert "untrusted code" in low and "real credentials" in low
    assert REAL_LIMITS in AGENT_BRIEF_RULE
