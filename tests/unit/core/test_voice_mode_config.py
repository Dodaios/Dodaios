"""Voice calls run only on realtime providers; old pipeline settings migrate.

The pipeline voice mode (STT plugin -> brain -> TTS plugin) was retired
2026-11-24. An upgraded install may still carry ``[voice] mode`` and the
ChatGPT-plan ``[voice] profile = "codex-subscription-voice"``; boot removes
both and lands every install on a working realtime selection.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from dodaios.core import config as cfg_mod
from dodaios.core import config_writer


@pytest.fixture
def boot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Load a TOML through the real boot path (heals included)."""
    toml = tmp_path / "jarvis.toml"
    reference = tmp_path / "drift-reference.json"
    monkeypatch.setattr(cfg_mod, "resolve_config_path", lambda: toml)
    monkeypatch.setattr(config_writer, "_config_soll_path", lambda: reference)  # i18n-allow

    def _load(text: str) -> cfg_mod.JarvisConfig:
        """Run the boot heals on the file, then parse exactly what it holds.

        ``load_config`` also layers the machine's profile and environment on
        top, so the result is read from the healed TOML alone.
        """
        toml.write_text(text, encoding="utf-8")
        cfg_mod._LEGACY_CODEX_REALTIME_HEALED.discard(toml)
        cfg_mod._RETIRED_VOICE_PIPELINE_HEALED.discard(toml)
        cfg_mod._heal_legacy_codex_realtime_once(toml)
        cfg_mod._heal_retired_voice_pipeline_once(toml)
        raw = toml.read_text(encoding="utf-8").lstrip("\ufeff")
        return cfg_mod.JarvisConfig.model_validate(tomllib.loads(raw))

    _load.toml = toml  # type: ignore[attr-defined]
    _load.reference = reference  # type: ignore[attr-defined]
    return _load


def test_voice_config_has_no_engine_switch() -> None:
    voice = cfg_mod.JarvisConfig().voice
    assert "mode" not in cfg_mod.VoiceConfig.model_fields
    assert "profile" not in cfg_mod.VoiceConfig.model_fields
    assert cfg_mod.JarvisConfig().brain.realtime is None
    assert voice.realtime_tool_mode == "hybrid"


def test_pipeline_mode_migrates_and_keeps_the_realtime_provider(boot) -> None:
    loaded = boot(
        '[brain.realtime]\nprovider = "gemini-live"\n\n'
        '[voice]\nmode = "pipeline"\nrealtime_tool_mode = "hybrid"\n'
    )

    content = boot.toml.read_text(encoding="utf-8")
    assert "mode = " not in content.split("[voice]", 1)[1].replace("realtime_tool_mode", "")
    assert 'realtime_tool_mode = "hybrid"' in content
    assert loaded.brain.realtime is not None
    assert loaded.brain.realtime.provider == "gemini-live"
    assert "mode" not in (loaded.voice.model_extra or {})


def test_pipeline_mode_without_a_provider_lands_on_the_default_pick(boot) -> None:
    """No pin: the factory picks the first credential-ready realtime provider."""
    loaded = boot('[voice]\nmode = "pipeline"\n')

    assert loaded.brain.realtime is None
    assert "mode" not in boot.toml.read_text(encoding="utf-8")


def test_subscription_voice_profile_moves_to_chatgpt_live(boot) -> None:
    loaded = boot(
        '[brain.providers.codex]\nmodel = "gpt-5.4"\n\n'
        '[voice]\nmode = "pipeline"\nprofile = "codex-subscription-voice"\n'
    )

    assert loaded.live.auth_mode == "chatgpt_subscription"
    assert loaded.live.configured is True
    assert loaded.live.subscription_backend_model == "gpt-5.4"
    assert loaded.live.provider_id == "openai-live-subscription"
    assert loaded.brain.realtime is not None
    assert loaded.brain.realtime.provider == "openai-live-subscription"
    assert loaded.brain.realtime.model == "gpt-live-1-codex"
    content = boot.toml.read_text(encoding="utf-8")
    assert "codex-subscription-voice" not in content
    assert 'mode = "pipeline"' not in content


def test_subscription_profile_without_a_codex_model_uses_the_codex_default(boot) -> None:
    from dodaios.plugins.brain.codex import DEFAULT_MODEL

    loaded = boot('[voice]\nprofile = "codex-subscription-voice"\n')

    assert loaded.live.subscription_backend_model == DEFAULT_MODEL
    assert loaded.brain.realtime is not None
    assert loaded.brain.realtime.provider == "openai-live-subscription"


def test_a_saved_live_setup_is_kept_when_the_profile_goes(boot) -> None:
    loaded = boot(
        '[live]\nconfigured = true\nauth_mode = "api_key"\nbackend_model = "gpt-5.5"\n\n'
        '[brain.realtime]\nprovider = "openai-live"\n\n'
        '[voice]\nmode = "realtime"\nprofile = "codex-subscription-voice"\n'
    )

    assert loaded.live.auth_mode == "api_key"
    assert loaded.brain.realtime is not None
    assert loaded.brain.realtime.provider == "openai-live"
    assert "profile" not in boot.toml.read_text(encoding="utf-8")


def test_removed_codex_realtime_primary_lands_on_chatgpt_live(boot) -> None:
    loaded = boot(
        '[brain.realtime]\nprovider = "codex-subscription-realtime"\n\n'
        '[voice]\nmode = "realtime"\nprofile = ""\n'
    )

    assert loaded.brain.realtime is not None
    assert loaded.brain.realtime.provider == "openai-live-subscription"
    assert loaded.live.auth_mode == "chatgpt_subscription"
    content = boot.toml.read_text(encoding="utf-8")
    assert "codex-subscription-realtime" not in content
    assert "profile" not in content


def test_migration_is_a_no_op_on_a_current_config(tmp_path: Path) -> None:
    toml = tmp_path / "jarvis.toml"
    original = (
        '[brain.realtime]\nprovider = "grok-realtime"\n\n'
        '[voice]\nrealtime_tool_mode = "hybrid"\n'
    )
    toml.write_text(original, encoding="utf-8")

    assert config_writer.migrate_retired_voice_pipeline(path=toml) is False
    assert toml.read_text(encoding="utf-8") == original


def test_migration_runs_once_and_keeps_a_bom(tmp_path: Path) -> None:
    toml = tmp_path / "jarvis.toml"
    toml.write_text('\ufeff[voice]\nmode = "pipeline"\n', encoding="utf-8")

    assert config_writer.migrate_retired_voice_pipeline(path=toml) is True
    assert config_writer.migrate_retired_voice_pipeline(path=toml) is False
    assert toml.read_text(encoding="utf-8").startswith("\ufeff")


def test_drift_guard_reference_forgets_the_retired_keys(boot) -> None:
    boot.reference.write_text(
        json.dumps({"voice": {"mode": "realtime", "keep": 1}, "brain": {"primary": "x"}}),
        encoding="utf-8",
    )

    boot('[voice]\nmode = "pipeline"\n')

    data = json.loads(boot.reference.read_text(encoding="utf-8"))
    assert data["voice"] == {"keep": 1}
    assert data["brain"] == {"primary": "x"}


def test_saving_gpt_live_writes_no_engine_key(tmp_path: Path, monkeypatch) -> None:
    toml = tmp_path / "jarvis.toml"
    toml.write_text("", encoding="utf-8")
    absent = tmp_path / "absent.json"
    monkeypatch.setattr(config_writer, "_config_soll_path", lambda: absent)  # i18n-allow

    config_writer.set_live_profile(
        {"configured": True, "backend_model": "gpt-5.5"}, path=toml
    )

    content = toml.read_text(encoding="utf-8")
    assert 'provider = "openai-live"' in content
    assert "[voice]" not in content


def test_realtime_tier_field_accepts_brain_tier_config() -> None:
    cfg = cfg_mod.JarvisConfig.model_validate(
        {"brain": {"realtime": {"provider": "openai"}}}
    )
    assert cfg.brain.realtime is not None
    assert cfg.brain.realtime.provider == "openai"


def test_boot_runs_the_migration_before_the_first_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "jarvis.toml"
    toml.write_text('[voice]\nmode = "pipeline"\n', encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "resolve_config_path", lambda: toml)
    absent = tmp_path / "absent.json"
    monkeypatch.setattr(config_writer, "_config_soll_path", lambda: absent)  # i18n-allow
    cfg_mod._LEGACY_CODEX_REALTIME_HEALED.discard(toml)
    cfg_mod._RETIRED_VOICE_PIPELINE_HEALED.discard(toml)
    cfg_mod.clear_config_cache()

    cfg_mod.load_config()

    assert 'mode = "pipeline"' not in toml.read_text(encoding="utf-8")


def test_the_migration_default_follows_the_codex_brain_default() -> None:
    from dodaios.plugins.brain.codex import DEFAULT_MODEL

    assert config_writer._CODEX_DEFAULT_THINKING_MODEL == DEFAULT_MODEL
