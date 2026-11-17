"""Locate the freshest live Claude CLI OAuth login across config dirs.

The ``claude`` CLI stores its subscription OAuth bearer in
``<config dir>/.credentials.json`` and refreshes it in place — but only in
the config dir its sessions actually run with. The default is ``~/.claude``;
``CLAUDE_CONFIG_DIR`` (the CLI's official override) and multi-profile
managers pin sessions elsewhere, so the default file silently expires in
place while the real, freshly-refreshed login lives in another directory.

Reading ONLY ``~/.claude`` then reports "subscription login expired", the
Jarvis-Agents health banner declares the worker unavailable, and every heavy
mission diverts to another family — although a perfectly live login sits on
disk (2026-07-10 incident on a profile-manager-driven host; the same class as
the 2026-07-06 expired-in-place incident, one directory further left).

One shared rule fixes every reader: enumerate the known candidate config
dirs and let the FRESHEST live login win. Consumers:

* ``dodaios.missions.isolation.env`` — the token injected into isolated
  mission workers and the worker-viability gate;
* ``dodaios.claude_auth.ClaudeAuthService`` — the subscription card in the
  API-Keys view.

Pure stdlib + pathlib, cross-platform, never raises (CLOUD.md Rule #1): a
missing directory, file, or profile manager is simply not a candidate.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# Minimum remaining lifetime for a login to count as live. An isolated
# mission worker holds no refresh token, so a bearer dying seconds after the
# spawn would 401 mid-mission; the status card shares the same rule so the UI
# and the worker never disagree about "connected".
OAUTH_EXPIRY_SLACK_S: float = 120.0

# Multi-profile managers keep one Claude config dir per profile and launch
# every session with CLAUDE_CONFIG_DIR pointing at it — on such a host
# nothing ever refreshes ~/.claude again, so these profiles are where the
# live login actually is. Globbed relative to the home dir, best-effort;
# empty wherever the manager is not installed.
_PROFILE_MANAGER_GLOBS: tuple[str, ...] = (".bridgespace/ai-profiles/claude/*",)


def claude_config_dirs() -> list[Path]:
    """Candidate Claude CLI config dirs, most authoritative first (test seam).

    Order: ``$CLAUDE_CONFIG_DIR`` (the CLI's official override, when set) →
    the ``~/.claude`` default → per-profile dirs of known profile managers.
    Existence is NOT required; readers treat unreadable files as absent.
    """
    dirs: list[Path] = []
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if env_dir:
        dirs.append(Path(env_dir).expanduser())
    home = Path.home()
    dirs.append(home / ".claude")
    for pattern in _PROFILE_MANAGER_GLOBS:
        try:
            dirs.extend(sorted(p for p in home.glob(pattern) if p.is_dir()))
        except OSError:
            continue
    # Path.__eq__ is already case-insensitive on Windows; dedupe keeps the
    # first (most authoritative) occurrence.
    unique: list[Path] = []
    for d in dirs:
        if d not in unique:
            unique.append(d)
    return unique


@dataclass(frozen=True)
class ClaudeOAuthSnapshot:
    """The winning Claude OAuth login across all candidate config dirs.

    ``access_token`` is only set while ``status == "valid"`` — an expired
    bearer is never handed out (injecting it is a guaranteed 401).
    ``config_dir`` names the directory whose credentials file won, so
    callers can read sibling files (e.g. the ``.claude.json`` identity)
    from the SAME login, not a different profile's.
    """

    status: Literal["valid", "expired", "absent"]
    access_token: str | None = None
    subscription_type: str | None = None
    config_dir: Path | None = None
    expires_s: float | None = None  # epoch seconds; None == no expiry recorded
    #: A refresh token sits beside the bearer, so an ``"expired"`` login renews
    #: itself the next time the CLI runs — "expired" then means "stale between
    #: sessions", not "signed out". Status readers may report such a login as
    #: signed in; token INJECTORS must not, because the stale bearer itself is
    #: still a guaranteed 401 (only the CLI can redeem the refresh token).
    refresh_token_present: bool = False


def _parse_oauth_file(
    path: Path,
) -> tuple[str, str | None, float | None, bool] | None:
    """Tolerant parse of one ``.credentials.json``.

    Returns ``(access_token, subscription_type, expires_s, refresh_present)``
    for a present ``sk-ant-oat`` bearer, else ``None``. Only OAuth bearers
    count — a classic API key in the bearer slot is not a subscription login.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _parse_oauth_data(data)


def _parse_oauth_data(data: Any) -> tuple[str, str | None, float | None, bool] | None:
    """:func:`_parse_oauth_file` on already-loaded JSON (file or Keychain item)."""
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    if not (isinstance(token, str) and token.startswith("sk-ant-oat")):
        return None
    sub_type = oauth.get("subscriptionType")
    sub_type = sub_type if isinstance(sub_type, str) and sub_type else None
    expires_at = oauth.get("expiresAt")
    expires_s: float | None = None
    if isinstance(expires_at, (int, float)) and expires_at > 0:
        # `claude` writes epoch milliseconds; tolerate seconds defensively.
        expires_s = expires_at / 1000.0 if expires_at > 1e12 else float(expires_at)
    refresh = oauth.get("refreshToken")
    refresh_present = isinstance(refresh, str) and bool(refresh.strip())
    return token, sub_type, expires_s, refresh_present


_KEYCHAIN_SERVICE = "Claude Code-credentials"


def _keychain_service_from(raw_dir: str) -> str:
    import hashlib
    import unicodedata

    normalized = unicodedata.normalize("NFC", raw_dir)
    return f"{_KEYCHAIN_SERVICE}-{hashlib.sha256(normalized.encode()).hexdigest()[:8]}"


def keychain_service_for(config_dir: Path) -> str:
    """The macOS Keychain item Claude Code keeps THIS config dir's login in.

    Claude Code's rule, mirrored: the bare service name only while no
    ``CLAUDE_CONFIG_DIR`` is set; as soon as one is, the name gets the first 8
    hex digits of the SHA-256 of that value (NFC-normalized) as a suffix, even
    when it points at ``~/.claude`` (verified 2026-11-16 against Claude Code's
    own items). ``CLAUDE_SECURESTORAGE_CONFIG_DIR``, when set, overrides both.

    Added seats are spawned with ``CLAUDE_CONFIG_DIR=str(config_dir)``; the
    built-in seat inherits this process's own variable, so its raw value is
    hashed as given (a trailing slash changes the name).
    """
    storage = os.environ.get("CLAUDE_SECURESTORAGE_CONFIG_DIR")
    if storage is not None:
        return _keychain_service_from(storage) if storage else _KEYCHAIN_SERVICE
    directory = Path(config_dir).expanduser()
    inherited = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if not inherited.strip():
        if directory == Path.home() / ".claude":
            return _KEYCHAIN_SERVICE
        return _keychain_service_from(str(config_dir))
    if Path(inherited.strip()).expanduser() == directory:
        return _keychain_service_from(inherited)
    return _keychain_service_from(str(config_dir))


def _keychain_item_exists(service: str) -> bool:
    """Whether the login Keychain holds ``service``; reads metadata, never the secret."""
    import subprocess
    import sys

    if sys.platform != "darwin":
        return False
    try:
        done = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # probe: no tool or no answer means no login item
        return False
    return done.returncode == 0


def _keychain_secret(service: str) -> str | None:
    """The Keychain item's secret, read by the same ``security`` tool Claude Code uses."""
    import subprocess
    import sys

    if sys.platform != "darwin":
        return None
    try:
        done = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # probe: unreadable item, usage unmeasured
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def keychain_bearer(
    config_dir: Path,
    *,
    reader: Callable[[str], str | None] | None = None,
    now_fn: Callable[[], float] = time.time,
) -> str | None:
    """The live OAuth bearer Claude Code keeps in the Keychain for ``config_dir``.

    Only for reading plan usage from Anthropic (2026-11-17: without it no seat
    was ever measured, so automatic switching never moved a spent seat). Never
    logged; an expired bearer is ``None`` because only the CLI can refresh it.
    """
    raw = (reader or _keychain_secret)(keychain_service_for(config_dir))
    if not raw:
        return None
    try:
        parsed = _parse_oauth_data(json.loads(raw))
    except ValueError:  # an item that is not JSON holds no bearer we could use
        return None
    if parsed is None:
        return None
    token, _sub_type, expires_s, _refresh = parsed
    if expires_s is not None and expires_s <= now_fn() + OAUTH_EXPIRY_SLACK_S:
        return None
    return token


_ORG_TYPE_TO_TIER = {
    "claude_max": "max",
    "claude_pro": "pro",
    "claude_team": "team",
    "claude_enterprise": "enterprise",
}


def _tier_from_identity(config_dir: Path) -> str | None:
    from dodaios.claude_auth import claude_account_file

    try:
        data = json.loads(claude_account_file(Path(config_dir)).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # no identity file: tier unknown, login counts
        return None
    account = data.get("oauthAccount") if isinstance(data, dict) else None
    org_type = account.get("organizationType") if isinstance(account, dict) else None
    return _ORG_TYPE_TO_TIER.get(str(org_type or ""))


def claude_login_in(
    config_dir: Path,
    *,
    now_fn: Callable[[], float] = time.time,
    keychain_probe: Callable[[str], bool] | None = None,
) -> ClaudeOAuthSnapshot:
    """The login stored in ONE specific config dir, without cross-dir search.

    The multi-account switcher (:mod:`dodaios.agent_accounts`) asks a different
    question than :func:`freshest_claude_oauth`: not "where is the live login on
    this machine" but "is THIS account signed in". Answering that with the
    cross-dir scan would report a neighbouring account's healthy login as if it
    belonged to the directory being asked about, and the UI would show a green
    card for an account that cannot run anything.

    Never raises; an unreadable or absent file is ``"absent"``.
    """
    parsed = _parse_oauth_file(config_dir / ".credentials.json")
    if parsed is None:
        # macOS: Claude Code stores the login in the Keychain and writes no file,
        # so every account read as signed out and the seat switcher never moved
        # a spent seat (2026-11-16). The item's presence is the login; its
        # secret is never read (no prompt), and the CLI refreshes it itself.
        probe = keychain_probe or _keychain_item_exists
        if probe(keychain_service_for(config_dir)):
            return ClaudeOAuthSnapshot(
                status="valid",
                subscription_type=_tier_from_identity(config_dir),
                config_dir=config_dir,
            )
        return ClaudeOAuthSnapshot(status="absent", config_dir=config_dir)
    token, sub_type, expires_s, refresh_present = parsed
    if expires_s is not None and expires_s <= now_fn() + OAUTH_EXPIRY_SLACK_S:
        return ClaudeOAuthSnapshot(
            status="expired",
            subscription_type=sub_type,
            config_dir=config_dir,
            expires_s=expires_s,
            refresh_token_present=refresh_present,
        )
    return ClaudeOAuthSnapshot(
        status="valid",
        access_token=token,
        subscription_type=sub_type,
        config_dir=config_dir,
        expires_s=expires_s,
        refresh_token_present=refresh_present,
    )


def freshest_claude_oauth(*, now_fn: Callable[[], float] = time.time) -> ClaudeOAuthSnapshot:
    """Scan every candidate config dir; the freshest LIVE login wins.

    - ``"valid"``: at least one non-expired bearer exists; the one with the
      farthest ``expiresAt`` is returned (no ``expiresAt`` at all stays
      fail-open for older credential shapes and sorts as farthest).
    - ``"expired"``: bearers exist but every one has died in place; the
      least-stale one is the reference (its tier feeds the UI message).
    - ``"absent"``: no readable ``sk-ant-oat`` bearer anywhere.

    Cheap and offline — a handful of small file reads, never a subprocess or
    network probe, so health checks may call it freely.
    """
    horizon = now_fn() + OAUTH_EXPIRY_SLACK_S
    best_valid: tuple[float, ClaudeOAuthSnapshot] | None = None
    best_expired: tuple[float, ClaudeOAuthSnapshot] | None = None
    for config_dir in claude_config_dirs():
        parsed = _parse_oauth_file(config_dir / ".credentials.json")
        if parsed is None:
            continue
        token, sub_type, expires_s, refresh_present = parsed
        if expires_s is None or expires_s > horizon:
            sort_key = float("inf") if expires_s is None else expires_s
            if best_valid is None or sort_key > best_valid[0]:
                best_valid = (
                    sort_key,
                    ClaudeOAuthSnapshot(
                        status="valid",
                        access_token=token,
                        subscription_type=sub_type,
                        config_dir=config_dir,
                        expires_s=expires_s,
                        refresh_token_present=refresh_present,
                    ),
                )
        elif best_expired is None or expires_s > best_expired[0]:
            best_expired = (
                expires_s,
                ClaudeOAuthSnapshot(
                    status="expired",
                    subscription_type=sub_type,
                    config_dir=config_dir,
                    expires_s=expires_s,
                    refresh_token_present=refresh_present,
                ),
            )
    if best_valid is not None:
        return best_valid[1]
    if best_expired is not None:
        return best_expired[1]
    return ClaudeOAuthSnapshot(status="absent")


__all__ = [
    "OAUTH_EXPIRY_SLACK_S",
    "ClaudeOAuthSnapshot",
    "claude_config_dirs",
    "claude_login_in",
    "freshest_claude_oauth",
    "keychain_bearer",
]
