"""Build ``dodaios/assets/lexicon/common_words.bloom``.

The speech dictionary asks one question of this file: "is this token an
ordinary German or English word?" (see ``dodaios/speech/common_words.py``).
The answer is built from two public-domain word lists, pinned to a commit so a
rebuild gives the same file:

* German: https://github.com/enz/german-wordlist (CC0 1.0)
* English: https://github.com/dwyl/english-words (The Unlicense)

Usage::

    python scripts/build_common_words.py            # download + build
    python scripts/build_common_words.py --from DIR # use de.txt / en.txt in DIR
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dodaios.speech.common_words import (  # noqa: E402
    MAX_WORD_LEN,
    MIN_WORD_LEN,
    CommonWords,
    lexicon_path,
    normalize,
)

SOURCES = {
    "de": (
        "https://raw.githubusercontent.com/enz/german-wordlist/"
        "1071d87d9535b57b80ec076c699f2578a28ee9dc/words"
    ),
    "en": (
        "https://raw.githubusercontent.com/dwyl/english-words/"
        "20f5cc9b3f0ccc8ce45d814c532b7c2031bba31c/words_alpha.txt"
    ),
}


def _read(source_dir: Path | None, language: str) -> str:
    if source_dir is not None:
        return (source_dir / f"{language}.txt").read_text(encoding="utf-8")
    with urllib.request.urlopen(SOURCES[language], timeout=120) as response:  # noqa: S310
        return response.read().decode("utf-8")


def collect(source_dir: Path | None) -> set[str]:
    words: set[str] = set()
    for language in SOURCES:
        for line in _read(source_dir, language).splitlines():
            word = normalize(line.strip())
            if word.isalpha() and MIN_WORD_LEN <= len(word) <= MAX_WORD_LEN:
                words.add(word)
    return words


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="source_dir", type=Path, default=None)
    args = parser.parse_args()
    words = collect(args.source_dir)
    target = lexicon_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(CommonWords.build(words).to_bytes())
    print(f"{len(words)} words -> {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
