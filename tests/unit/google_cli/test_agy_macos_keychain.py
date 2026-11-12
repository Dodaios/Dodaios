"""agy 1.4+ keeps its login in the macOS Keychain; the status must see it.

agy 1.5.7 on macOS writes no ``antigravity-oauth-token`` file. Its cli.log says
"ChainedAuth: authenticated via keyring" and the login is a generic Keychain item
with service ``gemini`` and account ``antigravity``. The app only checked the
Windows Credential Manager, so a signed-in Mac read as "not logged in" and the
provider could not be added.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

import dodaios.google_cli.auth_service as auth_mod

# The autouse fixture in test_auth_service.py does not apply here, so these are
# the real functions; every test fakes ``subprocess.run`` and never touches the
# real Keychain.
present = auth_mod._agy_keyring_login_present
delete = auth_mod._delete_agy_keyring_login


class _Run:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, b"", b"")


@pytest.fixture
def mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_mod.sys, "platform", "darwin")


def test_keychain_login_is_seen_on_macos(mac: None, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _Run(0)
    monkeypatch.setattr(auth_mod.subprocess, "run", run)

    assert present() is True
    (argv,) = run.calls
    assert argv[:2] == ["/usr/bin/security", "find-generic-password"]
    assert ["-s", "gemini"] == argv[2:4] and ["-a", "antigravity"] == argv[4:6]


def test_the_presence_check_never_asks_for_the_secret(
    mac: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Run(0)
    monkeypatch.setattr(auth_mod.subprocess, "run", run)

    present()

    (argv,) = run.calls
    assert "-w" not in argv and "-g" not in argv


def test_no_keychain_item_means_not_logged_in(mac: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_mod.subprocess, "run", _Run(44))
    assert present() is False


def test_a_failing_security_tool_means_not_detected(
    mac: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise OSError("security not available")

    monkeypatch.setattr(auth_mod.subprocess, "run", broken)
    assert present() is False


def test_disconnect_removes_the_keychain_login(mac: None, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _Run(0)
    monkeypatch.setattr(auth_mod.subprocess, "run", run)

    delete()

    (argv,) = run.calls
    assert argv[:2] == ["/usr/bin/security", "delete-generic-password"]
    assert ["-s", "gemini", "-a", "antigravity"] == argv[2:6]


def test_disconnect_without_a_keychain_login_is_fine(
    mac: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_mod.subprocess, "run", _Run(44))
    delete()  # item not found: nothing to remove


def test_disconnect_reports_a_real_failure(mac: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_mod.subprocess, "run", _Run(51))
    with pytest.raises(OSError):
        delete()


def test_other_platforms_do_not_run_security(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _Run(0)
    monkeypatch.setattr(auth_mod.sys, "platform", "linux")
    monkeypatch.setattr(auth_mod.subprocess, "run", run, raising=False)

    assert present() is False
    delete()
    assert run.calls == []
