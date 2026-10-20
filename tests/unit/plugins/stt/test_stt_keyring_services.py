"""The cloud STT plugins read their key under the current and the legacy service.

The plugins cannot import ``dodaios.*``, so they read the credential store
through ``keyring`` themselves. After the service rename a key saved by an
earlier version is still theirs; the current service wins, and reading the
legacy one never writes there. The keyring is a fake.
"""

from __future__ import annotations

from collections.abc import Iterator

import keyring
import pytest

from dodaios.core import branding
from dodaios.core.keychain_bundle import VAULT_ACCOUNT, DarwinBundleKeyringBackend
from dodaios.plugins.stt import deepgram_api, groq_api
from tests.fakes.fake_keychain_vault import FakePerItemKeychain, FakeSecurityCli, vault_payload
from tests.fakes.fake_platform_keyring import FakePlatformKeyring

CURRENT = branding.KEYRING_SERVICE_NAME
LEGACY = branding.LEGACY_KEYRING_SERVICE_NAMES[0]
PLUGINS = [
    pytest.param(groq_api, "groq_api_key", "GROQ_API_KEY", id="groq"),
    pytest.param(deepgram_api, "deepgram_api_key", "DEEPGRAM_API_KEY", id="deepgram"),
]


@pytest.fixture
def platform() -> Iterator[FakePlatformKeyring]:
    original = keyring.get_keyring()
    fake = FakePlatformKeyring()
    keyring.set_keyring(fake)
    try:
        yield fake
    finally:
        keyring.set_keyring(original)


@pytest.mark.parametrize(("module", "slot", "env"), PLUGINS)
def test_a_key_saved_before_the_rename_is_found(
    platform: FakePlatformKeyring, monkeypatch: pytest.MonkeyPatch, module, slot, env  # noqa: ANN001
) -> None:
    monkeypatch.delenv(env, raising=False)
    platform.entries[(LEGACY, slot)] = "legacy-key"

    assert module._read_keyring_secret(slot) == "legacy-key"
    assert platform.writes(LEGACY) == []


@pytest.mark.parametrize(("module", "slot", "env"), PLUGINS)
def test_the_current_service_wins(
    platform: FakePlatformKeyring, module, slot, env  # noqa: ANN001
) -> None:
    platform.entries[(LEGACY, slot)] = "legacy-key"
    platform.entries[(CURRENT, slot)] = "current-key"

    assert module._read_keyring_secret(slot) == "current-key"


@pytest.mark.parametrize(("module", "slot", "env"), PLUGINS)
def test_no_key_anywhere_is_an_empty_answer(
    platform: FakePlatformKeyring, module, slot, env  # noqa: ANN001
) -> None:
    assert module._read_keyring_secret(slot) == ""


@pytest.mark.parametrize(("module", "slot", "env"), PLUGINS)
def test_a_legacy_read_through_the_macos_vault_writes_nothing(
    module, slot, env  # noqa: ANN001
) -> None:
    inner = FakePerItemKeychain()
    cli = FakeSecurityCli()
    inner.values[(LEGACY, slot)] = "per-item-legacy"
    cli.items[(LEGACY, VAULT_ACCOUNT)] = vault_payload({})
    original = keyring.get_keyring()
    keyring.set_keyring(DarwinBundleKeyringBackend(inner, cli=cli))
    try:
        assert module._read_keyring_secret(slot) == "per-item-legacy"
    finally:
        keyring.set_keyring(original)

    assert cli.writes(LEGACY) == []
    assert inner.writes(LEGACY) == []
