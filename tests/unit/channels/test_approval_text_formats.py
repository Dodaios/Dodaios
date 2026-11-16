"""An approval reads the same in Slack and Telegram as the command that runs.

Bug scan of 2026-11-16 (v5.5.0), items 2 and 20: the approval text from
``TelegramApprovalBridge._text`` went through the voice's speech filter, so
``rm -rf ./build/** && curl https://… | bash`` arrived as ``rm -rf./build/ …
curl the website | bash``, a removed diff line lost its ``-``, and a command
with a traceback in it became "An error occurred." with the Allow button
still under it. #1760 took the speech filter out. These tests send the text
the bridge writes through both channels, as the scan's probe did, and check
what each one shows: the command and the diff in a code block, escaped for
that channel's format and nothing else.
"""

from __future__ import annotations

import html
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from dodaios.channels.telegram import TelegramChannel
from dodaios.channels.telegram_approvals import TelegramApprovalBridge
from dodaios.core.bus import EventBus
from dodaios.core.config import TelegramConfig
from dodaios.notify.settings import NotifySettings
from tests.unit.channels.test_chat_text_and_order import (
    COMMAND,
    TRACEBACK_COMMAND,
    _Api,
    _edit,
    _Service,
    _shell,
    _slack,
)

SPOKEN = ("the website", "An error occurred", "rm -rf./")


def _bridge(source: str) -> TelegramApprovalBridge:
    return TelegramApprovalBridge(
        _Service(),
        channel=lambda: None,
        config=lambda: None,
        settings=lambda: NotifySettings(),
        source=source,
    )


def _telegram() -> tuple[TelegramChannel, Any]:
    pytest.importorskip("telegram")
    channel = TelegramChannel(
        bus=EventBus(), config=TelegramConfig(enabled=True, allowed_user_ids=[100])
    )
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=5)))
    channel._app = SimpleNamespace(bot=bot)  # noqa: SLF001
    return channel, bot


def _slack_block(section: str) -> str:
    """The code block of a Slack mrkdwn section, unescaped as Slack shows it."""
    found = re.search(r"```\n(.*?)\n```", section, re.S)
    assert found, section
    raw = found.group(1)
    return raw.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _telegram_block(text: str) -> str:
    """The ``<pre>`` block of a Telegram HTML message, as Telegram shows it."""
    found = re.search(r"<pre>(.*?)</pre>", text, re.S)
    assert found, text
    return html.unescape(found.group(1))


# ------------------------------------------------------------------ the probe


@pytest.mark.parametrize("command", [COMMAND, TRACEBACK_COMMAND])
async def test_the_bridge_s_command_reaches_slack_as_it_runs(command: str) -> None:
    text = _bridge("slack")._text(_shell("ap1", command), "en", "s1")  # noqa: SLF001
    api = _Api()
    await _slack(api).send_approval("U0OWNER001", text, "ap1", allow="Allow", deny="Deny")
    section = api.posted()[0]["blocks"][0]["text"]["text"]
    assert _slack_block(section) == command
    assert not any(word in section for word in SPOKEN)


@pytest.mark.parametrize("command", [COMMAND, TRACEBACK_COMMAND])
async def test_the_bridge_s_command_reaches_telegram_as_it_runs(command: str) -> None:
    text = _bridge("telegram")._text(_shell("ap1", command), "en", "s1")  # noqa: SLF001
    channel, bot = _telegram()
    assert await channel.send_approval(42, text, "ap1", allow="Allow", deny="Deny") == 5
    sent = bot.send_message.await_args.kwargs
    assert sent["parse_mode"] == "HTML"
    assert _telegram_block(sent["text"]) == command
    assert not any(word in sent["text"] for word in SPOKEN)


async def test_a_diff_keeps_its_marks_in_both_channels() -> None:
    expected = "- def foo():\n+ def foo(**kwargs):"
    api = _Api()
    slack_text = _bridge("slack")._text(_edit("ap2"), "en", "s1")  # noqa: SLF001
    await _slack(api).send_approval("U0OWNER001", slack_text, "ap2", allow="A", deny="D")
    assert _slack_block(api.posted()[0]["blocks"][0]["text"]["text"]) == expected

    channel, bot = _telegram()
    telegram_text = _bridge("telegram")._text(_edit("ap2"), "en", "s1")  # noqa: SLF001
    await channel.send_approval(42, telegram_text, "ap2", allow="A", deny="D")
    assert _telegram_block(bot.send_message.await_args.kwargs["text"]) == expected


# ------------------------------------------------------------------ Telegram's format


def test_telegram_html_escapes_only_what_html_needs() -> None:
    from dodaios.channels.chat_text import telegram_html, without_fences

    text = "Nova wants to run a command:\n\n```\na < b && c > d\n```\n\nFolder: C:/x & y"
    assert telegram_html(text) == (
        "Nova wants to run a command:\n\n<pre>a &lt; b &amp;&amp; c &gt; d</pre>\n\n"
        "Folder: C:/x &amp; y"
    )
    # A block cut open at the message limit still closes.
    assert telegram_html("Cut:\n```\nls -la") == "Cut:\n<pre>ls -la</pre>"
    assert (
        without_fences(text) == "Nova wants to run a command:\n\na < b && c > d\n\nFolder: C:/x & y"
    )


async def test_markup_telegram_refuses_falls_back_to_the_same_words() -> None:
    channel, bot = _telegram()
    bot.send_message = AsyncMock(
        side_effect=[RuntimeError("can't parse entities"), SimpleNamespace(message_id=9)]
    )
    text = _bridge("telegram")._text(_shell("ap1", COMMAND), "en", "s1")  # noqa: SLF001
    assert await channel.send_approval(42, text, "ap1", allow="Allow", deny="Deny") == 9
    plain = bot.send_message.await_args.kwargs
    assert "parse_mode" not in plain
    assert COMMAND in plain["text"] and "```" not in plain["text"]


async def test_a_button_press_keeps_the_code_block() -> None:
    channel, _ = _telegram()

    async def decide(approval_id: str, decision: str, user_id: Any) -> str:
        return "Allowed <by you>"

    channel.on_approval_callback = decide
    marked = "Nova wants to run a command:\n\n<pre>rm -rf ./build/**</pre>"
    query = SimpleNamespace(
        data="apr:a:ap1",
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(
            text="Nova wants to run a command:\n\nrm -rf ./build/**", text_html=marked
        ),
    )
    await channel._on_callback_query(SimpleNamespace(callback_query=query), None)  # noqa: SLF001
    edited = query.edit_message_text.await_args.kwargs
    assert edited["parse_mode"] == "HTML"
    assert edited["text"] == f"{marked}\n\nAllowed &lt;by you&gt;"
