"""The language a finished dictation is formatted in.

The filler rules are per language, and the recognizer's language tag is often
missing or spelled as a name. A dictation whose provider reports no language
must still get its hesitation sounds removed, a reported language must win
over a guess from the text, and whatever leaves the delivery step is a
language CODE the rest of the app can place.
"""

from __future__ import annotations

import pytest

from dodaios.core.config import DictationConfig
from dodaios.speech.pipeline import SpeechPipeline

pytestmark = pytest.mark.usefixtures("granted_microphone")


class _NullBus:
    async def publish(self, event: object) -> None:
        return None


def _delivery_pipeline() -> SpeechPipeline:
    pipe = SpeechPipeline.__new__(SpeechPipeline)
    pipe._bus = _NullBus()
    pipe._dictation_cfg = DictationConfig(target="chat", language="auto")
    pipe._dictation_completion_published = True
    return pipe


@pytest.mark.asyncio
async def test_fillers_are_removed_even_when_the_provider_names_no_language(
    monkeypatch,
) -> None:
    """``transcribe_pcm`` is only contracted to return TEXT.

    A provider that reports no language left the cleanup with nothing to match
    on, so it resolved to "no rules for this language" and every hesitation
    sound the user made went into the text — while the setting said filler
    removal was on. The language is read off the transcript instead, through
    the one canonical resolver.
    """
    pipe = _delivery_pipeline()
    recorded: dict[str, object] = {}

    async def _no_history(**kwargs: object) -> None:
        recorded.update(kwargs)

    pipe._record_dictation = _no_history  # type: ignore[method-assign]

    # The German hesitation sounds ARE the input under test:
    # the filler rules are per-language, so proving they ran needs a sentence
    # in a language that has rules.
    spoken = "Also ähm ich wollte äh kurz Bescheid sagen"  # i18n-allow: input under test

    cleaned = await pipe._finish_dictation(
        raw_text=spoken,
        language="",  # the provider said nothing
        duration_s=1.0,
        target="chat",
        hung_up=False,
    )

    assert "ähm" not in cleaned  # i18n-allow: input vocabulary under test
    assert "äh " not in cleaned  # i18n-allow: input vocabulary under test
    assert "Bescheid sagen" in cleaned  # i18n-allow: content words must survive
    assert recorded.get("language") == "de"


@pytest.mark.asyncio
async def test_a_reported_language_still_wins_over_the_text(monkeypatch) -> None:
    """Detection is the LAST resort, not a second opinion: a provider that did
    report a language keeps it, so a short or mixed transcript can never
    reclassify a dictation the provider was sure about.

    It keeps its MEANING, not its spelling. "English" wins here — and leaves as
    ``en``, because every consumer downstream keys off this string by code.
    """
    pipe = _delivery_pipeline()
    recorded: dict[str, object] = {}

    async def _no_history(**kwargs: object) -> None:
        recorded.update(kwargs)

    pipe._record_dictation = _no_history  # type: ignore[method-assign]

    await pipe._finish_dictation(
        raw_text="uh the thing is basically fine",
        language="English",
        duration_s=1.0,
        target="chat",
        hung_up=False,
    )

    assert recorded.get("language") == "en"


#: ``(reported tag, transcript, expected answer)``. The transcript AGREES with
#: the tag in every code case on purpose — that agreement is the normal path,
#: and it is the one the defect lived on. (A tag the text CONTRADICTS is covered
#: by its own test above: there the detection wins, which already worked.)
_LANGUAGE_TAG_CASES = [
    # What Groq and OpenAI actually answer: the language NAME, not a code.
    ("German", "kannst du es bitte im ordner abspeichern", "de"),  # i18n-allow
    ("english", "could you please save it in that folder", "en"),
    ("de-DE", "kannst du es bitte im ordner abspeichern", "de"),  # i18n-allow
    ("es", "puedes guardarlo en esa carpeta por favor", "es"),
    # No code to place it by -> verbatim, the documented no-op.
    ("French", "peux-tu enregistrer ceci dans le dossier", "French"),
    ("ja", "それを保存してください", "ja"),
]


@pytest.mark.parametrize(("reported", "text", "expected"), _LANGUAGE_TAG_CASES)
def test_a_placeable_language_leaves_as_a_code(
    reported: str, text: str, expected: str
) -> None:
    """The resolver answers with a CODE whenever the tag has one.

    Regression pin for the defect that made the polish pass rewrite words the
    user had said. The cloud Whisper APIs answer with the language NAME, the
    resolver handed that spelling on unchanged whenever the provider AGREED with
    the text — the normal case — and the polish pass's rare-token guard looks its
    vocabulary up by two-letter code, so it silently disabled itself on nearly
    every dictation. The guard was therefore armed only when the recognizer had
    been WRONG. Live cost, verbatim from the history:
    "kannst du es bitte mein download video abspeichern" was delivered as
    "Kannst du es bitte herunterladen?"  # i18n-allow: German transcript under test

    A tag with no code still passes through verbatim: ``detect_text_language``
    knows only de/en/es, and relabelling a French dictation as one of those
    would run the wrong language's rules over it.
    """
    from dodaios.speech.pipeline import resolve_dictation_language

    assert (
        resolve_dictation_language(pinned="auto", reported=reported, text=text)
        == expected
    )


def test_the_rare_token_guard_survives_a_provider_spelling() -> None:
    """The guard is robust to its caller, not just to a well-behaved one.

    Belt and braces with the resolver fix above: the guard normalises the
    language itself, so a future caller that forwards a provider's own spelling
    cannot silently disarm it. A guard whose failure mode looks exactly like
    passing has to defend itself.
    """
    from dodaios.dictation.polish_guards import drift_reason

    raw = "kannst du es bitte mein download video abspeichern"  # i18n-allow: under test
    rewritten = "Kannst du es bitte herunterladen?"  # i18n-allow: under test

    for spelling in ("de", "German", "de-DE", "GERMAN"):
        assert (
            drift_reason(
                raw,
                rewritten,
                language=spelling,
                protected=(),
                max_shrink=0.55,
                max_growth=1.20,
            )
            == "lost_term"
        ), spelling

    # ...while a genuine formatting pass still gets through untouched.
    assert (
        drift_reason(
            "kannst du es bitte mal in downloads ordner abspeichern",  # i18n-allow
            "Kannst du es bitte im Downloads-Ordner abspeichern.",  # i18n-allow
            language="German",
            protected=(),
            max_shrink=0.55,
            max_growth=1.20,
        )
        == ""
    )
