"""The one-thread BLAS pool numpy and scipy get on Windows (jarvis.core.blas_threads)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis.core import blas_threads
from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _no_thread_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(blas_threads.THREADS_ENV, raising=False)


@pytest.fixture
def fake_wheel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A site directory holding ``fakeblas`` laid out like the numpy wheel."""
    site = tmp_path / "site"
    (site / "fakeblas").mkdir(parents=True)
    (site / "fakeblas" / "__init__.py").write_text("", encoding="utf-8")
    libs = site / "fakeblas.libs"
    libs.mkdir()
    (libs / "libscipy_openblas64_-abc123.dll").write_bytes(b"")
    (libs / "msvcp140-def456.dll").write_bytes(b"")
    monkeypatch.syspath_prepend(str(site))
    return libs


def test_finds_the_bundled_openblas_without_importing_the_package(fake_wheel: Path) -> None:
    found = blas_threads.blas_libraries("fakeblas")
    assert [path.name for path in found] == ["libscipy_openblas64_-abc123.dll"]
    assert "fakeblas" not in sys.modules


def test_a_package_without_a_private_blas_has_nothing_to_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "plainpkg").mkdir()
    (tmp_path / "plainpkg" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert blas_threads.blas_libraries("plainpkg") == []
    assert blas_threads.blas_libraries("no_such_package_anywhere") == []


def test_the_cap_exists_only_while_the_library_loads(fake_wheel: Path) -> None:
    seen: list[tuple[str, str | None]] = []

    def load(path: str) -> None:
        seen.append((Path(path).name, os.environ.get(blas_threads.THREADS_ENV)))

    assert blas_threads.preload("fakeblas", load=load) is True
    assert seen == [("libscipy_openblas64_-abc123.dll", "1")]
    # Children spawned afterwards (terminal panes, agents) inherit no cap.
    assert blas_threads.THREADS_ENV not in os.environ


def test_a_thread_count_the_user_set_is_left_alone(
    fake_wheel: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(blas_threads.THREADS_ENV, "8")
    loaded: list[str] = []
    assert blas_threads.preload("fakeblas", load=loaded.append) is False
    assert loaded == []
    assert os.environ[blas_threads.THREADS_ENV] == "8"


def test_a_library_that_will_not_load_never_breaks_the_import(fake_wheel: Path) -> None:
    def load(path: str) -> None:
        raise OSError("not a valid Win32 application")

    assert blas_threads.preload("fakeblas", load=load) is False
    assert blas_threads.THREADS_ENV not in os.environ


def test_the_finder_preloads_each_package_once_and_resolves_nothing() -> None:
    calls: list[str] = []
    finder = blas_threads._PreloadOnImport(calls.append)
    assert finder.find_spec("numpy") is None
    assert finder.find_spec("numpy") is None
    assert finder.find_spec("numpy.linalg") is None
    assert finder.find_spec("scipy") is None
    assert finder.find_spec("json") is None
    assert calls == ["numpy", "scipy"]


def test_install_is_windows_only_and_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    def installed() -> int:
        return sum(isinstance(f, blas_threads._PreloadOnImport) for f in sys.meta_path)

    others = [f for f in sys.meta_path if not isinstance(f, blas_threads._PreloadOnImport)]
    monkeypatch.setattr(sys, "meta_path", others)
    monkeypatch.setattr(sys, "modules", {k: v for k, v in sys.modules.items() if k != "numpy"})

    monkeypatch.setattr(sys, "platform", "linux")
    blas_threads.install_when_imported()
    assert installed() == 0

    monkeypatch.setattr(sys, "platform", "win32")
    blas_threads.install_when_imported()
    blas_threads.install_when_imported()
    assert installed() == 1


_PROBE = """
import ctypes, json, os
from ctypes import wintypes as w
import jarvis
import numpy

SIZES = ("peak_ws", "ws", "qpp", "qp", "qpnp", "qnp", "pagefile", "peak_pagefile", "private")

class Counters(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [(n, ctypes.c_size_t) for n in SIZES]

kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
kernel32.GetCurrentProcess.restype = w.HANDLE
psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Counters), w.DWORD]
counters = Counters()
counters.cb = ctypes.sizeof(counters)
psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
matrix = numpy.arange(16.0).reshape(4, 4)
print(json.dumps({
    "private_mb": counters.private / 2**20,
    "leaked": "OPENBLAS_NUM_THREADS" in os.environ,
    "trace": float((matrix @ matrix).trace()),
}))
"""


@pytest.mark.skipif(sys.platform != "win32", reason="commit charge is a Windows cost")
def test_a_real_numpy_import_commits_one_buffer_not_one_per_core() -> None:
    pytest.importorskip("numpy")
    if not blas_threads.blas_libraries("numpy"):
        pytest.skip("this numpy brings no private OpenBLAS")
    if (os.cpu_count() or 1) < 4:
        pytest.skip("too few cores to tell a capped pool from the default")
    import json

    env = {k: v for k, v in os.environ.items() if k != blas_threads.THREADS_ENV}
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", _PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        check=True,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])
    # Uncapped, four cores already commit 4 x 32 MB on top of the interpreter.
    assert report["private_mb"] < 100, report
    assert report["leaked"] is False
    assert report["trace"] == 1060.0  # BLAS still computes
