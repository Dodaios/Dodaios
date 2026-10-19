"""Sentence tokenizer for the wiki's semantic search model, in plain Python.

The search model reads token ids, and the ids come from a SentencePiece
unigram vocabulary stored in the model's ``tokenizer.json``. Segmenting a word
against that vocabulary is a short dynamic program, so this module does it
directly instead of pulling a native tokenizer package into the install: the
feature then needs nothing beyond what the base install already carries.

The pipeline is the one the vocabulary file declares:

1. normalize the text (NFKC, control characters dropped, every kind of
   whitespace folded to a plain space);
2. split on whitespace and mark each word start with ``U+2581``;
3. pick, per word, the segmentation with the highest total piece score;
4. wrap the ids in the sentence start and end markers.

A character no vocabulary piece covers becomes the unknown id, and a run of
such characters collapses into a single unknown id.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

#: The word-start marker SentencePiece vocabularies use.
_WORD_START = "▁"

#: How far below the worst vocabulary score an uncovered character is rated,
#: so a real piece always beats the unknown fallback.
_UNKNOWN_PENALTY = 10.0

#: Segmentations kept per tokenizer. Words repeat heavily inside a vault, and
#: one cached word costs a few dozen bytes.
_WORD_CACHE_LIMIT = 50_000

_BOS = "<s>"
_EOS = "</s>"


def normalize(text: str) -> str:
    """Fold *text* to the form the vocabulary was trained on."""
    folded: list[str] = []
    for char in unicodedata.normalize("NFKC", text):
        if char.isspace():
            folded.append(" ")
            continue
        category = unicodedata.category(char)
        # Control and format characters (zero-width joiners, soft hyphens,
        # byte order marks) carry no meaning for retrieval.
        if category in ("Cc", "Cf"):
            continue
        folded.append(char)
    return "".join(folded)


class UnigramTokenizer:
    """Turn text into the token ids of one unigram vocabulary."""

    def __init__(
        self,
        vocab: list[tuple[str, float]],
        *,
        unk_id: int,
        bos_id: int,
        eos_id: int,
    ) -> None:
        if not vocab:
            raise ValueError("the tokenizer vocabulary is empty")
        self._ids: dict[str, int] = {}
        self._scores: dict[str, float] = {}
        for index, (piece, score) in enumerate(vocab):
            # The first entry wins, exactly as a lookup by position would.
            if piece not in self._ids:
                self._ids[piece] = index
                self._scores[piece] = float(score)
        self._unk_id = unk_id
        self._bos_id = bos_id
        self._eos_id = eos_id
        self._max_piece_chars = max(len(piece) for piece in self._ids)
        self._unknown_score = min(self._scores.values()) - _UNKNOWN_PENALTY
        self._word_cache: dict[str, tuple[int, ...]] = {}

    @classmethod
    def from_file(cls, path: Path) -> UnigramTokenizer:
        """Load the vocabulary from a ``tokenizer.json`` file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        model = data.get("model") or {}
        if model.get("type") != "Unigram":
            raise ValueError("tokenizer.json does not hold a unigram vocabulary")
        vocab = [(str(piece), float(score)) for piece, score in model["vocab"]]
        ids = {piece: index for index, (piece, _score) in reversed(list(enumerate(vocab)))}
        if _BOS not in ids or _EOS not in ids:
            raise ValueError("tokenizer.json lacks the sentence start or end marker")
        return cls(
            vocab,
            unk_id=int(model.get("unk_id", 0)),
            bos_id=ids[_BOS],
            eos_id=ids[_EOS],
        )

    def encode(self, text: str, *, max_tokens: int = 128) -> list[int]:
        """Token ids for *text*, markers included, at most *max_tokens* long.

        A longer text keeps its first ``max_tokens - 1`` ids and the end
        marker, which is how the model was trained to read a cut sentence.
        """
        ids = [self._bos_id]
        budget = max(max_tokens - 2, 0)
        for word in normalize(text).split():
            if len(ids) - 1 >= budget:
                break
            ids.extend(self._encode_word(word))
        del ids[budget + 1 :]
        ids.append(self._eos_id)
        return ids

    def _encode_word(self, word: str) -> tuple[int, ...]:
        cached = self._word_cache.get(word)
        if cached is not None:
            return cached
        ids = self._segment(_WORD_START + word)
        if len(self._word_cache) < _WORD_CACHE_LIMIT:
            self._word_cache[word] = ids
        return ids

    def _segment(self, text: str) -> tuple[int, ...]:
        """Best-scoring split of one marked word into vocabulary pieces."""
        length = len(text)
        best_score = [float("-inf")] * (length + 1)
        best_start = [-1] * (length + 1)
        best_id = [self._unk_id] * (length + 1)
        best_score[0] = 0.0
        scores = self._scores
        for start in range(length):
            base = best_score[start]
            if base == float("-inf"):
                continue
            single_piece = False
            for end in range(start + 1, min(length, start + self._max_piece_chars) + 1):
                piece = text[start:end]
                score = scores.get(piece)
                if score is None:
                    continue
                if end == start + 1:
                    single_piece = True
                candidate = base + score
                if best_start[end] < 0 or candidate > best_score[end]:
                    best_score[end] = candidate
                    best_start[end] = start
                    best_id[end] = self._ids[piece]
            if not single_piece:
                candidate = base + self._unknown_score
                end = start + 1
                if best_start[end] < 0 or candidate > best_score[end]:
                    best_score[end] = candidate
                    best_start[end] = start
                    best_id[end] = self._unk_id
        ids: list[int] = []
        position = length
        while position > 0:
            token = best_id[position]
            # A run of uncovered characters is one unknown token, not many.
            if not (token == self._unk_id and ids and ids[-1] == self._unk_id):
                ids.append(token)
            position = best_start[position]
        ids.reverse()
        return tuple(ids)


__all__ = ["UnigramTokenizer", "normalize"]
