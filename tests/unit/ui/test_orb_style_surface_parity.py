"""The voice orb wears the app's surface.

Reported 2026-08-06: on the desktop the procedural sphere spoke through a comic
bubble that read as a different program's window sitting on the same screen.
The sphere now speaks through no bubble at all and carries the same four
controls its in-app twin has (``components/agentic/VoiceBubble.tsx``).

These are pure-logic guards: no Tk root is created, because the overlay's own
pytest guard refuses to put a real window on a developer's desktop.
"""

from __future__ import annotations

import pytest

from ui.orb import overlay

# --- no bubble at all on the sphere -----------------------------------------


def test_the_sphere_speaks_through_no_bubble_at_all() -> None:
    """Maintainer, 2026-08-06: "that speech bubble up there can go".

    Everything it used to say now lives in how the orb moves — it swells on the
    voice and churns its colours while thinking. The bubble calls the bridge
    makes are accepted and do nothing.
    """
    orb = overlay.OrbOverlay(style="voice_orb")
    orb.show_comment("hello")
    orb.show_listening_transcript("hello")
    orb.hide_comment()
    assert orb.active_animations() == []


def test_the_sphere_has_its_own_window_size() -> None:
    orb = overlay.OrbOverlay(style="voice_orb")
    assert (orb._win_w, orb._win_h) == (overlay.VOICE_ORB_WIN_W, overlay.VOICE_ORB_WIN_H)


def test_the_mic_disc_starts_a_conversation_when_there_is_none() -> None:
    orb = overlay.OrbOverlay(style="voice_orb")
    calls: list[str] = []
    orb.set_on_talk(lambda: calls.append("talk"))
    orb.set_on_hangup(lambda: calls.append("hangup"))

    orb._on_control_action("mic")

    assert calls == ["talk"]


def test_the_mic_disc_hangs_up_a_running_conversation() -> None:
    orb = overlay.OrbOverlay(style="voice_orb")
    calls: list[str] = []
    orb.set_on_talk(lambda: calls.append("talk"))
    orb.set_on_hangup(lambda: calls.append("hangup"))
    orb._mode = "speak"

    orb._on_control_action("mic")

    assert calls == ["hangup"]
    # Local feedback immediately, rather than waiting for microphone teardown
    # plus the EventBus round-trip.
    assert orb._mode == "idle"


def test_the_x_ends_the_conversation_before_putting_the_orb_away() -> None:
    orb = overlay.OrbOverlay(style="voice_orb")
    calls: list[str] = []
    orb.set_on_hangup(lambda: calls.append("hangup"))
    orb._mode = "listen"

    orb._on_control_action("close")

    assert calls == ["hangup"]
    assert orb._mode == "idle"


def test_the_x_on_an_idle_orb_hangs_up_nothing() -> None:
    orb = overlay.OrbOverlay(style="voice_orb")
    calls: list[str] = []
    orb.set_on_hangup(lambda: calls.append("hangup"))

    orb._on_control_action("close")

    assert calls == []


def test_the_speaker_disc_delegates_when_a_host_owns_the_pipeline() -> None:
    """On macOS the orb runs in a companion process with no pipeline of its own."""
    orb = overlay.OrbOverlay(style="voice_orb")
    calls: list[str] = []
    orb.set_on_speaker_toggle(lambda: calls.append("speaker"))

    orb._on_control_action("speaker")
    assert calls == ["speaker"]
    assert orb._speaker_muted is True

    orb._on_control_action("speaker")
    assert calls == ["speaker", "speaker"]
    assert orb._speaker_muted is False


def test_the_speaker_disc_leaves_its_icon_alone_without_a_pipeline() -> None:
    """No pipeline, no mute — the disc must not claim one happened."""
    from dodaios.core import runtime_refs

    runtime_refs.set_speech_pipeline(None)
    orb = overlay.OrbOverlay(style="voice_orb")

    orb._on_control_action("speaker")

    assert orb._speaker_muted is False


@pytest.mark.parametrize("action", ["attach", "mic", "close", "speaker"])
def test_every_rendered_disc_has_a_handler(action: str) -> None:
    """The row draws four discs; a drawn disc that does nothing is a dead button."""
    assert action in overlay.orb_controls.ACTIONS
    orb = overlay.OrbOverlay(style="voice_orb")
    # No Tk root and no callbacks wired: every branch must survive that rather
    # than raising into the Tk event loop.
    orb._on_control_action(action)
