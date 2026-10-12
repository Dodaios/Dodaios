"""A dict-backed credential store with the ``keyring`` call shape.

Entries live under ``(service, key)`` like the real store, so a test can hold
two services side by side. Failures are scripted per call, and every call is
recorded, so a test can prove what was *not* touched.
"""

from __future__ import annotations


class FakeKeyringError(RuntimeError):
    """Stands in for the backend-specific errors a real store raises."""


class FakeKeyringBackend:
    """The ``KeyringBackend`` shape of ``jarvis.core.identity_migration``."""

    def __init__(self, *, unavailable: bool = False, drop_writes: bool = False) -> None:
        self.entries: dict[tuple[str, str], str] = {}
        self.unavailable = unavailable
        # Accept every write and keep nothing, like a null fallback store.
        self.drop_writes = drop_writes
        # ``(operation, service, key)`` triples that raise instead of working.
        self.fail_on: set[tuple[str, str, str]] = set()
        self.calls: list[tuple[str, str, str]] = []

    def _record(self, operation: str, service: str, key: str, value: str = "") -> None:
        self.calls.append((operation, service, key))
        if self.unavailable or (operation, service, key) in self.fail_on:
            # The error text of a store may quote the value it refused.
            raise FakeKeyringError(f"{operation} refused for {service}/{key}: {value!r}")

    def get_password(self, service: str, key: str) -> str | None:
        self._record("get", service, key)
        return self.entries.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self._record("set", service, key, value)
        if not self.drop_writes:
            self.entries[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        self._record("delete", service, key)
        self.entries.pop((service, key), None)

    def service(self, service: str) -> dict[str, str]:
        """Everything stored under one service, as ``key -> value``."""
        return {key: value for (owner, key), value in self.entries.items() if owner == service}
