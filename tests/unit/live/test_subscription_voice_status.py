"""A signed-in account is not a working voice: remember what a call start proved."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.live import subscription_voice_status as voice_status
from dodaios.live.subscription_auth import SubscriptionAuth


@pytest.fixture(autouse=True)
def _own_record(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_status, "_path", lambda: tmp_path / "voice.json")


def _token(plan: str, account_id: str = "remote-account") -> str:
    payload = {
        "exp": time.time() + 3600,
        "https://api.openai.com/auth": {
            "chatgpt_account_id": account_id,
            "chatgpt_plan_type": plan,
        },
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"fixture.{encoded}.signature"


def _auth(tmp_path: Path, plan: str = "free") -> SubscriptionAuth:
    folder = tmp_path / "account"
    folder.mkdir(exist_ok=True)
    (folder / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": _token(plan),
                    "refresh_token": "fixture-refresh-token",
                    "account_id": "remote-account",
                },
            }
        ),
        encoding="utf-8",
    )
    account = SimpleNamespace(
        id="codex:test", label="Test account", platform="codex", config_dir=folder
    )
    return SubscriptionAuth(account=account)


def test_a_connected_account_is_unverified_until_a_call_start_says_otherwise(tmp_path):
    status = _auth(tmp_path).status_snapshot()
    assert status["connected"] is True
    assert status["voice_status"] == "unverified"
    assert status["voice_verified"] is False
    assert status["plan"] == "free"


def test_a_refused_start_turns_connected_into_unavailable_with_the_reason(tmp_path):
    auth = _auth(tmp_path)
    auth._load_credentials(False)
    auth.record_voice_outcome("voice_not_offered")

    status = _auth(tmp_path).status_snapshot()
    assert status["connected"] is True
    assert status["voice_status"] == "unavailable"
    assert status["voice_code"] == "voice_not_offered"
    assert "Free plan" in status["voice_reason"]
    assert "fixture" not in json.dumps(status)


def test_a_successful_start_replaces_an_older_refusal(tmp_path):
    auth = _auth(tmp_path)
    auth._load_credentials(False)
    auth.record_voice_outcome("voice_not_offered")
    auth.record_voice_outcome("ready")

    status = _auth(tmp_path).status_snapshot()
    assert status["voice_status"] == "ready"
    assert status["voice_verified"] is True


def test_a_changed_plan_makes_an_old_refusal_stop_matching(tmp_path):
    auth = _auth(tmp_path, plan="free")
    auth._load_credentials(False)
    auth.record_voice_outcome("voice_not_offered")

    assert _auth(tmp_path, plan="plus").status_snapshot()["voice_status"] == "unverified"


@pytest.mark.parametrize("code", ["rate_limited", "network_unreachable", "provider_error", ""])
def test_a_passing_failure_says_nothing_lasting_about_the_account(tmp_path, code):
    auth = _auth(tmp_path)
    auth._load_credentials(False)
    auth.record_voice_outcome(code)
    assert _auth(tmp_path).status_snapshot()["voice_status"] == "unverified"


def test_nothing_is_recorded_before_the_login_was_loaded(tmp_path):
    _auth(tmp_path).record_voice_outcome("voice_not_offered")
    assert not (tmp_path / "voice.json").exists()


def test_the_record_holds_no_account_identifier(tmp_path):
    auth = _auth(tmp_path)
    auth._load_credentials(False)
    auth.record_voice_outcome("ready")
    stored = (tmp_path / "voice.json").read_text(encoding="utf-8")
    assert "remote-account" not in stored
    assert "fixture" not in stored


def test_an_unreadable_record_reads_as_unverified(tmp_path):
    (tmp_path / "voice.json").write_text("not json", encoding="utf-8")
    assert voice_status.read("codex:test", "anything") == ""
    assert _auth(tmp_path).status_snapshot()["voice_status"] == "unverified"
