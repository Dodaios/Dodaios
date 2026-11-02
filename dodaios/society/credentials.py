"""Credentials an agent asked the person for: stored safely, never shown to the agent.

An agent that needs a token (a GitHub token, a Discord bot token, an API key
for a service it scripts against) asks with ``society_request_credential``.
The person pastes the value into a secure field in the chat; it goes straight
from that field to the OS credential store through ``set_secret`` and never
enters the chat log, the event stream, a prompt or a tool result.

What the agent gets is the NAME: the value is set as the environment variable
``<ENV>`` only in the commands it runs through ``society_shell``, which reads
the store on every call (a credential saved mid-turn works in the very next
command) and masks the value in the command's output BEFORE the model reads
it. A CLI seat's own process never receives a credential: its own shell tool
would hand ``printenv`` straight to the model, and a provider key there could
move a subscription seat onto paid billing.

Masking (``redact``) covers the plain value and its common encodings (base64,
URL encoding). It protects against an accidental print, not an agent set on
exfiltrating the value; every chat event of the agent is masked the same way.

The index file per agent holds names, labels and timestamps only; the values
live in the credential store under ``society_credential.<agent>.<ENV>``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import quote, urlsplit

log = logging.getLogger(__name__)

__all__ = [
    "SecretStore",
    "CredentialError",
    "CredentialInfo",
    "CredentialVault",
    "LoginInfo",
    "MAX_VALUE_CHARS",
    "login_key",
    "login_site",
    "validate_env_name",
]

#: A pasted secret longer than this is a file, not a token.
MAX_VALUE_CHARS: Final[int] = 16_384

#: Shorter values are never scrubbed from text: "1234" would eat every number.
_MIN_REDACT_CHARS: Final[int] = 6

_ENV_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")

#: Names the shell or the app itself depends on: refused outright.
_RESERVED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "APPDATA", "COMSPEC", "HOME", "HOMEDRIVE", "HOMEPATH", "LANG", "LD_LIBRARY_PATH",
        "LD_PRELOAD", "LOCALAPPDATA", "NODE_OPTIONS", "PATH", "PATHEXT", "PROGRAMDATA",
        "PROGRAMFILES", "PSMODULEPATH", "PWD", "PYTHONHOME", "PYTHONIOENCODING", "PYTHONPATH",
        "SHELL", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TERM", "TMP", "TMPDIR", "USER",
        "USERNAME", "USERPROFILE", "WINDIR",
    }
)
_RESERVED_PREFIXES: Final[tuple[str, ...]] = ("JARVIS", "DYLD_")

_SLOT_PREFIX: Final[str] = "society_credential"
_SAFE_ID: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.-]")


class SecretStore(Protocol):
    """Where the values live: the OS credential store in the app, a dict in tests."""

    def get(self, slot: str) -> str | None: ...

    def set(self, slot: str, value: str) -> bool: ...

    def delete(self, slot: str) -> bool: ...


class _OsSecrets:
    """``dodaios.core.config``'s keyring → file-fallback store (AGENTS.md: get_secret only)."""

    def get(self, slot: str) -> str | None:
        from dodaios.core.config import get_secret

        # "" turns off the ENV/.env fallback: only this slot's own value counts.
        return get_secret(slot, "")

    def set(self, slot: str, value: str) -> bool:
        from dodaios.core.config import set_secret

        return set_secret(slot, value)

    def delete(self, slot: str) -> bool:
        from dodaios.core.config import delete_secret

        return delete_secret(slot)


class CredentialError(ValueError):
    """A safe, user-facing reason for a failed credential submission."""

    def __init__(self, message: str, *, code: str = "invalid_token") -> None:
        super().__init__(message)
        self.code = code


def normalize_value(value: str) -> str:
    """Reject malformed input before validation or storage, without echoing it."""
    value = value.strip()
    if not value:
        raise CredentialError("Enter the credential before saving.")
    if len(value) > MAX_VALUE_CHARS:
        raise CredentialError("The credential is too long.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise CredentialError("A credential must be a single line without control characters.")
    return value


async def validate_token(env: str, value: str, *, label: str = "") -> None:
    """Check identifiable Discord tokens only at the fixed, official endpoint.

    Other credentials receive local input validation; arbitrary service names
    and descriptions can never select a URL or send credentials elsewhere.
    """
    import httpx

    value = normalize_value(value)
    discord = ("DISCORD" in env.split("_") and "TOKEN" in env.split("_")) or (
        "discord" in label.casefold() and "token" in label.casefold()
    )
    if not discord:
        return
    if not value.isascii() or any(ch.isspace() for ch in value):
        raise CredentialError("Paste only the Discord bot token, without an authorization prefix.")
    try:
        # One user-triggered validation, no retry, redirect, paid generation or
        # token in the URL. A context-managed client closes its resources.
        async with asyncio.timeout(12):
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {value}"},
                )
    except (TimeoutError, httpx.TimeoutException):
        raise CredentialError(
            "Discord did not respond in time. Please try saving again.",
            code="validation_timeout",
        ) from None
    except httpx.RequestError:
        raise CredentialError(
            "Discord could not be reached. Check your connection and try again.",
            code="network_error",
        ) from None
    if response.status_code in {401, 403}:
        raise CredentialError("Discord rejected this bot token. Check it or create a new one.")
    if response.status_code != 200:
        raise CredentialError(
            "Discord could not validate the token right now. Please try again later.",
            code="network_error",
        )
    try:
        user = response.json()
    except ValueError:
        raise CredentialError(
            "Discord returned an unreadable response. Please try again.", code="network_error",
        ) from None
    if not isinstance(user, dict) or not user.get("id") or user.get("bot") is not True:
        raise CredentialError("Use a Discord bot token from the Bot page in the Developer Portal.")


async def save_requested_credential(
    agent_id: str, env: str, value: str, *, label: str = "",
) -> None:
    """The shared validation and storage path for new and restored fields."""
    validate_env_name(env)
    value = normalize_value(value)
    vault = current_vault()
    if vault is None:
        raise CredentialError(
            "The credential store is unavailable. Please try again shortly.", code="storage_failed",
        )
    await validate_token(env, value, label=label)
    await asyncio.to_thread(vault.store, agent_id, env, value, label=label)


async def save_requested_login(
    agent_id: str, key: str, raw: str, *, url: str, label: str = "",
) -> None:
    """Store the two values the login form sent as one JSON object."""
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        raise CredentialError("Enter the username or email and the password.") from None
    if not isinstance(body, dict):
        raise CredentialError("Enter the username or email and the password.")
    vault = current_vault()
    if vault is None:
        raise CredentialError(
            "The credential store is unavailable. Please try again shortly.", code="storage_failed",
        )
    await asyncio.to_thread(
        vault.store_login, agent_id, key, body.get("username"), body.get("password"),
        url=url, label=label,
    )


def validate_env_name(raw: Any) -> str:
    """The environment variable name ``raw`` asks for, or ``CredentialError``."""
    name = str(raw or "").strip()
    if not _ENV_NAME.fullmatch(name):
        raise CredentialError(
            "env must be an UPPER_SNAKE_CASE environment variable name such as GITHUB_TOKEN"
        )
    if name in _RESERVED_NAMES or name.startswith(_RESERVED_PREFIXES):
        raise CredentialError(f"{name} is reserved for the system and cannot hold a credential")
    return name


def _encodings(value: str) -> list[str]:
    """The forms a printed value commonly takes: plain, base64 (also with the
    newline ``echo`` adds), URL-encoded."""
    raw = value.encode("utf-8")
    forms = {value, quote(value, safe="")}
    for data in (raw, raw + b"\n"):
        forms.add(base64.b64encode(data).decode("ascii"))
        forms.add(base64.b64encode(data).decode("ascii").rstrip("="))
        forms.add(base64.urlsafe_b64encode(data).decode("ascii").rstrip("="))
    return [form for form in forms if len(form) >= _MIN_REDACT_CHARS]


#: A login's key names its browser placeholders: ``<secret>reddit_password</secret>``.
_LOGIN_KEY: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_LOGIN_SLOT_PREFIX: Final[str] = "society_login"
#: Second-level labels under which a country code is the public suffix (co.uk, com.au).
_SHARED_SECOND_LEVEL: Final[frozenset[str]] = frozenset(
    {"ac", "co", "com", "edu", "gov", "ltd", "net", "ne", "or", "org", "plc"}
)
MAX_LOGIN_FIELD_CHARS: Final[int] = 1024


def login_key(raw: Any) -> str:
    """``raw`` (a label such as "Hacker News") as a placeholder key (``hacker_news``)."""
    key = re.sub(r"[^a-z0-9]+", "_", str(raw or "").casefold()).strip("_")
    if key and not key[0].isalpha():
        key = f"site_{key}"
    key = key[:40].rstrip("_")
    if not _LOGIN_KEY.fullmatch(key):
        raise CredentialError("site must name the website, e.g. 'Reddit' or 'Hacker News'")
    return key


def login_site(raw: Any) -> tuple[str, str]:
    """The sign-in page ``raw`` as ``(https URL, registrable domain)``.

    The domain decides where the browser may type the login: the site itself
    and its subdomains, over HTTPS only. Anything that is not a public web
    address (an IP, localhost, another scheme) is refused.
    """
    text = str(raw or "").strip()
    if text and "://" not in text:
        text = f"https://{text}"
    parts = urlsplit(text)
    host = (parts.hostname or "").casefold().rstrip(".")
    if parts.scheme not in {"https", "http"} or not host or "." not in host:
        raise CredentialError("url must be the website's address, e.g. https://www.reddit.com")
    labels = host.split(".")
    if all(label.isdigit() for label in labels) or not all(
        re.fullmatch(r"[a-z0-9-]{1,63}", label) for label in labels
    ):
        raise CredentialError("url must be a website's domain name, not an IP address")
    shared = labels[-2] in _SHARED_SECOND_LEVEL and len(labels[-1]) == 2
    if shared and len(labels) < 3:
        raise CredentialError("url must name one website, not a whole country domain")
    keep = 3 if shared else 2
    domain = ".".join(labels[-keep:])
    path = parts.path or "/"
    return f"https://{host}{path}"[:300], domain


def username_is_private(username: str) -> bool:
    """An email address is private; a site username is public on its own profile.

    A public username is shown to the agent and typed as it is: hiding it
    would mask every mention of that name (often the project's own name) in
    the chat and in every page the browser reads.
    """
    return "@" in username


def _login_field(value: Any, what: str, *, strip: bool) -> str:
    text = str(value if isinstance(value, str) else "")
    if strip:
        text = text.strip()
    if not text.strip():
        raise CredentialError(f"Enter the {what} before saving.")
    if len(text) > MAX_LOGIN_FIELD_CHARS:
        raise CredentialError(f"The {what} is too long.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise CredentialError(f"The {what} must be a single line without control characters.")
    return text


@dataclass(frozen=True, slots=True)
class LoginInfo:
    """A website login the agent may use in its browser: never the values."""

    key: str
    label: str
    url: str
    domain: str
    created_ms: int
    updated_ms: int

    @property
    def placeholders(self) -> tuple[str, str]:
        return (f"{self.key}_username", f"{self.key}_password")

    @property
    def domain_pattern(self) -> str:
        """browser-use's pattern: the domain and its subdomains, HTTPS only."""
        return f"*.{self.domain}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "url": self.url,
            "domain": self.domain,
            "created_ms": self.created_ms,
            "updated_ms": self.updated_ms,
        }


@dataclass(frozen=True, slots=True)
class CredentialInfo:
    """What the index knows about one stored credential: never its value."""

    env: str
    label: str
    created_ms: int
    updated_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "env": self.env,
            "label": self.label,
            "created_ms": self.created_ms,
            "updated_ms": self.updated_ms,
        }


class CredentialVault:
    """Per-agent credentials: names in ``<root>/<agent>.json``, values in the store."""

    def __init__(self, root: Path, secrets: SecretStore | None = None) -> None:
        self._root = Path(root)
        self._secrets: SecretStore = secrets or _OsSecrets()
        self._lock = threading.Lock()
        #: Values by agent, loaded once per process for scrubbing and env building.
        self._values: dict[str, dict[str, str]] = {}
        #: Website logins by agent and key: (username, password).
        self._logins: dict[str, dict[str, tuple[str, str]]] = {}
        #: (needle, env) per agent, longest first, so a longer secret that
        #: contains a shorter one is masked whole.
        self._masks: dict[str, list[tuple[str, str]]] = {}
        #: Bumped by every store/delete: a load that raced one is discarded.
        self._generation = 0

    # ------------------------------------------------------------- index

    def _index_path(self, agent_id: str) -> Path:
        # The name keeps no separator, but the joined path is still checked to
        # stay inside the vault: an agent id must never address another file.
        root = os.path.normpath(os.path.abspath(self._root))
        path = os.path.normpath(os.path.join(root, f"{_SAFE_ID.sub('_', agent_id)}.json"))
        if not path.startswith(root + os.sep):
            raise ValueError("Agent credential index escapes the vault")
        return Path(path)

    def _read_raw(self, agent_id: str) -> dict[str, Any]:
        path = self._index_path(agent_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:  # An agent without saved credentials has no index yet.
            return {}
        except (OSError, ValueError):
            log.warning("society credentials: unreadable index %s", path, exc_info=True)
            return {}
        return raw if isinstance(raw, dict) else {}

    def _read_logins(self, agent_id: str) -> dict[str, LoginInfo]:
        rows: dict[str, LoginInfo] = {}
        for entry in self._read_raw(agent_id).get("logins", []):
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "")
            domain = str(entry.get("domain") or "")
            if not _LOGIN_KEY.fullmatch(key) or not domain:
                continue
            rows[key] = LoginInfo(
                key=key,
                label=str(entry.get("label") or "")[:120],
                url=str(entry.get("url") or "")[:300],
                domain=domain[:253],
                created_ms=int(entry.get("created_ms") or 0),
                updated_ms=int(entry.get("updated_ms") or 0),
            )
        return rows

    def _read_index(self, agent_id: str) -> dict[str, CredentialInfo]:
        raw = self._read_raw(agent_id)
        rows: dict[str, CredentialInfo] = {}
        for entry in raw.get("credentials", []):
            if not isinstance(entry, dict):
                continue
            env = str(entry.get("env") or "")
            if not _ENV_NAME.fullmatch(env):
                continue
            rows[env] = CredentialInfo(
                env=env,
                label=str(entry.get("label") or "")[:120],
                created_ms=int(entry.get("created_ms") or 0),
                updated_ms=int(entry.get("updated_ms") or 0),
            )
        return rows

    def _write_index(
        self,
        agent_id: str,
        rows: Mapping[str, CredentialInfo] | None = None,
        logins: Mapping[str, LoginInfo] | None = None,
    ) -> None:
        """Write the index; the half not passed is kept as it is on disk."""
        rows = self._read_index(agent_id) if rows is None else rows
        logins = self._read_logins(agent_id) if logins is None else logins
        path = self._index_path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        body: dict[str, Any] = {"credentials": [rows[name].to_dict() for name in sorted(rows)]}
        if logins:
            body["logins"] = [logins[key].to_dict() for key in sorted(logins)]
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _slot(agent_id: str, env: str) -> str:
        return f"{_SLOT_PREFIX}.{_SAFE_ID.sub('_', agent_id)}.{env}"

    # ------------------------------------------------------------- public

    def list(self, agent_id: str) -> list[CredentialInfo]:
        with self._lock:
            rows = self._read_index(agent_id)
        return [rows[name] for name in sorted(rows)]

    def has(self, agent_id: str, env: str) -> bool:
        """The value is really there: an index row whose store entry vanished is not."""
        return env in self.values(agent_id)

    def store(self, agent_id: str, env: str, value: str, *, label: str = "") -> CredentialInfo:
        """Save ``value`` for ``agent_id`` as ``env``; raises ``CredentialError``."""
        env = validate_env_name(env)
        value = normalize_value(value)
        now = int(time.time() * 1000)
        with self._lock:
            rows = self._read_index(agent_id)
            previous = rows.get(env)
            info = CredentialInfo(
                env=env,
                label=(label.strip() or (previous.label if previous else ""))[:120],
                created_ms=previous.created_ms if previous else now,
                updated_ms=now,
            )
            slot = self._slot(agent_id, env)
            previous_value: str | None = None
            attempted = False
            try:
                previous_value = self._secrets.get(slot)
                attempted = True
                if not self._secrets.set(slot, value) or self._secrets.get(slot) != value:
                    raise CredentialError(
                        "The credential store could not verify the saved value. Please try again.",
                        code="storage_failed",
                    )
                rows[env] = info
                self._write_index(agent_id, rows)
            except Exception:
                # Neither keyring errors nor their tracebacks are safe: a
                # backend may include the submitted value in its exception.
                if attempted:
                    try:
                        restored = (
                            self._secrets.set(slot, previous_value)
                            if previous_value is not None else self._secrets.delete(slot)
                        )
                        if not restored:
                            log.error("society credentials: rollback failed for %s", env)
                    except Exception:
                        log.error("society credentials: rollback failed for %s", env)
                raise CredentialError(
                    "The credential could not be stored. Please try saving again.",
                    code="storage_failed",
                ) from None
            finally:
                self._forget(agent_id)
        log.info("society credentials: stored %s for %s", env, agent_id)
        return info

    def delete(self, agent_id: str, env: str) -> bool:
        """Forget ``env`` for ``agent_id``; False when it was never stored."""
        with self._lock:
            rows = self._read_index(agent_id)
            if env not in rows:
                return False
            if not self._secrets.delete(self._slot(agent_id, env)):
                raise CredentialError("the credential store could not delete the value")
            rows.pop(env)
            self._write_index(agent_id, rows)
            self._forget(agent_id)
        log.info("society credentials: deleted %s for %s", env, agent_id)
        return True

    def _forget(self, agent_id: str) -> None:
        """Drop the cached values (caller holds the lock); the next read reloads."""
        self._generation += 1
        self._values.pop(agent_id, None)
        self._logins.pop(agent_id, None)
        self._masks.pop(agent_id, None)

    def values(self, agent_id: str) -> dict[str, str]:
        """Every stored credential of ``agent_id`` by name (reads the store once)."""
        while True:
            with self._lock:
                cached = self._values.get(agent_id)
                if cached is not None:
                    return dict(cached)
                rows = self._read_index(agent_id)
                login_rows = self._read_logins(agent_id)
                generation = self._generation
            loaded = self._load(agent_id, rows)
            logins = self._load_logins(agent_id, login_rows)
            with self._lock:
                if generation != self._generation:
                    continue  # a store or delete ran meanwhile: load again
                self._values[agent_id] = loaded
                self._logins[agent_id] = logins
                needles = [(value, env) for env, value in loaded.items()]
                for key, (username, password) in logins.items():
                    if username_is_private(username):
                        needles.append((username, f"{key} username"))
                    needles.append((password, f"{key} password"))
                self._masks[agent_id] = sorted(
                    ((form, name) for value, name in needles for form in _encodings(value)),
                    key=lambda pair: len(pair[0]),
                    reverse=True,
                )
                return dict(loaded)

    def _load(self, agent_id: str, rows: Mapping[str, CredentialInfo]) -> dict[str, str]:
        loaded: dict[str, str] = {}
        for env in rows:
            value = self._secrets.get(self._slot(agent_id, env))
            if value:
                loaded[env] = value
            else:
                log.warning(
                    "society credentials: %s for %s is missing from the store", env, agent_id
                )
        return loaded

    def _load_logins(
        self, agent_id: str, rows: Mapping[str, LoginInfo]
    ) -> dict[str, tuple[str, str]]:
        loaded: dict[str, tuple[str, str]] = {}
        for key in rows:
            username = self._secrets.get(self._login_slot(agent_id, key, "username"))
            password = self._secrets.get(self._login_slot(agent_id, key, "password"))
            if username and password:
                loaded[key] = (username, password)
            else:
                log.warning("society credentials: login %s for %s is incomplete", key, agent_id)
        return loaded

    @staticmethod
    def _login_slot(agent_id: str, key: str, field: str) -> str:
        return f"{_LOGIN_SLOT_PREFIX}.{_SAFE_ID.sub('_', agent_id)}.{key}.{field}"

    # ------------------------------------------------------------- logins

    def list_logins(self, agent_id: str) -> list[LoginInfo]:
        with self._lock:
            rows = self._read_logins(agent_id)
        return [rows[key] for key in sorted(rows)]

    def has_login(self, agent_id: str, key: str) -> bool:
        """Both values are really there, not only the index row."""
        self.values(agent_id)
        with self._lock:
            return key in self._logins.get(agent_id, {})

    def store_login(
        self,
        agent_id: str,
        key: str,
        username: Any,
        password: Any,
        *,
        url: str,
        label: str = "",
    ) -> LoginInfo:
        """Save a website login: both values go to the store, the index keeps the site."""
        key = login_key(key)
        site_url, domain = login_site(url)
        user_value = _login_field(username, "username or email", strip=True)
        pass_value = _login_field(password, "password", strip=False)
        now = int(time.time() * 1000)
        with self._lock:
            logins = self._read_logins(agent_id)
            previous = logins.get(key)
            info = LoginInfo(
                key=key,
                label=(label.strip() or (previous.label if previous else key))[:120],
                url=site_url,
                domain=domain,
                created_ms=previous.created_ms if previous else now,
                updated_ms=now,
            )
            slots = {
                self._login_slot(agent_id, key, "username"): user_value,
                self._login_slot(agent_id, key, "password"): pass_value,
            }
            before: dict[str, str | None] = {}
            try:
                for slot, value in slots.items():
                    before[slot] = self._secrets.get(slot)
                    if not self._secrets.set(slot, value) or self._secrets.get(slot) != value:
                        raise CredentialError("unverified", code="storage_failed")
                logins[key] = info
                self._write_index(agent_id, logins=logins)
            except Exception:
                # Never log the exception: a store backend may echo the value.
                for slot, old in before.items():
                    try:
                        if old is not None:
                            self._secrets.set(slot, old)
                        else:
                            self._secrets.delete(slot)
                    except Exception:
                        log.error("society credentials: login rollback failed for %s", key)
                raise CredentialError(
                    "The login could not be stored. Please try saving again.",
                    code="storage_failed",
                ) from None
            finally:
                self._forget(agent_id)
        log.info("society credentials: stored login %s for %s", key, agent_id)
        return info

    def delete_login(self, agent_id: str, key: str) -> bool:
        """Forget a website login; False when it was never stored."""
        with self._lock:
            logins = self._read_logins(agent_id)
            if key not in logins:
                return False
            for field in ("username", "password"):
                slot = self._login_slot(agent_id, key, field)
                if self._secrets.get(slot) is not None and not self._secrets.delete(slot):
                    raise CredentialError("the credential store could not delete the login")
            logins.pop(key)
            self._write_index(agent_id, logins=logins)
            self._forget(agent_id)
        log.info("society credentials: deleted login %s for %s", key, agent_id)
        return True

    def browser_secrets(self, agent_id: str) -> dict[str, dict[str, str]]:
        """browser-use ``sensitive_data``: each login bound to its own site.

        The browser types a value only on a page of that site; the model sees
        and writes the placeholder names, never the values.
        """
        self.values(agent_id)
        with self._lock:
            values = dict(self._logins.get(agent_id, {}))
            rows = self._read_logins(agent_id)
        out: dict[str, dict[str, str]] = {}
        for key, (username, password) in values.items():
            info = rows.get(key)
            if info is None:
                continue
            user_name, pass_name = info.placeholders
            scoped = out.setdefault(info.domain_pattern, {})
            scoped[pass_name] = password
            if username_is_private(username):
                scoped[user_name] = username
        return out

    def public_username(self, agent_id: str, key: str) -> str | None:
        """The login's username when it is not private, else ``None``."""
        self.values(agent_id)
        with self._lock:
            pair = self._logins.get(agent_id, {}).get(key)
        if pair is None or username_is_private(pair[0]):
            return None
        return pair[0]

    def is_loaded(self, agent_id: str) -> bool:
        return agent_id in self._values

    def _any_secret(self, agent_id: str) -> bool:
        if self.values(agent_id):
            return True
        with self._lock:
            return bool(self._logins.get(agent_id))

    def shell_env(self, agent_id: str) -> dict[str, str]:
        """The variables an agent's own ``society_shell`` commands run with."""
        return self.values(agent_id)

    def redact(self, agent_id: str, text: str) -> str:
        """``text`` with every credential value of ``agent_id`` masked (may read the store)."""
        if not text or not self._any_secret(agent_id):
            return text
        for needle, env in self._masks.get(agent_id, ()):
            if needle in text:
                text = text.replace(needle, f"[credential {env}]")
        return text

    def redact_payload(self, agent_id: str, payload: Any) -> Any:
        """``payload`` with every string in it redacted; unchanged objects are reused."""
        if not self._any_secret(agent_id):
            return payload
        if isinstance(payload, str):
            return self.redact(agent_id, payload)
        if isinstance(payload, dict):
            out: dict[Any, Any] = {}
            changed = False
            for key, item in payload.items():
                new = self.redact_payload(agent_id, item)
                changed = changed or new is not item
                out[key] = new
            return out if changed else payload
        if isinstance(payload, list):
            items = [self.redact_payload(agent_id, item) for item in payload]
            changed = any(a is not b for a, b in zip(items, payload, strict=True))
            return items if changed else payload
        return payload


_VAULT: CredentialVault | None = None
_VAULT_ROOT: Path | None = None
_VAULT_LOCK = threading.Lock()


def vault_for(data_dir: Path) -> CredentialVault:
    """The process's vault for the society data folder ``data_dir``."""
    global _VAULT, _VAULT_ROOT
    root = Path(data_dir) / "credentials"
    with _VAULT_LOCK:
        if _VAULT is None or _VAULT_ROOT != root:
            _VAULT = CredentialVault(root)
            _VAULT_ROOT = root
        return _VAULT


def current_vault() -> CredentialVault | None:
    """The vault of the running society, or ``None`` before it started."""
    from .runtime import current_runtime

    rt = current_runtime()
    data_dir = getattr(rt, "data_dir", None) if rt is not None else None
    return vault_for(data_dir) if data_dir is not None else None
