"""From the person's words to the things they stand for.

Measured on coding agents, a brief does not get better by swapping an everyday
word for a technical one: what costs is a missing fact, and a word that names
the wrong thing. So this module does not polish wording. It finds the places
where the person's words leave a fact open ("looks bad", "is broken",
"somehow") and says which fact would close each one, and it picks the words
worth looking up in the repository, so the writer can name the real component,
function or file instead of describing it.

It also reads a finished brief for the two ways a precise-sounding brief goes
wrong: an open phrase carried over unchanged, and a guess stated as a fact (an
agent follows a wrong direction it is handed).

The German words below are speech input vocabulary, matching data and not
prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = [
    "OpenPhrase",
    "open_phrases",
    "search_words",
    "spelled_out",
    "unlabelled_guesses",
    "vague_left",
]


@dataclass(frozen=True, slots=True)
class OpenPhrase:
    """Words of the person that leave a fact open, and the fact that closes them."""

    said: str
    kind: str
    name_instead: str

    def as_dict(self) -> dict[str, str]:
        return {"said": self.said, "name_instead": self.name_instead}


_LOOK = (
    r"looks? (?:bad|wrong|off|ugly|weird|terrible|awful|cheap)|(?:not|isn'?t) (?:pretty|nice)"
    r"|ugly|prettier|nicer|more beautiful|polish(?:ed)?"
    r"|sieht (?:\w+ ){0,3}(?:nicht gut|schlecht|komisch"  # i18n-allow: input vocab
    r"|h[aä]sslich|bl[oö]d)(?: aus)?"  # i18n-allow: input vocab
    r"|nicht (?:wirklich )?sch[oö]n|sch[oö]ner|h[uü]bscher"  # i18n-allow: input vocab
    r"|h[aä]sslich\w*"  # i18n-allow: input vocab
    r"|unsch[oö]n\w*|gef[aä]llt mir nicht"  # i18n-allow: input vocab
)
_BROKEN = (
    r"(?:is|are|seems?) broken|does ?n[o']t work|not working|stopped working|buggy|acts? up"
    r"|kaputt\w*|spinnt|macht probleme"  # i18n-allow: input vocab
    r"|(?:funktioniert|geht|klappt) "  # i18n-allow: input vocab
    r"(?:einfach |gar |so |noch |immer noch |wieder |leider )?nicht"  # i18n-allow: input vocab
)
_SLOW = (
    r"(?:too |very |so |really )?slow\w*|laggy|sluggish|takes (?:too |so )?long"
    r"|(?:zu |sehr |extrem )?langsam\w*|ruckel\w*|tr[aä]ge"  # i18n-allow: input vocab
    r"|dauert (?:\w+ ){0,2}(?:lange|ewig)"  # i18n-allow: input vocab
)
_BETTER = (
    r"(?:make|do) (?:it|this|that) better|improve\w*|optimi[sz]e\w*|clean(?:ed)? up|tidy up"
    r"|verbesser\w*|besser machen|(?:deutlich|viel|einfach) besser"  # i18n-allow: input vocab
    r"|optimier\w*|aufr[aä]um\w*"  # i18n-allow: input vocab
    r"|[uü]berarbeit\w*"  # i18n-allow: input vocab
)
_THING = (
    r"somehow|the thing|that thing|this thing|stuff|whatever it is"
    r"|irgendwie|irgendwas|das ding|dieses ding|dieses teil"  # i18n-allow: input vocab
    r"|das zeug"  # i18n-allow: input vocab
)

_OPEN: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = (
    (
        "look",
        re.compile(rf"(?i)\b(?:{_LOOK})\b"),
        "each visible fault as a fact: what is shown now and what should be shown",
    ),
    (
        "broken",
        re.compile(rf"(?i)\b(?:{_BROKEN})\b"),
        "what was observed (verbatim) and what was expected instead",
    ),
    (
        "slow",
        re.compile(rf"(?i)\b(?:{_SLOW})\b"),
        "the measure, its value now and the value it should reach",
    ),
    (
        "better",
        re.compile(rf"(?i)\b(?:{_BETTER})\b"),
        "the property that should change and how to tell that it did",
    ),
    (
        "thing",
        re.compile(rf"(?i)\b(?:{_THING})\b"),
        "the thing by its name in the code or on the screen",
    ),
)


def open_phrases(words: str) -> list[OpenPhrase]:
    """The phrases in the person's words that leave a fact open, each kind once."""
    text = " ".join((words or "").split())
    found: list[OpenPhrase] = []
    for kind, pattern, name_instead in _OPEN:
        match = pattern.search(text)
        if match is not None:
            found.append(OpenPhrase(said=match.group(0), kind=kind, name_instead=name_instead))
    return found


# What a brief may not carry over unchanged. English only: a brief for a coding
# agent that keeps the person's German phrase quotes it, and a quote is fine.
_VAGUE_IN_BRIEF = re.compile(
    r"(?i)\b(?:looks? (?:bad|ugly|off|weird)|not (?:pretty|nice)|make (?:it|this) (?:better|nicer)"
    r"|clearly improve|improve (?:it|this|the (?:ui|look|design|code|quality))"
    r"|as appropriate|where sensible|sensible (?:default|fallback)s?|properly|really well"
    r"|somehow|and so on|etc\.?)(?=\W|$)"
)
_GUESS = re.compile(
    r"(?i)\b(?:most likely|probably|presumably|i suspect|i assume|i guess|my guess"
    r"|likely (?:cause|reason|culprit)|must be (?:the|a|because)|should be (?:the|a) cause"
    r"|vermutlich|wahrscheinlich)\b"  # i18n-allow: input vocab
)
_GUESS_LABEL = re.compile(
    r"(?i)\b(?:hypothesis|hunch|unverified|not verified|unconfirmed|guess|suspicion|assumption"
    r"|to be confirmed|not checked)\b"
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def vague_left(brief: str) -> list[str]:
    """Open phrases a brief states as its own words (quotes do not count)."""
    unquoted = re.sub(r'"[^"\n]{0,400}"|“[^”\n]{0,400}”|`[^`\n]{0,400}`', " ", brief or "")
    seen: list[str] = []
    for match in _VAGUE_IN_BRIEF.finditer(unquoted):
        phrase = match.group(0).strip().lower()
        if phrase not in seen:
            seen.append(phrase)
    return seen


def unlabelled_guesses(brief: str) -> list[str]:
    """Sentences that state a suspected cause or fix without calling it a guess."""
    found: list[str] = []
    for match in _SENTENCE.finditer(brief or ""):
        sentence = " ".join(match.group(0).split())
        if _GUESS.search(sentence) and not _GUESS_LABEL.search(sentence):
            found.append(sentence[:240])
    return found


_STOP_EN: Final[str] = (
    "the a an and or but if then else for from with without into onto over under about this "
    "that these those there here what which when where why how who whom whose is are was were "
    "be been being have has had do does did can could should would will shall may might must "
    "not no yes please just also very really quite some any all every each more most less "
    "least much many make made makes take takes get gets got give gives look looks see sees "
    "want wants need needs like know think say said tell told thing things stuff something "
    "anything nothing new old good bad nice better best agent agents task work works working "
    "change changes fix fixes problem problems issue issues"
)
# Stop words of the spoken language: matching data, one marked line each.
_STOP_DE: Final[str] = (
    "bitte danke hallo also aber oder und der die das den dem des ein eine einen "  # i18n-allow
    "einem einer eines ich du er sie es wir ihr mich mir dich dir uns euch mein "  # i18n-allow
    "dein sein kein nicht noch schon mal doch halt eben ja nein wenn dann weil "  # i18n-allow
    "dass damit auch nur sehr ganz wirklich einfach irgendwie irgendwas "  # i18n-allow
    "vielleicht immer wieder jetzt hier dort da wie was wer wo warum wann "  # i18n-allow
    "welche welcher welches diese dieser dieses diesen jede jeder jedes alle "  # i18n-allow
    "alles viel viele mehr weniger gut schlecht neu alt machen macht gemacht "  # i18n-allow
    "soll sollte kann könnte muss müsste will möchte habe hast hat haben hatte "  # i18n-allow
    "sind ist war waren wird werden wurde bin bist für von mit ohne bei nach vor "  # i18n-allow
    "über unter auf aus zum zur ins im am an in zu um als so"  # i18n-allow
)
_STOP: Final[frozenset[str]] = frozenset(f"{_STOP_EN} {_STOP_DE}".split())
_IDENTIFIER = re.compile(
    r"`([^`\n]{2,80})`"  # anything the person put in backticks
    # Dotted, slashed or dashed names and file names. The underscore is a word
    # character and no separator here: as both, "a_b_c_..." could be split in
    # exponentially many ways.
    r"|\b([A-Za-z_]\w*(?:[./-]\w+)+)\b"
    r"|\b([a-z]+_[a-z0-9_]+)\b"  # snake_case
    r"|\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b"  # CamelCase
)
_QUOTED = re.compile(r'"([^"\n]{3,80})"|“([^”\n]{3,80})”|„([^“\n]{3,80})“')
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)


def spelled_out(words: str) -> list[str]:
    """The names a person spelled out or quoted: identifiers, file names, what a screen said.

    These are worth searching for in any language. The ordinary words of a
    dictated sentence are not: they are in the person's language, and in a
    code base they mostly find its lists of spoken vocabulary.
    """
    found: list[str] = []
    for pattern in (_IDENTIFIER, _QUOTED):
        for match in pattern.finditer(words or ""):
            token = next(group for group in match.groups() if group).strip()
            if token and token not in found:
                found.append(token)
    return found


def search_words(words: str, *, limit: int = 12) -> list[str]:
    """The words of a request worth looking up in the repository, best first.

    Names the person spelled out (backticks, file names, snake_case,
    CamelCase) come first, then what they quoted from the screen, then the
    remaining content words. Common words of English and German are left out.
    """
    text = words or ""
    found: list[str] = []

    def add(token: str) -> None:
        token = token.strip().strip(".,;:!?()[]")
        if token and token.lower() not in {f.lower() for f in found}:
            found.append(token)

    for match in _IDENTIFIER.finditer(text):
        add(next(group for group in match.groups() if group))
    for match in _QUOTED.finditer(text):
        add(next(group for group in match.groups() if group))
    for match in _WORD.finditer(text):
        word = match.group(0)
        if word.lower() not in _STOP:
            add(word)
    return found[:limit]
