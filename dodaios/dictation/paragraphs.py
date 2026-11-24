"""Where the paragraphs of a dictation go.

A paragraph holds one thought. German and English writing agree on what that
means, from school grammars and DIN 5008 for German letters to the common
English style guides, and this module follows those rules:

1. **A paragraph ends with a finished sentence**, never inside one. A full
   stop the recognizer wrote at a pause in the middle of a sentence is not
   the end of one (:mod:`dodaios.dictation.grammar`).
2. **A new paragraph starts where the text turns to a new point**: another
   topic, the next item of a counted line of thought, a conclusion, a turn
   against what came before. Words at the start of a sentence say so
   (:data:`_OPENERS`, "Another thing", "Second", "Finally", "However").
3. **A sentence that leans on the one before does not start one**: a word
   pointing back ("This", "That is why"), a consequence ("So", "Therefore"),
   an example ("For example").
4. **A paragraph is a few sentences long.** One short sentence is not a
   paragraph, and a block of ten is a wall.

A dictation has one cue writing does not have: the speaker stopping for a
while between two sentences. :func:`format_dictation
<dodaios.dictation.formatting.format_dictation>` marks where the reading of
the recording found such a pause with :data:`LONG_PAUSE`.

The planner (:func:`auto_paragraphs`) gives every sentence boundary a score
from its cues, every possible paragraph a cost from its length, and picks the
breaks with the lowest total, over each block of the dictation at once. A
break therefore lands at the best boundary near where one is needed, not at
the first sentence end past a word count, and never at a boundary rule 1
rules out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dodaios.dictation.cleanup import count_words, normalize_language
from dodaios.dictation.grammar import (
    continues_previous,
    joinable_tail,
    lowered_tail_start,
    unfinished,
    words_of,
)

# i18n-allow: the opener tables in this module are speech-recognition
# vocabulary, the literal words a matcher needs to read German speech.

#: Stands between two sentences where the speaker paused for a while. Never
#: delivered: :func:`auto_paragraphs` turns each into a break or a space.
LONG_PAUSE = "\u2029"

#: A dictation shorter than this stays one paragraph: a chat message of a few
#: sentences reads better without breaks.
PARAGRAPH_MIN_WORDS = 50

# --- What a paragraph's length costs ---------------------------------------- #

#: A paragraph of this many words and fewer begins to cost: it is short.
_SHORT_WORDS = 35
_SHORT_SCALE = 10.0
#: Past this many words a paragraph begins to cost: it is long, and from
#: about 120 words on a wall on a screen.
_LONG_WORDS = 80
_LONG_SCALE = 20.0
#: A paragraph of one sentence costs this on top, unless the sentence is long.
_ONE_SENTENCE_COST = 0.75
_ONE_SENTENCE_LONG_WORDS = 30
#: What a break costs before its cues pay for it.
_BREAK_COST = 1.25

# --- What a boundary's cues are worth --------------------------------------- #

#: The speaker stopped for a while between the two sentences.
_PAUSE_WORTH = 2.5
#: The sentence after the boundary opens a new point.
_TOPIC_WORTH = 2.0
#: It changes the subject the way speech does ("Okay, ..."), or turns from
#: telling to asking ("Could you ...").
_PIVOT_WORTH = 1.0
#: It turns against the sentence before.
_CONTRAST_WORTH = 0.5
#: It leans on the sentence before.
_TIE_WORTH = -1.5
#: It goes on with "and" or "then".
_WEAK_TIE_WORTH = -0.75

#: Sentence openers by what they say about the boundary before them, per
#: language, matched on the lower-case start of a sentence; the longest match
#: decides.
_OPENERS: dict[str, dict[str, tuple[str, ...]]] = {
    "de": {
        "topic": (  # i18n-allow: input vocabulary
            "außerdem", "ausserdem", "zudem", "darüber hinaus", "des weiteren",  # i18n-allow
            "weiterhin", "zusätzlich", "hinzu kommt", "dazu kommt",  # i18n-allow
            "erstens", "zweitens", "drittens", "viertens", "fünftens",  # i18n-allow
            "zum einen", "zum anderen", "als erstes", "als zweites",  # i18n-allow
            "als nächstes", "zuerst", "zunächst", "punkt eins", "punkt zwei",  # i18n-allow
            "punkt drei", "nächster punkt", "neuer punkt", "ein weiterer punkt",  # i18n-allow
            "ein anderes thema", "anderes thema", "zum thema", "ein weiteres",  # i18n-allow
            "eine weitere", "ein weiterer", "noch etwas", "noch was",  # i18n-allow
            "noch eine sache", "eine andere sache", "eine sache noch", "was noch",  # i18n-allow
            "dann noch", "kommen wir", "jetzt zu", "nun zu", "jetzt noch",  # i18n-allow
            "abschließend", "zum schluss", "zuletzt", "schließlich",  # i18n-allow
            "zusammenfassend", "zusammengefasst", "alles in allem", "insgesamt",  # i18n-allow
            "fazit", "kurz gesagt", "unterm strich", "übrigens", "ansonsten",  # i18n-allow
            "generell", "grundsätzlich", "wichtig ist", "ganz wichtig",  # i18n-allow
            "was mir wichtig ist", "vor allem", "vor allen dingen",  # i18n-allow
            "deine aufgabe", "die aufgabe", "meine frage", "eine frage",  # i18n-allow
            "die frage ist", "das ziel", "ziel ist", "mein ziel",  # i18n-allow
            "zum hintergrund", "bezüglich",  # i18n-allow
        ),
        "pivot": (  # i18n-allow: input vocabulary
            "okay", "ok", "alles klar", "also gut", "gut, dann", "ich möchte",  # i18n-allow
            "ich will", "ich würde gern", "ich würde gerne", "ich hätte gern",  # i18n-allow
            "ich hätte gerne", "ich wünsche mir", "kannst du", "könntest du",  # i18n-allow
            "bitte", "meine bitte",  # i18n-allow
        ),
        "contrast": (  # i18n-allow: input vocabulary
            "aber", "allerdings", "jedoch", "andererseits", "auf der anderen seite",  # i18n-allow
            "dennoch", "hingegen", "trotzdem", "im gegenteil",  # i18n-allow
        ),
        "tie": (  # i18n-allow: input vocabulary
            "dies", "diese", "dieser", "dieses", "diesen", "dadurch", "daher",  # i18n-allow
            "darum", "deshalb", "deswegen", "dafür", "dabei", "damit", "davon",  # i18n-allow
            "denn", "nämlich", "sprich", "somit", "folglich", "insofern",  # i18n-allow
            "zum beispiel", "beispielsweise", "das heißt", "also", "und zwar",  # i18n-allow
            "genauso", "ebenso", "sonst", "stattdessen", "es sei denn",  # i18n-allow
        ),
        "weak_tie": ("und", "oder", "dann", "und dann", "so"),  # i18n-allow
    },
    "en": {
        "topic": (
            "also", "additionally", "moreover", "furthermore", "besides",
            "in addition", "first", "firstly", "first of all", "second",
            "secondly", "third", "thirdly", "fourth", "to begin with",
            "to start with", "next", "finally", "lastly", "last but not least",
            "in summary", "to sum up", "in conclusion", "all in all", "overall",
            "in short", "another", "one more thing", "the other thing",
            "on another note", "by the way", "anyway", "apart from that",
            "other than that", "aside from that", "speaking of", "regarding",
            "as for", "moving on", "the next point", "my question",
            "the question is", "your task", "the task is", "the goal",
            "the problem is", "here's the thing", "above all", "most importantly",
        ),
        "pivot": (
            "okay", "ok", "alright", "all right", "i want you to", "i'd like you to",
            "i would like you to", "i need you to", "please", "can you", "could you",
        ),
        "contrast": (
            "however", "but", "on the other hand", "that said", "nevertheless",
            "nonetheless", "in contrast", "conversely", "on the contrary",
        ),
        "tie": (
            "this", "that", "these", "those", "it", "it's", "therefore", "thus",
            "hence", "because", "since", "for example", "for instance", "e.g",
            "that is", "i.e", "in other words", "as a result", "consequently",
            "otherwise", "instead", "which", "plus",
        ),
        "weak_tie": ("and", "or", "then", "and then", "so"),
    },
}

#: German words that point back only as a pronoun, before a verb; before a
#: noun they are its article ("the problem is ...") and say nothing.
_DE_POINTING_ARTICLES = frozenset({"das", "der", "die", "den", "dem"})  # i18n-allow
_DE_POINTING_ARTICLE_TIE = "pointing_back"

_WORTH: dict[str, float] = {
    "topic": _TOPIC_WORTH,
    "pivot": _PIVOT_WORTH,
    "contrast": _CONTRAST_WORTH,
    "tie": _TIE_WORTH,
    "weak_tie": _WEAK_TIE_WORTH,
    _DE_POINTING_ARTICLE_TIE: _TIE_WORTH,
}


def _merged_openers() -> dict[str, tuple[str, ...]]:
    """The openers of every language, for a dictation of unknown language.

    An opener that means something else in another language ("also" opens a
    new point in English and a consequence in German) is left out.
    """
    kinds: dict[str, set[str]] = {}
    for table in _OPENERS.values():
        for kind, openers in table.items():
            kinds.setdefault(kind, set()).update(openers)
    seen: dict[str, int] = {}
    for openers in kinds.values():  # type: ignore[assignment]
        for opener in openers:
            seen[opener] = seen.get(opener, 0) + 1
    return {
        kind: tuple(sorted(o for o in openers if seen[o] == 1))
        for kind, openers in kinds.items()
    }


_ANY_LANGUAGE_OPENERS = _merged_openers()

# --- Sentences -------------------------------------------------------------- #

#: Words that end in a full stop without ending a sentence.
_ABBREVIATIONS = frozenset(
    {
        "dr", "prof", "hr", "fr", "nr", "st", "bzw", "ca", "usw", "vgl", "etc",
        "inkl", "ggf", "evtl", "zb", "mr", "mrs", "ms", "vs", "eg", "ie", "no",
        "abs", "str", "tel", "bspw", "sog", "u", "z", "b", "d", "h", "e", "i",
    }
)
_SENTENCE_END_RE = re.compile(r"[.!?…]+[\"'”»)]*(?=\s|$)")
_WORD_BEFORE_RE = re.compile(r"([^\W\d_]+)\.?$")
_LONG_PAUSE_RE = re.compile(r"[ \t]*" + LONG_PAUSE + r"[ \t]*")
_LEADING_QUOTES = "\"'„“”»«‚‘’(["


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of the sentences of ``text``, in order.

    A sentence ends at ``.``, ``!`` or ``?`` followed by a space or the end,
    except after a known abbreviation or a single letter ("z. B.", "Dr.").
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        end = match.end()
        if match.group(0).startswith("."):
            before = _WORD_BEFORE_RE.search(text[start : match.start()])
            word = before.group(1).casefold() if before else ""
            if word in _ABBREVIATIONS or len(word) == 1:
                continue
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def break_before_sentences(text: str, indices: set[int] | frozenset[int]) -> str:
    """``text`` with a blank line before every sentence whose index is listed.

    Index 0 (the first sentence) and indices past the end are ignored.
    """
    spans = sentence_spans(text)
    wanted = sorted(i for i in indices if 0 < i < len(spans))
    if not wanted:
        return text
    out: list[str] = []
    cursor = 0
    for index in wanted:
        start = spans[index][0]
        out.append(text[cursor:start].rstrip())
        out.append("\n\n")
        cursor = start
        while cursor < len(text) and text[cursor] in " \t":
            cursor += 1
    out.append(text[cursor:])
    return "".join(out)


# --- Cues --------------------------------------------------------------------- #


def _opener_length(low: str, opener: str) -> int:
    if low.startswith(opener) and (len(low) == len(opener) or not low[len(opener)].isalnum()):
        return len(opener)
    return 0


def _opener_kind(sentence: str, language: str | None) -> str:
    """What the start of ``sentence`` says about the boundary before it."""
    code = normalize_language(language)
    table = _OPENERS.get(code or "", _ANY_LANGUAGE_OPENERS)
    low = " ".join(sentence.strip().lstrip(_LEADING_QUOTES).casefold().split())
    best_kind, best_length = "", 0
    for kind, openers in table.items():
        for opener in openers:
            length = _opener_length(low, opener)
            if length > best_length:
                best_kind, best_length = kind, length
    if best_kind in ("weak_tie", "contrast"):
        # "And another thing", "But first": the opener after the joining
        # word says what the sentence does.
        rest = low[best_length:].lstrip(" ,")
        for opener in table.get("topic", ()):
            if _opener_length(rest, opener):
                return "topic"
    if not best_kind and code == "de":
        words = words_of(sentence)
        if (
            len(words) > 1
            and words[0].casefold() in _DE_POINTING_ARTICLES
            and words[1][:1].islower()
        ):
            return _DE_POINTING_ARTICLE_TIE
    return best_kind


@dataclass(frozen=True, slots=True)
class _Boundary:
    """The boundary before one sentence."""

    allowed: bool
    worth: float


def _length_cost(words: int, sentences: int) -> float:
    cost = 0.0
    if words < _SHORT_WORDS:
        cost += ((_SHORT_WORDS - words) / _SHORT_SCALE) ** 2
    elif words > _LONG_WORDS:
        cost += ((words - _LONG_WORDS) / _LONG_SCALE) ** 2
    if sentences == 1 and words < _ONE_SENTENCE_LONG_WORDS:
        cost += _ONE_SENTENCE_COST
    return cost


def _plan(words: list[int], boundaries: list[_Boundary]) -> list[int]:
    """The sentence indices to break before, for the lowest total cost.

    ``boundaries[i]`` is the boundary before sentence ``i`` (index 0 unused).
    """
    count = len(words)
    prefix = [0]
    for number in words:
        prefix.append(prefix[-1] + number)
    best = [float("inf")] * (count + 1)
    back = [0] * (count + 1)
    best[0] = 0.0
    for end in range(1, count + 1):
        for start in range(end):
            if start > 0 and not boundaries[start].allowed:
                continue
            cost = best[start] + _length_cost(prefix[end] - prefix[start], end - start)
            if start > 0:
                cost += _BREAK_COST - boundaries[start].worth
            if cost < best[end] - 1e-9:
                best[end] = cost
                back[end] = start
    breaks: list[int] = []
    end = count
    while end > 0:
        start = back[end]
        if start > 0:
            breaks.append(start)
        end = start
    return sorted(breaks)


def _join(before: str, after: str, language: str | None) -> str:
    """Two halves of a sentence split at a pause, as one sentence again."""
    head = before.rstrip()
    closing = ""
    while head and head[-1] in "\"'”»)":
        closing = head[-1] + closing
        head = head[:-1]
    head = head.rstrip(".…").rstrip() + closing
    tail = after.strip()
    if lowered_tail_start(before, after, language=language):
        tail = tail[:1].lower() + tail[1:]
    return f"{head} {tail}"


def _plan_block(block: str, *, language: str | None, plan: bool) -> tuple[str, int]:
    """One block of a dictation (no spoken break inside) with its paragraphs."""
    if LONG_PAUSE not in block and not plan:
        return block, 0
    spans = sentence_spans(block)
    pieces = [block[a:b] for a, b in spans]
    sentences: list[str] = []
    paused: list[bool] = []
    for piece in pieces:
        lead = piece[: len(piece) - len(piece.lstrip())]
        text = _LONG_PAUSE_RE.sub(" ", piece).strip()
        if not text:
            continue
        pause = LONG_PAUSE in lead
        if sentences and pause and joinable_tail(sentences[-1], text, language=language):
            # The speaker stopped in the middle of a sentence, and the
            # recognizer closed it there.
            sentences[-1] = _join(sentences[-1], text, language)
            continue
        sentences.append(text)
        paused.append(pause)
    if not sentences:
        return _LONG_PAUSE_RE.sub(" ", block).strip(), 0
    words = [count_words(sentence) for sentence in sentences]
    breaks: list[int] = []
    if plan and len(sentences) > 1:
        boundaries = [_Boundary(allowed=False, worth=0.0)]
        for index in range(1, len(sentences)):
            before, sentence = sentences[index - 1], sentences[index]
            allowed = not unfinished(before, language=language) and not continues_previous(
                sentence, language=language
            )
            worth = _PAUSE_WORTH if paused[index] else 0.0
            kind = _opener_kind(sentence, language)
            worth += _WORTH.get(kind, 0.0)
            boundaries.append(_Boundary(allowed=allowed, worth=worth))
        breaks = _plan(words, boundaries)
    paragraphs: list[str] = []
    start = 0
    for index in [*breaks, len(sentences)]:
        paragraphs.append(" ".join(sentences[start:index]))
        start = index
    return "\n\n".join(paragraphs), len(breaks)


def auto_paragraphs(
    text: str, *, language: str | None = None, plan: bool = True
) -> tuple[str, int]:
    """Lay a dictation out in paragraphs; returns the text and how many breaks.

    ``text`` may hold blank lines (paragraphs spoken as a command, kept as
    they are), single line breaks (a spoken list: its block is left alone)
    and :data:`LONG_PAUSE` between two sentences where the speaker paused.
    Every pause mark is gone from what comes back.

    A sentence the recognizer split at a pause is put back together first
    (:func:`dodaios.dictation.grammar.joinable_tail`). With ``plan`` off, or
    for a dictation under :data:`PARAGRAPH_MIN_WORDS` words, nothing else
    changes; otherwise each block gets the breaks the planner finds.
    """
    source = text or ""
    if not source.strip():
        return _LONG_PAUSE_RE.sub(" ", source).strip(), 0
    planned = plan and count_words(source) >= PARAGRAPH_MIN_WORDS
    made = 0
    out: list[str] = []
    for block in source.split("\n\n"):
        if "\n" in block:
            out.append(_LONG_PAUSE_RE.sub(" ", block).strip())
            continue
        laid_out, breaks = _plan_block(block, language=language, plan=planned)
        out.append(laid_out)
        made += breaks
    return "\n\n".join(part for part in out if part), made


__all__ = [
    "PARAGRAPH_MIN_WORDS",
    "LONG_PAUSE",
    "auto_paragraphs",
    "break_before_sentences",
    "sentence_spans",
]
