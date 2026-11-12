"""Where the person meets the assistant outside the app: Telegram and Slack.

The front page's panel shows one button per channel (``GET
/api/agent-chat/lead/channels``). Each row says whether the channel is
connected, the name to show on the button, and the web address a click opens.

The two are not the same kind of thing, and ``kind`` says so:

* ``chat``: Telegram. The owner's private chat with the bot is the lead
  conversation itself (``channels/chat_bridge.py``), so the address is the
  bot's own chat. Connected means the live channel runs, not just that a
  token is stored.
* ``tool``: Slack. The assistant works in the person's workspace with their
  own grant (``plugins/tool/slack_rest.py``); nobody can write to it there.
  The address is the workspace.

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
    row["connected"] = True
    if _TELEGRAM_NAME.fullmatch(name):
        row["handle"] = f"@{name}"
        row["url"] = f"https://t.me/{name}"
    return row


def slack_row(token_store: Any = None) -> dict[str, Any]:
    """Slack as the stored grant describes it. Reads the keyring: call off the loop."""
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
    return {"channels": [slack_row(token_store), telegram_row(channel_manager)]}
