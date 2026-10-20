"""An agent's own seat as the brain for its background memory work.

Maintainer decision (2026-09-30): an agent's memory updates run on exactly the
provider, model and auth mode that agent's chat runs on. An agent on the
Claude API key with a chosen model reviews on that key and that model; one on
the Claude subscription reviews on that subscription; one on the ChatGPT
subscription on that one. Nothing else is ever asked. Before, reviews walked
a chain of other providers and landed on keys nobody chose for that work: one
agent's own key answered 401 and its reviews fell through to an unrelated
per-token key for a month.

The background billing rule (``brain.background_policy``) still applies to
an agent's seat: Society reviews and skill learning are unattended, so once a
subscription is connected an agent whose chat bills a per-token API key does
not have that key billed for its memory work. :func:`agent_brain` raises
:class:`SeatDeferred` instead (and no other seat is asked); on an install
that never connected a subscription the key seat answers as before.

A seat that cannot be resolved, or that fails, raises here and the caller's
own bounded retry applies (the Society review queue, the learning loop's
backoff); after that the work is dropped. There is no fallback to another
provider, another model, a subscription the agent does not sit on, or a key
the agent does not use.

Three callers share this module: the Society turn review
(``society/review.py``), Society skill learning (``society/learning.py``)
and Jarvis' own learning loop (``memory/learning``), whose seat is the Jarvis
lead's: the front-page chat's pick. That loop is the one exception to the
billing rule (maintainer decision 2026-10-20): it is not held off a key, and
:func:`subscription_twin` moves a key seat onto the same family's signed-in
subscription first (``memory.learning.review.seat_choices``).

"The seat" is read from the same places the chat reads it, so the two cannot
disagree:

* the provider/model pair: ``chat_binding.pair_for`` for an agent;
  ``model_selection.worker_selection`` + ``task_agent.subscription_seat`` for
  Jarvis, exactly as ``AgentChatService.send`` reseats the front-page chat;
* the runner: ``agent_chat.service.resolve_runner``. A vendor CLI seat answers
  through that CLI's brain in structured mode; an API seat through the
  provider's own brain plugin behind the Agents-tab key
  (``get_jarvis_agent_secret``, as ``runner_brain`` does for the chat);
* the instance: ``brain.resolver.resolve_browser_brain``, the resolver of an
  agent's existing access with a structured-output contract.

Everything that may block (a login probe, the keyring, plugin construction)
runs in a worker thread, off the desktop event loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "Seat",
    "SeatBrain",
    "SeatCallFailed",
    "SeatDeferred",
    "SeatUnavailable",
    "agent_brain",
    "agent_seat",
    "bills_per_token",
    "hold_to_background_policy",
    "jarvis_seat",
    "seat_brain",
    "subscription_twin",
]

#: Runners that are a provider's own API behind a key, not a vendor CLI.
_KEYED_RUNNERS: Final[frozenset[str]] = frozenset({"brain", "api"})


class SeatUnavailable(RuntimeError):
    """The seat cannot be built right now; no other provider is asked instead.

    The message is app-authored (never a provider's error body, AP-34).
    """


class SeatDeferred(SeatUnavailable):
    """The seat bills a per-token key and background work may not bill it now.

    Raised for unattended Society work while a subscription is connected
    (``brain.background_policy``). The message is app-authored and names the
    reason, so a status line can show it; ``provider`` is the seat's provider,
    for a UI that words the reason itself.
    """

    def __init__(self, message: str, *, provider: str = "") -> None:
        super().__init__(message)
        self.provider = provider


class SeatCallFailed(RuntimeError):
    """A call on the seat failed. Carries the exception type, never its text:
    a provider error body must not reach a log line (AP-34)."""


@dataclass(frozen=True, slots=True)
class Seat:
    """What a chat runs on: provider, model and the runner behind them."""

    provider: str
    #: ``""`` = the seat's own default (the CLI's, or the provider's
    #: router-tier model, exactly as the chat picks it).
    model: str = ""
    #: ``brain``/``api`` = the provider API behind a key; else a CLI runner id.
    runner: str = "brain"
    #: Whether the Agents-tab key slot applies. ``False`` for an explicit
    #: ``[memory.learning]`` provider override, which uses the provider's
    #: ordinary credential chain.
    agent_key: bool = True

    @property
    def keyed(self) -> bool:
        return self.runner in _KEYED_RUNNERS

    def describe(self) -> str:
        return f"{self.provider}/{self.model or 'default model'}"


def agent_seat(config: Any, agent: Any) -> Seat:
    """The seat of a Society agent's own chat. Blocking: call it in a thread."""
    from dodaios.agent_chat.service import resolve_runner

    from .chat_binding import pair_for

    try:
        provider, model, _effort = pair_for(config, agent)
    except PermissionError as exc:
        raise SeatUnavailable(str(exc) or "no provider can run this agent's chat") from None
    if not provider:
        raise SeatUnavailable("this agent's chat names no provider")
    account = getattr(agent, "account_id", "") if provider == agent.provider else ""
    if str(getattr(agent, "runtime", "") or "jarvis") != "jarvis":
        return _runtime_seat(provider, model or "", account)
    return Seat(
        provider, model or "", resolve_runner(provider, surface="society", account_id=account)
    )


def _runtime_seat(provider: str, model: str, account: str) -> Seat:
    """The seat of a Hermes / OpenClaw agent: the auth its gateway route uses.

    Jarvis' model gateway answers such an agent on the provider's API key, or
    on the Claude login when the agent is pinned to it or no key is saved
    (``model_map.login_token_for``). ``resolve_runner`` alone would prefer
    Claude Code for an unpinned agent, so its reviews would run on the plan
    while its chat bills the key. The login is reachable for a review only
    through Claude Code; without it the seat is unavailable, never a key.
    """
    from dodaios.agent_chat.catalog import API_KEY_ACCOUNT, SUBSCRIPTION_ACCOUNT
    from dodaios.agent_chat.service import resolve_runner
    from dodaios.agent_runtimes.model_map import login_token_for

    on_login = login_token_for(provider, account) is not None
    pinned = SUBSCRIPTION_ACCOUNT if on_login else API_KEY_ACCOUNT
    runner = resolve_runner(provider, surface="society", account_id=pinned)
    if on_login and runner in _KEYED_RUNNERS:
        raise SeatUnavailable(
            "this agent's chat runs on the Claude login, which only Claude Code can "
            "use for a review, and Claude Code is not installed"
        )
    return Seat(provider, model, runner)


def jarvis_seat(config: Any) -> Seat:
    """The Jarvis lead's seat: what the front-page chat answers on right now.

    The Agents selection (``[brain.worker]``) when one is set, mapped onto its
    subscription seat the way ``AgentChatService.send`` maps it; otherwise the
    Agents tier, which is what a chat with no provider of its own runs on.
    Blocking (the Claude login probe, the credential probes): call it in a
    thread.
    """
    from dodaios.core.model_selection import worker_selection
    from dodaios.core.task_agent import subscription_seat

    selection = worker_selection(config)
    if selection is not None:
        provider, runner = subscription_seat(selection.provider) or (selection.provider, "brain")
        return Seat(provider, selection.model or "", runner)
    from dodaios.agent_chat.service import resolve_runner
    from dodaios.local_models.assistant_session import agents_tier

    tier = agents_tier(config)
    if not tier.ready or not tier.provider:
        raise SeatUnavailable(tier.reason or "no provider can run the Dodaios chat")
    return Seat(tier.provider, tier.model or "", resolve_runner(tier.provider, surface="jarvis"))


def _chat_default_model(config: Any, provider: str) -> str:
    """The model an API seat's chat runs when it names none.

    ``runner_brain`` asks ``BrainManager._fast_model``: the provider's
    configured model, else its router-tier default. Read from the config here
    so a review drained before the brain manager exists never falls to a
    plugin's hardcoded default (for a gateway that can be a paid frontier
    model the person never picked).
    """
    from dodaios.brain.manager import get_tier_default_model

    providers = getattr(getattr(config, "brain", None), "providers", None) or {}
    configured = str(getattr(providers.get(provider), "model", "") or "")
    return configured or get_tier_default_model("router", provider) or ""


def _cli_adapter(seat: Seat, model: str) -> Any:
    """A CLI seat with no brain plugin of its own, adapted like the browser does."""
    from dodaios.agent_chat.catalog import provider_row

    row = provider_row(seat.provider)
    if row is None or row.runner != "grok-cli":
        raise SeatUnavailable(f"the {seat.provider} seat has no background model in this app")
    from dodaios.agent_chat.browser_model import GrokBrowserModel
    from dodaios.brain.usage_meter import meter_brain

    return meter_brain(GrokBrowserModel(model), seat.provider)


def _build(config: Any, seat: Seat, caller: str) -> SeatBrain:
    """Instantiate exactly ``seat``. Blocking: call it in a thread."""
    from dodaios.brain.resolver import resolve_browser_brain

    model = seat.model
    if seat.keyed and not model:
        model = _chat_default_model(config, seat.provider)
    try:
        inner = resolve_browser_brain(config, seat.provider, model, runner=seat.runner)
    except LookupError:  # no brain plugin: a CLI adapter, or SeatUnavailable
        inner = _cli_adapter(seat, model)
    except Exception as exc:  # noqa: BLE001 - reported by type; the text may be a provider's
        raise SeatUnavailable(
            f"the {seat.provider} seat could not be built ({type(exc).__name__})"
        ) from None
    secrets: dict[str, str] = {}
    if seat.keyed and seat.agent_key:
        from dodaios.core.config import get_jarvis_agent_secret

        try:
            secret = get_jarvis_agent_secret(seat.provider)
        except Exception as exc:  # noqa: BLE001 - no dedicated key: the family key answers
            # Same as the chat (``runner_brain._agent_secret``): without an
            # Agents-tab key the provider resolves its ordinary credential.
            log.debug(
                "seat brain: no Agents-tab key for %s (%s)", seat.provider, type(exc).__name__
            )
            secret = None
        if secret:
            secrets[seat.provider] = secret
    return SeatBrain(inner, seat, secrets=secrets, caller=caller)


async def seat_brain(config: Any, seat: Seat, *, caller: str) -> SeatBrain:
    """``seat`` as a Brain, built off the event loop. Raises ``SeatUnavailable``."""
    return await asyncio.to_thread(_build, config, seat, caller)


async def agent_brain(config: Any, agent: Any, *, caller: str) -> SeatBrain:
    """A Society agent's own seat as a Brain. Raises ``SeatUnavailable``."""

    def resolve() -> SeatBrain:
        seat = agent_seat(config, agent)
        hold_to_background_policy(seat)
        return _build(config, seat, caller)

    return await asyncio.to_thread(resolve)


def bills_per_token(seat: Seat) -> bool:
    """Whether a call on ``seat`` spends a per-token API key.

    A CLI runner answers on its subscription; a keyed runner on a keyless
    local provider (by its provider card or its chat-catalog row) bills
    nothing. Decided from cards and rows, never a provider name (AP-21).
    """
    if not seat.keyed:
        return False
    from dodaios.brain.background_policy import keyless_local

    if keyless_local(seat.provider):
        return False
    try:
        from dodaios.agent_chat.catalog import provider_row
    except Exception:  # noqa: BLE001 - without the catalog a keyed seat counts as billed
        return True
    row = provider_row(seat.provider)
    return not (row is not None and bool(getattr(row, "keyless", False)))


def subscription_twin(seat: Seat) -> Seat | None:
    """The same provider family's subscription seat, when it is signed in now.

    For a seat that bills a per-token key: the subscription card whose chat row
    has the key row's brand family (``catalog.ProviderRow.family``; the OpenAI
    key and the ChatGPT login through Codex, the Anthropic key and the Claude
    login through Claude Code). Only a login the probe reports signed in right
    now counts. Its model is kept when that subscription offers it, else the
    subscription's own default answers. Decided from rows and cards, never a
    provider name (AP-21). Blocking (the login probe): call it in a thread.
    """
    if not bills_per_token(seat):
        return None
    from dodaios.agent_chat.catalog import provider_row
    from dodaios.brain.background_policy import login_state, subscription_capable
    from dodaios.core.task_agent import subscription_seats

    own = provider_row(seat.provider)
    if own is None:
        return None
    for card, (row_id, runner) in subscription_seats().items():
        row = provider_row(row_id)
        if row is None or row.family != own.family or not subscription_capable(card):
            continue
        if login_state(card) is not True:
            continue
        offered = {model.id for model in row.curated_models}
        model = seat.model if row.id == seat.provider or seat.model in offered else ""
        return Seat(row.id, model, runner)
    return None


def hold_to_background_policy(seat: Seat) -> None:
    """Refuse a per-token seat for unattended work once a subscription is connected.

    Blocking (the login probe): call it in a thread. Raises
    :class:`SeatDeferred`; returns quietly for a subscription or local seat
    and on an install that never connected a subscription.
    """
    if not bills_per_token(seat):
        return
    from dodaios.brain.background_policy import subscription_mode

    if subscription_mode((seat.provider,)):
        raise SeatDeferred(
            f"a subscription is connected, so background memory work does not bill "
            f"this agent's API key ({seat.provider}); put the agent on a subscription "
            "or local model for it to learn from its chats",
            provider=seat.provider,
        )


class SeatBrain:
    """One seat's brain: every call runs under that seat's credential and is
    written to the usage ledger under ``caller``.

    The credential override is entered around each step of the stream, never
    across a ``yield``, so it is always reset in the context that set it,
    however the consumer ends the stream. Attributes other than ``complete``
    forward to the seat's own brain (``name``, ``context_window``, ...).
    """

    __slots__ = ("_caller", "_inner", "_secrets", "seat")

    def __init__(
        self, inner: Any, seat: Seat, *, secrets: Mapping[str, str], caller: str
    ) -> None:
        self._inner = inner
        self.seat = seat
        self._secrets = dict(secrets)
        self._caller = caller

    def __getattr__(self, name: str) -> Any:
        if name in SeatBrain.__slots__ or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    def __repr__(self) -> str:  # pragma: no cover - logging nicety
        return f"SeatBrain({self.seat.describe()}, runner={self.seat.runner})"

    @contextmanager
    def _scope(self) -> Iterator[None]:
        from dodaios.core.config import override_provider_secrets
        from dodaios.costs.ledger import usage_context

        # Exactly this seat's credentials: an override inherited from whatever
        # task scheduled this work never reaches the call.
        with usage_context(self._caller), override_provider_secrets(self._secrets):
            yield

    def complete(self, request: Any) -> AsyncIterator[Any]:
        return self._stream(request)

    async def _stream(self, request: Any) -> AsyncIterator[Any]:
        iterator: Any = None
        try:
            with self._scope():
                iterator = self._inner.complete(request).__aiter__()
            while True:
                with self._scope():
                    try:
                        delta = await iterator.__anext__()
                    except StopAsyncIteration:  # the seat's stream ended normally
                        return
                yield delta
        except Exception as exc:  # noqa: BLE001 - re-raised without the provider's text
            raise SeatCallFailed(
                f"the {self.seat.describe()} seat failed ({type(exc).__name__})"
            ) from None
        finally:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()
