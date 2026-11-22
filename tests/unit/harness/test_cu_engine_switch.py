"""The Computer-Use engine setting ([computer_use].engine).

Every value, the retired "current", "june13" and "stable" included, routes a
live mission to the guarded v2 engine; a config error falls back to it too.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import dodaios.plugins.harness.computer_use as harness

# --- selector: [computer_use].engine picks the right module -------------------


def _patch_engine(monkeypatch, value: str) -> None:
    monkeypatch.setattr(
        "dodaios.core.config.load_config",
        lambda: SimpleNamespace(computer_use=SimpleNamespace(engine=value)),
    )


def test_selector_routes_june13_to_guarded_v2(monkeypatch):
    _patch_engine(monkeypatch, "june13")
    loop = harness._resolve_run_cu_loop()
    assert loop.__module__ == "dodaios.cu.engine"


def test_selector_routes_current_to_guarded_v2(monkeypatch):
    _patch_engine(monkeypatch, "current")
    loop = harness._resolve_run_cu_loop()
    assert loop.__module__ == "dodaios.cu.engine"


def test_selector_picks_v2_when_configured(monkeypatch):
    _patch_engine(monkeypatch, "v2")
    loop = harness._resolve_run_cu_loop()
    assert loop.__module__ == "dodaios.cu.engine"


def test_selector_refuses_unguarded_legacy_engines_on_macos(monkeypatch):
    _patch_engine(monkeypatch, "current")
    monkeypatch.setattr(harness.sys, "platform", "darwin")

    loop = harness._resolve_run_cu_loop()

    assert loop.__module__ == "dodaios.cu.engine"


def test_selector_routes_stable_to_guarded_v2(monkeypatch):
    _patch_engine(monkeypatch, "stable")
    loop = harness._resolve_run_cu_loop()
    assert loop.__module__ == "dodaios.cu.engine"


def test_selector_falls_back_to_default_engine_on_config_error(monkeypatch):
    # The default engine is v2 since the rebuild; a config-read failure must
    # land on the same default, never on an older engine.
    def _boom() -> Any:
        raise RuntimeError("config unreadable")

    monkeypatch.setattr("dodaios.core.config.load_config", _boom)
    loop = harness._resolve_run_cu_loop()
    assert loop.__module__ == "dodaios.cu.engine"
