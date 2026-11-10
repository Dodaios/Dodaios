"""Paired phones: one-time pairing codes, revocable device tokens, push subscriptions.

A pairing code is minted on the desktop (shown as a QR code), lives five minutes
in memory and is spent by exactly one redemption. The redemption answers with a
device token the phone keeps; only its SHA-256 digest is stored here, so the
devices file never holds a usable credential. Revoking a device deletes its
digest and its push subscription; the phone's next call answers 401.

The file lives in the app's data directory (``mobile/devices.json``) and is
written atomically. Codes and failed attempts are process-local.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dodaios.core.paths import user_data_dir

#: How long a shown pairing code can be redeemed.
CODE_TTL_S = 300.0
#: Wrong codes before every open code is dropped (a LAN guesser gets nowhere).
MAX_FAILED_ATTEMPTS = 20
#: Codes are typeable: no 0/O or 1/I, upper case only.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 10
#: Marks a phone token apart from the control key and session tokens (not a secret).
_TOKEN_PREFIX = "mdt_"  # noqa: S105 — a format marker, not a credential


class PairingError(Exception):
    """A pairing or token problem with the HTTP status it maps to."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class PushSubscription(BaseModel):
    endpoint: str = Field(min_length=8, max_length=2048)
    p256dh: str = Field(min_length=16, max_length=256)
    auth: str = Field(min_length=8, max_length=128)


class PairedDevice(BaseModel):
    id: str
    name: str = Field(max_length=120)
    digest: str
    created_at: float
    last_seen_at: float = 0.0
    user_agent: str = Field(default="", max_length=300)
    push: PushSubscription | None = None

    def public(self) -> dict[str, Any]:
        """What the settings page shows: never the digest, never the endpoint."""
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "push": self.push is not None,
        }


class DevicesState(BaseModel):
    devices: list[PairedDevice] = Field(default_factory=list)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def normalize_code(code: str) -> str:
    """What the person typed or the QR carried, as the store spells it."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


class MobileDevices:
    """Durable device records plus process-local pairing codes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_data_dir() / "mobile" / "devices.json"
        self._lock = threading.RLock()
        self._codes: dict[str, float] = {}
        self._failed = 0

    # ------------------------------------------------------------ storage

    def _read(self) -> DevicesState:
        try:
            return DevicesState.model_validate_json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:  # no phone paired yet is the first-run state
            return DevicesState()
        except (ValueError, OSError) as exc:
            raise PairingError("The paired phones could not be read.", 500) from exc

    def _write(self, state: DevicesState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".devices-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(state.model_dump_json(indent=2))
            os.replace(name, self.path)
        except OSError:
            try:
                os.unlink(name)
            except OSError:  # the temp file is already gone; nothing to clean
                pass
            raise

    # ------------------------------------------------------------- codes

    def _sweep_codes(self, now: float) -> None:
        for code, expires in list(self._codes.items()):
            if expires <= now:
                self._codes.pop(code, None)

    def issue_code(self) -> dict[str, Any]:
        """A fresh five-minute code; older open codes stay valid until they expire."""
        with self._lock:
            now = time.monotonic()
            self._sweep_codes(now)
            code = _new_code()
            self._codes[code] = now + CODE_TTL_S
            return {"code": code, "expires_in": int(CODE_TTL_S)}

    def open_codes(self) -> int:
        with self._lock:
            self._sweep_codes(time.monotonic())
            return len(self._codes)

    def redeem(self, code: str, name: str, *, user_agent: str = "") -> tuple[PairedDevice, str]:
        """Spend ``code`` for a new device and its token (returned once, never stored)."""
        wanted = normalize_code(code)
        with self._lock:
            now = time.monotonic()
            self._sweep_codes(now)
            if not wanted or wanted not in self._codes:
                self._failed += 1
                if self._failed >= MAX_FAILED_ATTEMPTS:
                    self._codes.clear()
                    self._failed = 0
                raise PairingError("This pairing code is wrong or has expired.", 401)
            self._codes.pop(wanted, None)
            self._failed = 0
            token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
            device = PairedDevice(
                id=secrets.token_hex(8),
                name=(name or "Phone").strip()[:120] or "Phone",
                digest=_digest(token),
                created_at=time.time(),
                last_seen_at=time.time(),
                user_agent=(user_agent or "")[:300],
            )
            state = self._read()
            state.devices.append(device)
            self._write(state)
            return device, token

    # ------------------------------------------------------------ tokens

    def authenticate(self, token: str | None) -> PairedDevice | None:
        """The device a token belongs to, or ``None``. Constant-time per digest."""
        if not token or not token.startswith(_TOKEN_PREFIX) or len(token) > 128:
            return None
        wanted = _digest(token)
        with self._lock:
            for device in self._read().devices:
                if hmac.compare_digest(device.digest, wanted):
                    return device
        return None

    def touch(self, device_id: str) -> None:
        """Remember when a phone last called (shown in settings; coarse)."""
        with self._lock:
            state = self._read()
            for device in state.devices:
                if device.id == device_id:
                    if time.time() - device.last_seen_at < 60:
                        return
                    device.last_seen_at = time.time()
                    self._write(state)
                    return

    def rename(self, device_id: str, name: str) -> PairedDevice:
        with self._lock:
            state = self._read()
            for device in state.devices:
                if device.id == device_id:
                    device.name = name.strip()[:120] or device.name
                    self._write(state)
                    return device
        raise PairingError("No such phone.", 404)

    def revoke(self, device_id: str) -> bool:
        """Forget a phone: its token and its push subscription stop working."""
        with self._lock:
            state = self._read()
            kept = [d for d in state.devices if d.id != device_id]
            if len(kept) == len(state.devices):
                return False
            state.devices = kept
            self._write(state)
            return True

    def devices(self) -> list[PairedDevice]:
        with self._lock:
            return list(self._read().devices)

    def public_devices(self) -> list[dict[str, Any]]:
        return [d.public() for d in self.devices()]

    # -------------------------------------------------------------- push

    def set_push(self, device_id: str, subscription: PushSubscription | None) -> None:
        with self._lock:
            state = self._read()
            for device in state.devices:
                if device.id == device_id:
                    device.push = subscription
                    self._write(state)
                    return
        raise PairingError("No such phone.", 404)

    def push_targets(self) -> list[PairedDevice]:
        return [d for d in self.devices() if d.push is not None]


_DEVICES: MobileDevices | None = None
_DEVICES_LOCK = threading.Lock()


def get_devices() -> MobileDevices:
    """The process-wide device store (built on first use)."""
    global _DEVICES
    with _DEVICES_LOCK:
        if _DEVICES is None:
            _DEVICES = MobileDevices()
        return _DEVICES


def set_devices(devices: MobileDevices | None) -> None:
    """Test hook: swap the process-wide store."""
    global _DEVICES
    with _DEVICES_LOCK:
        _DEVICES = devices


def device_token_valid(token: str | None) -> bool:
    """Whether ``token`` is a live paired-phone token (for the outer boundary)."""
    try:
        return get_devices().authenticate(token) is not None
    except Exception:  # noqa: BLE001 — an unreadable store denies, never crashes the boundary
        return False


__all__ = [
    "CODE_TTL_S",
    "MobileDevices",
    "PairedDevice",
    "PairingError",
    "PushSubscription",
    "device_token_valid",
    "get_devices",
    "normalize_code",
    "set_devices",
]
