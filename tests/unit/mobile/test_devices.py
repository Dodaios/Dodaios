"""Pairing codes are one-use and short-lived; tokens are revocable and never stored."""

from __future__ import annotations

import pytest

from dodaios.mobile import devices as mod
from dodaios.mobile.devices import MobileDevices, PairingError, PushSubscription, normalize_code


@pytest.fixture
def store(tmp_path):
    return MobileDevices(tmp_path / "mobile" / "devices.json")


def test_redeem_once_then_the_code_is_spent(store: MobileDevices) -> None:
    code = store.issue_code()["code"]
    assert store.open_codes() == 1
    device, token = store.redeem(code, "My phone", user_agent="Mobile Safari")
    assert token.startswith("mdt_") and device.name == "My phone"
    assert store.authenticate(token) is not None
    assert store.open_codes() == 0
    with pytest.raises(PairingError) as spent:
        store.redeem(code, "Again")
    assert spent.value.status == 401


def test_token_is_never_written_to_disk_only_its_digest(store: MobileDevices) -> None:
    code = store.issue_code()["code"]
    _device, token = store.redeem(code, "Phone")
    text = store.path.read_text(encoding="utf-8")
    assert token not in text and code not in text
    assert store.authenticate("mdt_" + "x" * 43) is None
    assert store.authenticate(None) is None
    assert store.authenticate("") is None


def test_codes_are_typeable_and_normalised(store: MobileDevices) -> None:
    code = store.issue_code()["code"]
    assert len(code) == 10 and code.isupper()
    assert not set(code) & set("01IO")
    spaced = " ".join(code.lower()[i : i + 5] for i in (0, 5))
    assert normalize_code(spaced) == code
    device, _token = store.redeem(spaced, "Phone")
    assert device.id


def test_expired_codes_are_swept(store: MobileDevices, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    code = store.issue_code()["code"]
    now[0] += mod.CODE_TTL_S + 1
    assert store.open_codes() == 0
    with pytest.raises(PairingError):
        store.redeem(code, "Late")


def test_too_many_wrong_codes_drop_every_open_code(store: MobileDevices) -> None:
    store.issue_code()
    for _ in range(mod.MAX_FAILED_ATTEMPTS):
        with pytest.raises(PairingError):
            store.redeem("WRONG", "x")
    assert store.open_codes() == 0


def test_revoke_forgets_token_and_push(store: MobileDevices) -> None:
    device, token = store.redeem(store.issue_code()["code"], "Phone")
    store.set_push(
        device.id,
        PushSubscription(endpoint="https://push.example/abc", p256dh="k" * 32, auth="a" * 16),
    )
    assert store.push_targets()[0].id == device.id
    assert store.public_devices()[0]["push"] is True
    assert "endpoint" not in store.public_devices()[0]
    assert store.revoke(device.id) is True
    assert store.authenticate(token) is None
    assert store.push_targets() == []
    assert store.revoke(device.id) is False


def test_rename_and_touch(store: MobileDevices) -> None:
    device, _token = store.redeem(store.issue_code()["code"], "Phone")
    renamed = store.rename(device.id, "  Ruby's phone ")
    assert renamed.name == "Ruby's phone"
    store.touch(device.id)  # within a minute of pairing: no rewrite, no error
    with pytest.raises(PairingError) as missing:
        store.rename("nope", "x")
    assert missing.value.status == 404


def test_survives_a_new_store_instance(store: MobileDevices) -> None:
    _device, token = store.redeem(store.issue_code()["code"], "Phone")
    again = MobileDevices(store.path)
    assert again.authenticate(token) is not None
    assert again.open_codes() == 0  # codes are process-local
