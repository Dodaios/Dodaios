"""The managed browser's request check: public websites only, redirects included."""

from __future__ import annotations

import asyncio
import socket
import threading

import pytest

from dodaios.society.browser.request_guard import REFUSAL, RequestGuard, named_hosts

ADDRESSES = {
    "example.org": ["93.184.215.14"],
    "router.home": ["192.168.2.1"],
    "mixed.example": ["93.184.215.14", "10.0.0.7"],
    "six.example": ["2606:2800:21f:cb07:6820:80da:af6b:8b2c"],
    "localhost": ["127.0.0.1", "::1"],
    "169.254.169.254": ["169.254.169.254"],
    "127.0.0.1": ["127.0.0.1"],
}


@pytest.fixture
def lookups(monkeypatch):
    """Answer name lookups from a table; returns the names that were asked."""
    asked: list[str] = []

    def getaddrinfo(host, port, *args, **kwargs):
        asked.append(host)
        if host not in ADDRESSES:
            raise socket.gaierror("unknown name")
        return [(None, None, None, "", (address, 0)) for address in ADDRESSES[host]]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return asked


class Session:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.handlers: dict = {}

    def on(self, name, handler) -> None:
        self.handlers[name] = handler

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.sent.append((method, params or {}))
        return {}


async def answers(guard: RequestGuard, session: Session, *events: dict) -> list[tuple[str, dict]]:
    for event in events:
        guard.paused(event)
    await asyncio.gather(*guard.answers)
    return [sent for sent in session.sent if sent[0] != "Fetch.enable"]


def paused(url: str, request_id: str = "r1", kind: str = "Image") -> dict:
    return {"requestId": request_id, "request": {"url": url}, "resourceType": kind}


async def test_every_request_of_the_browser_is_checked_before_it_leaves():
    guard, session = RequestGuard(), Session()
    try:
        await guard.attach(session)
        assert session.sent == [
            ("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
        ]
        assert "Fetch.requestPaused" in session.handlers
    finally:
        guard.close()


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://example.org/page", True),
        ("http://example.org:8080/page", True),
        ("https://six.example/", True),
        ("http://router.home/admin", False),
        ("http://127.0.0.1:47821/api/config", False),
        ("http://localhost:3000/", False),
        ("http://169.254.169.254/latest/meta-data", False),
        # One address inside the network is enough to refuse the name.
        ("https://mixed.example/", False),
        ("https://no-such-name.example/", False),
        ("file:///etc/hosts", False),
        ("ftp://example.org/file", False),
        ("https://example.org:99999/", False),
    ],
)
async def test_only_public_websites_pass(lookups, url, allowed):
    guard = RequestGuard()
    try:
        assert await guard.permits(url, navigation=False) is allowed
    finally:
        guard.close()


async def test_a_refused_request_fails_and_an_allowed_one_goes_on(lookups):
    guard, session = RequestGuard(), Session()
    try:
        await guard.attach(session)
        sent = await answers(
            guard,
            session,
            paused("https://example.org/logo.png", "ok"),
            paused("http://router.home/status", "no"),
        )
        assert ("Fetch.continueRequest", {"requestId": "ok"}) in sent
        assert ("Fetch.failRequest", {"requestId": "no", "errorReason": REFUSAL}) in sent
        assert len(sent) == 2
    finally:
        guard.close()


async def test_a_redirect_into_the_local_network_is_refused(lookups):
    """Each hop of a redirect is paused as a request of its own."""
    guard, session = RequestGuard(), Session()
    try:
        await guard.attach(session)
        first = paused("https://example.org/go", "hop", "Document")
        second = paused("http://127.0.0.1:47821/api/config", "hop", "Document")
        sent = await answers(guard, session, first)
        assert sent == [("Fetch.continueRequest", {"requestId": "hop"})]
        sent = await answers(guard, session, second)
        assert sent[-1] == ("Fetch.failRequest", {"requestId": "hop", "errorReason": REFUSAL})
    finally:
        guard.close()


async def test_a_host_the_agent_was_given_by_name_may_be_local(lookups):
    assert named_hosts(["http*://127.0.0.1", "https://*.example.org", "intranet.home/app"]) == {
        ("127.0.0.1", None),
        ("intranet.home", None),
    }
    guard = RequestGuard(allowed_domains=["http*://127.0.0.1"])
    try:
        assert await guard.permits("http://127.0.0.1:8000/", navigation=True) is True
        assert lookups == []
        # Another local address stays closed.
        assert await guard.permits("http://localhost:8000/", navigation=False) is False
    finally:
        guard.close()


async def test_a_named_host_with_a_port_or_capitals_is_the_same_host(lookups):
    """A grant reads like the navigation check reads it: port and case as written."""
    assert named_hosts(["http://localhost:3000", "MyNAS.local", "192.168.1.20:8080/app"]) == {
        ("localhost", 3000),
        ("mynas.local", None),
        ("192.168.1.20", 8080),
    }
    guard = RequestGuard(
        allowed_domains=["http://localhost:3000", "MyNAS.local", "192.168.1.20:8080/app"]
    )
    try:
        assert await guard.permits("http://localhost:3000/", navigation=True) is True
        assert await guard.permits("http://mynas.local/", navigation=True) is True
        assert await guard.permits("http://MyNAS.local:5000/share", navigation=False) is True
        assert await guard.permits("http://192.168.1.20:8080/app", navigation=True) is True
        assert lookups == []
        # Another port of a host granted with one stays closed.
        assert await guard.permits("http://localhost:3001/", navigation=False) is False
        assert await guard.permits("http://192.168.1.20/", navigation=False) is False
    finally:
        guard.close()


async def test_a_named_port_matches_the_scheme_default_when_the_address_has_none(lookups):
    guard = RequestGuard(allowed_domains=["router.home:443", "http://printer.home:80"])
    try:
        assert await guard.permits("https://router.home/", navigation=True) is True
        assert await guard.permits("http://printer.home/", navigation=True) is True
        assert await guard.permits("http://router.home/", navigation=False) is False
    finally:
        guard.close()


async def test_a_page_opens_only_on_a_site_the_agent_may_open(lookups):
    guard = RequestGuard(navigation_allowed=lambda url: "example.org" not in url)
    try:
        assert await guard.permits("https://example.org/", navigation=True) is False
        # A file of a page that is open is not a navigation.
        assert await guard.permits("https://example.org/app.js", navigation=False) is True
    finally:
        guard.close()


async def test_requests_waiting_for_one_name_share_its_lookup(monkeypatch):
    asked: list[str] = []
    release = threading.Event()
    started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def getaddrinfo(host, port, *args, **kwargs):
        asked.append(host)
        loop.call_soon_threadsafe(started.set)
        release.wait(5)
        return [(None, None, None, "", ("93.184.215.14", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    guard = RequestGuard()
    try:
        waiting = [
            asyncio.ensure_future(guard.permits(f"https://cdn.example/{n}.js", navigation=False))
            for n in range(20)
        ]
        await asyncio.wait_for(started.wait(), 5)
        release.set()
        assert await asyncio.gather(*waiting) == [True] * 20
        assert asked == ["cdn.example"]
        # Nothing is kept: the next request asks the resolver again.
        assert await guard.permits("https://cdn.example/late.js", navigation=False) is True
        assert asked == ["cdn.example", "cdn.example"]
    finally:
        release.set()
        guard.close()


async def test_a_fault_of_the_check_refuses_the_request(lookups):
    def broken(_url: str) -> bool:
        raise RuntimeError("rule failed")

    guard, session = RequestGuard(navigation_allowed=broken), Session()
    try:
        await guard.attach(session)
        sent = await answers(guard, session, paused("https://example.org/", "r", "Document"))
        assert sent == [("Fetch.failRequest", {"requestId": "r", "errorReason": REFUSAL})]
    finally:
        guard.close()


async def test_a_request_that_is_gone_before_its_answer_is_no_error(lookups):
    class Gone(Session):
        async def send(self, method, params=None):
            if method != "Fetch.enable":
                raise RuntimeError("Invalid InterceptionId")
            return {}

    guard, session = RequestGuard(), Gone()
    try:
        await guard.attach(session)
        assert await answers(guard, session, paused("https://example.org/a.png")) == []
    finally:
        guard.close()


def test_the_request_check_ships_with_the_frozen_app():
    """The worker loads it by file beside itself; a build without it starts no browser."""
    from pathlib import Path

    spec = (Path(__file__).parents[3] / "dodaios.spec").read_text(encoding="utf-8")
    assert "dodaios/society/browser/request_guard.py" in spec
