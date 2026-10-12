"""The restart helper follows the update contract of the tree it installs.

An update is applied by the previous version's helper. These tests prove it
asks the checked-out tree where its UI bundle, launcher, version and config
live instead of assuming its own layout - including the full crossing, run
against a real git checkout whose new release moved the whole package.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.core import instance
from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS
from jarvis.core.update_contract import (
    CONTRACT_PATH,
    CONTRACT_SCHEMA,
    DEFAULT_CONTRACT,
    UpdateContract,
    read_update_contract,
)
from jarvis.ui import desktop_log, relauncher
from jarvis.ui.web import update_routes

REPO = Path(__file__).resolve().parents[3]
GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")
REAL_PLATFORM = sys.platform

MOVED = UpdateContract(
    ui_bundle_dir="pkg_new/ui/web/dist",
    launcher_module="pkg_new.ui.web.launcher",
    version_file="pkg_new/__init__.py",
    config_file="pkg_new.toml",
    macos_app_dir_name="Moved Product.app",
    rollback_hook="install/rollback_hook.py",
)


def _contract_document(contract: UpdateContract) -> str:
    payload: dict[str, object] = {"schema": CONTRACT_SCHEMA}
    for name in (
        "ui_bundle_dir",
        "launcher_module",
        "version_file",
        "config_file",
        "macos_app_dir_name",
        "rollback_hook",
    ):
        value = getattr(contract, name)
        if value is not None:
            payload[name] = value
    return json.dumps(payload, indent=2) + "\n"


def _write_contract(root: Path, contract: UpdateContract) -> None:
    path = root / CONTRACT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_contract_document(contract), encoding="utf-8", newline="\n")


def _write_bundle(root: Path, bundle_dir: str) -> None:
    dist = root.joinpath(*bundle_dir.split("/"))
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(
        '<script type="module" src="/assets/app.js"></script>', encoding="utf-8"
    )
    (dist / "assets" / "app.js").write_text("export {};\n", encoding="utf-8")


@pytest.fixture
def default_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """One fixed instance identity, whatever the developer's shell exports."""
    monkeypatch.setattr(
        instance,
        "current_instance",
        lambda: SimpleNamespace(
            is_default=True,
            launcher_args=(),
            port=lambda base: base,
            windows_branded_launcher_file_name="NoSuchBrandedLauncher.exe",
        ),
    )


# --------------------------------------------------------------------------- #
# Each consumer reads the tree that is on disk
# --------------------------------------------------------------------------- #
def test_bundle_check_looks_where_the_checked_out_tree_says(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_contract(tmp_path, MOVED)
    _write_bundle(tmp_path, MOVED.ui_bundle_dir)
    tracked: list[str] = []

    def _tracked(cmd: list[str], *, root: Path, timeout: float) -> int:
        tracked.append(cmd[-1])
        return 0

    monkeypatch.setattr(relauncher, "_run_update_command", _tracked)

    assert relauncher._ui_bundle_ready(tmp_path) is True
    assert sorted(tracked) == [
        "pkg_new/ui/web/dist/assets/app.js",
        "pkg_new/ui/web/dist/index.html",
    ]


def test_bundle_check_ignores_a_bundle_left_in_the_old_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale bundle where the previous layout kept it proves nothing."""
    _write_contract(tmp_path, MOVED)
    _write_bundle(tmp_path, DEFAULT_CONTRACT.ui_bundle_dir)
    monkeypatch.setattr(relauncher, "_run_update_command", lambda *_a, **_k: 0)

    assert relauncher._ui_bundle_ready(tmp_path) is False


def test_bundle_check_without_a_contract_keeps_the_default_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_bundle(tmp_path, DEFAULT_CONTRACT.ui_bundle_dir)
    tracked: list[str] = []
    monkeypatch.setattr(
        relauncher,
        "_run_update_command",
        lambda cmd, **_k: tracked.append(cmd[-1]) or 0,
    )

    assert relauncher._ui_bundle_ready(tmp_path) is True
    assert "jarvis/ui/web/dist/index.html" in tracked


def test_admin_port_is_read_from_the_config_file_the_tree_names(
    tmp_path: Path, default_instance: None
) -> None:
    (tmp_path / "jarvis.toml").write_text("[ui]\nadmin_api_port = 40001\n", encoding="utf-8")
    (tmp_path / "pkg_new.toml").write_text("[ui]\nadmin_api_port = 40002\n", encoding="utf-8")

    assert relauncher._restart_admin_port(tmp_path) == 40001
    _write_contract(tmp_path, MOVED)
    assert relauncher._restart_admin_port(tmp_path) == 40002


def test_launch_command_starts_the_module_the_tree_names(
    monkeypatch: pytest.MonkeyPatch, default_instance: None
) -> None:
    monkeypatch.setattr(relauncher.sys, "platform", "linux")
    assert relauncher.build_launch_command("python", contract=MOVED) == [
        "python",
        "-m",
        "pkg_new.ui.web.launcher",
    ]
    assert relauncher.build_launch_command("python") == [
        "python",
        "-m",
        "jarvis.ui.web.launcher",
    ]


def test_windows_branded_launcher_runs_the_module_the_tree_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, default_instance: None
) -> None:
    branded = tmp_path / "Branded.exe"
    branded.write_bytes(b"MZ")
    monkeypatch.setattr(relauncher.sys, "platform", "win32")
    monkeypatch.setattr(relauncher, "_existing_branded_launcher", lambda: branded)

    assert relauncher.build_launch_command("python.exe", contract=MOVED) == [
        str(branded),
        "-m",
        "pkg_new.ui.web.launcher",
    ]


def test_macos_restart_opens_the_bundle_the_tree_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, default_instance: None
) -> None:
    import jarvis.setup.macos_app_bundle as bundle_module

    known = tmp_path / "Applications" / relauncher.MACOS_APP_DIR_NAME
    renamed = known.with_name(MOVED.macos_app_dir_name)
    renamed.mkdir(parents=True)
    monkeypatch.setattr(relauncher.sys, "platform", "darwin")
    monkeypatch.setattr(bundle_module, "macos_app_bundle_path", lambda: known)

    def _unexpected(_bundle: Path) -> bool:
        raise AssertionError("a renamed bundle is not validated against the old layout")

    monkeypatch.setattr(bundle_module, "macos_app_bundle_is_launchable", _unexpected)

    assert relauncher.build_launch_command("python3", contract=MOVED) == [
        "/usr/bin/open",
        "-W",
        "-a",
        str(renamed),
    ]


def test_macos_restart_names_the_renamed_bundle_even_before_it_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, default_instance: None
) -> None:
    import jarvis.setup.macos_app_bundle as bundle_module

    known = tmp_path / "Applications" / relauncher.MACOS_APP_DIR_NAME
    monkeypatch.setattr(relauncher.sys, "platform", "darwin")
    monkeypatch.setattr(relauncher.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(bundle_module, "macos_app_bundle_path", lambda: known)

    command = relauncher.build_launch_command("python3", contract=MOVED)

    # Fail closed on the new identity; never fall back to a raw interpreter.
    assert command[:3] == ["/usr/bin/open", "-W", "-a"]
    assert Path(command[3]).name == MOVED.macos_app_dir_name


# --------------------------------------------------------------------------- #
# Rollback hook
# --------------------------------------------------------------------------- #
def _pending(root: Path) -> tuple[str, str]:
    previous, target = "a" * 40, "b" * 40
    (root / ".git").mkdir()
    (root / relauncher.MANAGED_MARKER).write_text("{}\n", encoding="utf-8")
    (root / relauncher.PENDING_UPDATE_FILENAME).write_text(
        json.dumps(
            {
                "schema": 1,
                "previous_revision": previous,
                "target_revision": target,
                "profile": "full",
            }
        ),
        encoding="utf-8",
    )
    return previous, target


def _is_hook_call(cmd: list[str]) -> bool:
    """``<python> <root>/install/rollback_hook.py <previous> <target>``."""
    return len(cmd) == 4 and Path(cmd[1]).name == "rollback_hook.py"


class _FakeCheckout:
    """Stands in for git and the installer; the reset swaps the tree's contract."""

    def __init__(
        self,
        root: Path,
        *,
        target: str,
        target_contract: UpdateContract,
        install_fails: bool,
        hook_tracked: bool = True,
        hook_rc: int = 0,
        target_reset_rc: int = 0,
    ) -> None:
        self.root = root
        self.target = target
        self.target_contract = target_contract
        self.install_fails = install_fails
        self.hook_tracked = hook_tracked
        self.hook_rc = hook_rc
        self.target_reset_rc = target_reset_rc
        self.calls: list[list[str]] = []
        self.on_target = False

    def __call__(self, cmd: list[str], *, root: Path, timeout: float) -> int:
        self.calls.append(cmd)
        if cmd[:3] == ["git", "reset", "--hard"]:
            if cmd[3] == self.target:
                if self.target_reset_rc != 0:
                    return self.target_reset_rc
                self.on_target = True
                _write_contract(self.root, self.target_contract)
                hook = self.target_contract.rollback_hook
                if hook is not None:
                    (self.root / hook).write_text("", encoding="utf-8")
            else:
                self.on_target = False
                (self.root / CONTRACT_PATH).unlink(missing_ok=True)
            return 0
        if cmd[:2] == ["git", "ls-files"]:
            return 0 if self.hook_tracked else 1
        if cmd == ["installer", "full"]:
            return 1 if self.install_fails and self.on_target else 0
        if _is_hook_call(cmd):
            return self.hook_rc
        raise AssertionError(f"unexpected update command {cmd}")

    def hook_calls(self) -> list[list[str]]:
        return [cmd for cmd in self.calls if _is_hook_call(cmd)]


def _finalize_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **options: object
) -> tuple[_FakeCheckout, bool, str, str]:
    previous, target = _pending(tmp_path)
    checkout = _FakeCheckout(
        tmp_path,
        target=target,
        target_contract=options.pop("target_contract", MOVED),  # type: ignore[arg-type]
        **options,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(relauncher, "_run_update_command", checkout)
    monkeypatch.setattr(relauncher, "_ui_bundle_ready", lambda _root: True)
    monkeypatch.setattr(
        relauncher, "_installer_command", lambda _root, profile: ["installer", profile]
    )
    monkeypatch.setattr(relauncher, "_managed_python", lambda _root: "python")
    ok = relauncher.finalize_pending_update(tmp_path)
    return checkout, ok, previous, target


def test_a_successful_update_never_runs_the_rollback_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout, ok, _previous, _target = _finalize_with(
        monkeypatch, tmp_path, install_fails=False
    )
    assert ok is True
    assert checkout.hook_calls() == []


def test_a_failed_install_runs_the_targets_hook_before_the_rollback_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout, ok, previous, target = _finalize_with(monkeypatch, tmp_path, install_fails=True)
    hook = str(tmp_path.resolve() / "install" / "rollback_hook.py")

    assert ok is False
    assert checkout.calls == [
        ["git", "reset", "--hard", target],
        ["installer", "full"],
        ["git", "ls-files", "--error-unmatch", "--", "install/rollback_hook.py"],
        ["python", hook, previous, target],
        ["git", "reset", "--hard", previous],
        ["installer", "full"],
    ]
    result = json.loads(
        (tmp_path / relauncher.UPDATE_RESULT_FILENAME).read_text(encoding="utf-8")
    )
    assert result["ok"] is False
    assert result["rolled_back"] is True


def test_a_failing_hook_never_stops_the_rollback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout, ok, previous, _target = _finalize_with(
        monkeypatch, tmp_path, install_fails=True, hook_rc=-1
    )
    assert ok is False
    assert len(checkout.hook_calls()) == 1
    assert ["git", "reset", "--hard", previous] in checkout.calls
    result = json.loads(
        (tmp_path / relauncher.UPDATE_RESULT_FILENAME).read_text(encoding="utf-8")
    )
    assert result["rolled_back"] is True


def test_a_hook_the_release_does_not_track_is_never_executed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout, ok, previous, _target = _finalize_with(
        monkeypatch, tmp_path, install_fails=True, hook_tracked=False
    )
    assert ok is False
    assert checkout.hook_calls() == []
    assert ["git", "reset", "--hard", previous] in checkout.calls


def test_a_release_without_a_hook_rolls_back_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout, ok, previous, target = _finalize_with(
        monkeypatch, tmp_path, install_fails=True, target_contract=DEFAULT_CONTRACT
    )
    assert ok is False
    assert checkout.calls == [
        ["git", "reset", "--hard", target],
        ["installer", "full"],
        ["git", "reset", "--hard", previous],
        ["installer", "full"],
    ]


def test_no_hook_runs_when_the_target_was_never_checked_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A hook left on disk by anything else is not the target's to run."""
    _write_contract(tmp_path, MOVED)
    checkout, ok, previous, target = _finalize_with(
        monkeypatch, tmp_path, install_fails=False, target_reset_rc=1
    )
    assert ok is False
    assert checkout.calls == [
        ["git", "reset", "--hard", target],
        ["git", "reset", "--hard", previous],
        ["installer", "full"],
    ]


# --------------------------------------------------------------------------- #
# The helper's relaunch command follows what ended up installed
# --------------------------------------------------------------------------- #
def _run_main(
    monkeypatch: pytest.MonkeyPatch, root: Path, finalize: object
) -> list[list[str]]:
    monkeypatch.setattr(relauncher.sys, "platform", "linux")
    monkeypatch.setattr(relauncher.sys, "executable", "python")
    monkeypatch.setattr(relauncher, "fresh_user_env", lambda: {})
    monkeypatch.setattr(desktop_log, "_install_desktop_log_sink", lambda _path: None)
    spawned: list[list[str]] = []
    rc = relauncher.main(
        ["123", str(root)],
        _spawn=lambda cmd, **_kw: spawned.append(cmd) or SimpleNamespace(pid=456),
        _alive=lambda _pid: False,
        _sleep=lambda _seconds: None,
        _serving=lambda: True,
        _finalize_update=finalize,
    )
    assert rc == 0
    return spawned


def test_main_relaunches_through_the_launcher_of_the_installed_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, default_instance: None
) -> None:
    def _finalize(cwd: str) -> bool:
        # The finalizer just checked out a release that moved its package.
        _write_contract(Path(cwd), MOVED)
        return True

    assert _run_main(monkeypatch, tmp_path, _finalize) == [
        ["python", "-m", "pkg_new.ui.web.launcher"]
    ]


def test_main_keeps_the_known_launcher_when_nothing_was_updated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, default_instance: None
) -> None:
    assert _run_main(monkeypatch, tmp_path, lambda _cwd: True) == [
        ["python", "-m", "jarvis.ui.web.launcher"]
    ]


# --------------------------------------------------------------------------- #
# The crossing, against a real checkout
# --------------------------------------------------------------------------- #
FAKE_INSTALLER = """import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
(root / ".installer-ran").write_text(" ".join(sys.argv[1:]), encoding="utf-8")
raise SystemExit(1 if (root / ".fail-install").exists() and FAILS_ON_REQUEST else 0)
"""

FAKE_HOOK = """import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
state = "new-tree" if (root / "pkg_new" / "__init__.py").is_file() else "other-tree"
(root / ".hook-ran").write_text(" ".join([state, *sys.argv[1:]]), encoding="utf-8")
"""


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(  # noqa: S603 - test-controlled command
        [str(GIT), "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _commit(root: Path, message: str) -> str:
    # Forced: a developer's global ignore file commonly lists ``dist``.
    _git(root, "add", "-A", "--force")
    _git(
        root,
        "-c",
        "user.name=Update Test",
        "-c",
        "user.email=update-test@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        message,
    )
    return _git(root, "rev-parse", "HEAD")


def _write_package(root: Path, package: str, version: str) -> None:
    (root / package / "ui" / "web").mkdir(parents=True)
    (root / package / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8", newline="\n"
    )
    _write_bundle(root, f"{package}/ui/web/dist")


def _write_installer(root: Path, *, fails_on_request: bool) -> None:
    (root / "install").mkdir(exist_ok=True)
    (root / "install" / "installer.py").write_text(
        FAKE_INSTALLER.replace("FAILS_ON_REQUEST", repr(fails_on_request)),
        encoding="utf-8",
        newline="\n",
    )


class _Crossing:
    """A managed checkout sitting on ``old`` with ``new`` staged as an update."""

    def __init__(self, root: Path, old_package: str, old: str, new: str) -> None:
        self.root = root
        self.old_package = old_package
        self.old = old
        self.new = new

    def head(self) -> str:
        return _git(self.root, "rev-parse", "HEAD")

    def result(self) -> dict[str, object]:
        return json.loads(
            (self.root / relauncher.UPDATE_RESULT_FILENAME).read_text(encoding="utf-8")
        )


@pytest.fixture(params=["jarvis", "pkg_old"])
def crossing(request: pytest.FixtureRequest, tmp_path: Path) -> _Crossing:
    """``old`` keeps its package at the default place without a contract, or
    elsewhere with one; ``new`` moved everything to ``pkg_new``."""
    old_package: str = request.param
    root = tmp_path / "install"
    root.mkdir()
    _git(root, "init", "--quiet")
    # Line endings and hooks of the developer's machine must not decide what
    # this checkout tracks.
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "core.hooksPath", str(root / ".git" / "no-hooks"))

    _write_package(root, old_package, "1.0.0")
    _write_installer(root, fails_on_request=False)
    if old_package != "jarvis":
        _write_contract(
            root,
            UpdateContract(
                ui_bundle_dir=f"{old_package}/ui/web/dist",
                launcher_module=f"{old_package}.ui.web.launcher",
                version_file=f"{old_package}/__init__.py",
            ),
        )
    old = _commit(root, "old release")

    shutil.rmtree(root / old_package)
    _write_package(root, "pkg_new", "2.0.0")
    _write_installer(root, fails_on_request=True)
    (root / "install" / "rollback_hook.py").write_text(FAKE_HOOK, encoding="utf-8", newline="\n")
    _write_contract(root, MOVED)
    new = _commit(root, "new release moves the package")

    _git(root, "reset", "--quiet", "--hard", old)
    (root / relauncher.MANAGED_MARKER).write_text("{}\n", encoding="utf-8")
    (root / relauncher.PENDING_UPDATE_FILENAME).write_text(
        json.dumps(
            {
                "schema": 1,
                "previous_revision": old,
                "target_revision": new,
                "profile": "full",
            }
        ),
        encoding="utf-8",
    )
    return _Crossing(root, old_package, old, new)


def _recording_real_commands(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Run every update command for real, and keep what was run."""
    calls: list[list[str]] = []
    real = relauncher._run_update_command

    def _run(cmd: list[str], *, root: Path, timeout: float) -> int:
        calls.append(list(cmd))
        return real(cmd, root=root, timeout=timeout)

    monkeypatch.setattr(relauncher, "_run_update_command", _run)
    return calls


def _finalize_on_the_real_platform(monkeypatch: pytest.MonkeyPatch) -> object:
    """The finalizer spawns real processes, so it must see the real OS."""

    def _finalize(cwd: str) -> bool:
        with monkeypatch.context() as scoped:
            scoped.setattr(relauncher.sys, "platform", REAL_PLATFORM)
            scoped.setattr(relauncher.sys, "executable", sys.executable)
            return relauncher.finalize_pending_update(cwd)

    return _finalize


@needs_git
def test_crossing_installs_a_release_that_moved_its_package(
    monkeypatch: pytest.MonkeyPatch, crossing: _Crossing, default_instance: None
) -> None:
    root = crossing.root
    (root / "pkg_new.toml").write_text("[ui]\nadmin_api_port = 40123\n", encoding="utf-8")
    calls = _recording_real_commands(monkeypatch)

    spawned = _run_main(monkeypatch, root, _finalize_on_the_real_platform(monkeypatch))

    assert crossing.head() == crossing.new
    assert crossing.result()["ok"] is True
    assert not (root / relauncher.PENDING_UPDATE_FILENAME).exists()
    # The TARGET tree's installer ran, with the staged profile.
    assert (root / ".installer-ran").read_text(encoding="utf-8") == "--no-launch --with-desktop"
    # The bundle was verified where the new tree keeps it ...
    tracked = [cmd[-1] for cmd in calls if cmd[:2] == ["git", "ls-files"]]
    assert sorted(tracked) == [
        "pkg_new/ui/web/dist/assets/app.js",
        "pkg_new/ui/web/dist/index.html",
    ]
    # ... the app comes back through the new tree's launcher ...
    assert spawned == [["python", "-m", "pkg_new.ui.web.launcher"]]
    # ... and its port is read from the config file the new tree names.
    assert relauncher._restart_admin_port(root) == 40123
    assert not (root / ".hook-ran").exists()


@needs_git
def test_crossing_rolls_back_through_the_hook_to_the_old_tree(
    monkeypatch: pytest.MonkeyPatch, crossing: _Crossing, default_instance: None
) -> None:
    root = crossing.root
    (root / ".fail-install").write_text("", encoding="utf-8")
    calls = _recording_real_commands(monkeypatch)

    spawned = _run_main(monkeypatch, root, _finalize_on_the_real_platform(monkeypatch))

    assert crossing.head() == crossing.old
    result = crossing.result()
    assert result["ok"] is False
    assert result["rolled_back"] is True

    # The hook belonged to the new tree and ran while that tree was still
    # checked out, with both revisions, before the checkout went back.
    assert (root / ".hook-ran").read_text(encoding="utf-8") == (
        f"new-tree {crossing.old} {crossing.new}"
    )
    hook_at = next(index for index, cmd in enumerate(calls) if _is_hook_call(cmd))
    back_at = calls.index(["git", "reset", "--hard", crossing.old])
    assert hook_at < back_at

    # After the rollback the OLD tree's layout is what gets verified and started.
    tracked_after = [cmd[-1] for cmd in calls[back_at:] if cmd[:2] == ["git", "ls-files"]]
    assert sorted(tracked_after) == [
        f"{crossing.old_package}/ui/web/dist/assets/app.js",
        f"{crossing.old_package}/ui/web/dist/index.html",
    ]
    assert spawned == [["python", "-m", f"{crossing.old_package}.ui.web.launcher"]]
    assert read_update_contract(root).rollback_hook is None


@needs_git
def test_crossing_refuses_a_release_whose_bundle_is_not_where_it_says(
    monkeypatch: pytest.MonkeyPatch, crossing: _Crossing, default_instance: None
) -> None:
    """The contract is checked, not believed: no bundle there, no update."""
    root = crossing.root
    marker = root / relauncher.MANAGED_MARKER
    pending = root / relauncher.PENDING_UPDATE_FILENAME
    payload = json.loads(pending.read_text(encoding="utf-8"))
    # Out of the way while the broken release is committed, so the install's
    # own untracked files do not become part of it.
    marker.unlink()
    pending.unlink()
    _git(root, "reset", "--quiet", "--hard", crossing.new)
    _write_contract(root, replace(MOVED, ui_bundle_dir="pkg_new/elsewhere"))
    broken = _commit(root, "new release with a wrong bundle location")
    _git(root, "reset", "--quiet", "--hard", crossing.old)
    marker.write_text("{}\n", encoding="utf-8")
    payload["target_revision"] = broken
    pending.write_text(json.dumps(payload), encoding="utf-8")

    spawned = _run_main(monkeypatch, root, _finalize_on_the_real_platform(monkeypatch))

    assert crossing.head() == crossing.old
    assert crossing.result()["rolled_back"] is True
    assert spawned == [["python", "-m", f"{crossing.old_package}.ui.web.launcher"]]


@needs_git
async def test_crossing_reads_each_revisions_version_from_its_own_version_file(
    crossing: _Crossing,
) -> None:
    """The staging step must agree with the release before anything is reset."""
    assert await update_routes._version_at_revision(crossing.root, crossing.new) == "2.0.0"
    assert await update_routes._version_at_revision(crossing.root, crossing.old) == "1.0.0"
    # The checkout still holds the old tree, and is read by ITS contract.
    assert update_routes._version_on_disk(crossing.root) == "1.0.0"


# --------------------------------------------------------------------------- #
# Nothing is imported from the package after the checkout changed
# --------------------------------------------------------------------------- #
IMPORT_GUARD_DRIVER = r'''
import asyncio  # noqa: F401 - loaded for the real OS before it is disguised
import ctypes  # noqa: F401
import importlib.abc
import json
import logging  # noqa: F401
import socket  # noqa: F401
import subprocess  # noqa: F401
import sys
from pathlib import Path
from types import SimpleNamespace

try:
    import loguru  # noqa: F401
except ImportError:
    pass

simulated, workdir, preload = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
if simulated != "native":
    # Standard-library and third-party modules above were imported for the
    # real OS. Only the package under test sees the simulated one.
    sys.platform = simulated

from jarvis.ui import relauncher

if preload == "skip":
    relauncher._load_modules_needed_after_update = lambda: None


class PackageIsGone(importlib.abc.MetaPathFinder):
    """After the reset the old package is no longer on disk: refuse and record."""

    def __init__(self):
        self.late = []

    def find_spec(self, name, path=None, target=None):
        if name == "jarvis" or name.startswith("jarvis."):
            self.late.append(name)
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None


guard = PackageIsGone()
root = workdir / "install"
(root / ".git").mkdir(parents=True)
(root / relauncher.MANAGED_MARKER).write_text("{}\n", encoding="utf-8")
(root / relauncher.PENDING_UPDATE_FILENAME).write_text(
    json.dumps(
        {
            "schema": 1,
            "previous_revision": "a" * 40,
            "target_revision": "b" * 40,
            "profile": "full",
        }
    ),
    encoding="utf-8",
)
contract = json.loads(sys.argv[4])
loaded_at_reset = []


def run_update_command(cmd, *, root, timeout):
    if cmd[:3] == ["git", "reset", "--hard"] and guard not in sys.meta_path:
        # From here on the checkout holds a release that moved its package.
        loaded_at_reset.extend(sorted(m for m in sys.modules if m.split(".")[0] == "jarvis"))
        (root / "install").mkdir(exist_ok=True)
        (root / "install" / "update-contract.json").write_text(
            json.dumps(contract), encoding="utf-8"
        )
        dist = root.joinpath(*contract["ui_bundle_dir"].split("/"))
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text(
            '<script type="module" src="/assets/app.js"></script>', encoding="utf-8"
        )
        (dist / "assets" / "app.js").write_text("export {};\n", encoding="utf-8")
        sys.meta_path.insert(0, guard)
    return 0


relauncher._run_update_command = run_update_command
relauncher._installer_command = lambda _root, profile: ["installer", profile]

spawned = []
dialogs = []


def spawn(cmd, **_kwargs):
    spawned.append(list(cmd))
    # Reached through sys.modules on purpose: importing here would load the
    # very modules this run is checking for.
    process_utils = sys.modules.get("jarvis.core.process_utils")
    if process_utils is not None:
        process_utils.standard_error_is_visible = lambda: False
    native_dialog = sys.modules.get("jarvis.ui.native_dialog")
    if native_dialog is not None:
        native_dialog.show_error_dialog = lambda title, message: dialogs.append(title)
    return SimpleNamespace(pid=4321)


ports = []


def serving():
    ports.append(relauncher._restart_admin_port(root))
    return False


common = dict(
    _wait=lambda _pid, **_kw: True,
    _spawn=spawn,
    _sleep=lambda _seconds: None,
    _alive=lambda pid: pid != 4242,
    _serving=serving,
)
came_back = relauncher.main(["4242", str(root)], **common)
never_settled = relauncher.main(
    ["4242", str(root)], _settled=lambda *_a, **_kw: False, **common
)
print(
    "RESULT "
    + json.dumps(
        {
            "came_back": came_back,
            "never_settled": never_settled,
            "late": guard.late,
            "guard_installed": guard in sys.meta_path,
            "spawned": spawned,
            "dialogs": dialogs,
            "ports": ports,
            "loaded_at_reset": loaded_at_reset,
        }
    )
)
'''


def _run_import_guard(tmp_path: Path, simulated: str, *, preload: str = "keep") -> dict:
    env = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("JARVIS")
    }
    # The helper logs to the desktop log; keep that inside the test directory.
    env["JARVIS_DATA_DIR"] = str(tmp_path / "data")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(  # noqa: S603 - this interpreter, test-controlled script
        [
            sys.executable,
            "-c",
            IMPORT_GUARD_DRIVER,
            simulated,
            str(tmp_path),
            preload,
            json.dumps(json.loads(_contract_document(MOVED))),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(REPO),
        env=env,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [line for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(lines[-1].removeprefix("RESULT "))


def _simulated_platforms() -> list[str]:
    # The native run exercises this OS for real. The others re-run the same
    # helper with ``sys.platform`` swapped, which reaches every branch except
    # the Windows registry read (``winreg`` exists on Windows only).
    return ["native", *(name for name in ("darwin", "linux") if name != REAL_PLATFORM)]


@pytest.mark.parametrize("simulated", _simulated_platforms())
def test_no_package_module_is_imported_after_the_checkout_changed(
    tmp_path: Path, simulated: str
) -> None:
    """Once the tree is reset, the old package may no longer exist on disk.

    A fresh interpreter runs the helper end to end. From the first
    ``git reset`` on, any import of a not-yet-loaded ``jarvis`` module fails
    the way it would after the package moved - and is recorded. The helper
    must still bring the app back, report a failed restart, and resolve the
    admin port, all from modules it loaded beforehand.
    """
    outcome = _run_import_guard(tmp_path, simulated)

    assert outcome["guard_installed"] is True
    assert outcome["late"] == []
    assert outcome["came_back"] == 0
    # Three failed attempts end in the failure report, which needs the dialog.
    assert outcome["never_settled"] == 1
    assert len(outcome["dialogs"]) == 1
    assert outcome["ports"], "the admin-port probe never ran"
    assert {
        "jarvis.core.frozen",
        "jarvis.core.instance",
        "jarvis.core.process_utils",
        "jarvis.ui.native_dialog",
    } <= set(outcome["loaded_at_reset"])
    platform_name = REAL_PLATFORM if simulated == "native" else simulated
    if platform_name == "darwin":
        assert "jarvis.setup.macos_app_bundle" in outcome["loaded_at_reset"]
        assert outcome["spawned"][0][-1].endswith(MOVED.macos_app_dir_name)
    else:
        assert outcome["spawned"][0][1:3] == ["-m", MOVED.launcher_module]


def test_the_guard_notices_a_module_that_was_not_loaded_in_time(tmp_path: Path) -> None:
    """Without the up-front load, the failure report imports from the new tree."""
    outcome = _run_import_guard(tmp_path, "native", preload="skip")

    assert "jarvis.ui.native_dialog" in outcome["late"] or (
        "jarvis.core.process_utils" in outcome["late"]
    )
    assert outcome["dialogs"] == []
