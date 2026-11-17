"""Is this token an ordinary German or English word?

The speech dictionary repairs a token toward a word the user registered when
the two sound alike. That is only safe for a token that is NOT a word in its
own right: "Dodios" may become "Dodaios", "Nation" must never become "Notion".
This module answers that one question.

The answer comes from a Bloom filter over two public-domain word lists (German
and English, about a million words with their inflected forms), shipped as
``dodaios/assets/lexicon/common_words.bloom`` and built by
``scripts/build_common_words.py``. A Bloom filter keeps a million words in
about 1.5 MB of memory with no parsing at load; its one flaw — a small share
of non-words is reported as words — errs on the safe side here, because a
token taken for a word is simply left alone.

No model, no network, no dependency: one file read on first use.
"""
from __future__ import annotations

import hashlib
import logging
import struct
import threading
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

#: File magic + layout: ``magic, bit count, hash count, word count`` then bits.
MAGIC = b"DWB1"
_HEADER = struct.Struct("<4sQBQ")

#: Words outside this length range are never stored and never looked up: the
#: sound matcher ignores shorter tokens, and nothing that long sits one sound
#: away from a registered word.
MIN_WORD_LEN = 4
MAX_WORD_LEN = 24


def lexicon_path() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "lexicon" / "common_words.bloom"


def _positions(word: str, bit_count: int, hash_count: int) -> list[int]:
    """Bit positions for ``word`` (double hashing over one BLAKE2 digest)."""
    digest = hashlib.blake2b(word.encode("utf-8"), digest_size=16).digest()
    first = int.from_bytes(digest[:8], "little")
    second = int.from_bytes(digest[8:], "little") | 1
    return [(first + i * second) % bit_count for i in range(hash_count)]


def normalize(word: str) -> str:
    """The form words are stored and looked up in."""
    return word.casefold()


class CommonWords:
    """Membership test over the shipped word lists."""

    def __init__(self, bits: bytes, bit_count: int, hash_count: int, word_count: int) -> None:
        self._bits = bits
        self._bit_count = bit_count
        self._hash_count = hash_count
        self.word_count = word_count

    @classmethod
    def from_bytes(cls, blob: bytes) -> CommonWords:
        magic, bit_count, hash_count, word_count = _HEADER.unpack_from(blob)
        if magic != MAGIC:
            raise ValueError("not a common-words file")
        bits = blob[_HEADER.size :]
        if len(bits) * 8 < bit_count or hash_count < 1:
            raise ValueError("common-words file is truncated")
        return cls(bits, bit_count, hash_count, word_count)

    @classmethod
    def build(cls, words: set[str], *, bits_per_word: int = 12) -> CommonWords:
        """A filter holding ``words`` (already normalized)."""
        bit_count = max(64, len(words) * bits_per_word)
        hash_count = max(1, round(bits_per_word * 0.693))
        bits = bytearray((bit_count + 7) // 8)
        for word in words:
            for pos in _positions(word, bit_count, hash_count):
                bits[pos >> 3] |= 1 << (pos & 7)
        return cls(bytes(bits), bit_count, hash_count, len(words))

    def to_bytes(self) -> bytes:
        return (
            _HEADER.pack(MAGIC, self._bit_count, self._hash_count, self.word_count)
            + self._bits
        )

    def __contains__(self, word: object) -> bool:
        if not isinstance(word, str):
            return False
        key = normalize(word)
        if not MIN_WORD_LEN <= len(key) <= MAX_WORD_LEN:
            return False
        return self._lookup(key)

    @lru_cache(maxsize=8192)  # noqa: B019 — one process-wide instance
    def _lookup(self, key: str) -> bool:
        bits = self._bits
        return all(
            bits[pos >> 3] & (1 << (pos & 7))
            for pos in _positions(key, self._bit_count, self._hash_count)
        )


_lock = threading.Lock()
_loaded: CommonWords | None = None
_load_attempted = False


def common_words() -> CommonWords | None:
    """The shipped word lists, or ``None`` when the file is missing or broken.

    ``None`` makes the dictionary fall back to exact sound matches only, so a
    damaged install corrects less — it never corrects wrongly.
    """
    global _loaded, _load_attempted
    if _load_attempted:
        return _loaded
    with _lock:
        if _load_attempted:
            return _loaded
        try:
            _loaded = CommonWords.from_bytes(lexicon_path().read_bytes())
        except Exception as exc:  # noqa: BLE001 — never break speech over a data file
            log.warning(
                "Common-word list unavailable (%s); the speech dictionary only "
                "repairs exact sound matches.",
                exc,
            )
            _loaded = None
        _load_attempted = True
        return _loaded


__all__ = [
    "CommonWords",
    "MAX_WORD_LEN",
    "MIN_WORD_LEN",
    "common_words",
    "lexicon_path",
    "normalize",
]
