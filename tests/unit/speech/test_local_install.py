"""The install result must explain a cache-readiness failure accurately."""

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

    local_install._run_install("faster-whisper")

    assert run.state == "error"
    assert run.message == detail
    assert "download may have been interrupted" not in run.message
