"""A realtime voice provider that said no, in plain words and remembered.

A call through a realtime provider can be refused before a single word is
spoken: the account's plan does not include that voice route (HTTP 404 or
403 on it), the key is wrong (401), the credit is used up or the provider is
rate limited (429), or it cannot be reached at all. Until 2026-11-10 such a
refusal ended the call after ~12 s with ``hangup_reason=error`` and nothing
for the person to read, and the next call tried the same dead provider first.

This module is the one place that

* classifies a start failure into a small vocabulary of refusal kinds
  (:func:`describe`), preferring the authored ``code`` a
  :class:`~dodaios.core.protocols.VoiceStartError` carries over text matching;
* remembers the refusal in the provider health ledger
  (:func:`remember`) so the status dots and the next call's provider order
  (:func:`order_by_health`) know about it, each kind for as long as waiting
  could plausibly change it (:data:`SKIP_FOR_S`);
* words the refusal for the person (:func:`sentence`) from the phrase catalog,
  and tells every surface about it in one go (:func:`announce`): the
  ``VoiceProviderRefused`` bus event the call window reads and a notice in
  the lead's conversation.

Nothing here opens a provider connection, and no provider body, credential
or URL ever passes through (AP-34): only the classification survives.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Final

from dodaios.i18n import catalog as i18n_catalog

log = logging.getLogger(__name__)

#: The account or its plan does not offer this voice route (404/403, a model
#: the account cannot use, "not offered"). Waiting does not help.
KIND_PLAN: Final[str] = "plan"
#: The credential was rejected (401). Waiting does not help; a new key does.
KIND_KEY: Final[str] = "key"
#: Credit or quota is used up. A top-up helps; waiting an hour might.
KIND_CREDIT: Final[str] = "credit"
#: Rate limited. Waiting a minute or two helps.
KIND_BUSY: Final[str] = "busy"
#: Timeout or network failure. Waiting a little helps.
KIND_UNREACHABLE: Final[str] = "unreachable"
#: The provider rejected the session settings (400/422). Waiting does not help.
KIND_REJECTED: Final[str] = "rejected"

KINDS: Final[tuple[str, ...]] = (
    KIND_PLAN,
    KIND_KEY,
    KIND_CREDIT,
    KIND_BUSY,
    KIND_UNREACHABLE,
    KIND_REJECTED,
)

#: How long a remembered refusal keeps a provider out of first place. Chosen
#: per kind by how an outside fix would reach the app: a changed key or model
#: voids the ledger entry at once (so the long windows cost nothing then), a
#: plan upgrade or a top-up happens outside the app and is noticed by retrying.
SKIP_FOR_S: Final[dict[str, float]] = {
    KIND_PLAN: 2 * 60 * 60.0,
    KIND_KEY: 24 * 60 * 60.0,
    KIND_CREDIT: 60 * 60.0,
    KIND_BUSY: 2 * 60.0,
    KIND_UNREACHABLE: 60.0,
    KIND_REJECTED: 60 * 60.0,
}

#: What the call does after the refusal; carried on the event and the notice.
CONTINUED_PIPELINE: Final[str] = "pipeline"
CONTINUED_REALTIME: Final[str] = "realtime"
CONTINUED_NONE: Final[str] = ""

_HTTP_PLAN_RE = re.compile(r"\bHTTP\s*(?:403|404)\b")
_HTTP_KEY_RE = re.compile(r"\bHTTP\s*401\b")
_HTTP_SETTINGS_RE = re.compile(r"\bHTTP\s*(?:400|422)\b")

# ``VoiceStartError.code`` values the realtime plugins author today.
_CODE_KINDS: Final[dict[str, str]] = {
    "bad_key": KIND_KEY,
    "access_denied": KIND_PLAN,
    "model_unavailable": KIND_PLAN,
    "not_offered": KIND_PLAN,
    "voice_not_offered": KIND_PLAN,
    "no_credits": KIND_CREDIT,
    "quota_exhausted": KIND_CREDIT,
    "authentication_required": KIND_KEY,
    "rate_limited": KIND_BUSY,
    "unreachable": KIND_UNREACHABLE,
    "invalid_configuration": KIND_REJECTED,
}


@dataclass(frozen=True, slots=True)
class Refusal:
    """One classified refusal: its kind and the ledger status it maps to."""

    kind: str
    #: Vocabulary of :mod:`dodaios.brain.provider_test`; ``""`` when the
    #: ledger keeps no record of this kind.
    status: str = ""
    #: The refusal came from a subscription login (an external account), not
    #: from an API key the person pays by usage.
    subscription: bool = False

    @property
    def waiting_helps(self) -> bool:
        """Whether simply trying again a little later could succeed."""
        return self.kind in {KIND_BUSY, KIND_UNREACHABLE}

    @property
    def overrides_fallback_block(self) -> bool:
        """Whether this refusal may continue a call on the classic path even
        for a provider that forbids ambient usage-billed fallback.

        Only a definitive refusal (plan, key, credit, settings) of a
        usage-billed provider does: the person already pays that provider by
        usage, and nothing is gained by ending the call. A subscription that
        refused keeps the rule it was pinned for (the call ends with the
        reason; issue #828), and a transient failure may still answer.
        """
        return not self.waiting_helps and not self.subscription

    @property
    def skip_for_s(self) -> float:
        return SKIP_FOR_S.get(self.kind, 60.0)


def _ledger_status(kind: str) -> str:
    from dodaios.brain import provider_test as pt

    return {
        KIND_PLAN: pt.MODEL_UNAVAILABLE,
        KIND_KEY: pt.BAD_KEY,
        KIND_CREDIT: pt.NO_CREDITS,
        KIND_BUSY: pt.RATE_LIMITED,
        KIND_UNREACHABLE: pt.UNREACHABLE,
    }.get(kind, "")


def _kind_of_status(status: str) -> str | None:
    from dodaios.brain import provider_test as pt

    return {
        pt.MODEL_UNAVAILABLE: KIND_PLAN,
        pt.BAD_KEY: KIND_KEY,
        pt.NO_CREDITS: KIND_CREDIT,
        pt.RATE_LIMITED: KIND_BUSY,
        pt.UNREACHABLE: KIND_UNREACHABLE,
    }.get(status)


def refusal_of_kind(kind: str, *, subscription: bool = False) -> Refusal:
    return Refusal(kind=kind, status=_ledger_status(kind), subscription=subscription)


#: Exception class-name fragments of the subscription (external login) stack.
#: Matched by name so no plugin is imported here (AP-28).
_SUBSCRIPTION_ERROR_TOKENS: Final[tuple[str, ...]] = ("Subscription",)


def _from_subscription(error: BaseException) -> bool:
    for current in _chain(error):
        names = [cls.__name__ for cls in type(current).__mro__]
        if any(token in name for name in names for token in _SUBSCRIPTION_ERROR_TOKENS):
            return True
    return False


def provider_uses_external_login(provider_id: str | None) -> bool:
    """Whether the realtime plugin ``provider_id`` is backed by an account
    login rather than an API key (a capability read, never a name check)."""
    if not provider_id:
        return False
    try:
        from dodaios.core.registry import load
        from dodaios.realtime.protocol import RealtimeProvider

        provider_cls = load("jarvis.realtime", provider_id, protocol=RealtimeProvider)
    except Exception:  # noqa: BLE001 — an unloadable plugin is not a subscription
        return False
    if str(getattr(provider_cls, "external_credentials_kind", "") or ""):
        return True
    return callable(getattr(provider_cls, "external_login_ready", None))


def _chain(error: BaseException):
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def describe(error: BaseException | str | None) -> Refusal | None:
    """Classify a start failure; ``None`` when it is not a provider's refusal.

    An authored ``code`` on a ``VoiceStartError`` anywhere in the exception
    chain wins. Otherwise the health ledger's strict classifier decides, with
    one addition it does not make: an HTTP 403/404 on the realtime route is a
    plan refusal even when the body does not mention a model (the live
    incident of 2026-11-10 was exactly that and left no trace anywhere).
    """
    if error is None:
        return None
    text = str(error) if isinstance(error, str) else ""
    subscription = False
    if isinstance(error, BaseException):
        subscription = _from_subscription(error)
        for current in _chain(error):
            code = str(getattr(current, "code", "") or "")
            if code in _CODE_KINDS:
                return refusal_of_kind(_CODE_KINDS[code], subscription=subscription)
        text = " ".join(f"{type(c).__name__}: {c}" for c in _chain(error))
    elif error in _CODE_KINDS:
        return refusal_of_kind(_CODE_KINDS[error])
    from dodaios.brain import provider_test as pt
    from dodaios.brain.provider_health_ledger import failure_status

    status = failure_status(error, strict=True)
    kind = _kind_of_status(status)
    if kind is None and status not in {pt.OK}:
        if _HTTP_KEY_RE.search(text):
            kind = KIND_KEY
        elif _HTTP_PLAN_RE.search(text):
            kind = KIND_PLAN
        elif _HTTP_SETTINGS_RE.search(text):
            kind = KIND_REJECTED
    return refusal_of_kind(kind, subscription=subscription) if kind else None


def remember(provider: str | None, refusal: Refusal, *, model: str | None = None) -> None:
    """Record the refusal in the provider health ledger (never raises)."""
    if not provider or not refusal.status:
        return
    from dodaios.brain import provider_health_ledger as ledger

    ledger.record_status(provider, ledger.MODALITY_REALTIME, refusal.status, model=model)


def fresh_refusal(provider: str | None, *, now: float | None = None) -> Refusal | None:
    """The refusal still held against ``provider``, or ``None``.

    Reads the ledger's effective realtime outcome and applies this module's
    per-kind window on top of the ledger's own expiry: a key the person just
    replaced is already gone from the ledger, a plan refusal from this
    morning is still fresh, one from yesterday is not.
    """
    if not provider:
        return None
    from dodaios.brain import provider_health_ledger as ledger

    outcome = ledger.effective_outcome(provider, ledger.MODALITY_REALTIME)
    if outcome is None:
        return None
    kind = _kind_of_status(str(outcome.status))
    if kind is None:
        return None
    refusal = refusal_of_kind(kind)
    current = time.time() if now is None else now
    if current - float(outcome.at) > refusal.skip_for_s:
        return None
    return refusal


def order_by_health(provider_ids: list[str]) -> list[str]:
    """The providers a call should try, in order, given what they said last time.

    Untouched providers keep their configured order. One that was busy or
    unreachable a moment ago goes last (it may well answer now). One whose
    account, key or credit refused the last call is left out for its window
    (:data:`SKIP_FOR_S`): trying it again would only spend the same twelve
    seconds on the same answer, and when it is the only one configured the
    session builder answers "none", which is how the call reaches the classic
    path at once instead of after a second refusal.
    """
    kept: list[str] = []
    demoted: list[str] = []
    skipped: list[str] = []
    for provider_id in provider_ids:
        refusal = fresh_refusal(provider_id)
        if refusal is None:
            kept.append(provider_id)
        elif refusal.waiting_helps:
            demoted.append(provider_id)
        else:
            skipped.append(provider_id)
    if demoted:
        log.info("Realtime providers demoted after a recent refusal: %s", ", ".join(demoted))
    if skipped:
        log.info("Realtime providers skipped after a refusal that waiting cannot fix: %s",
                 ", ".join(skipped))
    return [*kept, *demoted]


def provider_label(provider_id: str | None) -> str:
    """A readable name for a provider id ("openai-live" -> "openai live")."""
    text = str(provider_id or "").strip()
    return text.replace("_", " ").replace("-", " ") or "the voice provider"


def sentence(
    refusal: Refusal,
    *,
    provider: str | None,
    language: str | None,
    continued_on: str = CONTINUED_NONE,
) -> str:
    """The refusal and what happens next, in the person's language."""
    kind = refusal.kind if refusal.kind in KINDS else KIND_REJECTED
    why = i18n_catalog.t(
        f"speech.provider_refused.{kind}", language, provider=provider_label(provider)
    )
    tail_key = {
        CONTINUED_PIPELINE: "continued_pipeline",
        CONTINUED_REALTIME: "continued_realtime",
    }.get(continued_on, "ended")
    return f"{why} {i18n_catalog.t(f'speech.provider_refused.{tail_key}', language)}"


async def announce(
    bus: Any,
    *,
    session_id: str,
    provider: str | None,
    refusal: Refusal,
    language: str | None,
    continued_on: str = CONTINUED_NONE,
    message: str | None = None,
) -> str:
    """Tell every surface about the refusal; returns the sentence used.

    Publishes ``VoiceProviderRefused`` (the call window and the status
    surfaces read it) and posts a notice into the lead's one conversation.
    Never raises: a failure to announce must not cost the call that is still
    being saved.
    """
    text = message or sentence(
        refusal, provider=provider, language=language, continued_on=continued_on
    )
    log.warning(
        "Voice provider refused (provider=%s kind=%s continued_on=%s)",
        provider or "?",
        refusal.kind,
        continued_on or "none",
    )
    if bus is not None:
        try:
            from dodaios.core.events import VoiceProviderRefused

            await bus.publish(
                VoiceProviderRefused(
                    session_id=str(session_id or ""),
                    provider=str(provider or ""),
                    kind=refusal.kind,
                    message=text,
                    continued_on=continued_on,
                )
            )
        except Exception:  # noqa: BLE001 — the announcement must never end the call
            log.debug("VoiceProviderRefused not published", exc_info=True)
    await _post_lead_notice(text, provider=provider, kind=refusal.kind, continued_on=continued_on)
    return text


async def _post_lead_notice(
    text: str, *, provider: str | None, kind: str, continued_on: str
) -> None:
    try:
        from dodaios.agent_chat.lead import lead_session
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        svc = runtime.chat_service() if runtime is not None else None
        if svc is None:
            return
        session = lead_session(svc, create=False)
        if session is None:
            return
        await svc.post_notice(
            session.session_id,
            {
                "kind": "voice_provider_refused",
                "status": "done",
                "text": text,
                "provider": str(provider or ""),
                "refusal": kind,
                "continued_on": continued_on,
            },
        )
    except Exception:  # noqa: BLE001 — the conversation is a courtesy copy, not the call
        log.debug("voice provider refusal notice not posted", exc_info=True)


__all__ = [
    "CONTINUED_NONE",
    "CONTINUED_PIPELINE",
    "CONTINUED_REALTIME",
    "KINDS",
    "KIND_BUSY",
    "KIND_CREDIT",
    "KIND_KEY",
    "KIND_PLAN",
    "KIND_REJECTED",
    "KIND_UNREACHABLE",
    "SKIP_FOR_S",
    "Refusal",
    "announce",
    "describe",
    "fresh_refusal",
    "order_by_health",
    "provider_label",
    "provider_uses_external_login",
    "refusal_of_kind",
    "remember",
    "sentence",
]
