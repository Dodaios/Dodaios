"""The composer's progress line on stdout names the assistant the user's way."""

from __future__ import annotations

from jarvis.agentic_ide.prompt_composer import STAGE_START, ComposeNotice, print_notice
from jarvis.brain.assistant_name import DEFAULT_ASSISTANT_NAME

_NOTICE = ComposeNotice(stage=STAGE_START, message="Writing the brief for T1.", terminal="T1")


def test_the_line_leads_with_the_name_the_user_gave_the_assistant(capsys) -> None:
    print_notice(_NOTICE, speaker="George")
    assert capsys.readouterr().out == "George: Writing the brief for T1.\n"


def test_without_a_name_the_line_uses_the_neutral_one(capsys) -> None:
    print_notice(_NOTICE)
    print_notice(_NOTICE, speaker="   ")
    line = f"{DEFAULT_ASSISTANT_NAME}: Writing the brief for T1.\n"
    assert capsys.readouterr().out == line * 2
