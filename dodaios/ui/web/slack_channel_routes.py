"""Connect the owner's own Slack app as a conversation channel (``/api/channels/slack``).

Setup in the app, in three moves: open the prefilled "create app from
manifest" link, install the app to the workspace, paste its two keys. The
connect checks both keys with Slack before anything is stored, keeps them in
the Credential Manager (never in ``jarvis.toml``, never in a log), knows the
owner at once when the person's own Slack sign-in (the Slack plugin) is in the
same workspace, and starts the channel live.

Routes:

* ``GET  /api/channels/slack``             the state for the settings card
* ``POST /api/channels/slack/connect``     ``{bot_token, app_token}``
* ``POST /api/channels/slack/pairing``     forget the owner, open pairing again
* ``POST /api/channels/slack/disconnect``  remove the keys, stop the channel

A failed connect answers ``{"detail": {"code": ..., "message": ...}}``; the
code is what the UI words (``bot_token_shape``, ``app_token_shape``,
``bot_token_rejected``, ``app_token_rejected``, ``socket_mode_off``,
``different_apps``, ``slack_unreachable``, ``store_failed``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from dodaios.channels.slack_api import (
    SlackApi,
    SlackSetupError,
    check_keys,
    create_app_url,
    manifest,
)
from dodaios.core.config import delete_secret, get_secret, load_config, set_secret

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channels/slack", tags=["channels"])

_BOT_SECRET = "slack_bot_token"  # noqa: S105 — keyring entry name, not a secret
_APP_SECRET = "slack_app_token"  # noqa: S105 — keyring entry name, not a secret


class ConnectBody(BaseModel):
    bot_token: str = Field(min_length=1, max_length=512)
    app_token: str = Field(min_length=1, max_length=512)


def _assistant(request: Request) -> str:
    from dodaios.brain.assistant_name import DEFAULT_ASSISTANT_NAME, resolve_assistant_name

    cfg = getattr(request.app.state, "config", None) or getattr(request.app.state, "cfg", None)
    try:
        name = resolve_assistant_name(cfg) if cfg is not None else DEFAULT_ASSISTANT_NAME
    except Exception:  # noqa: BLE001 — a name for the app; the fallback is fine
        name = DEFAULT_ASSISTANT_NAME
    return name if name != DEFAULT_ASSISTANT_NAME else "Nova"


def _channel(request: Request) -> tuple[Any, Any]:
    manager = getattr(request.app.state, "channel_manager", None)
    if manager is None:
        return None, None
    try:
        if "slack" in manager.started():
            return manager, manager.get("slack")
    except Exception:  # noqa: BLE001 — a manager mid-start shows as not connected
        log.debug("slack channel not readable", exc_info=True)
    return manager, None


def _keys_saved() -> bool:
    bot = get_secret(_BOT_SECRET, env_fallback="SLACK_BOT_TOKEN")
    app = get_secret(_APP_SECRET, env_fallback="SLACK_APP_TOKEN")
    return bool(bot and app)


async def _state(request: Request) -> dict[str, Any]:
    cfg = await asyncio.to_thread(load_config)
    slack_cfg = cfg.integrations.slack
    keys_saved = await asyncio.to_thread(_keys_saved)
    manager, channel = _channel(request)
    active = bool(getattr(channel, "active", False))
    error = ""
    retrying = False
    if manager is not None:
        try:
            error = str(manager.start_errors().get("slack", "") or "")
            retrying = "slack" in manager.retrying()
        except Exception:  # noqa: BLE001 — the card still paints
            log.debug("slack start state not readable", exc_info=True)
    if active:
        error = str(getattr(channel, "last_error", "") or "")
    owners = list(getattr(channel, "owner_ids", None) or slack_cfg.allowed_user_ids)
    assistant = _assistant(request)
    return {
        "enabled": bool(slack_cfg.enabled),
        "keys_saved": keys_saved,
        "running": active,
        "link_up": bool(getattr(channel, "connected", False)) if active else False,
        "retrying": retrying,
        "error": error.split(": ", 1)[-1] if error.startswith("ChannelStartError") else error,
        "team_name": str(getattr(channel, "team_name", "") or ""),
        "team_id": str(getattr(channel, "team_id", "") or slack_cfg.team_id),
        "bot_name": str(getattr(channel, "bot_name", "") or ""),
        "app_id": str(getattr(channel, "app_id", "") or ""),
        "dm_url": str(getattr(channel, "dm_url", "") or ""),
        "owner_paired": bool(owners),
        "pairing_open": bool(getattr(channel, "pairing_open", False)),
        "pairing_seconds_left": int(getattr(channel, "pairing_seconds_left", 0) or 0),
        "assistant": assistant,
        "create_app_url": create_app_url(assistant),
        "manifest": manifest(assistant),
    }


@router.get("")
async def slack_channel_state(request: Request) -> dict[str, Any]:
    return await _state(request)


async def _owner_from_own_sign_in(team_id: str, api: SlackApi) -> str:
    """The person's member id, when their own Slack sign-in is in the same workspace."""
    try:
        from dodaios.marketplace.token_store import TokenStore

        tokens = await asyncio.to_thread(TokenStore().load, "slack")
    except Exception:  # noqa: BLE001 — no sign-in: the first direct message pairs
        return ""
    if tokens is None or not tokens.access or getattr(tokens, "needs_reauth", False):
        return ""
    try:
        me = await api.call("auth.test", tokens.access)
    except Exception:  # noqa: BLE001 — same: pairing by the first direct message
        return ""
    if str(me.get("team_id") or "") != team_id:
        return ""
    return str(me.get("user_id") or "")


def _setup_error(exc: SlackSetupError) -> HTTPException:
    return HTTPException(
        status_code=502 if exc.transient else 400,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.post("/connect")
async def slack_channel_connect(body: ConnectBody, request: Request) -> dict[str, Any]:
    cfg = await asyncio.to_thread(load_config)
    api = SlackApi(cfg.integrations.slack.api_base_url)
    try:
        try:
            keys = await check_keys(body.bot_token, body.app_token, api=api)
        except SlackSetupError as exc:
            raise _setup_error(exc) from None
        owner = await _owner_from_own_sign_in(keys.team_id, api)
    finally:
        await api.aclose()

    stored = await asyncio.to_thread(set_secret, _BOT_SECRET, body.bot_token.strip())
    stored = stored and await asyncio.to_thread(set_secret, _APP_SECRET, body.app_token.strip())
    if not stored:
        raise HTTPException(
            status_code=500,
            detail={"code": "store_failed", "message": "The keys could not be stored."},
        )

    from dodaios.core.config_writer import set_slack_channel

    previous = cfg.integrations.slack
    same_workspace = previous.team_id == keys.team_id
    owners = [str(v) for v in previous.allowed_user_ids] if same_workspace else []
    if owner and owner not in owners:
        owners = [owner, *owners]
    # Owner and workspace before the switch: a crash between the writes never
    # leaves the channel on with an allowlist meant for another workspace.
    await asyncio.to_thread(
        set_slack_channel,
        allowed_user_ids=owners,
        pair_on_first_dm=not owners,
        team_id=keys.team_id,
    )
    await asyncio.to_thread(set_slack_channel, enabled=True)
    log.info(
        "slack channel connected (workspace %s, owner %s)",
        keys.team_name or "?",
        "known" if owners else "pairs by the first direct message",
    )

    from dodaios.marketplace.channel_runtime import apply_channel_live

    live = await apply_channel_live(request.app.state, "slack")
    state = await _state(request)
    state["live_applied"] = live
    state["owner_from_sign_in"] = bool(owner)
    return state


@router.post("/pairing")
async def slack_channel_pairing(request: Request) -> dict[str, Any]:
    """Forget the owner and open pairing for the next few minutes."""
    from dodaios.core.config_writer import set_slack_channel

    await asyncio.to_thread(set_slack_channel, allowed_user_ids=[], pair_on_first_dm=True)
    from dodaios.marketplace.channel_runtime import apply_channel_live

    await apply_channel_live(request.app.state, "slack")
    return await _state(request)


@router.post("/disconnect")
async def slack_channel_disconnect(request: Request) -> dict[str, Any]:
    from dodaios.core.config_writer import set_slack_channel

    await asyncio.to_thread(set_slack_channel, enabled=False)
    await asyncio.to_thread(delete_secret, _BOT_SECRET)
    await asyncio.to_thread(delete_secret, _APP_SECRET)
    await asyncio.to_thread(set_slack_channel, allowed_user_ids=[], pair_on_first_dm=True)
    from dodaios.marketplace.channel_runtime import apply_channel_live

    await apply_channel_live(request.app.state, "slack")
    log.info("slack channel disconnected")
    return await _state(request)


__all__ = ["router"]
