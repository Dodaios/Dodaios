"""What the repository itself says about a request, read before the brief is written.

A brief that names where to start saves the agent its first searches, and one
that names a file which does not exist sends it looking for nothing. Rewriting
a task helps a coding agent only when the added facts were read from the
repository; added from memory they make the result worse than no rewrite. So
everything here is read from disk:

* **starting points**: the files whose names and contents fit the request,
  with the lines that made them fit (the file index and the peek the voice
  composer already uses);
* **the project's own checks**: the commands its instruction files call the
  end of a change, and the test commands its manifests define, so a brief's
  "done" can name a real command instead of "tests pass";
* **whether a path exists**, and what the nearest real path is when it does
  not.

All of it is blocking file work bounded by a deadline: callers run
:func:`lookup` in a worker thread. A fault never fails a hand-off: the facts
come back emptier.

Everything is read through a :class:`RepoFiles`: in the app the folder on
disk (:class:`DiskFiles`, the default), and in a benchmark replay one commit of
the repository read from git's objects (``dodaios.rsi.bench.at_commit``), so
that measuring the kit at a past commit writes no file.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from dodaios.rsi import domains

__all__ = [
    "DiskFiles",
    "RepoFacts",
    "RepoFiles",
    "StartingPoint",
    "house_checks",
    "lookup",
    "nearest",
    "path_exists",
]

log = logging.getLogger(__name__)

#: How many starting points a writer is shown.
MAX_STARTING_POINTS: Final[int] = 5
#: The lines of a file shown with a starting point.
_EXCERPT_CHARS: Final[int] = 240
#: What the peek writes in front of the lines that mention the request (``file_peek``).
_HIT_MARK: Final[str] = "Lines mentioning the task:"
#: Instruction files a project keeps for its coding agents, in reading order.
_INSTRUCTION_FILES: Final[tuple[str, ...]] = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
_INSTRUCTION_CHARS: Final[int] = 40_000
#: A line of an instruction file that is about ending or checking a change.
_CHECK_LINE = re.compile(
    r"(?i)\b(?:done|gate|land(?:s|ing)?|before (?:you )?(?:commit|push|merge)|tests?|lint|"
    r"type ?check|verify|check)\b"
)
_BACKTICK = re.compile(r"`([^`\n]{3,160})`")
_COMMAND = re.compile(
    r"^(?:\./[\w./-]+|(?:[~\w./-]*/)?python3?\s|(?:[~\w./-]*/)?pytest\b|npm\s|pnpm\s|yarn\s"
    r"|npx\s|make\s|cargo\s|go\s|uv\s|tox\b|ruff\s|mypy\b|tsc\b|vitest\b|jest\b|bash\s|sh\s)"
)
_MAX_CHECKS: Final[int] = 6
#: Manifests below the root are looked for this deep.
_MANIFEST_DEPTH: Final[int] = 4
_MAX_MANIFESTS: Final[int] = 4
_NODE_SCRIPTS: Final[tuple[str, ...]] = ("test", "typecheck", "lint", "build")


@dataclass(frozen=True, slots=True)
class StartingPoint:
    """A file that fits the request, and the lines that say why."""

    path: str
    lines: str = ""

    def as_dict(self) -> dict[str, str]:
        out = {"path": self.path}
        if self.lines:
            out["lines"] = self.lines
        return out


@dataclass(slots=True)
class RepoFacts:
    """What was read from one folder for one request."""

    folder: str = ""
    #: The folder exists and could be listed.
    known: bool = False
    files: int = 0
    starting_points: list[StartingPoint] = field(default_factory=list)
    #: At least one starting point is a real lead: found by what stands in it.
    content_match: bool = False
    checks: list[str] = field(default_factory=list)
    frontend_roots: list[str] = field(default_factory=list)
    #: Every indexed path, for existence checks without touching the disk again.
    paths: frozenset[str] = frozenset()

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.starting_points:
            out["starting_points"] = [p.as_dict() for p in self.starting_points]
        if self.checks:
            out["project_checks"] = list(self.checks)
        return out


def _read(path: Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:  # an unreadable file gives no facts, it is not an error
        return ""


class RepoFiles(Protocol):
    """Where a look-up reads a repository, by paths relative to its root."""

    #: The folder the facts are about.
    root: Path

    def is_file(self, rel: str) -> bool: ...

    def is_dir(self, rel: str) -> bool: ...

    def read(self, rel: str, limit: int = 200_000) -> str:
        """The text of a file, at most ``limit`` characters; "" when there is none."""
        ...

    def names(self, rel: str) -> list[str]:
        """The names in a folder."""
        ...

    def source(self, rel: str) -> str:
        """A file's text within the code outline's bounds (``code_skeleton.read_source``)."""
        ...

    def index(self, wait_s: float) -> Any:
        """The file index (``file_index.FileIndex``), waited for at most ``wait_s``; or None."""
        ...

    def files_with(self, word: str, stop_at: float) -> list[str] | None:
        """The files that contain ``word``, any case; None when this cannot be answered."""
        ...


class DiskFiles:
    """A repository's folder on disk: what the app reads, as it always did."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def is_file(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def is_dir(self, rel: str) -> bool:
        return (self.root / rel).is_dir()

    def read(self, rel: str, limit: int = 200_000) -> str:
        return _read(self.root / rel, limit)

    def names(self, rel: str) -> list[str]:
        return [p.name for p in (self.root / rel).iterdir()]

    def source(self, rel: str) -> str:
        from dodaios.agentic_ide.code_skeleton import read_source

        return read_source(str(self.root), rel)

    def index(self, wait_s: float) -> Any:
        return _index_within(self.root, wait_s)

    def files_with(self, word: str, stop_at: float) -> list[str] | None:
        return _files_with(self.root, word, stop_at)


def house_checks(folder: str | Path, *, files: RepoFiles | None = None) -> list[str]:
    """The commands a project's own files call the check of a change.

    First what its instruction files say in a sentence about being done,
    landing or testing, then the test commands its manifests define. Read
    only; no command is run. ``files``: read there instead of the folder on disk.
    """
    root = Path(folder).expanduser()
    files = files if files is not None else DiskFiles(root)
    found: list[str] = []

    def add(command: str) -> None:
        command = " ".join(command.split())
        if command and command not in found and len(found) < _MAX_CHECKS:
            found.append(command)

    for name in _INSTRUCTION_FILES:
        for line in files.read(name, _INSTRUCTION_CHARS).splitlines():
            if not _CHECK_LINE.search(line):
                continue
            for snippet in _BACKTICK.findall(line):
                if _COMMAND.match(snippet.strip()):
                    add(snippet.strip())
    try:
        from dodaios.self_build.code import commands

        for argv in commands.detect(root, files=files).get("test") or []:
            add(commands.shown(list(argv)))
    except Exception:  # noqa: BLE001 - no detectable test command is an answer too
        log.debug("brief facts: test command detection failed for %s", root, exc_info=True)
    return found


def _node_checks(files: RepoFiles, paths: frozenset[str]) -> tuple[list[str], list[str]]:
    """``(commands, frontend roots)`` from the package manifests below the root."""
    import json

    commands: list[str] = []
    roots: list[str] = []
    manifests = sorted(
        (p for p in paths if p.endswith("package.json") and p.count("/") <= _MANIFEST_DEPTH),
        key=lambda p: (p.count("/"), p),
    )
    for rel in manifests[:_MAX_MANIFESTS]:
        try:
            package = json.loads(files.read(rel, 200_000) or "{}")
        except ValueError:  # a broken manifest names no scripts
            continue
        scripts = package.get("scripts") if isinstance(package, dict) else None
        if not isinstance(scripts, dict):
            continue
        where = str(Path(rel).parent).replace("\\", "/")
        if where != ".":
            roots.append(where)
        for name in _NODE_SCRIPTS:
            body = str(scripts.get(name) or "")
            if body and "no test specified" not in body:
                run = "npm test" if name == "test" else f"npm run {name}"
                commands.append(run if where == "." else f"{run} (in {where})")
    return commands, roots


#: Files worth opening for a request: source and text, not data or build output.
_SEARCHED_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".rs", ".java", ".kt", ".rb", ".php",
        ".cs", ".c", ".h", ".cc", ".cpp", ".swift", ".scala", ".sh", ".sql", ".vue", ".svelte",
        ".css", ".scss", ".html", ".md", ".toml", ".yaml", ".yml",
    }
)
_GREP_TIMEOUT_S: Final[float] = 1.5
_MAX_SEARCH_WORDS: Final[int] = 8
#: A word found in more files than this says nothing about where to start.
_COMMON_WORD_FILES: Final[int] = 400
_SCAN_FILES: Final[int] = 1_500
_SCAN_BYTES: Final[int] = 200_000


def _files_with(root: Path, word: str, stop_at: float) -> list[str] | None:
    """The files that contain ``word``; ``None`` when ``git grep`` cannot answer."""
    import subprocess

    left = stop_at - time.monotonic()
    if left <= 0.05:
        return []
    try:
        got = subprocess.run(  # noqa: S603 - fixed argv, a read-only search
            ["git", "-C", str(root), "grep", "-I", "-i", "-l", "-F", "-e", word],  # noqa: S607
            capture_output=True, text=True, timeout=min(_GREP_TIMEOUT_S, left), check=False,
        )
    except (OSError, subprocess.SubprocessError):  # no git or too slow: no answer
        return None
    if got.returncode not in (0, 1):  # 1 means no match; anything else, not a repository
        return None
    return got.stdout.splitlines()


def _scan_for(
    files: RepoFiles, words: list[str], paths: frozenset[str], stop_at: float
) -> dict[str, list[str]]:
    """``word -> files`` by reading the files themselves, for a folder without git."""
    found: dict[str, list[str]] = {word: [] for word in words}
    lowered = [(word, word.lower()) for word in words]
    for rel in sorted(paths)[:_SCAN_FILES]:
        if time.monotonic() >= stop_at:
            break
        if Path(rel).suffix.lower() not in _SEARCHED_SUFFIXES:
            continue
        body = files.read(rel, _SCAN_BYTES).lower()
        for word, low in lowered:
            if low in body:
                found[word].append(rel)
    return found


def _content_candidates(
    files: RepoFiles, text: str, paths: frozenset[str], *, deadline_s: float
) -> list[str]:
    """Files whose contents share the request's words, the most telling first.

    A file scores by the words it holds, a rare word counting for more than a
    common one, and a name the person spelled out (an identifier) for more
    than an ordinary word. Read-only and bounded by ``deadline_s``.
    """
    import math

    from dodaios.briefs import terms

    words = terms.search_words(text, limit=_MAX_SEARCH_WORDS)
    if not words or not paths or deadline_s <= 0:
        return []
    stop_at = time.monotonic() + deadline_s
    hits: dict[str, list[str]] = {}
    for word in words:
        left = stop_at - time.monotonic()
        found = files.files_with(word, stop_at) if left > 0.05 else []
        if found is None:
            hits = _scan_for(files, words, paths, stop_at)
            break
        hits[word] = [rel for rel in found if rel in paths]
    scores: dict[str, float] = {}
    matched: dict[str, int] = {}
    for word, files in hits.items():
        kept = [f for f in files if Path(f).suffix.lower() in _SEARCHED_SUFFIXES]
        if not kept or len(kept) > _COMMON_WORD_FILES:
            continue
        spelled_out = any(mark in word for mark in "_./") or word != word.lower()
        weight = (3.0 if spelled_out else 1.0) / math.log(2 + len(kept))
        for rel in kept:
            scores[rel] = scores.get(rel, 0.0) + weight
            matched[rel] = matched.get(rel, 0) + 1
    # One ordinary word in common is chance; two, or one spelled-out name, is a lead.
    leads = [
        rel for rel in scores
        if matched[rel] >= 2 or scores[rel] >= 3.0 / math.log(2 + _COMMON_WORD_FILES)
    ]
    leads.sort(key=lambda rel: (-scores[rel], "test" in rel.lower(), rel.count("/"), rel))
    return leads[: MAX_STARTING_POINTS * 2]


#: How long a hand-off waits for a folder's first file index.
_INDEX_WAIT_S: Final[float] = 2.5
#: An index older than this is rebuilt behind the next look-up.
_INDEX_MAX_AGE_S: Final[float] = 600.0
_INDEXED_AT: dict[str, float] = {}


def _index_within(root: Path, wait_s: float) -> Any | None:
    """The folder's file index, waiting at most ``wait_s`` for a first build.

    The index is built in the background and kept (``file_index``). A look-up
    never builds it on its own clock: listing a very large folder takes as
    long as it takes, and a hand-off must not wait for it.
    """
    try:
        from dodaios.agentic_ide import file_index
    except Exception:  # noqa: BLE001 - without an index the brief is checked on wording only
        log.warning("brief facts: file index unavailable", exc_info=True)
        return None
    key = str(root)
    index = file_index.cached_index(root)
    now = time.monotonic()
    if index is not None:
        if now - _INDEXED_AT.setdefault(key, now) > _INDEX_MAX_AGE_S:
            # Files came and went since: this look-up uses what it has, the next a new list.
            _INDEXED_AT.pop(key, None)
            file_index.forget_index(root)
            file_index.prime_index(root)
        return index
    file_index.prime_index(root)
    stop_at = now + max(0.0, wait_s)
    while time.monotonic() < stop_at:
        time.sleep(0.05)
        index = file_index.cached_index(root)
        if index is not None:
            _INDEXED_AT[key] = time.monotonic()
            return index
    return None


def path_exists(facts: RepoFacts, token: str) -> bool:
    """Whether a path a brief names is real: in the index, or on disk under the folder."""
    name = token.strip().lstrip("@").strip("`'\"").rstrip(".,;:)")
    if not name or not facts.folder:
        return True
    posix = name.replace("\\", "/").removeprefix("./")
    if posix in facts.paths:
        return True
    if "/" not in posix:
        # A bare file name stands for any file of that name.
        return any(p == posix or p.endswith("/" + posix) for p in facts.paths)
    try:
        candidate = Path(posix).expanduser()
        if not candidate.is_absolute():
            candidate = Path(facts.folder) / posix
        return candidate.exists()
    except OSError:  # a name the file system cannot even ask about is not a real path
        return False


def nearest(facts: RepoFacts, token: str, *, limit: int = 3) -> list[str]:
    """Real paths closest to one that does not exist: same file name first."""
    posix = token.strip().lstrip("@").strip("`'\"").replace("\\", "/")
    base = posix.rsplit("/", 1)[-1].lower()
    if not base:
        return []
    same = sorted(p for p in facts.paths if p.rsplit("/", 1)[-1].lower() == base)
    if same:
        return same[:limit]
    import difflib

    names = {p.rsplit("/", 1)[-1].lower(): p for p in sorted(facts.paths, reverse=True)}
    close = difflib.get_close_matches(base, list(names), n=limit, cutoff=0.78)
    return [names[name] for name in close]


def lookup(
    folder: str | Path,
    text: str,
    *,
    kind: str = "",
    extra_words: str = "",
    deadline_s: float = 4.0,
    files: RepoFiles | None = None,
) -> RepoFacts:
    """Read ``folder`` for a request and return what fits it.

    ``text`` is the request (the person's words and, when there is one, the
    draft); ``extra_words`` are further search words such as what a glossary
    entry stands for. ``files`` reads the repository there instead of the
    folder on disk (one commit of it). Blocking: run it off the event loop.
    """
    started = time.monotonic()
    facts = RepoFacts(folder=str(folder or ""))
    if not facts.folder:
        return facts
    root = Path(facts.folder).expanduser()
    if files is None:
        try:
            if not root.is_dir():
                return facts
        except OSError:  # a folder that cannot be asked about is an unknown folder
            return facts
        files = DiskFiles(root)
    # What the project's own files say about checking a change needs no index.
    facts.checks = house_checks(root, files=files)
    index = files.index(min(_INDEX_WAIT_S, deadline_s * 0.6))
    if index is None:
        # A very large folder, or a machine under load: the brief is checked on
        # its wording this time, and the index is ready for the next one.
        return facts
    facts.known = True
    facts.paths = frozenset(entry.rel for entry in index.entries)
    facts.files = len(facts.paths)
    node_commands, facts.frontend_roots = _node_checks(files, facts.paths)
    for command in node_commands:
        if command not in facts.checks and len(facts.checks) < _MAX_CHECKS:
            facts.checks.append(command)

    words = " ".join(part for part in (text, extra_words) if part and part.strip())
    try:
        by_name = index.suggest(words, limit=MAX_STARTING_POINTS * 2)
    except Exception:  # noqa: BLE001 - a ranking fault leaves the brief without hints
        log.warning("brief facts: file ranking failed for %s", root, exc_info=True)
        by_name = []
    # A request rarely uses a file's name; it uses the words that stand in it.
    by_content = _content_candidates(
        files, words, facts.paths, deadline_s=max(0.0, deadline_s * 0.5)
    )
    candidates = list(dict.fromkeys([*by_content, *by_name]))[: MAX_STARTING_POINTS * 3]
    if not candidates:
        return facts
    ranked, excerpts = list(candidates), {}
    left = deadline_s - (time.monotonic() - started)
    if left > 0.2:
        try:
            from dodaios.agentic_ide import file_peek

            peeked = file_peek.peek(
                str(root), words, candidates, kind, deadline_s=left, read=files.source
            )
            ranked, excerpts = list(peeked.ranked) or ranked, dict(peeked.excerpts)
        except Exception:  # noqa: BLE001 - names alone are still starting points
            log.debug("brief facts: peek failed for %s", root, exc_info=True)
    leads = set(by_content)
    points: list[StartingPoint] = []
    for rel in ranked:
        # Only the lines that mention the request are worth a writer's attention;
        # the outline around them is what the agent reads for itself.
        _, _, hits = (excerpts.get(rel) or "").partition(_HIT_MARK)
        lines = " ".join(hits.split())
        points.append(StartingPoint(path=rel, lines=lines[:_EXCERPT_CHARS]))
    # A file that mentions the request beats one that only has a fitting name,
    # the code beats its tests, and a file with neither is not shown at all
    # unless nothing better was found.
    telling = [p for p in points if p.lines or p.path in leads]
    shown = telling or points[:3]
    shown.sort(key=lambda p: (
        p.path not in leads, not p.lines, domains.domain_of(p.path) in ("testing", "docs"),
    ))
    facts.starting_points = shown[:MAX_STARTING_POINTS]
    # A file that only shares one ordinary word with the request is chance; a
    # file found by its contents (two words, or a spelled-out name) is a lead.
    facts.content_match = any(p.path in leads for p in facts.starting_points)
    return facts
