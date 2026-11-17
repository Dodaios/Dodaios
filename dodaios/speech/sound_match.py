"""Find the places in a transcript where a registered word was said.

A recognizer that does not know a word writes down what it heard. For
"Dodaios" that is "Dodios", "du Dios", "Diodios", "Doda iOS", "Odaios" or
"Dodios-Website" — never the same spelling twice, so a list of spellings can
not keep up. What these have in common is their SOUND, and that is what this
module compares:

* **Same sound.** The text, read across word gaps and hyphens, folds to the
  same phonetic key as the word ("Doda iOS", "Dodeios", "Klaude").
* **Almost the same sound.** The keys differ only in their vowels, or in a
  d/t-style consonant twin ("Dodios", "du Dios", "Kubernetis"). Vowels are
  what a recognizer gets wrong in a name it has never seen; the consonants it
  mostly keeps, so a different consonant means a different word — only a long
  word may differ by one.
* **The beginning is missing.** Recognizers drop an unstressed first syllable,
  so a token that is exactly the END of the word counts too ("Odaios").

A match that is not exact needs a witness: one token in it must be a word
that does not exist (``is_word``, see ``common_words.py``). "Nation" is a word
and stays "Nation" next to a registered "Notion"; "Dodios" is nothing, so it is
the registered word that sounds like it. That one rule is what lets the
matching be generous without rewriting ordinary speech.

What is left to chance is a NAME the word lists do not know that sounds like a
registered word ("Leiner" next to a registered "Linear"). Registering that
name too settles it: a registered word is never rewritten. The rules were
tuned on 9,300 words of real dictation (every miss of the product name fixed,
nothing else touched) and against 3.5 million words of news text full of such
names.

Pure string work — no model, no network; it runs on every transcript.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache

# Spelling variants that sound alike in German and English, applied in order
# on the casefolded text. Every rule makes MORE spellings equal, so the list
# stays short. The two placeholders protect "sch"/"ch" from the c- and h-rules
# that follow.
_FOLD_RULES: tuple[tuple[str, str], ...] = (
    ("ä", "e"),  # i18n-allow: a sound rule, not text
    ("ae", "e"),
    ("sch", "\x01"),
    ("ch", "\x02"),
    ("ph", "f"),
    ("th", "t"),
    ("ck", "k"),
    ("dt", "t"),
    ("tz", "ts"),
    ("z", "ts"),
    ("qu", "kv"),
    ("x", "ks"),
    ("c", "k"),
    ("v", "f"),
    ("w", "v"),
    ("y", "i"),
    ("ie", "i"),
    ("ei", "ai"),
    ("ou", "au"),  # English "ou" is German "au": "Cloude" is how STT spells "Claude"
)
_FOLD_SILENT_H_RE = re.compile(r"(?<!^)h")
_FOLD_REPEAT_RE = re.compile(r"(.)\1+")
_NOT_A_LETTER_RE = re.compile(r"[\W\d_]+", re.UNICODE)

_VOWELS = frozenset("aeiouöü")  # i18n-allow: letters, not text
#: Consonants a recognizer swaps freely (voiced/unvoiced twins, the nasals).
_TWINS = frozenset(frozenset(pair) for pair in ("dt", "bp", "gk", "mn", "fv"))
_NEVER = float("inf")
#: One letter per twin pair, and no vowels: two keys that may only differ in
#: their vowels and twins share this skeleton, which is what the index of
#: registered words is keyed by.
_SKELETON = str.maketrans(
    {"d": "t", "b": "p", "g": "k", "m": "n", "v": "f"} | dict.fromkeys(_VOWELS)
)
#: Results remembered per matcher. A live preview corrects the same growing
#: text several times a second, so most lookups are repeats.
_CACHE_LIMIT = 8192

#: A token shorter than this carries no evidence either way.
MIN_TOKEN_LEN = 4
#: Words whose key is shorter than this are matched exactly or not at all: in
#: a short name one vowel is the difference between two people ("Niki"/"Nico").
_MIN_NEAR_KEY_LEN = 6
#: From this key length on, two vowels may differ ("du Dios", "Diodios").
_TWO_VOWEL_KEY_LEN = 7
#: From this key length on, one consonant may differ as well.
_LONG_KEY_LEN = 9
#: How many tokens one word may have been split into.
_MAX_WINDOW = 3
#: The longest beginning a recognizer is assumed to drop, in key letters, and
#: how much of the word must still be there.
_MAX_DROPPED_HEAD = 2
_MIN_TAIL_KEY_LEN = 5
#: Word separators a split word may contain: "Doda iOS", "Do-Dios".
_JOINERS = frozenset({" ", "-"})

#: A token is a run of word characters; an apostrophe or a combining accent
#: keeps it in one piece, so "here's" and a decomposed umlaut stay one token
#: each (and, not being plain letters, are never matched).
_TOKEN_RE = re.compile(
    r"[\ẁ-ͯ]+(?:['’][\ẁ-ͯ]+)*", re.UNICODE
)


@lru_cache(maxsize=4096)
def phonetic_key(text: str) -> str:
    """Collapse ``text`` to how it sounds, so spelling twins compare equal.

    "Veltrok"/"Veltroc", "Klaude"/"Claude", "Doda iOS"/"Dodaios" fold to one
    key each; "grob"/"Grok" and "Clause"/"Claude" do not. Spaces, hyphens and
    digits are dropped: a key describes a sound, not a spelling.
    """
    folded = _NOT_A_LETTER_RE.sub("", text.casefold())
    for source, target in _FOLD_RULES:
        folded = folded.replace(source, target)
    folded = _FOLD_SILENT_H_RE.sub("", folded)
    folded = folded.replace("\x01", "sh").replace("\x02", "ch")
    return _FOLD_REPEAT_RE.sub(r"\1", folded)


def sound_cost(a: str, b: str, budget: float, *, consonants: bool = True) -> float | None:
    """How far two phonetic keys are apart, or ``None`` beyond ``budget``.

    A weighted edit distance: a vowel costs half a step to swap, add or drop,
    a consonant twin half a step to swap, any other consonant change a full
    step — or, with ``consonants=False``, is not allowed at all.
    """
    if a == b:
        return 0.0
    if abs(len(a) - len(b)) > budget * 2:
        return None
    hard = 1.0 if consonants else _NEVER

    def gap(ch: str) -> float:
        return 0.5 if ch in _VOWELS else hard

    def swap(x: str, y: str) -> float:
        if x == y:
            return 0.0
        if (x in _VOWELS and y in _VOWELS) or frozenset((x, y)) in _TWINS:
            return 0.5
        return hard

    prev = [0.0]
    for ch in b:
        prev.append(prev[-1] + gap(ch))
    for ca in a:
        cur = [prev[0] + gap(ca)]
        row_min = cur[0]
        for j, cb in enumerate(b, start=1):
            val = min(prev[j] + gap(ca), cur[j - 1] + gap(cb), prev[j - 1] + swap(ca, cb))
            cur.append(val)
            if val < row_min:
                row_min = val
        if row_min > budget:
            return None
        prev = cur
    return prev[-1] if prev[-1] <= budget else None


def _skeleton(key: str) -> str:
    return key.translate(_SKELETON)


def _one_short(skeleton: str) -> set[str]:
    """``skeleton`` and every version of it with one consonant left out.

    Two skeletons at most one consonant apart share one of these, which is
    how a long word finds its candidates without a scan of the dictionary.
    """
    return {skeleton, *(skeleton[:i] + skeleton[i + 1 :] for i in range(len(skeleton)))}


def near_budget(key_len: int) -> tuple[float, bool]:
    """``(budget, consonants)`` for a word whose key has ``key_len`` letters.

    How far a spelling may sit from the word, and whether a consonant may
    differ. ``(0.0, False)`` means: exact matches only.
    """
    if key_len < _MIN_NEAR_KEY_LEN:
        return 0.0, False
    if key_len < _TWO_VOWEL_KEY_LEN:
        return 0.5, False
    if key_len < _LONG_KEY_LEN:
        return 1.0, False
    return 1.5, True


@dataclass(frozen=True, slots=True)
class SoundTarget:
    """One sound the matcher listens for, and the word to write for it."""

    word: str
    key: str
    #: ``True`` for the registered word itself: near and tail matches allowed.
    #: ``False`` for a listed mishearing: only its exact sound counts.
    canonical: bool
    #: ``True`` for a mishearing that is a real word somewhere else ("Dios"):
    #: it only counts in a text the word lists cover.
    covered_only: bool = False


@dataclass(frozen=True, slots=True)
class _Token:
    start: int
    end: int
    text: str
    folded: str
    #: Letters only — a token with a digit, an apostrophe or an underscore is
    #: never matched.
    plain: bool


class SoundMatcher:
    """Rewrites the spans of a text that sound like a registered word."""

    def __init__(
        self,
        targets: Iterable[SoundTarget],
        *,
        is_word: Callable[[str], bool] | None,
        protected: Iterable[str] = (),
    ) -> None:
        """``is_word`` tells an ordinary word from an invented spelling; with
        ``None`` only exact sound matches are made. ``protected`` are spellings
        that are already right (every registered word) and are never rewritten.
        """
        self._is_word = is_word
        self._protected = frozenset(p.casefold() for p in protected)
        self._protected_stems = tuple(p for p in self._protected if len(p) >= MIN_TOKEN_LEN)
        self._exact: dict[str, set[str]] = {}
        self._exact_covered: dict[str, set[str]] = {}
        self._canonical_keys: set[str] = set()
        #: Words that may differ in vowels and twins only, by skeleton; and the
        #: long ones that may also differ by one consonant, by every skeleton
        #: one consonant short of theirs.
        self._near: dict[str, list[SoundTarget]] = {}
        self._near_long: dict[str, list[SoundTarget]] = {}
        self._tails: dict[str, set[str]] = {}
        self._closest_cache: dict[str, tuple[float, str] | None] = {}
        self._invented_cache: dict[str, bool] = {}
        seen: set[tuple[str, str]] = set()
        for target in targets:
            if not target.key or (target.word, target.key) in seen:
                continue
            seen.add((target.word, target.key))
            if target.covered_only:
                self._exact_covered.setdefault(target.key, set()).add(target.word)
                continue
            self._exact.setdefault(target.key, set()).add(target.word)
            if not target.canonical:
                continue
            self._canonical_keys.add(target.key)
            if len(target.key) < _MIN_NEAR_KEY_LEN:
                continue
            if near_budget(len(target.key))[1]:
                for short in _one_short(_skeleton(target.key)):
                    self._near_long.setdefault(short, []).append(target)
            else:
                self._near.setdefault(_skeleton(target.key), []).append(target)
            if " " in target.word or "-" in target.word:
                continue
            for dropped in range(1, _MAX_DROPPED_HEAD + 1):
                tail = target.key[dropped:]
                if len(tail) < _MIN_TAIL_KEY_LEN:
                    break
                self._tails.setdefault(tail, set()).add(target.word)
        self.target_count = len(seen)

    # -- public ---------------------------------------------------------

    def rewrite(self, text: str, *, generous: bool = True) -> str:
        """``text`` with every span that sounds like a registered word fixed.

        ``generous=False`` keeps to exact sound matches — for a text in a
        language the word lists do not cover, where ``is_word`` would call
        every ordinary word an invention.
        """
        if not text or not self.target_count:
            return text
        tokens = self._tokenize(text)
        if not tokens:
            return text
        generous = generous and self._is_word is not None
        out: list[str] = []
        cursor = 0
        i = 0
        while i < len(tokens):
            found = self._best_from(text, tokens, i, generous)
            if found is None:
                i += 1
                continue
            width, word = found
            out.append(text[cursor : tokens[i].start])
            out.append(word)
            cursor = tokens[i + width - 1].end
            i += width
        if not out:
            return text
        out.append(text[cursor:])
        return "".join(out)

    def knows(self, text: str, *, min_share: float = 0.5) -> bool:
        """Is ``text`` in a language the word lists cover?

        Judged by the share of its longer tokens that are ordinary words. A
        Spanish or Portuguese sentence fails this; a German or English one
        passes even with an invented name or two in it.
        """
        if self._is_word is None:
            return False
        judged = known = 0
        for token in self._tokenize(text):
            if not token.plain or len(token.text) < MIN_TOKEN_LEN:
                continue
            if token.folded in self._protected:
                continue
            judged += 1
            if self._is_word(token.folded):
                known += 1
        return judged > 0 and known / judged >= min_share

    # -- matching -------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[_Token]:
        return [
            _Token(
                start=m.start(),
                end=m.end(),
                text=m.group(0),
                folded=m.group(0).casefold(),
                plain=m.group(0).isalpha(),
            )
            for m in _TOKEN_RE.finditer(text)
        ]

    def _windows(self, text: str, tokens: list[_Token], i: int) -> Iterable[list[_Token]]:
        """The runs of 1..n tokens from ``i`` that may be one split word."""
        for width in range(1, _MAX_WINDOW + 1):
            window = tokens[i : i + width]
            if len(window) < width or not window[-1].plain:
                return
            if width > 1 and text[window[-2].end : window[-1].start] not in _JOINERS:
                return
            yield window

    def _best_from(
        self, text: str, tokens: list[_Token], i: int, generous: bool
    ) -> tuple[int, str] | None:
        """The best match starting at token ``i``: ``(tokens used, word)``."""
        best: tuple[float, int, str] | None = None
        for window in self._windows(text, tokens, i):
            match = self._match(window, generous)
            if match is not None and (best is None or match[0] < best[0]):
                best = (match[0], len(window), match[1])
        if best is None:
            return None
        cost, width, word = best
        # A split match must explain the text better than a match that starts
        # later inside it: "wie du Dodios" keeps its "du".
        for later in range(1, width):
            for window in self._windows(text, tokens, i + later):
                inner = self._match(window, generous, strict=True)
                if inner is not None and inner[0] <= cost:
                    return None
        return width, word

    def _is_invented(self, token: _Token) -> bool:
        """A token long enough to judge that is no word and no registered term."""
        if len(token.text) < MIN_TOKEN_LEN or token.folded in self._protected:
            return False
        if token.text.isupper():
            return False  # "LNER", "HRMS": an abbreviation, not a spelling
        cached = self._invented_cache.get(token.folded)
        if cached is None:
            if len(self._invented_cache) >= _CACHE_LIMIT:
                self._invented_cache.clear()
            cached = self._invented_cache[token.folded] = not (
                self._is_word is None
                or self._is_word(token.folded)
                # "Claudes", "Groks": a registered word with an ending is that word.
                or token.folded.startswith(self._protected_stems)
            )
        return cached

    def _match(
        self, window: list[_Token], generous: bool, *, strict: bool = False
    ) -> tuple[float, str] | None:
        """``(cost, word)`` when ``window`` sounds like a registered word.

        ``strict`` leaves out the two readings that take a FRAGMENT for the
        word — a missing beginning and a covered-only mishearing. A fragment
        on its own does not outweigh a split that explains the whole word:
        in "du Dios" the "du" is the first syllable, not a pronoun.
        """
        single = len(window) == 1
        raw = "".join(t.text for t in window)
        if len(raw) < MIN_TOKEN_LEN:
            return None
        if single and window[0].folded in self._protected:
            return None
        key = phonetic_key(raw)
        if not key:
            return None

        # 1) The same sound.
        words = self._exact.get(key)
        if words is None and generous and not strict:
            words = self._exact_covered.get(key)
        if words is not None:
            if len(words) > 1:
                return None  # two registered words sound like this — do not guess
            word = next(iter(words))
            if single:
                # An ordinary word is rewritten only when the user LISTED this
                # sound as a mishearing; never because it happens to sound
                # like a registered word ("viel" next to a registered "Phil").
                is_ordinary = self._is_word is not None and self._is_word(window[0].folded)
                if is_ordinary and key in self._canonical_keys:
                    return None
                return 0.0, word
            # Several ordinary words that happen to sound like one registered
            # word are a sentence ("the pipe I built"), unless they are the
            # word itself with a gap in it ("Git Hub", "Open AI").
            split_of_word = raw.casefold() == _NOT_A_LETTER_RE.sub("", word.casefold())
            if split_of_word or any(self._is_invented(t) for t in window):
                return 0.0, word
            return None
        if not generous:
            return None

        # 2) Almost the same sound — needs an invented token as its witness.
        #    A name chopped into three syllables has no token long enough to
        #    be one ("du da iOS"); there the witness is a fragment written
        #    like an abbreviation, which everyday short words ("not on", "ob
        #    sie den") never are. Two fragments are not enough: "DoD is".
        if any(t.folded in self._protected for t in window):
            return None
        chopped = (
            len(window) == _MAX_WINDOW
            and all(len(t.text) < MIN_TOKEN_LEN for t in window)
            and any(not t.text[1:].islower() for t in window if len(t.text) > 1)
        )
        if not chopped and not any(self._is_invented(t) for t in window):
            return None
        found = self._closest(key)
        if found is not None:
            return found

        # 3) The beginning is missing.
        if single and not strict:
            words = self._tails.get(key)
            if words is not None and len(words) == 1:
                return 0.5, next(iter(words))
        return None

    def _closest(self, key: str) -> tuple[float, str] | None:
        """The one registered word closest to ``key``; ``None`` on a tie."""
        if key in self._closest_cache:
            return self._closest_cache[key]
        best_cost: float | None = None
        best_word: str | None = None
        tied = False
        skeleton = _skeleton(key)
        candidates = {id(t): t for t in self._near.get(skeleton, ())}
        for short in _one_short(skeleton):
            candidates.update((id(t), t) for t in self._near_long.get(short, ()))
        for target in candidates.values():
            if target.key[0] != key[0]:
                continue  # a recognizer rarely gets the first sound wrong
            budget, consonants = near_budget(len(target.key))
            cost = sound_cost(key, target.key, budget, consonants=consonants)
            if cost is None:
                continue
            if best_cost is None or cost < best_cost:
                best_cost, best_word, tied = cost, target.word, False
            elif cost == best_cost and target.word != best_word:
                tied = True
        found = None if best_word is None or best_cost is None or tied else (best_cost, best_word)
        if len(self._closest_cache) >= _CACHE_LIMIT:
            self._closest_cache.clear()
        self._closest_cache[key] = found
        return found


__all__ = [
    "MIN_TOKEN_LEN",
    "SoundMatcher",
    "SoundTarget",
    "near_budget",
    "phonetic_key",
    "sound_cost",
]
