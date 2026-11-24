"""Ask which terminal was meant, instead of guessing or going silent.

No score threshold separates a garbled call-sign from ordinary speech, so the decision is by
CONTEXT: when the turn is about the panes but the name is uncertain, ask. Detector only; pure regex,
no IO or LLM (AP-9 / AP-11).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .names import CALL_SIGN_WORD_RE, canonical_positions, near_miss, resolve

# How long a pending question stays answerable; same bound as the delegation offer window.
_WINDOW_TTL_S = 120.0

# A short turn is an ANSWER; a longer sentence is the user moving on.
_ANSWER_MAX_WORDS = 6


_WORKSPACE_NOUN_RE = re.compile(
    r"\b(?:terminals?|terminales|terminais|panes?|workspaces?|"
    r"painel|pain[eé]is|"  # i18n-allow: input vocab
    r"arbeitsbereich\w*|instanz\w*|instances?|"  # i18n-allow: input vocab
    r"prompte?\w*|prompting|anprompt\w*|"  # i18n-allow: input vocab
    r"beauftrag\w*|briefe?\w*|briefing)\b",  # i18n-allow: input vocab
    re.IGNORECASE,
)

_CODING_WORK_RE = re.compile(
    r"\b(?:"
    r"deep[\s-]?dive|root[\s-]?cause|debug\w*|analysier\w*|analyz\w*|analis\w*|"
    r"untersuch\w*|investigate\w*|diagnos\w*|"  # i18n-allow: input vocab
    # i18n-allow: input vocab
    r"fix\w*|behebe?\w*|repariere?\w*|refactor\w*|implementier\w*|implement\w*|"
    r"commit\w*|merge\w*|rebase\w*|deploy\w*|"
    r"bugs?|fehler\w*|tests?|teste\w*|repo\w*|branch\w*|"  # i18n-allow: input vocab
    r"code\w*|datei\w*|files?|funktion\w*|functions?|"  # i18n-allow: input vocab
    r"pull[\s-]?request|pr\b|"
    r"arregl\w*|revis\w*|prueba\w*|archivo\w*|rama\w*|"
    r"corrig\w*|conserta\w*|ficheiros?|c[oó]digo\w*|ramo\w*|"  # i18n-allow: input vocab
    r"refatoriz\w*|erros?"  # i18n-allow: input vocab
    r")\b",
    re.IGNORECASE,
)

#: Handing work to somebody; a flat verb scan because the NAME is what is uncertain.
_HANDOVER_VERB_RE = re.compile(
    r"\b(?:sag\w*|schick\w*|gib|geb\w*|frag\w*|lass\w*|l[aä]sst|"  # i18n-allow: input vocab
    r"beauftrag\w*|[uü]bergib|[uü]bergeb\w*|weiterleit\w*|"  # i18n-allow: input vocab
    r"tell|send|give|ask|hand|forward|assign|let|have|"
    r"dile|d[ií]gale|env[ií]a|manda|preg[uú]nta|pasa|asigna|encarga|"  # i18n-allow: input vocab
    r"diz|dizer|pede|pedir|pergunta|passa|atribui|encarrega)\b",  # i18n-allow: input vocab
    re.IGNORECASE,
)


#: "X SOLL das fixen": an order to a third party carried by the modal.
_DIRECTIVE_MODAL_RE = re.compile(
    r"\b(?:soll|sollen|sollte|sollten|m[uü]ssen|muss|"  # i18n-allow: input vocab
    r"should|must|shall|"
    r"deber[ií]an?|debe|deben|"  # i18n-allow: input vocab
    r"deve|devem|deveria|deveriam|t[eê]m\s+de|tem\s+que)\b",  # i18n-allow: input vocab
    re.IGNORECASE,
)


#: A status question to a NAMED worker, no coding vocabulary; both word orders per locale, German
#: with the perfect prefix.
_REPORT_QUESTION_RE = re.compile(
    r"\b(?:wie\s+weit|wie\s+l[aä]uft|wie\s+steht|how\s+far|"  # i18n-allow: input vocab
    r"c[oó]mo\s+va|como\s+vai|em\s+que\s+ponto)\b|"  # i18n-allow: input vocab
    r"\bwas\b[^.!?]{0,40}?"  # i18n-allow: input vocab
    r"\b(?:ge)?(?:macht|machen|tut|tun|tan|treibt|treiben|arbeitet|"  # i18n-allow: input vocab
    r"arbeiten|schafft|geschafft|erledigt|rausgefunden|"  # i18n-allow: input vocab
    r"herausgefunden|gebaut|geschrieben|ge[aä]ndert)\b|"  # i18n-allow: input vocab
    r"\b(?:ist|sind)\b[^.!?]{0,30}?\b(?:fertig|durch|soweit)\b|"  # i18n-allow: input vocab
    r"\b(?:what|how)\b[^.!?]{0,40}?"
    r"\b(?:doing|done|do|did|up\s+to|going|built|found|changed|"
    r"working\s+on|progress\w*)\b|"
    r"\b(?:is|are)\b[^.!?]{0,30}?\b(?:done|finished|ready|stuck)\b|"
    r"\b(?:qu[eé]|c[oó]mo)\b[^.!?]{0,40}?"
    r"\b(?:hacen?|haciendo|hecho|hizo|hicieron|va|van|"
    r"encontr\w*|cambi\w*)\b|"
    r"\b(?:est[aá]|est[aá]n)\b[^.!?]{0,30}?\b(?:listo\w*|terminad\w*)\b|"
    r"\b(?:o\s+que|como)\b[^.!?]{0,40}?"  # i18n-allow: input vocab
    r"\b(?:faz|fazem|fez|fizeram|feito|"  # i18n-allow: input vocab
    r"descobri\w*|mud\w*|alter\w*)\b|"  # i18n-allow: input vocab
    r"\b(?:est[aá]|est[aã]o)\b[^.!?]{0,30}?"  # i18n-allow: input vocab
    r"\b(?:pront[oa]s?|terminad\w*|acabad\w*)\b|"  # i18n-allow: input vocab
    r"\b(?:status|fortschritt|estado|progreso|progresso)\b",  # i18n-allow: input vocab
    re.IGNORECASE,
)


def addresses_workspace(text: str) -> bool:
    """Whether this turn is plausibly about the open coding workspace.

    It names the workspace, hands over or orders coding work, or asks a named worker for a STATUS
    REPORT. A handover verb alone never qualifies ("tell me what Elon Musk is doing").
    """
    body = str(text or "")
    if _WORKSPACE_NOUN_RE.search(body):
        return True
    # A status question about a FULL personal name is about that person.
    if _REPORT_QUESTION_RE.search(body) and not is_outside_world_talk(body):
        return True
    if not _CODING_WORK_RE.search(body):
        return False
    return bool(
        _HANDOVER_VERB_RE.search(body) or _DIRECTIVE_MODAL_RE.search(body)
    )


#: The unit the resolver scores: letters plus an optional digit tail (shared with ``intent``).
_WORD_RE = CALL_SIGN_WORD_RE

def _opens_sentence(prefix: str) -> bool:
    """True when whatever follows ``prefix`` starts a sentence (a string scan: the regex was
    quadratic, CodeQL py/polynomial-redos)."""
    core = prefix.rstrip()
    if "\n" in prefix[len(core) :]:
        return True
    if not core:
        return not prefix
    return core[-1] in ".!?:;"

#: Function words that are never a call-sign, however close they score (input vocabulary): "allen"
#: scores 0.750 against "Alex", above the acting threshold. Closed class only; one tuple per
#: language since the locales overlap.
_STOPWORDS_DE: tuple[str, ...] = (  # i18n-allow: input vocabulary
    "alle", "allen", "aller", "alles", "als", "am", "an", "auch", "auf",
    "aus", "bei", "bin", "bis", "bist", "bitte", "da", "dann", "das",
    "dass", "dein", "deine", "dem", "den", "denn", "der", "des", "die",
    "dir", "doch", "du", "ein", "eine", "einen", "einer", "eines", "er",
    "es", "etwas", "euch", "für", "gerade", "gib", "hab", "habe", "haben",
    "hast", "hat", "hier", "ich", "ihm", "ihn", "ihr", "im", "in", "ist",
    "ja", "kann", "kannst", "können", "könnte", "lass", "lassen", "mach",
    "machen", "macht", "mal", "man", "mein", "meine", "mir", "mit", "muss",
    "müssen", "nach", "nein", "nicht", "noch", "nur", "ob", "oder", "sag",
    "sage", "schon", "sein", "seine", "sich", "sie", "sind", "so", "soll",
    "sollen", "über", "um", "und", "uns", "unser", "von", "vor", "war",
    "was", "wenn", "wer", "werde", "werden", "wie", "wieso", "will",
    "wir", "wird", "wo", "zu", "zum", "zur",
)
_STOPWORDS_EN: tuple[str, ...] = (
    "a", "all", "am", "an", "and", "are", "as", "ask", "at", "be", "been",
    "but", "by", "can", "could", "did", "do", "does", "for", "from", "get",
    "give", "had", "has", "have", "he", "her", "him", "his", "how", "i",
    "if", "in", "into", "is", "it", "its", "just", "let", "make", "makes",
    "me", "my", "no", "not", "now", "of", "on", "one", "or", "our", "out",
    "please", "put", "say", "she", "should", "so", "some", "tell", "that",
    "the", "their", "them", "then", "there", "these", "they", "this",
    "to", "up", "us", "was", "we", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "would", "yes", "you", "your",
)
_STOPWORDS_ES: tuple[str, ...] = (  # i18n-allow: input vocabulary
    "a", "al", "algo", "aqui", "así", "como", "con", "cual", "cuando",
    "de", "del", "dile", "donde", "el", "ella", "ellos", "en", "era",
    "es", "esa", "ese", "eso", "esta", "este", "esto", "está", "están",
    "haz", "la", "las", "le", "les", "lo", "los", "mas", "me", "mi",
    "no", "nos", "o", "para", "pero", "por", "que", "qué", "quien",
    "se", "ser", "si", "sí", "sobre", "solo", "son", "su", "sus", "te",
    "tu", "un", "una", "uno", "y", "ya", "yo",
)
_STOPWORDS_PT: tuple[str, ...] = (  # i18n-allow: input vocabulary
    "a", "agora", "ao", "aos", "aqui", "as", "assim", "com", "como",
    "da", "das", "de", "diz", "do", "dos", "e", "ela", "ele",
    "eles", "em", "era", "és", "esse", "essa", "isso", "esta", "este",
    "está", "estão", "eu", "faz", "foi", "há", "isto", "já", "lhe",
    "mais", "mas", "me", "meu", "minha", "na", "nas", "no", "nos", "não",
    "nao", "o", "onde", "os", "ou", "para", "pelo", "pela", "por",
    "porque", "pode", "podes", "quando", "que", "quê", "quem", "se", "ser",
    "seu", "sim", "sobre", "só", "sua", "são", "também", "te", "teu",
    "tu", "um", "uma", "vai", "vou", "é",
)
_STOPWORDS: frozenset[str] = frozenset(
    _STOPWORDS_DE + _STOPWORDS_EN + _STOPWORDS_ES + _STOPWORDS_PT
)


def _capitalization_is_informative(text: str) -> bool:
    """Whether this transcript capitalizes at all (an all-lowercase one is a provider quirk)."""
    body = str(text or "")
    return any(ch.isupper() for ch in body)


def _is_proper_name_position(text: str, start: int, end: int) -> bool:
    """Whether the word reads as a proper name: a function word never is, else capitalization
    decides."""
    word = text[start:end]
    if word.casefold() in _STOPWORDS:
        return False
    if _is_vocabulary_word(word):
        return False
    if not _capitalization_is_informative(text):
        return True
    return word[:1].isupper()


#: What somebody ASKS FOR about a pane, as a noun ("Alex Status?"); never a surname.
_STATUS_NOUN_RE = re.compile(
    r"\b(?:status|fortschritt\w*|stand|update\w*|progress|"  # i18n-allow: input vocab
    r"bericht\w*|report\w*|estado|progreso|informe\w*|"  # i18n-allow: input vocab
    r"progresso|relat[oó]rio\w*)\b",  # i18n-allow: input vocab
    re.IGNORECASE,
)


def _is_vocabulary_word(word: str) -> bool:
    """Whether the word is one this module already reads as work, workspace or status (a WHOLE
    word)."""
    for pattern in (
        _WORKSPACE_NOUN_RE,
        _CODING_WORK_RE,
        _HANDOVER_VERB_RE,
        _DIRECTIVE_MODAL_RE,
        _STATUS_NOUN_RE,
    ):
        match = pattern.match(word)
        if match is not None and match.end() == len(word):
            return True
    return False


#: A second capitalized word after the candidate ("Elon MUSK"): panes carry one given name, so it is
#: a PERSON.
_SURNAME_FOLLOWS_RE = re.compile(r"^[\s,]*[A-ZÄÖÜ][^\W\d_]+")
_SURNAME_PRECEDES_RE = re.compile(r"[A-ZÄÖÜ][^\W\d_]+[\s,]*$")


def is_part_of_full_name(text: str, start: int, end: int) -> bool:
    """Whether the candidate is part of a longer proper name ("Elon Musk"); shared with
    ``intent``."""
    if not _capitalization_is_informative(text):
        return False
    following = _SURNAME_FOLLOWS_RE.match(text[end:])
    if following is not None:
        # A word read as work, workspace or status is never a surname ("Alex Status?").
        if not _is_vocabulary_word(following.group(0).strip(" ,")):
            return True
    preceding = text[:start]
    leading = _SURNAME_PRECEDES_RE.search(preceding)
    if leading is None:
        return False
    if _is_vocabulary_word(leading.group(0).strip(" ,")):
        return False
    # Test the PRECEDING word for sentence start, not the candidate ("Ist Blake fertig?").
    return not _opens_sentence(preceding[: leading.start()])


#: Two capitalized words in a row, the second not opening a sentence: a person ("Elon Musk").
_MULTIWORD_NAME_RE = re.compile(
    r"(?<![.!?:;\n])\s[A-ZÄÖÜ][^\W\d_]+\s+[A-ZÄÖÜ][^\W\d_]+"
)


def is_outside_world_talk(text: str) -> bool:
    """Whether this turn is about the world rather than the codebase (guards the COLLECTIVE
    address)."""
    body = str(text or "")
    if not _capitalization_is_informative(body):
        return False
    return bool(
        _MULTIWORD_NAME_RE.search(body) and not _CODING_WORK_RE.search(body)
    )



@dataclass(frozen=True, slots=True)
class UncertainName:
    """One word that came close to a call-sign, and the panes it might be."""

    spoken: str
    """The word as the transcript spelled it ("Ilies")."""

    candidates: tuple[str, ...]
    """Panes it could mean, best first. Never empty."""


@dataclass(frozen=True, slots=True)
class ClarificationNeeded:
    """Everything one turn addressed that could not simply be acted on; ``certain`` panes are
    briefed anyway."""

    uncertain: tuple[UncertainName, ...]
    """The words that need a question. Never empty."""

    utterance: str
    """The original turn, kept verbatim so the confirmed pane gets the REAL
    task and not a paraphrase assembled from fragments."""

    certain: tuple[str, ...] = ()
    """Panes the SAME turn named beyond doubt. They are not in question and
    must be briefed whatever the answer is; they travel with the question only
    so the caller can tell "one pane is uncertain" from "everything is"."""

    @property
    def spoken(self) -> str:
        """The first uncertain word — the one a single-name question names."""
        return self.uncertain[0].spoken

    @property
    def candidates(self) -> tuple[str, ...]:
        """Panes the first uncertain word could mean."""
        return self.uncertain[0].candidates

    @property
    def offered(self) -> tuple[str, ...]:
        """Every pane any of the uncertain words could mean, in order."""
        seen: list[str] = []
        for item in self.uncertain:
            for name in item.candidates:
                if name not in seen:
                    seen.append(name)
        return tuple(seen)


#: What may stand between two listed names ("and", enumeration punctuation); possessive runs avoid
#: ReDoS.
_ENUMERATION_GAP_RE = re.compile(
    r"^[\s,;&]*+"
    # i18n-allow: input vocabulary — the supported languages' "and"
    r"(?:(?:und|and|y|e|sowie|plus|as\s+well\s+as|together\s+with|junto\s+con|junto\s+com|bem\s+como)"
    r"[\s,;&]*+)?$",
    re.IGNORECASE,
)


def _is_listed_beside(text: str, span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    """Whether the word at ``span`` is enumerated next to one of ``others`` ("Alex und Blaike")."""
    start, end = span
    for other_start, other_end in others:
        if other_end <= start and _ENUMERATION_GAP_RE.match(text[other_end:start]):
            return True
        if end <= other_start and _ENUMERATION_GAP_RE.match(text[end:other_start]):
            return True
    return False


def detect_clarification(
    user_text: str, *, names: list[str]
) -> ClarificationNeeded | None:
    """What this turn addressed but did not clearly name, or ``None``.

    A lone uncertain word asks only when no pane was certainly named; otherwise it must be
    ENUMERATED beside another name. ``certain`` panes are briefed at once.
    """
    text = str(user_text or "").strip()
    if len(text) < 3 or not names:
        return None
    # Gate on the ORIGINAL wording: the rewrite below consumes the pane noun that is its evidence.
    if not addresses_workspace(text):
        return None
    # Canonical wording from here on: a pane named by position is as CERTAIN as a call-sign.
    working = canonical_positions(text, names)

    certain: list[str] = []
    certain_spans: list[tuple[int, int]] = []
    uncertain: list[tuple[tuple[int, int], UncertainName]] = []
    for match in _WORD_RE.finditer(working):
        word = match.group(0)
        span = (match.start(), match.end())
        # Certain means the exact name or the same sound, the same bar ``near_miss`` uses.
        sure = resolve(word, names, fuzzy=False)
        if sure is not None:
            if sure not in certain:
                certain.append(sure)
            certain_spans.append(span)
            continue
        candidates = near_miss(word, names)
        if not candidates:
            continue
        if not _is_proper_name_position(working, *span):
            continue
        if is_part_of_full_name(working, *span):
            continue
        uncertain.append(
            (span, UncertainName(spoken=word, candidates=tuple(n for n, _ in candidates)))
        )

    if not uncertain:
        return None

    if len(uncertain) > 1 or certain:
        # Only names being LISTED with another survive; a single stray near miss is noise.
        neighbours = certain_spans + [span for span, _ in uncertain]
        kept = [
            (span, item)
            for span, item in uncertain
            if _is_listed_beside(working, span, [s for s in neighbours if s != span])
        ]
        if not kept:
            return None
        uncertain = kept

    return ClarificationNeeded(
        uncertain=tuple(item for _, item in uncertain),
        utterance=text,
        certain=tuple(certain),
    )



@dataclass(slots=True)
class _Pending:
    uncertain: tuple[UncertainName, ...]
    utterance: str
    asked_at: float
    question: str = ""

    @property
    def candidates(self) -> tuple[str, ...]:
        """Every pane on offer, in the order they were spoken."""
        seen: list[str] = []
        for item in self.uncertain:
            for name in item.candidates:
                if name not in seen:
                    seen.append(name)
        return tuple(seen)


@dataclass(slots=True)
class ClarificationWindow:
    """A question waiting for its answer, so "yes" delivers the ORIGINAL task."""

    _pending: _Pending | None = field(default=None)

    def arm(
        self, need: ClarificationNeeded, *, question: str = "", now: float | None = None
    ) -> None:
        self._pending = _Pending(
            uncertain=need.uncertain,
            utterance=need.utterance,
            asked_at=time.monotonic() if now is None else now,
            question=question,
        )

    def disarm(self) -> None:
        self._pending = None

    @property
    def armed(self) -> bool:
        return self._pending is not None

    def resolve_answer(
        self, answer: str, *, language: str = "de", now: float | None = None
    ) -> tuple[tuple[str, ...], str] | None:
        """``(panes, original_utterance)`` for a clear answer, else ``None``.

        Consumed exactly once; an answer is NAMING offered panes or a short affirmative (confirms
        words with ONE candidate).
        """
        pending = self._pending
        if pending is None:
            return None
        current = time.monotonic() if now is None else now
        if (current - pending.asked_at) > _WINDOW_TTL_S:
            self._pending = None
            return None

        text = str(answer or "").strip()
        if not text:
            return None

        offered = list(pending.candidates)
        named = [
            hit
            for hit in (
                resolve(match.group(0), offered, fuzzy=False)
                for match in _WORD_RE.finditer(text)
            )
            if hit is not None
        ]
        if not named:
            # The whole answer as one token (a one-word reply or a two-word call-sign).
            single = resolve(text, offered)
            if single is not None:
                named = [single]
        if named:
            self._pending = None
            return tuple(dict.fromkeys(named)), pending.utterance

        # Only a SHORT turn is an answer; the bound grows with the names on offer.
        if len(text.split()) > _ANSWER_MAX_WORDS + len(pending.uncertain) - 1:
            self._pending = None
            return None

        verdict = _classify(text, language)
        self._pending = None
        if verdict != "confirm":
            return None
        decided = tuple(
            dict.fromkeys(
                item.candidates[0] for item in pending.uncertain if len(item.candidates) == 1
            )
        )
        return (decided, pending.utterance) if decided else None


def classify_short_answer(text: str, language: str = "de") -> str:
    """``"confirm"`` / ``"veto"`` / ``"unknown"`` for a short answer; public so questions read "yes"
    alike."""
    return _classify(text, language)


def _classify(text: str, language: str) -> str:
    """Yes/no verdict across every supported language (the per-turn language tag is untrusted)."""
    try:
        from dodaios.voice.echo_confirmation import classify_response  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — a classifier fault is simply "no answer"
        return "unknown"
    verdicts = {
        classify_response(text, language=lang)
        for lang in {"de", "en", "es", "pt", str(language or "de")}
    }
    if "veto" in verdicts:
        return "veto"
    return "confirm" if "confirm" in verdicts else "unknown"


#: ONE shared window per process (as ``spawn_gate.OFFER_WINDOW``); tests reset it via ``disarm()``.
WINDOW = ClarificationWindow()


__all__ = [
    "WINDOW",
    "ClarificationNeeded",
    "ClarificationWindow",
    "UncertainName",
    "addresses_workspace",
    "classify_short_answer",
    "detect_clarification",
    "is_outside_world_talk",
    "is_part_of_full_name",
]
