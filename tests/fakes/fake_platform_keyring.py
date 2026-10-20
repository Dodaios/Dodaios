"""An OS credential store stand-in that ``keyring.set_keyring`` accepts.

``dodaios.core.config`` talks to the process-wide ``keyring`` module, which
only takes a ``keyring.backend.KeyringBackend``. This one keeps entries under
``(service, key)`` in a dict, records every call, and behaves like the real
backends the app relies on: a read of a missing entry is ``None``, a delete of
one raises ``PasswordDeleteError``. Nothing here reaches a real keyring.
"""

from __future__ import annotations

import keyring.backend
from keyring.errors import PasswordDeleteError


class FakePlatformKeyring(keyring.backend.KeyringBackend):
    """A dict-backed platform keyring with a positive priority."""

    priority = 5  # type: ignore[assignment]  # a real OS backend, not fail.Keyring

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append(("get", service, username))
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append(("set", service, username))
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete", service, username))
        if (service, username) not in self.entries:
            raise PasswordDeleteError(f"no entry {username!r} under {service!r}")
        del self.entries[(service, username)]

    def writes(self, service: str) -> list[str]:
        """The keys written or deleted under ``service``, in call order."""
        return [key for op, owner, key in self.calls if owner == service and op != "get"]

    def service(self, service: str) -> dict[str, str]:
        return {key: value for (owner, key), value in self.entries.items() if owner == service}
