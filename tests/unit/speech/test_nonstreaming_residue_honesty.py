"""The announcement voice path must not announce a failure that never happened.

``scrub_for_voice`` ends with a residue guard: a filter fired AND fewer than
three alphanumeric characters survived → the whole text becomes the canned
error phrase ("Es trat ein Fehler auf." / "An error occurred."). That guard is
right for what it defends — a machine leak must never reach TTS — but it
conflates two turns that have nothing in common:

* a leak was cut out (tool JSON, stacktrace, raw repr, shell command): the
  error phrase is honest, something really did go wrong;
* only harmless prose was cut out (filler opener, honorific, self-reference,
  jargon, markdown): nothing failed, the model just said nothing of substance.

Measured 2026-08-18 before the fix: a turn whose whole content was "Tolle
Frage!" was spoken as "Es trat ein Fehler auf.". These tests pin the split for  # i18n-allow: quoted
the whole-text chokepoint the pipeline still owns: the bus announcement
handler.
"""
from __future__ import annotations

import pytest

from dodaios.brain.output_filter import FALLBACK_PHRASES
from dodaios.core.bus import EventBus
from dodaios.core.events import AnnouncementRequested
from tests.unit.speech.test_announcement_bridge import (
    FakePlayer,
    FakeTTS,
    _make_pipeline,
)

# A turn made of nothing but a filler opener. Every filter that touches it is a
# prose transform — no machine data is involved anywhere.
FILLER_DE = "Tolle Frage!"  # i18n-allow: German filler opener under test
FILLER_EN = "Great question."
# A real leak: the tool-call wrapper is removed and the residue guard then fires
# on what is left. The user IS owed the error phrase here.
TOOL_LEAK = (
    "<function_calls><invoke name='read_file'>"
    "<parameter name='path'>x</parameter></invoke></function_calls>"
)


def _spoken(tts: FakeTTS) -> list[str]:
    return [text for text, _lang in tts.calls]


async def _run_announcement(text: str, language: str) -> list[str]:
    bus = EventBus()
    tts = FakeTTS()
    _make_pipeline(tts, bus, FakePlayer())
    await bus.publish(AnnouncementRequested(text=text, language=language))
    return _spoken(tts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "language"),
    [(FILLER_DE, "de"), (FILLER_EN, "en")],
)
async def test_filler_only_announcement_is_silent_not_an_error(
    text: str, language: str
) -> None:
    """A filler-only announcement is silence, never the error phrase."""
    assert await _run_announcement(text, language) == []


@pytest.mark.asyncio
async def test_scrubbed_leak_still_speaks_the_fallback_on_an_announcement() -> None:
    assert await _run_announcement(TOOL_LEAK, "de") == [FALLBACK_PHRASES["de"]]


