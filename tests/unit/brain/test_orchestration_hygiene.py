"""Hygiene: inert harness config and registry misses log once, not per rebuild."""
from __future__ import annotations

import logging
import re
import types
from pathlib import Path

from dodaios.brain import factory


def _harness_cfg() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        harness=types.SimpleNamespace(jarvis_agent=types.SimpleNamespace(enabled=True))
    )


def test_phantom_harness_is_one_info_line(monkeypatch, caplog) -> None:
    monkeypatch.setattr(factory, "_PHANTOM_HARNESS_REPORTED", False)
    manager = types.SimpleNamespace(available=lambda: ["python-script", "screenshot"])
    with caplog.at_level(logging.DEBUG):
        assert factory.warn_if_phantom_worker_harness(_harness_cfg(), manager) is True
        assert factory.warn_if_phantom_worker_harness(_harness_cfg(), manager) is True
    records = [r for r in caplog.records if "not a registered" in r.getMessage()]
    assert len(records) <= 1
    assert all(r.levelno < logging.WARNING for r in records)


def test_unknown_spawn_fallback_warns_once(monkeypatch, caplog) -> None:
    monkeypatch.setattr(factory, "_REPORTED_MISSING_FALLBACKS", set())
    cfg = types.SimpleNamespace(provider="gemini", fallback_provider="no-such-provider")
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            assert factory._build_spawn_fallback(cfg) == (None, None)
    hits = [r for r in caplog.records if "not in REGISTRY" in r.getMessage()]
    assert len(hits) == 1


def test_multi_spawn_enum_lists_only_registered_harnesses() -> None:
    from dodaios.plugins.tool.multi_spawn import MultiSpawnTool

    root = Path(__file__).resolve().parents[3]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    block = text.split('[project.entry-points."jarvis.harness"]', 1)[1].split("\n[", 1)[0]
    registered = set(re.findall(r"^([\w-]+)\s*=", block, flags=re.M))
    advertised = set(MultiSpawnTool.schema["properties"]["harness"]["enum"])
    assert advertised and advertised <= registered
