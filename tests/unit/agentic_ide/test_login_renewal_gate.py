"""Panes that share an expired login let one of them renew it first.

The defect these pin down (2026-10-14): after a reboot, a restored workspace
started a dozen Claude Code panes within seconds, all on one config directory
whose access token had expired overnight. Each of them raced for the CLI's
refresh lock, and every one that did not win it within a few seconds printed
"Could not refresh your login ... sign in again with /login" — so the user saw
every coding pane logged out, although the login itself was fine.

What must hold:

* on an expired-but-renewable login, ONE pane starts and the rest wait until
  the credentials file holds a live token again,
* a renewal that never comes holds the others only up to the ceiling, and is
  not waited for a second time,
* a live login never makes anybody wait.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from dodaios import agent_accounts
from dodaios.agentic_ide import session as ide
from tests.fakes.fake_pty_manager import FakePtyManager

#: A credentials file in the CLI's shape, holding placeholders rather than real
#: tokens. Kept as finished text so nothing here reads as a secret being stored.
_LOGIN_FILE = (
    '{{"claudeAiOauth": {{"accessToken": "sk-ant-oat01-test", '
    '"expiresAt": {expires_ms}, "subscriptionType": "max"{renewal}}}}}'
)
_RENEWAL_FIELD = ', "refreshToken": "sk-ant-ort01-test"'


def _write_login(directory: Path, *, expires_in_s: float, refresh: bool = True) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    text = _LOGIN_FILE.format(
        expires_ms=int((time.time() + expires_in_s) * 1000),
        renewal=_RENEWAL_FIELD if refresh else "",
    )
    (directory / ".credentials.json").write_text(text, encoding="utf-8")


def _claude_home() -> Path:
    # The autouse fixture points CLAUDE_CONFIG_DIR at a temporary directory, so
    # the built-in account's login lives there.
    return Path(os.environ["CLAUDE_CONFIG_DIR"])


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> FakePtyManager:
    monkeypatch.setattr(ide, "agent_argv", lambda name: (f"/usr/bin/{name}",))
    monkeypatch.setattr(ide, "COLD_START_LIMIT", 16)
    monkeypatch.setattr(ide, "COLD_START_SETTLE_S", 0.0)
    monkeypatch.setattr(ide, "COLD_START_HOLD_MAX_S", 0.0)
    monkeypatch.setattr(ide, "LOGIN_RENEWAL_POLL_S", 0.01)
    return FakePtyManager()


async def _attach_all(registry: ide.Registry, session) -> None:  # noqa: ANN001
    async def sink(_text: str) -> None:
        return None

    async def gone(_code: int) -> None:
        return None

    await asyncio.gather(
        *(
            registry.attach(term.key, 80, 24, sink, gone, workspace_id=session.id)
            for term in session.terminals
        )
    )


async def _wait_for_spawns(pool: FakePtyManager, count: int) -> None:
    for _ in range(200):
        if len(pool.spawns) >= count:
            return
        await asyncio.sleep(0.01)


async def test_one_pane_renews_an_expired_login_before_the_others_start(
    pool: FakePtyManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ide, "LOGIN_RENEWAL_WAIT_S", 10.0)
    _write_login(_claude_home(), expires_in_s=-3600)
    registry = ide.Registry(pty_manager=pool)
    session = await registry.start(str(tmp_path), [{"agent": "claude"} for _ in range(4)])

    mounting = asyncio.create_task(_attach_all(registry, session))
    await _wait_for_spawns(pool, 1)
    await asyncio.sleep(0.1)
    assert len(pool.spawns) == 1, "the other panes raced the renewal"

    # A file caught mid-rewrite reads as no login at all; that is not a renewal.
    (_claude_home() / ".credentials.json").write_text("{", encoding="utf-8")
    await asyncio.sleep(0.1)
    assert len(pool.spawns) == 1, "a half-written credentials file released the queue"

    # The first CLI renews the token in place, as Claude Code does.
    _write_login(_claude_home(), expires_in_s=8 * 3600)
    await asyncio.wait_for(mounting, timeout=5.0)
    assert len(pool.spawns) == 4, "every pane starts once the login is live again"


async def test_a_renewal_that_never_comes_holds_the_others_only_to_the_ceiling(
    pool: FakePtyManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ide, "LOGIN_RENEWAL_WAIT_S", 0.2)
    _write_login(_claude_home(), expires_in_s=-3600)
    registry = ide.Registry(pty_manager=pool)
    session = await registry.start(str(tmp_path), [{"agent": "claude"} for _ in range(3)])

    await asyncio.wait_for(_attach_all(registry, session), timeout=5.0)
    assert len(pool.spawns) == 3

    # The same stale login was already waited for once: a second workspace on
    # it starts at once instead of paying the ceiling again.
    monkeypatch.setattr(ide, "LOGIN_RENEWAL_WAIT_S", 30.0)
    other = tmp_path / "other"
    other.mkdir()
    second = await registry.start(str(other), [{"agent": "claude"} for _ in range(2)])
    await asyncio.wait_for(_attach_all(registry, second), timeout=5.0)
    assert len(pool.spawns) == 5


async def test_a_live_login_makes_nobody_wait(
    pool: FakePtyManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ide, "LOGIN_RENEWAL_WAIT_S", 30.0)
    _write_login(_claude_home(), expires_in_s=8 * 3600)
    registry = ide.Registry(pty_manager=pool)
    session = await registry.start(str(tmp_path), [{"agent": "claude"} for _ in range(4)])

    await asyncio.wait_for(_attach_all(registry, session), timeout=5.0)
    assert len(pool.spawns) == 4


def test_stale_login_marker_names_only_a_renewable_expired_claude_login() -> None:
    home = _claude_home()

    _write_login(home, expires_in_s=-60)
    marker = agent_accounts.stale_login_marker("claude", None)
    assert marker is not None and marker < time.time()

    _write_login(home, expires_in_s=3600)
    assert agent_accounts.stale_login_marker("claude", None) is None

    # Without a refresh token the CLI cannot renew anything; waiting is useless.
    _write_login(home, expires_in_s=-60, refresh=False)
    assert agent_accounts.stale_login_marker("claude", None) is None

    assert agent_accounts.stale_login_marker("codex", None) is None
