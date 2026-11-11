"""Ranking for ``find_tools``: BM25 over what a tool is called and says.

A model asks for a tool in its own words, in whatever language the person
spoke (a German "send a mail to", "what is running", "linear ticket"). Plain
word overlap misses most of those: the tool says "email" and "send message",
the request says "Mail" and "schick". This ranks the deferred tools with
Okapi BM25 over four fields (tool name, server or category, aliases and
description), folds umlauts, stems lightly, and widens the query with a small
German/English synonym table so either language finds the same tool.

Pure Python, no registry and no model: AP-26 and "no new heavy dependency".
A tool may carry ``search_aliases`` (a tuple of extra words) to be found
under names its description does not use.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from typing import Any, Final

__all__ = ["STOP_WORDS", "rank_tools", "search_terms"]

_K1: Final[float] = 1.5
_B: Final[float] = 0.75
#: How often a field's words count, so a hit in the name outweighs one buried
#: in a long description.
_NAME_WEIGHT: Final[int] = 3
_GROUP_WEIGHT: Final[int] = 2
_ALIAS_WEIGHT: Final[int] = 2
#: A synonym added by the table counts less than a word the person said.
_EXPANSION_WEIGHT: Final[float] = 0.6

_WORD_RE = re.compile(r"[a-z0-9]+")
_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u"})  # i18n-allow: umlaut folding data

#: Words that say nothing about which tool is meant (English and German).
STOP_WORDS: Final[frozenset[str]] = frozenset(
    {
        "a", "an", "and", "for", "from", "i", "in", "is", "it", "me", "my", "of", "on",
        "or", "please", "the", "this", "to", "want", "with", "what", "whats", "s", "do",
        "can", "you", "how", "now", "all",
        "eine", "einen", "einem", "ein", "der", "die", "das", "den", "dem", "und",
        "mir", "ich", "mein", "meine", "meinen", "bitte", "im", "auf", "zu",
        "von", "was", "wer", "wie", "mal", "doch", "fur", "mit", "ist", "sind",
    }  # i18n-allow: German stop words are matching data
)

#: Synonyms, keyed by the folded stem of a word the person may use. Each value
#: is what a tool of that kind is likely to say. The two languages meet in
#: English, because tool names and descriptions are English.
_SYNONYMS: Final[dict[str, tuple[str, ...]]] = {  # i18n-allow: German matching data
    "schick": ("send", "message"),
    "sende": ("send", "message"),
    "send": ("message",),
    "versend": ("send", "message"),
    "mail": ("email", "gmail", "message"),
    "email": ("mail", "gmail", "message"),
    "nachricht": ("message", "send"),
    "kalender": ("calendar", "event"),
    "calendar": ("event",),
    "termin": ("calendar", "event", "meeting"),
    "meeting": ("calendar", "event"),
    "morgen": ("tomorrow", "upcoming", "date"),
    "heute": ("today", "date"),
    "ticket": ("issue", "task"),
    "issue": ("ticket",),
    "aufgabe": ("task", "issue", "todo"),
    "lauf": ("running", "status", "active", "job"),
    "lauft": ("running", "status", "active", "job"),
    "laeuft": ("running", "status", "active", "job"),
    "running": ("status", "active", "job", "progress"),
    "status": ("progress", "state"),
    "fortschritt": ("status", "progress"),
    "datei": ("file", "document"),
    "ordner": ("folder", "directory"),
    "such": ("search", "find"),
    "find": ("search",),
    "lies": ("read", "get"),
    "les": ("read", "get"),
    "losch": ("delete", "remove"),
    "entfern": ("delete", "remove"),
    "erstell": ("create", "new"),
    "anleg": ("create", "new"),
    "speicher": ("save", "store"),
    "aender": ("update", "edit"),
    "musik": ("music", "play", "song"),
    "lied": ("song", "music", "play"),
    "spiel": ("play",),
    "licht": ("light", "lamp"),
    "wetter": ("weather", "forecast"),
    "kontakt": ("contact", "person"),
    "erinner": ("reminder", "remind"),
    "erinnerung": ("reminder", "remind"),
    "projekt": ("project",),
    "rechnung": ("invoice", "payment"),
    "zahlung": ("payment", "charge"),
    "kunde": ("customer",),
    "datenbank": ("database", "sql", "table"),
    "anfrage": ("request", "pull"),
    "oeffne": ("open",),
    "offn": ("open",),
    "zeig": ("show", "list", "display"),
    "liste": ("list",),
}

_SUFFIXES: Final[tuple[str, ...]] = ("ungen", "ung", "ing", "en", "er", "es", "ed", "e", "s", "n")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _fold(text: str) -> str:
    return (text or "").lower().replace("ß", "ss").translate(_FOLD)  # i18n-allow: folding


def _stems(text: str) -> list[str]:
    return [_stem(word) for word in _WORD_RE.findall(_fold(text))]


_BY_STEM: Final[dict[str, tuple[str, ...]]] = {
    _stem(_fold(key)): words for key, words in _SYNONYMS.items()
}


def search_terms(query: str) -> dict[str, float]:
    """The weighted stems a query looks for: its own words and their synonyms."""
    own = [
        _stem(word)
        for word in _WORD_RE.findall(_fold(query))
        if word not in STOP_WORDS
    ]
    terms: dict[str, float] = {stem: 1.0 for stem in own}
    for stem in own:
        for synonym in _BY_STEM.get(stem, ()):
            terms.setdefault(_stem(synonym), _EXPANSION_WEIGHT)
    return terms


def _fields(name: str, tool: Any) -> list[str]:
    server, _, local = name.partition("/")
    group = server if local else ""
    aliases = " ".join(str(a) for a in (getattr(tool, "search_aliases", None) or ()))
    tokens: list[str] = []
    tokens += _stems(local or name) * _NAME_WEIGHT
    tokens += _stems(group) * _GROUP_WEIGHT
    tokens += _stems(aliases) * _ALIAS_WEIGHT
    tokens += _stems(getattr(tool, "description", "") or "")
    return tokens


def rank_tools(query: str, tools: Mapping[str, Any]) -> list[str]:
    """Names of ``tools`` that match ``query``, best first; non-matches left out."""
    terms = search_terms(query)
    if not terms or not tools:
        return []
    counts = {name: Counter(_fields(name, tool)) for name, tool in tools.items()}
    lengths = {name: sum(c.values()) for name, c in counts.items()}
    total = len(counts)
    average = (sum(lengths.values()) / total) or 1.0
    frequency = {term: sum(1 for c in counts.values() if term in c) for term in terms}
    scored: list[tuple[float, int, str]] = []
    for name, counter in counts.items():
        score = 0.0
        overlap = 0
        for term, weight in terms.items():
            tf = counter.get(term, 0)
            if not tf:
                continue
            overlap += 1
            df = frequency[term]
            idf = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
            score += weight * idf * (tf * (_K1 + 1.0)) / (
                tf + _K1 * (1.0 - _B + _B * lengths[name] / average)
            )
        if score > 0.0:
            scored.append((score, overlap, name))
    # Word overlap, then the name, break a tie in score.
    scored.sort(key=lambda item: (-round(item[0], 9), -item[1], item[2]))
    return [name for _score, _overlap, name in scored]
