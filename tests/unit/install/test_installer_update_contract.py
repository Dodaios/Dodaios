"""Installer contracts reused by the post-exit in-app updater."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.package_names import is_package_module

REPO = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "installer_update_contract", REPO / "install" / "installer.py"
)
assert _SPEC is not None and _SPEC.loader is not None
installer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(installer)


@pytest.mark.parametrize(
    ("with_desktop", "profile"),
    ((True, "full"), (False, "headless")),
)
def test_managed_marker_persists_install_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    with_desktop: bool,
    profile: str,
) -> None:
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    installer.write_managed_marker(with_desktop=with_desktop)

    payload = json.loads(
        (tmp_path / ".jarvis-managed-install").read_text(encoding="utf-8")
    )
    assert payload["profile"] == profile
    assert payload["desktop"] is with_desktop


def test_managed_marker_is_written_under_every_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # An updater from before the rename knows only the earlier name.
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    installer.write_managed_marker(with_desktop=True)

    names = (".dodaios-managed-install", ".jarvis-managed-install")
    payloads = [json.loads((tmp_path / name).read_text(encoding="utf-8")) for name in names]
    assert payloads[0] == payloads[1]
    assert payloads[0]["install_path"] == str(tmp_path)


@pytest.mark.parametrize(
    "present", [(), (".dodaios-managed-install",), (".jarvis-managed-install",)]
)
def test_an_update_run_is_recognised_by_either_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, present: tuple[str, ...]
) -> None:
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    for name in present:
        (tmp_path / name).write_text("{}", encoding="utf-8")

    assert installer.is_update_run() is bool(present)


def test_desktop_dependency_plan_is_complete_and_verified(capsys) -> None:
    installer.step_pip_install(
        with_desktop=True,
        with_voice_local=False,
        dry_run=True,
    )
    output = capsys.readouterr().out
    assert "--require-hashes" in output
    assert ".[full]" in output
    assert "dependency consistency check" in output


def test_metadata_repair_removes_only_incomplete_records(tmp_path: Path) -> None:
    valid = tmp_path / "example-1.0.dist-info"
    valid.mkdir()
    (valid / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: example\nVersion: 1.0\n",
        encoding="utf-8",
    )
    broken = tmp_path / "old_update-0.9.dist-info"
    broken.mkdir()
    (broken / "RECORD").write_text("", encoding="utf-8")
    licenses = broken / "licenses"
    licenses.mkdir()
    license_file = licenses / "LICENSE.txt"
    license_file.write_text("legacy license\n", encoding="utf-8")
    os.chmod(license_file, stat.S_IREAD)
    os.chmod(licenses, stat.S_IREAD)
    os.chmod(broken, stat.S_IREAD)

    assert installer.repair_distribution_metadata(site_packages=tmp_path) is True
    assert valid.is_dir()
    assert not broken.exists()


def test_metadata_repair_dry_run_does_not_remove_records(tmp_path: Path) -> None:
    broken = tmp_path / "old_update-0.9.dist-info"
    broken.mkdir()

    assert installer.repair_distribution_metadata(
        site_packages=tmp_path, dry_run=True
    ) is True
    assert broken.is_dir()


def test_ui_bundle_check_rejects_missing_javascript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dodaios" / "ui" / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>\n", encoding="utf-8")
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)

    assert installer.step_ui_bundle_check() is False


def test_ui_bundle_check_accepts_complete_entry_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dodaios" / "ui" / "web" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<script type="module" src="/assets/app.js"></script>'
        '<link rel="stylesheet" href="/assets/app.css">',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("export {};\n", encoding="utf-8")
    (assets / "app.css").write_text("body {}\n", encoding="utf-8")
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)

    assert installer.step_ui_bundle_check() is True


def test_ui_bundle_check_builds_a_missing_bundle_with_npm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # main tracks no bundle: a branch install builds one when npm is there.
    frontend = tmp_path / "dodaios" / "ui" / "web" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package-lock.json").write_text("{}\n", encoding="utf-8")
    dist = tmp_path / "dodaios" / "ui" / "web" / "dist"
    calls: list[list[str]] = []

    def fake_build(cmd, *, label, cwd=None, timeout=None, env=None):
        calls.append(cmd[1:])
        if cmd[1:] == ["run", "build"]:
            (dist / "assets").mkdir(parents=True)
            (dist / "index.html").write_text(
                '<script type="module" src="/assets/app.js"></script>', encoding="utf-8"
            )
            (dist / "assets" / "app.js").write_text("export {};\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(installer, "run_captured", fake_build)

    assert installer.step_ui_bundle_check() is True
    assert calls == [["ci"], ["run", "build"]]


def test_ui_bundle_check_without_npm_reports_a_missing_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(installer.shutil, "which", lambda name: None)

    assert installer.step_ui_bundle_check() is False
    out = capsys.readouterr().out
    assert "Node.js/npm is not installed" in out


def test_ui_bundle_check_reports_npm_nonzero_exit_and_stderr_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    frontend = tmp_path / "dodaios" / "ui" / "web" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package-lock.json").write_text("{}\n", encoding="utf-8")
    stderr_lines = "\n".join(f"npm-err-{idx}" for idx in range(20))

    def fake_build(cmd, *, label, cwd=None, timeout=None, env=None):
        if cmd[1:] == ["run", "build"]:
            return subprocess.CompletedProcess(
                cmd, 2, "vite build started\n", stderr_lines
            )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(installer, "run_captured", fake_build)

    assert installer.step_ui_bundle_check() is False
    out = capsys.readouterr().out
    assert "Node.js/npm is not installed" not in out
    assert "npm run build" in out
    assert "exit code 2" in out
    assert "npm-err-19" in out
    assert "npm-err-0" not in out


def test_ui_bundle_check_reports_incomplete_build_output_when_index_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    frontend = tmp_path / "dodaios" / "ui" / "web" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package-lock.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(
        installer,
        "run_captured",
        lambda cmd, *, label, cwd=None, timeout=None, env=None: subprocess.CompletedProcess(
            cmd, 0, "", ""
        ),
    )

    assert installer.step_ui_bundle_check() is False
    out = capsys.readouterr().out
    assert "Node.js/npm is not installed" not in out
    assert "build output is incomplete" in out
    assert "index.html" in out


def test_desktop_registration_failure_is_install_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(installer, "venv_python", lambda: tmp_path / "python")
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout='{"ok": false, "attempted": true}',
            stderr="",
        ),
    )

    assert installer.step_desktop_integration(enabled=True, dry_run=False) is False


def test_desktop_registration_failure_surfaces_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(installer, "venv_python", lambda: tmp_path / "python")
    stderr = "\n".join(f"stderr-line-{index}" for index in range(20))
    report = json.dumps(
        {
            "ok": False,
            "attempted": True,
            "warnings": ["bundle identity probe failed"],
        }
    )
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout=report,
            stderr=stderr,
        ),
    )

    assert installer.step_desktop_integration(enabled=True, dry_run=False) is False

    out = capsys.readouterr().out
    assert "bundle identity probe failed" in out
    assert "stderr-line-19" in out
    assert "stderr-line-5" in out
    # Only the last ~15 stderr lines are echoed to the console.
    assert "stderr-line-4" not in out
    assert "--headless" in out
    # The full path may be folded across lines by the console width.
    assert "full log:" in out
    log_path = tmp_path / "data" / "logs" / "install-desktop-integration.log"
    text = log_path.read_text(encoding="utf-8")
    assert "stderr-line-0" in text
    assert "bundle identity probe failed" in text


def test_desktop_registration_success_still_writes_full_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(installer, "venv_python", lambda: tmp_path / "python")
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout='{"ok": true, "attempted": true}',
            stderr="probe chatter\n",
        ),
    )

    assert installer.step_desktop_integration(enabled=True, dry_run=False) is True

    text = (
        tmp_path / "data" / "logs" / "install-desktop-integration.log"
    ).read_text(encoding="utf-8")
    assert '{"ok": true, "attempted": true}' in text
    assert "probe chatter" in text


def test_macos_launch_survives_missing_editable_import(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """BUG-078: on a FRESH install the installer process predates the editable
    install, so ``import dodaios`` fails in-process (.pth hooks only load at
    interpreter startup). step_launch must fall back to launching by app name
    instead of crashing after a fully successful install."""
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(installer, "is_headless_linux", lambda: False)
    # Force the in-process import to fail even though the dev venv has jarvis.
    import builtins

    real_import = builtins.__import__

    def _no_package(name, *args, **kwargs):
        if is_package_module(name):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_package)

    installer.step_launch(headless=False, dry_run=True)

    out = capsys.readouterr().out
    assert "/usr/bin/open -a Dodaios" in out


def _failing_build(monkeypatch, tmp_path: Path, stdout: str, stderr: str) -> list[dict]:
    frontend = tmp_path / "dodaios" / "ui" / "web" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package-lock.json").write_text("{}\n", encoding="utf-8")
    envs: list[dict] = []

    def fake_build(cmd, *, label, cwd=None, timeout=None, env=None):
        envs.append(env)
        if cmd[1:] == ["run", "build"]:
            return subprocess.CompletedProcess(cmd, 134, stdout, stderr)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(installer, "run_captured", fake_build)
    return envs


def test_ui_build_failure_keeps_the_fatal_header_above_a_long_stack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    """#1033: a V8 abort prints its reason first, then a 50-frame native stack."""
    stack = "\n".join(
        f"{idx}: 0x10679d540 node::Frame{idx}() [libnode.dylib]" for idx in range(53)
    )
    stderr = (
        "<--- Last few GCs --->\n"
        "FATAL ERROR: Ineffective mark-compacts near heap limit "
        "Allocation failed - JavaScript heap out of memory\n"
        + stack
        + "\nsh: line 1: 13287 Abort trap: 6           vite build --outDir ../dist\n"
    )
    _failing_build(monkeypatch, tmp_path, "vite v7 building for production...\n", stderr)

    assert installer.step_ui_bundle_check() is False
    out = capsys.readouterr().out
    assert "exit code 134" in out
    assert "JavaScript heap out of memory" in out
    assert "Abort trap: 6" in out
    assert "node::Frame52()" in out
    assert "node::Frame5()" not in out  # the middle of the stack stays out


def test_ui_build_raises_the_node_heap_unless_the_user_set_node_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("NODE_OPTIONS", raising=False)
    envs = _failing_build(monkeypatch, tmp_path, "", "boom")
    installer.step_ui_bundle_check()
    assert envs
    assert all(env["NODE_OPTIONS"] == installer.UI_BUILD_NODE_OPTIONS for env in envs)

    monkeypatch.setenv("NODE_OPTIONS", "--max-old-space-size=8192")
    assert installer._ui_build_env()["NODE_OPTIONS"] == "--max-old-space-size=8192"
