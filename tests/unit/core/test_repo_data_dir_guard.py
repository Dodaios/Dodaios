"""The session-end guard against writes into ``<repo>/data`` (#458)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture
def guard(monkeypatch, tmp_path: Path):  # noqa: ANN001, ANN201
    conftest = sys.modules["tests.conftest"]
    monkeypatch.setattr(conftest, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(conftest, "_REPO_DATA_DIR", tmp_path / "data")
    return conftest


def test_a_fresh_checkout_left_alone_passes(guard, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(guard, "_REPO_DATA_DIR_EXISTED", False)
    assert guard._repo_data_dir_leftovers() == []


def test_a_fresh_checkout_with_a_new_data_dir_is_reported(
    guard, monkeypatch, tmp_path: Path  # noqa: ANN001
) -> None:
    monkeypatch.setattr(guard, "_REPO_DATA_DIR_EXISTED", False)
    (tmp_path / "data").mkdir()
    assert guard._repo_data_dir_leftovers() == ["data/"]
    (tmp_path / "data" / "society").mkdir()
    (tmp_path / "data" / "self_mod.log").write_text("{}\n", encoding="utf-8")
    assert guard._repo_data_dir_leftovers() == ["data/self_mod.log", "data/society"]


def test_a_live_data_dir_is_not_judged(guard, monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setattr(guard, "_REPO_DATA_DIR_EXISTED", True)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "jarvis.db").write_bytes(b"")
    assert guard._repo_data_dir_leftovers() == []
