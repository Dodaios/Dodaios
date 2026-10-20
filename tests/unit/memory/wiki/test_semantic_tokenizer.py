"""The plain-Python tokenizer segments like the vocabulary's reference does.

The real vocabulary has 250,000 pieces and is downloaded with the model, so
these tests run on a small hand-made one. Each case pins one rule of the
algorithm; agreement with the reference library on real text was measured
separately on 2,300 passages of a live vault.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.memory.wiki.semantic_tokenizer import UnigramTokenizer, normalize

W = "▁"  # the word-start marker

VOCAB: list[tuple[str, float]] = [
    ("<s>", 0.0),
    ("<pad>", 0.0),
    ("</s>", 0.0),
    ("<unk>", 0.0),
    (W, -3.0),
    (f"{W}un", -2.0),
    (f"{W}unhappy", -9.0),
    ("happy", -2.5),
    ("h", -6.0),
    ("a", -6.0),
    ("p", -6.0),
    ("y", -6.0),
    (f"{W}a", -2.0),
    (f"{W}b", -2.0),
    ("b", -5.0),
]
ID = {piece: index for index, (piece, _score) in enumerate(VOCAB)}


@pytest.fixture()
def tokenizer() -> UnigramTokenizer:
    return UnigramTokenizer(VOCAB, unk_id=3, bos_id=0, eos_id=2)


def test_picks_the_segmentation_with_the_best_total_score(tokenizer: UnigramTokenizer) -> None:
    # "_un" + "happy" scores -4.5 and beats the single piece "_unhappy" at -9.
    assert tokenizer.encode("unhappy") == [0, ID[f"{W}un"], ID["happy"], 2]


def test_every_word_starts_with_the_marker(tokenizer: UnigramTokenizer) -> None:
    assert tokenizer.encode("a b") == [0, ID[f"{W}a"], ID[f"{W}b"], 2]


def test_a_run_of_uncovered_characters_is_one_unknown(tokenizer: UnigramTokenizer) -> None:
    # "z" and "q" are in no piece; together they become a single unknown id.
    assert tokenizer.encode("azqb") == [0, ID[f"{W}a"], 3, ID["b"], 2]


def test_empty_and_blank_text_is_just_the_markers(tokenizer: UnigramTokenizer) -> None:
    assert tokenizer.encode("") == [0, 2]
    assert tokenizer.encode("  \t\n ") == [0, 2]


def test_a_long_text_keeps_its_start_and_the_end_marker(tokenizer: UnigramTokenizer) -> None:
    ids = tokenizer.encode("a " * 50, max_tokens=8)
    assert len(ids) == 8
    assert ids[0] == 0 and ids[-1] == 2
    assert ids[1:-1] == [ID[f"{W}a"]] * 6


def test_normalize_folds_width_whitespace_and_invisible_characters() -> None:
    assert normalize("ａｂ") == "ab"  # full-width letters
    assert normalize("a b\tc\nd") == "a b c d"  # every whitespace is a space
    assert normalize("a​b­c﻿") == "abc"  # zero width, soft hyphen, BOM
    assert normalize("ﬁ") == "fi"  # ligature


def test_loads_the_vocabulary_from_a_tokenizer_file(tmp_path: Path) -> None:
    path = tmp_path / "tokenizer.json"
    path.write_text(
        json.dumps({"model": {"type": "Unigram", "unk_id": 3, "vocab": VOCAB}}),
        encoding="utf-8",
    )
    loaded = UnigramTokenizer.from_file(path)
    assert loaded.encode("unhappy") == [0, ID[f"{W}un"], ID["happy"], 2]


def test_rejects_a_file_that_is_not_a_unigram_vocabulary(tmp_path: Path) -> None:
    path = tmp_path / "tokenizer.json"
    path.write_text(json.dumps({"model": {"type": "WordPiece", "vocab": {}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="unigram"):
        UnigramTokenizer.from_file(path)
