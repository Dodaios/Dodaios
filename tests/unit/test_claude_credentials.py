"""The shared Claude credentials locator must let the FRESHEST login win.

Forensic ground truth (2026-07-10): every interactive Claude session on the
maintainer host runs through a profile manager that pins ``CLAUDE_CONFIG_DIR``
to a per-profile directory, so ``~/.claude/.credentials.json`` expired in
place on 07-08 while a freshly-refreshed login sat in the profile dir. Both
hardcoded ``~/.claude`` readers (mission-worker token injection and the
subscription card) reported "expired", the Jarvis-Agents banner declared the
worker unavailable, and every mission diverted to codex — although a live
login existed on disk the whole time.

Contract under test: ``freshest_claude_oauth`` scans every candidate config
dir and returns the live login with the farthest expiry; only when NO
candidate is live does it report expired/absent.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios import claude_credentials as cc

# Test fixtures, not real credentials.
_TEST_OAT = "sk-ant-oat01-test-token"  # noqa: S105 — test fixture, not a real token
_TEST_OAT_2 = "sk-ant-oat01-second-token"  # noqa: S105 — test fixture
_TEST_CLASSIC_KEY = "sk-ant-api03-classic-key"  # noqa: S105 — test fixture

NOW_S = 1_783_300_000.0  # arbitrary fixed wall clock for the tests


def _write_credentials(
    config_dir: Path,
    *,
    token: str = _TEST_OAT,
    expires_at_ms: float | None = None,
    subscription_type: str | None = None,
) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    oauth: dict[str, object] = {"accessToken": token}
    if expires_at_ms is not None:
        oauth["expiresAt"] = expires_at_ms
    if subscription_type is not None:
        oauth["subscriptionType"] = subscription_type
    creds = config_dir / ".credentials.json"
    creds.write_text(json.dumps({"claudeAiOauth": oauth}), encoding="utf-8")
    return creds


def _pin_dirs(monkeypatch: pytest.MonkeyPatch, dirs: list[Path]) -> None:
    monkeypatch.setattr(cc, "claude_config_dirs", lambda: dirs)


# -- freshest_claude_oauth ----------------------------------------------


def test_single_valid_login_is_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / "default"
    _write_credentials(
        d, expires_at_ms=(NOW_S + 3600.0) * 1000.0, subscription_type="max"
    )
    _pin_dirs(monkeypatch, [d])
    snap = cc.freshest_claude_oauth(now_fn=lambda: NOW_S)
    assert snap.status == "valid"
    assert snap.access_token == _TEST_OAT
    assert snap.subscription_type == "max"
    assert snap.config_dir == d


def test_valid_profile_login_beats_expired_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE 2026-07-10 shape: ~/.claude expired in place, the profile-manager
    dir holds the real, freshly-refreshed login — the login must win."""
    default = tmp_path / "dot-claude"
    profile = tmp_path / "profile"
    _write_credentials(default, expires_at_ms=(NOW_S - 48 * 3600.0) * 1000.0)
    _write_credentials(
        profile, token=_TEST_OAT_2, expires_at_ms=(NOW_S + 4 * 3600.0) * 1000.0
    )
    _pin_dirs(monkeypatch, [default, profile])
    snap = cc.freshest_claude_oauth(now_fn=lambda: NOW_S)
    assert snap.status == "valid"
    assert snap.access_token == _TEST_OAT_2
    assert snap.config_dir == profile


def test_freshest_of_two_valid_logins_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older = tmp_path / "older"
    fresher = tmp_path / "fresher"
    _write_credentials(older, expires_at_ms=(NOW_S + 600.0) * 1000.0)
    _write_credentials(
        fresher, token=_TEST_OAT_2, expires_at_ms=(NOW_S + 7200.0) * 1000.0
    )
    _pin_dirs(monkeypatch, [older, fresher])
    snap = cc.freshest_claude_oauth(now_fn=lambda: NOW_S)
    assert snap.access_token == _TEST_OAT_2
    assert snap.config_dir == fresher


def test_all_expired_reports_expired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write_credentials(
        a, expires_at_ms=(NOW_S - 3600.0) * 1000.0, subscription_type="max"
    )
    _write_credentials(b, expires_at_ms=(NOW_S - 7200.0) * 1000.0)
    _pin_dirs(monkeypatch, [a, b])
    snap = cc.freshest_claude_oauth(now_fn=lambda: NOW_S)
    assert snap.status == "expired"
    assert snap.access_token is None
    # The least-stale candidate is the reference (its tier feeds the UI).
    assert snap.config_dir == a
    assert snap.subscription_type == "max"


def test_no_readable_bearer_reports_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_dirs(monkeypatch, [tmp_path / "missing"])
    snap = cc.freshest_claude_oauth(now_fn=lambda: NOW_S)
    assert snap.status == "absent"
    assert snap.access_token is None
    assert snap.config_dir is None


def test_classic_api_key_in_bearer_slot_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / "d"
    _write_credentials(
        d, token=_TEST_CLASSIC_KEY, expires_at_ms=(NOW_S + 3600.0) * 1000.0
    )
    _pin_dirs(monkeypatch, [d])
    assert cc.freshest_claude_oauth(now_fn=lambda: NOW_S).status == "absent"


def test_missing_expiry_stays_fail_open_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Older credential shapes without expiresAt keep working (back-compat)."""
    d = tmp_path / "d"
    _write_credentials(d)
    _pin_dirs(monkeypatch, [d])
    snap = cc.freshest_claude_oauth(now_fn=lambda: NOW_S)
    assert snap.status == "valid"
    assert snap.access_token == _TEST_OAT


def test_token_expiring_within_slack_is_expired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bearer dying seconds from now would 401 mid-mission — never live."""
    d = tmp_path / "d"
    _write_credentials(d, expires_at_ms=(NOW_S + 10.0) * 1000.0)
    _pin_dirs(monkeypatch, [d])
    assert cc.freshest_claude_oauth(now_fn=lambda: NOW_S).status == "expired"


def test_garbage_file_is_tolerated_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / ".credentials.json").write_text("{not json", encoding="utf-8")
    _pin_dirs(monkeypatch, [d])
    assert cc.freshest_claude_oauth(now_fn=lambda: NOW_S).status == "absent"


# -- claude_config_dirs --------------------------------------------------


def test_config_dirs_env_override_comes_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env_dir = tmp_path / "pinned-profile"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(env_dir))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    dirs = cc.claude_config_dirs()
    assert dirs[0] == env_dir
    assert home / ".claude" in dirs


def test_config_dirs_include_profile_manager_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    profile = home / ".bridgespace" / "ai-profiles" / "claude" / "prof_x"
    profile.mkdir(parents=True)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    dirs = cc.claude_config_dirs()
    assert dirs[0] == home / ".claude"
    assert profile in dirs


def test_config_dirs_deduplicate_env_and_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    dirs = cc.claude_config_dirs()
    assert dirs.count(home / ".claude") == 1


# 2026-11-16: on macOS Claude Code keeps the login in the Keychain, not in
# .credentials.json; every account (even the working default) read as signed
# out, so the seat switcher had nowhere to move a spent seat.
def test_keychain_service_name_default_and_added_dirs(tmp_path, monkeypatch) -> None:
    from dodaios.claude_credentials import keychain_service_for

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", raising=False)

    assert keychain_service_for(Path.home() / ".claude") == "Claude Code-credentials"
    added = Path("/Users/x/.dodaios-data/agent-accounts/claude/soukrom-95586f")
    import hashlib

    suffix = hashlib.sha256(str(added).encode()).hexdigest()[:8]
    assert keychain_service_for(added) == f"Claude Code-credentials-{suffix}"


def test_login_in_keychain_counts_as_signed_in(tmp_path) -> None:
    from dodaios.claude_credentials import claude_login_in

    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"organizationType": "claude_max"}}), encoding="utf-8"
    )
    seen: list[str] = []

    def probe(service: str) -> bool:
        seen.append(service)
        return True

    snap = claude_login_in(tmp_path, keychain_probe=probe)
    assert snap.status == "valid"
    assert snap.access_token is None  # the secret is never read, only its presence
    assert snap.subscription_type == "max"
    assert seen and seen[0].startswith("Claude Code-credentials")


def test_no_file_and_no_keychain_item_stays_absent(tmp_path) -> None:
    from dodaios.claude_credentials import claude_login_in

    assert claude_login_in(tmp_path, keychain_probe=lambda _s: False).status == "absent"


def test_credentials_file_still_wins_over_keychain(tmp_path) -> None:
    from dodaios.claude_credentials import claude_login_in

    (tmp_path / ".credentials.json").write_text(
        json.dumps(
            {"claudeAiOauth": {"accessToken": "sk-ant-oat01-x", "expiresAt": 1,
                               "refreshToken": "x"}}
        ),
        encoding="utf-8",
    )
    called: list[str] = []
    snap = claude_login_in(tmp_path, keychain_probe=lambda s: called.append(s) or True)
    assert snap.status == "expired" and not called


def _keychain_json(token: str, expires_ms: float) -> str:
    return json.dumps(
        {"claudeAiOauth": {"accessToken": token, "expiresAt": expires_ms, "refreshToken": "r"}}
    )


def test_keychain_bearer_returns_a_live_token(tmp_path) -> None:
    """2026-11-17: usage stayed unreadable because only the item's presence was known."""
    seen: list[str] = []
    bearer = cc.keychain_bearer(
        tmp_path,
        reader=lambda s: seen.append(s) or _keychain_json("sk-ant-oat01-live", 2_000_000_000_000),
        now_fn=lambda: 1_000_000_000.0,
    )
    assert bearer == "sk-ant-oat01-live"
    assert seen == [cc.keychain_service_for(tmp_path)]


def test_keychain_bearer_skips_expired_unreadable_and_non_oauth(tmp_path) -> None:
    now = lambda: 1_900_000_000.0  # noqa: E731
    expired = _keychain_json("sk-ant-oat01-old", 1_500_000_000_000)
    assert cc.keychain_bearer(tmp_path, reader=lambda _s: expired, now_fn=now) is None
    assert cc.keychain_bearer(tmp_path, reader=lambda _s: None, now_fn=now) is None
    assert cc.keychain_bearer(tmp_path, reader=lambda _s: "not json", now_fn=now) is None
    api_key = _keychain_json("sk-ant-api03-x", 2_000_000_000_000)
    assert cc.keychain_bearer(tmp_path, reader=lambda _s: api_key, now_fn=now) is None


def _cc_service(raw: str) -> str:
    import hashlib
    import unicodedata

    digest = hashlib.sha256(unicodedata.normalize("NFC", raw).encode()).hexdigest()[:8]
    return f"Claude Code-credentials-{digest}"


def test_keychain_service_hashes_the_default_dir_once_the_variable_is_set(monkeypatch) -> None:
    """Claude Code drops the bare name as soon as CLAUDE_CONFIG_DIR is set, even
    for ~/.claude; the bare item may belong to another login."""
    monkeypatch.delenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", raising=False)
    default = Path.home() / ".claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(default))
    assert cc.keychain_service_for(default) == _cc_service(str(default))


def test_keychain_service_hashes_the_inherited_value_as_given(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", raising=False)
    raw = str(tmp_path / "profile") + "/"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", raw)
    assert cc.keychain_service_for(tmp_path / "profile") == _cc_service(raw)
    # An added seat beside it is still named after its own directory.
    other = tmp_path / "seat"
    assert cc.keychain_service_for(other) == _cc_service(str(other))


def test_keychain_service_normalizes_to_nfc(monkeypatch) -> None:
    import unicodedata

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", raising=False)
    decomposed = Path(unicodedata.normalize("NFD", "/Users/josé/seat"))
    composed = unicodedata.normalize("NFC", str(decomposed))
    assert cc.keychain_service_for(decomposed) == _cc_service(composed)


def test_keychain_service_follows_the_secure_storage_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", "")
    assert cc.keychain_service_for(tmp_path) == "Claude Code-credentials"
    monkeypatch.setenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", "/Users/x/store")
    assert cc.keychain_service_for(tmp_path) == _cc_service("/Users/x/store")


def test_keychain_login_reads_its_tier_from_the_fresher_account_file(
    tmp_path, monkeypatch
) -> None:
    """The default seat's identity lives in ~/.claude.json; a stale inner file loses."""
    import os

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", raising=False)
    inner = tmp_path / ".claude"
    inner.mkdir()
    stale = inner / ".claude.json"
    stale.write_text(
        json.dumps({"oauthAccount": {"emailAddress": "old@x", "organizationType": "claude_pro"}}),
        encoding="utf-8",
    )
    os.utime(stale, (1_000_000, 1_000_000))
    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "new@x", "organizationType": "claude_max"}}),
        encoding="utf-8",
    )
    snap = cc.claude_login_in(inner, keychain_probe=lambda _s: True)
    assert snap.status == "valid"
    assert snap.subscription_type == "max"
