"""The system trash: send2trash when installed, the Windows shell otherwise."""

from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest

from dodaios.agentic_ide import system_trash


@pytest.fixture
def no_send2trash(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "send2trash":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_without_the_package_windows_uses_the_shell(
    no_send2trash: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recycled: list[Path] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        system_trash, "_windows_recycle", lambda target: recycled.append(target) or True
    )
    assert system_trash.move_to_trash(tmp_path / "a.txt") is True
    assert recycled == [tmp_path / "a.txt"]


def test_a_refusing_recycle_bin_is_an_error(
    no_send2trash: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(system_trash, "_windows_recycle", lambda target: False)
    with pytest.raises(OSError):
        system_trash.move_to_trash(tmp_path / "a.txt")


def test_without_the_package_elsewhere_there_is_no_trash(
    no_send2trash: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert system_trash.move_to_trash(tmp_path / "a.txt") is False
