"""The server's record: how a client finds the running server and talks to it.

One small JSON file, written atomically, readable only by its owner on POSIX
(it may carry the token clients authenticate with)::

    {"pid": 4242, "state": "ready", "port": 47821, "url": null,
     "token": "...", "version": "1.2.0", "started_at": 1764000000.0,
     "info": {}}

The record says WHERE the server is. Whether it is alive is answered by the
instance lock (:mod:`daemonkit.lock`), never by the record alone: a record can
survive a crash, a lock cannot.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

STARTING = "starting"
READY = "ready"
STOPPING = "stopping"
_STATES = frozenset({STARTING, READY, STOPPING})


@dataclass(frozen=True)
class ServerRecord:
    """What a running server tells its clients about itself."""

    pid: int
    state: str = STARTING
    port: int | None = None
    url: str | None = None
    token: str | None = None
    version: str | None = None
    started_at: float = 0.0
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.state == READY

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: object) -> ServerRecord | None:
        """Parse a record; ``None`` for anything that is not one."""
        if not isinstance(data, dict):
            return None
        try:
            pid = int(data.get("pid") or 0)
            port = data.get("port")
            info = data.get("info")
            record = cls(
                pid=pid,
                state=str(data.get("state") or STARTING),
                port=int(port) if port not in (None, "") else None,
                url=str(data["url"]) if data.get("url") else None,
                token=str(data["token"]) if data.get("token") else None,
                version=str(data["version"]) if data.get("version") else None,
                started_at=float(data.get("started_at") or 0.0),
                info=dict(info) if isinstance(info, dict) else {},
            )
        except (TypeError, ValueError):
            return None
        if record.pid <= 0 or record.state not in _STATES:
            return None
        return record


def new_token() -> str:
    """A fresh random token for a server's clients (256 bits)."""
    return secrets.token_urlsafe(32)


def token_matches(presented: str | None, expected: str | None) -> bool:
    """Constant-time comparison; an empty expected token never matches."""
    if not expected or presented is None:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def write_record(path: Path, record: ServerRecord) -> None:
    """Replace the record at ``path`` atomically (owner-only on POSIX)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record.to_json(), indent=2, sort_keys=True).encode("utf-8")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    _replace(tmp, path)


def read_record(path: Path) -> ServerRecord | None:
    """The record at ``path``, or ``None`` when there is no readable one."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.debug("daemonkit: record %s unreadable: %s", path, exc)
        return None
    try:
        return ServerRecord.from_json(json.loads(text))
    except ValueError:
        # A half-written file cannot happen (atomic replace); a hand-edited
        # one can, and it names no server.
        log.debug("daemonkit: record %s is not JSON", path)
        return None


def remove_record(path: Path, *, pid: int | None = None) -> bool:
    """Delete the record, but only if it still belongs to ``pid`` (when given)."""
    path = Path(path)
    if pid is not None:
        current = read_record(path)
        if current is not None and current.pid != pid:
            return False
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError as exc:
        log.warning("daemonkit: record %s not removed: %s", path, exc)
        return False
    return True


def _replace(src: Path, dst: Path, *, attempts: int = 20) -> None:
    """``os.replace`` that waits out a reader on Windows (sharing violation)."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                with contextlib.suppress(OSError):
                    src.unlink()
                raise
            time.sleep(0.025)
