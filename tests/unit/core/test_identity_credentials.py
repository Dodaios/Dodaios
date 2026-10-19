"""The one-time copy of stored credentials from the legacy service to the current one.

``dodaios.core.identity_credentials`` copies over each store ``get_secret``
reads: the platform keyring (on macOS one vault write) and the 0600 file
store. It never overwrites a current value, never writes or deletes a legacy
entry, marks the work done, and runs in the background of the main instance
only. Every store here is a fake.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest

from dodaios.core import config as c
from dodaios.core import identity_credentials as ic
from dodaios.core import secret_slots
from dodaios.core.identity_migration import keyring_marker_key
from dodaios.core.keychain_bundle import (
    VAULT_ACCOUNT,
    DarwinBundleKeyringBackend,
    VaultCopyOutcome,
)
from tests.fakes.fake_keychain_vault import (
    FakePerItemKeychain,
    FakeSecurityCli,
    read_payload,
    vault_payload,
)
from tests.fakes.fake_platform_keyring import FakePlatformKeyring

CURRENT = c.KEYRING_SERVICE
LEGACY = c.LEGACY_KEYRING_SERVICES[0]
MARKER = keyring_marker_key(LEGACY)
KNOWN = "telegram_bot_token"
DYNAMIC = "computer_password_0f3c"


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("JARVIS_DATA_DIR", raising=False)
    monkeypatch.setattr(c, "DATA_DIR", tmp_path)
    monkeypatch.setattr(c, "_KEYRING_BACKEND_READY", True)
    monkeypatch.setattr(c, "_FILE_BACKEND_ACTIVE", False)
    monkeypatch.setattr(c, "_PLATFORM_KEYRING_BACKEND", None)
    # The listed runtime names: one computer password, nothing read from disk.
    monkeypatch.setattr(secret_slots, "dynamic_secret_keys", lambda: frozenset({DYNAMIC}))
    original = keyring.get_keyring()
    try:
        yield
    finally:
        keyring.set_keyring(original)


@pytest.fixture
def platform(stores: None) -> FakePlatformKeyring:
    fake = FakePlatformKeyring()
    keyring.set_keyring(fake)
    return fake


def _by_store(results: tuple[ic.StoreMigration, ...]) -> dict[str, ic.StoreMigration]:
    return {result.store: result for result in results}


# ---------------------------------------------------------------- platform store


def test_known_and_listed_runtime_keys_are_copied_once(platform: FakePlatformKeyring) -> None:
    platform.entries[(LEGACY, KNOWN)] = "bot-token"
    platform.entries[(LEGACY, DYNAMIC)] = "ssh-password"
    assert KNOWN in secret_slots.KNOWN_SECRET_KEYS

    first = _by_store(ic.migrate_credentials())["platform"]

    assert first.outcome == "migrated"
    assert set(first.copied) == {KNOWN, DYNAMIC}
    assert platform.entries[(CURRENT, KNOWN)] == "bot-token"
    assert platform.entries[(CURRENT, DYNAMIC)] == "ssh-password"
    assert platform.entries[(CURRENT, MARKER)] == "1"
    # The legacy entries stay: they are the way back for a downgrade.
    assert platform.service(LEGACY) == {KNOWN: "bot-token", DYNAMIC: "ssh-password"}
    assert platform.writes(LEGACY) == []

    platform.calls.clear()
    second = _by_store(ic.migrate_credentials())["platform"]

    assert second.outcome == "already_migrated"
    assert platform.calls == [("get", CURRENT, MARKER)]  # one read, nothing else


def test_a_current_value_is_never_overwritten(platform: FakePlatformKeyring) -> None:
    platform.entries[(LEGACY, KNOWN)] = "old"
    platform.entries[(CURRENT, KNOWN)] = "saved-after-the-rename"

    result = _by_store(ic.migrate_credentials())["platform"]

    assert result.kept == (KNOWN,)
    assert platform.entries[(CURRENT, KNOWN)] == "saved-after-the-rename"


def test_explicit_keys_replace_the_slot_listing(platform: FakePlatformKeyring) -> None:
    platform.entries[(LEGACY, "custom_slot")] = "v"
    platform.entries[(LEGACY, KNOWN)] = "not-listed-this-time"

    result = _by_store(ic.migrate_credentials(keys=["custom_slot"]))["platform"]

    assert result.copied == ("custom_slot",)
    assert (CURRENT, KNOWN) not in platform.entries


def test_a_failed_copy_leaves_no_marker_and_is_finished_next_time(
    platform: FakePlatformKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform.entries[(LEGACY, KNOWN)] = "bot-token"
    platform.entries[(LEGACY, DYNAMIC)] = "ssh-password"
    real_set = platform.set_password

    def flaky(service: str, username: str, password: str) -> None:
        if username == DYNAMIC:
            raise RuntimeError("store busy")
        real_set(service, username, password)

    monkeypatch.setattr(platform, "set_password", flaky)
    first = _by_store(ic.migrate_credentials())["platform"]
    assert first.outcome == "incomplete"
    assert first.failed == (DYNAMIC,)
    assert (CURRENT, MARKER) not in platform.entries

    monkeypatch.setattr(platform, "set_password", real_set)
    second = _by_store(ic.migrate_credentials())["platform"]
    assert second.outcome == "migrated"
    assert second.copied == (DYNAMIC,)
    assert second.kept == (KNOWN,)


def test_a_process_on_the_file_backend_does_not_copy_into_the_platform(
    platform: FakePlatformKeyring,
) -> None:
    platform.entries[(LEGACY, KNOWN)] = "bot-token"
    assert c._install_file_cred_backend("test: platform failed")

    results = _by_store(ic.migrate_credentials())

    assert "platform" not in results
    assert platform.writes(CURRENT) == []
    # Still readable meanwhile, through the legacy fallback.
    assert c.get_secret(KNOWN) == "bot-token"


# ---------------------------------------------------------------- file store


def test_the_file_store_copies_every_legacy_entry_it_holds(
    platform: FakePlatformKeyring,
) -> None:
    store = c._FileCredStore()
    store.set(LEGACY, "routine_webhook_7_123", "hook-token")  # a name nothing lists
    store.set(LEGACY, KNOWN, "bot-token")

    first = _by_store(ic.migrate_credentials())["file"]

    assert first.outcome == "migrated"
    assert set(first.copied) == {"routine_webhook_7_123", KNOWN}
    assert store.get(CURRENT, "routine_webhook_7_123") == "hook-token"
    assert store.get(CURRENT, MARKER) == "1"
    assert store.get(LEGACY, KNOWN) == "bot-token"

    second = _by_store(ic.migrate_credentials())["file"]
    assert second.outcome == "already_migrated"


def test_no_file_store_is_created_when_it_holds_nothing_legacy(
    platform: FakePlatformKeyring, tmp_path: Path
) -> None:
    results = _by_store(ic.migrate_credentials())

    assert "file" not in results
    assert not (tmp_path / "credentials.json").exists()


# ---------------------------------------------------------------- macOS vault


@pytest.fixture
def vault(stores: None) -> tuple[DarwinBundleKeyringBackend, FakeSecurityCli, FakePerItemKeychain]:
    inner = FakePerItemKeychain()
    cli = FakeSecurityCli()
    backend = DarwinBundleKeyringBackend(inner, cli=cli)
    keyring.set_keyring(backend)
    return backend, cli, inner


def test_the_vault_is_copied_in_one_write_with_the_marker(vault) -> None:  # noqa: ANN001
    _backend, cli, inner = vault
    legacy_entries = {KNOWN: "bot-token", "society_credential.a1.TOKEN": "s3cret"}
    cli.items[(LEGACY, VAULT_ACCOUNT)] = vault_payload(legacy_entries)

    results = _by_store(ic.migrate_credentials())

    assert results["keychain-vault"].outcome == VaultCopyOutcome.COPIED.value
    assert set(results["keychain-vault"].copied) == set(legacy_entries)
    assert "platform" not in results  # no per-key pass after a vault copy
    assert cli.writes(CURRENT) == [VAULT_ACCOUNT]  # one write, no prompt per key
    assert read_payload(cli.items[(CURRENT, VAULT_ACCOUNT)]) == {**legacy_entries, MARKER: "1"}
    assert cli.writes(LEGACY) == []
    assert inner.calls == []
    assert c.get_secret("society_credential.a1.TOKEN", "") == "s3cret"

    cli.calls.clear()
    again = _by_store(ic.migrate_credentials())
    assert again["keychain-vault"].outcome == VaultCopyOutcome.ALREADY_COPIED.value
    assert cli.writes(CURRENT) == []


def test_a_vault_copy_keeps_values_saved_under_the_new_name(vault) -> None:  # noqa: ANN001
    _backend, cli, _inner = vault
    cli.items[(LEGACY, VAULT_ACCOUNT)] = vault_payload({KNOWN: "old", "zai_api_key": "z"})
    cli.items[(CURRENT, VAULT_ACCOUNT)] = vault_payload({KNOWN: "new"})

    results = _by_store(ic.migrate_credentials())

    assert results["keychain-vault"].copied == ("zai_api_key",)
    assert read_payload(cli.items[(CURRENT, VAULT_ACCOUNT)]) == {
        KNOWN: "new",
        "zai_api_key": "z",
        MARKER: "1",
    }


def test_per_item_legacy_entries_are_copied_when_there_is_no_legacy_vault(
    vault,  # noqa: ANN001
) -> None:
    _backend, cli, inner = vault
    inner.values[(LEGACY, KNOWN)] = "from-before-the-vault"

    results = _by_store(ic.migrate_credentials())

    assert results["keychain-vault"].outcome == VaultCopyOutcome.NO_LEGACY_VAULT.value
    assert results["platform"].copied == (KNOWN,)
    assert read_payload(cli.items[(CURRENT, VAULT_ACCOUNT)])[KNOWN] == "from-before-the-vault"
    # The legacy item is read, never folded into a legacy vault or deleted.
    assert inner.writes(LEGACY) == []
    assert cli.writes(LEGACY) == []


def test_a_malformed_legacy_vault_is_left_alone(vault) -> None:  # noqa: ANN001
    _backend, cli, _inner = vault
    cli.items[(LEGACY, VAULT_ACCOUNT)] = "not a vault"

    results = _by_store(ic.migrate_credentials())

    assert results["keychain-vault"].outcome == VaultCopyOutcome.MALFORMED.value
    assert cli.items[(LEGACY, VAULT_ACCOUNT)] == "not a vault"
    assert cli.writes(LEGACY) == []


# ---------------------------------------------------------------- the read-only view


def test_the_copy_can_never_write_or_delete_the_legacy_service() -> None:
    fake = FakePlatformKeyring()
    view = ic._LegacyReadOnly(fake, LEGACY)

    with pytest.raises(PermissionError):
        view.set_password(LEGACY, KNOWN, "x")
    with pytest.raises(PermissionError):
        view.delete_password(CURRENT, KNOWN)
    view.set_password(CURRENT, KNOWN, "x")
    assert fake.service(CURRENT) == {KNOWN: "x"}


# ---------------------------------------------------------------- scheduling


@pytest.fixture
def recorded_runs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    runs: list[str] = []
    monkeypatch.setattr(ic, "_scheduled", False)
    monkeypatch.setattr(ic, "migrate_credentials", lambda: runs.append("ran") or ())
    return runs


def test_only_the_main_instance_schedules_the_copy(recorded_runs: list[str]) -> None:
    assert ic.schedule_credential_migration(delay_s=0, environ={}) is None
    assert ic.schedule_credential_migration(
        delay_s=0, environ={"JARVIS_PRIMARY_INSTANCE": "0"}
    ) is None
    assert recorded_runs == []


def test_the_copy_runs_once_in_a_background_daemon_thread(recorded_runs: list[str]) -> None:
    primary = {"JARVIS_PRIMARY_INSTANCE": "1"}

    thread = ic.schedule_credential_migration(delay_s=0, environ=primary)

    assert isinstance(thread, threading.Thread)
    assert thread.daemon and thread is not threading.current_thread()
    thread.join(timeout=10)
    assert recorded_runs == ["ran"]
    assert ic.schedule_credential_migration(delay_s=0, environ=primary) is None


def test_a_failing_copy_never_escapes_the_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> tuple[()]:
        raise RuntimeError("store exploded")

    monkeypatch.setattr(ic, "_scheduled", False)
    monkeypatch.setattr(ic, "migrate_credentials", boom)
    seen: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(args.exc_value))

    thread = ic.schedule_credential_migration(delay_s=0, environ={"JARVIS_PRIMARY_INSTANCE": "1"})
    assert thread is not None
    thread.join(timeout=10)

    assert seen == []
