"""Deterministic impact classification for shell commands.

Answers, without any LLM involvement, the question a non-technical user needs
answered before a command runs: does this only READ, does it MODIFY something,
or does it DELETE/destroy something? Used by ``RunShellTool`` to escalate
destructive commands to the ``ask`` tier via the ``risk_tier_for_args`` hook
(same pattern as the gmail per-action tiers, forensic 2026-06-19), and
intended as the basis for plain-language previews in the UI/voice surface.

Design constraints:
- Pure token heuristics, no shell parser: commands are split at pipe/chain
  separators and the leading word of every segment is classified. False
  positives escalate (a read misread as modify is harmless); unknown commands
  default to MODIFY, never to READ.
- Cross-shell: understands POSIX names (``rm``, ``ls``), PowerShell
  Verb-Noun cmdlets (``Remove-Item``) and their aliases (``del``, ``gci``).
- A ``>`` / ``>>`` redirect escalates a read to MODIFY (it writes a file),
  quoted ``>`` characters cause at most an over-escalation, never an
  under-escalation.
- Nested commands are classified, not trusted (security audit 2026-11-09:
  ``sh -c 'rm -rf ~'``, ``echo $(rm -rf ~)``, ``echo hi & rm -rf ~`` and
  ``find ~ -exec rm`` all read as harmless before). Splitting also happens at
  ``&``, backticks, ``$(``, parentheses and braces; a shell's ``-c`` payload,
  ``cmd /c`` and ``powershell -Command`` are classified recursively; code a
  classifier cannot see (``python -c``, ``node -e``, ``eval``, ``iex``,
  encoded PowerShell, a shell reading a pipe as in ``curl ... | sh``) counts
  as DESTRUCTIVE, because nothing proves it is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

READ = "read"
MODIFY = "modify"
DESTRUCTIVE = "destructive"

_SEVERITY = {READ: 0, MODIFY: 1, DESTRUCTIVE: 2}

# Segment separators: |, ||, &&, ;, newlines. Splitting inside quotes is
# acceptable — extra segments can only escalate severity, never lower it.
_SEGMENT_SPLIT = re.compile(r"\|\||&&|;|\||\n|\r|&|`|\$\(|[(){}]")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_REDIRECT = re.compile(r">{1,2}")

# Prefix words that wrap the real command.
_WRAPPERS = frozenset({
    "sudo", "time", "nohup", "env", "command", "builtin", "exec", "xargs",
})

_DESTRUCTIVE_COMMANDS = frozenset({
    # POSIX
    "rm", "rmdir", "shred", "dd", "mkfs", "fdisk", "parted", "wipefs",
    "shutdown", "reboot", "poweroff", "halt", "truncate",
    # Windows / PowerShell (aliases included)
    "del", "erase", "rd", "format", "diskpart",
    "remove-item", "ri", "remove-itemproperty",
    "clear-content", "clc", "clear-item", "cli", "clear-disk",
    "clear-recyclebin", "stop-computer", "restart-computer",
})

_READ_COMMANDS = frozenset({
    # POSIX
    "ls", "cat", "head", "tail", "grep", "find", "pwd", "whoami", "echo",
    "printf", "date", "uname", "hostname", "df", "du", "free", "ps", "top",
    "wc", "sort", "uniq", "which", "file", "stat", "env", "id", "uptime",
    "tr", "cut", "less", "more", "basename", "dirname", "tree",
    # NOT listed on purpose: sed (-i edits in place), awk (can invoke
    # system()), tee (writes files) — they fall through to MODIFY.
    # Windows / PowerShell (aliases included)
    "dir", "type", "where.exe", "findstr", "hostname.exe", "ver", "systeminfo",
    "get-childitem", "gci", "get-content", "gc", "get-item", "gi",
    "get-process", "gps", "get-date", "get-location", "gl", "get-service",
    "get-command", "gcm", "get-help", "select-string", "sls", "select-object",
    "select", "measure-object", "measure", "test-path", "resolve-path",
    "write-output", "write-host", "format-table", "ft", "format-list", "fl",
    "out-string", "compare-object", "sort-object", "where-object", "foreach-object",
})

# PowerShell Verb-Noun classification for cmdlets not covered above. The verb
# is the part before the dash; e.g. ``Uninstall-Module`` → "uninstall".
_DESTRUCTIVE_VERBS = frozenset({"remove", "clear", "reset", "uninstall"})
_READ_VERBS = frozenset({
    "get", "select", "measure", "test", "find", "resolve", "compare", "show",
    "read", "convertto", "convertfrom", "out",
})

# Shells whose inline payload (``-c``) is classified recursively. Without a
# payload and without a script argument they read commands from a pipe.
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish", "ash", "csh", "tcsh"})
_POWERSHELLS = frozenset({"powershell", "pwsh"})
_PS_INLINE = frozenset({"-command", "-c", "-com", "-comm", "-comma", "-comman"})
_PS_ENCODED = frozenset({"-encodedcommand", "-enc", "-e", "-ec", "-en", "-encoded"})
# Interpreters: running a named script file is an ordinary unknown (MODIFY);
# inline code or code from stdin is opaque (DESTRUCTIVE).
_INTERPRETERS = frozenset({
    "python", "python3", "python2", "py", "pypy", "pypy3", "node", "nodejs",
    "deno", "bun", "perl", "ruby", "php", "lua", "osascript", "rscript",
})
_INLINE_CODE_FLAGS = frozenset({
    "-c", "-e", "-r", "-p", "--eval", "--print", "-command", "-", "-x",
})
# Evaluate their argument as code.
_EVALUATORS = frozenset({"eval", "iex", "invoke-expression"})
_FIND_EXEC = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_QUOTES = "'\""
#: Nesting deeper than this is treated as opaque.
_MAX_DEPTH = 4

# Subcommand-sensitive commands: "git status" reads, "git reset" destroys.
_GIT_READ = frozenset({
    "status", "log", "diff", "show", "branch", "remote", "describe", "blame",
    "shortlog", "tag", "ls-files", "rev-parse", "config",
})
_GIT_DESTRUCTIVE = frozenset({"reset", "clean"})


@dataclass(frozen=True, slots=True)
class CommandImpact:
    """Classification result: the worst level across all command segments."""

    level: str  # READ | MODIFY | DESTRUCTIVE
    commands: tuple[str, ...]  # the classified leading words, for previews


def _normalize_word(token: str) -> str:
    word = token.strip(_QUOTES).lower().replace("\\", "/").rsplit("/", 1)[-1]
    return word.removesuffix(".exe")


def _tokens(segment: str) -> tuple[list[str], bool]:
    """Tokens after wrapper words and env assignments, and whether a wrapper led.

    Option tokens right after a wrapper (``sudo -u``, ``xargs -0``) are
    skipped, so the wrapped command is the one classified.
    """
    tokens = segment.strip().split()
    wrapped = False
    while tokens:
        word = _normalize_word(tokens[0])
        if word in _WRAPPERS:
            wrapped = True
            tokens = tokens[1:]
            while tokens and tokens[0].startswith("-"):
                tokens = tokens[1:]
        elif _ENV_ASSIGN.match(tokens[0]):
            tokens = tokens[1:]
        else:
            break
    return tokens, wrapped


def _leading_word(segment: str) -> tuple[str, str]:
    """Return (command, subcommand) of a segment, normalized.

    Strips wrapper words, env assignments, path prefixes, quotes and ``.exe``
    suffixes; lowercases. Empty strings when the segment has no word.
    """
    tokens, _ = _tokens(segment)
    if not tokens:
        return "", ""
    sub = tokens[1].strip(_QUOTES).lower() if len(tokens) > 1 else ""
    return _normalize_word(tokens[0]), sub


def _payload_after(segment: str, flags: frozenset[str]) -> str | None:
    """The raw text after the first token in ``flags`` (case-insensitive)."""
    parts = segment.split()
    for i, token in enumerate(parts):
        if token.lower() in flags:
            return " ".join(parts[i + 1:]).strip().strip(_QUOTES)
    return None


def _nested_level(word: str, segment: str, depth: int) -> str | None:
    """Level of commands hidden inside this segment, or None if there are none."""
    tokens, _ = _tokens(segment)
    args = [t.lower() for t in tokens[1:]]
    if word in _EVALUATORS:
        return DESTRUCTIVE
    if word in _SHELLS:
        payload = _payload_after(segment, frozenset({"-c"}))
        if payload is not None:
            return _classify(payload, depth + 1).level if payload else MODIFY
        if not args or args[0] in ("-", "-s", "-i"):
            return DESTRUCTIVE  # reads commands from a pipe: ``curl ... | sh``
        return None
    if word == "cmd":
        payload = _payload_after(segment, frozenset({"/c", "/k", "/r"}))
        if payload is not None:
            return _classify(payload, depth + 1).level if payload else MODIFY
        return DESTRUCTIVE if not args else None
    if word in _POWERSHELLS:
        if any(a in _PS_ENCODED for a in args):
            return DESTRUCTIVE
        payload = _payload_after(segment, _PS_INLINE)
        if payload is not None:
            return _classify(payload, depth + 1).level if payload else MODIFY
        if not args or "-" in args:
            return DESTRUCTIVE
        return None
    if word in _INTERPRETERS:
        if not args or any(a in _INLINE_CODE_FLAGS for a in args):
            return DESTRUCTIVE
        return None
    if word == "find":
        payload = _payload_after(segment, _FIND_EXEC)
        if payload is not None:
            inner = payload.rstrip(";+\\ ").replace("{}", "")
            return _classify(inner, depth + 1).level if inner.strip() else MODIFY
    return None


def _classify_segment(segment: str, depth: int = 0) -> tuple[str, str]:
    """Return (level, command_word) for one pipe/chain segment."""
    word, sub = _leading_word(segment)
    if not word:
        return READ, ""

    nested = _nested_level(word, segment, depth)
    if nested == DESTRUCTIVE:
        return DESTRUCTIVE, word

    if word == "git":
        if sub in _GIT_DESTRUCTIVE:
            return DESTRUCTIVE, f"git {sub}"
        if sub in _GIT_READ:
            return READ, f"git {sub}"
        return MODIFY, f"git {sub}".strip()
    if word == "reg":
        return (DESTRUCTIVE if sub == "delete" else MODIFY), f"reg {sub}".strip()

    if word == "find" and "-delete" in segment.lower():
        return DESTRUCTIVE, "find -delete"

    # A wrapper can hide the real command behind its own arguments
    # (``sudo -u bob rm``): any destructive word in a wrapped segment counts.
    tokens, wrapped = _tokens(segment)
    if wrapped and any(_normalize_word(t) in _DESTRUCTIVE_COMMANDS for t in tokens):
        return DESTRUCTIVE, word

    if word in _DESTRUCTIVE_COMMANDS:
        return DESTRUCTIVE, word
    if nested is not None:
        # Nested commands that only read or modify: never report below MODIFY,
        # an interpreter or shell is not a plain read.
        return (MODIFY if _SEVERITY[nested] <= _SEVERITY[MODIFY] else nested), word
    if word in _READ_COMMANDS:
        return READ, word

    # PowerShell Verb-Noun fallback ("format" alone is format.com, handled
    # above; "format-table" reaches this branch and reads).
    if "-" in word:
        verb = word.split("-", 1)[0]
        if verb in _DESTRUCTIVE_VERBS:
            return DESTRUCTIVE, word
        if verb in _READ_VERBS:
            return READ, word

    # Unknown commands default to MODIFY — never assume a stranger only reads.
    return MODIFY, word


def _classify(command: str, depth: int) -> CommandImpact:
    if depth > _MAX_DEPTH:
        return CommandImpact(level=DESTRUCTIVE, commands=())
    level = READ
    words: list[str] = []
    for segment in _SEGMENT_SPLIT.split(command):
        seg_level, word = _classify_segment(segment, depth)
        if _REDIRECT.search(segment) and _SEVERITY[seg_level] < _SEVERITY[MODIFY]:
            seg_level = MODIFY
        if word:
            words.append(word)
        if _SEVERITY[seg_level] > _SEVERITY[level]:
            level = seg_level
    return CommandImpact(level=level, commands=tuple(words))


def classify_command(command: str) -> CommandImpact:
    """Classify a full shell command string (worst segment wins)."""
    return _classify(command, 0)
