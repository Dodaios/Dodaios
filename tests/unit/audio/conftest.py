"""Audio tests mock PortAudio. They need the sounddevice import to have succeeded.

A runner whose libportaudio the installed sounddevice cannot open leaves
``sd`` as None. Patching ``None.query_devices`` then fails every test. The
headless-import tests are the exception: they prove that None path on purpose.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _require_loaded_sounddevice(request: pytest.FixtureRequest) -> None:
    if request.path.name == "test_headless_import.py":
        return
    from dodaios.audio import player

    if player.sd is None:
        pytest.skip("sounddevice did not load (PortAudio missing or unloadable)")


@pytest.fixture(autouse=True)
def _no_native_calls_left_over(request: pytest.FixtureRequest) -> None:
    """What one test leaves with the audio system must not hold the next one back."""
    if request.path.name == "test_headless_import.py":
        yield
        return
    from dodaios.audio import capture, devices

    capture._forget_unanswered_calls()
    capture._STREAM_ENDINGS.clear()
    devices._forget_virtual_devices()
    yield
    capture._forget_unanswered_calls()
    capture._STREAM_ENDINGS.clear()
    devices._forget_virtual_devices()
