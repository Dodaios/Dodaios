"""The credential broker: tools name a login by handle, only the executor holds the value.

Flow for a browser task that mentions ``cred:github.com/owner``:

1. The handle is looked up in the owner's chosen backend (backends.py).
2. The first time an agent signs in to a site the owner is asked (``authorize``);
   an approval writes a per-site rule the owner can revoke in the Credentials
   section, and later logins on that site run without asking.
3. The values go to the browser runner as ``sensitive_data`` bound to the site
   (it types them only there); the model reads and writes placeholders such as
   ``<secret>cred_github_com_owner_password</secret>``, never values.
4. Everything leaving the call (the tool result, and for as long as the lease
   lives every chat event) is scrubbed of the values and their common
   encodings; the lease is released when the task ends, and nothing is kept.

One-time codes: when the manager holds a TOTP seed, the browser derives the
code itself at the moment the form asks. Otherwise the agent is told to stop
and hand the browser to the owner. Reading a code from mail is only offered
where the owner switched it on for that site.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .backends import (
    BackendError,
    BitwardenBackend,
    CredentialBackend,
    HandleInfo,
    LocalVaultBackend,
    OnePasswordBackend,
    Secrets,
)
from .handles import Handle, find_handles

log = logging.getLogger(__name__)

__all__ = [
    "BrowserLogins",
    "CredentialBroker",
    "SiteRules",
    "broker_for",
    "redact_active",
]

Authorize = Callable[[Handle], Awaitable[bool]]

_MIN_REDACT_CHARS: Final[int] = 6


# ----------------------------------------------------------------- rules


class SiteRules:
    """The owner's choices: the active backend and the per-site always-rules."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._data is None:
            data: Any = {}
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except FileNotFoundError:  # nothing was ever chosen: the defaults
                pass
            except (OSError, ValueError):
                log.warning("credential broker: unreadable settings %s", self._path)
            self._data = data if isinstance(data, dict) else {}
            self._data.setdefault("rules", [])
        return self._data

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.warning("credential broker: could not write %s", self._path, exc_info=True)

    def backend(self) -> str:
        with self._lock:
            return str(self._load().get("backend") or "local")

    def set_backend(self, name: str) -> None:
        with self._lock:
            self._load()["backend"] = name
            self._save()

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._load()["rules"]]

    def find(self, agent_id: str, domain: str) -> dict[str, Any] | None:
        return next(
            (r for r in self.items() if r["agent_id"] == agent_id and r["domain"] == domain), None,
        )

    def add(self, agent_id: str, handle: Handle) -> dict[str, Any]:
        with self._lock:
            rules = self._load()["rules"]
            for rule in rules:
                if rule["agent_id"] == agent_id and rule["domain"] == handle.domain:
                    return dict(rule)
            rule = {
                "id": uuid.uuid4().hex[:12], "agent_id": agent_id, "domain": handle.domain,
                "handle": str(handle), "otp_from_mail": False,
                "created_ms": int(time.time() * 1000),
            }
            rules.append(rule)
            self._save()
            return dict(rule)

    def revoke(self, rule_id: str) -> dict[str, Any] | None:
        with self._lock:
            rules = self._load()["rules"]
            for i, rule in enumerate(rules):
                if rule["id"] == rule_id:
                    del rules[i]
                    self._save()
                    return dict(rule)
        return None

    def set_otp_from_mail(self, rule_id: str, on: bool) -> bool:
        with self._lock:
            for rule in self._load()["rules"]:
                if rule["id"] == rule_id:
                    rule["otp_from_mail"] = bool(on)
                    self._save()
                    return True
        return False


# ------------------------------------------------------------- redaction

_ACTIVE_LOCK = threading.Lock()
_ACTIVE: dict[int, list[tuple[str, str]]] = {}


def _needles(label: str, secrets: Secrets) -> list[tuple[str, str]]:
    from dodaios.society.credentials import _encodings, username_is_private

    plain = [secrets.password, secrets.totp_seed or ""]
    if username_is_private(secrets.username):
        plain.append(secrets.username)
    out = [
        (form, label) for value in plain if value and len(value) >= _MIN_REDACT_CHARS
        for form in _encodings(value)
    ]
    return sorted(out, key=lambda pair: len(pair[0]), reverse=True)


def _scrub(needles: list[tuple[str, str]], payload: Any) -> Any:
    if isinstance(payload, str):
        for needle, label in needles:
            if needle in payload:
                payload = payload.replace(needle, f"[credential {label}]")
        return payload
    if isinstance(payload, dict):
        return {key: _scrub(needles, item) for key, item in payload.items()}
    if isinstance(payload, list):
        return [_scrub(needles, item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(_scrub(needles, item) for item in payload)
    return payload


def redact_active(payload: Any) -> Any:
    """``payload`` with the value of every login a running task holds masked."""
    with _ACTIVE_LOCK:
        needles = sorted(
            (pair for group in _ACTIVE.values() for pair in group),
            key=lambda pair: len(pair[0]), reverse=True,
        )
    return _scrub(needles, payload) if needles else payload


# --------------------------------------------------------------- the lease


@dataclass
class BrowserLogins:
    """What a browser task gets: the rewritten task, the typed values, and the scrubber."""

    task: str
    sensitive_data: dict[str, dict[str, str]] = field(default_factory=dict)
    used: list[str] = field(default_factory=list)
    unavailable: dict[str, str] = field(default_factory=dict)
    _needles: list[tuple[str, str]] = field(default_factory=list, repr=False)
    _released: bool = False

    def redact(self, payload: Any) -> Any:
        return _scrub(self._needles, payload)

    def release(self) -> None:
        """Drop every value: nothing outlives the task."""
        if self._released:
            return
        self._released = True
        with _ACTIVE_LOCK:
            _ACTIVE.pop(id(self), None)
        self.sensitive_data = {}
        self._needles = []


# -------------------------------------------------------------- the broker


class CredentialBroker:
    def __init__(
        self,
        backends: dict[str, CredentialBackend],
        rules: SiteRules,
        *,
        audit: Callable[[], Any] | None = None,
    ) -> None:
        self._backends = backends
        self.rules = rules
        self._audit = audit

    # ---------------------------------------------------------- backends

    @property
    def backend_names(self) -> list[str]:
        return list(self._backends)

    def active_name(self) -> str:
        name = self.rules.backend()
        return name if name in self._backends else "local"

    def backend(self, name: str | None = None) -> CredentialBackend:
        return self._backends[name or self.active_name()]

    def set_backend(self, name: str) -> None:
        if name not in self._backends:
            raise ValueError(f"unknown credential backend {name!r}")
        self.rules.set_backend(name)

    def set_session(self, name: str, key: str) -> bool:
        """The owner pasted (or cleared) a manager's session key; memory only."""
        backend = self._backends.get(name)
        setter = getattr(backend, "set_session", None)
        if not callable(setter):
            return False
        setter(key)
        return True

    async def statuses(self) -> list[dict[str, Any]]:
        def collect() -> list[dict[str, Any]]:
            return [b.status().to_dict() for b in self._backends.values()]

        return await asyncio.to_thread(collect)

    async def handles(self, agent_id: str) -> list[HandleInfo]:
        return await asyncio.to_thread(self.backend().list_handles, agent_id)

    # ----------------------------------------------------------- audit

    def _record(
        self, agent_id: str, handle: Handle, outcome: str, *, approval: str, session_id: str,
        trace_id: str, error: str = "",
    ) -> None:
        try:
            if self._audit is not None:
                log_ = self._audit()
            else:
                from dodaios.trust.audit import audit_log

                log_ = audit_log()
            log_.record({
                "trace_id": trace_id, "tool": "credential_broker", "action": "browser_login",
                "origin": "agent", "origin_detail": agent_id, "session_id": session_id,
                "approval": approval, "tier": "ask", "effect": "credential",
                "outcome": outcome, "error": error, "args_preview": str(handle),
                "receipt": {
                    "id": uuid.uuid4().hex[:16], "state": "none", "kind": "credential_use",
                    "summary": f"Login {handle} released to the browser ({outcome})",
                    "evidence": {"handle": str(handle), "backend": self.active_name()},
                    "links": [],
                },
            })
        except Exception:  # noqa: BLE001 — a log that cannot write never costs the task
            log.warning("credential broker: audit write failed", exc_info=True)

    # ---------------------------------------------------------- browser

    async def prepare_browser(
        self, agent_id: str, task: str, authorize: Authorize, *,
        session_id: str = "", trace_id: str = "",
    ) -> BrowserLogins:
        """Resolve every handle named in ``task``; the result is a lease to release."""
        handles = find_handles(task)
        lease = BrowserLogins(task=task)
        if not handles:
            return lease
        needles: list[tuple[str, str]] = []
        for handle in handles:
            text = await self._one(
                agent_id, handle, authorize, lease, needles, session_id, trace_id,
            )
            lease.task = lease.task.replace(str(handle), text)
        lease._needles = sorted(needles, key=lambda pair: len(pair[0]), reverse=True)
        with _ACTIVE_LOCK:
            _ACTIVE[id(lease)] = list(lease._needles)
        return lease

    async def _one(
        self, agent_id: str, handle: Handle, authorize: Authorize, lease: BrowserLogins,
        needles: list[tuple[str, str]], session_id: str, trace_id: str,
    ) -> str:
        def refuse(reason: str, outcome: str, approval: str = "none") -> str:
            lease.unavailable[str(handle)] = reason
            self._record(
                agent_id, handle, outcome, approval=approval, session_id=session_id,
                trace_id=trace_id, error=reason,
            )
            return (
                f"{handle} (this stored login is unavailable: {reason}; do not guess a "
                "password, stop and tell the owner)"
            )

        approval = "always_rule"
        if self.rules.find(agent_id, handle.domain) is None:
            if not await authorize(handle):
                return refuse("the owner did not allow it", "denied")
            self.rules.add(agent_id, handle)
            approval = "owner_click"
        try:
            secrets = await asyncio.to_thread(self.backend().resolve, agent_id, handle)
        except BackendError as exc:  # the reason is shown to the owner and audited
            return refuse(str(exc), "failed", approval)
        except Exception:  # noqa: BLE001 — a backend fault costs this login, not the task
            log.warning("credential broker: lookup failed for %s", handle, exc_info=True)
            return refuse("the password manager could not be read", "failed", approval)
        base = handle.placeholder_base
        scoped = lease.sensitive_data.setdefault(f"*.{handle.domain}", {})
        scoped[f"{base}_password"] = secrets.password
        scoped[f"{base}_username"] = secrets.username
        if secrets.totp_seed:
            scoped[f"{base}_bu_2fa_code"] = secrets.totp_seed
        needles.extend(_needles(str(handle), secrets))
        lease.used.append(str(handle))
        self._record(
            agent_id, handle, "executed", approval=approval, session_id=session_id,
            trace_id=trace_id,
        )
        return self._usage(handle, secrets, base, agent_id)

    def _usage(self, handle: Handle, secrets: Secrets, base: str, agent_id: str) -> str:
        rule = self.rules.find(agent_id, handle.domain) or {}
        if secrets.totp_seed:
            code = (
                f" If the site asks for a one-time code, enter <secret>{base}_bu_2fa_code</secret>."
            )
        elif rule.get("otp_from_mail"):
            code = (
                " If the site asks for a one-time code, the owner allowed reading it from "
                "their mail for this site."
            )
        else:
            code = (
                " If the site asks for a one-time code, stop with success=false and ask the "
                "owner to take over the browser; never read one-time codes from mail."
            )
        return (
            f"the stored login {handle} (username <secret>{base}_username</secret>, password "
            f"<secret>{base}_password</secret>; use the sign-in form on {handle.domain}, you "
            f"never see the values).{code}"
        )


# ------------------------------------------------------------ the singleton

_BROKER: CredentialBroker | None = None
_BROKER_ROOT: Path | None = None
_BROKER_LOCK = threading.Lock()


def broker_for(data_dir: Path) -> CredentialBroker:
    """The process's broker for the society data folder ``data_dir``."""
    global _BROKER, _BROKER_ROOT
    root = Path(data_dir) / "credential_broker"
    with _BROKER_LOCK:
        if _BROKER is None or _BROKER_ROOT != root:
            from dodaios.society.credentials import current_vault

            _BROKER = CredentialBroker(
                {
                    "local": LocalVaultBackend(current_vault),
                    "bitwarden": BitwardenBackend(),
                    "1password": OnePasswordBackend(),
                },
                SiteRules(root / "settings.json"),
            )
            _BROKER_ROOT = root
        return _BROKER
