"""An error no route handled answers with its type and the log file (issue #1734)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dodaios.ui.web.internal_error as internal_error


def _client(monkeypatch, log_file: str = "C:/Users/x/AppData/Local/Dodaios/data/app.log"):
    monkeypatch.setattr(internal_error, "_log_file", lambda: log_file)
    app = FastAPI()
    internal_error.install_internal_error_answer(app)

    @app.put("/api/boom")
    def boom() -> None:
        raise KeyError("sk-secret-value")

    return TestClient(app, raise_server_exceptions=False)


def test_the_answer_names_the_error_type_and_the_log_file(monkeypatch) -> None:
    res = _client(monkeypatch).put("/api/boom")
    assert res.status_code == 500
    body = res.json()
    assert body["code"] == "internal_error"
    assert "KeyError" in body["detail"]
    assert "C:/Users/x/AppData/Local/Dodaios/data/app.log" in body["detail"]


def test_the_exception_message_stays_in_the_log(monkeypatch) -> None:
    res = _client(monkeypatch).put("/api/boom")
    assert "sk-secret-value" not in res.text


def test_without_a_known_log_file_the_answer_still_says_what_failed(monkeypatch) -> None:
    res = _client(monkeypatch, log_file="").put("/api/boom")
    assert res.json()["detail"] == "Something went wrong inside Dodaios (KeyError)."
