"""Fail fast before a doomed run: is the seat usable at all?

A society assignment or routine run on a seat that real calls already found
dead (a rejected login or key, a model the account does not offer, a usage
limit still open) used to start, burn a turn and fail with the provider's
words. The preflight asks three cheap, billing-free questions first:

1. does seat health (:mod:`dodaios.brain.seat_health`) hold a live verdict;
2. is the subscription logged in (the memoised login probe);
3. is the model id in the account's live model list (CLI seats only; the
   discovery is cached and read-only).

Each answer is readable text with a typed :class:`FailureReason`. An unknown
answer (probe failed, no catalog) is never a refusal. Nothing is switched.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from dodaios.brain import seat_health as sh

from .failure_reasons import FailureReason

log = logging.getLogger(__name__)

__all__ = ["PreflightFailure", "preflight_seat"]

_CATALOG_TIMEOUT_S: Final[float] = 12.0


@dataclass(frozen=True, slots=True)
class PreflightFailure:
    reason: FailureReason
    text: str
    cls: str


_REASON: Final[dict[str, FailureReason]] = {
    sh.CLASS_QUOTA: FailureReason.PROVIDER_QUOTA_LIMIT,
    sh.CLASS_RATE: FailureReason.RATE_LIMITED,
    sh.CLASS_AUTH: FailureReason.AUTH_FAILED,
    sh.CLASS_MODEL: FailureReason.PROVIDER_ERROR,
}


def _live_model_ids(provider: str, account_id: str) -> set[str] | None:
    """The model ids the seat's account lists right now; ``None`` when unknown."""
    if account_id:
        return None  # a named login has its own catalog; not read from here
    from dodaios.agent_chat import runner_cli
    from dodaios.agent_chat.service import resolve_runner

    runner = resolve_runner(provider, surface="society")
    if runner == "codex-cli":
        rows = runner_cli.read_codex_models()
    elif runner == "agy-cli":
        rows = runner_cli.read_agy_models()
    else:
        return None
    ids = {str(r.get("id")) for r in rows or [] if isinstance(r, dict) and r.get("id")}
    return ids or None


async def preflight_seat(
    provider: str,
    model: str,
    account_id: str = "",
    *,
    catalog: Callable[[str, str], set[str] | None] | None = None,
    login: Callable[[str], bool | None] | None = None,
) -> PreflightFailure | None:
    """``None`` when the run may start, else why it would be doomed."""
    if not provider:
        return None
    found = sh.get_seat_health().verdict(provider, account_id, model=model)
    if found is not None and found.cls != sh.CLASS_RATE:
        return PreflightFailure(
            _REASON.get(found.cls, FailureReason.PROVIDER_ERROR),
            f"{provider} is not usable: {found.reason()}.",
            found.cls,
        )
    try:
        if not account_id:
            from dodaios.brain.background_policy import login_state, subscription_capable

            if subscription_capable(provider):
                state = await asyncio.to_thread(login or login_state, provider)
                if state is False:
                    return PreflightFailure(
                        FailureReason.AUTH_FAILED,
                        f"{provider} is not signed in; sign in again before this runs.",
                        sh.CLASS_AUTH,
                    )
        if model:
            ids = await asyncio.wait_for(
                asyncio.to_thread(catalog or _live_model_ids, provider, account_id),
                timeout=_CATALOG_TIMEOUT_S,
            )
            if ids is not None and model not in ids:
                return PreflightFailure(
                    FailureReason.PROVIDER_ERROR,
                    f"The model {model} is not offered on this {provider} account; "
                    "pick another model for the agent.",
                    sh.CLASS_MODEL,
                )
    except Exception:  # noqa: BLE001 — an unknown answer is never a refusal
        log.debug("society: seat preflight inconclusive for %s", provider, exc_info=True)
    return None
