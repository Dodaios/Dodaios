"""Regression tests for the DDGS Yahoo fallback."""

from types import SimpleNamespace

import httpx
import pytest

from dodaios.plugins.tool import search_backends as sb


def fake_result(status, results):
    return SimpleNamespace(
        backend="ddg_serp",
        status=status,
        results=results,
    )


@pytest.mark.asyncio
async def test_yahoo_not_used_when_primary_succeeds(monkeypatch):
    calls = []

    async def fake_serp(query, max_results, *, searcher=None):
        calls.append(searcher)
        return fake_result(
            "ok",
            [{"title": "Python", "url": "https://www.python.org/"}],
        )

    monkeypatch.setattr(sb, "ddg_serp_search", fake_serp)

    async with httpx.AsyncClient() as client:
        result = await sb.run_search("Python", 3, client=client)

    assert result.status == "ok"
    assert len(calls) == 1
    assert calls[0] is None


@pytest.mark.asyncio
async def test_yahoo_used_when_primary_empty(monkeypatch):
    calls = []

    async def fake_serp(query, max_results, *, searcher=None):
        calls.append(searcher)

        if searcher is None:
            return fake_result("empty", [])

        return fake_result(
            "ok",
            [{"title": "Python", "url": "https://www.python.org/"}],
        )

    monkeypatch.setattr(sb, "ddg_serp_search", fake_serp)

    async with httpx.AsyncClient() as client:
        result = await sb.run_search("Python", 3, client=client)

    assert result.status == "ok"
    assert len(result.results) == 1
    assert len(calls) == 2
    assert calls[0] is None
    assert callable(calls[1])


@pytest.mark.asyncio
async def test_yahoo_failure_uses_existing_fallback(monkeypatch):
    calls = []

    async def fake_serp(query, max_results, *, searcher=None):
        calls.append(searcher)
        return fake_result("unavailable", [])

    async def fake_instant(*args, **kwargs):
        return fake_result(
            "ok",
            [{"title": "Fallback", "url": "https://example.org/"}],
        )

    monkeypatch.setattr(sb, "ddg_serp_search", fake_serp)
    monkeypatch.setattr(sb, "ddg_instant_search", fake_instant)

    async with httpx.AsyncClient() as client:
        result = await sb.run_search("Python", 3, client=client)

    assert result.status == "ok"
    assert len(result.results) == 1
    assert len(calls) == 2
