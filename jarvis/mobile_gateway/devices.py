"""Paired phones and pending pairing codes, kept in one small JSON file.

Neither a pairing code nor a device key is ever stored: only their SHA-256.
The file is rewritten atomically and only when something changes (a code is
issued, a phone pairs, a device is revoked), so the CLI and the running
gateway can share it without a database.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEVICES_NAME = "devices.json"

#: Unambiguous alphabet for codes a person may have to type (no 0/O, 1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
#: Wrong codes in a row before every pending code is thrown away.
MAX_FAILED_PAIRINGS = 5
_MAX_DEVICE_NAME = 64


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Device:
    device_id: str
    name: str
    key_sha256: str
    paired_at: float
    revoked: bool = False


@dataclass(slots=True)
class PairingResult:
    device_id: str
    token: str


@dataclass(slots=True)
class _State:
    devices: dict[str, Device] = field(default_factory=dict)
    # code hash -> expiry (epoch seconds)
    pending: dict[str, float] = field(default_factory=dict)


class DeviceStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._path = data_dir / DEVICES_NAME
        self._lock = threading.Lock()
        self._failed_pairings = 0
        self.last_seen: dict[str, float] = {}

    # -- persistence ---------------------------------------------------

    def _load(self) -> _State:
        try:
            raw: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:  # first run: no device file yet
            return _State()
        devices = {d["device_id"]: Device(**d) for d in raw.get("devices", []) if "device_id" in d}
        pending = {str(k): float(v) for k, v in raw.get("pending", {}).items()}
        return _State(devices=devices, pending=pending)

    def _save(self, state: _State) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "devices": [asdict(d) for d in state.devices.values()],
            "pending": state.pending,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    # -- pairing -------------------------------------------------------

    def issue_code(self, ttl_s: float) -> str:
        """A fresh one-time code, valid for ``ttl_s`` seconds."""
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        now = time.time()
        with self._lock:
            state = self._load()
            state.pending = {h: exp for h, exp in state.pending.items() if exp > now}
            state.pending[_sha256(code)] = now + ttl_s
            self._save(state)
        return code

    def pair(self, code: str, device_name: str) -> PairingResult | None:
        """Redeem ``code`` for a new device key, or ``None`` if it is not valid."""
        normalized = "".join(code.split()).upper()
        now = time.time()
        with self._lock:
            state = self._load()
            live = {h: exp for h, exp in state.pending.items() if exp > now}
            wanted = _sha256(normalized)
            match = next((h for h in live if hmac.compare_digest(h, wanted)), None)
            if match is None:
                self._failed_pairings += 1
                if self._failed_pairings >= MAX_FAILED_PAIRINGS:
                    live = {}
                    self._failed_pairings = 0
                if live != state.pending:
                    state.pending = live
                    self._save(state)
                return None
            del live[match]
            self._failed_pairings = 0
            device_id = secrets.token_hex(8)
            token = secrets.token_urlsafe(32)
            name = " ".join(device_name.split())[:_MAX_DEVICE_NAME] or "Phone"
            state.pending = live
            state.devices[device_id] = Device(
                device_id=device_id,
                name=name,
                key_sha256=_sha256(token),
                paired_at=now,
            )
            self._save(state)
        return PairingResult(device_id=device_id, token=token)

    # -- devices -------------------------------------------------------

    def authenticate(self, credential: str) -> Device | None:
        """The device behind a ``<device_id>.<token>`` credential, if valid."""
        device_id, sep, token = credential.partition(".")
        if not sep or not device_id or not token:
            return None
        with self._lock:
            device = self._load().devices.get(device_id)
        if device is None or device.revoked:
            return None
        if not hmac.compare_digest(device.key_sha256, _sha256(token)):
            return None
        self.last_seen[device_id] = time.time()
        return device

    def devices(self) -> list[Device]:
        with self._lock:
            return list(self._load().devices.values())

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            state = self._load()
            device = state.devices.get(device_id)
            if device is None or device.revoked:
                return False
            device.revoked = True
            self._save(state)
        return True
