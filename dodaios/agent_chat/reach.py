"""Where the person meets the assistant outside the app: Slack and Telegram.

The front page's panel shows one button per channel (``GET
/api/agent-chat/lead/channels``). Each row says whether the channel is
connected, the name to show on the button, and the web address a click opens.

The two are not the same kind of thing, and ``kind`` says so:

* ``chat``: Telegram. The owner's private chat with the bot is the lead
  conversation itself (``channels/chat_bridge.py``), so the address is the
  bot's own chat. Connected means Telegram has named the bot to the live
  channel: a stored token alone is not enough, and neither is a channel that
  is switched off (it still counts as started for the manager).
* ``chat`` too: Slack, once the person connected their own Slack app
  (``channels/slack.py``). A direct message to it is the lead conversation,
  so the address opens that direct message. Connected means the channel runs
  with both keys accepted.
* ``tool``: Slack without that app. The assistant works in the person's
  workspace with their own grant (``plugins/tool/slack_rest.py``); nobody can
  write to it there. The address is the workspace.

Addresses are ``https`` only: that is all the app's opener accepts.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

#: A Telegram username as the Bot API reports it.
_TELEGRAM_NAME = re.compile(r"[a-z0-9_]{3,64}")
#: A Slack workspace id.
_SLACK_TEAM = re.compile(r"T[A-Z0-9]{2,32}")


def _row(channel_id: str, kind: str) -> dict[str, Any]:
    return {"id": channel_id, "kind": kind, "connected": False, "handle": "", "url": ""}


def telegram_row(channel_manager: Any) -> dict[str, Any]:
    """Telegram as it runs right now, read from the live channel."""
    row = _row("telegram", "chat")
    try:
        if channel_manager is None or "telegram" not in channel_manager.started():
            return row
        name = str(getattr(channel_manager.get("telegram"), "bot_username", "") or "")
    except Exception:  # noqa: BLE001 - a manager mid-start counts as not connected
        log.debug("telegram channel state could not be read", exc_info=True)
        return row
    # A channel with ``enabled = false`` starts too, without ever asking
    # Telegram who it is. Only a bot Telegram has named can be written to.
    if not _TELEGRAM_NAME.fullmatch(name):
        return row
    row["connected"] = True
    row["handle"] = f"@{name}"
    row["url"] = f"https://t.me/{name}"
    return row


#: A Slack app id and a bot user name as Slack reports them.
_SLACK_APP = re.compile(r"A[A-Z0-9]{2,32}")
_SLACK_NAME = re.compile(r"[a-z0-9._-]{1,80}")


def slack_chat_row(channel_manager: Any) -> dict[str, Any] | None:
    """Slack as a conversation, when the owner's own Slack app runs; else ``None``."""
    try:
        if channel_manager is None or "slack" not in channel_manager.started():
            return None
        channel = channel_manager.get("slack")
    except Exception:  # noqa: BLE001 - a manager mid-start counts as not connected
        log.debug("slack channel state could not be read", exc_info=True)
        return None
    if not getattr(channel, "active", False):
        return None
    row = _row("slack", "chat")
    row["connected"] = True
    name = str(getattr(channel, "bot_name", "") or "")
    team = str(getattr(channel, "team_name", "") or "")
    row["handle"] = f"@{name}" if _SLACK_NAME.fullmatch(name) else team[:80]
    app = str(getattr(channel, "app_id", "") or "")
    team_id = str(getattr(channel, "team_id", "") or "")
    if _SLACK_APP.fullmatch(app) and _SLACK_TEAM.fullmatch(team_id):
        row["url"] = f"https://slack.com/app_redirect?app={app}&team={team_id}"
    return row


def slack_row(token_store: Any = None, channel_manager: Any = None) -> dict[str, Any]:
    """Slack as a conversation if the owner's app runs, else as the stored grant describes it.

    Reads the keyring: call off the loop.
    """
    chat = slack_chat_row(channel_manager)
    if chat is not None:
        return chat
    row = _row("slack", "tool")
    try:
        if token_store is None:
            from dodaios.marketplace.token_store import TokenStore

            token_store = TokenStore()
        tokens = token_store.load("slack")
    except Exception:  # noqa: BLE001 - an unreadable grant is shown as not connected
        log.debug("slack grant could not be read", exc_info=True)
        return row
    if tokens is None or not tokens.access or tokens.needs_reauth:
        return row
    row["connected"] = True
    row["handle"] = str(tokens.extra.get("team_name", "") or "")[:80]
    team = str(tokens.extra.get("team_id", "") or "")
    if _SLACK_TEAM.fullmatch(team):
        row["url"] = f"https://app.slack.com/client/{team}"
    return row


def channels_view(channel_manager: Any, token_store: Any = None) -> dict[str, Any]:
    """Both rows, in the order the panel draws them."""
    return {"channels": [slack_row(token_store, channel_manager), telegram_row(channel_manager)]}
