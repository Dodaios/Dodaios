"""Sentence vectors of the vault's pages, kept in the wiki database.

The word index (``fts_index``) finds a page by the words it contains. This
index finds it by what it says: every page is cut into short passages, each
passage becomes one vector from :class:`~dodaios.memory.wiki.semantic_model.SemanticEncoder`,
and a question is answered by the passages whose vectors point the same way.

The two indexes are independent. They share the database file and the rules
for which files count as pages, nothing else: the word index is rebuilt on
every start because that is cheap, this one is only ever brought up to date,
because computing a vector is the expensive part. A page is encoded again only
when its modification time or the model changed.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dodaios.memory.wiki import fts_index
from dodaios.memory.wiki.semantic_model import EMBEDDING_DIMENSIONS, MODEL_REVISION

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_semantic_pages (
    path  TEXT PRIMARY KEY,
    mtime TEXT NOT NULL,
    model TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wiki_semantic_chunks (
    path      TEXT NOT NULL,
    chunk     INTEGER NOT NULL,
    title     TEXT NOT NULL,
    text      TEXT NOT NULL,
    embedding BLOB NOT NULL,
    PRIMARY KEY (path, chunk)
);
"""

#: A passage shorter than this is a stray mark, not a statement. Kept low on
#: purpose: "Age: 34" is a whole fact once the page title stands in front.
_MIN_PASSAGE_CHARS = 6

#: The model reads about this much text; a longer passage is cut so its tail
#: is not silently ignored.
_MAX_PASSAGE_CHARS = 480

#: Upper bound per page, so one pathological file (a pasted log) cannot take
#: the index over.
_MAX_PASSAGES_PER_PAGE = 200

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MARKUP_RE = re.compile(r"[*_`]+")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?;:])\s+")


@dataclass(frozen=True, slots=True)
class SyncResult:
    """What one pass over the vault did."""

    pages: int
    encoded: int
    removed: int
    failed: int = 0


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def passages(title: str, body: str) -> list[tuple[str, str]]:
    """Cut a page into ``(passage, text to encode)`` pairs.

    A wiki page is mostly a list of facts under a few headings. Each list
    item and each paragraph becomes its own passage, because one vector for a
    whole list of unrelated facts matches none of them well. The encoded text
    carries the page title and the heading, so "born 1961" under "Harald"
    is findable as a fact about Harald.
    """
    out: list[tuple[str, str]] = []
    heading = ""
    paragraph: list[str] = []
    in_code = False

    def emit(raw: str) -> None:
        text = _plain(raw)
        if len(text) < _MIN_PASSAGE_CHARS:
            return
        context = ": ".join(part for part in (title, heading) if part)
        for piece in _split_long(text):
            if len(out) < _MAX_PASSAGES_PER_PAGE:
                out.append((piece, f"{context}: {piece}" if context else piece))

    def flush() -> None:
        if paragraph:
            emit(" ".join(paragraph))
            paragraph.clear()

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped:
            flush()
            continue
        match = _HEADING_RE.match(stripped)
        if match:
            flush()
            found = _plain(match.group(1))
            heading = "" if found == title else found
            continue
        if _BULLET_RE.match(line):
            flush()
            emit(_BULLET_RE.sub("", line, count=1))
            continue
        paragraph.append(stripped)
    flush()
    return out


def upsert_page(
    conn: sqlite3.Connection, vault_root: Path, abs_path: Path, *, encoder: Any
) -> bool:
    """Encode one page and replace its rows. Returns False when it is skipped."""
    parsed = fts_index._parse_page_data(abs_path, vault_root)
    if parsed is None:
        return False
    rel_path, title, _frontmatter, body, mtime = parsed
    cut = passages(title, body)
    vectors = encoder.encode([encoded for _text, encoded in cut]) if cut else None
    conn.execute("DELETE FROM wiki_semantic_chunks WHERE path = ?", (rel_path,))
    if vectors is not None:
        conn.executemany(
            "INSERT INTO wiki_semantic_chunks (path, chunk, title, text, embedding) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (rel_path, index, title, text, vectors[index].tobytes())
                for index, (text, _encoded) in enumerate(cut)
            ],
        )
    conn.execute(
        "INSERT OR REPLACE INTO wiki_semantic_pages (path, mtime, model) VALUES (?, ?, ?)",
        (rel_path, mtime, MODEL_REVISION),
    )
    conn.commit()
    return True


def page_key(vault_root: Path, abs_path: Path) -> str:
    """The vault-relative path a page is stored under."""
    return fts_index._relative_posix(vault_root, abs_path)


def remove_page(conn: sqlite3.Connection, vault_root: Path, abs_path: Path) -> None:
    rel_path = page_key(vault_root, abs_path)
    conn.execute("DELETE FROM wiki_semantic_chunks WHERE path = ?", (rel_path,))
    conn.execute("DELETE FROM wiki_semantic_pages WHERE path = ?", (rel_path,))
    conn.commit()


def plan_sync(conn: sqlite3.Connection, vault_root: Path) -> tuple[list[str], int, int]:
    """Compare the index with the vault and clear out what no longer belongs.

    Returns ``(stale, pages, removed)``: the vault-relative paths that are new
    or changed and still have to be encoded, the number of pages in the vault,
    and how many pages' rows were dropped. The rows of pages that are gone, or
    that belong to a vault that is no longer the active one, are deleted here
    and now, before anything is encoded: a search must never see passages of
    the previous vault next to those of the new one.
    """
    ensure_schema(conn)
    known = {
        path: (mtime, model)
        for path, mtime, model in conn.execute(
            "SELECT path, mtime, model FROM wiki_semantic_pages"
        )
    }
    current = fts_index.vault_page_mtimes(vault_root)
    gone = sorted(set(known) - set(current))
    for rel_path in gone:
        conn.execute("DELETE FROM wiki_semantic_chunks WHERE path = ?", (rel_path,))
        conn.execute("DELETE FROM wiki_semantic_pages WHERE path = ?", (rel_path,))
    conn.commit()
    stale = [
        rel_path
        for rel_path, mtime in current.items()
        if known.get(rel_path) != (str(mtime), MODEL_REVISION)
    ]
    return stale, len(current), len(gone)


def sync_vault(
    conn: sqlite3.Connection,
    vault_root: Path,
    *,
    encoder: Any,
    progress: Callable[[int, int], None] | None = None,
) -> SyncResult:
    """Bring the index up to date with the vault on disk.

    Encodes the pages that are new or changed, drops the rows of pages that
    are gone, and leaves everything else untouched. A page that cannot be
    encoded is logged and counted, and the run goes on with the next one.
    ``progress`` receives stale pages handled so far and their total.
    """
    stale, pages, removed = plan_sync(conn, vault_root)
    encoded = failed = 0
    for done, rel_path in enumerate(stale, start=1):
        try:
            if upsert_page(conn, vault_root, vault_root / rel_path, encoder=encoder):
                encoded += 1
        except Exception as exc:  # noqa: BLE001 - one bad page must not end the run
            conn.rollback()
            failed += 1
            log.warning("Semantic wiki index: %s could not be encoded: %s", rel_path, exc)
        if progress is not None:
            progress(done, len(stale))
    return SyncResult(pages=pages, encoded=encoded, removed=removed, failed=failed)


def load_passages(
    conn: sqlite3.Connection, *, path: str | None = None
) -> tuple[Any, list[tuple[str, str, str]]]:
    """Stored vectors as one matrix, with ``(path, title, text)`` per row.

    Every page by default; only the passages of one page when *path* is given.
    """
    import numpy as np

    rows: list[tuple[str, str, str]] = []
    blobs: list[bytes] = []
    width = EMBEDDING_DIMENSIONS * 4
    query = "SELECT path, title, text, embedding FROM wiki_semantic_chunks"
    cursor = (
        conn.execute(f"{query} ORDER BY path, chunk")
        if path is None
        else conn.execute(f"{query} WHERE path = ? ORDER BY chunk", (path,))
    )
    for row_path, title, text, blob in cursor:
        if len(blob) != width:
            continue  # written by another model size; the next sync replaces it
        rows.append((row_path, title, text))
        blobs.append(blob)
    matrix = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(
        len(rows), EMBEDDING_DIMENSIONS
    )
    return matrix, rows


def counts(conn: sqlite3.Connection) -> tuple[int, int]:
    """``(pages, passages)`` currently in the index."""
    pages = conn.execute("SELECT COUNT(*) FROM wiki_semantic_pages").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM wiki_semantic_chunks").fetchone()[0]
    return int(pages), int(chunks)


def _plain(text: str) -> str:
    """Markdown to the words a reader sees."""
    text = _WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1).rsplit("/", 1)[-1], text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MARKUP_RE.sub("", text)
    return _SPACE_RE.sub(" ", text).strip()


def _split_long(text: str) -> list[str]:
    """Cut *text* at sentence ends into pieces the model reads in full."""
    if len(text) <= _MAX_PASSAGE_CHARS:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END_RE.split(text):
        while len(sentence) > _MAX_PASSAGE_CHARS:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:_MAX_PASSAGE_CHARS])
            sentence = sentence[_MAX_PASSAGE_CHARS:]
        if current and len(current) + 1 + len(sentence) > _MAX_PASSAGE_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


__all__ = [
    "SyncResult",
    "counts",
    "ensure_schema",
    "load_passages",
    "page_key",
    "passages",
    "plan_sync",
    "remove_page",
    "sync_vault",
    "upsert_page",
]
