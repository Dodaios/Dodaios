"""The control CLI answers under every one of its names and repeats the one used.

``dodaiosctl`` is the command; ``jarvisctl`` and ``jctl`` are its earlier
names, and ``dodaios <group> ...`` / ``jarvis <group> ...`` route into the same
command tree.
"""

from __future__ import annotations

import sys

import pytest

import jarvis.__main__ as entry
from jarvis import __version__
from jarvis.cli_ctl.__main__ import app, build_root_command
from jarvis.core.branding import CONTROL_CLI_COMMAND_NAME

_NAMES = ["dodaiosctl", "jarvisctl", "jctl", "dodaios", "jarvis"]


def test_the_control_app_is_named_after_the_primary_command() -> None:
    assert app.info.name == CONTROL_CLI_COMMAND_NAME == "dodaiosctl"


@pytest.mark.parametrize("name", _NAMES)
def test_the_version_line_repeats_the_invoked_name(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = build_root_command(["version"])

    root.main(args=["version"], prog_name=name, standalone_mode=False)

    assert capsys.readouterr().out.strip() == f"{name} (Dodaios {__version__})"


@pytest.mark.parametrize("name", _NAMES)
def test_the_usage_line_repeats_the_invoked_name(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = build_root_command(["--help"])

    root.main(args=["--help"], prog_name=name, standalone_mode=False)

    assert f"Usage: {name} [OPTIONS] COMMAND [ARGS]..." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv0", "expected"),
    [("/usr/local/bin/dodaios", "dodaios"), ("/usr/local/bin/jarvis", "jarvis")],
)
def test_a_control_command_through_the_launcher_keeps_the_typed_name(
    argv0: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", [argv0, "version"])

    assert entry._run_control(["version"]) == 0

    assert capsys.readouterr().out.strip() == f"{expected} (Dodaios {__version__})"
