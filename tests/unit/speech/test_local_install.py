"""The install result must explain why a local provider is not usable."""

from dodaios.speech import local_install
from dodaios.speech.local_models import LocalModelStatus


def test_install_reports_the_specific_model_readiness_issue(monkeypatch):
    detail = "The engine is installed, but large-v3 is not ready: missing model.bin."
    status = LocalModelStatus(
        runtime="faster-whisper",
        engine_installed=True,
        model_present=False,
        model_label="large-v3",
        detail=detail,
    )
    run = local_install._InstallRun()
    monkeypatch.setattr(local_install, "_run_for", lambda provider_id: run)
    monkeypatch.setattr(local_install, "local_status", lambda provider_id: status)
    monkeypatch.setattr(local_install, "_download_model", lambda entry, progress: None)
    monkeypatch.setattr(local_install, "_verify_engine", lambda entry: None)

    local_install._run_install("faster-whisper")

    assert run.state == "error"
    assert run.message == detail
    assert "download may have been interrupted" not in run.message


def _status(*, engine: bool, model: bool = True) -> LocalModelStatus:
    return LocalModelStatus(
        runtime="sherpa-onnx",
        engine_installed=engine,
        model_present=model,
        model_label="Piper voices",
        detail="Ready." if engine and model else "Not ready.",
    )


def test_install_fails_when_the_runtime_is_there_but_does_not_load(monkeypatch):
    """The package being on disk is not enough: the install loads it once.

    This is the state of issue #1698: the card said "ready", the first real
    use failed. The install now ends in an error that names the reason, and
    does not go on to download voices for a runtime that cannot speak.
    """
    run = local_install._InstallRun()
    downloads: list[str] = []
    monkeypatch.setattr(local_install, "_run_for", lambda provider_id: run)
    monkeypatch.setattr(local_install, "local_status", lambda provider_id: _status(engine=True))
    monkeypatch.setattr(
        local_install, "_verify_engine", lambda entry: "DLL load failed while importing _native"
    )
    monkeypatch.setattr(
        local_install,
        "_download_model",
        lambda entry, progress: downloads.append(entry.provider_id),
    )

    local_install._run_install("piper-local")

    assert run.state == "error"
    assert "could not be loaded" in run.message
    assert "DLL load failed" in run.message
    assert downloads == []


def test_a_runtime_that_did_not_load_is_replaced_not_just_installed(monkeypatch):
    """pip finds a broken runtime "already satisfied": the repair must replace it."""
    from dodaios.speech import local_models

    run = local_install._InstallRun()
    calls: list[bool] = []
    monkeypatch.setattr(local_models, "_LOAD_FAILURES", {"sherpa-onnx": "OSError: broken"})
    monkeypatch.setattr(local_install, "_run_for", lambda provider_id: run)

    def _probe(provider_id):
        return _status(engine=local_models.runtime_load_failure("sherpa-onnx") is None)

    monkeypatch.setattr(local_install, "local_status", _probe)

    def _install(entry, *, repair=False):
        calls.append(repair)
        return True, "installed"

    monkeypatch.setattr(local_install, "_install_engine", _install)
    monkeypatch.setattr(local_install, "_verify_engine", lambda entry: None)
    monkeypatch.setattr(local_install, "_download_model", lambda entry, progress: None)

    local_install._run_install("piper-local")

    assert calls == [True]
    assert local_models.runtime_load_failure("sherpa-onnx") is None
    assert run.state == "done"


def test_verify_engine_reports_the_real_load_error(monkeypatch):
    from dodaios.speech import local_models

    def _refuse(runtime, **_kwargs):
        raise ImportError("sherpa_onnx could not be loaded: missing library")

    monkeypatch.setattr(local_models, "import_runtime", _refuse)
    entry = local_models.get_local_provider("piper-local")

    assert local_install._verify_engine(entry) == "sherpa_onnx could not be loaded: missing library"
