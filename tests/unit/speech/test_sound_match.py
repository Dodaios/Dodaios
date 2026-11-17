"""Sound matching: a registered word is found wherever it was SAID.

A recognizer that does not know a word spells it a new way every time, so the
speech dictionary compares sounds, not spellings. These tests pin the three
ways a word is recognised (same sound, almost the same sound, a missing
beginning) and the guard that keeps ordinary speech from being rewritten.
"""
from __future__ import annotations

import pytest

from dodaios.speech.sound_match import (
    SoundMatcher,
    SoundTarget,
    near_budget,
    phonetic_key,
    sound_cost,
)

# A tiny stand-in for the shipped word lists.
ORDINARY = frozenset(
    {
        "nation", "motion", "clause", "cloud", "grob", "viel", "pipe", "built",
        "website", "schreibst", "wirklich", "gehen", "open", "have", "with",
        "about", "other", "that", "this", "says", "please", "start", "meine",
        "unser", "projekt", "heute", "nicht", "immer",  # i18n-allow
    }
)


def matcher(*words: str, heard: dict[str, tuple[str, ...]] | None = None) -> SoundMatcher:
    targets = [SoundTarget(w, phonetic_key(w), canonical=True) for w in words]
    for word, variants in (heard or {}).items():
        targets += [SoundTarget(word, phonetic_key(v), canonical=False) for v in variants]
    protected = {tok for w in words for tok in (w, *w.split())}
    return SoundMatcher(targets, is_word=lambda t: t in ORDINARY, protected=protected)


class TestPhoneticKey:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Veltrok", "Veltroc"),
            ("Klaude", "Claude"),
            ("Cloude", "Claude"),
            ("Doda iOS", "Dodaios"),
            ("Dodai-OS", "Dodaios"),
            ("Dodeios", "Dodaios"),
            ("Dodayos", "Dodaios"),
            ("Anthropik", "Anthropic"),
        ],
    )
    def test_spelling_twins_share_a_key(self, a: str, b: str) -> None:
        assert phonetic_key(a) == phonetic_key(b)

    @pytest.mark.parametrize(
        ("a", "b"), [("grob", "Grok"), ("Clause", "Claude"), ("Nation", "Notion")]
    )
    def test_different_sounds_keep_different_keys(self, a: str, b: str) -> None:
        assert phonetic_key(a) != phonetic_key(b)


class TestSoundCost:
    def test_a_vowel_is_half_a_step(self) -> None:
        assert sound_cost("dodios", "dodaios", 1.0) == 0.5
        assert sound_cost("nikolas", "nikolos", 1.0) == 0.5

    def test_a_consonant_twin_is_half_a_step(self) -> None:
        assert sound_cost("dodaios", "totaios", 1.0) == 1.0

    def test_another_consonant_is_a_full_step_or_forbidden(self) -> None:
        assert sound_cost("klause", "klaude", 1.0) == 1.0
        assert sound_cost("klause", "klaude", 1.0, consonants=False) is None

    def test_beyond_the_budget_is_no_match(self) -> None:
        assert sound_cost("dudodios", "dodaios", 1.0) is None

    def test_short_words_are_exact_only_and_long_ones_may_lose_a_consonant(self) -> None:
        assert near_budget(4) == (0.0, False)
        assert near_budget(6) == (0.5, False)
        assert near_budget(7) == (1.0, False)
        assert near_budget(10) == (1.5, True)


class TestSameSound:
    def test_a_spelling_twin_becomes_the_word(self) -> None:
        assert matcher("Claude").rewrite("one Klaude terminal") == "one Claude terminal"

    def test_a_word_split_in_two_is_put_back(self) -> None:
        m = matcher("Dodaios")
        assert m.rewrite("start Doda iOS now") == "start Dodaios now"
        assert m.rewrite("start Dodai-OS now") == "start Dodaios now"

    def test_the_word_with_a_gap_in_it_needs_no_witness(self) -> None:
        # Both halves are ordinary words; together they are the word itself.
        m = SoundMatcher(
            [SoundTarget("OpenAI", phonetic_key("OpenAI"), canonical=True)],
            is_word=lambda t: t in {"open"},
            protected={"openai"},
        )
        assert m.rewrite("ask Open AI about it") == "ask OpenAI about it"

    def test_ordinary_words_that_happen_to_sound_alike_are_a_sentence(self) -> None:
        m = matcher(heard={"PyPI": ("Pipe-I",)})
        assert m.rewrite("the pipe I built") == "the pipe I built"

    def test_an_ordinary_word_is_never_taken_for_a_registered_one(self) -> None:
        # "viel" and "Phil" fold to one key; "viel" is a word and stays.
        said = "das ist viel"  # i18n-allow
        assert matcher("Phil").rewrite(said) == said

    def test_a_listed_mishearing_also_catches_its_other_spelling(self) -> None:
        m = SoundMatcher(
            [SoundTarget("Agentic", phonetic_key("Genetic"), canonical=False)],
            is_word=lambda t: t == "genetik",
            protected={"agentic"},
        )
        assert m.rewrite("die Genetik IDE") == "die Agentic IDE"

    def test_two_registered_words_with_one_sound_are_left_alone(self) -> None:
        assert matcher("Nico", "Niko").rewrite("call Nicko today") == "call Nicko today"


class TestAlmostTheSameSound:
    @pytest.mark.parametrize(
        ("heard", "meant"),
        [
            # Verbatim spellings from one week of dictation history.
            ("du mit Dodios schreibst", "du mit Dodaios schreibst"),  # i18n-allow
            ("von Diodios vornimmt", "von Dodaios vornimmt"),  # i18n-allow
            ("wie du Dios die Canvas baut", "wie Dodaios die Canvas baut"),  # i18n-allow
            ("wirklich um die Dios gehen", "wirklich um Dodaios gehen"),  # i18n-allow
            ("meine Dodios-Website", "meine Dodaios-Website"),
        ],
    )
    def test_the_recognizers_spellings_of_a_new_name(self, heard: str, meant: str) -> None:
        assert matcher("Dodaios").rewrite(heard) == meant

    def test_a_name_chopped_into_syllables_is_put_back(self) -> None:
        # What the local recognizer wrote for a synthesized "Dodaios": no
        # token in it is long enough to be judged, together they are the name.
        m = matcher("Dodaios")
        assert m.rewrite("Wenn du da iOS eine Frage") == "Wenn Dodaios eine Frage"  # i18n-allow
        assert m.rewrite("an Duda iOS und") == "an Dodaios und"

    def test_short_words_that_do_not_sound_like_the_name_stay(self) -> None:
        m = matcher("Dodaios", "Notion", "Obsidian")
        for said in (
            "so do I as it is",
            "du bist da und er ist es",  # i18n-allow
            "no it is not on",
            "the DoD is talking",
            "und die Frage, ob sie den Plan",  # i18n-allow
        ):
            assert m.rewrite(said) == said

    def test_a_long_word_may_differ_by_one_consonant(self) -> None:
        m = matcher("Kubernetes")
        assert m.rewrite("deploy on Kubernetis") == "deploy on Kubernetes"
        assert m.rewrite("deploy on Kubernedes") == "deploy on Kubernetes"

    def test_an_ordinary_word_is_no_witness(self) -> None:
        m = matcher("Notion", "Claude", "Grok")
        for said in (
            "the nation says",
            "a clause in it",
            "in the cloud",
            "das ist grob",  # i18n-allow
        ):
            assert m.rewrite(said) == said

    def test_a_different_consonant_is_a_different_word(self) -> None:
        # Names the word lists do not know, one consonant away.
        m = matcher("Whisper", "Claude")
        for said in ("Janine Wissler sagte", "Herr Wieser kam", "Frau Klaube kam"):
            assert m.rewrite(said) == said

    def test_short_names_are_never_guessed(self) -> None:
        m = matcher("Nico", "Mira", "Kimi")
        for said in ("with Niki Lauda", "ask Mera about it", "Kemi says"):
            assert m.rewrite(said) == said

    def test_a_token_with_an_apostrophe_or_in_capitals_is_no_witness(self) -> None:
        m = matcher("Hermes", "Linear", "Dodaios")
        for said in ("Here's what happened", "the day's work", "LNER trains", "the HRMs"):
            assert m.rewrite(said) == said

    def test_the_word_with_an_ending_is_left_as_it_is(self) -> None:
        m = matcher("Claude", "Dodaios")
        assert m.rewrite("Claudes Antwort") == "Claudes Antwort"  # i18n-allow
        assert m.rewrite("die Dodaiosse") == "die Dodaiosse"

    def test_a_split_keeps_a_word_that_is_not_part_of_the_name(self) -> None:
        heard = "wie du Dodios den Prompt"  # i18n-allow
        assert matcher("Dodaios").rewrite(heard) == "wie du Dodaios den Prompt"  # i18n-allow

    def test_a_registered_word_is_never_rewritten_toward_another(self) -> None:
        m = matcher("Leiner", "Linear")
        assert m.rewrite("Leiner und Linear") == "Leiner und Linear"


class TestMissingBeginning:
    def test_the_end_of_the_word_is_the_word(self) -> None:
        m = matcher("Dodaios", "Kubernetes")
        assert m.rewrite("Hauptagent Odaios chattet") == "Hauptagent Dodaios chattet"
        assert m.rewrite("deploy on Bernetes") == "deploy on Kubernetes"

    def test_a_short_end_is_not_enough(self) -> None:
        m = matcher("Raycast", "Claude")
        for said in ("Bas Kast erklärt", "sagt Aude Hennino"):  # i18n-allow
            assert m.rewrite(said) == said


class TestCoverage:
    def test_exact_only_leaves_near_matches_alone(self) -> None:
        m = matcher("Dodaios")
        assert m.rewrite("con Dodios", generous=False) == "con Dodios"
        assert m.rewrite("con Doda iOS", generous=False) == "con Dodaios"

    def test_a_covered_only_mishearing_needs_a_covered_text(self) -> None:
        m = SoundMatcher(
            [
                SoundTarget("Dodaios", phonetic_key("Dodaios"), canonical=True),
                SoundTarget(
                    "Dodaios", phonetic_key("Dios"), canonical=False, covered_only=True
                ),
            ],
            is_word=lambda t: t in ORDINARY,
            protected={"dodaios"},
        )
        assert m.rewrite("unser Dios Projekt") == "unser Dodaios Projekt"
        assert m.rewrite("Dios mío", generous=False) == "Dios mío"

    def test_knows_tells_a_covered_text_from_another_language(self) -> None:
        m = matcher("Dodaios")
        assert m.knows("unser Projekt heute mit Dodios") is True  # i18n-allow
        assert m.knows("Dios mío, otra vez") is False
        assert m.knows("ok") is False

    def test_without_word_lists_only_exact_sounds_match(self) -> None:
        m = SoundMatcher(
            [SoundTarget("Dodaios", phonetic_key("Dodaios"), canonical=True)],
            is_word=None,
            protected={"dodaios"},
        )
        heard = "mit Dodios und Dodayos"  # i18n-allow
        assert m.rewrite(heard) == "mit Dodios und Dodaios"  # i18n-allow
        assert m.knows("anything at all") is False


def test_text_without_a_match_comes_back_unchanged() -> None:
    said = "nothing to do here, 42 times over"
    assert matcher("Dodaios").rewrite(said) is said
    assert matcher().rewrite(said) is said
