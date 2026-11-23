"""The values in effect: what was learned, kept in ``params.db``, read on every call.

``get(name)`` is what the code calls where a constant used to be. It answers,
in this order:

1. inside a benchmark run, the run's overlay (its own value, or the shipped
   default when the run measures the assistant as it ships);
2. the learned value, when one is stored and still valid;
3. the shipped default.

A learned value is written only by the self-change registry, through
:class:`ParamStore` (the handler of the ``parameter`` surface), so it has a
version, a diff and a byte-exact rollback like every self-change. The stored
text is small JSON: the value, and ``base``, the shipped default it was learned
against.

**Updates.** The app ships new defaults, renames parameters and removes them.
A stored value never breaks a start and is never deleted by an update:

* the shipped default changed since it was learned: the value stays in effect
  and is listed as ``restale`` so the next night measures it first;
* the parameter was renamed: the value is served under the new name;
* the parameter no longer exists, or the value is outside today's limits: the
  entry rests (``dormant``) and has no effect, until a version knows it again.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dodaios.rsi import overlay
from dodaios.rsi.storage import Db, Schema, open_db

from .catalog import INDEX, Index
from .spec import Param, ParamError, Value

__all__ = [
    "DB_NAME",
    "Entry",
    "ParamStore",
    "get",
    "install",
    "installed",
    "learned",
    "release",
    "text_for",
    "values",
]

log = logging.getLogger(__name__)

DB_NAME: Final = "params.db"
SCHEMA: Final = Schema(
    "params.db",
    (
        """
        CREATE TABLE IF NOT EXISTS params (
            name        TEXT PRIMARY KEY,
            text        TEXT NOT NULL,
            updated_ms  INTEGER NOT NULL
        );
        """,
    ),
)

LIVE: Final = "live"
RESTALE: Final = "restale"
DORMANT: Final = "dormant"


def text_for(param: Param, value: Any) -> str:
    """The canonical text the registry stores for ``value``."""
    data = {"base": param.default, "value": param.coerce(value)}
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class Entry:
    """One stored value and what it means in this version of the app."""

    #: The name it was stored under (possibly an earlier one).
    stored_as: str
    #: Today's name; "" when no parameter of this version matches.
    name: str
    value: Any
    #: The shipped default it was learned against.
    base: Any
    #: ``live``, ``restale`` (in effect, measure again first) or ``dormant`` (no effect).
    status: str
    why: str = ""

    @property
    def in_effect(self) -> bool:
        return self.status in (LIVE, RESTALE)

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name or self.stored_as,
            "stored_as": self.stored_as,
            "value": self.value,
            "base": self.base,
            "status": self.status,
            "why": self.why,
        }


class ParamStore:
    """Where the registry writes learned values; the self-change handler of ``parameter``."""

    def __init__(self, path: Path | str, *, index: Index = INDEX) -> None:
        self.index = index
        self._db: Db = open_db(path, SCHEMA)
        self._lock = threading.RLock()
        self._entries: dict[str, Entry] = {}
        self._values: dict[str, Value] = {}
        self._load()

    @property
    def readonly(self) -> bool:
        """True when a newer app wrote the file: values apply, nothing is written."""
        return self._db.readonly

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------ loading

    def _entry(self, stored_as: str, text: str) -> Entry:
        try:
            data = json.loads(text)
            value, base = data["value"], data.get("base")
        except (ValueError, KeyError, TypeError):  # kept and shown as a resting entry
            return Entry(stored_as, "", None, None, DORMANT, "the stored text is unreadable")
        param = self.index.get(stored_as)
        if param is None:
            why = "this version has no such parameter"
            return Entry(stored_as, "", value, base, DORMANT, why)
        try:
            value = param.coerce(value)
        except ParamError as exc:  # the reason is kept on the entry, which the report lists
            return Entry(stored_as, param.name, value, base, DORMANT, str(exc))
        if base != param.default:
            why = f"learned against the default {base!r}, which is now {param.default!r}"
            return Entry(stored_as, param.name, value, base, RESTALE, why)
        return Entry(stored_as, param.name, value, base, LIVE)

    def _load(self) -> None:
        with self._lock, self._db.lock:
            rows = self._db.conn.execute("SELECT name, text FROM params ORDER BY name").fetchall()
        entries: dict[str, Entry] = {}
        values: dict[str, Value] = {}
        for row in rows:
            entry = self._entry(str(row["name"]), str(row["text"]))
            entries[entry.stored_as] = entry
            # A value stored under today's name wins over one under an earlier name.
            if entry.in_effect and (entry.stored_as == entry.name or entry.name not in values):
                values[entry.name] = entry.value
        with self._lock:
            self._entries, self._values = entries, values

    # --------------------------------------------------- the handler protocol

    def _stored_name(self, target: str) -> str:
        """The row a target means: its own, or the row an earlier name left behind."""
        with self._lock:
            if target in self._entries:
                return target
            today = self.index.canonical(target)
            for entry in self._entries.values():
                if today is not None and entry.name == today:
                    return entry.stored_as
        return target

    def read(self, target: str) -> str | None:
        name = self._stored_name(target)
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT text FROM params WHERE name = ?", (name,)
            ).fetchone()
        return str(row["text"]) if row is not None else None

    def write(self, target: str, text: str | None) -> None:
        """Store ``text`` for ``target``, or remove the entry.

        Only the shape is checked here. Whether a stored value has an effect is
        decided on reading (:meth:`_entry`), so a rollback can always put back
        the exact earlier text, also one that today's limits would not allow:
        it then rests instead of applying.
        """
        if self._db.readonly:
            raise ParamError("a newer version of the app wrote the parameters; this one only reads")
        name = self._stored_name(target)
        if text is not None:
            try:
                json.loads(text)["value"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ParamError("a parameter value is JSON with a 'value'") from exc
        with self._db.lock:
            if text is None:
                self._db.conn.execute("DELETE FROM params WHERE name = ?", (name,))
            else:
                self._db.conn.execute(
                    "INSERT INTO params (name, text, updated_ms) VALUES (?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET text = excluded.text, "
                    "updated_ms = excluded.updated_ms",
                    (name, text, int(time.time() * 1000)),
                )
            self._db.conn.commit()
        self._load()

    # ------------------------------------------------------------- reading

    def value(self, name: str) -> Value | None:
        """The learned value in effect for today's name ``name``, or ``None``."""
        return self._values.get(name)

    def values(self) -> dict[str, Value]:
        with self._lock:
            return dict(self._values)

    def entries(self) -> list[Entry]:
        with self._lock:
            return list(self._entries.values())


# ----------------------------------------------------------- the live values

_store: ParamStore | None = None
_stores: dict[str, ParamStore] = {}
_stores_lock = threading.Lock()


def install(data_dir: Path | str | None) -> ParamStore | None:
    """Make the store of ``data_dir`` the one ``get`` reads. ``None`` goes back to defaults."""
    global _store
    if data_dir is None:
        _store = None
        return None
    path = str(Path(data_dir) / DB_NAME)
    with _stores_lock:
        found = _stores.get(path)
        if found is None:
            found = _stores[path] = ParamStore(path)
    _store = found
    return found


def installed() -> ParamStore | None:
    return _store


def release(store: ParamStore) -> None:
    """Close a store and forget it (a sandbox, a test). The app never releases its own."""
    global _store
    with _stores_lock:
        for path, found in list(_stores.items()):
            if found is store:
                del _stores[path]
    if _store is store:
        _store = None
    store.close()


def get(name: str, session_id: str = "") -> Any:
    """The value in effect for ``name``. Cheap: two dictionary lookups."""
    store = _store
    index = store.index if store is not None else INDEX
    param = index.by_name(name)
    running = overlay.current(session_id)
    if running is not None:
        if param.name in running.params:
            return param.coerce(running.params[param.name])
        if running.factory:
            return param.default
    if store is not None:
        found = store.value(param.name)
        if found is not None:
            return found
    return param.default


def learned() -> dict[str, Value]:
    """Every learned value in effect, by today's name."""
    return _store.values() if _store is not None else {}


def values(session_id: str = "") -> dict[str, Any]:
    """Every parameter with the value in effect right now (the fingerprint hashes this)."""
    index = _store.index if _store is not None else INDEX
    return {param.name: get(param.name, session_id) for param in index.params}
