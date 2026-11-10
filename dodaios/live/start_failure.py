"""Why a voice call could not start, as one sentence the person can act on.

A start can fail in the account (plan, login, allowance), in the provider
(key, credit, model), in the network, or in Dodaios itself while it is still
booting. Each of those already has fixed, authored text somewhere; this module
finds it. Anything it does not recognise returns ``None`` and the surface
shows its generic line: provider bodies, credentials and URLs never pass
through here (issue #828).
"""

from __future__ import annotations

TIMED_OUT = (
    "The voice service did not answer in time. Check the internet connection, "
    "then try again."
)


def _chain(error: BaseException):
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def start_failure_reason(error: BaseException | str | None) -> str | None:
    """Return the authored sentence behind a start failure, or ``None``."""
    from dodaios.core.protocols import VoiceStartError
    from dodaios.live.subscription_auth import SubscriptionAuthError
    from dodaios.plugins.realtime.openai_subscription_live import (
        SubscriptionLiveError,
        static_failure_message,
    )

    if not isinstance(error, BaseException):
        return static_failure_message(error)
    for current in _chain(error):
        if isinstance(current, SubscriptionLiveError):
            return static_failure_message(current)
        if isinstance(current, SubscriptionAuthError):
            # Every SubscriptionAuthError is raised with fixed text.
            return str(current) or None
        if isinstance(current, VoiceStartError):
            return current.user_message or None
    if any(isinstance(current, TimeoutError) for current in _chain(error)):
        return TIMED_OUT
    return static_failure_message(str(error))
