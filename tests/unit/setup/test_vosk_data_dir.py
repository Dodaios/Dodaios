"""Vosk verification and prefetch must use the install's data directory."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.core import paths
from dodaios.setup import model_report, prefetch
from dodaios.speech import wake_constants, wake_model_fetch
from dodaios.speech.wake_phrase import resolve_wake_plan


@pytest.fixture
def install_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "install"
    root.mkdir()
    monkeypatch.setattr(paths, "repo_root", lambda: root)
    for name in ("JARVIS_DATA_DIR", "JARVIS__MEMORY__DATA_DIR", "JARVIS_INSTANCE"):
        monkeypatch.delenv(name, raising=False)
    return root


def _model(data_dir: Path, language: str = "en") -> Path:
    model = data_dir / "wake_models" / "vosk" / language
    (model / "am").mkdir(parents=True)
    return model


@pytest.mark.parametrize("source", ["default", "dev", "runtime_env", "memory_env", "explicit"])
def test_presence_and_prefetch_keep_data_directory_precedence(
    install_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    data_dir = install_root / ("data-dev" if source == "dev" else "data")
    explicit = None
    if source == "dev":
        monkeypatch.setenv("JARVIS_INSTANCE", "dev")
    if source in ("runtime_env", "memory_env", "explicit"):
        data_dir = tmp_path / "runtime-data"
        monkeypatch.setenv("JARVIS_DATA_DIR", str(data_dir))
    if source in ("memory_env", "explicit"):
        data_dir = tmp_path / "memory-data"
        monkeypatch.setenv("JARVIS__MEMORY__DATA_DIR", str(data_dir))
    if source == "explicit":
        data_dir = tmp_path / "explicit-data"
        explicit = str(data_dir)
    expected = _model(data_dir)

    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    downloads: list[str] = []

    def no_download(url: str) -> bytes:
        downloads.append(url)
        raise AssertionError("An installed model must not be downloaded again")

    assert wake_model_fetch.vosk_model_present("en", data_dir=explicit)
    assert (
        wake_model_fetch.ensure_vosk_model(
            "en", data_dir=explicit, http_get=no_download, echo=lambda _line: None
        )
        == expected
    )
    assert downloads == []
    assert not (foreign / "data").exists()
    if source != "explicit":
        assert wake_constants.resolve_vosk_model_path("en") == str(expected)
        assert wake_constants.resolve_vosk_model_paths("en") == [str(expected)]
        plan = resolve_wake_plan(
            SimpleNamespace(phrase="Hey Nova", engine="auto", custom_model_path=""),
            local_whisper_available=False,
            language="en",
            vosk_available=True,
        )
        assert plan.engine == "vosk_kws"
        assert plan.vosk_model_path == str(expected)
        assert plan.vosk_model_paths == (str(expected),)
        assert plan.wake_available


@pytest.mark.parametrize("full_profile", [False, True])
def test_report_finds_installed_models_from_any_cwd(
    install_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    full_profile: bool,
) -> None:
    for language in wake_model_fetch.VOSK_MODELS:
        _model(install_root / "data", language)
    cfg = SimpleNamespace(stt=SimpleNamespace(language="en"))
    monkeypatch.setattr(model_report, "_wake_backbone_present", lambda: True)
    monkeypatch.setattr(model_report, "_vad_present", lambda: True)
    monkeypatch.setattr(model_report, "_neural_wake_runtime_available", lambda: False)
    monkeypatch.setattr(model_report, "_silero_runtime_available", lambda: False)
    monkeypatch.setattr(model_report, "_webrtc_vad_available", lambda: False)
    monkeypatch.setattr(model_report, "_faster_whisper_available", lambda: False)

    for cwd in (install_root, tmp_path, tmp_path / "elsewhere"):
        cwd.mkdir(exist_ok=True)
        monkeypatch.chdir(cwd)
        report = model_report.voice_model_report(cfg, full_profile=full_profile)
        wake = [item for item in report if "custom-wake model" in item.label]
        assert len(wake) == (len(wake_model_fetch.VOSK_MODELS) if full_profile else 1)
        assert all(item.present and item.detail == "ready" for item in wake)
        assert all(item.required == full_profile for item in wake)


def test_foreign_cwd_model_does_not_hide_missing_install_model(
    install_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(tmp_path / "data")
    monkeypatch.chdir(tmp_path)

    assert not wake_model_fetch.vosk_model_present("en")
    assert wake_constants.resolve_vosk_model_path("en") is None
    assert wake_constants.resolve_vosk_model_paths("en") == []
    plan = resolve_wake_plan(
        SimpleNamespace(phrase="Hey Nova", engine="auto", custom_model_path=""),
        local_whisper_available=False,
        language="en",
        vosk_available=True,
    )
    assert plan.engine == "none"
    assert not plan.wake_available
    assert not (install_root / "data").exists()


def test_prefetch_reuses_install_model_from_foreign_cwd(
    install_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(install_root / "data")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prefetch, "_wakeword_bundle_present", lambda: True)
    monkeypatch.setattr(prefetch, "_load_config", lambda: SimpleNamespace())
    monkeypatch.setattr(prefetch, "_faster_whisper_available", lambda: False)
    downloads: list[str] = []

    def no_download(url: str) -> bytes:
        downloads.append(url)
        raise AssertionError("Prefetch must reuse the installed model")

    monkeypatch.setattr(wake_model_fetch, "_http_get", no_download)
    assert prefetch.prefetch_all(echo=lambda _line: None) == 0
    assert downloads == []
    assert not (tmp_path / "data").exists()
