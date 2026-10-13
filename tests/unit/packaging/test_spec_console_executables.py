"""``jarvis.spec`` builds the console CLI under its name and its earlier name.

The frozen build ships three executables in one folder: the windowed launcher,
the console command (``dodaios``) and the same console program once more as
``jarvis``, which scripts and shell history still call. This runs the real
spec with stand-in PyInstaller names and checks the targets it declares, for
every OS the spec is built on.
"""

from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path

import pytest

from jarvis.core import branding

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "jarvis.spec"


def _exec_spec(
    monkeypatch: pytest.MonkeyPatch, root: Path, platform: str
) -> list[tuple[str, tuple[object, ...], dict[str, object]]]:
    """Run the real spec for ``platform``; return every build call in order."""
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def recorder(name: str):
        def _call(*args: object, **kwargs: object) -> types.SimpleNamespace:
            calls.append((name, args, kwargs))
            return types.SimpleNamespace(
                target=name,
                name=kwargs.get("name"),
                pure=[],
                zipped_data=[],
                scripts=[],
                binaries=[],
                zipfiles=[],
                datas=[],
            )

        return _call

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda *a, **k: []  # type: ignore[attr-defined]
    hooks.collect_submodules = lambda *a, **k: []  # type: ignore[attr-defined]
    hooks.copy_metadata = lambda *a, **k: []  # type: ignore[attr-defined]
    # The Windows version resource: any structure the spec asks for is recorded.
    versioninfo = types.ModuleType("PyInstaller.utils.win32.versioninfo")
    versioninfo.__getattr__ = lambda kind: (  # type: ignore[method-assign]
        lambda *args, **kwargs: types.SimpleNamespace(kind=kind, args=args, kwargs=kwargs)
    )
    for name, module in (
        ("PyInstaller", types.ModuleType("PyInstaller")),
        ("PyInstaller.utils", types.ModuleType("PyInstaller.utils")),
        ("PyInstaller.utils.hooks", hooks),
        ("PyInstaller.utils.win32", types.ModuleType("PyInstaller.utils.win32")),
        ("PyInstaller.utils.win32.versioninfo", versioninfo),
        # The spec probes these optional packages with __import__; stand-ins keep
        # a real (possibly platform-specific) import from running under a fake OS.
        ("webview", types.ModuleType("webview")),
        ("pystray", types.ModuleType("pystray")),
        ("PIL", types.ModuleType("PIL")),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, "platform", platform)

    namespace: dict[str, object] = {"SPECPATH": str(root), "__file__": str(root / "jarvis.spec")}
    for builtin in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE"):
        namespace[builtin] = recorder(builtin)
    source = (root / "jarvis.spec").read_text(encoding="utf-8")
    exec(compile(source, str(root / "jarvis.spec"), "exec"), namespace)  # noqa: S102
    return calls


@pytest.fixture
def spec_root(tmp_path: Path) -> Path:
    """A minimal checkout: the real spec and the files it reads by path."""
    root = tmp_path / "checkout"
    (root / "jarvis" / "core").mkdir(parents=True)
    (root / "jarvis" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    shutil.copy2(
        REPO_ROOT / "jarvis" / "core" / "macos_privacy_strings.py",
        root / "jarvis" / "core" / "macos_privacy_strings.py",
    )
    shutil.copy2(SPEC_PATH, root / "jarvis.spec")
    # The notice collector walks every installed distribution, which has
    # nothing to do with the executables under test: a stand-in with the same
    # entry point keeps this file about the build targets (and fast).
    helper_dir = root / "scripts" / "packaging"
    helper_dir.mkdir(parents=True)
    (helper_dir / "native_notices.py").write_text(
        "def collect_native_notices(*_args, **_kwargs):\n    return []\n", encoding="utf-8"
    )
    return root


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_the_freeze_ships_the_console_program_under_both_names(
    monkeypatch: pytest.MonkeyPatch, spec_root: Path, platform: str
) -> None:
    calls = _exec_spec(monkeypatch, spec_root, platform)

    executables = [kwargs for name, _args, kwargs in calls if name == "EXE"]
    built = [(kwargs["name"], kwargs["console"]) for kwargs in executables]
    gui = Path(branding.WINDOWS_BRANDED_LAUNCHER_FILE_NAME).stem
    assert built == [
        (gui, False),
        (branding.CLI_COMMAND_NAME, True),
        (branding.LEGACY_CLI_COMMAND_NAMES[0], True),
    ]
    # One folder holds all of them: no two names may differ by case alone.
    folded = [str(name).casefold() for name, _console in built]
    assert len(set(folded)) == len(folded)

    # Every executable is collected into the one bundle, the launcher first.
    collect = next(args for name, args, _kwargs in calls if name == "COLLECT")
    collected = [item.name for item in collect if getattr(item, "target", None) == "EXE"]
    assert collected == [name for name, _console in built]

    # The console builds differ in nothing but their name.
    new, legacy = executables[1], executables[2]
    assert {k: v for k, v in new.items() if k != "name"} == {
        k: v for k, v in legacy.items() if k != "name"
    }


def test_the_macos_bundle_still_launches_the_windowed_executable(
    monkeypatch: pytest.MonkeyPatch, spec_root: Path
) -> None:
    calls = _exec_spec(monkeypatch, spec_root, "darwin")

    bundle = next(kwargs for name, _args, kwargs in calls if name == "BUNDLE")
    assert bundle["info_plist"]["CFBundleExecutable"] == branding.MACOS_EXECUTABLE_NAME
    # The last collected executable is a console one; the bundle must say it
    # is a windowed app all the same.
    assert bundle["info_plist"]["LSBackgroundOnly"] is False
