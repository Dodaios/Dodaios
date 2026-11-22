"""Which policy a new coding run runs under: the active one, or a candidate on trial.

A cell has one active policy (the default until a better one was found) and at
most one candidate on trial. While a candidate is on trial, the person's
requests are split between the two by a fixed draw on the request's id (the
canary of decision 5.3): every run of one request gets the same arm, and the
same request always gets the same one. The policy is frozen into the run's
record when the run starts, so a policy that changes later never reaches a run
that is already going.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Final

from .policy import ACTIVE, CANDIDATE, DEFAULT, Policy, PolicyStore

log = logging.getLogger(__name__)

__all__ = ["Binding", "arm_of", "bind", "set_store", "store"]

_ARM_SALT: Final[str] = "rsi-canary-1"


@dataclass(frozen=True, slots=True)
class Binding:
    policy: Policy
    #: ``active`` or ``candidate``.
    arm: str


def arm_of(root: str) -> str:
    """The canary arm of a request: the same request always draws the same."""
    digest = hashlib.sha256(f"{root}:{_ARM_SALT}".encode()).hexdigest()
    return CANDIDATE if int(digest[:8], 16) % 2 else ACTIVE


def bind(policies: PolicyStore | None, cell: str, root: str) -> Binding:
    """The policy and arm of a new run in ``cell`` for the request ``root``. Never raises."""
    if policies is None:
        return Binding(DEFAULT, ACTIVE)
    try:
        active = policies.policy(cell, ACTIVE) or DEFAULT
        candidate = policies.policy(cell, CANDIDATE)
    except Exception:  # noqa: BLE001 - an unreadable store binds the default, and says so
        log.warning("rsi bind: policies of %s unreadable; the default applies", cell, exc_info=True)
        return Binding(DEFAULT, ACTIVE)
    if candidate is None or candidate == active or not root:
        return Binding(active, ACTIVE)
    if arm_of(root) == CANDIDATE:
        return Binding(candidate, CANDIDATE)
    return Binding(active, ACTIVE)


_store: PolicyStore | None = None


def store() -> PolicyStore | None:
    """The process's policy store, or ``None`` while no policy can be bound."""
    return _store


def set_store(value: PolicyStore | None) -> None:
    global _store
    _store = value


def binding_fields(cell: str, root: str) -> dict[str, Any]:
    """The run columns a binding sets: policy id, arm and the frozen policy text."""
    found = bind(_store, cell, root)
    return {"policy_id": found.policy.id, "arm": found.arm, "policy_json": found.policy.to_text()}
