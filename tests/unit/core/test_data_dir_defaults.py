"""Stores without an explicit path follow the runtime data dir, not the cwd (#458).

``JARVIS_DATA_DIR`` (the test session points it at a temp dir) and
``dodaios.core.config.DATA_DIR`` name the data dir; a default that is a bare
``data/`` lands in whatever directory the process runs from instead.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.core import config


@pytest.fixture
def runtime_dir(monkeypatch, tmp_path: Path) -> Path:  # noqa: ANN001
    """A runtime data dir that differs from the cwd."""
    target = tmp_path / "runtime"
    monkeypatch.setenv("JARVIS_DATA_DIR", str(target))
    monkeypatch.delenv("JARVIS__MEMORY__DATA_DIR", raising=False)
    monkeypatch.setattr(config, "DATA_DIR", target)
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    return target


def test_memory_data_dir_prefers_the_config_value(runtime_dir: Path, tmp_path: Path) -> None:
    cfg = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path / "configured")))
    assert config.memory_data_dir(cfg) == tmp_path / "configured"


@pytest.mark.parametrize("cfg", [None, SimpleNamespace(), SimpleNamespace(memory=None)])
def test_memory_data_dir_without_a_value_is_the_runtime_dir(runtime_dir: Path, cfg) -> None:  # noqa: ANN001
    assert config.memory_data_dir(cfg) == runtime_dir


def test_wiki_db_without_a_data_dir_is_in_the_runtime_dir(runtime_dir: Path) -> None:
    from dodaios.memory.wiki.db_path import resolve_wiki_db_path

    assert resolve_wiki_db_path() == (runtime_dir / "jarvis.db").resolve()


def test_wiki_db_with_a_relative_data_dir_is_anchored_at_the_checkout(runtime_dir: Path) -> None:
    from dodaios.core.paths import repo_root
    from dodaios.memory.wiki.db_path import resolve_wiki_db_path

    assert resolve_wiki_db_path("./data") == (repo_root() / "data" / "jarvis.db").resolve()


def test_speech_models_without_an_override_are_in_the_runtime_dir(runtime_dir: Path) -> None:
    from dodaios.speech.local_models import models_root

    assert models_root() == runtime_dir / "models"


def test_wake_gpu_probe_without_an_override_is_in_the_runtime_dir(runtime_dir: Path) -> None:
    from dodaios.plugins.stt import _wake_gpu_probe_cache_path

    assert _wake_gpu_probe_cache_path() == runtime_dir / "wake_gpu_probe.json"


def test_society_workspace_without_a_config_is_in_the_runtime_dir(runtime_dir: Path) -> None:
    from dodaios.society.surface import _workspace_fallback

    assert _workspace_fallback(None, "scout") == runtime_dir / "society" / "scout" / "workspace"


def test_wiki_cli_defaults_follow_the_session_data_dir() -> None:
    """Resolved at import, under the session's temp ``JARVIS_DATA_DIR``."""
    import os

    from dodaios.memory.wiki import cli

    session_dir = Path(os.environ["JARVIS_DATA_DIR"])
    assert cli.DEFAULT_DB == session_dir / "jarvis.db"
    assert cli.DEFAULT_BACKUP_DIR == session_dir / "backups"


def test_flight_recorder_dir_is_in_the_runtime_dir(runtime_dir: Path) -> None:
    from dodaios.core.paths import flight_recorder_dir, runtime_data_dir

    assert runtime_data_dir() == runtime_dir
    assert flight_recorder_dir() == runtime_dir / "flight_recorder"


def test_attached_flight_recorder_writes_into_the_runtime_dir(runtime_dir: Path) -> None:
    from dodaios.core.bus import EventBus
    from dodaios.telemetry.recorder import attach_flight_recorder

    rec = attach_flight_recorder(EventBus(), enabled=True)
    assert rec is not None
    assert rec._data_dir == runtime_dir / "flight_recorder"
