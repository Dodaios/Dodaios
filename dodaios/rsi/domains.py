"""Which domain a coding task belongs to, read from file paths.

A run is tagged twice. Before it starts, from the paths its brief names, so the
tag does not depend on what the agent then did. After it ends, from the files
the agent really changed, so a wrong first guess shows up in the record.
Statistics use the first tag: the second one depends on the work itself.

Matching is ordered and the first rule wins: testing, database, infra_ci, docs,
frontend, backend, other. A folder name alone never makes a file frontend
(``ui/web/server.py`` is a backend file); the extension does, or a frontend root
the caller knows about.

``refactoring`` comes from the wording of the brief and ``multi_repo`` from the
request as a whole (runs in two or more repositories), never from paths.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
from typing import Final

__all__ = [
    "DOMAINS",
    "FALLBACK",
    "classify_paths",
    "domain_of",
    "is_refactoring",
    "paths_in_text",
    "pre_classify",
    "primary",
]

DOMAINS: Final[tuple[str, ...]] = (
    "frontend",
    "backend",
    "database",
    "infra_ci",
    "testing",
    "docs",
    "refactoring",
    "multi_repo",
    "other",
)
FALLBACK: Final[str] = "other"

#: A domain needs this share of the changed paths to count for a run.
MIN_SHARE: Final[float] = 0.15
#: One path is enough for these: a single migration or workflow file matters.
ONE_PATH_IS_ENOUGH: Final[frozenset[str]] = frozenset({"database", "infra_ci"})

_TEST_DIRS: Final[frozenset[str]] = frozenset({"tests", "test", "__tests__", "e2e", "spec"})
_TEST_FILE = re.compile(
    r"(?:^test_.+\.py$|.+_test\.(?:py|go|rb|rs)$|.+\.(?:test|spec)\.[cm]?[jt]sx?$|^conftest\.py$)"
)
_DB_DIRS: Final[frozenset[str]] = frozenset({"migrations", "alembic", "prisma"})
_DB_SUFFIXES: Final[frozenset[str]] = frozenset({".sql", ".prisma"})
_INFRA_DIRS: Final[frozenset[str]] = frozenset(
    {".github", ".circleci", "terraform", "helm", "k8s", "kubernetes", "packaging", "deploy"}
)
_INFRA_FILE = re.compile(
    r"(?i)^(?:dockerfile.*|docker-compose.*\.ya?ml|\.gitlab-ci\.ya?ml|jenkinsfile|makefile"
    r"|azure-pipelines\.ya?ml|.+\.tf)$"
)
_DOC_DIRS: Final[frozenset[str]] = frozenset({"docs", "doc"})
_DOC_SUFFIXES: Final[frozenset[str]] = frozenset({".md", ".mdx", ".rst", ".adoc"})
#: Extensions that only a user interface has.
_UI_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss", ".sass", ".less", ".html"}
)
#: Script extensions that are frontend only inside a known frontend root.
_SCRIPT_SUFFIXES: Final[frozenset[str]] = frozenset({".ts", ".js", ".mjs", ".cjs"})
_CODE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".py", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".c", ".h", ".cc", ".cpp",
        ".hpp", ".swift", ".m", ".scala", ".ex", ".exs", ".sh", ".ps1",
    }
) | _SCRIPT_SUFFIXES

_REFACTORING = re.compile(
    r"(?i)\b(?:refa[ck]tor\w*|renam(?:e|es|ed|ing)|restructur\w+|dedup\w*|clean(?:ing)?[ -]?up"
    r"|simplif(?:y|ies|ied|ying)"
    r"|extract(?:s|ed|ing)? (?:a |the )?(?:function|method|module|class))\b"
)
#: A path as a brief writes it: an optional at-sign, folders, a file with an extension.
_PATH_TOKEN = re.compile(
    r"@?((?:[\w.\-]+/)+[\w.\-]+\.\w{1,6}|[\w\-]+\.(?:py|tsx?|jsx?|sql|md|go|rs))\b"
)


def _norm(path: str) -> PurePosixPath:
    text = str(path).replace("\\", "/")
    # Only a leading "./" goes: ".github" keeps its dot.
    while text.startswith("./"):
        text = text[2:]
    return PurePosixPath(text)


def domain_of(path: str, *, frontend_roots: Sequence[str] = ()) -> str:
    """The one domain of ``path`` (first matching rule)."""
    posix = _norm(path)
    name = posix.name
    dirs = {part.lower() for part in posix.parts[:-1]}
    suffix = posix.suffix.lower()
    if dirs & _TEST_DIRS or _TEST_FILE.match(name):
        return "testing"
    if dirs & _DB_DIRS or suffix in _DB_SUFFIXES:
        return "database"
    if dirs & _INFRA_DIRS or _INFRA_FILE.match(name) or "scripts/ci/" in f"{posix}/":
        return "infra_ci"
    if dirs & _DOC_DIRS or suffix in _DOC_SUFFIXES:
        return "docs"
    if suffix in _UI_SUFFIXES:
        return "frontend"
    if suffix in _SCRIPT_SUFFIXES and _under(posix, frontend_roots):
        return "frontend"
    if suffix in _CODE_SUFFIXES:
        return "backend"
    return FALLBACK


def _under(path: PurePosixPath, roots: Sequence[str]) -> bool:
    text = f"{path}/"
    return any(text.startswith(f"{_norm(root)}/") for root in roots if str(_norm(root)) != ".")


def classify_paths(paths: Iterable[str], *, frontend_roots: Sequence[str] = ()) -> list[str]:
    """Every domain a set of changed paths belongs to, largest share first.

    A domain counts from :data:`MIN_SHARE` of the paths on; one path is enough
    for the domains in :data:`ONE_PATH_IS_ENOUGH`. No path at all is no domain.
    """
    counts = Counter(domain_of(p, frontend_roots=frontend_roots) for p in paths if str(p).strip())
    total = sum(counts.values())
    if not total:
        return []
    kept = [
        domain
        for domain, count in counts.items()
        if count / total >= MIN_SHARE or domain in ONE_PATH_IS_ENOUGH
    ]
    # Largest share first; the fixed vocabulary order breaks a tie the same way every time.
    return sorted(kept, key=lambda d: (-counts[d], DOMAINS.index(d)))


def primary(paths: Iterable[str], *, frontend_roots: Sequence[str] = ()) -> str:
    """The domain with the largest share of ``paths``, or :data:`FALLBACK`."""
    found = classify_paths(paths, frontend_roots=frontend_roots)
    return found[0] if found else FALLBACK


def paths_in_text(text: str) -> list[str]:
    """Path-like tokens a brief names, in order, each once."""
    seen: list[str] = []
    for match in _PATH_TOKEN.finditer(text or ""):
        token = match.group(1)
        if token not in seen:
            seen.append(token)
    return seen


def is_refactoring(text: str) -> bool:
    """Whether a brief asks for a change of shape rather than of behaviour."""
    return bool(_REFACTORING.search(text or ""))


def pre_classify(brief: str, *, frontend_roots: Sequence[str] = ()) -> tuple[list[str], str, str]:
    """``(domains, primary_domain, source)`` of a task before it runs.

    ``source`` says where the answer came from: ``paths`` when the brief names
    files, ``wording`` when only its verbs gave a domain, ``fallback`` when
    nothing did. The primary domain is always a path domain or the fallback, so
    a refactoring of frontend code is still counted with the frontend.
    """
    named = paths_in_text(brief)
    domains = classify_paths(named, frontend_roots=frontend_roots)
    source = "paths" if domains else "fallback"
    main = domains[0] if domains else FALLBACK
    if is_refactoring(brief):
        domains = [*domains, "refactoring"]
        if source == "fallback":
            source = "wording"
    return domains, main, source
