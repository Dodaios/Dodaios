"""The personal memory vault: one SQLite file that holds what the assistant
knows about the user (ADR-0044).

Rules the store enforces:

- A memory row is never rewritten. An edit or a changed fact is a new row
  that supersedes the old one; the old one is closed with a date.
- Forgetting purges the text everywhere (row, search index, audit log) and
  leaves a tombstone, so an inferred write can never bring it back.
- Secrets are refused at the door.
"""

from __future__ import annotations

import json
import logging
import math
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dodaios.memory.vault.models import (
    KINDS,
    ORIGINS,
    SENSITIVITIES,
    Memory,
    SearchHit,
    WriteResult,
    content_hash,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory (
    id            TEXT PRIMARY KEY,
    content_hash  TEXT NOT NULL,
    kind          TEXT NOT NULL,
    text          TEXT NOT NULL,
    scope         TEXT NOT NULL DEFAULT 'global',
    valid_from    TEXT,
    valid_to      TEXT,
    recorded_at   TEXT NOT NULL,
    expired_at    TEXT,
    supersedes_id TEXT,
    origin        TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT '{}',
    confidence    REAL NOT NULL DEFAULT 1.0,
    sensitivity   TEXT NOT NULL DEFAULT 'normal',
    pinned        INTEGER NOT NULL DEFAULT 0,
    use_count     INTEGER NOT NULL DEFAULT 0,
    last_used_at  TEXT
);
CREATE INDEX IF NOT EXISTS memory_hash ON memory(content_hash);
CREATE INDEX IF NOT EXISTS memory_kind ON memory(kind);
CREATE INDEX IF NOT EXISTS memory_supersedes ON memory(supersedes_id);
CREATE TABLE IF NOT EXISTS entity (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    name_key   TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_entity (
    memory_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    PRIMARY KEY (memory_id, entity_id)
);
CREATE INDEX IF NOT EXISTS memory_entity_by_entity ON memory_entity(entity_id);
CREATE TABLE IF NOT EXISTS audit (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    action    TEXT NOT NULL,
    memory_id TEXT,
    detail    TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS tombstone (
    id           TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    forgotten_at TEXT NOT NULL,
    reason       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS tombstone_hash ON tombstone(content_hash);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    id UNINDEXED,
    text,
    entities,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

_COLUMNS = (
    "id, content_hash, kind, text, scope, valid_from, valid_to, recorded_at, "
    "expired_at, supersedes_id, origin, source, confidence, sensitivity, pinned, "
    "use_count, last_used_at"
)

_CURRENT = "m.expired_at IS NULL AND (m.valid_to IS NULL OR m.valid_to > ?)"

_TOKEN = re.compile(r"\w+", re.UNICODE)

#: Order of kinds in the always-on profile block.
_PROFILE_ORDER = ("profile", "preference", "procedural", "relationship", "project", "reference")

_PROFILE_HEADINGS = {
    "profile": "About the user",
    "preference": "Preferences",
    "procedural": "Standing instructions",
    "relationship": "People",
    "project": "Current projects",
    "reference": "Where things are",
    "pinned": "Pinned",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _new_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"mem_{stamp}_{secrets.token_hex(6)}"


def _secret_check(text: str) -> bool:
    # The secret detector still lives with the wiki; ADR-0044 chunk 6 moves it.
    from dodaios.memory.wiki.secret_guard import contains_secret

    return contains_secret(text)


def _clean_entities(names: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for name in names:
        label = " ".join(str(name).split())
        if label and label.casefold() not in seen:
            seen[label.casefold()] = label
    return tuple(seen.values())


class MemoryVault:
    """Read/write handle for ``vault.db``. Safe to share between threads."""

    def __init__(self, path: str | Path, *, clock: Callable[[], str] = utc_now) -> None:
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            if str(path) != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(_SCHEMA)
            self._db.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._db.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('vault_id', ?)",
                (f"vault_{secrets.token_hex(8)}",),
            )
            self._db.commit()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> MemoryVault:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def vault_id(self) -> str:
        row = self._db.execute("SELECT value FROM meta WHERE key='vault_id'").fetchone()
        return str(row["value"])

    def now(self) -> str:
        return self._clock()

    # -- writes ------------------------------------------------------------

    def remember(
        self,
        text: str,
        kind: str = "profile",
        *,
        entities: Sequence[str] = (),
        origin: str = "user",
        source: dict[str, Any] | None = None,
        scope: str = "global",
        confidence: float = 1.0,
        sensitivity: str = "normal",
        pinned: bool = False,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> WriteResult:
        """Store one memory, or return the identical one that is already current."""
        text = " ".join(text.split())
        self._validate(text, kind, origin, sensitivity)
        if _secret_check(text):
            return WriteResult("refused", reason="looks like a secret")
        digest = content_hash(kind, text)
        with self._lock:
            now = self.now()
            existing = self._current_by_hash(digest, scope, now)
            if existing is not None:
                if pinned and not existing.pinned:
                    self.pin(existing.id, True)
                    existing = self.get(existing.id)
                return WriteResult("existing", existing)
            if self._is_tombstoned(digest):
                if origin != "user":
                    return WriteResult("blocked", reason="the user asked to forget this")
                self._db.execute("DELETE FROM tombstone WHERE content_hash=?", (digest,))
            if kind == "ephemeral" and valid_to is None:
                raise ValueError("an ephemeral memory needs valid_to")
            memory = Memory(
                id=_new_id(),
                content_hash=digest,
                kind=kind,
                text=text,
                recorded_at=now,
                origin=origin,
                entities=_clean_entities(entities),
                scope=scope,
                valid_from=valid_from or now,
                valid_to=valid_to,
                source=dict(source or {}),
                confidence=max(0.0, min(1.0, float(confidence))),
                sensitivity=sensitivity,
                pinned=pinned,
            )
            self._insert(memory)
            self._audit("add", memory.id, {"kind": kind, "origin": origin})
            self._db.commit()
            return WriteResult("added", memory)

    def supersede(
        self,
        old_id: str,
        text: str,
        *,
        kind: str | None = None,
        entities: Sequence[str] | None = None,
        origin: str = "user",
        source: dict[str, Any] | None = None,
        confidence: float | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> WriteResult:
        """Replace a memory with a newer version and close the old one."""
        text = " ".join(text.split())
        with self._lock:
            old = self.get(old_id)
            if old is None:
                raise KeyError(old_id)
            now = self.now()
            if not old.is_current(now):
                raise ValueError(f"{old_id} is no longer current")
            new_kind = kind or old.kind
            self._validate(text, new_kind, origin, old.sensitivity)
            if _secret_check(text):
                return WriteResult("refused", reason="looks like a secret")
            digest = content_hash(new_kind, text)
            if digest == old.content_hash:
                return WriteResult("existing", old)
            if self._is_tombstoned(digest) and origin != "user":
                return WriteResult("blocked", reason="the user asked to forget this")
            memory = Memory(
                id=_new_id(),
                content_hash=digest,
                kind=new_kind,
                text=text,
                recorded_at=now,
                origin=origin,
                entities=_clean_entities(old.entities if entities is None else entities),
                scope=old.scope,
                valid_from=valid_from or now,
                valid_to=valid_to,
                supersedes_id=old.id,
                source=dict(source or {}),
                confidence=old.confidence if confidence is None else confidence,
                sensitivity=old.sensitivity,
                pinned=old.pinned,
            )
            self._close(old.id, valid_to=memory.valid_from, expired_at=now)
            self._insert(memory)
            self._audit("supersede", memory.id, {"replaces": old.id, "origin": origin})
            self._db.commit()
            return WriteResult("superseded", memory)

    def invalidate(self, memory_id: str, *, reason: str = "", when: str | None = None) -> bool:
        """Mark a fact as no longer true without a replacement ("I quit that job")."""
        with self._lock:
            memory = self.get(memory_id)
            now = self.now()
            if memory is None or not memory.is_current(now):
                return False
            self._close(memory_id, valid_to=when or now, expired_at=None)
            self._audit("invalidate", memory_id, {"reason": reason})
            self._db.commit()
            return True

    def forget(self, memory_id: str, *, reason: str = "user request") -> int:
        """Erase a memory and every earlier and later version of it.

        Returns how many rows were erased. The text is gone from the row, the
        search index and the audit log; a tombstone per version remains.
        """
        with self._lock:
            chain = self._chain_ids(memory_id)
            if not chain:
                return 0
            now = self.now()
            for mid in chain:
                row = self._db.execute(
                    "SELECT content_hash FROM memory WHERE id=?", (mid,)
                ).fetchone()
                self._db.execute(
                    "INSERT OR REPLACE INTO tombstone(id, content_hash, forgotten_at, reason) "
                    "VALUES (?, ?, ?, ?)",
                    (mid, row["content_hash"], now, reason),
                )
                self._purge(mid)
            self._audit("forget", None, {"count": len(chain), "reason": reason})
            self._db.commit()
            return len(chain)

    def pin(self, memory_id: str, pinned: bool = True) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE memory SET pinned=? WHERE id=?", (1 if pinned else 0, memory_id)
            )
            if cur.rowcount:
                self._audit("pin" if pinned else "unpin", memory_id, {})
            self._db.commit()
            return bool(cur.rowcount)

    def mark_used(self, memory_ids: Iterable[str]) -> None:
        ids = list(memory_ids)
        if not ids:
            return
        with self._lock:
            now = self.now()
            self._db.executemany(
                "UPDATE memory SET use_count = use_count + 1, last_used_at=? WHERE id=?",
                [(now, mid) for mid in ids],
            )
            self._db.commit()

    # -- reads -------------------------------------------------------------

    def get(self, memory_id: str) -> Memory | None:
        row = self._db.execute(
            f"SELECT {_COLUMNS} FROM memory WHERE id=?",  # noqa: S608
            (memory_id,),
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def list(
        self,
        *,
        kind: str | None = None,
        scope: str | None = None,
        include_closed: bool = False,
        limit: int | None = None,
    ) -> list[Memory]:
        """Memories, newest first. Current ones only unless asked otherwise."""
        where: list[str] = []
        args: list[Any] = []
        if not include_closed:
            where.append(_CURRENT)
            args.append(self.now())
        if kind:
            where.append("m.kind = ?")
            args.append(kind)
        if scope:
            where.append("m.scope IN ('global', ?)")
            args.append(scope)
        sql = f"SELECT {_prefixed()} FROM memory m"  # noqa: S608
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.recorded_at DESC, m.id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._row_to_memory(r) for r in self._db.execute(sql, args)]

    def history(self, memory_id: str) -> list[Memory]:
        """Every version of a memory, oldest first."""
        ids = self._chain_ids(memory_id)
        found = {m.id: m for m in (self.get(i) for i in ids) if m is not None}
        # Follow the supersede links; time alone cannot order two versions
        # recorded in the same second.
        depth: dict[str, int] = {}

        def _depth(mid: str) -> int:
            if mid not in depth:
                prev = found[mid].supersedes_id
                depth[mid] = 0 if prev not in found else _depth(prev) + 1
            return depth[mid]

        return sorted(found.values(), key=lambda m: (_depth(m.id), m.recorded_at, m.id))

    def about(self, entity: str, *, include_closed: bool = True) -> list[Memory]:
        """Every memory that names an entity, oldest first ("where did I live before?")."""
        rows = self._db.execute(
            f"SELECT {_prefixed()} FROM memory m "  # noqa: S608
            "JOIN memory_entity me ON me.memory_id = m.id "
            "JOIN entity e ON e.id = me.entity_id WHERE e.name_key = ? "
            "ORDER BY m.recorded_at, m.id",
            (entity.casefold().strip(),),
        )
        memories = [self._row_to_memory(r) for r in rows]
        if include_closed:
            return memories
        now = self.now()
        return [m for m in memories if m.is_current(now)]

    def entities(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT e.id, e.name, e.created_at, COUNT(me.memory_id) AS uses FROM entity e "
            "LEFT JOIN memory_entity me ON me.entity_id = e.id GROUP BY e.id ORDER BY e.name"
        )
        return [dict(r) for r in rows]

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        kinds: Sequence[str] | None = None,
        scope: str | None = None,
        include_closed: bool = False,
    ) -> list[SearchHit]:
        """Keyword search with entity and recency boosts. Best hit first.

        Each word matches as a prefix, any word may match (OR), and BM25
        ranks the rows; a hit that names an entity from the query, or that
        is pinned or recent, moves up.
        """
        tokens = [t for t in _TOKEN.findall(query.casefold()) if len(t) > 1]
        if not tokens:
            return []
        match = " OR ".join(f'"{t}"*' for t in dict.fromkeys(tokens))
        where = ["memory_fts MATCH ?"]
        args: list[Any] = [match]
        if not include_closed:
            where.append(_CURRENT)
            args.append(self.now())
        if kinds:
            where.append(f"m.kind IN ({','.join('?' * len(kinds))})")
            args.extend(kinds)
        if scope:
            where.append("m.scope IN ('global', ?)")
            args.append(scope)
        sql = (
            f"SELECT {_prefixed()}, bm25(memory_fts) AS rank FROM memory_fts "  # noqa: S608
            "JOIN memory m ON m.id = memory_fts.id WHERE "
            + " AND ".join(where)
            + " ORDER BY rank LIMIT ?"
        )
        args.append(max(limit * 4, 20))
        try:
            rows = self._db.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            log.warning("memory vault: search failed for %r", query, exc_info=True)
            return []
        query_words = set(tokens)
        hits: list[SearchHit] = []
        for row in rows:
            memory = self._row_to_memory(row)
            score = -float(row["rank"])  # bm25 is lower-is-better
            entity_words = {w for e in memory.entities for w in _TOKEN.findall(e.casefold())}
            if entity_words & query_words:
                score *= 1.5
            if memory.pinned:
                score *= 1.2
            score *= _recency(memory.recorded_at, self.now())
            hits.append(SearchHit(memory, score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def profile_block(self, *, max_chars: int = 2400, scope: str | None = None) -> str:
        """The always-on summary for the system prompt.

        Pinned memories first, then the stable kinds in a fixed order. Episodes
        and sensitive memories stay out; they reach the model through search.
        A budget cut drops whole lines, oldest last-used first.
        """
        current = [
            m
            for m in self.list(scope=scope)
            if m.sensitivity == "normal" and (m.pinned or m.kind in _PROFILE_ORDER)
        ]
        if not current:
            return ""
        groups: dict[str, list[Memory]] = {}
        for m in current:
            groups.setdefault("pinned" if m.pinned else m.kind, []).append(m)
        lines: list[str] = []
        budget = max_chars
        for key in ("pinned", *_PROFILE_ORDER):
            items = sorted(
                groups.get(key, []),
                key=lambda m: (m.use_count, m.recorded_at),
                reverse=True,
            )
            if not items:
                continue
            heading = f"{_PROFILE_HEADINGS[key]}:"
            if len(heading) + 1 > budget:
                break
            section = [heading]
            used = len(heading) + 1
            for m in items:
                line = f"- {m.text}"
                if used + len(line) + 1 > budget:
                    break
                section.append(line)
                used += len(line) + 1
            if len(section) > 1:
                lines.extend(section)
                budget -= used
        return "\n".join(lines)

    def stats(self) -> dict[str, Any]:
        now = self.now()
        by_kind = {
            r["kind"]: r["n"]
            for r in self._db.execute(
                f"SELECT kind, COUNT(*) AS n FROM memory m WHERE {_CURRENT} GROUP BY kind",  # noqa: S608
                (now,),
            )
        }
        total = self._db.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        forgotten = self._db.execute("SELECT COUNT(*) FROM tombstone").fetchone()[0]
        return {
            "current": sum(by_kind.values()),
            "by_kind": by_kind,
            "all_versions": total,
            "forgotten": forgotten,
            "entities": self._db.execute("SELECT COUNT(*) FROM entity").fetchone()[0],
        }

    def audit_log(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT seq, at, action, memory_id, detail FROM audit ORDER BY seq"
        if limit:
            sql += f" DESC LIMIT {int(limit)}"
        rows = [dict(r) for r in self._db.execute(sql)]
        for r in rows:
            r["detail"] = json.loads(r["detail"] or "{}")
        return rows

    def tombstones(self) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self._db.execute(
                "SELECT id, content_hash, forgotten_at, reason FROM tombstone "
                "ORDER BY forgotten_at, id"
            )
        ]

    # -- import support (used by vault.portable) ----------------------------

    def has(self, memory_id: str) -> bool:
        return (
            self._db.execute("SELECT 1 FROM memory WHERE id=?", (memory_id,)).fetchone() is not None
        )

    def has_hash_version(self, memory: Memory) -> bool:
        """True if the same statement is already here, current or as the same version."""
        row = self._db.execute(
            f"SELECT 1 FROM memory m WHERE m.content_hash=? AND m.scope=? "  # noqa: S608
            f"AND (m.recorded_at=? OR {_CURRENT})",
            (memory.content_hash, memory.scope, memory.recorded_at, self.now()),
        ).fetchone()
        return row is not None

    def insert_imported(self, memory: Memory) -> bool:
        """Insert a memory exactly as exported. False if it is known or forgotten."""
        with self._lock:
            if self.has(memory.id) or self._is_tombstoned_id(memory.id):
                return False
            self._validate(memory.text, memory.kind, memory.origin, memory.sensitivity)
            if _secret_check(memory.text):
                return False
            self._insert(memory)
            self._audit("import", memory.id, {"kind": memory.kind})
            self._db.commit()
            return True

    def apply_tombstone(self, memory_id: str, digest: str, forgotten_at: str, reason: str) -> None:
        with self._lock:
            if self.has(memory_id):
                self._purge(memory_id)
            for row in self._db.execute(
                "SELECT id FROM memory WHERE content_hash=?", (digest,)
            ).fetchall():
                self._purge(row["id"])
            self._db.execute(
                "INSERT OR IGNORE INTO tombstone(id, content_hash, forgotten_at, reason) "
                "VALUES (?, ?, ?, ?)",
                (memory_id, digest, forgotten_at, reason),
            )
            self._db.commit()

    # -- internals ---------------------------------------------------------

    def _validate(self, text: str, kind: str, origin: str, sensitivity: str) -> None:
        if not text:
            raise ValueError("a memory needs text")
        if len(text) > 2000:
            raise ValueError("a memory is one statement; split long text")
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        if origin not in ORIGINS:
            raise ValueError(f"unknown origin {origin!r}")
        if sensitivity not in SENSITIVITIES:
            raise ValueError(f"unknown sensitivity {sensitivity!r}")

    def _insert(self, m: Memory) -> None:
        self._db.execute(
            f"INSERT INTO memory({_COLUMNS}) VALUES ({','.join('?' * 17)})",  # noqa: S608
            (
                m.id,
                m.content_hash,
                m.kind,
                m.text,
                m.scope,
                m.valid_from,
                m.valid_to,
                m.recorded_at,
                m.expired_at,
                m.supersedes_id,
                m.origin,
                m.source_json(),
                m.confidence,
                m.sensitivity,
                1 if m.pinned else 0,
                m.use_count,
                m.last_used_at,
            ),
        )
        self._db.execute(
            "INSERT INTO memory_fts(id, text, entities) VALUES (?, ?, ?)",
            (m.id, m.text, " ".join(m.entities)),
        )
        for name in m.entities:
            key = name.casefold()
            row = self._db.execute("SELECT id FROM entity WHERE name_key=?", (key,)).fetchone()
            if row is None:
                entity_id = f"ent_{secrets.token_hex(6)}"
                self._db.execute(
                    "INSERT INTO entity(id, name, name_key, created_at) VALUES (?, ?, ?, ?)",
                    (entity_id, name, key, m.recorded_at),
                )
            else:
                entity_id = row["id"]
            self._db.execute(
                "INSERT OR IGNORE INTO memory_entity(memory_id, entity_id) VALUES (?, ?)",
                (m.id, entity_id),
            )

    def _close(self, memory_id: str, *, valid_to: str | None, expired_at: str | None) -> None:
        self._db.execute(
            "UPDATE memory SET valid_to = COALESCE(?, valid_to), expired_at = ? WHERE id=?",
            (valid_to, expired_at, memory_id),
        )

    def _purge(self, memory_id: str) -> None:
        self._db.execute("DELETE FROM memory WHERE id=?", (memory_id,))
        self._db.execute("DELETE FROM memory_fts WHERE id=?", (memory_id,))
        self._db.execute("DELETE FROM memory_entity WHERE memory_id=?", (memory_id,))
        self._db.execute(
            "UPDATE audit SET detail='{}', memory_id=NULL WHERE memory_id=?", (memory_id,)
        )
        self._db.execute("DELETE FROM entity WHERE id NOT IN (SELECT entity_id FROM memory_entity)")
        # Rows that pointed at a forgotten version keep pointing at nothing.
        self._db.execute("UPDATE memory SET supersedes_id=NULL WHERE supersedes_id=?", (memory_id,))

    def _chain_ids(self, memory_id: str) -> list[str]:
        if not self.has(memory_id):
            return []
        seen = {memory_id}
        frontier = [memory_id]
        while frontier:
            mid = frontier.pop()
            row = self._db.execute("SELECT supersedes_id FROM memory WHERE id=?", (mid,)).fetchone()
            linked = [row["supersedes_id"]] if row and row["supersedes_id"] else []
            linked += [
                r["id"]
                for r in self._db.execute("SELECT id FROM memory WHERE supersedes_id=?", (mid,))
            ]
            for other in linked:
                if other not in seen:
                    seen.add(other)
                    frontier.append(other)
        return sorted(seen)

    def _current_by_hash(self, digest: str, scope: str, now: str) -> Memory | None:
        row = self._db.execute(
            f"SELECT {_prefixed()} FROM memory m "  # noqa: S608 - constant columns
            f"WHERE m.content_hash=? AND m.scope=? AND {_CURRENT}",
            (digest, scope, now),
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def _is_tombstoned(self, digest: str) -> bool:
        return (
            self._db.execute("SELECT 1 FROM tombstone WHERE content_hash=?", (digest,)).fetchone()
            is not None
        )

    def _is_tombstoned_id(self, memory_id: str) -> bool:
        return (
            self._db.execute("SELECT 1 FROM tombstone WHERE id=?", (memory_id,)).fetchone()
            is not None
        )

    def _audit(self, action: str, memory_id: str | None, detail: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT INTO audit(at, action, memory_id, detail) VALUES (?, ?, ?, ?)",
            (self.now(), action, memory_id, json.dumps(detail, ensure_ascii=False)),
        )

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        names = [
            r["name"]
            for r in self._db.execute(
                "SELECT e.name FROM memory_entity me JOIN entity e ON e.id = me.entity_id "
                "WHERE me.memory_id=? ORDER BY e.name",
                (row["id"],),
            )
        ]
        return Memory(
            id=row["id"],
            content_hash=row["content_hash"],
            kind=row["kind"],
            text=row["text"],
            recorded_at=row["recorded_at"],
            origin=row["origin"],
            entities=tuple(names),
            scope=row["scope"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            expired_at=row["expired_at"],
            supersedes_id=row["supersedes_id"],
            source=json.loads(row["source"] or "{}"),
            confidence=float(row["confidence"]),
            sensitivity=row["sensitivity"],
            pinned=bool(row["pinned"]),
            use_count=int(row["use_count"]),
            last_used_at=row["last_used_at"],
        )


def _prefixed() -> str:
    return ", ".join(f"m.{c.strip()}" for c in _COLUMNS.split(","))


def _recency(recorded_at: str, now: str) -> float:
    """1.0 for today, sliding to 0.7 for memories a few years old."""
    try:
        age_days = (
            datetime.fromisoformat(now) - datetime.fromisoformat(recorded_at)
        ).total_seconds() / 86400
    except ValueError:  # an unparsable stamp gets no recency penalty, by design
        return 1.0
    return 0.7 + 0.3 * math.exp(-max(age_days, 0.0) / 365.0)
