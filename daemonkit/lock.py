"""An exclusive lock on a file that the operating system drops when its owner dies.

This lock is the only source of truth for "is the server running". A pid in a
file can be reused by an unrelated process after a crash; a lock cannot
outlive the process that holds it, because the kernel releases it together
with the process's open files. So a crashed server never leaves a stale lock
behind, and nothing ever has to guess.

* POSIX: ``flock(LOCK_EX | LOCK_NB)`` on an open file description.
* Windows: ``msvcrt.locking(LK_NBLCK)`` on the first byte.

The descriptor is opened non-inheritable (Python's default), so a child the
server starts cannot keep the lock alive after the server has gone.

The lock file itself is never deleted: removing it while another process has
it open would let two processes lock two different files of the same name.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path


class InstanceLock:
    """A non-blocking exclusive lock on ``path``.

    >>> lock = InstanceLock(Path("server.lock"))
    >>> if lock.acquire():
    ...     try:
    ...         ...  # this process is the one instance
    ...     finally:
    ...         lock.release()
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        """Whether THIS object holds the lock right now."""
        return self._fd is not None

    def acquire(self) -> bool:
        """Take the lock if it is free. Returns at once either way."""
        if self._fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock(fd)
        except OSError:
            # Held by someone else: that is the answer, not an error.
            os.close(fd)
            return False
        self._fd = fd
        return True

    def acquire_within(self, timeout: float, *, poll: float = 0.05) -> bool:
        """Try to take the lock until ``timeout`` seconds have passed."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self.acquire():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll)

    def release(self) -> None:
        """Give the lock back. Safe to call when it is not held."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock(fd)
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def hold(self, timeout: float = 0.0) -> Iterator[InstanceLock]:
        """``with lock.hold(timeout=5):`` — raises :class:`TimeoutError` if not taken."""
        if not self.acquire_within(timeout):
            raise TimeoutError(f"{self.path} is held by another process")
        try:
            yield self
        finally:
            self.release()

    def __del__(self) -> None:
        # A forgotten lock is released by the OS when the process exits anyway;
        # this only closes the descriptor a little earlier.
        with contextlib.suppress(OSError):
            self.release()


def is_locked(path: Path) -> bool:
    """Whether some process holds the lock on ``path``.

    Probes by trying to take the lock and giving it back at once. A server that
    starts during that instant fails its first attempt, which is why a server
    takes its lock with :meth:`InstanceLock.acquire_within` rather than once.
    """
    if not Path(path).exists():
        return False
    probe = InstanceLock(path)
    if probe.acquire():
        probe.release()
        return False
    return True


if sys.platform == "win32":
    import msvcrt

    def _lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
