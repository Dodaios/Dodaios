"""The privacy overview reads what is configured; it decides nothing."""

from __future__ import annotations

from types import SimpleNamespace

from dodaios.trust import privacy


def _cfg(**over):
    base = {
        "brain": SimpleNamespace(
            primary="gemini", realtime=SimpleNamespace(provider="openai-realtime")
        ),
        "tts": SimpleNamespace(provider="piper-local"),
        "stt": SimpleNamespace(provider="faster-whisper"),
        "memory": SimpleNamespace(learning=SimpleNamespace(provider="")),
        "integrations": SimpleNamespace(
            telegram=SimpleNamespace(enabled=True), discord=SimpleNamespace(enabled=False)
        ),
        "screen_context": SimpleNamespace(enabled=False),
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_providers_in_use_name_each_role_and_whether_it_is_local(monkeypatch) -> None:
    monkeypatch.setattr(
        privacy, "is_local_provider", lambda pid: "local" in pid or "whisper" in pid
    )
    monkeypatch.setattr(privacy, "_provider_label", lambda pid: pid.upper())
    rows = privacy.providers_in_use(_cfg())
    assert [(r["role"], r["provider"], r["local"]) for r in rows] == [
        ("brain", "gemini", False),
        ("realtime", "openai-realtime", False),
        ("tts", "piper-local", True),
        ("stt", "faster-whisper", True),
    ]
    assert rows[0]["label"] == "GEMINI"


def test_the_overview_lists_channels_screen_and_memory(monkeypatch) -> None:
    monkeypatch.setattr(
        privacy,
        "connected_accounts",
        lambda: [{"id": "gmail", "label": "Gmail", "category": "mail", "status": "connected"}],
    )
    monkeypatch.setattr(
        privacy,
        "memory_state",
        lambda: {"available": True, "count": 12, "learning_paused": False, "paused_until": None},
    )
    monkeypatch.setattr(privacy, "is_local_provider", lambda pid: pid.endswith("local"))
    monkeypatch.setattr(privacy, "_provider_label", lambda pid: pid)
    out = privacy.overview(_cfg())
    assert out["accounts"][0]["id"] == "gmail"
    assert out["memory"]["count"] == 12
    assert out["channels"] == ["telegram"]
    assert out["screen_context"] is False
    assert [p["provider"] for p in out["cloud"]] == ["gemini", "openai-realtime", "faster-whisper"]


def test_the_overview_paints_without_a_vault_or_a_catalog(monkeypatch) -> None:
    monkeypatch.setattr(privacy, "connected_accounts", lambda: [])
    out = privacy.overview(_cfg())
    assert out["memory"]["available"] is False
    assert out["known_recipients"] == 0


def test_local_providers_are_spec_derived_with_obvious_names_as_a_fallback() -> None:
    assert privacy.is_local_provider("ollama")
    assert privacy.is_local_provider("faster-whisper")
    assert not privacy.is_local_provider("gemini")
    assert not privacy.is_local_provider("")
