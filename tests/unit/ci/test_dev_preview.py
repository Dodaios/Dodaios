"""`scripts/dev_preview.py`: pull requests run in the Dev app, never in the person's own app."""

from __future__ import annotations

import pytest

from scripts import dev_preview as dp

LAUNCHER = ["DodaiosApp.exe", "-m", "dodaios.ui.web.launcher"]


@pytest.mark.parametrize(
    ("target", "spec"),
    [
        ("1423", "+refs/pull/1423/head:refs/dev-preview/head"),
        ("#1423", "+refs/pull/1423/head:refs/dev-preview/head"),
        ("feat/x", "+refs/heads/feat/x:refs/dev-preview/head"),
        ("main", "+refs/heads/main:refs/dev-preview/head"),
    ],
)
def test_fetch_spec(target: str, spec: str) -> None:
    assert dp.fetch_spec(target) == spec


@pytest.mark.parametrize(
    "cmdline",
    [
        [*LAUNCHER, "--instance", "dev"],
        [*LAUNCHER, "--instance=dev"],
        ["x.exe", "-m", "dodaios.agent_chat.turn_host", "--state", r"C:\x\turn_host.dev.json"],
        ["x.exe", "-m", "dodaios.terminal.pty_host", "--state", "/x/pty_host.dev.json"],
    ],
)
def test_dev_processes_are_recognised(cmdline: list[str]) -> None:
    assert dp.is_dev_process(cmdline)


@pytest.mark.parametrize(
    "cmdline",
    [
        LAUNCHER,
        [*LAUNCHER, "--headless"],
        ["DodaiosApp.exe", "-m", "dodaios.agent_chat.turn_host", "--state", r"C:\x\turn_host.json"],
        ["pythonw.exe", "-m", "dodaios.terminal.pty_host", "--state", "/x/pty_host.json"],
        ["python.exe", "serve.py", "--instance", "dev"],
        [],
    ],
)
def test_default_app_processes_are_never_matched(cmdline: list[str]) -> None:
    assert not dp.is_dev_process(cmdline)
