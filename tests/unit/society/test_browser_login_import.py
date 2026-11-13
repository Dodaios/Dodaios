"""Importing website logins from installed browsers, with synthetic data only.

Every database, Local State and profiles.ini here is built in a temporary
home. No test reads the real Keychain, a real browser profile, or starts a
browser: the key is supplied, and the Keychain/secret-tool calls are trapped.
"""

from __future__ import annotations

import base64
import configparser
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dodaios.society.browser import login_import
from dodaios.society.browser.live import LiveSessions
from dodaios.society.browser.login_import import (
    ChromiumDecryptor,
    HostEnv,
    LoginImportError,
    chrome_time_to_unix,
    detect_sources,
    find_source,
    read_source_cookies,
    site_of,
)
from tests.fakes.fake_browser_profiles import ProfileSession

NOW = 1_800_000_000.0  # a fixed "now" so expiry checks are deterministic
KEY = hashlib.pbkdf2_hmac("sha1", b"fixture-safe-storage", b"saltysalt", 1003, 16)
WRONG_KEY = hashlib.pbkdf2_hmac("sha1", b"another-password", b"saltysalt", 1003, 16)
COOKIE_VALUE = "fixture-session-value-7f3a"


@pytest.fixture(autouse=True)
def no_real_secrets(monkeypatch):
    """Any attempt to read a real key or run a helper fails the test."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("tests must never read a real Keychain or keyring")

    monkeypatch.setattr(login_import, "_mac_key", forbidden)
    monkeypatch.setattr(login_import, "_linux_secret", forbidden)
    monkeypatch.setattr(login_import, "_dpapi_unprotect", forbidden)
    monkeypatch.setattr(login_import.subprocess, "run", forbidden)


def unix_to_chrome(seconds: float) -> int:
    return int((seconds + 11_644_473_600) * 1_000_000)


def cbc(value: str, host: str, key: bytes = KEY, *, hashed: bool = True) -> bytes:
    data = (hashlib.sha256(host.encode()).digest() if hashed else b"") + value.encode()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
    return b"v10" + encryptor.update(padded) + encryptor.finalize()


def chromium_db(path: Path, rows: list[dict], version: int = 24) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE meta(key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR);
        CREATE TABLE cookies(
          creation_utc INTEGER NOT NULL, host_key TEXT NOT NULL, top_frame_site_key TEXT NOT NULL,
          name TEXT NOT NULL, value TEXT NOT NULL, encrypted_value BLOB NOT NULL,
          path TEXT NOT NULL, expires_utc INTEGER NOT NULL, is_secure INTEGER NOT NULL,
          is_httponly INTEGER NOT NULL, last_access_utc INTEGER NOT NULL,
          has_expires INTEGER NOT NULL, is_persistent INTEGER NOT NULL,
          priority INTEGER NOT NULL, samesite INTEGER NOT NULL, source_scheme INTEGER NOT NULL,
          source_port INTEGER NOT NULL, last_update_utc INTEGER NOT NULL,
          source_type INTEGER NOT NULL, has_cross_site_ancestor INTEGER NOT NULL);
        """
    )
    conn.execute("INSERT INTO meta VALUES('version', ?)", (str(version),))
    for row in rows:
        conn.execute(
            "INSERT INTO cookies VALUES(0,?,?,?,?,?,?,?,?,?,0,?,?,1,?,2,443,0,0,0)",
            (
                row["host"],
                row.get("partition", ""),
                row["name"],
                row.get("plain", ""),
                row.get("encrypted", b""),
                row.get("path", "/"),
                row.get("expires", 0),
                row.get("secure", 1),
                row.get("http_only", 0),
                1 if row.get("expires") else 0,
                1 if row.get("expires") else 0,
                row.get("samesite", -1),
            ),
        )
    conn.commit()
    conn.close()


def mac_home(tmp_path: Path) -> tuple[HostEnv, Path]:
    home = tmp_path / "home"
    chrome = home / "Library/Application Support/Google/Chrome"
    chrome.mkdir(parents=True)
    (chrome / "Local State").write_text(
        json.dumps(
            {
                "profile": {
                    "last_used": "Profile 1",
                    "info_cache": {
                        "Default": {"name": "Person 1", "user_name": ""},
                        "Profile 1": {"name": "Work", "user_name": "owner@example.com"},
                        "System Profile": {"name": "System"},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return HostEnv(home, "darwin", {}), chrome


def standard_rows() -> list[dict]:
    future = unix_to_chrome(NOW + 86_400)
    return [
        # Host-only, secure, Lax, persistent: keeps no Domain attribute.
        {
            "host": "app.example.com",
            "name": "sid",
            "encrypted": cbc(COOKIE_VALUE, "app.example.com"),
            "expires": future,
            "http_only": 1,
            "samesite": 1,
        },
        # Domain cookie, session (no expiry), SameSite=None on a secure cookie.
        {
            "host": ".example.com",
            "name": "pref",
            "encrypted": cbc("dark", ".example.com"),
            "samesite": 0,
        },
        # Already expired.
        {
            "host": ".old.example",
            "name": "gone",
            "encrypted": cbc("x", ".old.example"),
            "expires": unix_to_chrome(NOW - 60),
        },
        # A partitioned third-party embed cookie.
        {
            "host": ".embed.example",
            "name": "chip",
            "encrypted": cbc("y", ".embed.example"),
            "partition": "https://news.example",
            "expires": future,
        },
        # Encrypted with another key: cannot be read.
        {
            "host": ".other.example",
            "name": "locked",
            "encrypted": cbc("z", ".other.example", WRONG_KEY),
            "expires": future,
        },
        # Plaintext legacy value, not secure, SameSite=None must be dropped.
        {
            "host": "legacy.example.co.uk",
            "name": "plain",
            "plain": "visible",
            "secure": 0,
            "samesite": 0,
            "expires": future,
        },
    ]


def test_chromium_v24_decrypts_strips_host_hash_and_converts_to_cdp(tmp_path):
    host, chrome = mac_home(tmp_path)
    chromium_db(chrome / "Profile 1" / "Cookies", standard_rows())
    source = find_source("chrome", "Profile 1", host)
    assert source is not None and source.supported
    result = read_source_cookies(
        source, decryptor=ChromiumDecryptor(cbc_keys={b"v10": [KEY]}), now=NOW
    )
    assert (result.expired, result.skipped, result.undecryptable) == (1, 1, 1)
    by_name = {cookie["name"]: cookie for cookie in result.cookies}
    assert set(by_name) == {"sid", "pref", "plain"}
    assert by_name["sid"] == {
        "name": "sid",
        "value": COOKIE_VALUE,
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "url": "https://app.example.com/",
        "sameSite": "Lax",
        "expires": pytest.approx(NOW + 86_400, abs=1),
    }
    assert by_name["pref"]["domain"] == ".example.com" and "url" not in by_name["pref"]
    assert by_name["pref"]["sameSite"] == "None"
    assert "expires" not in by_name["pref"]  # a session cookie stays a session cookie
    assert by_name["plain"]["value"] == "visible"
    assert by_name["plain"]["url"] == "http://legacy.example.co.uk/"
    assert "sameSite" not in by_name["plain"]


def test_chromium_reading_uses_a_private_copy_and_leaves_the_source_unchanged(tmp_path):
    host, chrome = mac_home(tmp_path)
    db = chrome / "Profile 1" / "Cookies"
    chromium_db(db, standard_rows())
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    source = find_source("chrome", "Profile 1", host)
    read_source_cookies(source, decryptor=ChromiumDecryptor(cbc_keys={b"v10": [KEY]}), now=NOW)
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before
    assert sorted(p.name for p in db.parent.iterdir()) == ["Cookies"]


def test_older_databases_have_no_hash_prefix(tmp_path):
    host, chrome = mac_home(tmp_path)
    rows = [
        {
            "host": ".example.com",
            "name": "a",
            "expires": unix_to_chrome(NOW + 10),
            "encrypted": cbc("old-style", ".example.com", hashed=False),
        }
    ]
    chromium_db(chrome / "Profile 1" / "Cookies", rows, version=18)
    result = read_source_cookies(
        find_source("chrome", "Profile 1", host),
        decryptor=ChromiumDecryptor(cbc_keys={b"v10": [KEY]}),
        now=NOW,
    )
    assert [c["value"] for c in result.cookies] == ["old-style"]


def test_a_hash_for_another_host_is_rejected():
    blob = cbc("v", "a.example")
    decryptor = ChromiumDecryptor(cbc_keys={b"v10": [KEY]})
    assert decryptor.decrypt(blob, "a.example", hashed=True) == "v"
    assert decryptor.decrypt(blob, "b.example", hashed=True) is None


def test_windows_gcm_values_decrypt_and_app_bound_values_stay_locked():
    key = bytes(range(32))
    nonce = b"\x01" * 12
    host = ".example.com"
    data = hashlib.sha256(host.encode()).digest() + b"gcm-value"
    blob = b"v10" + nonce + AESGCM(key).encrypt(nonce, data, None)
    decryptor = ChromiumDecryptor(gcm_key=key)
    assert decryptor.decrypt(blob, host, hashed=True) == "gcm-value"
    assert decryptor.decrypt(b"v20" + blob[3:], host, hashed=True) is None


def test_linux_without_a_keyring_uses_the_fixed_v10_key(tmp_path, monkeypatch):
    monkeypatch.setattr(login_import, "_linux_secret", lambda apps: None)
    home = tmp_path / "home"
    root = home / ".config" / "google-chrome"
    root.mkdir(parents=True)
    peanuts = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)
    chromium_db(
        root / "Default" / "Network" / "Cookies",
        [
            {
                "host": ".example.com",
                "name": "a",
                "expires": unix_to_chrome(NOW + 10),
                "encrypted": cbc("linux-value", ".example.com", peanuts),
            }
        ],
    )
    host = HostEnv(home, "linux", {})
    source = find_source("chrome", "Default", host)
    assert source is not None and source.cookie_db.parent.name == "Network"
    result = read_source_cookies(source, host=host, now=NOW)
    assert [c["value"] for c in result.cookies] == ["linux-value"]


def test_a_denied_keychain_is_a_readable_error_without_values(tmp_path, monkeypatch):
    host, chrome = mac_home(tmp_path)
    chromium_db(chrome / "Profile 1" / "Cookies", standard_rows())

    def denied(service):
        assert service == "Chrome Safe Storage"
        raise LoginImportError("keychain_denied", "macOS did not allow access")

    monkeypatch.setattr(login_import, "_mac_key", denied)
    with pytest.raises(LoginImportError) as caught:
        read_source_cookies(find_source("chrome", "Profile 1", host), host=host, now=NOW)
    assert caught.value.code == "keychain_denied"
    assert COOKIE_VALUE not in str(caught.value)


def firefox_home(tmp_path: Path) -> tuple[HostEnv, Path]:
    home = tmp_path / "home"
    root = home / "Library/Application Support/Firefox"
    profile = root / "Profiles" / "abc.default-release"
    profile.mkdir(parents=True)
    ini = configparser.ConfigParser()
    ini["Profile0"] = {
        "Name": "default-release",
        "IsRelative": "1",
        "Path": "Profiles/abc.default-release",
    }
    ini["InstallABC"] = {"Default": "Profiles/abc.default-release"}
    with (root / "profiles.ini").open("w", encoding="utf-8") as handle:
        ini.write(handle)
    conn = sqlite3.connect(profile / "cookies.sqlite")
    conn.execute(
        "CREATE TABLE moz_cookies(id INTEGER PRIMARY KEY,"
        " originAttributes TEXT NOT NULL DEFAULT '', name TEXT, value TEXT, host TEXT,"
        " path TEXT, expiry INTEGER, lastAccessed INTEGER,"
        " creationTime INTEGER, isSecure INTEGER, isHttpOnly INTEGER, sameSite INTEGER)"
    )
    rows = [
        ("", "session", COOKIE_VALUE, ".example.org", "/", int(NOW + 3600), 1, 1, 2),
        ("", "ms", "milli", "shop.example.org", "/cart", int((NOW + 60) * 1000), 0, 0, 0),
        ("^userContextId=1", "container", "c", ".example.org", "/", int(NOW + 3600), 1, 0, 1),
        ("", "expired", "e", ".example.org", "/", int(NOW - 1), 1, 0, 1),
    ]
    conn.executemany(
        "INSERT INTO moz_cookies(originAttributes,name,value,host,path,expiry,isSecure,"
        "isHttpOnly,sameSite) VALUES(?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return HostEnv(home, "darwin", {}), root


def test_firefox_cookies_convert_without_any_key(tmp_path):
    host, _root = firefox_home(tmp_path)
    source = find_source("firefox", "Profiles/abc.default-release", host)
    assert source is not None and source.last_used and source.cookies == 4
    result = read_source_cookies(source, now=NOW)
    assert (result.expired, result.skipped) == (1, 1)
    by_name = {c["name"]: c for c in result.cookies}
    assert by_name["session"]["domain"] == ".example.org"
    assert by_name["session"]["sameSite"] == "Strict" and by_name["session"]["httpOnly"]
    assert by_name["ms"]["expires"] == pytest.approx(NOW + 60)
    assert by_name["ms"]["url"] == "http://shop.example.org/cart"
    assert "sameSite" not in by_name["ms"]  # SameSite=None without Secure is left to Chrome


def test_detection_lists_profiles_without_keys_paths_or_values(tmp_path):
    host, chrome = mac_home(tmp_path)
    chromium_db(chrome / "Profile 1" / "Cookies", standard_rows())
    chromium_db(chrome / "Default" / "Cookies", standard_rows()[:2])
    chromium_db(chrome / "System Profile" / "Cookies", standard_rows()[:1])
    brave = host.home / "Library/Application Support/BraveSoftware/Brave-Browser"
    brave.mkdir(parents=True)
    (brave / "Local State").write_text("{}", encoding="utf-8")  # installed, never used
    firefox_home(tmp_path)
    sources = [s.public(host.platform) for s in detect_sources(host)]
    assert [(s["browser"], s["profile"]) for s in sources] == [
        ("chrome", "Profile 1"),
        ("chrome", "Default"),
        ("firefox", "Profiles/abc.default-release"),
    ]
    work = sources[0]
    assert work["name"] == "Work" and work["email"] == "owner@example.com"
    assert work["last_used"] and work["cookies"] == 6 and work["supported"]
    assert work["keychain_prompt"] and not sources[2]["keychain_prompt"]
    flat = json.dumps(sources)
    assert COOKIE_VALUE not in flat and str(tmp_path) not in flat


def test_windows_chrome_is_reported_unsupported_and_edge_is_offered(tmp_path):
    local = tmp_path / "Local"
    chrome = local / "Google/Chrome/User Data"
    edge = local / "Microsoft/Edge/User Data"
    for root, state in (
        (chrome, {"os_crypt": {"encrypted_key": "x", "app_bound_encrypted_key": "y"}}),
        (edge, {"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPIfixture").decode()}}),
    ):
        chromium_db(root / "Default" / "Network" / "Cookies", [])
        (root / "Local State").write_text(json.dumps(state), encoding="utf-8")
    host = HostEnv(tmp_path / "home", "win32", {"LOCALAPPDATA": str(local)})
    sources = {s.spec.key: s for s in detect_sources(host)}
    assert not sources["chrome"].supported and "Sign in once" in sources["chrome"].reason
    assert sources["edge"].supported
    with pytest.raises(LoginImportError) as caught:
        read_source_cookies(sources["chrome"], now=NOW)
    assert caught.value.code == "unsupported"


def test_unknown_or_undetected_profiles_are_not_importable(tmp_path):
    host, _chrome = mac_home(tmp_path)
    assert find_source("chrome", "../../etc", host) is None
    assert find_source("safari", "Default", host) is None
    assert find_source("chrome", "Profile 1", host) is None  # no Cookies file yet


def test_time_and_site_helpers():
    assert chrome_time_to_unix(unix_to_chrome(NOW)) == pytest.approx(NOW, abs=1e-3)
    assert site_of({"domain": ".mail.google.com"}) == "google.com"
    assert site_of({"url": "https://www.bbc.co.uk/news"}) == "bbc.co.uk"
    assert site_of({"url": "http://localhost/"}) == "localhost"


# ----------------------------------------------------- parent and worker side


def lead():
    return SimpleNamespace(agent_id="lead", browser_mode="own", browser_allowed_domains=[])


class ImportSession(ProfileSession):
    def __init__(self, reject=()):
        super().__init__("lead")
        self.profile_binding = SimpleNamespace(kind="managed")
        self.reject = set(reject)

    async def command(self, op, args=None, **kwargs):
        self.commands.append((op, args))
        cookies = (args or {}).get("cookies") or []
        failed = [i for i, c in enumerate(cookies) if c["name"] in self.reject]
        return {
            "imported": len(cookies) - len(failed),
            "failed": len(failed),
            "failed_indices": failed,
        }


def fake_source(tmp_path, mtime_file=True):
    db = tmp_path / "source-Cookies"
    if mtime_file:
        db.write_bytes(b"fixture")
    return login_import.LoginSource(
        spec=login_import._BY_KEY["chrome"],
        profile="Default",
        name="Person 1",
        email="",
        user_data=tmp_path,
        cookie_db=db,
        last_used=True,
        supported=True,
    )


def cookies(n, prefix="c"):
    return [
        {
            "name": f"{prefix}{i}",
            "value": COOKIE_VALUE,
            "path": "/",
            "secure": True,
            "httpOnly": False,
            "domain": f".site{i % 3}.example",
        }
        for i in range(n)
    ]


async def test_import_sends_the_list_to_the_worker_and_remembers_the_source(
    tmp_path, monkeypatch, caplog
):
    live = LiveSessions(tmp_path)
    session = ImportSession(reject={"c1"})
    source = fake_source(tmp_path)
    ensured = []

    async def ensure(agent, **kwargs):
        ensured.append(agent.agent_id)
        return session

    monkeypatch.setattr(live, "ensure", ensure)
    monkeypatch.setattr(login_import, "find_source", lambda b, p: source)
    sent = cookies(5)
    monkeypatch.setattr(
        login_import,
        "read_source_cookies",
        lambda s: login_import.ReadResult(cookies=list(sent), expired=2, skipped=1),
    )
    caplog.set_level("DEBUG")
    result = await live.import_logins(lead(), "chrome", "Default")
    assert ensured == ["lead"] and result["started"]
    assert session.commands == [("import_cookies", {"cookies": sent})]
    assert (result["imported"], result["failed"], result["expired"]) == (4, 1, 2)
    assert result["sites"] == {"site0.example": 2, "site2.example": 1, "site1.example": 1}
    assert COOKIE_VALUE not in caplog.text
    record = live.profiles.login_source("agent-lead")
    assert record["browser"] == "chrome" and record["profile"] == "Default"
    assert record["imported"] == 4 and record["sites"] == 3 and record["status"] == "ok"
    assert session.logins_imported
    await live.close()


async def test_large_imports_are_split_below_the_pipe_limit(tmp_path):
    live = LiveSessions(tmp_path)
    session = ImportSession()
    result = await live.send_cookies(session, cookies(900))
    sizes = [len(args["cookies"]) for op, args in session.commands]
    assert sizes == [400, 400, 100] and result["imported"] == 900
    await live.close()


async def test_extension_profiles_do_not_accept_imported_cookies(tmp_path):
    live = LiveSessions(tmp_path)
    session = ImportSession()
    session.profile_binding = SimpleNamespace(kind="chrome")
    with pytest.raises(ValueError, match="Dodaios browser profile"):
        await live.send_cookies(session, cookies(1))
    assert session.commands == []
    await live.close()


async def test_start_refresh_reimports_only_when_the_source_changed(tmp_path, monkeypatch):
    live = LiveSessions(tmp_path)
    source = fake_source(tmp_path)
    binding = live.profiles.resolve(lead())
    live.profiles.remember_login_source(
        binding.key,
        browser="chrome",
        profile="Default",
        imported_at=source.cookie_mtime() + 5,
        source_mtime=source.cookie_mtime(),
        imported=1,
        failed=0,
        sites=1,
    )
    monkeypatch.setattr(login_import, "find_source", lambda b, p: source)
    reads = []

    def read(s):
        reads.append(s)
        return login_import.ReadResult(cookies=cookies(2))

    monkeypatch.setattr(login_import, "read_source_cookies", read)
    session = ImportSession()
    await live._refresh_logins(session, binding)
    assert reads == [] and session.commands == []  # unchanged since the last import

    live.profiles.remember_login_source(
        binding.key,
        browser="chrome",
        profile="Default",
        imported_at=1.0,
        source_mtime=0.5,
        imported=1,
        failed=0,
        sites=1,
    )
    await live._refresh_logins(session, binding)
    assert len(reads) == 1 and session.commands[0][0] == "import_cookies"
    assert live.profiles.login_source(binding.key)["imported"] == 2
    await live.close()


async def test_a_failed_refresh_keeps_the_browser_and_records_a_status(tmp_path, monkeypatch):
    live = LiveSessions(tmp_path)
    source = fake_source(tmp_path)
    binding = live.profiles.resolve(lead())
    live.profiles.remember_login_source(
        binding.key,
        browser="chrome",
        profile="Default",
        imported_at=1.0,
        source_mtime=0.5,
        imported=7,
        failed=0,
        sites=2,
    )
    monkeypatch.setattr(login_import, "find_source", lambda b, p: source)

    def denied(s):
        raise LoginImportError("keychain_denied", "denied")

    monkeypatch.setattr(login_import, "read_source_cookies", denied)
    session = ImportSession()
    await live._refresh_logins(session, binding)  # must not raise
    record = live.profiles.login_source(binding.key)
    assert record["status"] == "keychain_denied" and record["imported"] == 7
    assert session.commands == [] and not session.closed
    await live.close()


async def test_a_profile_without_a_remembered_source_never_creates_the_registry(tmp_path):
    live = LiveSessions(tmp_path)
    binding = SimpleNamespace(key="agent-lead", kind="managed")
    await live._refresh_logins(ImportSession(), binding)
    assert not live.profiles.path.exists()
    await live.close()


@pytest.fixture
def worker():
    previous = sys.stdout
    try:
        from dodaios.society.browser import live_runner
    finally:
        sys.stdout = previous
    return live_runner.Worker()


class FakeCdp:
    def __init__(self):
        self.sent = []
        self.detached = False

    async def send(self, method, params):
        self.sent.append((method, len(params["cookies"])))
        if any(c["name"] == "bad" for c in params["cookies"]):
            raise RuntimeError("Invalid cookie fields")

    async def detach(self):
        self.detached = True


async def test_worker_sets_cookies_browser_wide_and_counts_rejections(worker):
    cdp = FakeCdp()

    async def new_session():
        return cdp

    worker.owns_context = True
    worker.context = SimpleNamespace(browser=SimpleNamespace(new_browser_cdp_session=new_session))
    batch = cookies(3)
    batch[1] = {**batch[1], "name": "bad"}
    result = await worker.command("import_cookies", {"cookies": batch})
    assert result == {"imported": 2, "failed": 1, "failed_indices": [1]}
    assert cdp.sent[0] == ("Storage.setCookies", 3)  # one batch first, then one by one
    assert cdp.sent[1:] == [("Storage.setCookies", 1)] * 3
    assert cdp.detached


async def test_worker_refuses_imports_without_its_own_browser(worker):
    worker.owns_context = False
    worker.context = SimpleNamespace()
    with pytest.raises(RuntimeError, match="only while the Dodaios browser is open"):
        await worker.command("import_cookies", {"cookies": cookies(1)})
