"""Whether a recognized sentence is really finished, by German and English grammar.

A recognizer writes a full stop wherever the speaker stops for a while. People
stop to think in the middle of a sentence too, so a dictation gets full stops
inside sentences, and the words after such a pause arrive as a "sentence" of
their own. A paragraph, a cut in the recording or a capital put at such a
place splits a sentence in two.

The rules here tell those stops from real sentence ends, from the words alone
and without a model. Three kinds:

* **A word no sentence ends with.** An article, a conjunction, a possessive
  always has something after it: "the", "and", "because", "my".
* **A German clause still waiting for its verb.** A German subordinate or
  relative clause puts its verb last, so such a clause that ends in a noun,
  an adjective or a pronoun has not ended yet (the German example of "that
  these paragraphs are not really sensible" without its final verb).
* **A sentence that only carries on the one before**: it starts in lower case,
  it is one or two words that are not a reply or a greeting, or it is a
  subordinate or relative clause on its own ("Which we can remove.").

Every rule leans the same way. Calling a finished sentence unfinished costs a
paragraph or a cut that would have been fine; calling a broken sentence
finished splits it. So a rule says "unfinished" on fair evidence, and the one
place that rewrites text (:func:`joinable_tail`) asks for more.

German and English are covered in full. For a dictation in another language,
or one whose language is not known, only the words that end no sentence in any
served language count.
"""

from __future__ import annotations

import re

from dodaios.dictation.cleanup import normalize_language

# i18n-allow: the tables in this module are speech-recognition vocabulary, the
# literal German words the rules need to read German sentences. Matching data,
# not prose.

_TOKEN_RE = re.compile(r"\w+(?:['’]\w+)*", re.UNICODE)
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_END_MARKS = ".!?…"
_CLOSING_MARKS = "\"'»«“”’)]"
_CLAUSE_SPLIT_RE = re.compile(r"[,;:–—]")

#: Words after which no sentence ends, in any language a dictation is read in.
#: None of them is a word of another served language that could end one.
_NEVER_LAST_ANY: frozenset[str] = frozenset(
    {
        "the", "and", "nor", "than", "because", "although", "whether", "unless",
        "my", "your", "our", "their",
        "und", "oder", "sondern", "dass", "weil", "obwohl", "sodass",  # i18n-allow
        "beziehungsweise", "bzw",  # i18n-allow
    }
)

#: Words after which no sentence of the language ends. Left out on purpose:
#: German prepositions that are also verb particles (they end a sentence the
#: way "up" ends "I call you up"), German articles and determiners that are
#: also pronouns ("I like that"), and English prepositions, which may end an
#: English sentence ("what it is made of").
_NEVER_LAST: dict[str, frozenset[str]] = {
    "de": _NEVER_LAST_ANY
    | frozenset(
        {
            "des", "zum", "zur", "im", "am", "beim", "vom", "ins", "ans",  # i18n-allow
            "für", "von", "zwischen", "trotz", "seit", "gegen",  # i18n-allow
            "mein", "dein", "unser", "euer",  # i18n-allow
            "meinem", "deinem", "seinem", "ihrem", "unserem", "eurem", "diesem",  # i18n-allow
            "obgleich", "wenn", "falls", "sobald", "nachdem", "bevor", "indem",  # i18n-allow
            "als", "sowie", "sowohl", "weder", "entweder", "ob", "sofern",  # i18n-allow
        }
    ),
    "en": _NEVER_LAST_ANY
    | frozenset({"a", "an", "or", "but", "its", "very", "every", "as"}),
}

# --- German clauses that put their verb last ------------------------------- #

#: Conjunctions that open a German clause with its verb at the end.
_DE_SUBORDINATORS: frozenset[str] = frozenset(
    {
        "dass", "weil", "obwohl", "obgleich", "obschon", "ob", "wenn", "falls",  # i18n-allow
        "sobald", "nachdem", "bevor", "ehe", "indem", "sodass", "damit",  # i18n-allow
        "wobei", "sofern", "seitdem", "solange",  # i18n-allow
    }
)
#: Words that open such a clause only when a pronoun follows them: each has
#: another use (a comparison, a preposition, a question of its own).
_DE_SUBORDINATORS_BEFORE_PRONOUN: frozenset[str] = frozenset(
    {
        "wie", "als", "bis", "seit", "während", "wo", "warum", "weshalb",  # i18n-allow
        "wieso", "was", "wer", "wem", "wen",  # i18n-allow
    }
)
#: Relative pronouns that are nothing else after a comma.
_DE_RELATIVES: frozenset[str] = frozenset(
    {
        "deren", "dessen", "denen", "welche", "welcher", "welches", "welchen",  # i18n-allow
        "welchem",  # i18n-allow
    }
)
#: Relative pronouns that are articles as well; they count before a pronoun.
_DE_ARTICLE_RELATIVES: frozenset[str] = frozenset(
    {"der", "die", "das", "den", "dem"}  # i18n-allow
)
#: Prepositions that may stand before a relative pronoun ("in which").
_DE_PREPOSITIONS: frozenset[str] = frozenset(
    {
        "in", "mit", "an", "auf", "bei", "von", "zu", "für", "über", "unter",  # i18n-allow
        "aus", "nach", "durch", "um", "gegen", "ohne", "vor", "hinter",  # i18n-allow
        "neben", "zwischen", "wegen", "trotz", "seit", "während",  # i18n-allow
    }
)
_DE_PRONOUNS: frozenset[str] = frozenset(
    {
        "ich", "du", "er", "sie", "es", "wir", "ihr", "man", "mir", "mich",  # i18n-allow
        "dir", "dich", "uns", "euch", "ihm", "ihn", "ihnen", "sich",  # i18n-allow
        "jemand", "niemand",  # i18n-allow
    }
)
#: Finite verbs common enough to tell a clause that keeps its verb in second
#: place, as spoken German often does after "weil" or a comma.
_DE_FINITE: frozenset[str] = frozenset(
    {
        "ist", "sind", "war", "waren", "bin", "bist", "seid", "hat", "haben",  # i18n-allow
        "hatte", "hatten", "habe", "hast", "wird", "werden", "wurde", "wurden",  # i18n-allow
        "kann", "können", "muss", "müssen", "soll", "sollen", "will", "wollen",  # i18n-allow
        "darf", "gibt", "geht", "macht", "kommt", "steht", "heißt", "weiß",  # i18n-allow
    }
)
#: Verb forms that do not end like most German verbs do (in -n, -t or -e).
_DE_IRREGULAR_VERBS: frozenset[str] = frozenset(
    {
        "war", "sind", "wird", "seid", "muss", "will", "soll", "darf", "mag",  # i18n-allow
        "weiß", "gab", "kam", "nahm", "sah", "las", "aß", "blieb", "schrieb",  # i18n-allow
        "fand", "stand", "verstand", "entstand", "bestand", "ging", "fing",  # i18n-allow
        "hing", "gelang", "ließ", "hieß", "saß", "vergaß", "schloss",  # i18n-allow
        "beschloss", "lief", "rief", "half", "warf", "traf", "starb", "fuhr",  # i18n-allow
        "erfuhr", "verlor", "zog", "flog", "trug", "schlug", "lag", "sprach",  # i18n-allow
        "brach", "fiel", "gefiel", "stieg", "schwieg", "wuchs", "trank",  # i18n-allow
        "sank", "glich", "verglich", "bewies", "lieh", "mied", "wusch",  # i18n-allow
    }
)
#: Words that close a German clause by coordinating a new one; past one of
#: them the rule cannot tell which clause the last word belongs to.
_DE_COORDINATORS: frozenset[str] = frozenset(
    {"und", "oder", "aber", "sondern", "denn"}  # i18n-allow
)
#: Determiners after which a German word is a noun, not a verb.
_DE_DETERMINERS: frozenset[str] = frozenset(
    {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen",  # i18n-allow
        "einem", "einer", "eines", "kein", "keine", "keinen", "keinem",  # i18n-allow
        "diese", "dieser", "dieses", "diesen", "diesem", "mein", "meine",  # i18n-allow
        "meinen", "dein", "deine", "unser", "unsere", "ihre", "seine",  # i18n-allow
        "irgendwelche", "welche", "jede", "jeder", "jedes", "alle",  # i18n-allow
    }
)

# --- Sentences that carry on the one before -------------------------------- #

#: Words a short sentence of its own starts with: replies, greetings,
#: closings, thanks. "Thanks." or "Exactly." after a pause is a sentence; any
#: other one or two words after one are most likely the rest of the last.
_REPLY_WORDS: frozenset[str] = frozenset(
    {
        "yes", "no", "yeah", "yep", "nope", "sure", "okay", "ok", "great",
        "perfect", "right", "exactly", "fine", "good", "cool", "nice", "thanks",
        "thank", "cheers", "hello", "hi", "hey", "bye", "see", "best", "kind",
        "regards", "sorry", "absolutely", "agreed", "correct", "done", "wow",
        "ja", "nein", "genau", "danke", "dankeschön", "gut", "super", "perfekt",  # i18n-allow
        "prima", "klar", "stimmt", "richtig", "hallo", "tschüss", "servus",  # i18n-allow
        "moin", "bitte", "alles", "viele", "liebe", "beste", "schöne", "bis",  # i18n-allow
        "entschuldigung", "naja", "egal", "schade", "ach", "oh", "aha",  # i18n-allow
        "achso", "passt", "fertig", "erledigt", "toll", "spitze", "jawohl",  # i18n-allow
        "punkt", "erstens", "zweitens", "drittens", "first", "second", "third",  # i18n-allow
        "finally", "next", "also", "außerdem", "abschließend", "zuletzt",  # i18n-allow
    }
)
#: Conjunctions that open a clause which cannot stand alone; a sentence that is
#: nothing but such a clause (no comma, so no main clause after it) carries on
#: the sentence before.
_CLAUSE_ONLY_OPENERS: dict[str, frozenset[str]] = {
    "de": frozenset(
        {
            "dass", "weil", "obwohl", "obgleich", "wobei", "wenn", "falls",  # i18n-allow
            "sodass", "nachdem", "sobald", "indem",  # i18n-allow
        }
    ),
    "en": frozenset({"because", "although", "though", "unless", "whereas", "which"}),
}
#: Relative pronouns that open a sentence only when it is a question.
_RELATIVE_OPENERS: dict[str, frozenset[str]] = {
    "de": _DE_RELATIVES,
    "en": frozenset({"which", "whose", "whom"}),
}

#: How many words a sentence of its own needs unless it is a reply.
_FRAGMENT_MAX_WORDS = 2
#: How many words, at most, the rest of a broken sentence may have for
#: :func:`joinable_tail` to put the two halves back together.
_TAIL_MAX_WORDS = 3


def _code(language: str | None) -> str:
    code = normalize_language(language)
    return code if code in ("de", "en") else ""


def _body(sentence: str) -> str:
    """The sentence without its closing marks and end mark."""
    return sentence.strip().rstrip(_CLOSING_MARKS).rstrip(_END_MARKS).rstrip(_CLOSING_MARKS).strip()


def _end_mark(sentence: str) -> str:
    tail = sentence.strip().rstrip(_CLOSING_MARKS)
    return tail[-1:] if tail[-1:] in _END_MARKS else ""


def words_of(text: str) -> list[str]:
    """The words of ``text`` in their written case, numbers included."""
    return _TOKEN_RE.findall(text or "")


def _verb_like(word: str) -> bool:
    """Whether a lower-case German word can be a verb form at a clause end.

    German infinitives, participles and most finite forms end in -n, -t or -e
    ("entstehen", "gemacht", "hatte"); the rest are listed. Generous on
    purpose: a word taken for a verb only means the clause counts as finished.
    """
    if not word or not word[:1].islower():
        return False
    return word.endswith(("n", "t", "e")) or word in _DE_IRREGULAR_VERBS


def _german_clause_open(body: str) -> bool:
    """Whether the last clause of a German sentence still waits for its verb.

    The clause is the part after the last comma. It is a verb-last clause
    when it opens with a subordinating conjunction, a relative pronoun or a
    preposition before one; such a clause that ends in a noun (a capital in
    the middle of a German sentence), a number or a word that cannot be a
    verb form has not ended yet. Past a coordinating conjunction the rule
    cannot tell which clause the last word closes, and says nothing.
    """
    segments = _CLAUSE_SPLIT_RE.split(body)
    words = words_of(segments[-1])
    if len(words) < 2:
        return False
    after_comma = len(segments) > 1
    low = [w.casefold() for w in words]
    first, second = low[0], low[1]
    if first in _DE_SUBORDINATORS:
        opener = 1
    elif after_comma and first in _DE_RELATIVES:
        opener = 1
    elif after_comma and first in _DE_ARTICLE_RELATIVES and second in _DE_PRONOUNS:
        opener = 1
    elif after_comma and first in _DE_SUBORDINATORS_BEFORE_PRONOUN and second in _DE_PRONOUNS:
        opener = 1
    elif (
        after_comma
        and first in _DE_PREPOSITIONS
        and (
            second in _DE_RELATIVES
            or (second in _DE_ARTICLE_RELATIVES and len(low) > 2 and low[2] in _DE_PRONOUNS)
        )
    ):
        opener = 2
    else:
        return False
    rest = low[opener:]
    if not rest:
        return False
    if any(word in _DE_COORDINATORS for word in rest):
        return False
    # Spoken German often keeps the verb in second place after a conjunction
    # like "because": a common finite verb right after the opener is that verb.
    if any(word in _DE_FINITE for word in rest[:2]) and low[-1] not in _DE_FINITE:
        return False
    last = words[-1]
    if last[:1].isdigit():
        return True
    if not _LETTER_RE.match(last):
        return False
    if last[:1].isupper():
        # A capital in the middle of a German sentence is a noun or a name.
        return True
    return not _verb_like(last)


def unfinished(sentence: str, *, language: str | None = None) -> str:
    """Why ``sentence`` cannot be the end of a sentence, or ``""``.

    ``"dangling"``: its last word is one no sentence ends with.
    ``"open_clause"``: a German clause in it still waits for its verb.

    Only a full stop (or no mark at all) is judged: a question or an
    exclamation mark is a choice the recognizer made on purpose.
    """
    if _end_mark(sentence) in ("?", "!"):
        return ""
    body = _body(sentence)
    if not body or body.endswith((",", ";", ":")):
        return "dangling" if body else ""
    words = words_of(body)
    if not words:
        return ""
    code = _code(language)
    last = words[-1].casefold()
    if last in _NEVER_LAST.get(code, _NEVER_LAST_ANY):
        return "dangling"
    if code == "de" and _german_clause_open(body):
        return "open_clause"
    return ""


def continues_previous(sentence: str, *, language: str | None = None) -> str:
    """Why ``sentence`` only carries on the sentence before it, or ``""``.

    ``"lower_case"``: it starts in lower case, so the recognizer itself read
    it as the rest of a sentence. ``"fragment"``: one or two words that are
    not a reply, a greeting or a closing. ``"clause_only"``: a subordinate or
    relative clause with no main clause.
    """
    body = _body(sentence)
    words = words_of(body)
    if not words:
        return ""
    first = words[0]
    if first[:1].isalpha() and first[:1].islower():
        return "lower_case"
    low = [w.casefold() for w in words]
    if len(words) <= _FRAGMENT_MAX_WORDS and low[0] not in _REPLY_WORDS:
        return "fragment"
    if _end_mark(sentence) == "?":
        return ""
    code = _code(language)
    if not code:
        return ""
    if code == "de" and len(low) > 1 and low[1] in _DE_FINITE:
        # A finite verb in second place makes it a main clause, not a relative one.
        return ""
    if low[0] in _RELATIVE_OPENERS[code]:
        if code == "en" or (len(low) > 1 and low[1] in _DE_PRONOUNS):
            return "clause_only"
    if low[0] in _CLAUSE_ONLY_OPENERS[code] and "," not in body:
        return "clause_only"
    return ""


def joinable_tail(before: str, after: str, *, language: str | None = None) -> bool:
    """Whether ``after`` is the rest of ``before``, cut off by a pause.

    True only when ``before`` is unfinished and ``after`` is a short tail
    that closes it: at most a few words and not a reply. Such a pair is one
    sentence the recognizer split at the speaker's pause, and the full stop
    between them is put back as a space.
    """
    if not unfinished(before, language=language):
        return False
    words = words_of(_body(after))
    if not words or len(words) > _TAIL_MAX_WORDS:
        return False
    if words[0].casefold() in _REPLY_WORDS:
        return False
    # A question or an exclamation is a sentence the speaker meant.
    return _end_mark(after) not in ("?", "!")


def lowered_tail_start(before: str, after: str, *, language: str | None = None) -> bool:
    """Whether the first word of a joined tail loses its capital.

    The recognizer gave it a capital only because it took the word for the
    start of a sentence. A German noun keeps its capital, so the word is put
    in lower case only when it is a word that is never a noun: one of the
    listed function words, or the verb that closes an open German clause
    (it ends like a verb and no article stands before it).
    """
    words = words_of(_body(after))
    if not words or not words[0][:1].isupper():
        return False
    first = words[0].casefold()
    if first in _FUNCTION_WORDS:
        return True
    if _code(language) != "de" or unfinished(before, language=language) != "open_clause":
        return False
    previous = words_of(_body(before))
    if previous and previous[-1].casefold() in _DE_DETERMINERS:
        return False
    return len(words) <= _FRAGMENT_MAX_WORDS and first.endswith(("en", "ern", "eln", "t"))


#: Words that are never nouns, so a capital on one of them inside a sentence
#: was only the recognizer's sentence start.
_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "and", "but", "or", "so", "then", "that", "which", "because", "if",
        "when", "the", "a", "an", "to", "of", "in", "on", "at", "for", "with",
        "it", "we", "you", "they", "he", "she", "is", "are", "was", "were",
        "und", "oder", "aber", "dann", "da", "dass", "weil", "wenn", "ob",  # i18n-allow
        "wie", "wo", "der", "die", "das", "den", "dem", "ein", "eine",  # i18n-allow
        "einen", "einem", "einer", "zu", "zum", "zur", "im", "mit", "auf",  # i18n-allow
        "am", "für", "von", "bei", "nach", "ich", "du", "er", "es", "wir",  # i18n-allow
        "ihr", "man", "mir", "mich", "dir", "dich", "uns", "sich", "ist",  # i18n-allow
        "sind", "war", "hat", "haben", "wird", "werden", "kann", "können",  # i18n-allow
        "muss", "soll", "noch", "schon", "auch", "nur", "nicht", "also", "ja",  # i18n-allow
        "eben", "halt", "doch", "mal",  # i18n-allow
    }
)


__all__ = [
    "continues_previous",
    "joinable_tail",
    "lowered_tail_start",
    "unfinished",
    "words_of",
]
