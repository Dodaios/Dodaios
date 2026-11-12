"""Which notices only record background work and are kept out of every chat view."""

from __future__ import annotations

import pytest

from dodaios.agent_chat.events import is_background_notice


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "memory_learned", "status": "done", "text": "Prefers files over chat text."},
        {"kind": "watchdog", "status": "done", "text": "Something needs a look."},
        {"kind": "society_result", "source": "routine", "status": "failed", "text": "failed"},
        {"kind": "society_result", "source": "routine", "status": "skipped", "text": "skipped"},
        {"kind": "society_result", "source": "routine", "status": "waiting", "text": "waiting"},
    ],
)
def test_background_records(payload: dict[str, str]) -> None:
    assert is_background_notice(payload) is True


@pytest.mark.parametrize(
    "payload",
    [
        # A routine's finished result is an answer the person asked for.
        {"kind": "society_result", "source": "routine", "status": "done", "text": "The brief."},
        {"kind": "society_result", "source": "routine", "text": "The brief."},
        # A task the assistant handed out for the person: its failure belongs to the conversation.
        {"kind": "society_result", "status": "blocked", "text": "Scout needs a login."},
        {"kind": "reminder", "text": "Call the dentist."},
        {"kind": "memory_health", "text": "The usage limit is spent."},
        {},
    ],
)
def test_notices_the_chat_keeps(payload: dict[str, str]) -> None:
    assert is_background_notice(payload) is False
