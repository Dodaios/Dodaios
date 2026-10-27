"""Regression guard: what the product ships names it Dodaios and nothing else.

Two rules, checked over everything that ships or is drawn for it:

1. **No fictional-character coupling.** The assistant is not modelled on any
   film or comic character: no actor, no film franchise, no character owner,
   no character backstory. Scanned: the package (``dodaios/**``, including the
   frontend sources and locales) and ``art/``.
2. **No former product name in what a person reads or a model is told.** The
   product's name is ``branding.PRODUCT_NAME``. The earlier name survives only
   as a persistent identifier that keeps existing installations working (the
   ``LEGACY_*`` / ``PERSISTENT_*`` constants in ``dodaios.core.branding``, file
   and folder names, environment variables, wire headers, markers). Scanned:
   every locale string, the frontend code with its comments removed, the
   runtime string literals of the Python package (docstrings excluded), the
   text and data files the package ships, and ``art/``.

An identifier that must keep the earlier spelling goes into one of the
allowlists below with the reason it has to stay. Anything else is display
text or prompt text and uses the product's name, the assistant's name, or a
neutral word.
"""
from __future__ import annotations

import ast
import functools
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_PACKAGE = _REPO / "dodaios"
_ART = _REPO / "art"
_FRONTEND = _PACKAGE / "ui" / "web" / "frontend"
_FRONTEND_SRC = _FRONTEND / "src"
_LOCALES = _FRONTEND_SRC / "i18n" / "locales"

# Generated or vendored trees: built from the sources scanned here, or not ours.
_SKIPPED_DIRS = frozenset({"node_modules", "dist", "__pycache__", ".vite"})

_TEXT_SUFFIXES = frozenset(
    {".py", ".md", ".json", ".txt", ".toml", ".yaml", ".yml", ".html", ".css", ".ts", ".tsx",
     ".js", ".mjs"}
)

# --- Rule 1: character markers ---------------------------------------------------------

_CHARACTER_MARKERS = (
    "paul bettany",
    "bettany",
    "iron man",
    "iron-man",
    "ironman",
    "avengers",
    "tony stark",
    "tony-stark",
    "mr. stark",
    "mr stark",
    "stark industries",
    "stark's jarvis",
    "just a rather very intelligent",
    "j.a.r.v.i.s",
    "marvel",
)
_CHARACTER_RE = re.compile("|".join(re.escape(m) for m in _CHARACTER_MARKERS), re.IGNORECASE)

# Text that contains a marker word without referring to the character.
_CHARACTER_ALLOWED = (
    # A third-party video game in the games catalog (its id, title, install
    # folder and guide URLs).
    re.compile(r"marvel[ _-]rivals|\\+Marvel\\+Saved", re.IGNORECASE),
)

# --- Rule 2: the former product name ---------------------------------------------------

# Case-sensitive: lower-case ``jarvis`` is the spelling of identifiers (ids,
# surfaces, files, commands) and is not display text. ``\b`` treats ``_`` as a
# word character, so ``JARVIS_FOO`` env names and ``JarvisX`` symbols do not match.
_BARE_NAME_RE = re.compile(r"\b(?:Jarvis|JARVIS)\b|Personal[ -]Jarvis")
# Locale strings are display text through and through: any spelling counts.
_LOCALE_NAME_RE = re.compile(r"jarvis", re.IGNORECASE)

# Persistent identifiers that keep the earlier spelling, wherever they appear.
# Each is removed from the text before it is searched.
_LEGACY_IDENTIFIERS = (
    # Request headers of the local API; older clients and agents send them.
    re.compile(r"X-Jarvis-[A-Za-z-]+"),
    # The pairing line setup prompts from before the rename ask an agent to print.
    re.compile(r"JARVIS-CONNECT"),
    # Markers written into files of existing installations and found again there.
    re.compile(r"# (?:BEGIN|END) JARVIS HANDS"),
    re.compile(r"<<<(?:END-)?JARVIS-FOLDER>>>"),
    # Environment variables (also as a bare reserved prefix).
    re.compile(r"\bJARVIS_[A-Z0-9_]*"),
    # The user agent of the third-party REST plugins; its rename belongs to the
    # user-agent change of the release tooling, not to this guard.
    re.compile(r"Personal-Jarvis/1\.0"),
    # The name of the shared Microsoft sign-in registration: an administrator
    # approves the app under exactly this name on Microsoft's consent screen.
    re.compile(r"approve Personal Jarvis once"),
)

# Modules whose job is to name the earlier identifiers. Their string literals
# are not scanned; everything else in the package is.
_LEGACY_NAME_MODULES = {
    "dodaios/core/branding.py": "the persistent identity anchors and every LEGACY_* name",
    "dodaios/brain/identity.py": "tells a model the former names mean the app, not itself",
    "dodaios/memory/core_memory.py": "skips the persona name earlier versions stored",
    "dodaios/autostart/windows.py": "removes shortcuts and scripts of earlier versions",
    "dodaios/dodaiosx/paths.py": "keeps a capture folder created under the earlier name",
    "dodaios/society/roster.py": "the lead's persisted roster row name",
    "dodaios/society/credentials.py": "reserves the JARVIS* environment prefix",
}

# Shipped data files that are copies of stored configuration and change only
# with their evidence (``docs/marketplace/plugin-e2e-audit.json``).
_LEGACY_DATA_FILES = {
    "dodaios/clis/catalog/seed_catalog.json": (
        "the control CLI entry keeps its persistent name and parses the version "
        "line of earlier releases"
    ),
    "dodaios/skills/builtin/dodaios-doc-author/SKILL.md": (
        "its text is pinned by the retirement hash of the old jarvis-doc-author "
        "copy (dodaios.skills.bootstrap._RETIRED_SHIPPED_HASHES); edit it together "
        "with that retirement"
    ),
}


def _rel(path: Path) -> str:
    return path.relative_to(_REPO).as_posix()


def _walk(root: Path) -> Iterator[Path]:
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _SKIPPED_DIRS)
        for name in sorted(files):
            path = Path(folder) / name
            if path.suffix.lower() in _TEXT_SUFFIXES:
                yield path


# Several tests read the same files; opening one is the slow part on a box
# with on-access scanning, so each file is read once per session.
@functools.cache
def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# Plain substring checks first: a regex over every byte of the package is slow,
# and almost no file can match at all.
def _may_name_character(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _CHARACTER_MARKERS)


def _may_name_former_product(text: str) -> bool:
    return "Jarvis" in text or "JARVIS" in text


def _without_legacy_identifiers(text: str) -> str:
    for pattern in _LEGACY_IDENTIFIERS:
        text = pattern.sub("", text)
    return text


def _is_frontend_test(path: Path) -> bool:
    return ".test." in path.name or "__tests__" in path.parts or "test" in path.parts


def _strip_js_comments(src: str) -> str:
    """``src`` with ``//`` and ``/* */`` comments blanked (line count kept).

    A small scanner, not a parser: it knows string, template and regular
    expression literals well enough not to mistake their contents for comments.
    """
    out: list[str] = []
    i, n = 0, len(src)
    last_code = ""
    while i < n:
        c = src[i]
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i : j + 1])
            last_code = c
            i = j + 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            end = n if j < 0 else j + 2
            out.append("\n" * src.count("\n", i, end))
            i = end
            continue
        if c == "/" and (last_code == "" or last_code in "(,=:[!&|?{};+-*%<>~^"):
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    break
                j += 1
            out.append(src[i : j + 1])
            last_code = "/"
            i = j + 1
            continue
        out.append(c)
        if not c.isspace():
            last_code = c
        i += 1
    return "".join(out)


def _runtime_string_literals(tree: ast.AST) -> Iterator[ast.Constant]:
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            yield node


def _fail(rule: str, hits: list[str]) -> str:
    return f"{rule}:\n  " + "\n  ".join(sorted(hits))


# --- tests -----------------------------------------------------------------------------


def test_nothing_shipped_or_drawn_couples_the_assistant_to_a_character() -> None:
    hits: list[str] = []
    for root in (_PACKAGE, _ART):
        for path in _walk(root):
            text = _read(path)
            if text is None or not _may_name_character(text):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for allowed in _CHARACTER_ALLOWED:
                    line = allowed.sub("", line)
                if _CHARACTER_RE.search(line):
                    hits.append(f"{_rel(path)}:{lineno}: {line.strip()[:160]}")
    assert not hits, _fail("Fictional-character markers found", hits)


def test_no_locale_string_names_the_former_product() -> None:
    hits: list[str] = []
    for path in sorted(_LOCALES.rglob("*.json")):
        def walk(node: object, key: str) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{key}.{k}" if key else k)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{key}[{i}]")
            elif isinstance(node, str):
                if _LOCALE_NAME_RE.search(_without_legacy_identifiers(node)):
                    hits.append(f"{_rel(path)} {key}: {node[:160]}")  # noqa: B023

        walk(json.loads(path.read_text(encoding="utf-8")), "")
    assert not hits, _fail("Locale strings name the former product", hits)


def test_frontend_code_never_names_the_former_product() -> None:
    hits: list[str] = []
    sources = [p for p in _walk(_FRONTEND_SRC) if p.suffix in {".ts", ".tsx", ".css", ".html"}]
    sources.append(_FRONTEND / "index.html")
    for path in sources:
        if _is_frontend_test(path):
            continue
        text = _read(path)
        if text is None or not _may_name_former_product(text):
            continue
        code = _without_legacy_identifiers(_strip_js_comments(text))
        for lineno, line in enumerate(code.splitlines(), start=1):
            if _BARE_NAME_RE.search(line):
                hits.append(f"{_rel(path)}:{lineno}: {line.strip()[:160]}")
    assert not hits, _fail(
        "Frontend code names the former product (use PRODUCT_NAME / the assistant name)", hits
    )


def test_python_runtime_strings_never_name_the_former_product() -> None:
    hits: list[str] = []
    for path in _walk(_PACKAGE):
        rel = _rel(path)
        if path.suffix != ".py" or rel in _LEGACY_NAME_MODULES:
            continue
        text = _read(path)
        if text is None or not _may_name_former_product(text):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in _runtime_string_literals(tree):
            if _BARE_NAME_RE.search(_without_legacy_identifiers(node.value)):
                hits.append(f"{rel}:{node.lineno}: {node.value[:160]!r}")
    assert not hits, _fail(
        "Runtime strings name the former product (use branding.PRODUCT_NAME, the "
        "assistant name, or a LEGACY_* constant for a persistent identifier)",
        hits,
    )


def test_shipped_text_and_art_never_name_the_former_product() -> None:
    hits: list[str] = []
    roots = (_PACKAGE, _ART)
    for root in roots:
        for path in _walk(root):
            if path.suffix in {".py", ".ts", ".tsx"} or _FRONTEND_SRC in path.parents:
                continue  # covered above, with comments and docstrings set aside
            rel = _rel(path)
            if rel in _LEGACY_DATA_FILES:
                continue
            text = _read(path)
            if text is None or not _may_name_former_product(text):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _BARE_NAME_RE.search(_without_legacy_identifiers(line)):
                    hits.append(f"{rel}:{lineno}: {line.strip()[:160]}")
    assert not hits, _fail("Shipped text or art names the former product", hits)


def test_allowlists_name_only_files_that_exist() -> None:
    missing = [
        rel for rel in (*_LEGACY_NAME_MODULES, *_LEGACY_DATA_FILES) if not (_REPO / rel).is_file()
    ]
    assert not missing, f"Stale allowlist entries: {missing}"
