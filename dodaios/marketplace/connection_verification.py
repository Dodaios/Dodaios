"""Bounded, read-only resource checks for a freshly granted connection.

These checks validate access, not a completed plugin smoke-test audit. No token
is stored here, and provider payloads never become diagnostic messages.

The connect flow persists the grant BEFORE it runs this check. A failure is
then classified: only a provider that rejects the credential itself (HTTP 401,
or Slack's ``invalid_auth`` family) means the grant is unusable. Every other
failure (a missing scope, a rate limit, an outage, an empty tool list) leaves a
valid grant connected with degraded capability, so the user is never sent back
through a browser consent that already succeeded.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from dodaios.marketplace.catalog import PluginSpec
from dodaios.marketplace.token_store import Tokens

VERIFY_TIMEOUT_SECONDS = 30.0
CLOSE_TIMEOUT_SECONDS = 5.0


# Why a capability check failed. Fixed codes only: provider text never leaves
# this module, because an error body can echo a token back.
CAPABILITY_UNAUTHORIZED = "unauthorized"
"""The provider rejected the credential itself; the grant is unusable."""
CAPABILITY_FORBIDDEN = "forbidden"
"""Signed in, but the account or scopes do not reach the probed resource."""
CAPABILITY_RATE_LIMITED = "rate_limited"
"""The provider throttled the check; access itself is unknown."""
CAPABILITY_UNAVAILABLE = "unavailable"
"""Anything else: outage, timeout, transport error, unusable response."""

# Slack answers HTTP 200 with ok=false; these error codes reject the token.
_SLACK_REJECTED_ERRORS = frozenset(
    {"invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive"}
)


class ConnectionVerificationError(RuntimeError):
    """A fixed, safe explanation suitable for the connection dialog.

    ``reason`` is one of the ``CAPABILITY_*`` codes. Only
    ``CAPABILITY_UNAUTHORIZED`` means the grant itself was refused.
    """

    def __init__(self, message: str, *, reason: str = CAPABILITY_UNAVAILABLE) -> None:
        super().__init__(message)
        self.reason = reason

    @property
    def rejected(self) -> bool:
        """True when the provider refused the credential, not just a capability."""
        return self.reason == CAPABILITY_UNAUTHORIZED


def _http_status(exc: BaseException) -> int | None:
    """Find the HTTP status behind a failure, through groups and chained causes."""
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            return current.response.status_code
        status = getattr(current, "status_code", None)
        if isinstance(status, int) and not isinstance(status, bool):
            return status
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
    return None


def _reason_for_status(status: int | None) -> str:
    if status == 401:
        return CAPABILITY_UNAUTHORIZED
    if status == 403:
        return CAPABILITY_FORBIDDEN
    if status == 429:
        return CAPABILITY_RATE_LIMITED
    return CAPABILITY_UNAVAILABLE


# Explicit operations avoid accidentally verifying through a future write tool.
_REST_PROBES: dict[str, tuple[str, dict[str, Any]]] = {
    "outlook": ("list_messages", {"query_params": {"$top": 1, "$select": "id"}}),
    "onedrive": ("list_files", {"query_params": {"$top": 1, "$select": "id"}}),
    "teams": ("list_chats", {"query_params": {"$top": 1}}),
    "sharepoint": ("search_sites", {"query_params": {"search": "*"}}),
    "onenote": ("list_notebooks", {}),
    "microsoft_todo": ("list_lists", {}),
    "azure": ("list_subscriptions", {}),
    "google_cloud": ("list_projects", {}),
    "gitlab": ("list_projects", {"query_params": {"per_page": 1}}),
    "x": ("read_profile", {}),
    "linkedin": ("read_profile", {}),
    "meta": ("list_pages", {}),
    "youtube_studio": ("read_channel", {}),
    "hubspot": ("list_contacts", {"query_params": {"limit": 1}}),
    "figma": ("read_profile", {}),
    "zoom": ("list_meetings", {}),
}

_NATIVE_PROBES: dict[str, tuple[str, dict[str, str], str]] = {
    "discord": ("https://discord.com/api/v10/users/@me", {}, "id"),
    "gmail": ("https://gmail.googleapis.com/gmail/v1/users/me/profile", {}, "emailAddress"),
    "google_drive": (
        "https://www.googleapis.com/drive/v3/files",
        {"pageSize": "1", "fields": "files(id)"},
        "files",
    ),
    "google_calendar": (
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        {"maxResults": "1"},
        "kind",
    ),
    # auth.test only identifies the token's user; Slack answers failures as
    # HTTP 200 with ok=false and an "error" key, which the check rejects.
    "slack": ("https://slack.com/api/auth.test", {}, "user_id"),
    "spotify": ("https://api.spotify.com/v1/me", {}, "id"),
    "youtube_music": (
        "https://www.googleapis.com/youtube/v3/playlists",
        {"part": "id", "mine": "true", "maxResults": "1"},
        "kind",
    ),
}


async def _verify_native(spec: PluginSpec, tokens: Tokens) -> None:
    if spec.id == "home_assistant":
        from dodaios.marketplace.instance_url import normalize_instance_url

        url = normalize_instance_url(tokens.extra.get("instance_url", "")) + "/api/"
        params: dict[str, str] = {}
        expected = "message"
    else:
        url, params, expected = _NATIVE_PROBES[spec.id]
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        response = await client.get(
            url, params=params, headers={"Authorization": f"Bearer {tokens.access}"}
        )
        response.raise_for_status()
        payload = response.json()
        if (
            spec.id == "slack"
            and isinstance(payload, dict)
            and payload.get("ok") is False
            and str(payload.get("error", "")) in _SLACK_REJECTED_ERRORS
        ):
            raise ConnectionVerificationError(
                "Slack rejected the authorization. Connect again.",
                reason=CAPABILITY_UNAUTHORIZED,
            )
        if (
            not isinstance(payload, dict)
            or expected not in payload
            or payload.get("error")
            or payload.get("ok") is False
        ):
            raise ConnectionVerificationError(
                "The provider returned an unusable resource response."
            )


async def _verify_rest(spec: PluginSpec, tokens: Tokens) -> None:
    from dodaios.plugins.tool.connected_server import ConnectedRestClient

    operation, arguments = _REST_PROBES[spec.id]
    client = ConnectedRestClient(
        spec.id, tokens.access, auth_type="oauth" if tokens.extra.get("client_id") else "pat"
    )
    try:
        async with asyncio.timeout(VERIFY_TIMEOUT_SECONDS):
            payload = await client.call(operation, arguments)
            if not isinstance(payload, (dict, list)) or (
                isinstance(payload, dict)
                and (payload.get("error") or "content_type" in payload or payload.get("accepted"))
            ):
                raise ConnectionVerificationError(
                    "The provider returned an unusable resource response."
                )
    finally:
        async with asyncio.timeout(CLOSE_TIMEOUT_SECONDS):
            await client.close()


async def _verify_mcp(spec: PluginSpec, tokens: Tokens) -> None:
    from dodaios.marketplace.plugin_mcp import plugin_to_mcp_server_spec
    from dodaios.marketplace.plugin_registry import _default_client_factory

    resolved = plugin_to_mcp_server_spec(spec, tokens)
    if resolved is None or resolved[0].transport != "http":
        raise ConnectionVerificationError("This plugin has no supported connection verifier.")
    server_spec, env = resolved
    client = _default_client_factory(server_spec, env_overrides=env)
    # Keep all three lifecycle calls in this task. MCP context managers may
    # own AnyIO cancel scopes that cannot be closed by a wait_for child task.
    try:
        async with asyncio.timeout(VERIFY_TIMEOUT_SECONDS):
            await client.start()
            tools = await client.list_tools()
            if not tools or not all(isinstance(t, dict) and t.get("name") for t in tools):
                raise ConnectionVerificationError("The provider exposes no usable plugin tools.")
    finally:
        async with asyncio.timeout(CLOSE_TIMEOUT_SECONDS):
            await client.stop()


async def verify_connection(spec: PluginSpec, tokens: Tokens) -> None:
    """Raise a safe, classified ``ConnectionVerificationError`` on failed access.

    Persistence is the caller's job; ``exc.rejected`` tells it whether the
    grant itself was refused or only a capability is degraded.
    """
    try:
        if not tokens.access or tokens.needs_reauth:
            raise ConnectionVerificationError(
                "Authorization is missing or expired. Connect again.",
                reason=CAPABILITY_UNAUTHORIZED,
            )
        if spec.verification_hook is not None:
            if spec.verification_hook != "home_assistant_api" or spec.id != "home_assistant":
                raise ConnectionVerificationError(
                    "This plugin declares an unsupported connection verifier."
                )
        if spec.id in _REST_PROBES:
            await _verify_rest(spec, tokens)
        elif spec.id in _NATIVE_PROBES or spec.id == "home_assistant":
            async with asyncio.timeout(VERIFY_TIMEOUT_SECONDS):
                await _verify_native(spec, tokens)
        else:
            await _verify_mcp(spec, tokens)
    except ConnectionVerificationError:
        raise
    except asyncio.CancelledError as exc:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise
        # A failed MCP transport can cancel its internal owner and forward
        # that exception without cancellation of this verification task.
        raise ConnectionVerificationError(
            "The provider connection closed during verification. Try again.",
            reason=_reason_for_status(_http_status(exc)),
        ) from None
    except TimeoutError:
        raise ConnectionVerificationError("The connection check timed out. Try again.") from None
    except Exception as exc:
        # Exception text can contain tokens, response bodies or account data;
        # only the HTTP status is read from it, never the message.
        reason = _reason_for_status(_http_status(exc))
        if reason == CAPABILITY_UNAUTHORIZED:
            message = "The provider rejected the authorization. Connect again."
        else:
            message = "The provider connection check failed. Check account access and try again."
        raise ConnectionVerificationError(message, reason=reason) from None
