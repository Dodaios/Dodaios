"""Password-manager backends behind one read-only interface.

``local``      the app's own vault (society/credentials.py): the default.
``bitwarden``  the ``bw`` CLI, when installed and unlocked by the owner.
``1password``  the ``op`` CLI, when installed and signed in by the owner.

Rules every backend keeps:

* Lookups are read-only (list and get; never create, edit or delete).
* Nothing is cached: each call asks the manager again and the values leave with
  the caller's lease.
* Unlock is the owner's action. This module never asks for, stores or passes a
  master password. Bitwarden's session key comes from the owner (the
  ``BW_SESSION`` variable of the app, or the in-memory key the owner pastes in
  the Credentials section, see ``set_session``); 1Password unlocks through its
  own desktop app.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol
from urllib.parse import parse_qs, urlsplit

from .handles import Handle, slug

__all__ = [
    "BackendError",
    "BackendStatus",
    "BitwardenBackend",
    "CredentialBackend",
    "HandleInfo",
    "LocalVaultBackend",
    "OnePasswordBackend",
    "Run",
    "Secrets",
]

_CLI_TIMEOUT_S: Final[float] = 20.0


class BackendError(RuntimeError):
    """A safe, owner-facing reason a lookup failed (never carries a value)."""


@dataclass(frozen=True, slots=True)
class BackendStatus:
    name: str
    installed: bool
    unlocked: bool
    #: ``ready`` | ``locked`` | ``not_installed`` | ``unavailable``
    state: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "installed": self.installed,
            "unlocked": self.unlocked, "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class HandleInfo:
    """One login the owner may let an agent use: names only."""

    handle: str
    domain: str
    account: str
    label: str
    backend: str
    has_totp: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle, "domain": self.domain, "account": self.account,
            "label": self.label, "backend": self.backend, "has_totp": self.has_totp,
        }


class Secrets:
    """The values behind one handle; the repr never shows them."""

    __slots__ = ("password", "totp_seed", "username")

    def __init__(self, username: str, password: str, totp_seed: str | None = None) -> None:
        self.username = username
        self.password = password
        self.totp_seed = totp_seed or None

    def __repr__(self) -> str:
        return "Secrets(<hidden>)"

    def values(self) -> list[str]:
        return [v for v in (self.username, self.password, self.totp_seed) if v]


class CredentialBackend(Protocol):
    name: str

    def status(self) -> BackendStatus: ...

    def list_handles(self, agent_id: str, domain: str | None = None) -> list[HandleInfo]: ...

    def resolve(self, agent_id: str, handle: Handle) -> Secrets: ...


#: Runs a CLI: ``(argv, extra_env) -> (returncode, stdout)``. Tests pass a fake.
Run = Callable[[Sequence[str], dict[str, str]], tuple[int, str]]


def _run_cli(argv: Sequence[str], env: dict[str, str]) -> tuple[int, str]:
    try:
        done = subprocess.run(  # noqa: S603 — fixed argv, no shell
            list(argv), capture_output=True, text=True, timeout=_CLI_TIMEOUT_S,
            env={**os.environ, **env}, stdin=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):  # a safe BackendError; stderr may hold a value
        raise BackendError("the password manager did not answer") from None
    # stderr is dropped on purpose: a manager may echo a value in an error.
    return done.returncode, done.stdout


def _site_of(uri: str) -> str:
    """The registrable domain of ``uri``, or ``""`` for anything that is not a public site."""
    from dodaios.society.credentials import CredentialError, login_site

    try:
        return login_site(uri)[1]
    except CredentialError:  # not a public site: the item is skipped
        return ""


def _totp_secret(raw: Any) -> str | None:
    """The base32 seed of a stored one-time-password entry (a bare seed or an otpauth URI)."""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("otpauth://"):
        found = parse_qs(urlsplit(text).query).get("secret")
        return found[0] if found else None
    return text.replace(" ", "")


def _unique_accounts(rows: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Account slug -> item, a numeric suffix keeping two items of one name apart."""
    out: dict[str, dict[str, Any]] = {}
    for name, item in rows:
        base = slug(name) or "login"
        account, n = base, 2
        while account in out:
            account, n = f"{base}-{n}", n + 1
        out[account] = item
    return out


# ------------------------------------------------------------------ local


class LocalVaultBackend:
    """The app's own per-agent login vault. Always available, always unlocked."""

    name = "local"

    def __init__(self, vault_getter: Callable[[], Any]) -> None:
        self._vault = vault_getter

    def status(self) -> BackendStatus:
        ok = self._vault() is not None
        return BackendStatus(self.name, True, ok, "ready" if ok else "unavailable")

    def list_handles(self, agent_id: str, domain: str | None = None) -> list[HandleInfo]:
        vault = self._vault()
        if vault is None:
            return []
        return [
            HandleInfo(str(Handle(row.domain, row.key)), row.domain, row.key, row.label, self.name)
            for row in vault.list_logins(agent_id)
            if domain is None or row.domain == domain
        ]

    def resolve(self, agent_id: str, handle: Handle) -> Secrets:
        vault = self._vault()
        for row in vault.list_logins(agent_id) if vault is not None else []:
            if row.domain == handle.domain and row.key == handle.account:
                pair = vault.login_values(agent_id, row.key)
                if pair is not None:
                    return Secrets(pair[0], pair[1])
        raise BackendError("no such stored login")


# --------------------------------------------------------------- listing


def _group(
    rows: list[tuple[str, str, dict[str, Any]]],
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    by_site: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for site, name, item in rows:
        by_site.setdefault(site, []).append((name, item))
    return by_site


# -------------------------------------------------------------- bitwarden


class BitwardenBackend:
    """``bw``: read-only ``list items`` / ``status``; the session key is the owner's."""

    name = "bitwarden"

    def __init__(
        self, run: Run | None = None, which: Callable[[str], str | None] | None = None,
    ) -> None:
        self._run = run or _run_cli
        self._which = which or shutil.which
        self._lock = threading.Lock()
        self._session = ""

    def set_session(self, key: str) -> None:
        """The owner's unlock key (``bw unlock --raw``), kept in memory only; ``""`` locks."""
        with self._lock:
            self._session = str(key or "").strip()

    def _key(self) -> str:
        with self._lock:
            return self._session or os.environ.get("BW_SESSION", "")

    def status(self) -> BackendStatus:
        if not self._which("bw"):
            return BackendStatus(self.name, False, False, "not_installed")
        try:
            code, out = self._run(["bw", "status", "--nointeraction"], self._env())
            state = json.loads(out).get("status") if code == 0 else None
        except (BackendError, ValueError, AttributeError):  # reported as unavailable
            return BackendStatus(self.name, True, False, "unavailable")
        if state == "unlocked":
            return BackendStatus(self.name, True, True, "ready")
        return BackendStatus(self.name, True, False, "locked")

    def _env(self) -> dict[str, str]:
        key = self._key()
        return {"BW_SESSION": key} if key else {}

    def _items(self, domain: str | None) -> list[tuple[str, str, dict[str, Any]]]:
        argv = ["bw", "list", "items", "--nointeraction"]
        if domain:
            argv += ["--search", domain]
        code, out = self._run(argv, self._env())
        if code != 0:
            raise BackendError("Bitwarden is locked or did not answer")
        try:
            items = json.loads(out)
        except ValueError:  # a safe BackendError, never the raw answer
            raise BackendError("Bitwarden returned an unreadable answer") from None
        rows: list[tuple[str, str, dict[str, Any]]] = []
        for item in items if isinstance(items, list) else []:
            login = item.get("login") if isinstance(item, dict) else None
            if not isinstance(login, dict) or item.get("type") != 1:
                continue
            sites = [
                _site_of(str(u.get("uri") or ""))
                for u in login.get("uris") or [] if isinstance(u, dict)
            ]
            for site in dict.fromkeys(s for s in sites if s):
                if domain is None or site == domain:
                    rows.append((site, str(item.get("name") or ""), item))
        return rows

    def list_handles(self, agent_id: str, domain: str | None = None) -> list[HandleInfo]:
        out: list[HandleInfo] = []
        for site, rows in _group(self._items(domain)).items():
            for account, item in _unique_accounts(rows).items():
                out.append(HandleInfo(
                    str(Handle(site, account)), site, account, str(item.get("name") or ""),
                    self.name, bool(item["login"].get("totp")),
                ))
        return out

    def resolve(self, agent_id: str, handle: Handle) -> Secrets:
        rows = _group(self._items(handle.domain)).get(handle.domain, [])
        item = _unique_accounts(rows).get(handle.account)
        if item is None:
            raise BackendError("no such login in Bitwarden")
        login = item["login"]
        return Secrets(
            str(login.get("username") or ""), str(login.get("password") or ""),
            _totp_secret(login.get("totp")),
        )


# ---------------------------------------------------------------- 1password


class OnePasswordBackend:
    """``op``: read-only ``item list`` / ``item get``; the desktop app does the unlock."""

    name = "1password"

    def __init__(
        self, run: Run | None = None, which: Callable[[str], str | None] | None = None,
    ) -> None:
        self._run = run or _run_cli
        self._which = which or shutil.which

    def status(self) -> BackendStatus:
        if not self._which("op"):
            return BackendStatus(self.name, False, False, "not_installed")
        try:
            code, _ = self._run(["op", "whoami"], {})
        except BackendError:  # a safe BackendError, never the raw answer
            return BackendStatus(self.name, True, False, "unavailable")
        return BackendStatus(self.name, True, code == 0, "ready" if code == 0 else "locked")

    def _items(self, domain: str | None) -> list[tuple[str, str, dict[str, Any]]]:
        code, out = self._run(
            ["op", "item", "list", "--categories", "Login", "--format", "json"], {},
        )
        if code != 0:
            raise BackendError("1Password is locked or did not answer")
        try:
            items = json.loads(out)
        except ValueError:  # a safe BackendError, never the raw answer
            raise BackendError("1Password returned an unreadable answer") from None
        rows: list[tuple[str, str, dict[str, Any]]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            sites = [
                _site_of(str(u.get("href") or ""))
                for u in item.get("urls") or [] if isinstance(u, dict)
            ]
            for site in dict.fromkeys(s for s in sites if s):
                if domain is None or site == domain:
                    rows.append((site, str(item.get("title") or ""), item))
        return rows

    def list_handles(self, agent_id: str, domain: str | None = None) -> list[HandleInfo]:
        out: list[HandleInfo] = []
        for site, rows in _group(self._items(domain)).items():
            for account, item in _unique_accounts(rows).items():
                out.append(HandleInfo(
                    str(Handle(site, account)), site, account, str(item.get("title") or ""),
                    self.name,
                ))
        return out

    def resolve(self, agent_id: str, handle: Handle) -> Secrets:
        rows = _group(self._items(handle.domain)).get(handle.domain, [])
        item = _unique_accounts(rows).get(handle.account)
        if item is None:
            raise BackendError("no such login in 1Password")
        code, out = self._run(
            ["op", "item", "get", str(item.get("id")), "--format", "json", "--reveal"], {},
        )
        if code != 0:
            raise BackendError("1Password is locked or did not answer")
        try:
            fields = json.loads(out).get("fields") or []
        except (ValueError, AttributeError):  # a safe BackendError, never the raw answer
            raise BackendError("1Password returned an unreadable answer") from None
        username = password = ""
        totp: str | None = None
        for field in fields:
            if not isinstance(field, dict):
                continue
            purpose, kind = field.get("purpose"), str(field.get("type") or "").upper()
            if purpose == "USERNAME":
                username = str(field.get("value") or "")
            elif purpose == "PASSWORD":
                password = str(field.get("value") or "")
            elif kind == "OTP":
                totp = _totp_secret(field.get("value"))
        return Secrets(username, password, totp)
