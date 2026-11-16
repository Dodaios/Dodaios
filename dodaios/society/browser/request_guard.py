"""The managed browser's request check: public websites only.

Every request the browser sends is checked before it leaves: only http and
https, a page only on a site the agent may open, and no address inside this
computer or its network unless the agent was given that host by name.

The check listens on one CDP session of the whole browser (``Fetch``), not on
Playwright's ``route``. Routing switches the browser's HTTP cache off, so
every visit loaded every file of a page again, and it never shows a redirect
to its handler: a site that redirected into the local network was let
through. Here each hop of a redirect is a request of its own, and the cache
stays on (what the cache answers was checked when it was fetched).

Standalone like the worker that loads it: no Dodaios imports.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger(__name__)
#: Name lookups that may run at once. A name that never answers (a blocked
#: tracker) holds its thread for the resolver's whole timeout; the lookups for
#: the page's own files must not wait behind it.
LOOKUP_THREADS = 32
#: What a refused request looks like to the page: the same failure Playwright's
#: ``route.abort()`` produced (``net::ERR_FAILED``).
REFUSAL = "Failed"


def named_hosts(allowed_domains: Iterable[Any]) -> set[tuple[str, int | None]]:
    """Hosts the agent was given by name; they may lie inside the local network.

    Each is ``(host, port)``: the host in lower case, the port when the grant
    names one (``localhost:3000``), else ``None`` for any port. Read the way
    ``window_actions.navigation_allowed`` reads the same grants, so a page the
    agent may open is never refused here for its port or its capitals.
    """
    named: set[tuple[str, int | None]] = set()
    for pattern in allowed_domains:
        address = str(pattern).split("://")[-1]
        if "*" in address:
            continue
        try:
            target = urlsplit("https://" + address)
            host, port = (target.hostname or "").lower(), target.port
        except ValueError:
            # A grant that cannot be read names no host; the request check stays closed.
            log.warning("Browser grant %r names no readable host; it is ignored", pattern)
            continue
        if host:
            named.add((host, port))
    return named


_DEFAULT_PORTS = {"http": 80, "https": 443}


class RequestGuard:
    """Decides for each request of the browser whether it may leave."""

    def __init__(
        self,
        *,
        allowed_domains: Iterable[Any] = (),
        navigation_allowed: Callable[[str], bool] = lambda _url: True,
    ) -> None:
        self.named_hosts = named_hosts(allowed_domains)
        self.navigation_allowed = navigation_allowed
        self.session: Any = None
        self.lookups: dict[str, asyncio.Future[bool]] = {}
        self.answers: set[asyncio.Future] = set()
        self.pool = ThreadPoolExecutor(
            max_workers=LOOKUP_THREADS, thread_name_prefix="browser-lookup"
        )

    async def attach(self, session: Any) -> None:
        """Check every request of the browser this CDP session belongs to."""
        session.on("Fetch.requestPaused", self.paused)
        await session.send(
            "Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}
        )
        self.session = session

    def close(self) -> None:
        for answer in list(self.answers):
            answer.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def paused(self, event: dict) -> None:
        answer = asyncio.ensure_future(self.answer(event))
        self.answers.add(answer)
        answer.add_done_callback(self.answers.discard)

    async def answer(self, event: dict) -> None:
        request_id = event.get("requestId")
        try:
            request = event.get("request") or {}
            allowed = await self.permits(
                str(request.get("url") or ""), navigation=event.get("resourceType") == "Document"
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # A fault of the check must never let a request through.
            log.warning("Browser request check failed; the request is refused", exc_info=True)
            allowed = False
        try:
            if allowed:
                await self.session.send("Fetch.continueRequest", {"requestId": request_id})
            else:
                await self.session.send(
                    "Fetch.failRequest", {"requestId": request_id, "errorReason": REFUSAL}
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # The page went away while its request waited; nothing is left to answer.
            log.debug("Browser request was gone before its answer", exc_info=True)

    async def permits(self, url: str, *, navigation: bool) -> bool:
        """Whether this request may leave the browser."""
        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            parsed.port  # noqa: B018 — reading it is the check: a port out of range raises
        except ValueError:
            # An address that cannot be read is denied at the network boundary.
            return False
        if parsed.scheme not in {"http", "https"}:
            return False
        if navigation and not self.navigation_allowed(url):
            return False
        port = parsed.port or _DEFAULT_PORTS[parsed.scheme]
        if any(
            host.lower() == named and named_port in (None, port)
            for named, named_port in self.named_hosts
        ):
            return True
        return await self.public(host)

    async def public(self, host: str) -> bool:
        """Whether every address of ``host`` is on the public internet.

        Requests waiting for the same name share one lookup. Nothing is kept
        after it: the next request asks the resolver again, which keeps its
        own cache for as long as the name's owner allows.
        """
        lookup = self.lookups.get(host)
        if lookup is None:
            lookup = asyncio.ensure_future(self.resolve(host))
            self.lookups[host] = lookup
            lookup.add_done_callback(lambda _done: self.lookups.pop(host, None))
        return await asyncio.shield(lookup)

    async def resolve(self, host: str) -> bool:
        try:
            addresses = await asyncio.get_running_loop().run_in_executor(
                self.pool, lambda: socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            )
            return bool(addresses) and all(
                ipaddress.ip_address(address[4][0]).is_global for address in addresses
            )
        except (OSError, ValueError):
            # An unresolved or invalid destination is denied at the network boundary.
            return False
