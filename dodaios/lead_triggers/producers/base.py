"""Shared plumbing of the pollers: one authenticated GET with refresh, rate limits and errors.

Producers are plain provider API reads over the owner's existing connection
(the plugin token store). They never call a model and never use an API key.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from email.utils import parseaddr
from typing import Any, Protocol

from dodaios.core.branding import HTTP_USER_AGENT

from ..event import TriggerEvent

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 20.0


class NotConnected(Exception):
    """No usable connection: never connected, or the grant needs a reconnect."""


class AuthError(Exception):
    """The provider refused the token even after one refresh."""


class RateLimited(Exception):
    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"rate limited for {retry_after_s:.0f}s")
        self.retry_after_s = retry_after_s


class ProviderError(Exception):
    """An unexpected provider answer (5xx, a status the poller does not expect)."""


@dataclass(slots=True)
class Poll:
    """What one poll found and where the next one starts."""

    events: list[TriggerEvent] = field(default_factory=list)
    cursor: dict[str, Any] = field(default_factory=dict)
    #: The provider asked for a longer pause (GitHub's poll interval header).
    min_interval_s: float = 0.0


class Producer(Protocol):
    id: str
    source: str

    async def connected(self) -> bool: ...
    async def poll(self, cursor: dict[str, Any], now: float) -> Poll: ...


TokenSource = Callable[[], Awaitable[Any | None]]
Refresher = Callable[[str | None], Awaitable[bool]]


async def default_tokens(plugin_id: str) -> Any | None:
    from dodaios.marketplace.token_store import TokenStore

    return await asyncio.to_thread(TokenStore().load, plugin_id)


async def default_refresh(plugin_id: str, observed: str | None) -> bool:
    from dodaios.marketplace.connect_helpers import build_handler_from_catalog
    from dodaios.marketplace.refresh_scheduler import refresh_plugin_token
    from dodaios.marketplace.token_store import TokenStore

    attempt = await refresh_plugin_token(
        plugin_id, TokenStore(), build_handler_from_catalog, force=True,
        observed_access_token=observed,
    )
    return bool(attempt.usable)


class Api:
    """GET requests as the owner, through the connection the plugin already holds."""

    def __init__(
        self,
        plugin_id: str,
        *,
        transport: Any | None = None,
        tokens: TokenSource | None = None,
        refresh: Refresher | None = None,
    ) -> None:
        from dodaios.core.http_pool import HttpClientPool

        self.plugin_id = plugin_id
        self._tokens = tokens or (lambda: default_tokens(plugin_id))
        self._refresh = refresh or (lambda observed: default_refresh(plugin_id, observed))
        self._pool = HttpClientPool(timeout_s=REQUEST_TIMEOUT_S, transport=transport)

    async def connected(self) -> bool:
        try:
            tokens = await self._tokens()
        except Exception:  # noqa: BLE001 - an unreadable store counts as not connected
            log.debug("lead triggers: token store unreadable", exc_info=True)
            return False
        usable = tokens is not None and not getattr(tokens, "needs_reauth", False)
        return usable and bool(tokens.access)

    async def _headers(self, extra: dict[str, str] | None) -> tuple[dict[str, str], str]:
        tokens = await self._tokens()
        if tokens is None or getattr(tokens, "needs_reauth", False) or not tokens.access:
            raise NotConnected(self.plugin_id)
        headers = {"Authorization": f"Bearer {tokens.access}", "User-Agent": HTTP_USER_AGENT}
        headers.update(extra or {})
        return headers, str(tokens.access)

    async def get(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> Any:
        """The response, for any status the poller can read (2xx, 304, 404, 410).

        A 401 refreshes the token once and retries; a refused refresh is an
        :class:`AuthError`. A 429 (or a spent 403 quota) is :class:`RateLimited`,
        other failures :class:`ProviderError`.
        """
        for attempt in (0, 1):
            auth, observed = await self._headers(headers)
            response = await self._pool.client().get(url, params=params, headers=auth)
            if response.status_code == 401:
                if attempt == 1 or not await self._try_refresh(observed):
                    raise AuthError(self.plugin_id)
                continue
            break
        status = response.status_code
        if status == 429 or (status == 403 and _quota_spent(response)):
            raise RateLimited(_retry_after(response))
        if status >= 500 or status in (400, 403):
            raise ProviderError(f"{self.plugin_id}: HTTP {status}")
        return response

    async def _try_refresh(self, observed: str) -> bool:
        try:
            return bool(await self._refresh(observed))
        except Exception:  # noqa: BLE001 - a failed refresh is an auth error, not a crash
            log.debug("lead triggers: token refresh failed", exc_info=True)
            return False


def _quota_spent(response: Any) -> bool:
    return response.headers.get("x-ratelimit-remaining") == "0" or "Retry-After" in response.headers


def _retry_after(response: Any) -> float:
    raw = response.headers.get("retry-after")
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        log.debug("lead triggers: no usable Retry-After header")
    reset = response.headers.get("x-ratelimit-reset")
    try:
        return max(1.0, float(reset) - time.time())
    except (TypeError, ValueError):
        log.debug("lead triggers: no usable rate-limit reset header")
        return 60.0


def address_of(value: str) -> str:
    """``Name <a@b.c>`` to ``a@b.c`` (lowercase); the text itself when it has no address."""
    parsed = parseaddr(value or "")[1]
    return (parsed or (value or "").strip()).lower()
