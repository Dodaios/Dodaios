"""Turn what the recognizer heard into the text a dictation delivers.

Rules only: no model call happens in this module, so the same words always
come out the same way and every change can be read from the rule that made it.

What the rules do, in order:

1. **Pause marks go.** A recognizer writes ``...`` or ``…`` where the speaker
   paused or hesitated. Nobody dictates three dots, so none are delivered: a
   pause inside a sentence becomes a space, a pause before a new sentence
   becomes a full stop.
2. **Spoken layout commands become layout.** "new paragraph" / "neuer Absatz"
   is a blank line, "new line" / "neue Zeile" is a line break. A phrase that
   is being talked about ("add a new line") stays as words.
3. **Hesitation sounds go** (``fillers``), from the short list per language
   in :mod:`dodaios.dictation.cleanup`.
4. **Punctuation and capitals are repaired** where the steps above left a
   seam: doubled marks, a space before a full stop, a sentence or line whose
   first word lost its capital to a removed sound or a command.
5. **A long dictation gets paragraphs** (``paragraphs``): where the speaker
   stopped for a while between two sentences (found while the recording was
   read, see :mod:`dodaios.dictation.take`), before a sentence that opens a
   new topic, and at a sentence end once a paragraph has grown long.

Every step keeps the words. When a rule would remove more than hesitation
sounds can explain, the step is skipped and the text passes through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dodaios.dictation.cleanup import (
    FILLER_WORDS,
    SUPPORTED_LANGUAGES,
    count_words,
    normalize_language,
)

# i18n-allow: the tables in this module are speech-recognition vocabulary, the
# literal words a matcher needs to recognise German, Spanish or Portuguese
# speech. Matching data, not prose.

#: Spoken phrases that mean "blank line". Matched in every dictation whatever
#: language was detected: none of them is a phrase of another language.
PARAGRAPH_COMMANDS: tuple[str, ...] = (
    "new paragraph",
    "next paragraph",
    "start a new paragraph",
    "neuer absatz",  # i18n-allow: input vocabulary
    "nächster absatz",  # i18n-allow: input vocabulary
    "neuen absatz",  # i18n-allow: input vocabulary
    "nuevo párrafo",  # i18n-allow: input vocabulary
    "nuevo parrafo",
    "novo parágrafo",  # i18n-allow: input vocabulary
    "novo paragrafo",
)

#: Spoken phrases that mean "line break".
LINE_COMMANDS: tuple[str, ...] = (
    "new line",
    "next line",
    "newline",
    "line break",
    "neue zeile",  # i18n-allow: input vocabulary
    "nächste zeile",  # i18n-allow: input vocabulary
    "zeilenumbruch",  # i18n-allow: input vocabulary
    "nueva línea",  # i18n-allow: input vocabulary
    "nueva linea",
    "nova linha",
)

# A word in front of the phrase that makes it something the speaker talks
# ABOUT ("add a new line", "in der neuen Zeile") rather than a command.
_TALKED_ABOUT_BEFORE = (
    "a", "an", "the", "this", "that", "each", "every", "per", "one",
    # i18n-allow: input vocabulary
    "ein", "eine", "einen", "einer", "einem", "der", "die", "den", "dem",  # i18n-allow
    "diese", "dieser", "diesen", "jede", "jeder", "jeden", "pro", "kein",  # i18n-allow
    "keine", "una", "la", "cada", "uma",  # i18n-allow: input vocabulary
)

_WORD_RE = re.compile(r"\w+", re.UNICODE)
# "Whole word" spelled out, because ``\b`` misjudges words with non-ASCII
# letters at their edge.
_BEFORE_WORD = r"(?<![^\W\d_])"
_AFTER_WORD = r"(?![^\W\d_])"

_ELLIPSIS = r"(?:\.[ \t]?){3,}|…+|\.\.(?!\.)"
_ELLIPSIS_RE = re.compile(_ELLIPSIS)

#: Lower-case words that start a German or English sentence. After a pause
#: mark, a capital on one of these is a new sentence; a capital on any other
#: word may just be a noun or a name, and the sentence goes on.
_SENTENCE_OPENERS: frozenset[str] = frozenset(
    {
        # English
        "the", "this", "that", "these", "those", "it", "he", "she", "we",
        "you", "they", "there", "then", "and", "but", "so", "or", "if",
        "when", "what", "why", "how", "where", "who", "please", "can",
        "could", "would", "should", "do", "does", "did", "is", "are", "was",
        "let", "now", "also", "because", "maybe", "in", "on", "at", "for",
        "my", "our", "your", "his", "her", "its", "their", "not", "no", "yes",
        # German  # i18n-allow: input vocabulary
        "der", "die", "das", "den", "dem", "ein", "eine", "es", "er", "sie",  # i18n-allow
        "wir", "ihr", "ich", "du", "man", "dann", "und", "aber", "oder",  # i18n-allow
        "wenn", "weil", "dass", "wie", "wo", "wer", "warum", "bitte",  # i18n-allow
        "kannst", "kann", "könnte", "könntest", "soll", "sollte", "ist",  # i18n-allow
        "sind", "war", "jetzt", "außerdem", "vielleicht", "im", "auf", "an",  # i18n-allow
        "für", "mit", "mein", "meine", "unser", "unsere", "dein", "deine",  # i18n-allow
        "nicht", "nein", "ja", "da", "hier", "dort", "noch", "zum", "zur",  # i18n-allow
        "bei", "nach", "vor", "generell", "dazu", "danach", "deshalb",  # i18n-allow
        "trotzdem",
    }
)


@dataclass(frozen=True, slots=True)
class FormatResult:
    """One formatted dictation.

    ``text`` is what is delivered and ``raw`` what the recognizer returned.
    ``filler_reason`` says why no hesitation sound was removed (``""`` when
    the step ran): ``disabled``, ``no_rules``, ``ceiling``, ``empty``, or
    ``error`` when a rule failed and the recognized text was delivered as is.
    """

    text: str
    raw: str
    removed_words: int = 0
    filler_reason: str = ""
    pause_marks: int = 0
    layout_commands: int = 0
    #: Paragraph breaks the rules added (spoken commands not counted).
    paragraphs_made: int = 0


# --------------------------------------------------------------------------- #
# 1. Pause marks
# --------------------------------------------------------------------------- #

# A full stop counts as the mark BEFORE the dots only when a space separates
# the two ("gut. ... Dann"); attached, it is the first of the dots ("gut...").
_PAUSE_RE = re.compile(
    r"(?P<before>[!?,;:]|\.(?=[ \t]+(?:\.|…)))?[ \t]*"
    r"(?P<dots>" + _ELLIPSIS + r")"
    r"[ \t]*(?P<after>[.!?,;:]?)"
)


def strip_pause_marks(text: str) -> tuple[str, int]:
    """Remove every ``...`` / ``…``; returns the text and how many went.

    What replaces a mark depends on what stands around it:

    * a sentence mark right before or after it stays and the dots go;
    * at the end of the text the dots become a full stop;
    * before a lower-case word the speaker hesitated: a space;
    * before a capitalised sentence opener a sentence ended: a full stop;
    * before any other capitalised word (a noun, a name): a space.
    """
    source = text or ""
    if not _ELLIPSIS_RE.search(source):
        return source, 0
    count = 0
    out: list[str] = []
    cursor = 0
    for match in _PAUSE_RE.finditer(source):
        count += 1
        head = source[cursor : match.start()]
        out.append(head)
        cursor = match.end()
        rest = source[cursor:]
        before = match.group("before")
        after = match.group("after")
        written = "".join(out)
        if not written.strip():
            # Dots before the first word: nothing was said yet.
            continue
        if not rest.strip():
            # Dots at the very end: the sentence is over.
            mark = before or after or "."
            out.append(mark if mark in ".!?" else ".")
            continue
        if before or after:
            mark = before or after
            out.append(mark + " ")
            continue
        next_word = _WORD_RE.match(rest)
        word = next_word.group(0) if next_word else ""
        if word[:1].isupper() and word.lower() in _SENTENCE_OPENERS:
            out.append(". ")
        else:
            out.append(" ")
    out.append(source[cursor:])
    return "".join(out), count


# --------------------------------------------------------------------------- #
# 2. Spoken layout commands
# --------------------------------------------------------------------------- #


def _command_pattern(phrases: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(
        r"\s+".join(re.escape(part) for part in phrase.split())
        for phrase in sorted(phrases, key=len, reverse=True)
    )
    return re.compile(
        r"(?P<lead>[ \t]*[,;:.!?]?[ \t]*)"
        + _BEFORE_WORD
        + r"(?P<phrase>"
        + alternatives
        + r")"
        + _AFTER_WORD
        + r"(?P<trail>[ \t]*[,;:.!?]?[ \t]*)",
        re.IGNORECASE | re.UNICODE,
    )


_PARAGRAPH_RE = _command_pattern(PARAGRAPH_COMMANDS)
_LINE_RE = _command_pattern(LINE_COMMANDS)
_LAST_WORD_RE = re.compile(r"(\w+)\W*$", re.UNICODE)


def _apply_command(text: str, pattern: re.Pattern[str], replacement: str) -> tuple[str, int]:
    count = 0
    out: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        head = text[cursor : match.start()]
        lead = match.group("lead")
        written = "".join(out) + head
        # "add a new line here": the phrase is the object of a sentence.
        previous = _LAST_WORD_RE.search(written) if not lead.strip() else None
        if previous is not None and previous.group(1).lower() in _TALKED_ABOUT_BEFORE:
            continue
        count += 1
        out.append(head)
        cursor = match.end()
        # The sentence before the break keeps its own end mark; a weak mark
        # that only led up to the command goes with it.
        mark = lead.strip()
        if mark in (".", "!", "?"):
            out.append(mark)
        if "".join(out).strip():
            out.append(replacement)
    out.append(text[cursor:])
    return "".join(out), count


def apply_layout_commands(text: str) -> tuple[str, int]:
    """Replace spoken paragraph and line commands; returns text and count."""
    source = text or ""
    if not source.strip():
        return source, 0
    out, paragraphs = _apply_command(source, _PARAGRAPH_RE, "\n\n")
    out, lines = _apply_command(out, _LINE_RE, "\n")
    return out, paragraphs + lines


# --------------------------------------------------------------------------- #
# 3. Hesitation sounds
# --------------------------------------------------------------------------- #


def _filler_patterns(language: str) -> list[re.Pattern[str]]:
    words = sorted(FILLER_WORDS[language], key=len, reverse=True)
    return [
        re.compile(
            r"[ \t]*" + _BEFORE_WORD + re.escape(word) + _AFTER_WORD + r"[ \t]*[,]?",
            re.IGNORECASE | re.UNICODE,
        )
        for word in words
    ]


_FILLER_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    language: _filler_patterns(language) for language in FILLER_WORDS
}

# Removing sounds may not cost more words than this. Past it a rule is
# matching something that is not a hesitation, and the text passes through.
_SHORT_TEXT_WORDS = 4
_ABSOLUTE_CAP_WORDS = 12
_ABSOLUTE_MAX_REMOVED = 3

#: Stand where a hesitation sound was until the seam around it is closed:
#: one mark for a sound written in lower case, one for a sound that carried
#: the capital of its sentence ("Ähm, das auch.").  # i18n-allow: input vocabulary
_GAP = "\x00"
_CAPITAL_GAP = "\x01"
_GAP_RE = re.compile("([" + _GAP + _CAPITAL_GAP + r"]+)[ \t]*([^\W\d_])?")


def _mark_gap(match: re.Match[str]) -> str:
    sound = match.group(0).strip(" \t,")
    return _CAPITAL_GAP if sound[:1].isupper() else _GAP


def _close_gaps(text: str) -> str:
    """Replace each gap by a space; the capital of a removed sound moves to
    the word that follows it."""

    def _close(match: re.Match[str]) -> str:
        letter = match.group(2) or ""
        return " " + (letter.upper() if _CAPITAL_GAP in match.group(1) else letter)

    return _GAP_RE.sub(_close, text)


def remove_fillers(
    text: str, *, language: str | None, max_removed_fraction: float = 0.25
) -> tuple[str, int, str]:
    """Drop hesitation sounds; returns ``(text, removed, reason)``."""
    source = text or ""
    if not source.strip():
        return source, 0, "empty"
    code = normalize_language(language)
    if code is None:
        return source, 0, "no_rules"
    total = count_words(source)
    out = source
    for pattern in _FILLER_PATTERNS[code]:
        out = pattern.sub(_mark_gap, out)
    out = _close_gaps(out)
    removed = max(0, total - count_words(out))
    if removed == 0:
        return source, 0, ""
    if not out.strip():
        return source, 0, "ceiling"
    if _SHORT_TEXT_WORDS <= total <= _ABSOLUTE_CAP_WORDS:
        if removed > _ABSOLUTE_MAX_REMOVED:
            return source, 0, "ceiling"
    elif total > _ABSOLUTE_CAP_WORDS and removed / total > max_removed_fraction:
        return source, 0, "ceiling"
    return out, removed, ""


# --------------------------------------------------------------------------- #
# 4. Punctuation and capitals
# --------------------------------------------------------------------------- #

_SPACE_BEFORE_MARK_RE = re.compile(r"[ \t]+([,;]|\.(?!\w))")
_TERMINATOR_THEN_WEAK_RE = re.compile(r"([.!?])[ \t]*[,;:]+")
_WEAK_THEN_MARK_RE = re.compile(r"[,;:][ \t]*([,;:.!?])")
_DOUBLE_TERMINATOR_RE = re.compile(r"([.!?])(?:[ \t]*\.)+")
_SPACES_RE = re.compile(r"[ \t]{2,}")
_SPACE_AT_LINE_EDGE_RE = re.compile(r"[ \t]*\n[ \t]*")
_BLANK_RUN_RE = re.compile(r"\n{3,}")
_LEADING_MARKS_RE = re.compile(r"^[\s,;:.!?\-–—]+")
_WEAK_BEFORE_BREAK_RE = re.compile(r"[,;]+(?=\n)")
_LINE_START_RE = re.compile(r"(\n)([^\W\d_])")


def tidy_punctuation(text: str, *, capitalize_first: bool = True) -> str:
    """Repair doubled marks and stray spaces; a new line starts with a capital.

    Capitals inside a line are left as the recognizer wrote them: a full stop
    is not proof of a sentence end ("ca. zehn Euro"), and the steps that do
    end a sentence set its capital themselves.
    """
    out = text or ""
    if not out.strip():
        return ""
    out = _SPACE_AT_LINE_EDGE_RE.sub("\n", out)
    out = _BLANK_RUN_RE.sub("\n\n", out)
    out = _SPACE_BEFORE_MARK_RE.sub(r"\1", out)
    out = _TERMINATOR_THEN_WEAK_RE.sub(r"\1", out)
    out = _WEAK_THEN_MARK_RE.sub(r"\1", out)
    out = _DOUBLE_TERMINATOR_RE.sub(r"\1", out)
    out = _WEAK_BEFORE_BREAK_RE.sub("", out)
    out = _SPACES_RE.sub(" ", out)
    out = _LEADING_MARKS_RE.sub("", out).strip()
    out = _LINE_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), out)
    if capitalize_first and out[:1].islower():
        out = out[:1].upper() + out[1:]
    return out


# --------------------------------------------------------------------------- #
# The whole pass
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 5. Paragraphs
# --------------------------------------------------------------------------- #

#: A dictation shorter than this stays one paragraph: a chat message of a few
#: sentences reads better without breaks.
PARAGRAPH_MIN_WORDS = 50
#: A paragraph starts at a new topic only once the one before holds this much.
_TOPIC_BREAK_MIN_WORDS = 25
_TOPIC_BREAK_MIN_SENTENCES = 2
#: Without any cue a paragraph is closed at a sentence end once it holds this
#: much, as long as enough text follows to fill the next one.
_LENGTH_BREAK_WORDS = 70
_LENGTH_BREAK_MIN_SENTENCES = 2
_LENGTH_BREAK_MIN_REST_WORDS = 20

#: Words that open a sentence on a new topic, per language, longest first
#: where they share a start. Matched on the lower-case start of a sentence.
_TOPIC_OPENERS: dict[str, tuple[str, ...]] = {
    "de": (  # i18n-allow: input vocabulary
        "außerdem", "ausserdem", "zudem", "darüber hinaus",  # i18n-allow
        "zweitens", "drittens", "viertens", "fünftens",  # i18n-allow
        "abschließend", "zum schluss", "zuletzt", "schließlich",  # i18n-allow
        "übrigens", "ansonsten", "generell", "grundsätzlich",  # i18n-allow
        "noch etwas", "noch was", "noch eine sache", "eine andere sache",  # i18n-allow
        "ein anderes thema", "anderes thema", "ein weiterer punkt",  # i18n-allow
        "ein weiteres", "eine weitere", "ein weiterer",  # i18n-allow
        "als nächstes", "nächster punkt", "neuer punkt",  # i18n-allow
        "kommen wir", "jetzt zu", "nun zu", "dann noch", "was noch",  # i18n-allow
        "wichtig ist", "ganz wichtig",  # i18n-allow
    ),
    "en": (
        "also", "additionally", "moreover", "furthermore", "besides",
        "second", "secondly", "third", "thirdly", "next", "finally", "lastly",
        "another", "anyway", "by the way", "in addition", "on another note",
        "one more thing", "apart from that", "other than that",
    ),
    "es": (
        "además", "por otro lado", "finalmente", "por último", "otra cosa",  # i18n-allow
        "en segundo lugar", "en tercer lugar",  # i18n-allow
    ),
    "pt": (
        "além disso", "por outro lado", "finalmente", "por fim", "outra coisa",  # i18n-allow
        "em segundo lugar", "em terceiro lugar",  # i18n-allow
    ),
}
#: Openers that mean something else in another served language ("Also" is
#: "so" in German). Left out when the language is not known.
_AMBIGUOUS_OPENERS = frozenset({"also"})

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


def _opens_topic(sentence: str, openers: tuple[str, ...]) -> bool:
    low = " ".join(sentence.casefold().split())
    return any(
        low.startswith(opener)
        and (len(low) == len(opener) or not low[len(opener)].isalnum())
        for opener in openers
    )


def _openers_for(language: str | None) -> tuple[str, ...]:
    code = normalize_language(language)
    if code in _TOPIC_OPENERS:
        return _TOPIC_OPENERS[code]
    return tuple(
        opener
        for openers in _TOPIC_OPENERS.values()
        for opener in openers
        if opener not in _AMBIGUOUS_OPENERS
    )


def auto_paragraphs(text: str, *, language: str | None = None) -> tuple[str, int]:
    """Break a long dictation into paragraphs; returns the text and how many.

    Only at sentence ends, and only inside a paragraph that has no line
    breaks of its own (a spoken list stays as it is). A paragraph begins:

    * before a sentence that opens a new topic (see :data:`_TOPIC_OPENERS`),
      once the paragraph before holds a few sentences;
    * at the next sentence end once a paragraph has grown long, as long as
      enough text follows to fill another one.

    A dictation under :data:`PARAGRAPH_MIN_WORDS` words is left as it is.
    """
    if count_words(text) < PARAGRAPH_MIN_WORDS:
        return text, 0
    openers = _openers_for(language)
    made = 0
    paragraphs = text.split("\n\n")
    out: list[str] = []
    for paragraph in paragraphs:
        if "\n" in paragraph or count_words(paragraph) < _TOPIC_BREAK_MIN_WORDS * 2:
            out.append(paragraph)
            continue
        spans = sentence_spans(paragraph)
        sentences = [paragraph[a:b] for a, b in spans]
        words = [count_words(sentence) for sentence in sentences]
        breaks: set[int] = set()
        held_words = 0
        held_sentences = 0
        for index, sentence in enumerate(sentences):
            if index > 0:
                rest = sum(words[index:])
                topic = (
                    held_sentences >= _TOPIC_BREAK_MIN_SENTENCES
                    and held_words >= _TOPIC_BREAK_MIN_WORDS
                    and _opens_topic(sentence, openers)
                )
                long = (
                    held_sentences >= _LENGTH_BREAK_MIN_SENTENCES
                    and held_words >= _LENGTH_BREAK_WORDS
                    and rest >= _LENGTH_BREAK_MIN_REST_WORDS
                )
                if topic or long:
                    breaks.add(index)
                    held_words = 0
                    held_sentences = 0
            held_words += words[index]
            held_sentences += 1
        made += len(breaks)
        out.append(break_before_sentences(paragraph, breaks) if breaks else paragraph)
    return "\n\n".join(out), made


_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n\s*")


def format_dictation(
    text: str,
    *,
    language: str | None = None,
    fillers: bool = True,
    layout_commands: bool = True,
    paragraphs: bool = True,
    max_removed_fraction: float = 0.25,
) -> FormatResult:
    """Format one recognized dictation. Never raises.

    A blank line in ``text`` is a paragraph the reading of the recording
    found (a long pause between two sentences); any other line break a
    recognizer wrote carries no meaning. ``paragraphs`` off keeps the text
    one paragraph except where a paragraph was spoken.

    On an unexpected failure of a rule the text recognized is delivered as it
    is: a broken rule must never cost the words.
    """
    raw = text if isinstance(text, str) else str(text or "")
    if not raw.strip():
        return FormatResult(text="", raw=raw, filler_reason="empty")
    try:
        parts = _BLANK_LINE_RE.split(raw.strip()) if paragraphs else [raw]
        pauses = 0
        cleaned: list[str] = []
        for part in parts:
            body, marks = strip_pause_marks(" ".join(part.split()))
            pauses += marks
            if body.strip():
                cleaned.append(body.strip())
        out = "\n\n".join(cleaned)
        commands = 0
        if layout_commands:
            out, commands = apply_layout_commands(out)
        removed = 0
        reason = "disabled"
        if fillers:
            out, removed, reason = remove_fillers(
                out, language=language, max_removed_fraction=max_removed_fraction
            )
        out = tidy_punctuation(out, capitalize_first=raw.strip()[:1].isupper() or commands > 0)
        made = 0
        if paragraphs:
            out, made = auto_paragraphs(out, language=language)
    except Exception:  # noqa: BLE001 - a broken rule never costs the dictation
        return FormatResult(text=raw.strip(), raw=raw, filler_reason="error")
    return FormatResult(
        text=out,
        raw=raw,
        removed_words=removed,
        filler_reason=reason,
        pause_marks=pauses,
        layout_commands=commands,
        paragraphs_made=made + max(0, len(cleaned) - 1),
    )


__all__ = [
    "FILLER_WORDS",
    "PARAGRAPH_MIN_WORDS",
    "LINE_COMMANDS",
    "PARAGRAPH_COMMANDS",
    "SUPPORTED_LANGUAGES",
    "FormatResult",
    "apply_layout_commands",
    "auto_paragraphs",
    "break_before_sentences",
    "count_words",
    "format_dictation",
    "normalize_language",
    "remove_fillers",
    "sentence_spans",
    "strip_pause_marks",
    "tidy_punctuation",
]
