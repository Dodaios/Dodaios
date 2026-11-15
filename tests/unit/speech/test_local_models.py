"""Guards for the on-disk readiness probe behind the local speech providers.

The regression these pin: a local provider card that reported "ready" on an
install where the engine was never installed and the model never downloaded
(the defect that removed the local Whisper card on 2026-07-03). Every test here
asserts the FAIL-CLOSED direction — an unproven readiness must read as not
ready, because the alternative is a provider the user activates and that then
cannot transcribe a word.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from dodaios.speech import local_models


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every probe away from the developer's real model cache."""
    monkeypatch.setenv("JARVIS__MEMORY__DATA_DIR", str(tmp_path))
    # No test inherits another one's note about a runtime that did not load.
    monkeypatch.setattr(local_models, "_LOAD_FAILURES", {})


def _stand_in_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, source: str | None
) -> None:
    """Put a package called *name* on the path and make it the sherpa runtime.

    ``source`` is the text of its ``__init__.py``; None leaves only a folder,
    which is what an interrupted uninstall leaves behind.
    """
    package = tmp_path / "site" / name
    (package / "lib").mkdir(parents=True)
    if source is not None:
        (package / "__init__.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    monkeypatch.setitem(local_models._RUNTIME_MODULES, "sherpa-onnx", name)
    importlib.invalidate_caches()


def test_missing_engine_is_never_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """No engine installed -> not ready, and the text says to install it."""
    monkeypatch.setattr(local_models, "runtime_installed", lambda runtime: False)

    status = local_models.whisper_status("large-v3")

    assert status.ready is False
    assert status.engine_installed is False
    assert "not installed" in status.detail


def test_installed_engine_without_weights_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine alone is not readiness — the model still has to be there.

    This is the half the removed card got wrong: it treated "the package is
    importable" as "this provider works".
    """
    monkeypatch.setattr(local_models, "runtime_installed", lambda runtime: True)
    monkeypatch.setattr(
        local_models,
        "_whisper_model_cache_issue",
        lambda name: "missing or empty model files: model.bin",
    )

    status = local_models.whisper_status("large-v3")

    assert status.ready is False
    assert status.engine_installed is True
    assert status.model_present is False
    assert "missing or empty model files: model.bin" in status.detail


def test_engine_and_weights_present_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_models, "runtime_installed", lambda runtime: True)
    monkeypatch.setattr(local_models, "_whisper_model_cache_issue", lambda name: None)

    status = local_models.whisper_status("large-v3")

    assert status.ready is True
    assert "large-v3" in status.detail


def test_whisper_cache_probe_never_reaches_the_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The probe must ask the cache only — a status poll may not start a download."""
    seen: dict[str, object] = {}

    def _fake_download(name: str, **kwargs: object) -> str:
        seen.update(kwargs)
        return str(tmp_path)

    import huggingface_hub

    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.json"):
        (tmp_path / name).write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(huggingface_hub, "snapshot_download", _fake_download)

    assert local_models.whisper_model_cached("test/whisper") is True
    assert seen.get("local_files_only") is True


def test_unknown_runtime_reports_absent() -> None:
    """An unrecognised runtime is 'not installed', never an exception."""
    assert local_models.runtime_installed("something-else") is False


def test_incomplete_sherpa_bundle_is_not_present(tmp_path: Path) -> None:
    """A half-extracted download must not count as a usable model.

    An interrupted unpack leaves a directory that exists but cannot load; if
    that read as ready, the failure would surface as a stack trace mid-sentence
    instead of an honest "download it again".
    """
    model_dir = local_models.sherpa_model_dir("demo-model")
    model_dir.mkdir(parents=True)
    (model_dir / "model.onnx").write_bytes(b"not-really-a-model")

    assert (
        local_models.sherpa_model_present(
            "demo-model", required_files=("model.onnx", "tokens.txt")
        )
        is False
    )
    assert local_models.sherpa_model_present("demo-model") is True


def test_catalog_entry_is_resolvable_and_cloud_ids_are_not() -> None:
    """Locality is a catalog fact, so no caller has to branch on a name (AP-21)."""
    entry = local_models.get_local_provider("faster-whisper")

    assert entry is not None
    assert entry.tier == "stt"
    assert entry.model_id == local_models.WHISPER_VOICE_MODEL
    assert local_models.get_local_provider("groq-api") is None
    assert local_models.local_status("groq-api") is None


def test_pip_requirements_match_the_local_voice_extra() -> None:
    """The in-app installer and the packaged extra must ask for the SAME thing.

    They are declared in two files that never meet — the catalog (what the
    install button runs) and pyproject's ``[local-voice]`` extra (what a normal
    pip install brings). Drift here is invisible until someone installs one way
    and gets a different engine version than the other way, which for
    sherpa-onnx means a silently English-only recogniser.
    """
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extra = data["project"]["optional-dependencies"]["local-voice"]

    for entry in local_models.LOCAL_PROVIDERS:
        package, _, floor = entry.pip_package.partition(">=")
        matching = [dep for dep in extra if dep.split(";")[0].strip().startswith(package)]
        assert matching, f"{package} is missing from the [local-voice] extra"
        assert any(floor in dep for dep in matching), (
            f"{package} floor {floor} in the catalog does not match "
            f"the [local-voice] extra: {matching}"
        )


def test_status_reports_the_model_the_config_actually_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An override must be reflected, or the card reassures about the wrong model."""
    monkeypatch.setattr(local_models, "runtime_installed", lambda runtime: True)
    monkeypatch.setattr(
        local_models,
        "_whisper_model_cache_issue",
        lambda name: "missing or empty model files: model.bin",
    )

    status = local_models.local_status("faster-whisper", model_override="small")

    assert status is not None
    assert status.model_label == "small"
    assert "small" in status.detail


def test_never_downloaded_model_gets_the_plain_download_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first run is not a broken cache: tell the user to download once."""
    monkeypatch.setattr(local_models, "runtime_installed", lambda runtime: True)
    monkeypatch.setattr(
        local_models,
        "_whisper_model_cache_issue",
        lambda name: local_models._WHISPER_NOT_DOWNLOADED,
    )

    status = local_models.whisper_status("large-v3")

    assert status.ready is False
    assert "still has to be downloaded" in status.detail


def test_uncached_repo_reads_as_not_downloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    import huggingface_hub
    from huggingface_hub.errors import LocalEntryNotFoundError

    def _missing(*_args, **_kwargs):
        raise LocalEntryNotFoundError("not cached")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", _missing)

    assert (
        local_models._whisper_model_cache_issue("Systran/faster-whisper-large-v3")
        == local_models._WHISPER_NOT_DOWNLOADED
    )


def test_a_leftover_runtime_folder_is_not_an_installed_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A folder without code is importable as a namespace package, and is no engine.

    An interrupted uninstall or update leaves exactly that behind. The probe
    used to answer "installed" for it, so the card said "ready".
    """
    _stand_in_runtime(monkeypatch, tmp_path, "leftover_runtime_only_a_folder", None)

    assert importlib.util.find_spec("leftover_runtime_only_a_folder") is not None
    assert local_models.runtime_installed("sherpa-onnx") is False


def test_a_real_package_is_an_installed_engine_without_being_imported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The poll finds the package and does not load it (it may be a heavy native one)."""
    _stand_in_runtime(
        monkeypatch, tmp_path, "runtime_never_imported", "raise RuntimeError('imported')\n"
    )

    assert local_models.runtime_installed("sherpa-onnx") is True


def test_a_runtime_that_does_not_load_is_not_ready_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """After one failed load the card stops saying "ready" and gives the reason."""
    _stand_in_runtime(
        monkeypatch,
        tmp_path,
        "runtime_with_a_broken_library",
        "raise OSError('DLL load failed while importing _native')\n",
    )
    monkeypatch.setattr(local_models, "bundle_present", lambda model_id, **kw: True)
    before = local_models.sherpa_status(("voice",), model_label="Voice", download_size="1 MB")
    assert before.ready is True

    with pytest.raises(ImportError, match="DLL load failed"):
        local_models.import_runtime("sherpa-onnx")

    after = local_models.sherpa_status(("voice",), model_label="Voice", download_size="1 MB")
    assert after.ready is False
    assert after.engine_installed is False
    assert "could not be loaded" in after.detail
    assert "DLL load failed" in after.detail


def test_a_runtime_without_the_needed_parts_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A module that imports but lacks what the provider calls cannot run either."""
    _stand_in_runtime(monkeypatch, tmp_path, "runtime_with_half_an_api", "Present = object\n")

    module = local_models.import_runtime("sherpa-onnx", needs=("Present",))
    assert module.Present is object
    assert local_models.runtime_load_failure("sherpa-onnx") is None

    with pytest.raises(ImportError, match="no OfflineTts"):
        local_models.import_runtime("sherpa-onnx", needs=("Present", "OfflineTts"))
    assert local_models.runtime_installed("sherpa-onnx") is False


def test_a_load_that_works_again_makes_the_runtime_usable_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stand_in_runtime(monkeypatch, tmp_path, "runtime_repaired_later", "Present = object\n")
    with pytest.raises(ImportError):
        local_models.import_runtime("sherpa-onnx", needs=("Missing",))
    assert local_models.runtime_installed("sherpa-onnx") is False

    local_models.import_runtime("sherpa-onnx", needs=("Present",))

    assert local_models.runtime_installed("sherpa-onnx") is True


def test_a_runtime_that_was_never_installed_leaves_no_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plain absence is the cheap probe's own finding.

    A note would outlive a later install made outside the app and keep the
    card at "not installed" until the next start.
    """
    monkeypatch.setitem(local_models._RUNTIME_MODULES, "sherpa-onnx", "runtime_that_is_not_there")

    with pytest.raises(ImportError):
        local_models.import_runtime("sherpa-onnx")

    assert local_models.runtime_load_failure("sherpa-onnx") is None
    assert local_models.runtime_installed("sherpa-onnx") is False
