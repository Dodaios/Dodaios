"""Issue #1058: the active data directory and its source are visible.

A launcher that points ``JARVIS_DATA_DIR`` at a new folder makes saved agents
look deleted. The boot log and the diagnostics API now name the directory in
use and whether the environment variable or the default chose it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core import config as config_mod
from dodaios.core.instance import DATA_DIR_ENV_VAR, data_dir_source


def test_the_source_follows_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, "/srv/dodaios-data")
    assert data_dir_source() == "JARVIS_DATA_DIR"
    monkeypatch.setenv(DATA_DIR_ENV_VAR, "   ")
    assert data_dir_source() == "default"
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)
    assert data_dir_source() == "default"


def test_the_boot_line_names_path_and_source_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(config_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "DATA_DIR_SOURCE", "JARVIS_DATA_DIR")
    monkeypatch.setattr(config_mod, "_data_dir_logged", False)
    with caplog.at_level(logging.INFO, logger="dodaios.core.config"):
        assert config_mod.log_data_dir_once() is True
        assert config_mod.log_data_dir_once() is False
    lines = [r.getMessage() for r in caplog.records if "Data directory" in r.getMessage()]
    assert lines == [f"Data directory: {tmp_path} (source: JARVIS_DATA_DIR)"]


def test_the_diagnostics_route_reports_path_and_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dodaios.ui.web.diagnostics_routes import router

    monkeypatch.setattr(config_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "DATA_DIR_SOURCE", "default")
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/api/diagnostics/data-dir")
    assert response.status_code == 200
    assert response.json() == {"path": str(tmp_path), "source": "default"}


def test_the_import_time_source_matches_the_import_time_directory() -> None:
    assert config_mod.DATA_DIR_SOURCE in {"JARVIS_DATA_DIR", "default"}
    assert config_mod.data_dir_info()["path"] == str(config_mod.DATA_DIR)
