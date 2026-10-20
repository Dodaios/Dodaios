"""The only way the self-building loop asks a model: subscriptions or local, never a key.

The maintainer's background rule (docs/self-build.md, rule 1) is stricter here
than for other background work. :mod:`dodaios.brain.background_policy` lets a
key-only install keep using its key for, say, the wiki; the loop does not:
nobody asked for a build, so nothing may be billed per token for it, ever. A
model is asked only when a connected subscription or a keyless local runtime
can answer; otherwise :class:`BackgroundDeferred` is raised and the loop
proposes without a model, or waits.

Every call runs inside :func:`dodaios.self_build.cost.attributed` (or the
decide step's own caller tag), so the cost ledger can show what the loop
spent, per build.

Blocking parts (login probes, plugin construction) run in a worker thread.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from dodaios.brain import background_policy
from dodaios.brain.background_policy import BackgroundDeferred

log = logging.getLogger(__name__)

#: One answer may take a while on a cold subscription CLI; never forever.
TIMEOUT_S: Final[float] = 120.0

#: ``(system, prompt, max_tokens) -> text``; the test seam replaces the brain.
Ask = Callable[[str, str, int], Awaitable[str]]

_override: Ask | None = None
_override_provider: str = ""


@dataclass(frozen=True, slots=True)
class Seat:
    """The provider the loop may use right now, and its model (``None`` = default)."""

    provider: str
    model: str | None
    billing: str


def _brain_provider_ids() -> list[str]:
    from dodaios.ui.web.provider_spec import PROVIDERS

    return [spec.id for spec in PROVIDERS if spec.tier == "brain"]


def seats(config: Any) -> list[Seat]:
    """Subscriptions that are signed in, then keyless local runtimes. Blocking.

    Never a provider billed per token, whatever the install's mode.
    """
    from dodaios.brain import resolver as brain_resolver

    policy = background_policy.background_providers(_brain_provider_ids())
    try:
        available = set(brain_resolver._get_registry().available())
    except Exception:  # noqa: BLE001 - no registry means no brain, not a crash
        log.info("self_build: brain registry unavailable", exc_info=True)
        return []
    subscriptions: list[Seat] = []
    local: list[Seat] = []
    for name in policy.allowed:
        if name not in available:
            continue
        billing = background_policy._billing(name)
        if billing.startswith("subscription"):
            # Signed in now: a dual-billed card signed out would spend its key.
            if background_policy.login_state(name) is True:
                subscriptions.append(Seat(name, None, billing))
        elif billing == "local":
            local.append(Seat(name, _local_model(config, name), billing))
    return subscriptions + local


def _local_model(config: Any, provider: str) -> str | None:
    brain_cfg = getattr(config, "brain", None)
    if brain_cfg is not None and (brain_cfg.local_fallback or "").strip() == provider:
        picked = (brain_cfg.local_fallback_model or "").strip()
        if picked:
            return picked
    from dodaios.brain import resolver as brain_resolver

    try:
        return brain_resolver._deep_model_for(config, provider)
    except Exception:  # noqa: BLE001 - the provider's own default then
        return None


def available(config: Any) -> bool:
    """Whether a model may be asked right now. Blocking."""
    if _override is not None:
        return True
    return bool(seats(config))


def _instantiate(seat: Seat) -> Any | None:
    from dodaios.brain import resolver as brain_resolver

    registry = brain_resolver._get_registry()
    kwargs: dict[str, Any] = {}
    if seat.model:
        kwargs["model"] = seat.model
    try:
        parameters = set(inspect.signature(registry.get_class(seat.provider)).parameters)
    except Exception:  # noqa: BLE001 - an uninspectable class gets no extra options
        parameters = set()
    if "structured_prompts" in parameters:
        kwargs["structured_prompts"] = True
    if seat.billing == "subscription_or_api" and "prefer_subscription" in parameters:
        # Fail instead of falling through to the card's key slot.
        kwargs["prefer_subscription"] = True
    try:
        return registry.instantiate(seat.provider, **kwargs)
    except Exception as exc:  # noqa: BLE001 - an unusable seat is skipped
        log.info("self_build: %s not instantiable (%s)", seat.provider, type(exc).__name__)
        return None


async def ask(config: Any, system: str, prompt: str, *, max_tokens: int = 1_500) -> str:
    """One completion on the first usable subscription or local seat.

    Raises :class:`BackgroundDeferred` when none can answer; nothing was billed.
    The caller wraps the call in its cost attribution.
    """
    if _override is not None:
        return await _override(system, prompt, max_tokens)
    from dodaios.brain.streaming import aggregate
    from dodaios.core.protocols import BrainMessage, BrainRequest

    candidates = await asyncio.to_thread(seats, config)
    if not candidates:
        raise BackgroundDeferred("no subscription or local model can take self-build work")
    request = BrainRequest(
        system=system,
        messages=(BrainMessage(role="user", content=prompt),),
        temperature=0.1,
        max_tokens=max_tokens,
        stream=True,
    )
    for seat in candidates:
        brain = await asyncio.to_thread(_instantiate, seat)
        if brain is None:
            continue
        try:
            agg = await asyncio.wait_for(aggregate(brain.complete(request)), timeout=TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - try the next seat; the type only (AP-34)
            log.info("self_build: %s did not answer (%s)", seat.provider, type(exc).__name__)
            continue
        if (agg.text or "").strip():
            return agg.text
    raise BackgroundDeferred("no subscription or local model answered")


def provider_for_runs(config: Any) -> str:
    """The provider a self-built routine or agent runs on: the first seat. Blocking.

    ``""`` when there is none; the builder then does not build.
    """
    if _override is not None:
        return _override_provider
    found = seats(config)
    return found[0].provider if found else ""


def set_override(fn: Ask | None, *, provider: str = "") -> None:
    """Test seam: answer every ``ask`` with ``fn`` and run builds on ``provider``.

    ``None`` restores the real seats.
    """
    global _override, _override_provider
    _override = fn
    _override_provider = provider if fn is not None else ""


__all__ = [
    "BackgroundDeferred",
    "Seat",
    "TIMEOUT_S",
    "ask",
    "available",
    "provider_for_runs",
    "seats",
    "set_override",
]
