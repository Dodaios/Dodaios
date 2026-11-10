"""Deterministic background-billing state for tests.

Process-wide state decides what a background model call may bill: the
subscription policy (``dodaios.brain.background_policy`` — a login probe plus
a sticky "a subscription was seen" marker on disk). It reads the developer's
real user-data directory by default, so a suite run on a machine with a
signed-in CLI would silently switch every test into subscription mode.

:class:`BackgroundBilling` pins it to a temporary directory and a scripted
login table. The default is a key-only install: no subscription signed in,
nothing remembered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from dodaios.brain import background_policy


@dataclass
class BackgroundBilling:
    """Scripted login states plus isolated marker/counter files."""

    root: Path
    logins: dict[str, bool | None] = field(default_factory=dict)

    def sign_in(self, provider: str) -> None:
        """Make *provider*'s subscription login answer ``True`` from now on."""
        self.logins[provider] = True
        background_policy._probe_cache.pop(provider, None)  # noqa: SLF001 - test seam

    def sign_out(self, provider: str) -> None:
        """The login now answers ``False``; the sticky marker is kept."""
        self.logins[provider] = False
        background_policy._probe_cache.pop(provider, None)  # noqa: SLF001 - test seam

    def remember_subscription(self, provider: str = "claude-cli") -> None:
        """Record that a subscription was seen connected (subscription mode)."""
        background_policy.note_connected(provider)


def isolate_background_billing(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> BackgroundBilling:
    """Point the policy at *root* and script the login probe."""
    root.mkdir(parents=True, exist_ok=True)
    billing = BackgroundBilling(root=root)
    marker = root / "subscription_seen.json"
    monkeypatch.setattr(background_policy, "_marker_path", lambda: marker)
    background_policy.reset_for_tests()
    background_policy._probe_override = billing.logins.get  # noqa: SLF001 - test seam
    return billing


def reset_background_billing() -> None:
    background_policy.reset_for_tests()


__all__ = [
    "BackgroundBilling",
    "isolate_background_billing",
    "reset_background_billing",
]
