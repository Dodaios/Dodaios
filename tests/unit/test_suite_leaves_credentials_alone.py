"""The suite leaves the credential store of whoever runs it alone.

Covers the two session-wide rules in ``tests/conftest.py``: no OS credential
store behind ``keyring``, and the macOS ``security`` tool out of reach. Both
hold on every OS, so a test that would only do harm on a Mac fails in CI too.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from dodaios.core.keychain_bundle import VAULT_ACCOUNT, SecurityCliVault
from dodaios.setup import uninstall

NOT_FOUND = 44
# A service nothing ever saved under: were the guard gone, these commands
# would still find nothing to change.
SERVICE = "dodaios-suite-probe"


def test_a_keychain_lookup_finds_nothing() -> None:
    done = subprocess.run(  # noqa: S603
        ["security", "find-generic-password", "-s", SERVICE, "-a", VAULT_ACCOUNT],  # noqa: S607
        capture_output=True,
        check=False,
    )

    assert done.returncode == NOT_FOUND


def test_the_apps_own_keychain_reader_finds_nothing() -> None:
    assert SecurityCliVault().read(SERVICE, VAULT_ACCOUNT) is None


@pytest.mark.parametrize(
    "command",
    [
        ["security", "delete-generic-password", "-s", SERVICE, "-a", VAULT_ACCOUNT],
        ["/usr/bin/security", "add-generic-password", "-U", "-A", "-s", SERVICE, "-a", "k"],
        ["security", "-q", "delete-generic-password", "-s", SERVICE, "-a", "k"],
        ["security", "-i"],
        f"security delete-generic-password -s {SERVICE} -a k",
    ],
)
def test_a_command_that_could_change_the_keychain_fails_the_test(command) -> None:  # noqa: ANN001
    with pytest.raises(pytest.fail.Exception, match="Keychain"):
        subprocess.run(  # noqa: S603
            command, capture_output=True, check=False, shell=isinstance(command, str)
        )


def test_the_uninstaller_does_not_reach_the_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """The path that emptied a developer's Keychain: only the keyring was patched."""
    monkeypatch.setattr(uninstall.sys, "platform", "darwin")
    monkeypatch.setattr(uninstall, "_credential_services", lambda: (SERVICE,))
    monkeypatch.setattr(uninstall.cfg, "delete_secret", lambda key: True)

    with pytest.raises(pytest.fail.Exception, match="delete-generic-password"):
        uninstall._remove_keys(["openai_api_key"])


@pytest.mark.usefixtures("real_keychain_tool")
def test_a_test_of_the_tool_itself_can_ask_for_the_real_one() -> None:
    command = ["security", "delete-generic-password", "-s", SERVICE, "-a", "k"]
    try:
        done = subprocess.run(command, capture_output=True, check=False)  # noqa: S603
    except FileNotFoundError:
        return  # no such tool on this OS: the call reached the OS, which is the point

    assert done.returncode == NOT_FOUND


def test_any_other_command_runs_as_usual() -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "print('security delete-generic-password')"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert done.stdout.strip() == "security delete-generic-password"


def test_a_process_the_suite_starts_has_no_os_credential_store() -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import keyring; print(type(keyring.get_keyring()).__module__)"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert done.stdout.strip() == "keyring.backends.fail"
