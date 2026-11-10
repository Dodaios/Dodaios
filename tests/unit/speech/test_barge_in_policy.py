"""One barge-in policy for both voice paths (``[voice] barge_in``)."""

from __future__ import annotations

from types import SimpleNamespace

from dodaios.speech import barge_in


def test_default_is_the_proven_conservative_policy() -> None:
    profile = barge_in.profile_for(SimpleNamespace(voice=SimpleNamespace()))
    assert profile.name == barge_in.PROFILE_NORMAL
    assert profile.enabled
    assert profile.detector_kwargs() == {
        "grace_s": 1.5, "speech_threshold": 0.97, "consecutive_frames": 12,
    }


def test_fast_yields_sooner_but_keeps_a_grace_for_echo_calibration() -> None:
    profile = barge_in.profile_for(SimpleNamespace(voice=SimpleNamespace(barge_in="fast")))
    kwargs = profile.detector_kwargs()
    assert 0 < kwargs["grace_s"] < 1.5
    assert kwargs["consecutive_frames"] < 12
    assert kwargs["speech_threshold"] >= 0.9


def test_off_can_never_confirm_a_barge() -> None:
    profile = barge_in.profile_named("OFF")
    assert not profile.enabled
    kwargs = profile.detector_kwargs()
    assert kwargs["consecutive_frames"] >= 1_000_000
    assert kwargs["speech_threshold"] == 1.0


def test_unknown_values_and_missing_config_fall_back_to_normal() -> None:
    assert barge_in.profile_named("quick").name == barge_in.PROFILE_NORMAL
    assert barge_in.profile_for(None).name == barge_in.PROFILE_NORMAL
    assert barge_in.profile_for(SimpleNamespace()).name == barge_in.PROFILE_NORMAL


def test_a_caller_may_keep_its_own_grace() -> None:
    profile = barge_in.profile_named("fast")
    assert profile.detector_kwargs(grace_s=0.05)["grace_s"] == 0.05
    assert barge_in.profile_named("off").detector_kwargs(grace_s=0.05)["grace_s"] == 0.05


def test_the_detector_accepts_the_kwargs() -> None:
    from dodaios.realtime.desktop import DesktopRealtimeBargeInDetector

    for name in barge_in.PROFILES:
        DesktopRealtimeBargeInDetector(**barge_in.profile_named(name).detector_kwargs())
