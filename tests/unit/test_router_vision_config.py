"""Tests for RouterVisionConfig (Wave-1 B4).

Checks the Pydantic sub-config's defaults and the wiring into `jarvis.toml`
under `[brain.router.vision]`. All fields MUST have defaults — existing
configs without the section must still load cleanly.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from dodaios.core.config import (
    JarvisConfig,
    RouterVisionConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_router_vision_config_defaults():
    """RouterVisionConfig provides documented defaults without TOML data."""
    cfg = RouterVisionConfig()
    assert cfg.enabled is False  # latency fix: opt-in only (default changed)
    assert cfg.refresh_interval_s == 2.0
    assert cfg.max_staleness_s == 2.0
    assert cfg.capture_mode == "screenshot"
    assert cfg.max_image_kb == 500
    assert cfg.pause_on_idle is True


def test_public_example_loads_without_router_vision_override():
    """The public example loads without requiring a private jarvis.toml."""
    toml_path = REPO_ROOT / "docs/examples/dodaios.toml.example"
    assert toml_path.exists(), f"public config example not found at {toml_path}"

    with toml_path.open("rb") as f:
        data = tomllib.load(f)
    cfg = JarvisConfig.model_validate(data)
    assert cfg.brain.router is None


def test_router_vision_section_is_unmarshalled_into_typed_config():
    """An explicit nested section lands in RouterVisionConfig."""
    cfg = JarvisConfig.model_validate(
        {
            "brain": {
                "router": {
                    "provider": "gemini",
                    "vision": {
                        "enabled": True,
                        "refresh_interval_s": 3.5,
                        "capture_mode": "screenshot",
                    }
                }
            }
        }
    )

    assert isinstance(cfg.brain.router.vision, RouterVisionConfig)
    assert cfg.brain.router.vision.enabled is True
    assert cfg.brain.router.vision.refresh_interval_s == 3.5
