"""Hand-built stand-in for the pywin32 named-mutex calls.

Per AGENTS.md the project uses real fakes, never ``unittest.mock``. A real
named mutex is machine-wide (``Global\\...``): a test that created the app's own
name would make the developer's running app look like a secondary, or the
other way round. :class:`FakeNamedMutexes` keeps the namespace in memory and
hands out three module stand-ins (``win32event``, ``win32api``, ``winerror``)
plus a ``last_error`` function, the way ``dodaios.ui.shell.single_instance``
reads them.

Install with :meth:`FakeNamedMutexes.install`, which uses ``monkeypatch`` so
every module is put back after the test.
"""

from __future__ import annotations

import sys
import types
from collections import Counter

import pytest

ERROR_ALREADY_EXISTS = 183


class FakeNamedMutexes:
    """A per-test mutex namespace: create, release and close by handle.

    ``held`` counts the open handles per name, the way the kernel keeps a named
    object alive while any handle to it is open. ``created`` lists every
    ``CreateMutex`` call in order, ``closed`` every name whose handle closed.
    """

    def __init__(self, *, held_elsewhere: tuple[str, ...] = ()) -> None:
        self.held: Counter[str] = Counter(held_elsewhere)
        self.created: list[str] = []
        self.closed: list[str] = []
        self._names_by_handle: dict[int, str] = {}
        self._next_handle = 100
        self._last_error = 0

    # -- win32event ---------------------------------------------------------
    def CreateMutex(self, _security: object, _initial_owner: bool, name: str) -> int:  # noqa: N802
        self.created.append(name)
        self._last_error = ERROR_ALREADY_EXISTS if self.held[name] else 0
        self.held[name] += 1
        handle = self._next_handle
        self._next_handle += 1
        self._names_by_handle[handle] = name
        return handle

    def ReleaseMutex(self, handle: int) -> None:  # noqa: N802
        if handle not in self._names_by_handle:
            raise OSError("not a mutex handle")

    # -- win32api -----------------------------------------------------------
    def CloseHandle(self, handle: int) -> None:  # noqa: N802
        name = self._names_by_handle.pop(handle)
        self.held[name] -= 1
        if self.held[name] <= 0:
            del self.held[name]
        self.closed.append(name)

    # -- kernel32.GetLastError ---------------------------------------------
    def last_error(self) -> int:
        return self._last_error

    def is_held(self, name: str) -> bool:
        return self.held[name] > 0

    def install(self, monkeypatch: pytest.MonkeyPatch, module: types.ModuleType) -> None:
        """Put the stand-ins where ``module`` imports and reads them."""
        win32event = types.ModuleType("win32event")
        win32event.CreateMutex = self.CreateMutex  # type: ignore[attr-defined]
        win32event.ReleaseMutex = self.ReleaseMutex  # type: ignore[attr-defined]
        win32api = types.ModuleType("win32api")
        win32api.CloseHandle = self.CloseHandle  # type: ignore[attr-defined]
        winerror = types.ModuleType("winerror")
        winerror.ERROR_ALREADY_EXISTS = ERROR_ALREADY_EXISTS  # type: ignore[attr-defined]
        for name, stand_in in (
            ("win32event", win32event),
            ("win32api", win32api),
            ("winerror", winerror),
        ):
            monkeypatch.setitem(sys.modules, name, stand_in)
        monkeypatch.setattr(module, "_get_last_error", self.last_error)
