"""A stand-in for the wiki's sentence encoder that needs no model.

The real encoder maps texts with the same meaning to nearby vectors, whatever
their wording or language. This fake does the same for a handful of concepts
it is told about: every text becomes a unit vector over those concepts, so
"when is my sister's birthday" and a German note about the sister's birthday
land on the same axes while a note about pizza lands elsewhere.

It also honours the encoder's contract the callers rely on: ``wait=False``
returns ``None`` while ``busy`` is set, and every call is recorded.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from dodaios.memory.wiki.semantic_model import EMBEDDING_DIMENSIONS

#: Concept -> the words that express it, in any language the tests use.
DEFAULT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "sister": ("sister", "schwester"),
    "birthday": ("birthday", "geburtstag", "born"),
    "food": ("pizza", "food", "essen", "eat", "meal"),
    "travel": ("flight", "travel", "reise", "trip", "paris"),
    "testing": ("testing", "validating", "integrations", "connections"),
}


class FakeSemanticEncoder:
    def __init__(self, concepts: dict[str, tuple[str, ...]] | None = None) -> None:
        self._concepts = concepts or DEFAULT_CONCEPTS
        self.calls: list[list[str]] = []
        self.busy = False
        self.warmed = 0
        self.closed = 0

    def encode(self, texts: Sequence[str], *, wait: bool = True) -> Any | None:
        if self.busy and not wait:
            return None
        self.calls.append(list(texts))
        out = np.zeros((len(texts), EMBEDDING_DIMENSIONS), dtype=np.float32)
        for row, text in enumerate(texts):
            lowered = text.lower()
            for axis, words in enumerate(self._concepts.values()):
                if any(word in lowered for word in words):
                    out[row, axis] = 1.0
            if not out[row].any():
                # Unrelated text points somewhere no concept does.
                out[row, EMBEDDING_DIMENSIONS - 1] = 1.0
            out[row] /= np.linalg.norm(out[row])
        return out

    def warm_up(self) -> None:
        self.warmed += 1

    def close(self) -> None:
        self.closed += 1

    @property
    def texts_encoded(self) -> int:
        return sum(len(call) for call in self.calls)
