#!/usr/bin/env python3
"""Fail on names of other games, studios, franchises or real firearm makes and models.

The Verse may never name them (docs/verse/unreal/README.md, Legal), and no other
repo gate reads ``.cpp``, ``.h``, ``.cs`` or asset metadata for them. The list
lives only as SHA-256 hashes in ``scripts/unreal/forbidden_names.sha256``, so
the repository never contains the names it forbids; the integration owner keeps
the plain list outside the repo and adds hashes with ``--hash``.

Text is normalised to lower-case ASCII words (accents dropped, camelCase and
digits split, every other character a separator). Each single word, each raw
unsplit token and each two- and three-word sequence is hashed, joined by one
space and (when every word has two or more characters) with no separator, so
``Some Name``, ``some_name``, ``SomeName`` and ``somename`` all match the
entry ``some name``.

    python scripts/unreal/check_forbidden_names.py              # tracked files in scope
    python scripts/unreal/check_forbidden_names.py FILE...      # these files
    python scripts/unreal/check_forbidden_names.py --diff origin/main
                                                    # added lines + commit messages
    echo "feat(verse): ..." | python scripts/unreal/check_forbidden_names.py --stdin
    python scripts/unreal/check_forbidden_names.py --hash "two words"
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HASH_FILE = Path(__file__).resolve().with_name("forbidden_names.sha256")
#: Paths whose files are scanned by default (architecture.md 8.4, orchestration GC1.5).
SCOPE = ("unreal/", "art/verse/", "docs/verse/", "scripts/unreal/")
MAX_WORDS = 3

_RAW = re.compile(r"[A-Za-z0-9]+")
_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def _ascii(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def words(text: str) -> list[str]:
    """Lower-case words of ``text``, camelCase and digit runs split apart."""
    out: list[str] = []
    for raw in _RAW.findall(_ascii(text)):
        out.extend(w.lower() for w in _WORD.findall(raw))
    return out


def digest(phrase: str) -> str:
    return hashlib.sha256(phrase.encode("utf-8")).hexdigest()


def entry_hashes(phrase: str) -> set[str]:
    """The hashes one list entry contributes (spaced and joined form)."""
    raw = _RAW.findall(_ascii(phrase))
    ws = words(phrase)
    if len(raw) == 1 and ws:
        # One token such as a model code: match it whole, and split only into real
        # words ("ab12" also matches "AB-12"; "a12" never matches "A = 12").
        out = {digest(raw[0].lower())}
        if len(ws) <= MAX_WORDS and all(len(w) > 1 for w in ws):
            out |= {digest(" ".join(ws)), digest("".join(ws))}
        return out
    if not ws or len(ws) > MAX_WORDS:
        raise ValueError(f"an entry needs 1 to {MAX_WORDS} words, got {phrase!r}")
    return {digest(" ".join(ws)), digest("".join(ws))}


def candidates(text: str) -> Iterator[tuple[str, str]]:
    """(phrase, hash) for every word sequence of ``text`` the list can match."""
    for raw in _RAW.findall(_ascii(text)):
        low = raw.lower()
        yield low, digest(low)
    ws = words(text)
    for n in range(1, MAX_WORDS + 1):
        for i in range(len(ws) - n + 1):
            seq = ws[i : i + n]
            spaced = " ".join(seq)
            yield spaced, digest(spaced)
            # The joined form only for real words: joining single letters and
            # digits ("a k m" from "a, k * M") would match by accident.
            if n > 1 and all(len(w) > 1 for w in seq):
                yield spaced, digest("".join(seq))


def load_hashes(path: Path = HASH_FILE) -> set[str]:
    hashes: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", line):
            raise ValueError(f"{path.name}: not a SHA-256 line: {line[:20]}...")
        hashes.add(line)
    return hashes


def scan_text(text: str, hashes: set[str]) -> list[str]:
    """Matched phrases in ``text`` (as they appear after normalisation)."""
    return sorted({phrase for phrase, h in candidates(text) if h in hashes})


def _git(*args: str) -> str:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return proc.stdout


def _is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def scan_files(paths: Iterable[str], hashes: set[str]) -> list[str]:
    findings: list[str] = []
    for rel in paths:
        for hit in scan_text(rel, hashes):
            findings.append(f"{rel}: path contains a forbidden name ({hit})")
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if _is_binary(data):
            continue
        for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            for hit in scan_text(line, hashes):
                findings.append(f"{rel}:{number}: forbidden name ({hit})")
    return findings


def tracked_in_scope() -> list[str]:
    return [p for p in _git("ls-files", "--", *SCOPE).splitlines() if p and p != _SELF]


def scan_diff(base: str, hashes: set[str]) -> list[str]:
    findings: list[str] = []
    diff = _git("diff", "--unified=0", "--no-color", f"{base}...HEAD", "--", *SCOPE)
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
            for hit in scan_text(current, hashes):
                findings.append(f"{current}: path contains a forbidden name ({hit})")
        elif line.startswith("+") and current and current != _SELF:
            for hit in scan_text(line[1:], hashes):
                findings.append(f"{current}: added line has a forbidden name ({hit})")
    log = _git("log", "--format=%H%x00%B%x01", f"{base}..HEAD")
    for record in log.split("\x01"):
        sha, _, message = record.strip().partition("\x00")
        for hit in scan_text(message, hashes):
            findings.append(f"commit {sha[:10]}: message has a forbidden name ({hit})")
    return findings


_SELF = "scripts/unreal/forbidden_names.sha256"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="Repo-relative files to scan.")
    parser.add_argument("--diff", metavar="BASE", help="Scan added lines and commits since BASE.")
    parser.add_argument("--stdin", action="store_true", help="Scan text from stdin.")
    parser.add_argument("--hash", metavar="PHRASE", action="append", help="Print entry hashes.")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.hash:
        for phrase in args.hash:
            for h in sorted(entry_hashes(phrase)):
                print(h)
        return 0
    hashes = load_hashes()
    if args.stdin:
        findings = [f"stdin: forbidden name ({hit})" for hit in scan_text(sys.stdin.read(), hashes)]
    elif args.diff:
        findings = scan_diff(args.diff, hashes)
    else:
        findings = scan_files(args.paths or tracked_in_scope(), hashes)
    for line in findings:
        print(f"check_forbidden_names: {line}")
    if findings:
        print("Rename it: Verse names are our own (README Legal).")
        return 1
    print(f"check_forbidden_names: clean ({len(hashes)} hashes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
