"""Does what was said start a ritual? Decided by comparing words, with no model.

The phrase has to carry the sentence. After the address is peeled off both
ends (the wake word, the assistant's name, a "please"), what is left must be
the phrase, word for word. "Good morning, how is the weather" is a question
with a greeting in it and starts nothing; "Hey Nova, good morning" does.

Words are compared the way the wake word is: lower case, accents folded away,
punctuation ignored. The assistant's name is compared by sound as well, because
speech recognition spells a name in more than one way.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Final

from dodaios.speech.wake_constants import (
    WAKE_PREFIXES,
    normalize_phrase_for_match,
    phrase_core_for_match,
    sound_fold,
)

from .models import MAX_PHRASE_CHARS, MAX_PHRASE_WORDS

#: Words of address and courtesy that may stand before or after the phrase.
#: Only those: a narrative word ("I just wanted to say …") is not on the list,
#: so a phrase that is merely mentioned starts nothing.
_COURTESY: Final[frozenset[str]] = frozenset(
    {
        "please", "thanks", "thank", "you",
        "bitte", "danke", "mal", "kurz",  # i18n-allow: spoken-input vocabulary
        "por", "favor", "gracias", "obrigado", "obrigada",  # i18n-allow: spoken-input vocabulary
    }
)
#: What the product and its assistant have been called; people keep saying it.
_PRODUCT_NAMES: Final[frozenset[str]] = frozenset({"dodaios", "jarvis"})
_ADDRESS: Final[frozenset[str]] = WAKE_PREFIXES | _COURTESY | _PRODUCT_NAMES


def words(text: str) -> tuple[str, ...]:
    """``text`` as the words that are compared."""
    return tuple(normalize_phrase_for_match(text))


@lru_cache(maxsize=16)
def _name_sounds(wake_phrase: str) -> frozenset[str]:
    """The assistant's name (the wake phrase without its "hey"), by sound."""
    return frozenset(sound_fold(token) for token in phrase_core_for_match(wake_phrase))


def _is_address(token: str, names: frozenset[str]) -> bool:
    return token in _ADDRESS or sound_fold(token) in names


def says(utterance: str, phrase: str, *, wake_phrase: str = "") -> bool:
    """Whether ``utterance`` is ``phrase`` with nothing but address around it."""
    said, wanted = words(utterance), words(phrase)
    if not wanted or len(said) < len(wanted):
        return False
    names = _name_sounds(wake_phrase)
    size = len(wanted)
    for start in range(len(said) - size + 1):
        if said[start : start + size] != wanted:
            continue
        around = (*said[:start], *said[start + size :])
        if all(_is_address(token, names) for token in around):
            return True
    return False


def same_phrase(first: str, second: str) -> bool:
    """Whether two phrases are the same words."""
    return words(first) == words(second)


def phrase_problem(phrase: str, *, wake_phrase: str = "") -> str:
    """Why ``phrase`` cannot start a ritual, or ``""`` when it can."""
    text = " ".join(str(phrase or "").split())
    tokens = words(text)
    if not tokens:
        return "A phrase needs at least one word."
    if len(text) > MAX_PHRASE_CHARS or len(tokens) > MAX_PHRASE_WORDS:
        return (
            f"A phrase is short: at most {MAX_PHRASE_WORDS} words "
            f"and {MAX_PHRASE_CHARS} characters."
        )
    names = _name_sounds(wake_phrase)
    if all(_is_address(token, names) for token in tokens):
        return (
            f'"{text}" is only a form of address (the wake word, a name, a "please"); '
            "it would start the ritual on nearly everything said."
        )
    return ""


__all__ = ["phrase_problem", "same_phrase", "says", "words"]
