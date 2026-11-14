"""A solo hold key starts the dictation at the key-down (2026-11-14).

With ``hotkey_dictate = "cmd"`` the hold is confirmed only after Command was
held alone for ``SOLO_HOLD_S`` (``trigger/backends/solo_hold.py``), because
Command is also the first half of every shortcut. Starting nothing until then
made the Dodaios Bar rise a noticeable moment after the key went down. Now the
pipeline starts the recording on ``dictate_early``, keeps it on the
confirmation (``dictate_press``) and takes it back without a trace on
``dictate_abandon`` (``cmd+c``, or a tap). Anything a shortcut must not set
off still waits for the confirmation.
"""

from __future__ import annotations

from typing import Any

import pytest

from dodaios.speech.pipeline import SpeechPipeline
from dodaios.trigger.hotkey import SELF_INPUT_SUPPRESSED_EVENTS

_STT = object()


class _Mic:
    def __init__(self, state: str) -> None:
        self.state = state

    def check(self, permission: str) -> str:
        assert permission == "microphone"
        return self.state


def _pipeline(
    *,
    mic: str = "granted",
    voice_session: bool = False,
    live_call: bool = False,
    stt: Any = _STT,
) -> tuple[SpeechPipeline, dict[str, list]]:
    pipe = SpeechPipeline.__new__(SpeechPipeline)
    calls: dict[str, list] = {"commit": [], "start": [], "stop": [], "discard": []}
    running = {"on": False}
    pipe._utterance_stt = stt
    pipe._dictate_key_down = False
    pipe._dictate_key_seen_at = 0.0
    pipe._dictate_early_pending = False
    pipe._dictation_leave_no_trace = False
    pipe._permission_gate = _Mic(mic)
    pipe._user_activation_gate = None
    pipe._live_call_owns_microphone = lambda: live_call  # type: ignore[method-assign]
    pipe._voice_session_holds_microphone = lambda: voice_session  # type: ignore[method-assign]
    pipe._configured_dictation_target = lambda: "auto"  # type: ignore[method-assign]
    pipe.dictation_active = lambda: running["on"]  # type: ignore[method-assign]

    def _commit(loop: Any, *, target: str, source: str = "api", beside_call: bool = False) -> bool:
        calls["commit"].append((target, source, beside_call))
        running["on"] = True
        pipe._dictation_leave_no_trace = False
        return True

    def _start(*, target: str = "chat", source: str = "api") -> bool:
        calls["start"].append((target, source))
        running["on"] = True
        return True

    def _stop() -> None:
        calls["stop"].append(True)
        running["on"] = False

    def _request_stop(*, discard: bool = False) -> bool:
        calls["discard"].append(discard)
        pipe._dictate_key_down = False
        running["on"] = False
        return True

    pipe._commit_dictation = _commit  # type: ignore[method-assign]
    pipe.start_dictation = _start  # type: ignore[method-assign]
    pipe.stop_dictation = _stop  # type: ignore[method-assign]
    pipe.request_dictation_stop = _request_stop  # type: ignore[method-assign]
    return pipe, calls


async def test_the_recording_starts_at_the_key_down_and_the_hold_keeps_it() -> None:
    pipe, calls = _pipeline()
    pipe._dispatch_hotkey_event("dictate_early")
    assert calls["commit"] == [("auto", "hold_key", False)]
    pipe._dispatch_hotkey_event("dictate_press")  # held alone: confirmed
    assert calls["commit"] == [("auto", "hold_key", False)]
    assert calls["start"] == []  # no second dictation on the same hold
    pipe._dispatch_hotkey_event("dictate_release")
    assert calls["stop"] == [True]  # submitted like any hold
    assert calls["discard"] == []


async def test_a_shortcut_takes_the_early_recording_back_without_a_trace() -> None:
    pipe, calls = _pipeline()
    pipe._dispatch_hotkey_event("dictate_early")
    pipe._dispatch_hotkey_event("dictate_abandon")  # the c of cmd+c
    assert calls["discard"] == [True]
    assert pipe._dictation_leave_no_trace is True
    assert pipe._dictate_key_down is False
    assert calls["stop"] == []


async def test_a_take_back_without_an_early_start_does_nothing() -> None:
    pipe, calls = _pipeline()
    pipe._dispatch_hotkey_event("dictate_abandon")
    assert calls["discard"] == []
    assert pipe._dictation_leave_no_trace is False


@pytest.mark.parametrize(
    "setup",
    [
        {"voice_session": True},  # the handover would hang the conversation up
        {"live_call": True},  # the call's input would be held
        {"mic": "not_determined"},  # the press may raise the macOS dialog
        {"mic": "denied"},  # the refusal paints a cross
        {"stt": None},  # the refusal paints a cross
    ],
)
async def test_anything_but_the_plain_start_waits_for_the_confirmation(
    setup: dict[str, Any],
) -> None:
    pipe, calls = _pipeline(**setup)
    pipe._dispatch_hotkey_event("dictate_early")
    assert calls["commit"] == []
    pipe._dispatch_hotkey_event("dictate_abandon")  # cmd+c: nothing happened
    assert calls["discard"] == [] and calls["start"] == []
    pipe._dispatch_hotkey_event("dictate_press")  # held alone: the ordinary press
    assert calls["start"] == [("auto", "hold_key")]


async def test_no_early_start_over_a_running_dictation() -> None:
    """The confirmed press is that dictation's stop, as it always was."""
    pipe, calls = _pipeline()
    pipe.dictation_active = lambda: True  # type: ignore[method-assign]
    pipe._dispatch_hotkey_event("dictate_early")
    assert calls["commit"] == []
    pipe._dispatch_hotkey_event("dictate_press")
    assert calls["stop"] == [True]


def test_an_early_start_is_never_set_off_by_dodaios_own_paste() -> None:
    """The app's own Cmd+V must not open the microphone either."""
    assert "dictate_early" in SELF_INPUT_SUPPRESSED_EVENTS


async def test_a_taken_back_recording_writes_no_history_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dodaios.dictation.history as history_mod

    written: list[dict] = []

    class _History:
        def add(self, **fields: Any) -> None:
            written.append(fields)
            return None

    monkeypatch.setattr(history_mod, "DictationHistory", _History)
    pipe = SpeechPipeline.__new__(SpeechPipeline)
    pipe._dictation_cfg = None
    fields = dict(
        raw_text="",
        cleaned="",
        language="",
        duration_s=0.1,
        outcome_name="cancelled",
        method="",
        removed_words=0,
        cleanup_reason="",
        stt_error=None,
        audio=None,
    )
    pipe._dictation_leave_no_trace = True
    await pipe._record_dictation(**fields)
    assert written == []
    # The bar's X on a real dictation still leaves its row for a Restore.
    pipe._dictation_leave_no_trace = False
    await pipe._record_dictation(**fields)
    assert len(written) == 1


def test_the_event_loop_is_needed_for_an_early_start() -> None:
    """Off the loop the early start stands aside; the confirmation says why."""
    pipe, calls = _pipeline()
    pipe._dispatch_hotkey_event("dictate_early")
    assert calls["commit"] == []
    assert pipe._dictate_early_pending is False
