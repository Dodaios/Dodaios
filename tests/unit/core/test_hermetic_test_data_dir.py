"""The test session never resolves the repo's own data dir (#458)."""
from __future__ import annotations

import os
from pathlib import Path

from dodaios.core import config

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_session_data_dir_is_a_temp_dir_outside_the_checkout() -> None:
    env_dir = Path(os.environ["JARVIS_DATA_DIR"]).resolve()
    assert env_dir.name.startswith("dodaios-test-data-")
    assert not env_dir.is_relative_to(_REPO_ROOT)


def test_config_data_dir_follows_the_session_temp_dir() -> None:
    assert Path(config.DATA_DIR).resolve() == Path(os.environ["JARVIS_DATA_DIR"]).resolve()
    assert not Path(config.DATA_DIR).resolve().is_relative_to(_REPO_ROOT / "data")


def test_memory_data_dir_defaults_to_the_session_temp_dir() -> None:
    from dodaios.core.config import JarvisConfig, MemoryConfig

    expected = Path(os.environ["JARVIS_DATA_DIR"]).resolve()
    assert Path(MemoryConfig().data_dir).resolve() == expected
    assert Path(JarvisConfig().memory.data_dir).resolve() == expected
    assert MemoryConfig(data_dir="./elsewhere").data_dir == "./elsewhere"
