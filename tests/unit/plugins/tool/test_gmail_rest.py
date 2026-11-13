"""Gmail REST tool: reads the marketplace keyring token and calls the Gmail
REST API directly (Node-free, stays under the marketplace token model)."""

import base64

import httpx
import pytest

from dodaios.plugins.tool.gmail_rest import _GMAIL_BODY_CHAR_CAP, GmailRestTool


@pytest.mark.asyncio
async def test_list_messages_uses_bearer_from_provider():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer at_123"
        assert "/messages" in str(req.url)
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})

    tool = GmailRestTool(
        access_token_provider=lambda: "at_123",
        transport=httpx.MockTransport(handler),
    )
    out = await tool.list_messages(max_results=1)
    assert out["messages"][0]["id"] == "m1"


@pytest.mark.asyncio
async def test_send_message_posts_base64_raw():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        captured["url"] = str(req.url)
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "sent1"})

    tool = GmailRestTool(
        access_token_provider=lambda: "at_123",
        transport=httpx.MockTransport(handler),
    )
    out = await tool.send_message(to="a@b.com", subject="Hi", body="Hello")
    assert out["id"] == "sent1"
    assert "/messages/send" in captured["url"]
    decoded = base64.urlsafe_b64decode(captured["body"]["raw"]).decode()
    assert "To: a@b.com" in decoded and "Hello" in decoded


# Live bug 2026-11-13: the subject was put into the raw message as bare UTF-8,
# so Gmail showed mojibake such as "Ã¤" and "â€“" in the subject line.
_UNICODE_SUBJECT = "Geschäftsreise 17.–29. – Grüße 🚀"  # i18n-allow: umlaut round-trip sample
_UNICODE_BODY = "Hallo Herr Müller,\n\nGrüße – bis bald 🚀\n"  # i18n-allow: umlaut sample
_UNICODE_TO = "Jürgen Weiß <juergen@example.com>"  # i18n-allow: umlaut display name sample


async def _sent_raw_bytes(*, to: str, subject: str, body: str) -> bytes:
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "sent1"})

    tool = GmailRestTool(
        access_token_provider=lambda: "at_123",
        transport=httpx.MockTransport(handler),
    )
    await tool.send_message(to=to, subject=subject, body=body)
    return base64.urlsafe_b64decode(captured["body"]["raw"])


@pytest.mark.asyncio
async def test_send_message_unicode_subject_name_and_body_round_trip():
    from email import message_from_bytes, policy

    raw = await _sent_raw_bytes(to=_UNICODE_TO, subject=_UNICODE_SUBJECT, body=_UNICODE_BODY)

    # On the wire the message is plain ASCII: headers as RFC 2047 encoded-words,
    # the body in a 7-bit transfer encoding with a declared UTF-8 charset.
    raw.decode("ascii")
    assert b"=?utf-8?" in raw
    assert b"\r\n" in raw

    parsed = message_from_bytes(raw, policy=policy.default)
    assert parsed["Subject"] == _UNICODE_SUBJECT
    assert parsed["To"].addresses[0].display_name == "Jürgen Weiß"  # i18n-allow: sample name
    assert parsed["To"].addresses[0].addr_spec == "juergen@example.com"
    assert parsed.get_content_type() == "text/plain"
    assert parsed.get_content_charset() == "utf-8"
    # Mail line ends are CRLF on the wire; the text itself is unchanged.
    assert parsed.get_content().replace("\r\n", "\n") == _UNICODE_BODY


@pytest.mark.asyncio
async def test_send_message_line_break_in_subject_cannot_inject_a_header():
    from email import message_from_bytes, policy

    raw = await _sent_raw_bytes(
        to="a@b.com", subject="Hi\r\nBcc: evil@example.com", body="x"
    )
    parsed = message_from_bytes(raw, policy=policy.default)
    assert parsed["Bcc"] is None
    assert parsed["Subject"] == "Hi Bcc: evil@example.com"


@pytest.mark.asyncio
async def test_execute_returns_error_when_not_connected():
    tool = GmailRestTool(access_token_provider=lambda: None)
    result = await tool.execute({"action": "list_messages"}, ctx=None)
    assert result.success is False
    assert "connect" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_list_messages_refreshes_on_401_then_retries():
    # An expired access token returns 401. The tool must refresh once and retry
    # the call — self-healing instead of surfacing "Freigabe abgelaufen"
    # (live 2026-06-07 Gmail bug).
    calls = {"http": 0, "refresh": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["http"] += 1
        if calls["http"] == 1:
            return httpx.Response(401, json={"error": {"code": 401}})
        return httpx.Response(200, json={"messages": [{"id": "m9"}]})

    async def refresher() -> bool:
        calls["refresh"] += 1
        return True

    tool = GmailRestTool(
        access_token_provider=lambda: "at_dead",
        transport=httpx.MockTransport(handler),
        token_refresher=refresher,
    )
    out = await tool.list_messages(max_results=1)
    assert out["messages"][0]["id"] == "m9"
    assert calls["refresh"] == 1
    assert calls["http"] == 2  # retried exactly once after a successful refresh


@pytest.mark.asyncio
async def test_default_refresh_receives_failed_access_token(monkeypatch) -> None:  # noqa: ANN001
    seen: list[str | None] = []
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(401, json={"error": {"code": 401}})
        return httpx.Response(200, json={"messages": []})

    async def refresher(observed_access_token: str | None = None) -> bool:
        seen.append(observed_access_token)
        return True

    monkeypatch.setattr(
        "dodaios.plugins.tool.gmail_rest._default_refresher", refresher
    )
    tool = GmailRestTool(
        access_token_provider=lambda: "failed-access",
        transport=httpx.MockTransport(handler),
    )

    await tool.list_messages()

    assert seen == ["failed-access"]


@pytest.mark.asyncio
async def test_returns_reconnect_error_when_refresh_fails():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": 401}})

    async def refresher() -> bool:
        return False  # un-healable (e.g. invalid_client / revoked)

    tool = GmailRestTool(
        access_token_provider=lambda: "at_dead",
        transport=httpx.MockTransport(handler),
        token_refresher=refresher,
    )
    out = await tool.list_messages()
    assert "error" in out
    assert "reconnect" in out["error"].lower()


@pytest.mark.asyncio
async def test_send_message_refreshes_on_401_then_retries():
    calls = {"http": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["http"] += 1
        if calls["http"] == 1:
            return httpx.Response(401, json={"error": {"code": 401}})
        return httpx.Response(200, json={"id": "sent9"})

    async def refresher() -> bool:
        return True

    tool = GmailRestTool(
        access_token_provider=lambda: "at_dead",
        transport=httpx.MockTransport(handler),
        token_refresher=refresher,
    )
    out = await tool.send_message(to="a@b.com", subject="x", body="y")
    assert out["id"] == "sent9"
    assert calls["http"] == 2


@pytest.mark.asyncio
async def test_non_401_error_is_not_retried():
    # A 500 is not an auth problem — do not refresh, do not retry; let it surface.
    calls = {"http": 0, "refresh": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["http"] += 1
        return httpx.Response(500, json={"error": "boom"})

    async def refresher() -> bool:
        calls["refresh"] += 1
        return True

    tool = GmailRestTool(
        access_token_provider=lambda: "at_123",
        transport=httpx.MockTransport(handler),
        token_refresher=refresher,
    )
    result = await tool.execute({"action": "list_messages"}, ctx=None)
    assert result.success is False
    assert calls["refresh"] == 0
    assert calls["http"] == 1


def test_tool_contract_shape():
    tool = GmailRestTool()
    assert tool.name == "gmail"
    assert tool.risk_tier == "ask"  # conservative static fallback; send is consequential
    assert "schema" in dir(tool)


# ----------------------------------------------------------------------
# Per-action risk (forensic 2026-06-19, session dc533e39): "Was habe ich
# heute auf dem Plan?" → morning-routine → gmail action=list_messages  # i18n-allow: simulated German user utterance, forensic quote
# (read) was forced through the ask-tier confirm and Jarvis spoke "Soll  # i18n-allow: verbatim quote of real German runtime voice output
# ich die E-Mail wirklich senden?". Only send_message is consequential;  # i18n-allow: verbatim quote of real German runtime voice output
# reads must stay safe so the morning briefing can check unread mail
# without a spurious send confirmation.
# ----------------------------------------------------------------------


def test_risk_tier_for_args_read_actions_are_safe():
    tool = GmailRestTool(access_token_provider=lambda: "x")
    assert tool.risk_tier_for_args({"action": "list_messages"}) == "safe"
    assert tool.risk_tier_for_args({"action": "get_message"}) == "safe"


def test_risk_tier_for_args_send_is_ask():
    tool = GmailRestTool(access_token_provider=lambda: "x")
    assert tool.risk_tier_for_args({"action": "send_message"}) == "ask"


def test_risk_tier_for_args_default_action_is_safe():
    # No action key → defaults to list_messages (a read) → safe.
    tool = GmailRestTool(access_token_provider=lambda: "x")
    assert tool.risk_tier_for_args({}) == "safe"


def test_risk_tier_for_args_unknown_action_is_conservative():
    # An unrecognised action stays conservative (ask), never silently safe.
    tool = GmailRestTool(access_token_provider=lambda: "x")
    assert tool.risk_tier_for_args({"action": "purge_everything"}) == "ask"


# ----------------------------------------------------------------------
# Read output must be SLIM, not raw MIME (live bug 2026-07-01 "Was steht
# alles in meinen E-Mails drin?"): get_message with format=full returns
# ~23k chars of raw headers (ARC-Seal, DKIM), full MIME tree and base64
# body per message. Feeding that into the model context slowed the turn to
# ~20 s and added no answer value. Project to sender/subject/date/snippet +
# a decoded, length-capped plain-text body.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_message_returns_slim_projection_not_raw_mime():
    body_text = "Hallo Ruben, hier ist der Kern der Nachricht. " * 5  # i18n-allow
    raw_body_b64 = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("ascii")
    fat = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["UNREAD", "INBOX"],
        "snippet": "Hallo Ruben, hier ist der Kern",  # i18n-allow
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Chef <chef@firma.de>"},
                {"name": "To", "value": "ruben@example.com"},
                {"name": "Subject", "value": "Quartalszahlen"},
                {"name": "Date", "value": "Wed, 01 Jul 2026 12:58:21 +0000"},
                {"name": "ARC-Seal", "value": "i=1; a=rsa-sha256; " + "A" * 4000},
                {"name": "DKIM-Signature", "value": "v=1; a=rsa-sha256; " + "B" * 4000},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": raw_body_b64}},
                {"mimeType": "text/html", "body": {"data": raw_body_b64}},
            ],
        },
    }

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fat)

    tool = GmailRestTool(
        access_token_provider=lambda: "at_123",
        transport=httpx.MockTransport(handler),
    )
    result = await tool.execute({"action": "get_message", "message_id": "m1"}, ctx=None)
    assert result.success is True
    out = result.output
    assert out["from"] == "Chef <chef@firma.de>"
    assert out["subject"] == "Quartalszahlen"
    assert out["date"].startswith("Wed, 01 Jul 2026")
    assert out["snippet"] == "Hallo Ruben, hier ist der Kern"  # i18n-allow
    assert "Kern der Nachricht" in out["body"]  # i18n-allow

    import json as _json

    serialized = _json.dumps(out)
    # The raw signature noise must be gone entirely.
    assert "ARC-Seal" not in serialized
    assert "DKIM-Signature" not in serialized
    assert "AAAA" not in serialized and "BBBB" not in serialized
    # And the projection is a fraction of the raw payload.
    assert len(serialized) < len(_json.dumps(fat)) // 2


@pytest.mark.asyncio
async def test_get_message_caps_a_long_body():
    long_body = "wort " * 6000  # ~30k chars decoded, above the body cap
    raw_body_b64 = base64.urlsafe_b64encode(long_body.encode("utf-8")).decode("ascii")
    fat = {
        "id": "m2",
        "threadId": "t2",
        "labelIds": ["INBOX"],
        "snippet": "x",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": "Long"}],
            "body": {"data": raw_body_b64},
        },
    }

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fat)

    tool = GmailRestTool(
        access_token_provider=lambda: "at_123",
        transport=httpx.MockTransport(handler),
    )
    result = await tool.execute({"action": "get_message", "message_id": "m2"}, ctx=None)
    assert result.success is True
    body = result.output["body"]
    assert len(body) <= _GMAIL_BODY_CHAR_CAP + 100  # cap + short truncation marker
    assert "truncated" in body


# ---- links to the mail in Gmail ----------------------------------------------


def _gmail(routes):
    import json

    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        for suffix, body in routes.items():
            if req.url.path.endswith(suffix):
                return httpx.Response(200, content=json.dumps(body))
        return httpx.Response(404, json={"error": {"code": 404}})

    tool = GmailRestTool(
        access_token_provider=lambda: "at_1", transport=httpx.MockTransport(handler)
    )
    return tool, seen


def test_a_link_opens_the_mail_in_the_right_account():
    from dodaios.plugins.tool.gmail_rest import gmail_web_link

    assert gmail_web_link("1a1d64c67c83436f", "me+tax@example.com") == (
        "https://mail.google.com/mail/?authuser=me%2Btax@example.com#all/1a1d64c67c83436f"
    )
    assert gmail_web_link("1a1d", None) == "https://mail.google.com/mail/u/0/#all/1a1d"


@pytest.mark.asyncio
async def test_a_sent_mail_comes_back_with_its_link():
    tool, seen = _gmail({
        "/messages/send": {"id": "m1", "threadId": "t1", "labelIds": ["SENT"]},
        "/profile": {"emailAddress": "me@example.com"},
    })
    result = await tool.execute({"action": "send_message", "to": "a@b.com", "body": "x"}, ctx=None)
    assert result.success
    assert result.output["url"] == "https://mail.google.com/mail/?authuser=me@example.com#all/t1"
    assert result.output["labelIds"] == ["SENT"]
    # The account is asked once, then remembered.
    await tool.execute({"action": "send_message", "to": "a@b.com", "body": "y"}, ctx=None)
    assert seen.count("/gmail/v1/users/me/profile") == 1


@pytest.mark.asyncio
async def test_found_and_read_mails_carry_their_links():
    headers = [{"name": "Subject", "value": "Hi"}]
    raw = {"id": "m2", "threadId": "t2", "payload": {"headers": headers}}
    tool, _seen = _gmail({
        "/messages": {"messages": [{"id": "m1", "threadId": "t1"}, {"id": "m3"}]},
        "/messages/m2": raw,
        "/profile": {"emailAddress": "me@example.com"},
    })
    listed = await tool.execute({"action": "list_messages", "query": "from:x"}, ctx=None)
    urls = [m["url"] for m in listed.output["messages"]]
    assert urls == [
        "https://mail.google.com/mail/?authuser=me@example.com#all/t1",
        "https://mail.google.com/mail/?authuser=me@example.com#all/m3",
    ]
    read = await tool.execute({"action": "get_message", "message_id": "m2"}, ctx=None)
    assert read.output["subject"] == "Hi"
    assert read.output["url"].endswith("#all/t2")


@pytest.mark.asyncio
async def test_without_the_account_the_link_opens_the_first_one():
    tool, seen = _gmail({"/messages/send": {"id": "m1", "threadId": "t1"}})
    result = await tool.execute({"action": "send_message", "to": "a@b.com", "body": "x"}, ctx=None)
    assert result.output["url"] == "https://mail.google.com/mail/u/0/#all/t1"
    await tool.execute({"action": "send_message", "to": "a@b.com", "body": "y"}, ctx=None)
    # A failed lookup is not repeated for every mail.
    assert seen.count("/gmail/v1/users/me/profile") == 1


@pytest.mark.asyncio
async def test_an_empty_search_needs_no_account_lookup():
    tool, seen = _gmail({"/messages": {"resultSizeEstimate": 0}})
    result = await tool.execute({"action": "list_messages", "query": "nothing"}, ctx=None)
    assert result.success and "messages" not in result.output
    assert "/gmail/v1/users/me/profile" not in seen
