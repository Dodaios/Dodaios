"""The shipped default vocabulary: every install fixes the product name and the
developer terms mixed German/English dictation keeps mishearing — and the
user's own dictionary always wins over it.

Reported 2026-10-20: "Pipey" / "Pipe-I" for PyPI, "Baggen" for Bugs, "the Dios"
for Dodaios.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.speech.stt_dictionary import (
    DEFAULT_ID_PREFIX,
    DEFAULT_TERMS,
    DictionaryStore,
    dictionary_bias_words,
    dictionary_protected_words,
    get_corrector,
)


@pytest.fixture
def store(tmp_path: Path) -> DictionaryStore:
    return DictionaryStore(tmp_path / "stt_dictionary.json")


@pytest.mark.parametrize(
    ("heard", "meant"),
    [
        (
            "Ich habe das auf Pipey veröffentlicht.",  # i18n-allow: German dictation fixture
            "Ich habe das auf PyPI veröffentlicht.",  # i18n-allow: German dictation fixture
        ),
        ("Das Paket liegt auf Pipe-I.", "Das Paket liegt auf PyPI."),  # i18n-allow: fixture
        ("Die Baggen sind gefixt.", "Die Bugs sind gefixt."),  # i18n-allow: fixture
        ("I opened the Dios again.", "I opened Dodaios again."),
        ("Starte Doda iOS neu.", "Starte Dodaios neu."),
        ("Push it to Git Hub.", "Push it to GitHub."),
        ("push it to github", "push it to GitHub"),
        ("Schau dir die PR's an.", "Schau dir die PRs an."),
        ("dodaios startet", "Dodaios startet"),
    ],
)
def test_a_fresh_install_corrects_the_reported_mishearings(
    store: DictionaryStore, heard: str, meant: str
) -> None:
    assert get_corrector(store).correct(heard) == meant


@pytest.mark.parametrize(
    "said",
    [
        # Real words next to the defaults stay exactly as said.
        "Ich speichere das in der Cloud.",  # i18n-allow: German dictation fixture
        "Dios mío, otra vez.",
        "PyPy is a different interpreter.",
        "fix the bugs before the release",  # common word: no casing rule
        "We merge the release branch.",
        "the pipe I built",
        # "PyPI" folds like these; the sound-alike repair must not reach them.
        "Pippi Langstrumpf",
        "Das Kind muss Pipi.",  # i18n-allow: German dictation fixture
    ],
)
def test_the_defaults_leave_ordinary_words_alone(store: DictionaryStore, said: str) -> None:
    assert get_corrector(store).correct(said) == said


def test_reading_never_writes_the_users_sidecar(store: DictionaryStore) -> None:
    get_corrector(store).correct("Pipey")
    store.effective_entries()
    assert not store.path.exists()


def test_a_user_entry_for_the_same_word_replaces_the_default(
    store: DictionaryStore,
) -> None:
    store.add("PyPI", ["Pie Pie"])

    words = [e.word for e in store.effective_entries()]
    assert words.count("PyPI") == 1
    corrector = get_corrector(store)
    assert corrector.correct("Pie Pie") == "PyPI"
    # The default's variants went with it: the user's entry is the rule now.
    assert corrector.correct("Pipey") == "Pipey"


def test_a_user_spelling_beats_a_default_variant(store: DictionaryStore) -> None:
    store.add("Pipeline", ["Pipey"])

    assert get_corrector(store).correct("Pipey") == "Pipeline"
    # The rest of the default survives.
    assert get_corrector(store).correct("Pipe-I") == "PyPI"


def test_a_user_who_calls_the_word_a_mishearing_hides_the_default(
    store: DictionaryStore,
) -> None:
    store.add("Bugsy", ["Bugs"])

    assert "Bugs" not in [e.word for e in store.effective_entries()]


def test_a_deleted_default_stays_deleted(store: DictionaryStore) -> None:
    assert store.delete(f"{DEFAULT_ID_PREFIX}bugs") is True

    assert get_corrector(store).correct("Die Baggen") == "Die Baggen"
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["removed_defaults"] == [f"{DEFAULT_ID_PREFIX}bugs"]
    # Later writes keep the record.
    store.add("Vokando")
    assert store.removed_defaults() == frozenset({f"{DEFAULT_ID_PREFIX}bugs"})
    assert store.delete(f"{DEFAULT_ID_PREFIX}bugs") is False


def test_an_edited_default_is_stored_as_the_users_own(store: DictionaryStore) -> None:
    edited = store.update(
        f"{DEFAULT_ID_PREFIX}dodaios", misheard=["the Dios", "Duda OS"], misheard_set=True
    )

    assert edited is not None
    assert edited.default is False
    stored = store.list_all()
    assert [e.id for e in stored] == [f"{DEFAULT_ID_PREFIX}dodaios"]
    assert get_corrector(store).correct("Duda OS") == "Dodaios"
    # The sidecar holds the user's data only, never the derived flags.
    row = json.loads(store.path.read_text(encoding="utf-8"))["entries"][0]
    assert set(row) == {"id", "word", "misheard", "created_at", "updated_at"}


def test_an_unknown_default_id_is_not_found(store: DictionaryStore) -> None:
    assert store.update(f"{DEFAULT_ID_PREFIX}nope", word="X") is None
    assert store.delete(f"{DEFAULT_ID_PREFIX}nope") is False


def test_the_defaults_stay_out_of_every_decoder_prompt(store: DictionaryStore) -> None:
    """BUG-185/BUG-211: a primed Whisper recites its prompt over silence."""
    assert dictionary_bias_words(store) == []
    store.add("Vokando")
    assert dictionary_bias_words(store) == ["Vokando"]


def test_the_polish_pass_protects_the_defaults(store: DictionaryStore) -> None:
    words = dictionary_protected_words(store)

    assert {"Dodaios", "PyPI", "GitHub"} <= set(words)


def test_a_sentence_listing_default_terms_is_not_taken_for_a_recited_prompt(
    store: DictionaryStore,
) -> None:
    """The echo guard drops runs of PRIMED words; the defaults never are."""
    said = "Wir nutzen GitHub, PyPI, PRs und Dodaios."  # i18n-allow: German fixture

    assert get_corrector(store).strip_prompt_echo(said) == said


def test_the_defaults_carry_no_personal_data() -> None:
    for term in DEFAULT_TERMS:
        for value in (term.word, *term.misheard):
            assert "@" not in value
            assert not any(ch.isdigit() for ch in value)
    slugs = [t.slug for t in DEFAULT_TERMS]
    assert len(slugs) == len(set(slugs))
