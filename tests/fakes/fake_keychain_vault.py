"""Stand-ins for the macOS vault wrapper's two dependencies.

``DarwinBundleKeyringBackend`` (``dodaios.core.keychain_bundle``) keeps every
key in one vault item, read and written through the ``security`` CLI, and
falls back to the per-item platform backend. These fakes hold both in dicts
and record every call, so a test can prove which service was written. No
real Keychain and no ``security`` process is ever involved.
"""

from __future__ import annotations

import base64
import json

from keyring.errors import PasswordDeleteError


def vault_payload(entries: dict[str, str]) -> str:
    """A vault item as the ``security`` CLI stores it: base64 of the JSON object."""
    return base64.b64encode(json.dumps(entries).encode("utf-8")).decode("ascii")


def read_payload(raw: str) -> dict[str, str]:
    return json.loads(base64.b64decode(raw).decode("utf-8"))


class FakeSecurityCli:
    """In-memory ``security`` CLI vault store: ``(service, account) -> payload``."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []

    def read(self, service: str, account: str) -> str | None:
        self.calls.append(("read", service, account))
        return self.items.get((service, account))

    def write(self, service: str, account: str, value: str) -> None:
        self.calls.append(("write", service, account))
        self.items[(service, account)] = value

    def delete(self, service: str, account: str) -> None:
        self.calls.append(("delete", service, account))
        self.items.pop((service, account), None)

    def writes(self, service: str) -> list[str]:
        return [account for op, owner, account in self.calls if owner == service and op != "read"]


class FakePerItemKeychain:
    """The per-item backend the wrapper falls back to (one entry per key)."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []

    def get_password(self, service: str, key: str) -> str | None:
        self.calls.append(("get", service, key))
        return self.values.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.calls.append(("set", service, key))
        self.values[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        self.calls.append(("delete", service, key))
        if (service, key) not in self.values:
            raise PasswordDeleteError(f"no item {key!r} under {service!r}")
        del self.values[(service, key)]

    def writes(self, service: str) -> list[str]:
        return [key for op, owner, key in self.calls if owner == service and op != "get"]
