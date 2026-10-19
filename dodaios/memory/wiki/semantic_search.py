"""``SemanticVaultSearch`` — find wiki pages by meaning, next to the word search.

``VaultSearch`` answers "which pages contain these words". This class answers
"which pages say something like this question", in whatever language either
side is written. It returns the same ``SearchHit`` records, so a caller can
show or merge the two result lists without knowing which engine found what.

The word search does not depend on this module in any way. Semantic search is
an optional second engine: off unless the user switched it on, silent when its
model is missing, busy or broken. Every public method degrades to "no semantic
hits" instead of raising, and a caller on the turn path never waits for it.

One instance is active per process (:func:`activate`, :func:`get_active`): the
turn injector, the recall tool, the wiki routes and the file watcher all reach
the same model and the same in-memory copy of the vectors.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dodaios.memory.wiki import semantic_index
from dodaios.memory.wiki.db_path import resolve_wiki_db_path
from dodaios.memory.wiki.search import SearchHit
from dodaios.memory.wiki.semantic_model import SemanticEncoder

log = logging.getLogger(__name__)

#: Cosine similarity below which two texts are unrelated for this model, even
#: when one is the other's nearest neighbour. The terminal search in the
#: Agentic IDE uses the same model and the same floor.
MIN_SIMILARITY = 0.29

_SNIPPET_CHARS = 200

#: Pages a deliberate lookup may gain from the semantic engine on top of the
#: word search's own hits.
_EXTRA_HITS = 3


class SemanticVaultSearch:
    """Meaning-based search over one vault.

    Parameters
    ----------
    vault_root:
        Absolute path of the vault whose pages are indexed.
    db_path:
        The wiki database. Defaults to the shared ``data/jarvis.db``.
    encoder:
        Anything with ``encode(texts, wait=...)``, ``warm_up()`` and
        ``close()``. Tests pass a fake; production builds the real model.
    """

    def __init__(
        self,
        vault_root: Path,
        *,
        db_path: Path | None = None,
        data_dir: str | Path | None = None,
        encoder: Any = None,
    ) -> None:
        self._root = Path(vault_root)
        self._db_path = db_path or resolve_wiki_db_path(data_dir)
        self._encoder = encoder if encoder is not None else SemanticEncoder(data_dir)
        # One writer at a time: a full sync and a watcher update must not
        # interleave their deletes and inserts for the same page.
        self._write_lock = threading.Lock()
        self._passages: tuple[Any, list[tuple[str, str, str]]] | None = None

    @property
    def vault_root(self) -> Path:
        return self._root

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        min_score: float = MIN_SIMILARITY,
        wait: bool = False,
    ) -> list[SearchHit]:
        """Up to *k* pages, best first, each with its best-matching passage.

        ``score`` is the cosine similarity of that passage, comparable across
        calls. ``wait=False`` (the default, and the turn path's setting)
        returns ``[]`` at once while the model is loading or busy.
        """
        if not query or not query.strip():
            return []
        try:
            loaded = self._passages
            if loaded is None:
                if not wait:
                    # Reading every vector from disk is not turn-path work.
                    return []
                loaded = self.refresh()
            matrix, rows = loaded
            if not rows:
                return []
            vector = self._encoder.encode([query], wait=wait)
            if vector is None:
                return []
            scores = matrix @ vector[0]
        except Exception as exc:  # noqa: BLE001 - semantic search never breaks a caller
            log.warning("Semantic wiki search failed: %s", exc)
            return []

        best: dict[str, int] = {}
        for index in scores.argsort()[::-1]:
            score = float(scores[index])
            if score < min_score or len(best) >= k:
                break
            best.setdefault(rows[index][0], int(index))
        hits: list[SearchHit] = []
        for rel_path, index in best.items():
            _path, title, text = rows[index]
            hits.append(
                SearchHit(
                    title=title or Path(rel_path).stem,
                    path=self._root / rel_path,
                    snippet=_clip(text),
                    score=round(float(scores[index]), 4),
                    preview=_clip(text),
                )
            )
        return hits

    def warm_up(self) -> None:
        """Load the model and the vectors. For a background thread at boot."""
        try:
            self._encoder.warm_up()
            self.refresh()
        except Exception as exc:  # noqa: BLE001 - the next search retries
            log.debug("Semantic wiki search warm-up skipped: %s", exc)

    def sync(
        self, *, progress: Callable[[int, int], None] | None = None
    ) -> semantic_index.SyncResult:
        """Encode new and changed pages. Minutes on a first run: never on a turn.

        The write lock is taken per page, not for the run: a page the watcher
        saw change waits for one page at most, not for a whole first run. A
        page that cannot be encoded is logged and counted and the run goes on.
        ``progress`` may raise to end the run early; nothing is left half
        written, because every page is its own transaction.
        """
        encoded = failed = 0
        with self._connect() as conn:
            with self._write_lock:
                stale, pages, removed = semantic_index.plan_sync(conn, self._root)
            for done, rel_path in enumerate(stale, start=1):
                try:
                    with self._write_lock:
                        if semantic_index.upsert_page(
                            conn, self._root, self._root / rel_path, encoder=self._encoder
                        ):
                            encoded += 1
                except Exception as exc:  # noqa: BLE001 - one bad page must not end the run
                    conn.rollback()
                    failed += 1
                    log.warning("Semantic wiki index: %s could not be encoded: %s", rel_path, exc)
                if progress is not None:
                    progress(done, len(stale))
        self.refresh()
        return semantic_index.SyncResult(
            pages=pages, encoded=encoded, removed=removed, failed=failed
        )

    def index_page(self, abs_path: Path) -> None:
        """Re-encode one page after it changed on disk."""
        with self._write_lock, self._connect() as conn:
            semantic_index.ensure_schema(conn)
            semantic_index.upsert_page(conn, self._root, abs_path, encoder=self._encoder)
            self._reload_page(conn, abs_path)

    def remove_page(self, abs_path: Path) -> None:
        with self._write_lock, self._connect() as conn:
            semantic_index.ensure_schema(conn)
            semantic_index.remove_page(conn, self._root, abs_path)
            self._reload_page(conn, abs_path)

    def refresh(self) -> tuple[Any, list[tuple[str, str, str]]]:
        """Read every vector from the database into memory.

        Under the write lock, so a reload can never publish a snapshot that is
        older than a page update which finished while it was reading.
        """
        with self._write_lock, self._connect() as conn:
            semantic_index.ensure_schema(conn)
            loaded = semantic_index.load_passages(conn)
            self._passages = loaded
        return loaded

    def _reload_page(self, conn: sqlite3.Connection, abs_path: Path) -> None:
        """Swap one page's passages in the in-memory copy; the caller holds the lock.

        One saved file must not cost a reload of the whole vault's vectors.
        """
        loaded = self._passages
        if loaded is None:
            return  # nothing in memory yet; the first reader loads everything
        import numpy as np

        matrix, rows = loaded
        rel_path = semantic_index.page_key(self._root, abs_path)
        keep = [index for index, row in enumerate(rows) if row[0] != rel_path]
        fresh_matrix, fresh_rows = semantic_index.load_passages(conn, path=rel_path)
        self._passages = (
            np.concatenate([matrix[keep], fresh_matrix], axis=0),
            [rows[index] for index in keep] + fresh_rows,
        )

    def counts(self) -> tuple[int, int]:
        """``(pages, passages)`` in the index; ``(0, 0)`` when unreadable."""
        try:
            with self._connect() as conn:
                semantic_index.ensure_schema(conn)
                return semantic_index.counts(conn)
        except Exception as exc:  # noqa: BLE001 - a status read must not raise
            log.debug("Semantic wiki index count failed: %s", exc)
            return 0, 0

    def close(self) -> None:
        """Release the model and the in-memory vectors."""
        self._passages = None
        try:
            self._encoder.close()
        except Exception as exc:  # noqa: BLE001 - nothing to salvage on shutdown
            log.debug("Semantic wiki encoder close failed: %s", exc)

    def _connect(self) -> _Connection:
        return _Connection(self._db_path)


class _Connection:
    """A short-lived connection that is closed, not just committed, on exit."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        return self._conn

    def __exit__(self, *_exc: object) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _clip(text: str) -> str:
    return text if len(text) <= _SNIPPET_CHARS else text[: _SNIPPET_CHARS - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# The one active instance
# ---------------------------------------------------------------------------

_active: SemanticVaultSearch | None = None
_active_guard = threading.Lock()


def get_active() -> SemanticVaultSearch | None:
    """The running semantic search, or ``None`` while it is switched off."""
    return _active


def activate(
    vault_root: Path,
    *,
    db_path: Path | None = None,
    data_dir: str | Path | None = None,
    encoder: Any = None,
) -> SemanticVaultSearch:
    """Make semantic search available for *vault_root*; idempotent per vault."""
    global _active
    with _active_guard:
        current = _active
        if current is not None and current.vault_root == Path(vault_root):
            return current
        if current is not None:
            current.close()
        _active = SemanticVaultSearch(
            vault_root, db_path=db_path, data_dir=data_dir, encoder=encoder
        )
        return _active


def deactivate() -> None:
    """Switch semantic search off and free the model's memory."""
    global _active
    with _active_guard:
        current, _active = _active, None
    if current is not None:
        current.close()


def with_semantic_hits(
    hits: list[SearchHit],
    query: str,
    *,
    vault_root: Path,
    wait: bool = False,
) -> list[SearchHit]:
    """*hits* from the word search, plus pages found by meaning only.

    The word search's hits keep their order and are never dropped. Returns
    *hits* unchanged while semantic search is off or serves another vault.
    """
    active = get_active()
    if active is None or active.vault_root != Path(vault_root):
        return hits
    seen = {hit.path for hit in hits}
    extra = [
        hit
        for hit in active.search(query, k=_EXTRA_HITS, wait=wait)
        if hit.path not in seen
    ]
    return [*hits, *extra]


__all__ = [
    "MIN_SIMILARITY",
    "SemanticVaultSearch",
    "activate",
    "deactivate",
    "get_active",
    "with_semantic_hits",
]
