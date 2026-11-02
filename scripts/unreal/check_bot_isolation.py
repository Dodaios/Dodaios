#!/usr/bin/env python3
"""Static fairness checks F1 (isolation) and F6 (symmetry) of contracts/bot.md section 10.

F1: ``Source/VerseBot/**`` never reads the truth about the opponent. It uses
none of ``GetPlayerPawn``, ``GetPlayerController``, actor iterators or
``GetAllActorsOfClass`` over pawns, ``GetPawn()`` on another controller,
another actor's ability system component, ``IVersePieceQuery::GetPieceState``
outside ``FVersePieceBelief``; no EQS context returns an ``AVerseCharacter``;
raw world traces only on ``VerseSight`` or through ``TestSight``.

F6: the harness person models read the same ``FVersePerceptFrame`` under the
same rules as the bot, and hearing ranges come from ``DA_Audibility``
(``UVerseAudibilityTable``), never from numbers in code.

Comments and string literals are stripped before matching.

    python scripts/unreal/check_bot_isolation.py              # F1 and F6 on the repo
    python scripts/unreal/check_bot_isolation.py --source <dir>
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "unreal" / "Verse" / "Source"
SOURCE_SUFFIXES = (".h", ".cpp", ".inl")
#: Fakes and tests may build any world they like; the rules apply to shipped bot code.
EXEMPT_PARTS = ("Tests",)

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_STRING = re.compile(r'"(?:\\.|[^"\\\n])*"')

PAWNISH = r"(?:AVerseCharacter|ACharacter|APawn|AVerseDefaultCharacter)"

#: (rule id, pattern, message). Patterns run on comment- and string-free text.
RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("F1.player-pawn", re.compile(r"\bGetPlayerPawn\s*\("), "GetPlayerPawn reads the opponent"),
    (
        "F1.player-controller",
        re.compile(r"\bGet(?:First)?PlayerController(?:Iterator)?\s*\("),
        "GetPlayerController reaches the person's controller",
    ),
    (
        "F1.actor-iterator",
        re.compile(rf"\bT(?:Actor|Object)(?:Iterator|Range)\s*<\s*{PAWNISH}\s*>"),
        "an actor iterator over pawns",
    ),
    (
        "F1.all-actors",
        re.compile(rf"\bGetAllActors(?:OfClass|WithInterface|WithTag)?\s*\([^;]*{PAWNISH}"),
        "GetAllActorsOfClass on pawns",
    ),
    (
        "F1.other-pawn",
        re.compile(r"(?<!\bthis)(?:->|\.)\s*GetPawn\s*(?:<[^>]*>)?\s*\("),
        "GetPawn() on a controller other than its own",
    ),
    (
        "F1.other-asc",
        re.compile(
            r"GetAbilitySystemComponentFromActor\s*\(\s*(?!GetPawn\s*\(\s*\)\s*\))"
            r"|(?<!GetPawn\(\))(?<!\bthis)->\s*GetAbilitySystemComponent\s*\("
        ),
        "attribute reads on a non-own ability component",
    ),
    (
        "F1.raw-trace",
        re.compile(
            r"\b(?:LineTrace|Sweep|Overlap)(?:Single|Multi|Test|Any)\w*\s*\((?![^;]*VerseSight)"
        ),
        "a raw world trace that is not on VerseSight (use IVersePenetrationQuery::TestSight)",
    ),
)
PIECE_STATE = re.compile(r"\bGetPieceState\s*\(")
EQS_CONTEXT = re.compile(r"\bUEnvQueryContext\w*")
EQS_PAWN = re.compile(r"\bAVerseCharacter\b")
HEARING_NUMBER = re.compile(
    r"\b\w*(?:Hear|Audib)\w*(?:Range|Radius|Distance)\w*\s*(?:=|\{|\()\s*-?\d+(?:\.\d*)?f?\b"
)
AUDIBILITY = re.compile(r"\bUVerseAudibilityTable\b|\bDA_Audibility\b|\bAudibilityTable\b")
PERCEPT_FRAME = re.compile(r"\bFVersePerceptFrame\b")


def strip_code(text: str) -> str:
    """Text with comments and string literals blanked (line numbers kept)."""

    def blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return _STRING.sub(blank, _COMMENT.sub(blank, text))


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def source_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if path.suffix in SOURCE_SUFFIXES and not any(p in EXEMPT_PARTS for p in path.parts):
            yield path


def _rel(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def scan_rules(
    path: Path, base: Path, rules: Iterable[tuple[str, re.Pattern[str], str]]
) -> list[str]:
    code = strip_code(path.read_text(encoding="utf-8", errors="replace"))
    findings = []
    for rule, pattern, message in rules:
        for match in pattern.finditer(code):
            findings.append(
                f"{_rel(path, base)}:{_line_of(code, match.start())}: {rule}: {message}"
            )
    return findings


def check_isolation(source: Path = DEFAULT_SOURCE) -> list[str]:
    """F1 findings for ``<source>/VerseBot``."""
    bot = source / "VerseBot"
    findings: list[str] = []
    for path in source_files(bot):
        findings += scan_rules(path, source, RULES)
        code = strip_code(path.read_text(encoding="utf-8", errors="replace"))
        if "PieceBelief" not in path.name:
            for match in PIECE_STATE.finditer(code):
                findings.append(
                    f"{_rel(path, source)}:{_line_of(code, match.start())}: F1.piece-state: "
                    "IVersePieceQuery::GetPieceState outside FVersePieceBelief"
                )
        if EQS_CONTEXT.search(code):
            for match in EQS_PAWN.finditer(code):
                findings.append(
                    f"{_rel(path, source)}:{_line_of(code, match.start())}: F1.eqs-context: "
                    "an EQS context names AVerseCharacter"
                )
    return findings


def _model_files(source: Path) -> list[Path]:
    harness = source / "VerseHarness"
    return [p for p in source_files(harness) if "Model" in p.name or "Trick" in p.name]


def check_symmetry(source: Path = DEFAULT_SOURCE) -> list[str]:
    """F6 findings: person models perceive like the bot; hearing ranges come from DA_Audibility."""
    findings: list[str] = []
    models = _model_files(source)
    for path in models:
        findings += [f.replace(": F1.", ": F6.model.", 1) for f in scan_rules(path, source, RULES)]
    if models and not any(PERCEPT_FRAME.search(p.read_text(encoding="utf-8")) for p in models):
        findings.append(
            "VerseHarness: F6.model-input: person models do not read FVersePerceptFrame"
        )
    hearing_dirs = [source / "VerseBot", source / "VerseCombat" / "Private" / "Perception"]
    for directory in hearing_dirs:
        for path in source_files(directory):
            code = strip_code(path.read_text(encoding="utf-8", errors="replace"))
            for match in HEARING_NUMBER.finditer(code):
                findings.append(
                    f"{_rel(path, source)}:{_line_of(code, match.start())}: F6.hearing-literal: "
                    "a hearing range in code; read it from DA_Audibility"
                )
            mentions_hearing = re.search(r"\bHear(?:ing|d)\w*", code) and re.search(
                r"\b(?:Range|Radius)\b|RangeM\b", code
            )
            if mentions_hearing and not AUDIBILITY.search(code):
                findings.append(
                    f"{_rel(path, source)}: F6.hearing-source: hearing ranges without "
                    "UVerseAudibilityTable (DA_Audibility)"
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--only", choices=("F1", "F6"))
    args = parser.parse_args(argv)
    findings: list[str] = []
    if args.only in (None, "F1"):
        findings += check_isolation(args.source)
    if args.only in (None, "F6"):
        findings += check_symmetry(args.source)
    for line in findings:
        print(f"check_bot_isolation: {line}")
    if findings:
        print("The bot and the person models see the world only through percepts (bot.md 10).")
        return 1
    print("check_bot_isolation: clean (F1, F6)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
