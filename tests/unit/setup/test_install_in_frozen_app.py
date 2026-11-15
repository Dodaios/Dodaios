"""The in-app package install inside a desktop-installer build.

Those builds freeze Python into the app, so ``sys.executable`` is the app
itself. Running it with ``-m pip`` would start a second app, not an installer.
"""

from __future__ import annotations

import sys

import pytest

from dodaios.setup import dependencies as deps


def test_a_frozen_app_refuses_instead_of_starting_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        deps.subprocess, "run", lambda cmd, **_kw: started.append(cmd)
    )

    ok, message = deps.install_pip_package("sherpa-onnx>=1.13.3,<2", only_binary=True)

    assert ok is False
    assert started == []
    assert "install Dodaios again" in message


def test_a_repair_replaces_the_installed_package() -> None:
    plain = deps._pip_install_cmd("sherpa-onnx", only_binary=True)
    repair = deps._pip_install_cmd("sherpa-onnx", only_binary=True, force_reinstall=True)

    assert "--force-reinstall" not in plain
    assert "--force-reinstall" in repair
    assert repair[-1] == "sherpa-onnx"
