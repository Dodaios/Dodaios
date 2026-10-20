"""The credential service was renamed; no credential may be lost or come back.

``get_secret`` reads the legacy service when the current one has nothing for a
slot (many slot names exist only at runtime, so no copy can be complete),
``delete_secret`` clears every service, and ``set_secret`` refreshes a legacy
entry only where one already exists. A read never writes. Every store here is
a fake: the process-wide ``keyring`` points at ``FakePlatformKeyring`` and the
0600 file store lives under ``tmp_path``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest

from dodaios.core import branding
from dodaios.core import config as c
from tests.fakes.fake_keychain_vault import (
    FakePerItemKeychain,
    FakeSecurityCli,
    vault_payload,
)
from tests.fakes.fake_platform_keyring import FakePlatformKeyring

CURRENT = c.KEYRING_SERVICE
LEGACY = c.LEGACY_KEYRING_SERVICES[0]
SLOT = "groq_api_key"
ENV = "GROQ_API_KEY"


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakePlatformKeyring]:
    # Never the darwin branch: it would wrap the fake in the real security CLI.
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("JARVIS_DATA_DIR", raising=False)
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setattr(c, "DATA_DIR", tmp_path)
    monkeypatch.setattr(c, "PROJECT_ROOT", tmp_path)  # no .env file
    monkeypatch.setattr(c, "_KEYRING_BACKEND_READY", True)
    monkeypatch.setattr(c, "_FILE_BACKEND_ACTIVE", False)
    monkeypatch.setattr(c, "_PLATFORM_KEYRING_BACKEND", None)
    original = keyring.get_keyring()
    fake = FakePlatformKeyring()
    keyring.set_keyring(fake)
    try:
        yield fake
    finally:
        keyring.set_keyring(original)


def test_the_service_names_come_from_branding() -> None:
    assert CURRENT == branding.KEYRING_SERVICE_NAME == "dodaios"
    assert c.LEGACY_KEYRING_SERVICES == branding.LEGACY_KEYRING_SERVICE_NAMES
    assert LEGACY == "personal-jarvis"


# ---------------------------------------------------------------- reads


def test_a_key_saved_before_the_rename_is_read(platform: FakePlatformKeyring) -> None:
    platform.entries[(LEGACY, SLOT)] = "legacy-value"

    assert c.get_secret(SLOT) == "legacy-value"


def test_the_current_service_wins_over_the_legacy_one(platform: FakePlatformKeyring) -> None:
    platform.entries[(LEGACY, SLOT)] = "old"
    platform.entries[(CURRENT, SLOT)] = "new"

    assert c.get_secret(SLOT) == "new"


def test_a_legacy_keyring_value_still_beats_env(
    platform: FakePlatformKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Before the rename the OS keyring value beat ENV; the rename keeps that.
    platform.entries[(LEGACY, SLOT)] = "from-keyring"
    monkeypatch.setenv(ENV, "from-env")

    assert c.get_secret(SLOT) == "from-keyring"


def test_env_still_beats_a_legacy_file_value(
    platform: FakePlatformKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    c._FileCredStore().set(LEGACY, SLOT, "from-file")
    monkeypatch.setenv(ENV, "from-env")
    assert c.get_secret(SLOT) == "from-env"

    monkeypatch.delenv(ENV)
    assert c.get_secret(SLOT) == "from-file"


def test_env_is_read_when_no_service_has_the_slot(
    platform: FakePlatformKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV, "from-env")
    assert c.get_secret(SLOT) == "from-env"
    monkeypatch.delenv(ENV)
    assert c.get_secret(SLOT) is None


def test_a_read_never_writes_any_service(platform: FakePlatformKeyring, tmp_path: Path) -> None:
    platform.entries[(LEGACY, SLOT)] = "legacy-value"

    for _ in range(3):
        assert c.get_secret(SLOT) == "legacy-value"
        assert c.get_secret("never_saved_slot") is None

    assert platform.writes(LEGACY) == []
    assert platform.writes(CURRENT) == []
    assert not (tmp_path / "credentials.json").exists()


def test_a_legacy_read_on_the_file_backend_also_reads_the_retained_platform_copy(
    platform: FakePlatformKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    # After a platform failure the process runs on the file store, and the
    # platform store is retained beside it: a legacy entry there still counts.
    platform.entries[(LEGACY, SLOT)] = "legacy-platform"
    assert c._install_file_cred_backend("test: platform write failed")
    assert c._PLATFORM_KEYRING_BACKEND is platform

    assert c.get_secret(SLOT) == "legacy-platform"
    assert platform.writes(LEGACY) == []


def test_a_legacy_read_never_folds_a_per_item_entry_into_the_macos_vault(
    platform: FakePlatformKeyring,
) -> None:
    from dodaios.core.keychain_bundle import VAULT_ACCOUNT, DarwinBundleKeyringBackend

    inner = FakePerItemKeychain()
    cli = FakeSecurityCli()
    inner.values[(LEGACY, SLOT)] = "per-item-legacy"  # from before the vault existed
    cli.items[(LEGACY, VAULT_ACCOUNT)] = vault_payload({"other_api_key": "x"})
    keyring.set_keyring(DarwinBundleKeyringBackend(inner, cli=cli))

    assert c.get_secret(SLOT) == "per-item-legacy"
    assert c.get_secret("other_api_key") == "x"

    # A normal wrapper read would have moved the item into the legacy vault
    # and deleted it; the legacy service stays exactly as it was.
    assert cli.writes(LEGACY) == []
    assert inner.writes(LEGACY) == []
    assert inner.values[(LEGACY, SLOT)] == "per-item-legacy"


def test_a_malformed_legacy_vault_does_not_hide_the_current_one(
    platform: FakePlatformKeyring,
) -> None:
    from dodaios.core.keychain_bundle import VAULT_ACCOUNT, DarwinBundleKeyringBackend

    inner = FakePerItemKeychain()
    cli = FakeSecurityCli()
    cli.items[(LEGACY, VAULT_ACCOUNT)] = "not a vault"
    cli.items[(CURRENT, VAULT_ACCOUNT)] = vault_payload({"openai_api_key": "current"})
    keyring.set_keyring(DarwinBundleKeyringBackend(inner, cli=cli))

    assert c.get_secret(SLOT) is None  # legacy vault unreadable: absent
    assert c.get_secret("openai_api_key") == "current"
    assert cli.items[(LEGACY, VAULT_ACCOUNT)] == "not a vault"


# ---------------------------------------------------------------- deletes


def test_delete_clears_every_service_and_nothing_comes_back(
    platform: FakePlatformKeyring,
) -> None:
    platform.entries[(LEGACY, SLOT)] = "legacy"
    platform.entries[(CURRENT, SLOT)] = "current"
    store = c._FileCredStore()
    store.set(LEGACY, SLOT, "legacy-file")
    store.set(CURRENT, SLOT, "current-file")
    before = c.secret_generation()

    assert c.delete_secret(SLOT) is True

    assert c.get_secret(SLOT) is None
    assert (LEGACY, SLOT) not in platform.entries
    assert (CURRENT, SLOT) not in platform.entries
    assert store.get(LEGACY, SLOT) is None
    assert store.get(CURRENT, SLOT) is None
    assert c.secret_generation() == before + 1  # one change, announced once


def test_delete_of_a_key_that_only_exists_under_the_legacy_name(
    platform: FakePlatformKeyring,
) -> None:
    platform.entries[(LEGACY, SLOT)] = "legacy"

    assert c.delete_secret(SLOT) is True
    assert c.get_secret(SLOT) is None


def test_delete_of_an_absent_key_is_still_a_success(platform: FakePlatformKeyring) -> None:
    assert c.delete_secret("never_saved_slot") is True


def test_delete_reports_a_legacy_entry_it_could_not_remove(
    platform: FakePlatformKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform.entries[(LEGACY, SLOT)] = "stuck"
    real_delete = platform.delete_password

    def refuse_legacy(service: str, username: str) -> None:
        if service == LEGACY:
            return  # claims success, keeps the entry
        real_delete(service, username)

    monkeypatch.setattr(platform, "delete_password", refuse_legacy)

    assert c.delete_secret(SLOT) is False


# ---------------------------------------------------------------- writes


def test_a_save_goes_to_the_current_service(platform: FakePlatformKeyring) -> None:
    assert c.set_secret(SLOT, "fresh") is True

    assert platform.entries[(CURRENT, SLOT)] == "fresh"
    assert (LEGACY, SLOT) not in platform.entries  # never created there
    assert c.get_secret(SLOT) == "fresh"


def test_a_save_refreshes_an_existing_legacy_entry(platform: FakePlatformKeyring) -> None:
    # An install that goes back to a version reading only the legacy service
    # must see the value saved last.
    platform.entries[(LEGACY, SLOT)] = "stale"
    store = c._FileCredStore()
    store.set(LEGACY, SLOT, "stale-file")

    assert c.set_secret(SLOT, "fresh") is True

    assert platform.entries[(CURRENT, SLOT)] == "fresh"
    assert platform.entries[(LEGACY, SLOT)] == "fresh"
    assert store.get(LEGACY, SLOT) == "fresh"


def test_a_save_creates_no_legacy_file_entry(platform: FakePlatformKeyring) -> None:
    platform.entries[(LEGACY, SLOT)] = "stale"

    assert c.set_secret(SLOT, "fresh") is True

    assert c._FileCredStore().get(LEGACY, SLOT) is None


def test_a_failed_legacy_refresh_never_fails_the_save(
    platform: FakePlatformKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform.entries[(LEGACY, SLOT)] = "stale"
    real_set = platform.set_password

    def refuse_legacy(service: str, username: str, password: str) -> None:
        if service == LEGACY:
            raise RuntimeError("legacy write refused")
        real_set(service, username, password)

    monkeypatch.setattr(platform, "set_password", refuse_legacy)

    assert c.set_secret(SLOT, "fresh") is True
    assert c.get_secret(SLOT) == "fresh"
