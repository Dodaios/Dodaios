"""One BLAS thread per process instead of one per CPU core (Windows).

The numpy and the scipy wheel each bundle their own OpenBLAS. The moment such a
copy is loaded it starts one worker thread per logical CPU and commits a 32 MB
scratch buffer for every one of them. Windows charges committed memory against
the page file whether or not a page is ever touched, so the bill grows with the
core count. Measured on a 16-thread box (numpy 2.1, scipy 1.18):

* ``import numpy``                 9 MB ->   500 MB committed
* ``+ import scipy.signal``            -> 1,070 MB committed

The desktop app pays that in every process that touches audio: the backend,
both dictation engine workers and the screen-recording standby worker, about
3 GB together, for threads nothing here uses. The app's own array work is audio
buffers and mel filters, far below the size where OpenBLAS threads at all. A
single-threaded pool is also the faster one on a busy machine: 16 spinning
BLAS workers fighting other processes for cores took 4.7 s for an 800 x 800
inversion that one thread finished in 51 ms.

OpenBLAS reads ``OPENBLAS_NUM_THREADS`` exactly once, while its DLL loads.
Setting the variable for the whole process would hand it to every child too,
and the terminal panes run the user's own programs: their numpy must keep all
of its cores. So the variable exists only for the instant the DLL loads:
:func:`preload` sets it, loads the bundled OpenBLAS by path, and removes it
again. The later ``import numpy`` finds the library already in the process and
keeps the pool it was started with. A child spawned from another thread inside
that load (about a millisecond) would inherit the cap; that window is accepted.

:func:`install_when_imported` wires this in without importing either package:
a ``sys.meta_path`` finder runs the preload right before the first
``import numpy`` / ``import scipy``. ``jarvis/__init__.py`` calls it, so every
process of the app gets it. A value the user set themselves is left alone.

Windows only. Linux and macOS do not charge untouched allocations, so the same
buffers cost nothing there and the pool is left as the wheel configures it.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable
    from pathlib import Path

#: Read by OpenBLAS once, at DLL load. Wins over GOTO_/OMP_NUM_THREADS.
THREADS_ENV: Final[str] = "OPENBLAS_NUM_THREADS"
_THREADS: Final[str] = "1"
#: Packages whose wheel ships a private OpenBLAS in ``<package>.libs``.
_PACKAGES: Final[frozenset[str]] = frozenset({"numpy", "scipy"})


def blas_libraries(package: str) -> list[Path]:
    """The OpenBLAS DLLs bundled with ``package``, without importing it.

    Empty for a build that brings no private OpenBLAS (a conda numpy on MKL, a
    system BLAS): there is nothing to cap then.
    """
    from importlib.machinery import PathFinder
    from pathlib import Path

    spec = PathFinder.find_spec(package)
    origin = getattr(spec, "origin", None)
    if not origin:
        return []
    libs = Path(origin).parent.parent / f"{package}.libs"
    if not libs.is_dir():
        return []
    return sorted(libs.glob("*openblas*.dll"))


def _load_library(path: str) -> None:
    import ctypes

    # Never freed: the handle keeps the library, and so its thread pool, alive
    # until the package's own extension modules bind to it.
    ctypes.WinDLL(path)  # type: ignore[attr-defined]


def preload(package: str, *, load: Callable[[str], Any] | None = None) -> bool:
    """Load ``package``'s OpenBLAS with a one-thread pool; ``True`` if it did.

    Never raises: this is an optimisation in front of an import, and a wheel
    laid out differently must import exactly as it did before.
    """
    if THREADS_ENV in os.environ:
        return False  # the user's own setting is not ours to replace
    try:
        libraries = blas_libraries(package)
        if not libraries:
            return False
        loader = load or _load_library
        os.environ[THREADS_ENV] = _THREADS
        try:
            for library in libraries:
                loader(str(library))
        finally:
            os.environ.pop(THREADS_ENV, None)
    except Exception as exc:  # noqa: BLE001 - see docstring: must not break the import
        import logging

        logging.getLogger(__name__).debug(
            "blas-threads: could not preload the %s BLAS, keeping its default pool: %s",
            package,
            exc,
        )
        return False
    return True


class _PreloadOnImport:
    """``sys.meta_path`` finder: cap a package's BLAS right before it loads.

    It never resolves anything itself and stays installed (removing an entry
    while the import system walks the list would skip the finder behind it);
    once both packages were seen it is one failed set lookup per import.
    """

    def __init__(self, preloader: Callable[[str], Any] = preload) -> None:
        self._pending = set(_PACKAGES)
        self._preload = preloader

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname in self._pending:
            self._pending.discard(fullname)
            self._preload(fullname)
        return None


def install_when_imported() -> None:
    """Arrange the preload for the first ``import numpy`` / ``import scipy``."""
    if sys.platform != "win32":
        return
    if any(isinstance(finder, _PreloadOnImport) for finder in sys.meta_path):
        return
    finder = _PreloadOnImport()
    # A package that is already imported has its pool; only the rest can be capped.
    finder._pending -= sys.modules.keys()  # noqa: SLF001 - own instance
    if finder._pending:  # noqa: SLF001
        sys.meta_path.insert(0, finder)


__all__ = ["THREADS_ENV", "blas_libraries", "install_when_imported", "preload"]
