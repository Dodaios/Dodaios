"""The user-level Stop hook launcher runs the gate of a registered checkout only.

``scripts/agent_done_gate_launcher.py`` is copied into the user's home and
fires for every Codex and Kimi session, in whatever folder that session runs.
It must therefore never run a file of the session's own folder: only the gate
of a checkout the person registered with ``scripts/install_agent_done_gate.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import agent_done_gate_launcher as launcher
from scripts import install_agent_done_gate as install

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPO_ROOT / "scripts" / "agent_done_gate_launcher.py"
# Where the installed launcher keeps its files in the user's home: a contract
# between the copy in the home and every later installer run.
FOLDER = ".agent-done-gate"
REGISTRY = "repos.json"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _gate_script(marker: Path, word: str) -> str:
    """A stand-in gate: it only records that it ran, and how it was called."""
    return (
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text("
        f"{word!r} + ' ' + ' '.join(sys.argv[1:]), encoding='utf-8')\n"
    )


def _repository(root: Path, marker: Path, word: str) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "ci@example.invalid")
    _git(root, "config", "user.name", "ci")
    (root / "scripts").mkdir()
    (root / "scripts" / "agent_done_gate.py").write_text(
        _gate_script(marker, word), encoding="utf-8"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "gate")
    return root


def _fire(home: Path, cwd: Path, dialect: str = "codex") -> subprocess.CompletedProcess[str]:
    """Run the launcher the way a CLI's Stop hook does."""
    env = {**os.environ, "AGENT_DONE_GATE_HOME": str(home)}
    return subprocess.run(
        [sys.executable, str(LAUNCHER), dialect],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


def _register(home: Path, *checkouts: Path) -> None:
    folder = home / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / REGISTRY).write_text(
        json.dumps({"repos": [str(path) for path in checkouts]}), encoding="utf-8"
    )


def test_the_gate_of_an_unregistered_repository_is_never_run(tmp_path: Path) -> None:
    marker = tmp_path / "ran.txt"
    foreign = _repository(tmp_path / "foreign", marker, "foreign")

    done = _fire(tmp_path / "home", foreign)

    assert done.returncode == 0
    assert done.stdout == ""
    assert not marker.exists(), "a repository nobody registered had its script run"
    log = (tmp_path / "home" / FOLDER / "hook.log").read_text(encoding="utf-8")
    assert "not registered" in log


def test_a_registered_checkout_runs_its_gate_for_itself(tmp_path: Path) -> None:
    marker = tmp_path / "ran.txt"
    checkout = _repository(tmp_path / "checkout", marker, "primary")
    _register(tmp_path / "home", checkout)

    done = _fire(tmp_path / "home", checkout, "kimi")

    assert done.returncode == 0
    words = marker.read_text(encoding="utf-8").split()
    assert words[:3] == ["primary", "--hook", "kimi"]
    assert words[3] == "--cwd"


def test_a_linked_worktree_is_checked_by_its_checkout_never_by_its_own_copy(
    tmp_path: Path,
) -> None:
    """A worktree may hold anyone's branch; the script that runs is the checkout's."""
    marker = tmp_path / "ran.txt"
    other = tmp_path / "worktree-ran.txt"
    checkout = _repository(tmp_path / "checkout", marker, "primary")
    worktree = tmp_path / "linked"
    _git(checkout, "worktree", "add", "-q", "-b", "topic", str(worktree))
    (worktree / "scripts" / "agent_done_gate.py").write_text(
        _gate_script(other, "worktree"), encoding="utf-8"
    )
    _register(tmp_path / "home", checkout)

    done = _fire(tmp_path / "home", worktree)

    assert done.returncode == 0
    assert not other.exists(), "the worktree's own copy of the gate ran"
    words = marker.read_text(encoding="utf-8").split(" ", 4)
    assert words[:4] == ["primary", "--hook", "codex", "--cwd"]
    assert os.path.samefile(words[4], worktree)


def test_a_folder_outside_any_repository_is_left_alone(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    _register(tmp_path / "home", tmp_path / "elsewhere")

    done = _fire(tmp_path / "home", plain)

    assert (done.returncode, done.stdout) == (0, "")


def test_a_broken_registry_registers_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_DONE_GATE_HOME", str(tmp_path))
    folder = tmp_path / launcher.MARKER
    folder.mkdir()
    for text in ("not json", "[]", '{"repos": "C:/x"}', '{"repos": [7, null, ""]}'):
        (folder / launcher.REGISTRY_NAME).write_text(text, encoding="utf-8")
        assert launcher.registered() == set()


# --------------------------------------------------------------------------
# The installer
# --------------------------------------------------------------------------


@pytest.fixture
def machine(tmp_path: Path, monkeypatch) -> Path:
    """A home folder of its own and a checkout with a linked worktree to install from."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGENT_DONE_GATE_HOME", str(home))
    checkout = _repository(tmp_path / "checkout", tmp_path / "ran.txt", "primary")
    shutil.copyfile(LAUNCHER, checkout / "scripts" / "agent_done_gate_launcher.py")
    worktree = tmp_path / "linked"
    _git(checkout, "worktree", "add", "-q", "-b", "topic", str(worktree))
    shutil.copyfile(LAUNCHER, worktree / "scripts" / "agent_done_gate_launcher.py")
    # The installer is run from the linked worktree: the harder case.
    monkeypatch.setattr(install, "REPO_ROOT", worktree)
    return tmp_path


def _registry(machine: Path) -> list[str]:
    path = machine / "home" / install.MARKER / install.REGISTRY_NAME
    return json.loads(path.read_text(encoding="utf-8"))["repos"]


def test_installing_registers_the_primary_checkout_and_stays_the_same_when_repeated(
    machine: Path, capsys
) -> None:
    assert install.main([]) == 0
    first = capsys.readouterr().out
    repos = _registry(machine)
    assert [install.same_path(item) for item in repos] == [
        install.same_path(machine / "checkout")
    ], "a run from a linked worktree registers the checkout it belongs to"
    assert "checkout registered" in first
    installed = machine / "home" / install.MARKER / "hook.py"
    assert installed.read_bytes() == LAUNCHER.read_bytes()

    assert install.main([]) == 0
    assert "already registered" in capsys.readouterr().out
    assert _registry(machine) == repos


def test_installing_over_a_setup_from_before_the_registry_migrates_it(
    machine: Path, capsys
) -> None:
    """The machine had the launcher that ran any repository's gate, and no registry."""
    folder = machine / "home" / install.MARKER
    folder.mkdir()
    (folder / "hook.py").write_text("# the earlier launcher\n", encoding="utf-8")
    codex = machine / "home" / ".codex"
    codex.mkdir()
    stop = {"type": "command", "command": install.hook_command("codex"), "timeout": 600}
    other = {"type": "command", "command": "someone else's hook"}
    hooks = {"hooks": {"Stop": [{"hooks": [other]}, {"hooks": [stop]}]}}
    (codex / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
    before = (codex / "hooks.json").read_text(encoding="utf-8")

    assert install.main(["--check"]) == 0
    report = capsys.readouterr().out
    assert "missing or stale" in report and "NOT registered" in report
    assert not (folder / install.REGISTRY_NAME).exists(), "--check writes nothing"

    assert install.main([]) == 0
    assert (folder / "hook.py").read_bytes() == LAUNCHER.read_bytes()
    assert len(_registry(machine)) == 1
    assert (codex / "hooks.json").read_text(encoding="utf-8") == before
    assert install.main(["--check"]) == 0
    report = capsys.readouterr().out
    assert "launcher current" in report and "checkout registered" in report


def test_the_installed_launcher_runs_the_registered_gate_end_to_end(machine: Path) -> None:
    assert install.main([]) == 0
    home = machine / "home"
    installed = home / install.MARKER / "hook.py"
    env = {**os.environ, "AGENT_DONE_GATE_HOME": str(home)}

    subprocess.run(
        [sys.executable, str(installed), "codex"],
        input=json.dumps({"cwd": str(machine / "linked")}),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=True,
    )

    assert (machine / "ran.txt").read_text(encoding="utf-8").startswith("primary --hook codex")


def test_uninstalling_takes_the_registration_away(machine: Path, capsys) -> None:
    assert install.main([]) == 0
    other = machine / "another-checkout"
    install.register(other)
    assert len(_registry(machine)) == 2

    assert install.main(["--uninstall"]) == 0

    assert [install.same_path(item) for item in _registry(machine)] == [install.same_path(other)]
    assert not (machine / "home" / install.MARKER / "hook.py").exists()
    install.unregister(other)
    assert not (machine / "home" / install.MARKER / install.REGISTRY_NAME).exists()


def test_launcher_and_installer_agree_on_where_the_registry_is() -> None:
    assert (launcher.MARKER, launcher.REGISTRY_NAME) == (FOLDER, REGISTRY)
    assert (install.MARKER, install.REGISTRY_NAME) == (FOLDER, REGISTRY)
