"""GitHub: the owner's notifications (reviews, mentions, CI results), ETag-conditional."""

from __future__ import annotations

import logging
from typing import Any, Final

from ..event import TriggerEvent
from .base import Api, Poll, ProviderError

log = logging.getLogger(__name__)

_URL: Final[str] = "https://api.github.com/notifications"
MAX_PAGES: Final[int] = 5
_SEEN_REMEMBERED: Final[int] = 300
_HEADERS: Final[dict[str, str]] = {
    "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
}


def html_url(api_url: str) -> str:
    return (
        api_url.replace("https://api.github.com/repos/", "https://github.com/")
        .replace("/pulls/", "/pull/").replace("/commits/", "/commit/")
    )


class GithubProducer:
    id = "github"
    source = "github"

    def __init__(self, api: Api) -> None:
        self._api = api

    async def connected(self) -> bool:
        return await self._api.connected()

    async def poll(self, cursor: dict[str, Any], now: float) -> Poll:
        first = not cursor
        seen: dict[str, str] = dict(cursor.get("seen") or {})
        headers = dict(_HEADERS)
        if cursor.get("etag"):
            headers["If-None-Match"] = str(cursor["etag"])
        etag, interval = str(cursor.get("etag") or ""), 0.0
        items: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            response = await self._api.get(
                _URL, {"all": "false", "per_page": 50, "page": page}, headers
            )
            if response.status_code == 304:
                return Poll([], cursor, _poll_interval(response))
            if response.status_code != 200:
                raise ProviderError(f"github: notifications HTTP {response.status_code}")
            if page == 1:
                etag, interval = str(response.headers.get("etag") or ""), _poll_interval(response)
                headers.pop("If-None-Match", None)  # only the first page is conditional
            batch = response.json()
            batch = batch if isinstance(batch, list) else []
            items.extend(batch)
            if len(batch) < 50:
                break
        events: list[TriggerEvent] = []
        for item in items:
            key = str(item.get("id") or "")
            updated = str(item.get("updated_at") or "")
            if not key or seen.get(key) == updated:
                continue
            seen[key] = updated
            if not first:  # the first poll only marks what is already unread
                events.append(_event(item, now))
        trimmed = dict(list(seen.items())[-_SEEN_REMEMBERED:])
        return Poll(events, {"etag": etag, "seen": trimmed}, interval)


def _poll_interval(response: Any) -> float:
    try:
        return float(response.headers.get("x-poll-interval") or 0)
    except ValueError:
        log.debug("github: unreadable poll interval")
        return 0.0


def _event(item: dict[str, Any], now: float) -> TriggerEvent:
    subject = item.get("subject") or {}
    kind = str(subject.get("type") or "")
    reason = str(item.get("reason") or "")
    title = str(subject.get("title") or "")
    label = "CI" if kind == "CheckSuite" else reason.replace("_", " ")
    api_url = str(subject.get("url") or "")
    repo = item.get("repository") or {}
    return TriggerEvent(
        source="github", scope=str(repo.get("full_name") or ""),
        thread_key=api_url or str(item.get("id")),
        summary=f"{label}: {title}", ids=(f"{item.get('id')}:{item.get('updated_at')}",),
        received_at=now,
        raw_ref=html_url(api_url) if api_url else str(repo.get("html_url") or ""),
        labels=tuple(x for x in (reason, kind) if x),
    )
