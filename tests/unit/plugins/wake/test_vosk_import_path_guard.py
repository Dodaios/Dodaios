"""A failed vosk import must not grow PATH (#1045, #1071)."""

from __future__ import annotations

import os
import sys
import types

import pytest

from dodaios.core import path_augment
from dodaios.plugins.wake import vosk_native


@pytest.fixture
def fresh_import_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vosk_native, "_import_failure", None)
    monkeypatch.delitem(sys.modules, "vosk", raising=False)


def _broken_vosk_import(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Mimic vosk/__init__.py: prepend its DLL folder, then fail to load."""
    attempts: list[int] = []
    real_import = vosk_native.importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name != "vosk":
            return real_import(name, *args, **kwargs)
        attempts.append(1)
        os.environ["PATH"] = r"C:\app\_internal\vosk" + os.pathsep + os.environ["PATH"]
        raise OSError("cannot load library 'libvosk.dll'")

    monkeypatch.setattr(vosk_native.importlib, "import_module", fake_import)
    return attempts


def test_repeated_failing_import_leaves_path_unchanged(
    monkeypatch: pytest.MonkeyPatch, fresh_import_state: None
) -> None:
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))
    before = os.environ["PATH"]
    attempts = _broken_vosk_import(monkeypatch)

    for _ in range(50):
        with pytest.raises(ImportError):
            vosk_native.import_vosk()

    assert os.environ["PATH"] == before
    # The failure is remembered: the wake loop does not retry the import.
    assert len(attempts) == 1


def test_failed_import_is_retried_after_the_cooldown(
    monkeypatch: pytest.MonkeyPatch, fresh_import_state: None
) -> None:
    attempts = _broken_vosk_import(monkeypatch)
    with pytest.raises(ImportError):
        vosk_native.import_vosk()
    failed_at, error = vosk_native._import_failure
    monkeypatch.setattr(
        vosk_native, "_import_failure", (failed_at - vosk_native._IMPORT_RETRY_S - 1, error)
    )
    with pytest.raises(ImportError):
        vosk_native.import_vosk()
    assert len(attempts) == 2


def test_an_imported_vosk_is_returned_as_is(
    monkeypatch: pytest.MonkeyPatch, fresh_import_state: None
) -> None:
    module = types.ModuleType("vosk")
    monkeypatch.setitem(sys.modules, "vosk", module)
    monkeypatch.setattr(vosk_native, "_import_failure", (0.0, OSError("old")))
    assert vosk_native.import_vosk() is module


def test_trimming_drops_repeated_vosk_folders(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    real = tmp_path / "bin"
    real.mkdir()
    vosk_dir = str(tmp_path / "_internal" / "vosk")
    entries = [vosk_dir] * 600 + [str(real)]
    monkeypatch.setattr(path_augment, "_path_budget", lambda: 31_000)
    fitted = path_augment.fit_spawn_path(os.pathsep.join(entries))
    assert fitted.split(os.pathsep) == [vosk_dir, str(real)]


def test_browser_install_run_repairs_an_over_budget_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from dodaios.society.browser import install

    # A small budget stands in for Windows' limit: os.environ itself refuses
    # a value past 32,767 characters on Windows.
    real = tmp_path / "bin"
    real.mkdir()
    long_path = os.pathsep.join([str(tmp_path / "_internal" / "vosk")] * 200 + [str(real)])
    monkeypatch.setattr(path_augment, "_path_budget", lambda: 4_000)
    monkeypatch.setattr(path_augment, "candidate_dirs", lambda: [])
    monkeypatch.setattr(path_augment, "_settled_overflow", None)
    monkeypatch.setenv("PATH", long_path)
    seen: dict[str, str] = {}

    class FakeProc:
        pid = 4242
        returncode = 0

        def communicate(self, timeout=None):
            return "ok", None

        def poll(self):
            return 0

        def wait(self):
            return 0

    class FakeTree:
        def assign(self, pid):
            pass

        def close(self):
            pass

    def fake_popen(cmd, **kwargs):
        seen["child"] = kwargs["env"]["PATH"]
        seen["parent"] = os.environ["PATH"]
        return FakeProc()

    monkeypatch.setattr(install.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        "dodaios.core.process_tree.make_process_tree", lambda name: FakeTree()
    )
    install._run(["python", "-V"], env={"PATH": long_path})

    assert len(seen["parent"]) <= 4_000
    assert len(seen["child"]) <= 4_000
    assert seen["child"].split(os.pathsep)[-1] == str(real)


# ------------------------------------------------------------------ loader threads


def test_a_module_without_the_library_is_left_alone(tmp_path) -> None:
    module = types.ModuleType("vosk")
    module.__file__ = str(tmp_path / "__init__.py")
    assert vosk_native.cap_loader_threads(module) is False


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows charges untouched buffers")
def test_models_load_on_one_kaldi_thread() -> None:
    """Eight loader threads mapped eight 128 MB BLAS buffers for two 40 MB models."""
    import ctypes

    vosk = pytest.importorskip("vosk")
    library = os.path.join(os.path.dirname(vosk.__file__), "libvosk.dll")
    try:
        threads = ctypes.c_int.in_dll(ctypes.CDLL(library), vosk_native._LOADER_THREADS_SYMBOL)
    except (OSError, ValueError):
        pytest.skip("this libvosk does not export kaldi::g_num_threads")
    threads.value = 8
    assert vosk_native.cap_loader_threads(vosk) is True
    assert threads.value == 1
