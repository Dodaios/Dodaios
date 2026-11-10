"""Who the person has written to from here before.

A recipient becomes known the moment a send to them actually ran: by then a
person approved it (the ``new_recipient`` hard limit saw to that) or the
address was already known. The ledger is a small JSON file under the data dir;
addresses are compared case-insensitively and without surrounding ``<>``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_ADDRESS = re.compile(r"<([^<>]+)>")


def normalize_recipient(value: str) -> str:
    """``"Ada <Ada@Example.com>"`` -> ``ada@example.com``; a handle keeps its text."""
    text = (value or "").strip()
    match = _ADDRESS.search(text)
    if match:
        text = match.group(1).strip()
    return text.lower()


class KnownRecipients:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._known: dict[str, int] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:  # nobody has been written to yet: an empty ledger
            return
        except (OSError, ValueError) as exc:
            log.warning("known recipients: could not read %s: %s", self._path, exc)
            return
        items = raw.get("recipients") if isinstance(raw, dict) else None
        if isinstance(items, dict):
            self._known = {str(k): int(v or 0) for k, v in items.items()}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"recipients": self._known}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("known recipients: could not write %s: %s", self._path, exc)

    def knows(self, value: str) -> bool:
        key = normalize_recipient(value)
        if not key:
            return True
        with self._lock:
            self._load()
            return key in self._known

    def knows_all(self, values: Iterable[str]) -> bool:
        return all(self.knows(v) for v in values)

    def remember(self, values: Iterable[str]) -> list[str]:
        """Mark ``values`` as written to; returns the ones that were new."""
        now = int(time.time() * 1000)
        added: list[str] = []
        with self._lock:
            self._load()
            for value in values:
                key = normalize_recipient(value)
                if key and key not in self._known:
                    self._known[key] = now
                    added.append(key)
            if added:
                self._save()
        return added

    def forget(self, value: str) -> bool:
        key = normalize_recipient(value)
        with self._lock:
            self._load()
            if key not in self._known:
                return False
            del self._known[key]
            self._save()
            return True

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            self._load()
            return [
                {"recipient": k, "first_ms": v}
                for k, v in sorted(self._known.items(), key=lambda kv: kv[1])
            ]


_DEFAULT: list[KnownRecipients] = []


def known_recipients() -> KnownRecipients:
    """The process-wide ledger under the data dir (built on first use)."""
    if not _DEFAULT:
        from dodaios.core.config import DATA_DIR

        _DEFAULT.append(KnownRecipients(Path(DATA_DIR) / "trust" / "recipients.json"))
    return _DEFAULT[0]


def set_known_recipients(ledger: KnownRecipients | None) -> None:
    """Swap the process-wide ledger (tests, a custom data dir)."""
    _DEFAULT.clear()
    if ledger is not None:
        _DEFAULT.append(ledger)


__all__ = ["KnownRecipients", "known_recipients", "normalize_recipient", "set_known_recipients"]
