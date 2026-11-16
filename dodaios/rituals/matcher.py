"""Does what was said start a ritual? Decided by comparing words, with no model.

The phrase has to carry the sentence. After the address is peeled off both
ends (the wake word, the assistant's name, a "please"), what is left must be
the phrase, word for word. "Good morning, how is the weather" is a question
with a greeting in it and starts nothing; "Hey Nova, good morning" does.

Words are compared the way the wake word is: lower case, accents folded away,
punctuation ignored. An apostrophe inside a word is no break ("What's up" is
"Whats up"), and an umlaut reads the same as its two-letter spelling and as
its plain vowel (an o-umlaut as "oe" and as "o", a sharp s as "ss"). Saying the
phrase twice ("good morning, good morning") is still the phrase. The assistant's name is
compared by sound as well, because speech recognition spells a name in more
than one way.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Final

from dodaios.speech.wake_constants import (
    WAKE_PREFIXES,
    normalize_phrase_for_match,
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

#: An apostrophe between two letters: "What's", "let’s", "geht`s".
_INNER_APOSTROPHE: Final[re.Pattern[str]] = re.compile(r"(?<=\w)['\u2019\u2018`\u00b4](?=\w)")
#: An umlaut's two-letter spelling, after the accents were folded away ("ue" is "u").
_DIGRAPH: Final[re.Pattern[str]] = re.compile(r"([aou])e")


def _fold(token: str) -> str:
    """One spelling for an umlaut, its two-letter spelling and its plain vowel."""
    return _DIGRAPH.sub(r"\1", token)


#: Folded the way :func:`words` folds what was said.
_ADDRESS: Final[frozenset[str]] = frozenset(
    _fold(word) for word in WAKE_PREFIXES | _COURTESY | _PRODUCT_NAMES
)


def words(text: str) -> tuple[str, ...]:
    """``text`` as the words that are compared."""
    joined = _INNER_APOSTROPHE.sub("", str(text or ""))
    return tuple(_fold(token) for token in normalize_phrase_for_match(joined))


@lru_cache(maxsize=16)
def _name_sounds(wake_phrase: str) -> frozenset[str]:
    """The assistant's name (the wake phrase without its "hey"), by sound."""
    tokens = list(words(wake_phrase))
    core = list(tokens)
    while core and core[0] in WAKE_PREFIXES:
        core.pop(0)
    return frozenset(sound_fold(token) for token in core or tokens)


def _is_address(token: str, names: frozenset[str]) -> bool:
    return token in _ADDRESS or sound_fold(token) in names


def says(utterance: str, phrase: str, *, wake_phrase: str = "") -> bool:
    """Whether ``utterance`` is ``phrase`` (once or more) with nothing but address around it."""
    said, wanted = words(utterance), words(phrase)
    if not wanted or len(said) < len(wanted):
        return False
    names = _name_sounds(wake_phrase)
    size = len(wanted)
    index = hits = 0
    while index < len(said):
        if said[index : index + size] == wanted:
            hits += 1
            index += size
            continue
        if not _is_address(said[index], names):
            return False
        index += 1
    return hits > 0


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
