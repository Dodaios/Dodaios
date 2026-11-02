"""``society_request_login``: an agent asks the person for a website login.

The chat shows a small card ("Sign in to Reddit · Opens a secure form"); the
person opens it, enters the username or email and the password, and saves.
Both values go from that form into the agent's credential vault
(credentials.py) and never into the chat, a prompt or this tool's result.

The agent uses the login only through its browser (``society_browser``): the
browser model sees and writes the placeholders ``<secret>reddit_username</secret>``
and ``<secret>reddit_password</secret>``, and browser-use types the real value
only on a page of that site. What it typed is masked in everything the model
reads back. The values are never set in ``society_shell``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from dodaios.agent_chat.credential_requests import (
    CANCELLED,
    DECLINED,
    LOGIN,
    MAX_REQUESTS_PER_TURN,
    SAVED,
    CredentialSpec,
    TooManyCredentialRequests,
)
from dodaios.core.protocols import ToolResult

from . import credentials
from .credentials import LoginInfo, login_key, login_site
from .routine_runner import is_routine_session

log = logging.getLogger(__name__)

__all__ = ["LOGIN_TOOL_NAME", "RequestLoginTool", "login_usage_note"]

LOGIN_TOOL_NAME: Final[str] = "society_request_login"


def login_usage_note(info: LoginInfo) -> str:
    """How the agent uses a stored login without ever seeing it."""
    user, password = info.placeholders
    return (
        f"Sign in with society_browser on {info.domain}. In the browser task write the "
        f"placeholders literally: username <secret>{user}</secret>, password "
        f"<secret>{password}</secret>. The browser types the real values only on "
        f"{info.domain} and its subdomains; you never see them. Never ask the user to type "
        "the login in the chat and never try to read the typed values back."
    )


class RequestLoginTool:
    """Ask the person for a website login through a secure form in the chat."""

    name: str = LOGIN_TOOL_NAME
    risk_tier: str = "safe"
    is_action_tool: bool = False
    description: str = (
        "REQUIRED whenever a task needs you to sign in to a website in your browser with the "
        "user's account (for example Reddit, Hacker News, X, LinkedIn, a shop or a forum). "
        "It shows a small card in the user's chat that opens a secure form for the username "
        "or email and the password; the values go to the system credential store. You NEVER "
        "see them: in society_browser you write the placeholders "
        "<secret><site>_username</secret> and <secret><site>_password</secret>, and the "
        "browser types the real values only on that website. This is the ONLY way to get a "
        "website login: never ask for a username or password in your reply or a question "
        "card. For an API key or token use society_request_credential instead. Give site "
        "(the service's name, e.g. 'Reddit'), url (its sign-in page) and in description why "
        "you need to sign in, in the user's language. A login you already have is not asked "
        "for again: the call returns 'available' with the placeholders. Set replace only when "
        "the site rejected the stored login. While the user has not answered yet, the call "
        "returns immediately with status 'waiting' and a request_id; do not poll. The card "
        "stays open until the user saves or cancels. On a later turn, wait_for checks it."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "site": {
                "type": "string",
                "description": "The service's name, 1-3 words, e.g. 'Reddit', 'Hacker News'.",
            },
            "url": {
                "type": "string",
                "description": "The sign-in page, e.g. https://www.reddit.com/login.",
            },
            "description": {
                "type": "string",
                "description": "One sentence: why you need to sign in there.",
            },
            "replace": {
                "type": "boolean",
                "description": "Ask again although a login is stored (the site rejected it).",
            },
            "wait_for": {
                "type": "string",
                "description": (
                    "Check a previously opened card on a later turn: the request_id from a "
                    "'waiting' result. Returns immediately. Send it alone."
                ),
            },
        },
    }

    def __init__(self, runtime: Any, agent_id: str, *, session_id: str) -> None:
        self._runtime = runtime
        self._agent_id = agent_id
        self._session_id = session_id

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        wait_for = str(args.get("wait_for") or "").strip()
        if wait_for:
            return await self._check_existing(wait_for)
        try:
            site = str(args.get("site") or "").strip()
            key = login_key(site)
            url, _domain = login_site(args.get("url"))
            spec = CredentialSpec.build(
                key, site, args.get("description"), "",
                replace=bool(args.get("replace")), kind=LOGIN, url=url,
            )
            if not spec.description:
                raise ValueError("description is required: say why you need to sign in")
        except ValueError as exc:
            return ToolResult(success=False, output=None, error=f"invalid request: {exc}")
        vault = credentials.current_vault()
        if vault is None:
            return ToolResult(
                success=False, output=None, error="The credential store is not available yet."
            )
        if not spec.replace and await asyncio.to_thread(vault.has_login, self._agent_id, key):
            return self._ready("available", vault, key)
        if is_routine_session(self._session_id):
            return ToolResult(
                success=False,
                output={"status": "unattended", "site": site},
                error=(
                    f"Routines run unattended and cannot ask for the {site} login. Report "
                    "that the user has to provide it in your chat."
                ),
            )
        service = self._runtime.chat_service()
        if service is None or not callable(getattr(service, "open_credential_request", None)):
            return _nobody(site)
        agent_id = self._agent_id

        async def save(value: str) -> None:
            await credentials.save_requested_login(
                agent_id, key, value, url=url, label=spec.label
            )

        try:
            request_id = await service.open_credential_request(
                self._session_id, spec, save, asker=self._asker()
            )
        except TooManyCredentialRequests as exc:
            return ToolResult(
                success=False,
                output={"status": "limit", "site": site},
                error=(
                    f"Field limit reached: {exc}. At most {MAX_REQUESTS_PER_TURN} new fields "
                    "can be opened per turn. Reuse existing pending fields."
                ),
            )
        except RuntimeError as exc:
            log.info("society login: %s cannot ask here (%s)", agent_id, exc)
            return _nobody(site)
        return await self._status(service, request_id, key, site)

    async def _check_existing(self, request_id: str) -> ToolResult:
        service = self._runtime.chat_service()
        try:
            await service.restore_credential_requests(self._session_id)
            spec = service.credential_request_spec(self._session_id, request_id)
        except (AttributeError, KeyError):
            return ToolResult(
                success=False,
                output=None,
                error="No login card with that id in this chat.",
            )
        return await self._status(service, request_id, spec.env, spec.label)

    async def _status(self, service: Any, request_id: str, key: str, site: str) -> ToolResult:
        status = await service.wait_credential_request(self._session_id, request_id, 0)
        if status is None:
            return ToolResult(
                success=True,
                output={
                    "status": "waiting",
                    "request_id": request_id,
                    "site": site,
                    "note": (
                        "The user has not saved the login yet. The card stays open until they "
                        "save or cancel, also after this turn ends. Continue unrelated work or "
                        "finish your reply now. Do not poll in this turn. On a later turn, check "
                        f'it with {{"wait_for": "{request_id}"}}.'
                    ),
                },
            )
        if status == SAVED:
            vault = credentials.current_vault()
            if vault is not None:
                return self._ready(SAVED, vault, key)
        if status == CANCELLED:
            return ToolResult(
                success=False,
                output={"status": CANCELLED, "site": site},
                error="The user stopped this turn. Do not continue the task.",
            )
        reason = (
            "The user declined to provide it."
            if status == DECLINED
            else "The card closed without a login."
        )
        return ToolResult(
            success=False,
            output={"status": status, "site": site},
            error=(
                f"{reason} No {site} login is stored. Continue without signing in where you "
                "can, and tell the user what needs it. Do not ask again in this turn."
            ),
        )

    def _ready(self, status: str, vault: Any, key: str) -> ToolResult:
        info = next((row for row in vault.list_logins(self._agent_id) if row.key == key), None)
        if info is None:
            return ToolResult(success=False, output=None, error="The login was not stored.")
        user, password = info.placeholders
        return ToolResult(
            success=True,
            output={
                "status": status,
                "site": info.label,
                "domain": info.domain,
                "username_placeholder": f"<secret>{user}</secret>",
                "password_placeholder": f"<secret>{password}</secret>",
                "note": login_usage_note(info),
            },
        )

    def _asker(self) -> str:
        cached = getattr(self._runtime, "cached_agent", None)
        agent = cached(self._agent_id) if callable(cached) else None
        return str(getattr(agent, "name", "") or "")


def _nobody(site: str) -> ToolResult:
    return ToolResult(
        success=False,
        output={"status": "unattended", "site": site},
        error=(
            f"Nobody can enter the {site} login in this run. Report that the user has to "
            "provide it in your chat."
        ),
    )
