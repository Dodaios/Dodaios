"""``self_build_code.db``: what the code builder knows about the person's projects.

The build ledger (``self_build.db``) holds one row per build. This file holds
the knowledge the code builder works from, so nothing is recomputed from
scratch on every pass:

* ``briefs``: one project brief per repository checkout, stored in parts, each
  part with the key it was built for (a HEAD, a tree, file stamps). A pass
  rebuilds only the parts whose key changed.
* ``issues``: the triage verdict per issue and the ``updatedAt`` it was given
  for, so an unchanged issue is not triaged twice.
* ``profiles``: per repository, what happened to the loop's pull requests
  (merged as they were, changed before merge, closed) and the lessons of
  failed runs. Triage and the next prompt read it.
* ``polls``: when a repository was last asked for issues.

Plain ``sqlite3`` behind one lock, like the ledger; async callers wrap calls in
``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Final

from ..ledger import now_ms
from ..records import dumps

DB_NAME: Final[str] = "self_build_code.db"

_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS briefs (
    project_key TEXT PRIMARY KEY,
    folder      TEXT NOT NULL,
    repo        TEXT NOT NULL DEFAULT '',
    parts_json  TEXT NOT NULL DEFAULT '{}',
    keys_json   TEXT NOT NULL DEFAULT '{}',
    updated_ms  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS issues (
    repo       TEXT NOT NULL,
    number     INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    verdict    TEXT NOT NULL DEFAULT '',
    reason     TEXT NOT NULL DEFAULT '',
    issue_json TEXT NOT NULL DEFAULT '{}',
    seen_ms    INTEGER NOT NULL,
    PRIMARY KEY (repo, number)
);
CREATE TABLE IF NOT EXISTS profiles (
    repo       TEXT PRIMARY KEY,
    json       TEXT NOT NULL DEFAULT '{}',
    updated_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS polls (
    repo    TEXT PRIMARY KEY,
    last_ms INTEGER NOT NULL
);
"""

#: How many merged / closed pull requests and lessons a profile remembers.
PROFILE_KEEP: Final[int] = 30


def _loads(raw: Any, default: Any) -> Any:
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError):  # a damaged row reads as empty, the next write repairs it
        return default
    return value if isinstance(value, type(default)) else default


def repo_key(repo: str) -> str:
    """GitHub names are case-insensitive: one row per repository."""
    return repo.strip().lower()


class CodeStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=5.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ briefs

    def brief(self, project_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT folder, repo, parts_json, keys_json, updated_ms FROM briefs"
                " WHERE project_key = ?",
                (project_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "project_key": project_key,
            "folder": str(row[0]),
            "repo": str(row[1]),
            "parts": _loads(row[2], {}),
            "keys": _loads(row[3], {}),
            "updated_ms": int(row[4]),
        }

    def briefs(self) -> list[dict[str, Any]]:
        with self._lock:
            keys = [r[0] for r in self._conn.execute("SELECT project_key FROM briefs").fetchall()]
        return [b for b in (self.brief(k) for k in keys) if b is not None]

    def put_brief(
        self,
        project_key: str,
        *,
        folder: str,
        repo: str,
        parts: dict[str, Any],
        keys: dict[str, str],
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO briefs (project_key, folder, repo, parts_json, keys_json, updated_ms)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(project_key) DO UPDATE SET"
                " folder = excluded.folder, repo = excluded.repo,"
                " parts_json = excluded.parts_json, keys_json = excluded.keys_json,"
                " updated_ms = excluded.updated_ms",
                (project_key, folder, repo, dumps(parts), dumps(keys), now_ms()),
            )
            self._conn.commit()

    def set_part(self, project_key: str, part: str, value: Any, key: str = "") -> None:
        """Replace one part of a stored brief (the issue poll writes ``github``)."""
        with self._lock:
            current = self.brief(project_key)
            if current is None:
                return
            parts = dict(current["parts"])
            keys = dict(current["keys"])
            parts[part] = value
            keys[part] = key or str(now_ms())
            self.put_brief(
                project_key, folder=current["folder"], repo=current["repo"], parts=parts, keys=keys
            )

    # ------------------------------------------------------------ issues

    def issue(self, repo: str, number: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT updated_at, verdict, reason, issue_json, seen_ms FROM issues"
                " WHERE repo = ? AND number = ?",
                (repo_key(repo), int(number)),
            ).fetchone()
        if row is None:
            return None
        return {
            "updated_at": str(row[0]),
            "verdict": str(row[1]),
            "reason": str(row[2]),
            "issue": _loads(row[3], {}),
            "seen_ms": int(row[4]),
        }

    def put_issue(
        self,
        repo: str,
        number: int,
        *,
        updated_at: str,
        verdict: str,
        reason: str,
        issue: dict[str, Any],
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO issues (repo, number, updated_at, verdict, reason, issue_json,"
                " seen_ms) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(repo, number) DO UPDATE SET"
                " updated_at = excluded.updated_at, verdict = excluded.verdict,"
                " reason = excluded.reason, issue_json = excluded.issue_json,"
                " seen_ms = excluded.seen_ms",
                (
                    repo_key(repo),
                    int(number),
                    updated_at,
                    verdict,
                    reason[:300],
                    dumps(issue),
                    now_ms(),
                ),
            )
            self._conn.commit()

    # ------------------------------------------------------------ profiles

    def profile(self, repo: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT json FROM profiles WHERE repo = ?", (repo_key(repo),)
            ).fetchone()
        profile = _loads(row[0], {}) if row else {}
        for name in ("merged", "closed", "lessons"):
            if not isinstance(profile.get(name), list):
                profile[name] = []
        return profile

    def add_to_profile(self, repo: str, field: str, entry: dict[str, Any]) -> dict[str, Any]:
        """Append ``entry`` to one list of the repository's profile (newest kept)."""
        with self._lock:
            profile = self.profile(repo)
            items = [e for e in profile.get(field, []) if isinstance(e, dict)]
            items.append({**entry, "ms": now_ms()})
            profile[field] = items[-PROFILE_KEEP:]
            self._conn.execute(
                "INSERT INTO profiles (repo, json, updated_ms) VALUES (?, ?, ?)"
                " ON CONFLICT(repo) DO UPDATE SET json = excluded.json,"
                " updated_ms = excluded.updated_ms",
                (repo_key(repo), dumps(profile), now_ms()),
            )
            self._conn.commit()
            return profile

    # ------------------------------------------------------------ polls

    def last_poll(self, repo: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_ms FROM polls WHERE repo = ?", (repo_key(repo),)
            ).fetchone()
        return int(row[0]) if row else 0

    def set_poll(self, repo: str, stamp: int | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO polls (repo, last_ms) VALUES (?, ?)"
                " ON CONFLICT(repo) DO UPDATE SET last_ms = excluded.last_ms",
                (repo_key(repo), int(stamp if stamp is not None else now_ms())),
            )
            self._conn.commit()
