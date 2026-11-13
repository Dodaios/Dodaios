"""The language recent dictations were in, carried to the next one.

A recognizer finds the language from the audio it is handed. A clip of a few
seconds is too short for that: it comes back in the wrong language, and a
wrongly detected clip is not merely mislabelled, it is translated. So a short
clip is told the language recent dictations agreed on, and only a recording
long enough to detect from is asked to detect.
"""

from __future__ import annotations

from dodaios.dictation.take import SHORT_FOR_DETECTION_S, Take


def _asked_for(*, pinned: str, hint: str, speech_s: float) -> str:
    """The language a take asks a recognizer for, for a piece of ``speech_s``."""
    return Take([], language=pinned, language_hint=hint)._language_for(speech_s)


def test_a_short_clip_is_told_the_recent_language() -> None:
    assert _asked_for(pinned="auto", hint="de", speech_s=2.0) == "de"


def test_a_long_recording_is_asked_to_detect() -> None:
    assert _asked_for(pinned="auto", hint="de", speech_s=SHORT_FOR_DETECTION_S + 1) == "auto"


def test_without_a_recent_language_a_short_clip_detects_too() -> None:
    assert _asked_for(pinned="auto", hint="", speech_s=2.0) == "auto"


def test_a_chosen_language_is_what_the_recognizer_is_asked_for() -> None:
    assert _asked_for(pinned="de", hint="en", speech_s=2.0) == "de"
    assert _asked_for(pinned=" DE ", hint="", speech_s=40.0) == "de"


# ---------------------------------------------------------------------------
# The anchor that carries a reading across dictations
# ---------------------------------------------------------------------------


def _pipeline(*, primed: bool = True):
    """A bare pipeline for the anchor logic.

    ``primed`` marks the history seed as already done, so these tests exercise
    the arithmetic on readings they control instead of on whatever the machine
    running them happens to have dictated. The seeding itself is tested
    separately, against a history built for the purpose.
    """
    from dodaios.speech.pipeline import SpeechPipeline

    pipe = SpeechPipeline.__new__(SpeechPipeline)
    pipe._dictation_anchor_primed = primed
    return pipe


def test_a_fresh_pipeline_anchors_nothing() -> None:
    """No readings means auto-detect, exactly as before this existed."""
    assert _pipeline()._recent_dictation_language() == ""


def test_recent_dictations_supply_the_language_a_short_one_cannot() -> None:
    """The gap the in-session anchor leaves open, and why it matters.

    A two-second "carry on" is too short to detect a language from. On the
    live history, dictations under 4 s came back tagged English 59-64 % of the
    time for a speaker who was overwhelmingly speaking German, and a
    mis-detected clip is not merely mislabelled, it is TRANSLATED.

    Carrying the recent reading across is what gives that short recording the
    context its own audio cannot supply.
    """
    pipe = _pipeline()
    for _ in range(3):
        pipe._remember_dictation_language("de", on_device=False)

    assert pipe._recent_dictation_language() == "de"
    # And that is what the next take is told for a short clip, so it is
    # transcribed as German rather than detected from two seconds of audio.
    hint = pipe._recent_dictation_language()
    assert _asked_for(pinned="auto", hint=hint, speech_s=2.0) == "de"


def test_one_mis_detected_dictation_cannot_redirect_the_next() -> None:
    """A majority, not the last reading — the anchor has to be steadier than
    the signal it is correcting."""
    pipe = _pipeline()
    for lang in ("de", "de", "de", "en"):
        pipe._remember_dictation_language(lang, on_device=False)

    assert pipe._recent_dictation_language() == "de"


def test_a_speaker_who_switches_language_is_followed() -> None:
    """Steady is not the same as stuck: a real switch wins within the window.

    The bilingual mandate — a static pin was the 2026-06-14 bug and must not
    come back through the anchor.
    """
    pipe = _pipeline()
    for lang in ("de", "de", "en", "en", "en"):
        pipe._remember_dictation_language(lang, on_device=False)

    assert pipe._recent_dictation_language() == "en"


def test_an_on_device_reading_outvotes_a_run_of_cloud_guesses() -> None:
    """A local decoder cannot have translated the audio, so its answer is about
    the SOUND — the one reading a translation cannot fake."""
    pipe = _pipeline()
    for _ in range(3):
        pipe._remember_dictation_language("en", on_device=False)
    pipe._remember_dictation_language("de", on_device=True)

    assert pipe._recent_dictation_language() == "de"


def test_a_tie_restores_plain_auto_detect() -> None:
    """With no majority the anchor says nothing rather than picking a side."""
    pipe = _pipeline()
    pipe._remember_dictation_language("de", on_device=False)
    pipe._remember_dictation_language("en", on_device=False)

    assert pipe._recent_dictation_language() == ""


def test_unusable_readings_are_never_recorded() -> None:
    """``auto``/``unknown`` are the absence of a reading, not a language."""
    pipe = _pipeline()
    for junk in ("", "auto", "unknown", "und", None):
        pipe._remember_dictation_language(junk, on_device=False)

    assert pipe._recent_dictation_language() == ""


def test_a_user_pin_still_outranks_the_anchor() -> None:
    """The one signal a person sets deliberately keeps winning."""
    pipe = _pipeline()
    for _ in range(3):
        pipe._remember_dictation_language("en", on_device=False)

    hint = pipe._recent_dictation_language()
    assert _asked_for(pinned="de", hint=hint, speech_s=2.0) == "de"


def test_the_anchor_is_seeded_from_the_stored_history(tmp_path, monkeypatch) -> None:
    """After an app start the anchor must not be empty.

    Without seeding, the first short dictation of every session is back to
    asking two seconds of audio which language it is — the exact case this
    exists to avoid, reintroduced once per restart. The history already holds
    the answer.

    Only LONG entries are allowed to seed it, for the same reason only long
    dictations vote: a short one is what the provider gets wrong, so letting it
    seed would let the guess teach itself.
    """
    from dodaios.dictation.history import DictationHistory
    from dodaios.speech.pipeline import SpeechPipeline

    path = tmp_path / "history.json"
    store = DictationHistory(path)
    # Two long German dictations and a pile of short ones mis-tagged English —
    # the real shape of the bug this seed is for.
    for _ in range(6):
        store.add(raw_text="x", text="x", language="en", duration_s=1.5)
    for _ in range(2):
        store.add(raw_text="y", text="y", language="de", duration_s=12.0)

    monkeypatch.setattr(
        "dodaios.dictation.history.default_history_path", lambda: path
    )
    pipe = SpeechPipeline.__new__(SpeechPipeline)

    assert pipe._recent_dictation_language() == "de"


def test_seeding_happens_once_even_when_the_history_is_unreadable(
    tmp_path, monkeypatch
) -> None:
    """A broken history costs an opening guess, never a dictation."""
    from dodaios.speech.pipeline import SpeechPipeline

    calls: list[int] = []

    def _boom():
        calls.append(1)
        raise OSError("history is on a disconnected drive")

    monkeypatch.setattr("dodaios.dictation.history.default_history_path", _boom)
    pipe = SpeechPipeline.__new__(SpeechPipeline)

    assert pipe._recent_dictation_language() == ""
    assert pipe._recent_dictation_language() == ""
    assert len(calls) == 1, "the seed must not be retried on every dictation"
