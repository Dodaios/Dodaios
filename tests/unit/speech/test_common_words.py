"""The shipped word lists: what counts as an ordinary German or English word.

The speech dictionary repairs an invented spelling toward a registered word
and leaves ordinary words alone; this file is where that line is drawn.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.speech import common_words as cw
from dodaios.speech.common_words import CommonWords, common_words, lexicon_path


def test_the_file_ships_with_the_package() -> None:
    assert lexicon_path().is_file()
    words = common_words()
    assert words is not None
    assert words.word_count > 900_000


@pytest.mark.parametrize(
    "word",
    [
        # Words that sit one sound away from something people register.
        "grob", "Clause", "Nation", "Motion", "Lineal", "Cloud", "Claudia",
        "Website", "Maskottchen", "Straße", "genetic", "Genetik", "viel",  # i18n-allow
    ],
)
def test_ordinary_words_are_known(word: str) -> None:
    assert word in common_words()


@pytest.mark.parametrize(
    "token",
    ["Dodios", "Dios", "Diodios", "Klaude", "Veltrok", "Kubernetis", "Dodaios", "Odaios"],
)
def test_a_recognizers_inventions_are_not(token: str) -> None:
    assert token not in common_words()


def test_short_and_very_long_tokens_are_never_words() -> None:
    words = common_words()
    assert "der" not in words  # below the length the matcher looks at
    assert "x" * 40 not in words
    assert 42 not in words


def test_a_filter_survives_the_round_trip() -> None:
    built = CommonWords.build({"alpha", "bravo", "charlie"})
    loaded = CommonWords.from_bytes(built.to_bytes())
    assert loaded.word_count == 3
    assert "Alpha" in loaded and "charlie" in loaded
    assert "delta" not in loaded


def test_a_broken_file_is_refused() -> None:
    with pytest.raises(ValueError):
        CommonWords.from_bytes(b"NOPE" + bytes(40))
    with pytest.raises(ValueError):
        CommonWords.from_bytes(CommonWords.build({"alpha"}).to_bytes()[:-4])


def test_a_missing_file_costs_the_generous_matching_not_the_feature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cw, "_loaded", None)
    monkeypatch.setattr(cw, "_load_attempted", False)
    monkeypatch.setattr(cw, "lexicon_path", lambda: tmp_path / "missing.bloom")

    assert common_words() is None

    from dodaios.speech.stt_dictionary import DictionaryEntry, TranscriptCorrector

    corrector = TranscriptCorrector([DictionaryEntry(id="1", word="Dodaios")])
    # Exact sounds still work; the near match waits for the word lists.
    heard = "mit Dodayos und Dodios"  # i18n-allow
    assert corrector.correct(heard, "de") == "mit Dodaios und Dodios"  # i18n-allow
