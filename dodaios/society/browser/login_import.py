"""Find the person's installed browsers and read their website logins (cookies).

The agent browser is a separate managed Chromium profile, so the person would
have to sign in to every website again. This module reads the cookies of a
browser profile they choose (Chrome, Chromium, Brave, Edge, Arc, Vivaldi or
Firefox) and turns them into CDP ``Network.CookieParam`` dicts. ``live.py``
hands them to the running agent browser (``import_cookies``), which stores them
with its own encryption in its own profile.

Rules that keep this safe:

* Detection (:func:`detect_sources`) reads only ``Local State`` /
  ``profiles.ini`` and counts cookie rows. It never touches the Keychain or a
  cookie value.
* The decryption key is read only from :func:`read_source_cookies`, which runs
  only for the person's explicit import (or the remembered auto-refresh). On
  macOS the first read shows one Keychain consent dialog.
* Cookie databases are always read from a private temporary copy, never the
  live file, so the person's running browser is not disturbed.
* No cookie value is logged, returned in an error, or kept on disk here.
* Chrome on Windows (127+) uses app-bound ``v20`` encryption that another
  process cannot decrypt. That is reported as unsupported; it is not bypassed.
"""

from __future__ import annotations

import base64
import configparser
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import pathname2url

log = logging.getLogger(__name__)

# Chrome stores times as microseconds since 1601-01-01 (Windows epoch).
_CHROME_EPOCH_OFFSET_S = 11_644_473_600
_SALT = b"saltysalt"
_IV = b" " * 16
# Since cookie DB version 24 the plaintext starts with SHA-256(host_key).
_HASHED_VALUES_VERSION = 24
_PROFILE_DIR = re.compile(r"^[A-Za-z0-9 ._-]{1,100}$")
_SKIPPED_CHROMIUM_PROFILES = frozenset({"System Profile", "Guest Profile"})
_CHROMIUM_SAMESITE = {0: "None", 1: "Lax", 2: "Strict"}
_FIREFOX_SAMESITE = {0: "None", 1: "Lax", 2: "Strict"}
_WINDOWS_CHROME_REASON = (
    "Chrome on Windows locks its logins to Chrome itself, so other apps cannot "
    "read them. Sign in once in the Dodaios browser instead; the login stays."
)
# Two-letter country domains that sell names one level down (example.co.uk).
_SECOND_LEVEL = frozenset({"co", "com", "net", "org", "gov", "edu", "ac", "or", "ne", "go"})


class LoginImportError(RuntimeError):
    """A readable failure; ``code`` is stable for the UI and the status row."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BrowserSpec:
    key: str
    label: str
    family: str  # "chromium" or "firefox"
    mac: tuple[str, ...] = ()  # under ~/Library/Application Support
    linux: tuple[str, ...] = ()  # under $XDG_CONFIG_HOME (Firefox: under $HOME)
    windows: tuple[str, ...] = ()  # under %LOCALAPPDATA% (Firefox: %APPDATA%)
    keychain: str = ""  # macOS Keychain service holding the cookie key
    secret_apps: tuple[str, ...] = ()  # Linux libsecret "application" attribute


BROWSERS: tuple[BrowserSpec, ...] = (
    BrowserSpec(
        "chrome",
        "Google Chrome",
        "chromium",
        mac=("Google/Chrome",),
        linux=("google-chrome",),
        windows=("Google/Chrome/User Data",),
        keychain="Chrome Safe Storage",
        secret_apps=("chrome",),
    ),
    BrowserSpec(
        "chromium",
        "Chromium",
        "chromium",
        mac=("Chromium",),
        linux=("chromium",),
        windows=("Chromium/User Data",),
        keychain="Chromium Safe Storage",
        secret_apps=("chromium",),
    ),
    BrowserSpec(
        "brave",
        "Brave",
        "chromium",
        mac=("BraveSoftware/Brave-Browser",),
        linux=("BraveSoftware/Brave-Browser",),
        windows=("BraveSoftware/Brave-Browser/User Data",),
        keychain="Brave Safe Storage",
        secret_apps=("brave", "chromium"),
    ),
    BrowserSpec(
        "edge",
        "Microsoft Edge",
        "chromium",
        mac=("Microsoft Edge",),
        linux=("microsoft-edge",),
        windows=("Microsoft/Edge/User Data",),
        keychain="Microsoft Edge Safe Storage",
        secret_apps=("microsoft-edge", "chromium"),
    ),
    BrowserSpec(
        "arc",
        "Arc",
        "chromium",
        mac=("Arc/User Data",),
        keychain="Arc Safe Storage",
    ),
    BrowserSpec(
        "vivaldi",
        "Vivaldi",
        "chromium",
        mac=("Vivaldi",),
        linux=("vivaldi",),
        windows=("Vivaldi/User Data",),
        keychain="Vivaldi Safe Storage",
        secret_apps=("vivaldi", "chromium"),
    ),
    BrowserSpec(
        "firefox",
        "Firefox",
        "firefox",
        mac=("Firefox",),
        linux=(
            ".mozilla/firefox",
            "snap/firefox/common/.mozilla/firefox",
            ".var/app/org.mozilla.firefox/.mozilla/firefox",
        ),
        windows=("Mozilla/Firefox",),
    ),
)
_BY_KEY = {spec.key: spec for spec in BROWSERS}


@dataclass(frozen=True)
class HostEnv:
    """Where to look; tests pass a temporary home instead of the real one."""

    home: Path
    platform: str
    env: Mapping[str, str]

    @classmethod
    def current(cls) -> HostEnv:
        return cls(Path.home(), sys.platform, os.environ)

    @property
    def is_mac(self) -> bool:
        return self.platform == "darwin"

    @property
    def is_windows(self) -> bool:
        return self.platform.startswith("win")


@dataclass(frozen=True)
class LoginSource:
    spec: BrowserSpec
    profile: str  # Chromium: profile folder name; Firefox: profiles.ini Path
    name: str
    email: str
    user_data: Path  # Chromium: the folder holding Local State; Firefox: its root
    cookie_db: Path
    last_used: bool
    supported: bool
    reason: str = ""
    cookies: int | None = None

    def cookie_mtime(self) -> float | None:
        try:
            return self.cookie_db.stat().st_mtime
        except OSError:
            return None  # A missing database simply means nothing to refresh.

    def public(self, platform: str) -> dict[str, Any]:
        """What the UI may see: no paths, no keys, no values."""
        return {
            "id": f"{self.spec.key}:{self.profile}",
            "browser": self.spec.key,
            "browser_name": self.spec.label,
            "profile": self.profile,
            "name": self.name,
            "email": self.email,
            "cookies": self.cookies,
            "last_used": self.last_used,
            "supported": self.supported,
            "reason": self.reason,
            "keychain_prompt": self.supported
            and self.spec.family == "chromium"
            and platform == "darwin",
        }


@dataclass
class ReadResult:
    cookies: list[dict[str, Any]] = field(default_factory=list)
    expired: int = 0
    skipped: int = 0  # partitioned or container cookies, unusable rows
    undecryptable: int = 0


# ---------------------------------------------------------------- detection


def _roots(spec: BrowserSpec, host: HostEnv) -> list[Path]:
    if host.is_mac:
        base = host.home / "Library" / "Application Support"
        return [base / rel for rel in spec.mac]
    if host.is_windows:
        name = "APPDATA" if spec.family == "firefox" else "LOCALAPPDATA"
        default = "AppData/Roaming" if spec.family == "firefox" else "AppData/Local"
        base = Path(host.env.get(name) or host.home / default)
        return [base / rel for rel in spec.windows]
    if spec.family == "firefox":
        return [host.home / rel for rel in spec.linux]
    base = Path(host.env.get("XDG_CONFIG_HOME") or host.home / ".config")
    return [(base / rel) for rel in spec.linux]


def _count_rows(db: Path, table: str) -> int | None:
    """Count without locking or changing the person's live database."""
    try:
        uri = f"file:{pathname2url(str(db))}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 — fixed table names
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None  # A locked or unreadable database shows no count, not an error.


def _chromium_cookie_db(profile_dir: Path) -> Path | None:
    for candidate in (profile_dir / "Network" / "Cookies", profile_dir / "Cookies"):
        if candidate.is_file():
            return candidate
    return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # A missing or half-written Local State means "no metadata".
    return value if isinstance(value, dict) else {}


def _chromium_support(spec: BrowserSpec, host: HostEnv, local_state: dict) -> tuple[bool, str]:
    if host.is_windows:
        if spec.key == "chrome":
            return False, _WINDOWS_CHROME_REASON
        os_crypt = local_state.get("os_crypt")
        if not isinstance(os_crypt, dict) or not os_crypt.get("encrypted_key"):
            return False, f"{spec.label} did not publish a readable cookie key."
        return True, ""
    if host.is_mac and not spec.keychain:
        return False, f"{spec.label} is not supported on this Mac."
    return True, ""


def _chromium_sources(spec: BrowserSpec, root: Path, host: HostEnv) -> list[LoginSource]:
    local_state = _read_json(root / "Local State")
    profile_info = local_state.get("profile")
    profile_info = profile_info if isinstance(profile_info, dict) else {}
    cache = profile_info.get("info_cache")
    cache = cache if isinstance(cache, dict) else {}
    last_used = str(profile_info.get("last_used") or "Default")
    names = [str(name) for name in cache]
    if not names:
        # Without Local State metadata, fall back to the usual folder names.
        try:
            names = sorted(
                p.name
                for p in root.iterdir()
                if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile "))
            )
        except OSError:
            names = []  # An unreadable folder has no profiles to offer.
    supported, reason = _chromium_support(spec, host, local_state)
    sources = []
    for name in names:
        if not _PROFILE_DIR.fullmatch(name) or name in _SKIPPED_CHROMIUM_PROFILES:
            continue
        db = _chromium_cookie_db(root / name)
        if db is None:
            continue
        info = cache.get(name)
        info = info if isinstance(info, dict) else {}
        sources.append(
            LoginSource(
                spec=spec,
                profile=name,
                name=str(info.get("name") or info.get("gaia_name") or name)[:120],
                email=str(info.get("user_name") or "")[:200],
                user_data=root,
                cookie_db=db,
                last_used=name == last_used,
                supported=supported,
                reason=reason,
                cookies=_count_rows(db, "cookies"),
            )
        )
    return sources


def _firefox_sources(spec: BrowserSpec, root: Path) -> list[LoginSource]:
    ini = configparser.ConfigParser(interpolation=None)
    try:
        ini.read(root / "profiles.ini", encoding="utf-8")
    except (OSError, configparser.Error):
        return []  # A broken profiles.ini offers nothing; Firefox rewrites it.
    install_defaults = {
        ini.get(section, "Default", fallback="")
        for section in ini.sections()
        if section.startswith("Install")
    }
    sources = []
    for section in ini.sections():
        if not section.startswith("Profile"):
            continue
        rel = ini.get(section, "Path", fallback="").strip()
        if not rel or len(rel) > 300:
            continue
        relative = ini.get(section, "IsRelative", fallback="1").strip() != "0"
        folder = (root / rel) if relative else Path(rel)
        db = folder / "cookies.sqlite"
        if not db.is_file():
            continue
        sources.append(
            LoginSource(
                spec=spec,
                profile=rel,
                name=ini.get(section, "Name", fallback=rel)[:120],
                email="",
                user_data=root,
                cookie_db=db,
                last_used=rel in install_defaults
                or (not install_defaults and ini.get(section, "Default", fallback="") == "1"),
                supported=True,
                cookies=_count_rows(db, "moz_cookies"),
            )
        )
    return sources


def _sources_for(spec: BrowserSpec, host: HostEnv) -> list[LoginSource]:
    for root in _roots(spec, host):
        if not root.is_dir():
            continue
        found = (
            _firefox_sources(spec, root)
            if spec.family == "firefox"
            else _chromium_sources(spec, root, host)
        )
        if found:
            found.sort(key=lambda source: (not source.last_used, source.profile))
            return found
    return []


def detect_sources(host: HostEnv | None = None) -> list[LoginSource]:
    """Installed browser profiles with logins. Never reads a key or a value."""
    host = host or HostEnv.current()
    result: list[LoginSource] = []
    for spec in BROWSERS:
        try:
            result.extend(_sources_for(spec, host))
        except OSError:
            log.debug("Browser login detection skipped %s", spec.label, exc_info=True)
    return result


def find_source(browser: str, profile: str, host: HostEnv | None = None) -> LoginSource | None:
    """Only a source that detection itself reports can be imported."""
    spec = _BY_KEY.get(browser)
    if spec is None or not isinstance(profile, str):
        return None
    host = host or HostEnv.current()
    return next((s for s in _sources_for(spec, host) if s.profile == profile), None)


# --------------------------------------------------------------- decryption


def _pbkdf2(password: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", password, _SALT, iterations, 16)


class ChromiumDecryptor:
    """Decrypts ``v10``/``v11`` cookie values; ``v20`` (app-bound) stays locked."""

    def __init__(
        self,
        *,
        cbc_keys: Mapping[bytes, list[bytes]] | None = None,
        gcm_key: bytes | None = None,
    ) -> None:
        self.cbc_keys = {prefix: list(keys) for prefix, keys in (cbc_keys or {}).items()}
        self.gcm_key = gcm_key

    @staticmethod
    def _plain(data: bytes, host_key: str, hashed: bool) -> str | None:
        if hashed:
            if len(data) < 32 or data[:32] != hashlib.sha256(host_key.encode()).digest():
                return None
            data = data[32:]
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None  # A wrong key yields bytes that are not text.

    def decrypt(self, blob: bytes, host_key: str, *, hashed: bool) -> str | None:
        prefix, body = bytes(blob[:3]), bytes(blob[3:])
        if prefix == b"v10" and self.gcm_key is not None:
            from cryptography.exceptions import InvalidTag
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            if len(body) < 12 + 16:
                return None
            try:
                data = AESGCM(self.gcm_key).decrypt(body[:12], body[12:], None)
            except InvalidTag:
                return None  # A wrong key or a damaged row; counted as undecryptable.
            return self._plain(data, host_key, hashed)
        keys = self.cbc_keys.get(prefix)
        if not keys or not body or len(body) % 16:
            return None
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        for key in keys:
            decryptor = Cipher(algorithms.AES(key), modes.CBC(_IV)).decryptor()
            padded = decryptor.update(body) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            try:
                data = unpadder.update(padded) + unpadder.finalize()
            except ValueError:
                continue  # Bad padding: this key is not the right one.
            plain = self._plain(data, host_key, hashed)
            if plain is not None:
                return plain
        return None


def _mac_key(service: str) -> bytes:
    """Read the browser's cookie key; the first call shows macOS' consent dialog."""
    try:
        result = subprocess.run(  # noqa: S603 — fixed binary, no shell
            ["/usr/bin/security", "find-generic-password", "-w", "-s", service],
            capture_output=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LoginImportError(
            "keychain_unavailable", "The Keychain did not answer. Try the import again."
        ) from exc
    secret = result.stdout.strip()
    if result.returncode != 0 or not secret:
        raise LoginImportError(
            "keychain_denied",
            "macOS did not allow access to the browser's Keychain item. "
            "Choose Allow or Always Allow when macOS asks.",
        )
    return secret


def _linux_secret(apps: tuple[str, ...]) -> bytes | None:
    tool = shutil.which("secret-tool")
    if tool is None:
        return None
    for app in apps:
        try:
            result = subprocess.run(  # noqa: S603 — fixed arguments, no shell
                [tool, "lookup", "application", app],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            log.debug("libsecret lookup failed")
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    windll = getattr(ctypes, "windll")  # noqa: B009 — exists only on Windows
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    if not windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise LoginImportError("key_unavailable", "Windows could not unlock the browser's key.")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        windll.kernel32.LocalFree(blob_out.pbData)


def decryptor_for(source: LoginSource, host: HostEnv | None = None) -> ChromiumDecryptor:
    """Build the key for one source. This is the only place that reads a key."""
    host = host or HostEnv.current()
    spec = source.spec
    if host.is_mac:
        return ChromiumDecryptor(cbc_keys={b"v10": [_pbkdf2(_mac_key(spec.keychain), 1003)]})
    if host.is_windows:
        if not source.supported:
            raise LoginImportError("unsupported", source.reason)
        os_crypt = _read_json(source.user_data / "Local State").get("os_crypt") or {}
        try:
            wrapped = base64.b64decode(str(os_crypt.get("encrypted_key") or ""))
        except ValueError as exc:
            raise LoginImportError("key_unavailable", "The browser's key is unreadable.") from exc
        if not wrapped.startswith(b"DPAPI"):
            raise LoginImportError("key_unavailable", "The browser's key is unreadable.")
        return ChromiumDecryptor(gcm_key=_dpapi_unprotect(wrapped[5:]))
    secret = _linux_secret(spec.secret_apps)
    v11 = [_pbkdf2(secret, 1)] if secret else []
    # Without a keyring Chromium falls back to an empty password for v11.
    v11.append(_pbkdf2(b"", 1))
    return ChromiumDecryptor(cbc_keys={b"v10": [_pbkdf2(b"peanuts", 1)], b"v11": v11})


# ------------------------------------------------------------------ reading


@contextmanager
def _private_copy(db: Path) -> Iterator[Path]:
    """A private copy (with its WAL) so the person's browser is never disturbed."""
    with tempfile.TemporaryDirectory(prefix="dodaios-logins-") as folder:
        target = Path(folder) / db.name
        try:
            shutil.copyfile(db, target)
            wal = db.with_name(db.name + "-wal")
            if wal.is_file():
                shutil.copyfile(wal, target.with_name(target.name + "-wal"))
        except OSError as exc:
            raise LoginImportError(
                "source_locked",
                "The browser's login file could not be read. Close that browser and try again.",
            ) from exc
        yield target


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def cookie_param(
    *,
    name: str,
    value: str,
    host: str,
    path: str,
    secure: bool,
    http_only: bool,
    same_site: str | None,
    expires: float | None,
) -> dict[str, Any]:
    """One CDP ``Network.CookieParam``; a host-only cookie keeps no Domain."""
    param: dict[str, Any] = {
        "name": name,
        "value": value,
        "path": path or "/",
        "secure": secure,
        "httpOnly": http_only,
    }
    if host.startswith("."):
        param["domain"] = host
    else:
        param["url"] = f"{'https' if secure else 'http'}://{host}{path or '/'}"
    # SameSite=None without Secure is rejected; leave it to the browser default.
    if same_site and not (same_site == "None" and not secure):
        param["sameSite"] = same_site
    if expires is not None:
        param["expires"] = float(expires)
    return param


def chrome_time_to_unix(value: int) -> float:
    return value / 1_000_000 - _CHROME_EPOCH_OFFSET_S


def _read_chromium(db: Path, decryptor: Callable[[], ChromiumDecryptor], now: float) -> ReadResult:
    result = ReadResult()
    conn = sqlite3.connect(db)
    try:
        cols = _columns(conn, "cookies")
        try:
            version = int(conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        except (sqlite3.Error, TypeError, ValueError):
            version = 0  # Very old databases have no meta row; values are not hashed.
        secure = "is_secure" if "is_secure" in cols else "secure"
        http_only = "is_httponly" if "is_httponly" in cols else "httponly"
        persistent = "is_persistent" if "is_persistent" in cols else "persistent"
        partition = "top_frame_site_key" if "top_frame_site_key" in cols else "''"
        same_site = "samesite" if "samesite" in cols else "-1"
        rows = conn.execute(
            f"SELECT host_key, name, value, encrypted_value, path, expires_utc, "  # noqa: S608 — column names from PRAGMA
            f"{secure}, {http_only}, {persistent}, {same_site}, {partition} FROM cookies"
        ).fetchall()
        # All rows are read before any key is: a key error raised mid-iteration
        # would keep the cursor (and on Windows the temp file) open.
        hashed = version >= _HASHED_VALUES_VERSION
        active: ChromiumDecryptor | None = None
        for host, name, plain, encrypted, path, expires_utc, sec, http, keep, site, part in rows:
            host = str(host or "")
            if not host or part:
                result.skipped += 1  # partitioned (third-party embed) cookies are not logins
                continue
            expires = None
            if keep and expires_utc:
                expires = chrome_time_to_unix(int(expires_utc))
                if expires <= now:
                    result.expired += 1
                    continue
            value = str(plain or "")
            if not value and encrypted:
                if active is None:
                    active = decryptor()
                decoded = active.decrypt(bytes(encrypted), host, hashed=hashed)
                if decoded is None:
                    result.undecryptable += 1
                    continue
                value = decoded
            result.cookies.append(
                cookie_param(
                    name=str(name or ""),
                    value=value,
                    host=host,
                    path=str(path or "/"),
                    secure=bool(sec),
                    http_only=bool(http),
                    same_site=_CHROMIUM_SAMESITE.get(int(site if site is not None else -1)),
                    expires=expires,
                )
            )
    finally:
        conn.close()
    return result


def _read_firefox(db: Path, now: float) -> ReadResult:
    result = ReadResult()
    conn = sqlite3.connect(db)
    try:
        cols = _columns(conn, "moz_cookies")
        same_site = "sameSite" if "sameSite" in cols else "-1"
        origin = "originAttributes" if "originAttributes" in cols else "''"
        rows = conn.execute(
            f"SELECT host, name, value, path, expiry, isSecure, isHttpOnly, {same_site}, "  # noqa: S608 — column names from PRAGMA
            f"{origin} FROM moz_cookies"
        ).fetchall()
        for host, name, value, path, expiry, sec, http, site, attributes in rows:
            host = str(host or "")
            if not host or attributes:
                result.skipped += 1  # containers and partitioned cookies stay in Firefox
                continue
            expires = float(expiry or 0) or None
            if expires is not None and expires > 1e11:
                expires /= 1000  # newer Firefox stores milliseconds
            if expires is not None and expires <= now:
                result.expired += 1
                continue
            result.cookies.append(
                cookie_param(
                    name=str(name or ""),
                    value=str(value or ""),
                    host=host,
                    path=str(path or "/"),
                    secure=bool(sec),
                    http_only=bool(http),
                    same_site=_FIREFOX_SAMESITE.get(int(site if site is not None else -1)),
                    expires=expires,
                )
            )
    finally:
        conn.close()
    return result


def read_source_cookies(
    source: LoginSource,
    *,
    decryptor: ChromiumDecryptor | None = None,
    host: HostEnv | None = None,
    now: float | None = None,
) -> ReadResult:
    """All unexpired cookies of one source as CDP params (values in memory only).

    For a Chromium source the key is read only when the first encrypted value
    is met; pass ``decryptor`` to supply one (tests never touch a Keychain).
    """
    if not source.supported:
        raise LoginImportError("unsupported", source.reason or "This browser is not supported.")
    current = time.time() if now is None else now

    def key() -> ChromiumDecryptor:
        return decryptor if decryptor is not None else decryptor_for(source, host)

    with _private_copy(source.cookie_db) as copy:
        try:
            if source.spec.family == "firefox":
                return _read_firefox(copy, current)
            return _read_chromium(copy, key, current)
        except sqlite3.Error as exc:
            raise LoginImportError(
                "source_unreadable", "The browser's login file could not be read."
            ) from exc


def site_of(cookie: Mapping[str, Any]) -> str:
    """Approximate registrable site of a cookie param, for per-site totals."""
    host = str(cookie.get("domain") or "")
    if not host:
        url = str(cookie.get("url") or "")
        host = url.split("://", 1)[-1].split("/", 1)[0]
    labels = host.lstrip(".").lower().split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    keep = 3 if len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-keep:])
