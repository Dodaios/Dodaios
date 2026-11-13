"""Which recognizers read a dictation, and under which name.

The list a dictation reads with must be the engines that really run here. A
cloud provider without a saved key, or an on-device engine without its model,
is not on it, and nothing stands on it under another engine's name. These
tests pin the order for each kind of computer, the privacy rule for a person
who chose an on-device recognizer, and that a saved key counts from the next
dictation on.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.dictation import recognizers as recognizers_mod
from dodaios.dictation.recognizers import (
    PARAKEET_ID,
    WHISPER_ID,
    Resolution,
    credential_signature,
    resolve_recognizers,
)
from dodaios.dictation.take import Recognizer

_LOCAL_NAMES = {WHISPER_ID, PARAKEET_ID, "nemotron-local"}


class _Provider:
    def __init__(self, name: str, model: str = "") -> None:
        self.name = name
        self.last_used_model = model


def _resolve(
    configured: str,
    *,
    keyed: tuple[str, ...] = (),
    language: str = "auto",
    worker: bool = False,
    accelerator: bool = False,
    parakeet: bool = False,
    whisper_in_process: bool = False,
    built: list[str] | None = None,
) -> Resolution:
    """Resolve for a host described by its keys and installed engines."""
    built = built if built is not None else []

    def _cloud(name: str) -> Any:
        built.append(name)
        return _Provider(name, model=f"{name}-model")

    return resolve_recognizers(
        SimpleNamespace(provider=configured),
        language=language,
        cloud=_cloud,
        keyed_cloud_names=lambda: list(keyed),
        runs_on_device=lambda name: name in _LOCAL_NAMES,
        whisper_worker=_Provider(WHISPER_ID, "large-v3-turbo") if worker else None,
        whisper_has_accelerator=accelerator,
        parakeet=(lambda: _Provider(PARAKEET_ID, "parakeet-v3")) if parakeet else None,
        configured_local=lambda name: _Provider(name),
        whisper_in_process=(
            (lambda: _Provider(WHISPER_ID, "large-v3")) if whisper_in_process else None
        ),
    )


def _ids(resolution: Resolution) -> list[str]:
    return [recognizer.id for recognizer in resolution.recognizers]


# --------------------------------------------------------------------------
# A cloud provider with a key
# --------------------------------------------------------------------------


def test_a_keyed_cloud_provider_leads_and_the_fast_local_model_stands_in() -> None:
    resolution = _resolve("groq-api", keyed=("groq-api",), worker=True, parakeet=True)

    assert _ids(resolution) == ["groq-api", PARAKEET_ID]
    assert resolution.recognizers[0].on_device is False
    assert resolution.recognizers[1].on_device is True
    assert resolution.detail == ""


def test_without_the_fast_model_local_whisper_is_the_stand_in() -> None:
    resolution = _resolve("groq-api", keyed=("groq-api",), worker=True)

    assert _ids(resolution) == ["groq-api", WHISPER_ID]


def test_a_cloud_only_host_reads_with_the_cloud_provider_alone() -> None:
    resolution = _resolve("groq-api", keyed=("groq-api",))

    assert _ids(resolution) == ["groq-api"]


def test_a_graphics_card_puts_local_whisper_in_front_of_the_cloud() -> None:
    resolution = _resolve(
        "groq-api", keyed=("groq-api",), worker=True, accelerator=True, parakeet=True
    )

    assert _ids(resolution) == [WHISPER_ID, "groq-api"]
    assert resolution.recognizers[0].on_device is True


# --------------------------------------------------------------------------
# No key for the configured provider
# --------------------------------------------------------------------------


def test_a_provider_without_a_key_is_not_on_the_list_under_any_name() -> None:
    """The defect this replaces: the local engine ran under the cloud's name,
    so the log and the history named a provider that never saw the audio."""
    built: list[str] = []

    resolution = _resolve("groq-api", worker=True, parakeet=True, built=built)

    assert _ids(resolution) == [PARAKEET_ID, WHISPER_ID]
    assert all(recognizer.on_device for recognizer in resolution.recognizers)
    assert built == [], "a provider without a key was built anyway"
    assert "groq-api" in resolution.detail
    assert "this computer" in resolution.detail


def test_another_keyed_provider_takes_over_and_the_status_says_so() -> None:
    resolution = _resolve("groq-api", keyed=("openai-api",), parakeet=True)

    assert _ids(resolution) == ["openai-api", PARAKEET_ID]
    assert "openai-api" in resolution.detail and "groq-api" in resolution.detail


def test_slow_local_whisper_names_the_faster_model_that_can_be_downloaded() -> None:
    resolution = _resolve("groq-api", worker=True)

    assert _ids(resolution) == [WHISPER_ID]
    assert "Parakeet" in resolution.detail


def test_whisper_on_a_graphics_card_gets_no_hint_about_speed() -> None:
    resolution = _resolve("groq-api", worker=True, accelerator=True)

    assert _ids(resolution) == [WHISPER_ID]
    assert "Parakeet" not in resolution.detail


def test_whisper_inside_the_app_is_the_floor_without_the_worker() -> None:
    resolution = _resolve("groq-api", whisper_in_process=True)

    assert _ids(resolution) == [WHISPER_ID]


def test_nothing_installed_and_no_key_is_an_empty_list_with_a_reason() -> None:
    resolution = _resolve("groq-api")

    assert resolution.recognizers == ()
    assert resolution.detail
    assert resolution.status()["provider"] == ""


# --------------------------------------------------------------------------
# The person chose an on-device recognizer
# --------------------------------------------------------------------------


@pytest.mark.parametrize("configured", [WHISPER_ID, PARAKEET_ID, "nemotron-local"])
def test_a_local_choice_never_puts_a_cloud_provider_on_the_list(configured: str) -> None:
    """Somebody who picked an on-device recognizer did so to keep their audio
    on the computer. Saved keys do not change that."""
    built: list[str] = []

    resolution = _resolve(
        configured,
        keyed=("groq-api", "openai-api"),
        worker=True,
        parakeet=True,
        built=built,
    )

    assert built == []
    assert all(recognizer.on_device for recognizer in resolution.recognizers)
    assert _ids(resolution)[0] == configured


def test_chosen_whisper_leads_even_without_a_graphics_card() -> None:
    resolution = _resolve(WHISPER_ID, worker=True, parakeet=True)

    assert _ids(resolution) == [WHISPER_ID, PARAKEET_ID]


# --------------------------------------------------------------------------
# Language
# --------------------------------------------------------------------------


def test_the_fast_model_is_left_out_for_a_language_it_cannot_read() -> None:
    """Parakeet covers European languages only; Chinese belongs to Whisper."""
    resolution = _resolve("groq-api", language="zh", worker=True, parakeet=True)

    assert _ids(resolution) == [WHISPER_ID]


@pytest.mark.parametrize("language", ["de", "de-DE", "en", "auto", ""])
def test_the_fast_model_reads_the_languages_it_covers(language: str) -> None:
    resolution = _resolve("groq-api", language=language, worker=True, parakeet=True)

    assert _ids(resolution)[0] == PARAKEET_ID


# --------------------------------------------------------------------------
# The status the settings page shows
# --------------------------------------------------------------------------


def test_status_names_the_engine_its_model_and_the_stand_in() -> None:
    status = _resolve("groq-api", keyed=("groq-api",), parakeet=True).status()

    assert status == {
        "local": False,
        "provider": "groq-api",
        "model": "groq-api-model",
        "fallback": PARAKEET_ID,
        "detail": "",
        "reason": "",
        "configured": "groq-api",
    }


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"keyed": ("groq-api",), "parakeet": True}, ""),
        ({"parakeet": True}, "no_key"),
        ({"worker": True}, "no_key_slow"),
        ({"keyed": ("openai-api",)}, "other_provider"),
        ({}, "no_recognizer"),
    ],
)
def test_the_status_carries_a_reason_a_surface_can_translate(
    kwargs: dict[str, Any], reason: str
) -> None:
    assert _resolve("groq-api", **kwargs).status()["reason"] == reason


def test_every_provider_is_wrapped_once() -> None:
    wrapped: list[str] = []

    def _wrap(provider: Any) -> Any:
        wrapped.append(provider.name)
        return provider

    resolve_recognizers(
        SimpleNamespace(provider="groq-api"),
        cloud=lambda name: _Provider(name),
        keyed_cloud_names=lambda: ["groq-api"],
        runs_on_device=lambda name: name in _LOCAL_NAMES,
        parakeet=lambda: _Provider(PARAKEET_ID),
        wrap=_wrap,
    )

    assert sorted(wrapped) == ["groq-api", PARAKEET_ID]


# --------------------------------------------------------------------------
# A saved key counts at once
# --------------------------------------------------------------------------


def _secrets(monkeypatch: pytest.MonkeyPatch, store: dict[str, str]) -> None:
    from dodaios.core import config as config_mod

    def _get_secret_any(candidates: Any) -> str | None:
        for candidate in candidates:
            key = candidate[0] if isinstance(candidate, tuple | list) else candidate
            if store.get(str(key)):
                return store[str(key)]
        return None

    monkeypatch.setattr(config_mod, "get_secret_any", _get_secret_any)


def test_the_signature_changes_when_a_key_is_saved_or_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store: dict[str, str] = {}
    _secrets(monkeypatch, store)
    cfg = SimpleNamespace(provider="groq-api")

    without = credential_signature(cfg)
    store["groq_api_key"] = "gsk_first"
    with_key = credential_signature(cfg)
    store["groq_api_key"] = "gsk_second"
    replaced = credential_signature(cfg)
    del store["groq_api_key"]

    assert len({without, with_key, replaced}) == 3
    assert credential_signature(cfg) == without


def test_the_signature_holds_no_key_material(monkeypatch: pytest.MonkeyPatch) -> None:
    store = {"groq_api_key": "gsk_do_not_leak_this_value"}
    _secrets(monkeypatch, store)

    signature = credential_signature(SimpleNamespace(provider="groq-api"))

    assert "gsk_" not in repr(signature)
    assert "do_not_leak" not in repr(signature)


def test_the_signature_follows_the_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _secrets(monkeypatch, {})

    assert credential_signature(SimpleNamespace(provider="groq-api")) != credential_signature(
        SimpleNamespace(provider="openai-api")
    )


# --------------------------------------------------------------------------
# The pipeline: resolved once, resolved again when something changed
# --------------------------------------------------------------------------


def _pipeline(monkeypatch: pytest.MonkeyPatch, store: dict[str, str]) -> tuple[Any, list[str]]:
    """A pipeline whose plugin layer is replaced by a keyed/unkeyed fake."""
    import dodaios.plugins.stt as stt_plugins
    import dodaios.speech.pipeline as pipeline_mod
    from dodaios.core.config import DictationConfig, STTConfig

    _secrets(monkeypatch, store)
    built: list[str] = []

    def _build(cfg: Any, **_kwargs: Any) -> Any:
        built.append(str(cfg.provider))
        # A provider without a key is built as the local floor, as the real
        # factory does.
        if cfg.provider == "groq-api" and not store.get("groq_api_key"):
            return _Provider(WHISPER_ID)
        return _Provider(str(cfg.provider))

    monkeypatch.setattr(stt_plugins, "build_stt_from_config", _build)
    monkeypatch.setattr(
        stt_plugins,
        "available_stt_provider_names",
        lambda: ["groq-api"] if store.get("groq_api_key") else [],
    )
    monkeypatch.setattr(
        stt_plugins, "_stt_family_has_key", lambda name: bool(store.get("groq_api_key"))
    )
    monkeypatch.setattr(
        stt_plugins, "provider_runs_on_device", lambda name: name in _LOCAL_NAMES
    )
    monkeypatch.setattr(recognizers_mod, "parakeet_ready", lambda: True)
    monkeypatch.setattr(pipeline_mod, "meter_stt", lambda provider, *_a, **_k: provider)
    monkeypatch.setattr(
        "dodaios.speech.stt_dictionary.wrap_stt_with_dictionary", lambda provider: provider
    )

    pipe = pipeline_mod.SpeechPipeline.__new__(pipeline_mod.SpeechPipeline)
    pipe._config = SimpleNamespace(stt=STTConfig(provider="groq-api"))
    pipe._dictation_cfg = DictationConfig(local_engine=False, language="de")
    pipe._speech_trace = None
    pipe._dictation_parakeet_instance = _Provider(PARAKEET_ID)
    return pipe, built


def test_a_key_saved_between_two_dictations_counts_for_the_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pasting a key used to change nothing until the app was restarted."""
    store: dict[str, str] = {}
    pipe, _built = _pipeline(monkeypatch, store)

    before = pipe._dictation_resolution()
    assert [r.id for r in before.recognizers] == [PARAKEET_ID]
    assert pipe.dictation_engine_status()["local"] is True

    store["groq_api_key"] = "gsk_pasted"
    after = pipe._dictation_resolution()

    assert [r.id for r in after.recognizers] == ["groq-api", PARAKEET_ID]
    status = pipe.dictation_engine_status()
    assert status["provider"] == "groq-api"
    assert status["local"] is False
    assert status["fallback"] == PARAKEET_ID


def test_nothing_is_built_again_while_nothing_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = {"groq_api_key": "gsk_saved"}
    pipe, built = _pipeline(monkeypatch, store)

    first = pipe._dictation_resolution()
    second = pipe._dictation_resolution()

    assert second is first
    assert built == ["groq-api"]


def test_a_settings_change_asks_for_a_fresh_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = {"groq_api_key": "gsk_saved"}
    pipe, built = _pipeline(monkeypatch, store)
    first = pipe._dictation_resolution()

    pipe._voice_stt_fallback_chain = ("openai-api",)
    pipe._voice_stt_fallback_instances = {"openai-api": object()}
    pipe._reset_dictation_stt()

    assert pipe._dictation_resolution() is not first
    assert built == ["groq-api", "groq-api"]
    assert pipe._voice_stt_fallback_chain is None


def test_the_reader_for_kept_recordings_uses_the_same_recognizers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dodaios.dictation.take import RecordingReader

    store = {"groq_api_key": "gsk_saved"}
    pipe, _built = _pipeline(monkeypatch, store)
    pipe._dictation_anchor_primed = True

    reader = pipe._dictation_stt()

    assert isinstance(reader, RecordingReader)
    assert [r.id for r in reader._recognizers()] == ["groq-api", PARAKEET_ID]


def test_a_pipeline_without_a_configuration_reads_with_its_voice_provider() -> None:
    import dodaios.speech.pipeline as pipeline_mod

    voice = _Provider("groq-api")
    pipe = pipeline_mod.SpeechPipeline.__new__(pipeline_mod.SpeechPipeline)
    pipe._utterance_stt = voice

    recognizers = pipe._dictation_resolution().recognizers

    assert recognizers == (Recognizer(id="groq-api", provider=voice, on_device=False),)
