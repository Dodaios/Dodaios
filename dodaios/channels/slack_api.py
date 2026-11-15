"""The few Slack Web API calls the Slack channel needs, and its setup checks.

No Slack SDK: the channel needs a handful of Web API methods and the Socket
Mode link, and both fit in ``httpx`` and ``websockets``, which the app already
ships. Every call sends a key in the ``Authorization`` header, never in a URL,
and no error text that leaves this module carries a key.

Also here: the manifest a person creates their own Slack app from in one
click, and the check of the two keys pasted after it (``check_keys``), so the
connect route and the channel agree on what "a working Slack app" is.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote, urlsplit

import httpx

from dodaios.core.config import SLACK_API_BASE_URL

log = logging.getLogger(__name__)

__all__ = [
    "BOT_EVENTS",
    "BOT_SCOPES",
    "SlackApi",
    "SlackApiError",
    "SlackKeys",
    "SlackSetupError",
    "check_keys",
    "create_app_url",
    "manifest",
    "safe_api_base",
]

#: What the app's bot may do: read and answer its direct messages, see a
#: mention of it, fetch a picture or voice clip sent to it, and read the
#: owner's language from their profile.
BOT_SCOPES: Final[tuple[str, ...]] = (
    "app_mentions:read",
    "chat:write",
    "files:read",
    "im:history",
    "im:read",
    "im:write",
    "users:read",
)
#: A direct message to the app, and a mention of it in a channel.
BOT_EVENTS: Final[tuple[str, ...]] = ("message.im", "app_mention")

#: Slack errors no retry fixes: the key is wrong, revoked, or the wrong kind.
LASTING_ERRORS: Final[frozenset[str]] = frozenset(
    {
        "invalid_auth",
        "not_authed",
        "account_inactive",
        "token_revoked",
        "token_expired",
        "not_allowed_token_type",
        "missing_scope",
        "no_permission",
        "team_access_not_granted",
        "app_uninstalled",
        "invalid_token",
    }
)

_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(15.0, connect=10.0)
_LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"127.0.0.1", "localhost", "::1"})
#: Hosts Slack serves a file of a message from; the bot key goes to no other.
_FILE_HOST_SUFFIXES: Final[tuple[str, ...]] = (".slack.com", ".slack-edge.com")


class SlackApiError(RuntimeError):
    """Slack answered ``ok: false``; ``code`` is Slack's own error word."""

    def __init__(self, method: str, code: str, *, retry_after: float | None = None) -> None:
        super().__init__(f"Slack {method} failed: {code}")
        self.method = method
        self.code = code
        self.retry_after = retry_after

    @property
    def lasting(self) -> bool:
        return self.code in LASTING_ERRORS


def safe_api_base(url: str | None) -> str:
    """Slack's own API address, or a stand-in on this computer; anything else is refused.

    The bot key travels with every call, so a configured address that is
    neither Slack nor this computer falls back to Slack.
    """
    raw = (url or "").strip().rstrip("/")
    if not raw or raw == SLACK_API_BASE_URL:
        return SLACK_API_BASE_URL
    parts = urlsplit(raw)
    if parts.scheme in ("http", "https") and (parts.hostname or "") in _LOCAL_HOSTS:
        return raw
    log.warning("Slack api_base_url is neither Slack nor this computer; using Slack")
    return SLACK_API_BASE_URL


class SlackApi:
    """``await api.call("chat.postMessage", token, channel=..., text=...)``."""

    def __init__(self, base_url: str = SLACK_API_BASE_URL, client: httpx.AsyncClient | None = None):
        self.base_url = safe_api_base(base_url)
        self._client = client
        self._own_client = client is None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._own_client:
            await self._client.aclose()
        self._client = None

    async def call(self, method: str, token: str, **params: Any) -> dict[str, Any]:
        """POST one Web API method as JSON; raise :class:`SlackApiError` on ``ok: false``."""
        client = await self._http()
        body = {k: v for k, v in params.items() if v is not None}
        response = await client.post(
            f"{self.base_url}/{method}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            content=json.dumps(body),
        )
        if response.status_code == 429:
            try:
                wait = float(response.headers.get("Retry-After", "1"))
            except ValueError:  # an unreadable header means "a moment"
                wait = 1.0
            raise SlackApiError(method, "ratelimited", retry_after=wait)
        if response.status_code >= 500:
            raise SlackApiError(method, f"http_{response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise SlackApiError(method, f"http_{response.status_code}") from None
        if not isinstance(data, dict):
            raise SlackApiError(method, "unreadable_answer")
        if not data.get("ok"):
            raise SlackApiError(method, str(data.get("error") or "unknown_error")[:80])
        return data

    def may_receive_key(self, url: str) -> bool:
        """Whether a file address belongs to Slack (or to the stand-in this API talks to)."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme == "https" and (
            host == "slack.com" or any(host.endswith(s) for s in _FILE_HOST_SUFFIXES)
        ):
            return True
        own = urlsplit(self.base_url).hostname or ""
        return own in _LOCAL_HOSTS and host == own

    async def download(self, url: str, token: str, *, limit: int) -> bytes:
        """The bytes of a file of a message, at most ``limit``; ``b""`` when refused or too big."""
        if not self.may_receive_key(url):
            return b""
        client = await self._http()
        headers = {"Authorization": f"Bearer {token}"}
        # Slack answers a file address with a redirect to its file host; each
        # hop is checked before the key goes along.
        for _hop in range(4):
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = str(response.headers.get("location") or "")
                    if not self.may_receive_key(url):
                        return b""
                    continue
                if response.status_code != 200:
                    return b""
                if "text/html" in response.headers.get("content-type", ""):
                    return b""  # a sign-in page: the key may not read the file
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data += chunk
                    if len(data) > limit:
                        return b""
                return bytes(data)
        return b""


# ----------------------------------------------------------------------
# Setup: the manifest, and the check of the two keys
# ----------------------------------------------------------------------


def manifest(assistant: str = "Nova") -> dict[str, Any]:
    """The Slack app a person creates for their assistant: a bot they can message.

    Socket Mode, so no public address is needed; the Messages tab open, so a
    direct message to the app is possible; interactivity on for the Allow /
    Deny buttons of an approval.
    """
    name = " ".join((assistant or "Nova").split())[:35] or "Nova"
    return {
        "display_information": {
            "name": name,
            "description": f"{name}, your Dodaios assistant, in Slack."[:139],
            "background_color": "#1d1d1f",
        },
        "features": {
            "app_home": {
                "home_tab_enabled": False,
                "messages_tab_enabled": True,
                "messages_tab_read_only_enabled": False,
            },
            "bot_user": {"display_name": name, "always_online": True},
        },
        "oauth_config": {"scopes": {"bot": list(BOT_SCOPES)}},
        "settings": {
            "event_subscriptions": {"bot_events": list(BOT_EVENTS)},
            "interactivity": {"is_enabled": True},
            "org_deploy_enabled": False,
            "socket_mode_enabled": True,
            "token_rotation_enabled": False,
        },
    }


def create_app_url(assistant: str = "Nova") -> str:
    """The link that opens Slack's "create app from manifest" with this manifest filled in."""
    body = json.dumps(manifest(assistant), separators=(",", ":"))
    return f"https://api.slack.com/apps?new_app=1&manifest_json={quote(body, safe='')}"


@dataclass(frozen=True, slots=True)
class SlackKeys:
    """What Slack said about a working pair of keys."""

    team_id: str
    team_name: str
    team_url: str
    bot_user_id: str
    bot_id: str
    bot_name: str
    app_id: str


class SlackSetupError(RuntimeError):
    """A pair of keys that does not make a working Slack app; ``code`` names why."""

    def __init__(self, code: str, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient


def _app_id_of_link(url: str) -> str:
    for part in urlsplit(url).query.split("&"):
        key, _, value = part.partition("=")
        if key == "app_id":
            return value
    return ""


async def check_keys(bot_token: str, app_token: str, *, api: SlackApi) -> SlackKeys:
    """Check both keys with Slack; raise :class:`SlackSetupError` with a code the UI words.

    The bot key must be a bot key Slack accepts, the app key must open a
    Socket Mode link, and both must belong to the same app.
    """
    bot_token, app_token = bot_token.strip(), app_token.strip()
    if not bot_token.startswith("xoxb-"):
        raise SlackSetupError("bot_token_shape", "The bot token starts with xoxb-.")
    if not app_token.startswith("xapp-"):
        raise SlackSetupError("app_token_shape", "The app-level token starts with xapp-.")
    try:
        me = await api.call("auth.test", bot_token)
    except SlackApiError as exc:
        if exc.lasting:
            raise SlackSetupError(
                "bot_token_rejected", f"Slack refused the bot token ({exc.code})."
            ) from None
        raise SlackSetupError(
            "slack_unreachable", f"Slack did not answer ({exc.code}).", transient=True
        ) from None
    except httpx.HTTPError as exc:
        raise SlackSetupError(
            "slack_unreachable", f"Slack is not reachable ({type(exc).__name__}).", transient=True
        ) from None
    try:
        link = await api.call("apps.connections.open", app_token)
    except SlackApiError as exc:
        if exc.code in ("invalid_auth", "not_authed", "token_revoked", "not_allowed_token_type"):
            raise SlackSetupError(
                "app_token_rejected", f"Slack refused the app-level token ({exc.code})."
            ) from None
        if exc.lasting or exc.code in ("socket_mode_not_enabled", "invalid_request"):
            raise SlackSetupError(
                "socket_mode_off", f"Socket Mode is not on for this app ({exc.code})."
            ) from None
        raise SlackSetupError(
            "slack_unreachable", f"Slack did not answer ({exc.code}).", transient=True
        ) from None
    except httpx.HTTPError as exc:
        raise SlackSetupError(
            "slack_unreachable", f"Slack is not reachable ({type(exc).__name__}).", transient=True
        ) from None
    bot_id = str(me.get("bot_id") or "")
    app_id = ""
    if bot_id:
        try:
            info = await api.call("bots.info", bot_token, bot=bot_id)
            app_id = str((info.get("bot") or {}).get("app_id") or "")
        except (SlackApiError, httpx.HTTPError):
            app_id = ""  # only used to compare the two keys; the link's id stands alone
    link_app = _app_id_of_link(str(link.get("url") or ""))
    if app_id and link_app and app_id != link_app:
        raise SlackSetupError("different_apps", "The two keys belong to two different Slack apps.")
    return SlackKeys(
        team_id=str(me.get("team_id") or ""),
        team_name=str(me.get("team") or ""),
        team_url=str(me.get("url") or ""),
        bot_user_id=str(me.get("user_id") or ""),
        bot_id=bot_id,
        bot_name=str(me.get("user") or ""),
        app_id=app_id or link_app,
    )
