"""What the last subscription voice start proved about a ChatGPT account.

Signing in proves a login, not voice access: an account can be connected and
still be refused by the voice route (issue #828). The settings page reads this
record so "connected" is never shown as "voice works" after the server said no.

The record explains; it never gates. Every call still asks the server, and a
successful start replaces an older refusal. Nothing here is a credential: the
account is stored as a digest of its remote id and plan, so a new
login or a changed plan makes an old record stop matching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_FILE_NAME = "live_subscription_voice.json"
_MAX_ACCOUNTS = 64
_MAX_BYTES = 256 * 1024
#: Refusals that describe the account itself. Waiting does not change them.
ACCOUNT_REFUSALS = frozenset({"voice_not_offered", "access_denied"})
_lock = threading.Lock()


def identity(remote_account_id: str, plan: str) -> str:
    """A non-reversible tag for one login and its plan."""
    if not remote_account_id:
        return ""
    digest = hashlib.sha256(f"{remote_account_id}\0{plan.strip().lower()}".encode())
    return digest.hexdigest()[:24]


def _path() -> Path:
    # The app's data directory, which a test run redirects to a temporary one.
    from dodaios.core import config

    return Path(config.DATA_DIR) / _FILE_NAME


def _load(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # No record yet, or an unreadable one: voice is unverified.
    return data if isinstance(data, dict) else {}


def record(account_id: str, account_identity: str, code: str) -> None:
    """Remember a successful start (``"ready"``) or an account refusal.

    Any other failure code says nothing lasting about the account and leaves
    the record as it is.
    """
    if not account_id or not account_identity:
        return
    if code != "ready" and code not in ACCOUNT_REFUSALS:
        return
    path = _path()
    with _lock:
        data = _load(path)
        data[account_id] = {
            "identity": account_identity,
            "code": code,
            "at": int(time.time()),
        }
        while len(data) > _MAX_ACCOUNTS:
            oldest = min(data, key=lambda key: int((data[key] or {}).get("at", 0) or 0))
            del data[oldest]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".live-voice-", suffix=".tmp", dir=path.parent
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError:
            # The settings hint is optional; a call never depends on it.
            log.warning("Subscription voice status could not be saved.", exc_info=True)


def read(account_id: str, account_identity: str) -> str:
    """Return ``"ready"``, an account refusal code, or ``""`` when unverified."""
    if not account_id or not account_identity:
        return ""
    with _lock:
        entry = _load(_path()).get(account_id)
    if not isinstance(entry, dict) or entry.get("identity") != account_identity:
        return ""
    code = entry.get("code")
    if code == "ready" or code in ACCOUNT_REFUSALS:
        return str(code)
    return ""
